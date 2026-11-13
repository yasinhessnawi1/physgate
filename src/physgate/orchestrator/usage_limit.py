"""The account's usage limit, read from a session's stream as its own cause.

When the account a run's sessions spend from reaches its usage limit, every session ends at
once with an API error. The stream names the cause: a ``rate_limit_event`` whose state is
``rejected``, an assistant message whose error is ``rate_limit``, and a result whose text names
the limit and when it resets ("You've hit your session limit · resets 1:20pm (Europe/Oslo)").
Any one of those signs on a session that ended in an API error is read as the limit; the
reset is read from the result's text alone, and only for what it says of the reset.

That is neither a fault of the attempt nor a transient error: a retry inside the limit's window
cannot succeed, and a review that could not run is no reason to send its attempt to a person.
So the loop spends no retry on it and halts the run waiting for the reset (ARCH-030's
infrastructure outcomes, one more cause). Every other API error, a 503 among them, keeps its
retries.

The reset's text has no date and names a zone: it is the next time that wall time comes in that
zone after the session ended. A text that does not parse is recorded as it is, with no instant,
and a resume then waits for the operator's word or :data:`UNREAD_RESET_WAIT`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.budget import SessionEnd, classify_session_end
from physgate.orchestrator.common import NonEmptyStr, Timestamp, utc_stamp
from physgate.reviewers.transcript import parse_event

#: How long a run waits after a halt whose reset could not be read, before a resume is allowed
#: without the operator's word that the limit has reset: the account's session window.
UNREAD_RESET_WAIT = timedelta(hours=5)

#: The state a ``rate_limit_event`` gives when the account may not spend any more.
REJECTED = "rejected"
#: The error an assistant message carries when the binary was refused for the account's limit.
RATE_LIMIT = "rate_limit"
#: The result text that names the limit ("You've hit your session limit"), in any of its kinds.
_NAMES_THE_LIMIT = re.compile(r"\bhit your (?:[\w-]+ )*limit\b|\busage limit reached\b", re.I)
#: The reset, as the result's text gives it: everything after "resets" to the end of the text.
_RESETS = re.compile(r"\bresets\s+(\S.*?)\s*$", re.I | re.S)
#: A reset that parses: a twelve-hour wall time and a zone, and nothing else.
_WALL_TIME = re.compile(
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>am|pm)\s*\((?P<zone>[A-Za-z0-9_+\-/]+)\)",
    re.I,
)
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


class AccountWindow(BaseModel):
    """How full one of the account's usage windows was, as a rate-limit event gave it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The window, as the stream names it: ``five_hour`` (the session window), ``seven_day``.
    window: NonEmptyStr
    #: The share of the window's allowance spent: 0 none of it, 1 all of it.
    used_fraction: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    #: When the window resets.
    resets_at: Timestamp


class UsageLimit(BaseModel):
    """The account's usage limit as a session's stream named it, and when it resets."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The reset as the result's text gave it ("1:20pm (Europe/Oslo)"), or ``None``.
    resets: NonEmptyStr | None
    #: The reset as an instant: the refusal event's own, where it gave one; otherwise the text's,
    #: where it parses; ``None`` where neither does.
    resets_at: Timestamp | None = None
    #: The kind of limit, as the refusal event named it (``five_hour``, ``seven_day``, or a kind
    #: not known here, recorded as given); ``None`` where the stream gave no refusal event.
    limit_type: NonEmptyStr | None = None
    #: How full each of the account's windows was when the limit refused the session.
    windows: tuple[AccountWindow, ...] = ()


def account_windows(data: bytes | str) -> tuple[AccountWindow, ...]:
    """How full the account's windows were at the last rate-limit event a session's stream gave."""
    del data
    return ()


def _signs_the_limit(event: Mapping[str, object]) -> bool:
    """Whether one stream event says the account's limit refused the session."""
    if event.get("type") == "rate_limit_event":
        info = event.get("rate_limit_info")
        return isinstance(info, Mapping) and info.get("status") == REJECTED
    return event.get("type") == "assistant" and event.get("error") == RATE_LIMIT


