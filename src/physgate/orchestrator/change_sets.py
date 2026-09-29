"""What changed together in a run, and in what order, read from the run-event log alone.

The propagation check asks of every node whose quantities changed whether the
nodes it constrains were rewritten "in the same commit" or later (ARCH-082).
In this system a commit of the design is one merged attempt, because a role
writes only the nodes it owns: a motor and the current budget it constrains
belong to different roles, and cannot change in one attempt. So the unit the
check judges in is the attempt, and its order is the order attempts were
applied.

Both are on the durable record. Decomposition records the journal's head when
the design began, and every canonical write after it has a ``write_done`` line
naming its subtask, its attempt and its revision; a journal line with no such
line halts the run. Deriving the history from the log, rather than from the
running loop's memory, means a fresh process after a kill derives the same one.
"""

from __future__ import annotations

from collections.abc import Iterable

from physgate.orchestrator.events import Decomposed, Event, WriteDone
from physgate.orchestrator.protocols import ChangeSet


def change_history(events: Iterable[Event]) -> tuple[int, tuple[ChangeSet, ...]]:
    """The baseline revision, and every later revision grouped by the attempt that wrote it.

    The baseline is the journal head decomposition recorded, or 0 for a run that
    began without one. The change sets come in the order their first revision was
    written, each with its revisions in order.
    """
    baseline = 0
    grouped: dict[tuple[str, int], list[int]] = {}
    for event in events:
        if isinstance(event, Decomposed):
            baseline = event.head_revision
        elif isinstance(event, WriteDone):
            grouped.setdefault((event.subtask_id, event.attempt), []).append(event.revision)
    ordered = sorted(grouped.items(), key=lambda item: min(item[1]))
    return baseline, tuple(
        ChangeSet(subtask_id=subtask, attempt=attempt, revisions=tuple(sorted(revisions)))
        for (subtask, attempt), revisions in ordered
    )
