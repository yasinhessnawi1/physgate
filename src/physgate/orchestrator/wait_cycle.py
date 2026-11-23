"""A hold on a producer is let go when the producer can never end before the held subtask runs.

Two situations, in a run started under the ``wait_cycle`` mark (a run that acts on decisions):

* The producer waits for the held subtask. Its own next dispatch waits, through a chain, for the
  held subtask to end: the chain's links are a builder's wait for the designer that has not
  merged (the wait exists whether or not its line is written yet) and a reader's wait for a
  producer it is held on, or would be held on. The reader's hold on the producer would then wait
  for a subtask that waits for the reader: neither can run, and no person can lift either. The
  hold is let go as ``producer_waits_for_reader``, and where none stood none is written.
* The producer is held for good (:func:`physgate.orchestrator.design_wait.held_for_good`, the
  one definition): a builder whose designer ended without a merge, or whose designer is itself
  held for good, so it never ends. The hold is let go as ``producer_held_for_good``.

Which holds count as held for good is that definition's alone: a builder with an open hold whose
reason is ``ended_unmerged`` or ``designer_held``, and in a run that records only (where this rule
does not apply) one whose designer is with a person. A producer that waits for sizing's closing
pass is not held for good: it is let go by its own rule and comes back after the closing pass. A
wait on a person's item (a queue item, a sign-off, parts) ends in a person, never in a subtask, so
it is no link of a chain; nor is sizing's closing pass, which no pair or design names.

A run started under ``release_2`` opens a hold only on a producer with a person, so no hold is
owed in place of a release; but a hold already open is let go by both outcomes (a person's
decision takes its producer out of ``escalated`` and a retry, a fix or a reopen makes its next
dispatch wait): see :mod:`physgate.orchestrator.producer_wait`. A producer that is running or
about to run its retry is none of the two, and keeps its readers. What it adds is the end:
:func:`never_ran` names the subtasks that never ran, or whose ordered retry or fix never ran, and
the run ends as ``unrun`` instead of ``done``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.orchestrator import closing_wait, design_wait, producer_wait
from physgate.orchestrator.producer_wait import (
    _mutual,
    _reads_from,
    dispatch_due,
    let_go_key,
    root_item,
)

if TYPE_CHECKING:
    from physgate.orchestrator.events import ReleasedHow
    from physgate.orchestrator.replay import RunState


def waits_for(state: RunState, subtask_id: str) -> list[str]:
    """The subtasks whose end ``subtask_id``'s next dispatch waits for, in the recorded order.

    Only while its next dispatch is due: an attempt under way is let finish, and a subtask with a
    person waits for no subtask.
    """
    if not dispatch_due(state, subtask_id):
        return []
    found: list[str] = []
    for pair in design_wait._designers(state, subtask_id):  # noqa: SLF001 - the one reading of pairs
        if design_wait.standing(state, pair.designer) is not None:
            found.append(pair.designer)
    for read in _reads_from(state, subtask_id):
        producer = read.producer.subtask_id
        if _mutual(state, subtask_id, producer):
            continue
        if let_go_key(state, subtask_id, producer) in state.producer_waits.let_go:
            continue
        held = (subtask_id, producer) in state.producer_waits.open
        if held or root_item(state, producer, frozenset({subtask_id})) is not None:
            found.append(producer)
    return found


def reaches(state: RunState, start: str, target: str) -> bool:
    """Whether ``target`` is among what ``start`` waits for, directly or through a chain."""
    seen: set[str] = {start}
    todo = [start]
    while todo:
        for nxt in waits_for(state, todo.pop()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def letting_go(state: RunState, producer: str, reader: str) -> ReleasedHow | None:
    """How ``reader``'s hold on ``producer`` is let go by this rule now; ``None`` if it stands."""
    if reaches(state, producer, reader):
        return "producer_waits_for_reader"
    if design_wait.held_for_good(state, producer):
        return "producer_held_for_good"
    return None


