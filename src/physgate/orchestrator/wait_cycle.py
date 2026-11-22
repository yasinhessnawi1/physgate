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
    if reaches(state, producer, reader):
        return "producer_waits_for_reader"
    if design_wait.held_for_good(state, producer):
        return "producer_held_for_good"
    return None
