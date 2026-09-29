"""Run-event logs built by hand, line by line, for the catch-accounting tests.

Each log is one run in one gate mode. The lines are real event models, so every
field the derivation reads is validated as the loop's own lines are, but their
order is whatever the test writes: the point is to know every verdict in advance.
"""

from __future__ import annotations

from typing import Any

from physgate.orchestrator.events import (
    Event,
    GateRan,
    IntegrationGateRan,
    Resumed,
    ReviewRan,
    SessionEnded,
    WriteDone,
)
from physgate.orchestrator.protocols import (
    CheckRecord,
    GateResult,
    MagnitudeDetails,
    NumericOutput,
    PassDetails,
    PropagationDetails,
    ReviewResult,
    RunningGateMode,
    Scope,
    Verdict,
)

TS = "2026-09-27T12:00:00.000000Z"


class Log:
    """A run-event log built line by line, each with the next sequence number."""

    def __init__(
        self,
        run_id: str = "run-1",
        mode: RunningGateMode = "observe",
        ts: str = TS,
        manifest_id: str = "e" * 64,
    ) -> None:
        self.lines: list[Event] = []
        self.run_id, self.mode, self.ts = run_id, mode, ts
        self.manifest_id = manifest_id

    def env(self) -> dict[str, Any]:
        return {
            "seq": len(self.lines),
            "ts": self.ts,
            "run_id": self.run_id,
            "gate_mode": self.mode,
        }

    def gate(
        self, subtask: str, attempt: int, *, fails: bool = True, node: str = "motor.left"
    ) -> GateRan:
        checks = (
            (record("fail", node, mode=self.mode),)
            if fails
            else (record("pass", None, mode=self.mode),)
        )
        line = GateRan(
            **self.env(), subtask_id=subtask, attempt=attempt, result=result(checks, self.mode)
        )
        self.lines.append(line)
        return line

    def integration(self, *records: CheckRecord) -> IntegrationGateRan:
        line = IntegrationGateRan(**self.env(), result=result(records, self.mode))
        self.lines.append(line)
        return line

    def review(self, subtask: str, attempt: int, verdict: Verdict) -> ReviewRan:
        line = ReviewRan(
            **self.env(),
            subtask_id=subtask,
            attempt=attempt,
            result=ReviewResult(
                verdict=verdict,
                finding="reviewed",
                reviewer_model="claude-opus-5-5",
                session_id=f"rev-{len(self.lines)}",
                usage=(),
            ),
        )
        self.lines.append(line)
        return line

    def resumed(self, subtask: str, attempt: int) -> None:
        self.lines.append(
            Resumed(**self.env(), subtask_id=subtask, attempt=attempt, point="verify_reading")
        )

    def session(self, subtask: str, attempt: int) -> None:
        self.lines.append(
            SessionEnded(
                **self.env(),
                subtask_id=subtask,
                attempt=attempt,
                session_id=f"role-{len(self.lines)}",
                outcome="completed",
                cause=None,
                attempt_commit="a" * 40,
                trajectory="/t",
                worktree="/w",
                reading_verified=True,
            )
        )

    def wrote(self, subtask: str, attempt: int, node: str, revision: int) -> None:
        self.lines.append(
            WriteDone(
                **self.env(), subtask_id=subtask, attempt=attempt, node_id=node, revision=revision
            )
        )


def record(
    outcome: str,
    node: str | None,
    name: str = "magnitude",
    *,
    scope: Scope = "subtask",
    mode: RunningGateMode = "observe",
) -> CheckRecord:
    """A pass, a magnitude failure, or a propagation failure, at ``scope``."""
    if outcome == "pass":
        return CheckRecord(
            check=2,
            name="magnitude",
            scope=scope,
            outcome="pass",
            blocking=True,
            node=None,
            module=None,
            value=None,
            expected=None,
            tool="t",
            message="fine",
            gate_mode=mode,
            details=PassDetails(evaluated=1),
        )
    if name == "propagation":
        return CheckRecord(
            check=7,
            name="propagation",
            scope="system",
            outcome="fail",
            blocking=True,
            node=node,
            module=None,
            value=None,
            expected=None,
            tool="t",
            message="unwritten",
            gate_mode=mode,
            details=PropagationDetails(unwritten=(f"{node}->power.budget",)),
        )
    amps = NumericOutput(value=240, unit="A")
    return CheckRecord(
        check=2,
        name="magnitude",
        scope=scope,
        outcome="fail",
        blocking=True,
        node=node,
        module=None,
        value=amps,
        expected="0.36 A to 6.5 A",
        tool="t",
        message="implausible",
        gate_mode=mode,
        details=MagnitudeDetails(
            value=amps,
            low=NumericOutput(value=0.36, unit="A"),
            high=NumericOutput(value=6.5, unit="A"),
            source="s",
            table_sha256="d" * 64,
        ),
    )


def result(checks: tuple[CheckRecord, ...], mode: RunningGateMode) -> GateResult:
    """The gate result the records add up to."""
    blocking = [r for r in checks if r.outcome == "fail" and r.blocking]
    verdict: Verdict = "fail" if blocking else "pass"
    return GateResult(
        verdict=verdict,
        mode=mode,
        finding="judged",
        failing_check=blocking[0].name if blocking else None,
        numeric_output=None,
        quantities=(),
        checks=checks,
        catalogue_sha256="c" * 64,
    )