def never_ran(state: RunState) -> list[dict[str, object]]:
    """The subtasks of a run that acts, started under ``release_2``, that never ran or ran no more.

    Two kinds, each with why, in the record's words, and the readers that merged without it:
    a subtask left ``planned`` with no attempt when nothing else is owed (a builder held for
    good), and one a person's decision ordered another attempt of (a retry, a fix, a reopen) that
    is a builder held for good and so never ran: "never ran" or "its ordered retry never ran".
    The key keeps its name for both. Integration's own subtask is the call's consequence, not a
    module, and is not named. Empty in a run that records only and in one started under the
    earlier rules, which end ``done`` as before; so are the ends that are not a run's own
    (a rejected plan, a recording-only run) and integration's subtask under ``gate_mode=off``.
    """
    if not (state.producer_waits.narrow and state.acts):
        return []
    found: list[dict[str, object]] = []
    for subtask_id in state.integrated():
        sub = state.subtasks[subtask_id]
        retry = sub.status == "active" and bool(sub.attempts) and dispatch_due(state, subtask_id)
        if not retry and (sub.status != "planned" or sub.attempts):
            continue
        if retry and not design_wait.held_for_good(state, subtask_id):
            continue
        held = next((h for (b, _), h in state.design_waits.open.items() if b == subtask_id), None)
        if held is None:
            why = "it was never dispatched"
        elif held.why == "designer_held":
            chain = ", ".join(held.chain or (held.designer,))
            why = f"it is held for good through {chain}, none of which can merge"
        elif held.why == "ended_unmerged":
            why = f"its designer {held.designer} ended without a merge"
        else:
            why = f"its designer {held.designer} had not merged"
        if retry:
            why = f"its ordered retry never ran: {why}"
        ran_without = [
            p.consumer.subtask_id
            for p in state.contract_pairs or ()
            if p.producer.subtask_id == subtask_id
            and state.subtasks[p.consumer.subtask_id].status == "done"
        ]
        found.append({"subtask_id": subtask_id, "why": why, "ran_without": ran_without})
    return found


def never_ran_at(state: RunState, step: str) -> list[dict[str, object]]:
    """What the end ``step`` names as never run.

    At ``unrun``, and at an ``escalated`` end that owes a sign-off: that end comes before
    ``unrun`` can, and would otherwise hide a module that never ran until the sign-off is
    decided. Empty at every other step.
    """
    if step == "unrun" or (step == "escalated" and state.sign_offs_open()):
        return never_ran(state)
    return []


def items_open(state: RunState) -> list[str]:
    """Every item a person can still act on, from the record: undecided, or held to be confirmed.

    The plan's and a part's items, a subtask's, a failed contract's, a sign-off's and integration's.
    """
    found: list[str] = []
    for one in (state.plan_hold(), state.parts_hold()):
        if one is not None:
            found.append(one)
    for sub in state.subtasks.values():
        item = producer_wait.waiting_item(state, sub.plan.subtask_id)
        if item is not None:
            found.append(item)
    found += [i for i in state.contract_items if state.undecided(i)]
    found += [i for i in state.sign_offs if state.undecided(i)]
    esc = state.integration_escalated
    if esc is not None and state.undecided(esc.item_id):
        found.append(esc.item_id)
    return found


def held_on(state: RunState) -> list[str]:
    """What is held on what now, one phrase each, in plan order: for a run that waits on nothing."""
    words: list[str] = []
    for (reader, producer), _hold in state.producer_waits.open.items():
        words.append(f"{reader} is held on {producer}, which it reads from")
    for (builder, designer), held in state.design_waits.open.items():
        words.append(f"{builder} is held on {designer}, whose design it builds ({held.why})")
    for one in state.order:
        if closing_wait.waits(state, one):
            names = ", ".join(closing_wait.pending(state, one))
            words.append(f"{one}, sizing's closing pass, waits for {names}")
    for one in state.integrated():
        sub = state.subtasks[one]
        if sub.status in ("planned", "active"):
            words.append(f"{one} is {sub.status}")
    return words
