"""The account's usage limit, read from a session's stream as its own cause.

Not yet implemented: the types and the names the rows hold the loop to.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.budget import SessionEnd, classify_session_end
from physgate.orchestrator.common import NonEmptyStr, Timestamp

#: How long a run waits after a halt whose reset could not be read, before a resume is allowed
#: without the operator's word that the limit has reset: the account's session window.
UNREAD_RESET_WAIT = timedelta(hours=5)


class UsageLimit(BaseModel):
    """The account's usage limit as a session's stream named it, and when it resets."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The reset as the stream gave it ("1:20pm (Europe/Oslo)"), or ``None`` if it gave none.
    resets: NonEmptyStr | None
    #: That reset as an instant, where it parses; ``None`` where it does not.
    resets_at: Timestamp | None = None


def usage_limit_of(data: bytes | str, result: Mapping[str, object] | None) -> UsageLimit | None:
    """The usage limit a session's stream says it ended on, or ``None``."""
    del data, result
    return None


def reset_instant(resets: str, *, after: datetime) -> datetime | None:
    """The next instant after ``after`` at the wall time ``resets`` names, in its zone."""
    del resets, after
    return None


def with_instant(limit: UsageLimit, *, after: datetime) -> UsageLimit:
    """``limit`` with its reset parsed to an instant after ``after``, where it parses."""
    del after
    return limit


def session_end(
    data: bytes | str,
    result: Mapping[str, object] | None,
    *,
    exit_code: int | None,
    stopped_at_wall_clock: bool,
) -> tuple[SessionEnd, UsageLimit | None]:
    """How a role session ended, a usage limit named as its own cause."""
    del data
    end = classify_session_end(
        result, exit_code=exit_code, stopped_at_wall_clock=stopped_at_wall_clock
    )
    return end, None


def resume_refusal(
    halted_at: str, limit: UsageLimit | None, now: datetime, *, limit_reset: bool
) -> str | None:
    """Why a resume of a run waiting for the limit is refused now, or ``None`` if it may go on."""
    del halted_at, limit, now, limit_reset
    return None
