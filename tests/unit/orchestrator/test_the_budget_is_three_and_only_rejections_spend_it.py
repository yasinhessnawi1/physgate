"""The repair budget stops at three; infrastructure failures never spend from it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from physgate.orchestrator.budget import (
    SessionEnd,
    after_rejection,
    classify_session_end,
    infra_retry_delay,
    require_within_budget,
)
from physgate.orchestrator.exceptions import RepairBudgetExhaustedError


def test_three_rejections_and_the_subtask_escalates_with_no_fourth_attempt() -> None:
    attempts = [1]
    while (following := after_rejection(attempts[-1])) is not None:
        attempts.append(following)
    assert attempts == [1, 2, 3]
    with pytest.raises(RepairBudgetExhaustedError):
        require_within_budget(4)
    with pytest.raises(RepairBudgetExhaustedError):
        after_rejection(4)
    with pytest.raises(RepairBudgetExhaustedError):
        require_within_budget(0)


# The binary's result objects as measured on 2.1.272 against the scripted endpoint.
COMPLETED = {"subtype": "success", "is_error": False, "terminal_reason": "completed"}
MAX_TURNS = {"subtype": "error_max_turns", "is_error": True, "terminal_reason": "max_turns"}
OVERLOADED = {
    "subtype": "success",
    "is_error": True,
    "terminal_reason": "api_error",
    "api_error_status": 529,
}
INTERRUPTED = {"subtype": "error_during_execution", "is_error": True}

CASES: list[tuple[str, dict[str, object] | None, int | None, bool, SessionEnd]] = [
    ("a clean finish", COMPLETED, 0, False, SessionEnd(outcome="completed", cause=None)),
    (
        "a hit turn limit",
        MAX_TURNS,
        1,
        False,
        SessionEnd(outcome="infrastructure", cause="turn_limit"),
    ),
    ("an HTTP 529", OVERLOADED, 1, False, SessionEnd(outcome="infrastructure", cause="api_error")),
    (
        "stopped at the wall clock",
        COMPLETED,
        0,
        True,
        SessionEnd(outcome="infrastructure", cause="wall_clock"),
    ),
    ("killed, no result", None, -9, False, SessionEnd(outcome="infrastructure", cause="no_result")),
    (
        "interrupted",
        INTERRUPTED,
        0,
        False,
        SessionEnd(outcome="infrastructure", cause="unexpected_exit"),
    ),
    (
        "completed but a non-zero exit",
        COMPLETED,
        1,
        False,
        SessionEnd(outcome="infrastructure", cause="unexpected_exit"),
    ),
]


@pytest.mark.parametrize(
    ("result", "exit_code", "wall_clock", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_how_a_session_ended_is_read_from_is_error_and_terminal_reason(
    result: dict[str, object] | None, exit_code: int | None, wall_clock: bool, expected: SessionEnd
) -> None:
    got = classify_session_end(result, exit_code=exit_code, stopped_at_wall_clock=wall_clock)
    assert got == expected


def test_a_success_subtype_with_an_error_is_never_a_completed_session() -> None:
    measured = {"subtype": "success", "is_error": True, "terminal_reason": "api_error"}
    assert classify_session_end(measured, exit_code=1, stopped_at_wall_clock=False).outcome == (
        "infrastructure"
    )


def test_an_infrastructure_outcome_always_carries_its_cause() -> None:
    with pytest.raises(ValidationError):
        SessionEnd(outcome="infrastructure", cause=None)
    with pytest.raises(ValidationError):
        SessionEnd(outcome="completed", cause="api_error")


def test_the_infrastructure_schedule_is_the_run_parameter_and_then_stops() -> None:
    assert [infra_retry_delay((60.0, 300.0), n) for n in range(4)] == [60.0, 300.0, None, None]
    assert infra_retry_delay((), 0) is None
    assert infra_retry_delay((60.0,), -1) is None
