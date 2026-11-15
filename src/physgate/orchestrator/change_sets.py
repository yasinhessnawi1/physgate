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

from physgate.orchestrator.events import Decomposed, Event, PartsWriteDone, WriteDone
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


def integration_history(events: Iterable[Event]) -> tuple[int, tuple[ChangeSet, ...]]:
    """The history the system-scope call is told: :func:`change_history`, with declared parts given.

    A run that asks which parts a person has writes each part a person has or makes before any
    session runs (ARCH-122): at the revisions straight above decomposition's head, below every
    attempt's, and named by no attempt. Like decomposition's interface nodes they are the design
    the attempts were given, fixed before any role read it, so the baseline is the last of them
    and every attempt's writes are named exactly as :func:`change_history` names them. Every check
    still reads the declared nodes, at their latest revision, in the whole graph. A parts write
    after an attempt's write is given nothing: the history then leaves it unnamed, and the gate
    refuses it (replay refuses such a log before that). A run that wrote no part is told what
    :func:`change_history` says.
    """
    listed = list(events)
    baseline, change_sets = change_history(listed)
    for event in listed:
        # Only a write straight above the given design extends it: an attempt's write between
        # them takes the next revision, and a part written after it is no longer adjacent.
        if isinstance(event, PartsWriteDone) and event.revision == baseline + 1:
            baseline = event.revision
    return baseline, change_sets
