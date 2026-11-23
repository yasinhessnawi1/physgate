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

A run started under ``release_2`` has none of this: it holds a reader only on a producer that is
itself with a person, so no cycle can form and neither outcome can be owed (a builder held for
good is planned, never escalated, so no hold is ever open on one). :func:`letting_go` answers
``None`` there. What it adds is the end: :func:`never_ran` names the subtasks that never ran, and
the run ends as ``unrun`` instead of ``done``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.orchestrator import design_wait
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
    if state.producer_waits.narrow:
        return None
    if reaches(state, producer, reader):
        return "producer_waits_for_reader"
    if design_wait.held_for_good(state, producer):
        return "producer_held_for_good"
    return None


def never_ran(state: RunState) -> list[dict[str, object]]:
    """The subtasks of a run that acts, started under ``release_2``, that never ran.

    A subtask left ``planned`` with no attempt when nothing else is owed (integration's own
    subtask is the call's consequence, not a module, and is not named): a builder held for good.
    Each with why, in the record's words, and the readers that merged without it. Empty in a run
    that records only and in one started under the earlier rules, which end ``done`` as before.
    """
    if not (state.producer_waits.narrow and state.acts):
        return []
    found: list[dict[str, object]] = []
    for subtask_id in state.integrated():
        sub = state.subtasks[subtask_id]
        if sub.status != "planned" or sub.attempts:
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
        ran_without = [
            p.consumer.subtask_id
            for p in state.contract_pairs or ()
            if p.producer.subtask_id == subtask_id
            and state.subtasks[p.consumer.subtask_id].status == "done"
        ]
        found.append({"subtask_id": subtask_id, "why": why, "ran_without": ran_without})
    return found
