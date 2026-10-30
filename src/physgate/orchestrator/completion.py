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


def _contract(state: RunState, module: str) -> str | None:
    """The latest contract result of every pair the module takes part in passed (ARCH-051).

    The latest result is current: a merge in either module of a pair owes a retest before anything
    else is dispatched. A pair with no result, or whose latest result failed, withholds completion
    from both of its modules, whatever was decided about it. A run that records no contract pairs,
    as every run recorded before they existed, has none to hold.
    """
    found: list[str] = []
    for pair in state.contract_pairs or ():
        if module not in (pair.producer.subtask_id, pair.consumer.subtask_id):
            continue
        latest = state.latest_contract(pair)
        if latest is None or latest.result.outcome != "pass":
            why = "no contract result" if latest is None else "its latest contract result failed"
            found.append(f"{pair.producer.module} to {pair.consumer.module}: {why}")
    return "; ".join(found) or None


def _open_item(state: RunState, module: str) -> str | None:
    """No item about a failed contract of a pair the module takes part in is undecided.

    In either mode: a decision recorded in a run that acts on none still closes the item, and a
    held one not yet confirmed does not. A run that raised no contract item, as every run recorded
    before they existed, has none open.
    """
    found: list[str] = []
    for item_id in state.contract_items:
        pair = state.pair_of(item_id)
        if module in (pair.producer.subtask_id, pair.consumer.subtask_id) and state.undecided(
            item_id
        ):
            about = f"{pair.producer.module} to {pair.consumer.module}"
            found.append(f"queue item {item_id} about {about} has no decision taken")
    return "; ".join(found) or None


#: Asked in this order, and every open entry is named. A later precondition is one more entry
#: here, and holds on every run recorded before it.
PRECONDITIONS: tuple[Precondition, ...] = (
    Precondition("merged", _merged),
    Precondition("system_scope", _system_scope),
    Precondition("contract", _contract),
    Precondition("open_item", _open_item),
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
