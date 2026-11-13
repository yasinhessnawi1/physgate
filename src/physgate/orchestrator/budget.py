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

import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from physgate.lines import split_lines
from physgate.orchestrator.exceptions import RepairBudgetExhaustedError

#: Implementation attempts per subtask before it goes to the approval queue (ARCH-030).
REPAIR_BUDGET = 3

#: The highest attempt number a subtask can reach: the repair budget, and the one fix a person
#: may order after a review that blocked (ARCH-133), which is outside the budget and always the
#: subtask's last attempt. Every bound on an attempt number is this one; the replay holds an
#: attempt past the budget to being that fix.
ATTEMPT_LIMIT = REPAIR_BUDGET + 1

#: Why a session is an infrastructure outcome. Each is recorded, so an experiment
#: can decide for itself how to count one (a turn limit may be an agent looping).
#: ``credential_refused`` is an API error with HTTP 401 or 403: retrying cannot fix a
#: refused credential, so the loop halts on it for a person to replace it.
#: ``sandbox_unavailable``: the session refused to start because the OS layer it was
#: started with could not run; retrying cannot fix that either, so the loop halts.
#: ``disk_full``: the session ended as a finished one, the binary then said a full disk,
#: or a used-up quota, lost the session's own records, and the harness measured the volume
#: holding them as full; nothing it did is taken, it is not retried, and the loop halts.
InfraCause = Literal[
    "api_error",
    "credential_refused",
    "sandbox_unavailable",
    "disk_full",
    "prompt_too_long",
    "structured_output_retry_exhausted",
    "wall_clock",
    "turn_limit",
    "no_result",
    "unexpected_exit",
]

#: How the binary names a sandbox it was told it must have and could not start
#: (measured on 2.1.301 on Linux without bubblewrap: exit 1, before any request).
SANDBOX_UNAVAILABLE = "Sandbox required but unavailable"

#: The result's ``terminal_reason`` when a request outgrew the window (measured).
PROMPT_TOO_LONG = "prompt_too_long"
#: The result's ``terminal_reason`` when the binary's own cap on refused structured
#: answers (five, on both binaries) ended the session: every refusal before it was told
#: to the session, so a fresh one would repeat it (measured on both binaries).
STRUCTURED_OUTPUT_EXHAUSTED = "structured_output_retry_exhausted"

#: The pins on which those two ends are a cause of their own outside a review. On the
#: earlier pins they stay the cause every end without a name of its own gets, so what
#: those pins' runs record is what it was.
NAMED_END_VERSIONS = frozenset({"2.1.322"})

#: The HTTP statuses the binary reports for a credential the API refused.
CREDENTIAL_REFUSED_STATUSES = frozenset({401, 403})

#: The event the binary writes after its result when a full disk, or a used-up quota, lost
#: lines of the session's own transcript or changes to its own configuration. Measured on
#: 2.1.322 with the transcripts on a full volume: the result says ``completed``, the exit
#: status is 0, and this event follows. 2.1.301 loses the same writes and says nothing.
WRITES_LOST = "session_writes_lost"

#: The pins measured to write that event. On any other, nothing after a result is the binary's.
WRITES_LOST_VERSIONS = frozenset({"2.1.322"})

#: Free space, measured by the harness on the volumes holding a session's own records when
#: it ended, below which those volumes count as full.
DISK_FULL_BELOW_BYTES = 16 * 1024 * 1024

#: What the event may name as lost, and as the cause: the binary's own lists. Anything else
#: in those fields is left out of what is recorded, since a stream is not trusted text.
LOST_RECORDS = ("transcript", "global_config")
LOST_CAUSES = ("ENOSPC", "EDQUOT")


def writes_lost(stream: str) -> str | None:
    """What the binary said it could not save, and why, or ``None`` if it said nothing.

    Read from the binary's own event wherever it stands in ``stream``; the same words
    inside another event (a tool's output) are not it. A session that says this did not
    keep its own records, so no reader takes its end for a completed one.
    """
    for line in split_lines(stream):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") != "system" or event.get("subtype") != WRITES_LOST:
            continue
        named = event.get("lost")
        lost = [what for what in LOST_RECORDS if isinstance(named, list) and what in named]
        code = event.get("error_code")
        cause = code if code in LOST_CAUSES else "a cause it did not name"
        return f"{', '.join(lost) or 'records'} ({cause})"
    return None


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
    lost: str | None = None,
    claude_version: str | None = None,
) -> SessionEnd:
    """Classify how a session ended from its result object and exit.

    Args:
        result: the binary's final ``result`` object, or ``None`` if the stream
            ended without one (a killed or crashed session).
        exit_code: the process's exit status, ``None`` if it was never reaped.
        stopped_at_wall_clock: the orchestrator stopped it at its wall clock.
        lost: what the binary said after its result it could not save, if it said so: a
            session that would otherwise be a completed one is infrastructure under
            ``disk_full``, and one that ended for another reason keeps that reason.
        claude_version: the pin the session ran on, if the caller names it: on a pin in
            ``NAMED_END_VERSIONS`` a request that outgrew the window and a structured
            answer refused at the binary's cap are each a cause of their own.
    """
    if stopped_at_wall_clock:
        return SessionEnd(outcome="infrastructure", cause="wall_clock")
    if result is None:
        return SessionEnd(outcome="infrastructure", cause="no_result")
    terminal = result.get("terminal_reason")
    is_error = result.get("is_error")
    errors = result.get("errors")
    if (
        is_error is True
        and isinstance(errors, list)
        and any(isinstance(e, str) and e.startswith(SANDBOX_UNAVAILABLE) for e in errors)
    ):
        return SessionEnd(outcome="infrastructure", cause="sandbox_unavailable")
    if terminal == "max_turns":
        return SessionEnd(outcome="infrastructure", cause="turn_limit")
    if is_error is True and terminal == "api_error":
        if result.get("api_error_status") in CREDENTIAL_REFUSED_STATUSES:
            return SessionEnd(outcome="infrastructure", cause="credential_refused")
        return SessionEnd(outcome="infrastructure", cause="api_error")
    if is_error is True and claude_version in NAMED_END_VERSIONS:
        if terminal == PROMPT_TOO_LONG:
            return SessionEnd(outcome="infrastructure", cause="prompt_too_long")
        if terminal == STRUCTURED_OUTPUT_EXHAUSTED:
            return SessionEnd(outcome="infrastructure", cause="structured_output_retry_exhausted")
    if is_error is False and terminal == "completed" and exit_code == 0:
        if lost is not None:
            return SessionEnd(outcome="infrastructure", cause="disk_full")
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
