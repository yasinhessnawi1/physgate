"""The repair budget, and the failures that are not the agent's.

Three implementation attempts, then the approval queue (ARCH-030). Only a
**rejected** attempt spends from the budget: the gate, the reviewer, the
write-scope check or the store refused what the agent produced. An API error,
a session stopped at its wall clock, a hit turn limit, a session that died
without a result: those are **infrastructure** outcomes, they spend nothing, and
each carries its cause. An overloaded endpoint must never read as a subtask
exhausting its repair budget, because that number is a measured risk.

How a session ended is read from the binary's result object by ``is_error`` and
``terminal_reason``, never by ``subtype``: an HTTP 529 was measured to end with
``subtype: "success"`` and ``is_error: true``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from physgate.orchestrator.exceptions import RepairBudgetExhaustedError

#: Implementation attempts per subtask before it goes to the approval queue (ARCH-030).
REPAIR_BUDGET = 3

#: Why a session is an infrastructure outcome. Each is recorded, so an experiment
#: can decide for itself how to count one (a turn limit may be an agent looping).
InfraCause = Literal["api_error", "wall_clock", "turn_limit", "no_result", "unexpected_exit"]


class SessionEnd(BaseModel):
    """How one session ended, as far as the budget is concerned."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    outcome: Literal["completed", "infrastructure"]
    cause: InfraCause | None

    @model_validator(mode="after")
    def _infrastructure_has_a_cause(self) -> SessionEnd:
        if (self.outcome == "infrastructure") != (self.cause is not None):
            msg = "an infrastructure outcome carries its cause, and a completed one none"
            raise ValueError(msg)
        return self


def classify_session_end(
    result: Mapping[str, object] | None,
    *,
    exit_code: int | None,
    stopped_at_wall_clock: bool,
) -> SessionEnd:
    """Classify how a session ended from its result object and exit.

    Args:
        result: the binary's final ``result`` object, or ``None`` if the stream
            ended without one (a killed or crashed session).
        exit_code: the process's exit status, ``None`` if it was never reaped.
        stopped_at_wall_clock: the orchestrator stopped it at its wall clock.
    """
    if stopped_at_wall_clock:
        return SessionEnd(outcome="infrastructure", cause="wall_clock")
    if result is None:
        return SessionEnd(outcome="infrastructure", cause="no_result")
    terminal = result.get("terminal_reason")
    is_error = result.get("is_error")
    if terminal == "max_turns":
        return SessionEnd(outcome="infrastructure", cause="turn_limit")
    if is_error is True and terminal == "api_error":
        return SessionEnd(outcome="infrastructure", cause="api_error")
    if is_error is False and terminal == "completed" and exit_code == 0:
        return SessionEnd(outcome="completed", cause=None)
    return SessionEnd(outcome="infrastructure", cause="unexpected_exit")


def require_within_budget(attempt: int) -> int:
    """Return ``attempt`` if the budget allows it to exist.

    Raises:
        RepairBudgetExhaustedError: it is below one or past the budget. A fourth
            attempt is not something the loop can reach.
    """
    if not 1 <= attempt <= REPAIR_BUDGET:
        msg = "the repair budget allows no such attempt"
        raise RepairBudgetExhaustedError(msg, attempt=str(attempt), budget=str(REPAIR_BUDGET))
    return attempt


def after_rejection(attempt: int) -> int | None:
    """The next attempt's number after ``attempt`` was rejected, or ``None`` to escalate."""
    require_within_budget(attempt)
    return None if attempt == REPAIR_BUDGET else attempt + 1


def infra_retry_delay(delays: tuple[float, ...], retries_done: int) -> float | None:
    """How long to wait before the next infrastructure retry, or ``None`` if spent.

    The schedule is a required run parameter; its length is the number of
    retries. Every retry is the same attempt with a fresh session, and none of
    them touches the repair budget.
    """
    return delays[retries_done] if 0 <= retries_done < len(delays) else None
