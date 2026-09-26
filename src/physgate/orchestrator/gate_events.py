"""The catch-accounting events: one per gate check, derived from the run-event log.

The architecture asks every gate event to log the check, the value, the node, the
module, and whether the paired reviewer had passed the work (ARCH-083). The gate
writes all of one call's checks inside one line, so a killed process can never
leave half of them on the record; this module derives one event per check from
those lines, the way the task ledger is derived from the same log. Nothing here
writes, so a later reader changes what it derives, never what was recorded.

``reviewer_had_passed`` is present and empty. The gate runs before the reviewer,
so the gate cannot know it; the reader that counts catches fills it from the same
attempt's review line. The integration call's events belong to no subtask and are
named ``integration``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.orchestrator.common import NonEmptyStr, Timestamp
from physgate.orchestrator.events import Event, GateRan, IntegrationGateRan
from physgate.orchestrator.protocols import (
    CheckName,
    NumericOutput,
    Outcome,
    RunningGateMode,
    Scope,
)
from physgate.orchestrator.queue import INTEGRATION


class GateEvent(BaseModel):
    """One check of one gate call, with the fields catch accounting counts."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: NonEmptyStr
    #: The sequence number of the gate line this event came from.
    seq: Annotated[int, Field(ge=0)]
    ts: Timestamp
    gate_mode: RunningGateMode
    #: The subtask, or ``integration`` for the integration call.
    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1)] | None
    check: Annotated[int, Field(ge=1, le=7)]
    name: CheckName
    scope: Scope
    outcome: Outcome
    blocking: bool
    value: NumericOutput | None
    node: NonEmptyStr | None
    module: NonEmptyStr | None
    catalogue_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    reviewer_had_passed: None = None


def gate_events(events: Iterable[Event]) -> list[GateEvent]:
    """One event per check record in every gate line of ``events``, in log order."""
    found: list[GateEvent] = []
    for event in events:
        if isinstance(event, GateRan):
            subtask, attempt = event.subtask_id, event.attempt
        elif isinstance(event, IntegrationGateRan):
            subtask, attempt = INTEGRATION, None
        else:
            continue
        found.extend(
            GateEvent(
                run_id=event.run_id,
                seq=event.seq,
                ts=event.ts,
                gate_mode=event.result.mode,
                subtask_id=subtask,
                attempt=attempt,
                check=record.check,
                name=record.name,
                scope=record.scope,
                outcome=record.outcome,
                blocking=record.blocking,
                value=record.value,
                node=record.node,
                module=record.module,
                catalogue_sha256=event.result.catalogue_sha256,
                reviewer_had_passed=record.reviewer_had_passed,
            )
            for record in event.result.checks
        )
    return found
