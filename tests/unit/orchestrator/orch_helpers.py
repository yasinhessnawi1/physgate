"""Builders shared by the orchestrator's tests."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from physgate.orchestrator.cli import _harness_root
from physgate.orchestrator.protocols import (
    CHECK_NUMBERS,
    CheckRecord,
    MagnitudeDetails,
    NumericOutput,
    PassDetails,
    PowerDetails,
    RunningGateMode,
)
from physgate.orchestrator.run_config import (
    HarnessState,
    ModelStrings,
    RunBounds,
    RunConfig,
    harness_state,
)

SCRIPTED_BOUNDS = RunBounds(
    binary_max_retries=0,
    session_wall_clock_s=120.0,
    session_max_turns=20,
    infra_retry_delays_s=(),
)

#: A clean checkout at a commit, for tests about the harness record itself.
CLEAN_HARNESS = HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None)


#: The harness as the command measures it, taken once at import (before any test
#: narrows ``PATH``): a run a test drives under another record is refused.
MEASURED_HARNESS = harness_state(_harness_root())


def make_config(**overrides: Any) -> RunConfig:
    """A complete, valid run configuration, with any field replaced."""
    fields: dict[str, Any] = {
        "run_id": "run-1",
        "seed": 7,
        "brief_sha256": "a" * 64,
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"electrical": "claude-sonnet-5"},
            reviewers={"electrical": "claude-opus-5-5"},
        ),
        "bounds": SCRIPTED_BOUNDS,
        "token_ceiling": 100_000,
        "claude_version": "2.1.272",
        "target_head": "b" * 40,
        "endpoint": "default",
        "auth": "api_key",
        "reportable": False,
        "harness": MEASURED_HARNESS,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
        "role_python": None,
    }
    fields.update(overrides)
    return RunConfig(**fields)


def ticking_clock(start: datetime | None = None) -> Callable[[], datetime]:
    """A clock that moves one millisecond per call, so timestamps are deterministic."""
    base = start or datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    counter: Iterator[int] = itertools.count()
    return lambda: base + timedelta(milliseconds=next(counter))


def gate_records(mode: RunningGateMode, failing: str | None) -> tuple[CheckRecord, ...]:
    """The check records a gate result carries: one pass, or one blocking failure.

    ``failing`` is ``magnitude`` or ``power``, the two checks these tests fail with.
    """
    if failing is None:
        return (
            CheckRecord(
                check=1,
                name="units",
                scope="subtask",
                outcome="pass",
                blocking=True,
                node=None,
                module=None,
                value=None,
                expected=None,
                tool="test",
                message="every unit is consistent",
                gate_mode=mode,
                details=PassDetails(evaluated=1),
            ),
        )
    details: MagnitudeDetails | PowerDetails
    if failing == "magnitude":
        amps = NumericOutput(value=3.4, unit="A")
        details = MagnitudeDetails(
            value=amps,
            low=NumericOutput(value=0.36, unit="A"),
            high=NumericOutput(value=2.0, unit="A"),
            source="a test table",
            table_sha256="0" * 64,
        )
    else:
        details = PowerDetails(
            deficit=NumericOutput(value=1.25, unit="W"), contributing=("power.budget",)
        )
    return (
        CheckRecord(
            check=CHECK_NUMBERS[failing],
            name=failing,  # type: ignore[arg-type]
            scope="subtask" if failing == "magnitude" else "module",
            outcome="fail",
            blocking=True,
            node="motor.left" if failing == "magnitude" else "power.budget",
            module=None,
            value=None,
            expected=None,
            tool="test",
            message="a test failure",
            gate_mode=mode,
            details=details,
        ),
    )
