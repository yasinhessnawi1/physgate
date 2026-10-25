"""What must hold before a module of the plan is recorded complete (ARCH-051).

Completion is a declaration, not work. Integration's accepted attempt names the modules it
declares complete, and a module is recorded complete only while every precondition here holds
for it. The preconditions are an ordered registry: each entry is a name and a function from the
run's state, as the lines before the completion line leave it, and the module, to why the
precondition is open, or ``None``. Replay asks the same registry for every completion line it
reads, so the writer and replay cannot disagree, and a line written past a precondition is
refused.

A later precondition joins as one more entry, and no entry here is edited for it. Because replay
asks the registry as it stands, and a completion line does not carry the names of the
preconditions it was held to (a forged line could otherwise name none), an entry must hold on
every run recorded before it existed: one that is open on an old run makes that run unreadable.
A test replays every recorded run that has a completion line, so such an entry fails there first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from physgate.orchestrator.events import IntegrationGateRan, IntegrationGateSkipped

if TYPE_CHECKING:
    from physgate.orchestrator.replay import RunState


@dataclass(frozen=True)
class Precondition:
    """One precondition of completion: its name, and why it is open for a module, or ``None``."""

    name: str
    open_reason: Callable[[RunState, str], str | None]


def _merged(state: RunState, module: str) -> str | None:
    """Every subtask planned in the module's directory merged: the module and each pass over it."""
    directory = state.subtasks[module].plan.module_dir
    waiting = [
        s
        for s in state.order
        if state.subtasks[s].plan.module_dir == directory and state.subtasks[s].status != "done"
    ]
    if waiting:
        return f"not every subtask planned in {directory} merged: {', '.join(waiting)}"
    return None


def _system_scope(state: RunState, module: str) -> str | None:
    """The system-scope result passed, or the gate is off and there is none (ARCH-080).

    Under ``on`` a failed result blocks, and the run ends escalated. Under ``observe`` it blocks
    no merge, and it still withholds completion: the result says the design fails, and completion
    is a declaration about the design. Under ``off`` the call is skipped, and completion has no
    system-scope precondition. A call that found the design incomplete, or no call, gave none.
    """
    call = state.integration
    if isinstance(call, IntegrationGateRan):
        if call.result.verdict == "pass":
            return None
        result = call.result
        return f"the system-scope result failed at {result.failing_check} in {result.mode}"
    if isinstance(call, IntegrationGateSkipped):
        return None if call.reason == "gate_mode=off" else f"the call was skipped: {call.reason}"
    return "no integration call is on the record"


#: Asked in this order, and every open entry is named. A later precondition is one more entry
#: here, and holds on every run recorded before it.
PRECONDITIONS: tuple[Precondition, ...] = (
    Precondition("merged", _merged),
    Precondition("system_scope", _system_scope),
)


def open_preconditions(state: RunState, module: str) -> tuple[tuple[str, str], ...]:
    """Every registered precondition open for ``module``, in the registry's order, with why.

    The registry is read on each call, so an entry added to it is asked from then on.
    """
    found: list[tuple[str, str]] = []
    for precondition in PRECONDITIONS:
        why = precondition.open_reason(state, module)
        if why is not None:
            found.append((precondition.name, why))
    return tuple(found)
