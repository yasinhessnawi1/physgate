"""Sizing's closing pass is not dispatched while a domain module before it is still to settle.

The closing pass is placed after every domain module and reads every sizing node again with the
nodes it constrains and those that constrain it, as the graph holds them then. Dispatched while a
domain module has not merged, it judges a graph that lacks that module's work. So a dispatch of
the closing pass, its first or a later attempt's, waits while a domain module of the plan before
it is pending: planned or running and not held for good, or with a person on an item nobody has
decided. The run waits on the queue, or goes on with whatever else is free, and the closing pass
goes ahead once each such module merged or ended without a merge.

Not waited for: a module that waits for the closing pass itself (a person chose its producer's
value, and its attempt returns once the closing pass merged), and a builder held on the design of
such a module, directly or through a chain of builders, which cannot run before the closing pass
either. A sign-off a merged module owes is not waited for: it is asked after the follow-ups, which
can change the values it binds, and the closing pass reads the graph, not a signature. A module
reopened for a sign-off's fix is not merged, so the closing pass waits for it.

No line is written for the wait: the step is the wait the run already takes, and the status names
the closing pass with the modules it waits for.

Only in a run that acts on decisions and was started under the rule (its first line says so): in
a run that records only, a module with a person has ended there. A run recorded before the rule
replays as it did; a run started under it has its replay refuse a closing pass dispatched while a
module is pending.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from physgate.orchestrator.design_wait import _designers, held_for_good
from physgate.orchestrator.producer_wait import dispatch_due, waiting_item

if TYPE_CHECKING:
    from physgate.orchestrator.replay import RunState


def is_closing(state: RunState, subtask_id: str) -> bool:
    """Whether ``subtask_id`` is planned in a module directory an earlier subtask holds."""
    seen: set[str] = set()
    for one in state.integrated():
        directory = state.subtasks[one].plan.module_dir
        if one == subtask_id:
            return directory in seen
        seen.add(directory)
    return False


def _domains(state: RunState, closing: str) -> list[str]:
    """The subtasks before ``closing`` in plan order that are of another role than its own."""
    role = state.subtasks[closing].plan.assigned_role
    found: list[str] = []
    for one in state.integrated():
        if one == closing:
            break
        if state.subtasks[one].plan.assigned_role != role:
            found.append(one)
    return found


def _stuck_on_closing(state: RunState, subtask_id: str, seen: frozenset[str] = frozenset()) -> bool:
    """Whether ``subtask_id`` cannot go on before the closing pass.

    It waits for the closing pass itself, or builds the design of a module that cannot go on.
    """
    sub = state.subtasks[subtask_id]
    if sub.status == "waiting":
        return True
    if sub.status not in ("planned", "active") or subtask_id in seen:
        return False
    return any(
        _stuck_on_closing(state, pair.designer, seen | {subtask_id})
        for pair in _designers(state, subtask_id)
    )


def _is_pending(state: RunState, subtask_id: str) -> bool:
    sub = state.subtasks[subtask_id]
    if sub.status == "escalated":
        return waiting_item(state, subtask_id) is not None
    if sub.status in ("planned", "active"):
        return not held_for_good(state, subtask_id) and not _stuck_on_closing(state, subtask_id)
    return False


def pending(state: RunState, closing: str) -> list[str]:
    """The domain modules ``closing`` waits for now, in plan order; empty when it waits for none."""
    return [one for one in _domains(state, closing) if _is_pending(state, one)]


def waits(state: RunState, subtask_id: str) -> bool:
    """Whether ``subtask_id`` is a closing pass whose next dispatch waits for a domain module."""
    return (
        state.acts
        and state.closing_wait
        and is_closing(state, subtask_id)
        and dispatch_due(state, subtask_id)
        and bool(pending(state, subtask_id))
    )


def held_dispatch(state: RunState, subtask_id: str) -> str | None:
    """Why ``subtask_id`` cannot be dispatched now as a closing pass, or ``None``."""
    if not waits(state, subtask_id):
        return None
    names = ", ".join(repr(one) for one in pending(state, subtask_id))
    return (
        f"{subtask_id!r}, sizing's closing pass, is dispatched while {names} has neither merged "
        "nor ended without a merge"
    )


def closing_waits(state: RunState) -> dict[str, list[dict[str, object]]]:
    """Each closing pass held now with the modules it waits for, as the status prints them.

    ``{"closing_waits": [...]}``, or nothing where none is held, so every other run prints as it
    always has.
    """
    held: list[dict[str, object]] = [
        {"subtask_id": one, "pending": pending(state, one)}
        for one in state.order
        if waits(state, one)
    ]
    return {"closing_waits": held} if held else {}