def usage_limit_of(data: bytes | str, result: Mapping[str, object] | None) -> UsageLimit | None:
    """The usage limit a session's stream says it ended on, or ``None``.

    Only a session that ended in an API error ended on the limit: one that completed, ran out
    of turns, or left no result did not, whatever its stream holds. Of those, one whose stream
    shows the limit's refusal, or whose result's text names the limit, did.
    """
    if result is None or result.get("is_error") is not True:
        return None
    if result.get("terminal_reason") != "api_error":
        return None
    text = data.decode(errors="replace") if isinstance(data, bytes) else data
    said = result.get("result")
    said = said if isinstance(said, str) else ""
    signed = any(
        (event := parse_event(line)) is not None and _signs_the_limit(event)
        for line in text.splitlines()
    )
    if not signed and _NAMES_THE_LIMIT.search(said) is None:
        return None
    resets = _RESETS.search(said)
    return UsageLimit(resets=resets.group(1) if resets else None)


def reset_instant(resets: str, *, after: datetime) -> datetime | None:
    """The next instant after ``after`` at the wall time ``resets`` names, in its zone; or ``None``.

    ``resets`` parses only as a twelve-hour time and a zone ("1:20pm (Europe/Oslo)", "3am
    (Europe/Oslo)"); a date, a word, an hour or minute out of range, or a zone the system does not
    know gives ``None``, never a guess.
    """
    found = _WALL_TIME.fullmatch(resets.strip())
    if found is None:
        return None
    hour, minute = int(found["hour"]), int(found["minute"] or 0)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:  # noqa: PLR2004 - a twelve-hour clock
        return None
    hour = hour % 12 + (12 if found["half"].lower() == "pm" else 0)
    try:
        zone = ZoneInfo(found["zone"])
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = after.astimezone(zone)
    day = local.date()
    for days in (0, 1, 2):
        wall = datetime.combine(day + timedelta(days=days), datetime.min.time(), zone)
        instant = wall.replace(hour=hour, minute=minute).astimezone(UTC)
        if instant > after:
            return instant
    return None


def with_instant(limit: UsageLimit, *, after: datetime) -> UsageLimit:
    """``limit`` with its reset parsed to an instant after ``after``, where it parses."""
    instant = reset_instant(limit.resets, after=after) if limit.resets is not None else None
    if instant is None:
        return limit
    return limit.model_copy(update={"resets_at": utc_stamp(instant)})


def session_end(
    data: bytes | str,
    result: Mapping[str, object] | None,
    *,
    exit_code: int | None,
    stopped_at_wall_clock: bool,
) -> tuple[SessionEnd, UsageLimit | None]:
    """How a role session ended, a usage limit named as its own cause.

    As :func:`~physgate.orchestrator.budget.classify_session_end`, but an API error the stream
    names as the account's usage limit is ``usage_limit``, with the limit as the stream gave it.
    Every other end, a refused credential and a 503 among them, is classified as before.
    """
    end = classify_session_end(
        result, exit_code=exit_code, stopped_at_wall_clock=stopped_at_wall_clock
    )
    limit = usage_limit_of(data, result) if end.cause == "api_error" else None
    if limit is None:
        return end, None
    return SessionEnd(outcome="infrastructure", cause="usage_limit"), limit


def stamped(stamp: str) -> datetime:
    """A record's timestamp as an instant."""
    return datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)


def resume_after(halted_at: str, limit: UsageLimit | None) -> str:
    """The instant after which a run halted on the limit at ``halted_at`` may be resumed.

    The reset's instant, where it was read; otherwise :data:`UNREAD_RESET_WAIT` after the halt.
    """
    if limit is not None and limit.resets_at is not None:
        return limit.resets_at
    return utc_stamp(stamped(halted_at) + UNREAD_RESET_WAIT)


def resume_refusal(
    halted_at: str, limit: UsageLimit | None, now: datetime, *, limit_reset: bool
) -> str | None:
    """Why a resume of a run waiting for the limit is refused at ``now``; ``None`` if it goes on.

    A reset that was read is waited for, whatever the operator says. A reset that could not be
    read is waited for until the default wait has passed, or until the operator says it has
    reset (``limit_reset``).
    """
    after = resume_after(halted_at, limit)
    if now >= stamped(after):
        return None
    read = limit is not None and limit.resets_at is not None
    if not read and limit_reset:
        return None
    resets = limit.resets if limit is not None and limit.resets is not None else "not given"
    how = (
        "its reset was read"
        if read
        else "its reset could not be read; the operator may say it has reset (--limit-reset)"
    )
    return (
        f"the run waits for the account's usage limit (resets {resets}): resume after {after}; "
        f"{how}"
    )
