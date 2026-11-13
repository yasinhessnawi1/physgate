"""The account's usage limit is its own cause: no retry, nothing queued, a halt that waits.

When the account a run spends from reaches its usage limit, every session ends at once. Its
stream says so: a ``rate_limit_event`` whose state is ``rejected``, an assistant message whose
error is ``rate_limit``, and a result whose text names the limit and its reset ("You've hit your
session limit · resets 1:20pm (Europe/Oslo)"). Retrying inside the window cannot succeed, and a
review that could not run is no reason to send its attempt to a person. So a role session that
ended on the limit spends no retry and no attempt, a review that could not run leaves the
attempt waiting for it, and the run halts waiting for the reset: a resume before the reset
instant is refused and starts nothing, and one after it goes on exactly where the run stopped.

Every other infrastructure error keeps its handling: an API error such as a 503 is retried on
the schedule. A run recorded before the limit had a cause of its own replays as it did, and
its lines are written byte for byte as before.

The streams here are stand-ins in the shape a live run's stream gave when its account reached
the limit, its values replaced: a ``rate_limit_event`` whose ``rate_limit_info`` gives the state
(``rejected``), the reset as an exact instant (``resetsAt``, epoch seconds), the kind of limit
(``rateLimitType``) and how full each of the account's windows was (``unifiedWindows``); an
assistant line whose top-level ``error`` is ``rate_limit``, with its ``request_id``; and a result
whose ``terminal_reason`` is ``api_error`` and whose text names the limit and its reset. The
reset is taken from the event's instant; the result's wall-clock text is the fallback only.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import loop_fakes
import pytest
from loop_fakes import FakeDispatcher, FakeReviewer, Rig, plan, usage
from orch_helpers import ticking_clock
from pydantic import ValidationError

import physgate.orchestrator.cli as cli
from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    EscalationDecided,
    Halted,
    InfraRetryScheduled,
    Resumed,
    ReviewRan,
    ReviewUnavailable,
    SessionEnded,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import LimitNotResetError, ReviewUnavailableError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.usage_limit import (
    UNREAD_RESET_WAIT,
    AccountWindow,
    UsageLimit,
    account_windows,
    reset_instant,
    session_end,
    usage_limit_of,
    with_instant,
)
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT, limit_wait, printed_step
from physgate.state.task_ledger import TaskLedger

# -- the stream, as the live runs printed it ---------------------------------------------------

SESSION_LIMIT = "You've hit your session limit · resets 1:20pm (Europe/Oslo)"
NIGHT_LIMIT = "You've hit your session limit · resets 3am (Europe/Oslo)"
OUTAGE = (
    "API Error: 503 credential validation failed. This is usually temporary; "
    "please try again in a moment."
)
#: The weekly limit's text in a recorded stream's form: it has a date, so the text gives no instant.
WEEKLY_LIMIT = "You've hit your weekly limit · resets Nov 18 at 10am (Europe/Oslo)"
RESETS = "1:20pm (Europe/Oslo)"
UNREAD = "Nov 20 at 3am (Europe/Oslo)"
#: The session window's reset in the stand-in events: 1:20pm in Oslo on 13 November.
RESET_EPOCH = 1794572400
RESET_STAMP = "2026-11-13T12:20:00.000000Z"
#: The weekly window's reset in the stand-in events: 10am in Oslo on 18 November.
WEEK_EPOCH = 1794992400
WEEK_STAMP = "2026-11-18T09:00:00.000000Z"
#: How full the account's windows were in the stand-in refusal: the session window spent.
WINDOWS = (
    AccountWindow(window="five_hour", used_fraction=1.0, resets_at=RESET_STAMP),
    AccountWindow(window="seven_day", used_fraction=0.47, resets_at=WEEK_STAMP),
)


def _line(**fields: Any) -> str:  # noqa: ANN401 - the binary's own untyped events
    return json.dumps(fields)


def _stream(*lines: str) -> str:
    return "\n".join(lines) + "\n"


INIT = _line(type="system", subtype="init", session_id="s", model="claude-opus-5-5")


def _rate_limit(
    status: str,
    *,
    kind: str = "five_hour",
    resets_at: object = RESET_EPOCH,
    five_hour: object = 1,
    seven_day: object = 0.47,
    windows: object = None,
) -> str:
    """A ``rate_limit_event`` in the shape a live run's stream gave it."""
    unified = {
        "five_hour": {"utilization": five_hour, "resetsAt": RESET_EPOCH},
        "seven_day": {"utilization": seven_day, "resetsAt": WEEK_EPOCH},
    }
    info: dict[str, Any] = {
        "status": status,
        "resetsAt": resets_at,
        "rateLimitType": kind,
        "overageStatus": "rejected",
        "overageDisabledReason": "out_of_credits",
        "isUsingOverage": False,
        "unifiedWindows": unified if windows is None else windows,
    }
    if resets_at is None:
        del info["resetsAt"]
    return _line(type="rate_limit_event", rate_limit_info=info, uuid="u", session_id="s")


def _said(text: str, error: str | None) -> str:
    message = {
        "id": "msg_1",
        "model": "<synthetic>",
        "role": "assistant",
        "type": "message",
        "content": [{"type": "text", "text": text}],
    }
    marked = {"error": error, "request_id": "req_1", "is_api_error_message": True}
    return _line(type="assistant", message=message, session_id="s", **(marked if error else {}))


def _result(text: str, *, is_error: bool = True, status: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "terminal_reason": "api_error" if is_error else "completed",
        "result": text,
        "session_id": "s",
    }
    if status is not None:
        result["api_error_status"] = status
    return result


def _limited(text: str = SESSION_LIMIT, **event: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    result = _result(text, status=429)
    stream = _stream(
        INIT, _rate_limit("rejected", **event), _said(text, "rate_limit"), json.dumps(result)
    )
    return stream, result


def _outage() -> tuple[str, dict[str, Any]]:
    result = _result(OUTAGE, status=503)
    stream = _stream(
        INIT, _rate_limit("allowed"), _said(OUTAGE, "server_error"), json.dumps(result)
    )
    return stream, result


# -- reading the limit from the stream -------------------------------------------------------


def test_a_session_that_ended_on_the_limit_is_read_with_the_event_s_instant_kind_and_windows() -> (
    None
):
    stream, result = _limited()
    read = UsageLimit(resets=RESETS, resets_at=RESET_STAMP, limit_type="five_hour", windows=WINDOWS)
    assert usage_limit_of(stream, result) == read
    assert usage_limit_of(stream.encode(), result) == read
    end, limit = session_end(stream, result, exit_code=1, stopped_at_wall_clock=False)
    assert end == SessionEnd(outcome="infrastructure", cause="usage_limit")
    assert limit == read


def test_the_night_form_of_the_reset_is_read_as_given() -> None:
    stream, result = _limited(NIGHT_LIMIT)
    limit = usage_limit_of(stream, result)
    assert limit is not None and limit.resets == "3am (Europe/Oslo)"


def test_the_event_s_instant_is_the_reset_whatever_the_text_says() -> None:
    later = 1794574200  # 12:50Z, half an hour after the text's 1:20pm in Oslo
    stream, result = _limited(resets_at=later)
    limit = usage_limit_of(stream, result)
    assert limit is not None
    assert (limit.resets, limit.resets_at) == (RESETS, "2026-11-13T12:50:00.000000Z")


def test_a_weekly_limit_is_recorded_as_one_with_its_instant_days_later() -> None:
    stream, result = _limited(WEEKLY_LIMIT, kind="seven_day", resets_at=WEEK_EPOCH, seven_day=1)
    limit = usage_limit_of(stream, result)
    assert limit is not None
    assert (limit.limit_type, limit.resets_at) == ("seven_day", WEEK_STAMP)
    assert limit.resets == "Nov 18 at 10am (Europe/Oslo)"
    assert reset_instant(limit.resets, after=_at("2026-11-13T11:30:00")) is None, (
        "the text alone gives no instant; the event's is the one recorded"
    )
    assert [(w.window, w.used_fraction) for w in limit.windows] == [
        ("five_hour", 1.0),
        ("seven_day", 1.0),
    ]


def test_a_kind_of_limit_not_known_here_is_recorded_as_given_and_is_the_limit_all_the_same() -> (
    None
):
    stream, result = _limited(kind="opus_monthly")
    end, limit = session_end(stream, result, exit_code=1, stopped_at_wall_clock=False)
    assert end.cause == "usage_limit"
    assert limit is not None
    assert (limit.limit_type, limit.resets, limit.resets_at) == (
        "opus_monthly",
        RESETS,
        RESET_STAMP,
    )


@pytest.mark.parametrize(
    "resets_at",
    [None, "1794572400", True, 1794572400.5, 0, -1, 10**20],
    ids=["absent", "a-string", "a-bool", "a-fraction", "zero", "negative", "out-of-range"],
)
def test_an_event_instant_that_is_not_an_epoch_leaves_the_text_as_the_fallback(
    resets_at: object,
) -> None:
    stream, result = _limited(resets_at=resets_at)
    limit = usage_limit_of(stream, result)
    assert limit is not None
    assert (limit.resets, limit.resets_at, limit.limit_type) == (RESETS, None, "five_hour")
    # The text, read in its zone, is then the reset.
    assert with_instant(limit, after=_at("2026-11-13T11:30:00")).resets_at == RESET_STAMP


@pytest.mark.parametrize(
    "used",
    [True, -0.1, "0.5", None, float("nan"), float("inf")],
    ids=["a-bool", "negative", "a-string", "absent", "nan", "infinite"],
)
def test_a_window_whose_figure_is_not_a_share_is_left_out(used: object) -> None:
    stream, result = _limited(five_hour=used)
    limit = usage_limit_of(stream, result)
    assert limit is not None
    assert limit.windows == WINDOWS[1:]


def test_a_window_with_no_reset_instant_is_left_out() -> None:
    windows = {
        "five_hour": {"utilization": 1, "resetsAt": "soon"},
        "seven_day": {"utilization": 0.47, "resetsAt": WEEK_EPOCH},
        "other": "not a window",
    }
    stream, result = _limited(windows=windows)
    limit = usage_limit_of(stream, result)
    assert limit is not None
    assert limit.windows == WINDOWS[1:]


def test_a_share_outside_its_range_is_refused_on_the_record() -> None:
    for used in (-0.1, float("nan"), float("inf")):
        assert _refused(
            lambda used=used: AccountWindow(window="w", used_fraction=used, resets_at=RESET_STAMP)
        )


# -- how full the account's windows were at a session's end ------------------------------------


def test_a_session_s_end_records_the_latest_windows_its_stream_gave() -> None:
    result = _result("done", is_error=False)
    stream = _stream(
        INIT,
        _rate_limit("allowed", five_hour=0.81, seven_day=0.47),
        _rate_limit("allowed_warning", five_hour=0.9, seven_day=0.77),
        _rate_limit("allowed", windows={}),
        json.dumps(result),
    )
    assert account_windows(stream) == (
        AccountWindow(window="five_hour", used_fraction=0.9, resets_at=RESET_STAMP),
        AccountWindow(window="seven_day", used_fraction=0.77, resets_at=WEEK_STAMP),
    )
    assert account_windows(stream.encode()) == account_windows(stream)


def test_a_stream_with_no_rate_limit_state_gives_no_windows() -> None:
    result = _result("done", is_error=False)
    assert account_windows(_stream(INIT, json.dumps(result))) == ()


@pytest.mark.parametrize(
    "signal",
    ["event", "message", "text"],
    ids=["the-rejected-event", "the-message-error", "the-result-text"],
)
def test_each_of_the_stream_s_signs_alone_names_the_limit(signal: str) -> None:
    text = SESSION_LIMIT if signal == "text" else "API Error: 429"
    result = _result(text, status=429)
    lines = [INIT]
    if signal == "event":
        lines.append(_rate_limit("rejected"))
    if signal == "message":
        lines.append(_said(text, "rate_limit"))
    lines.append(json.dumps(result))
    limit = usage_limit_of(_stream(*lines), result)
    assert limit is not None
    assert limit.resets == (RESETS if signal == "text" else None)
    from_event = (RESET_STAMP, "five_hour", WINDOWS) if signal == "event" else (None, None, ())
    assert (limit.resets_at, limit.limit_type, limit.windows) == from_event


def test_a_503_is_an_api_error_as_today_and_never_the_limit() -> None:
    stream, result = _outage()
    assert usage_limit_of(stream, result) is None
    end, limit = session_end(stream, result, exit_code=1, stopped_at_wall_clock=False)
    assert (end, limit) == (SessionEnd(outcome="infrastructure", cause="api_error"), None)


def test_an_allowed_rate_limit_state_in_a_completed_session_is_no_limit() -> None:
    result = _result("done", is_error=False)
    stream = _stream(INIT, _rate_limit("allowed"), json.dumps(result))
    assert usage_limit_of(stream, result) is None
    end, limit = session_end(stream, result, exit_code=0, stopped_at_wall_clock=False)
    assert (end, limit) == (SessionEnd(outcome="completed", cause=None), None)


def test_a_session_whose_own_words_name_a_limit_but_that_completed_is_no_limit() -> None:
    result = _result(SESSION_LIMIT, is_error=False)
    stream = _stream(INIT, _rate_limit("rejected"), json.dumps(result))
    assert usage_limit_of(stream, result) is None


def test_a_session_stopped_at_its_wall_clock_keeps_that_cause() -> None:
    stream, result = _limited()
    end, limit = session_end(stream, result, exit_code=None, stopped_at_wall_clock=True)
    assert (end, limit) == (SessionEnd(outcome="infrastructure", cause="wall_clock"), None)


def test_a_session_with_no_result_is_no_limit() -> None:
    stream, _ = _limited()
    assert usage_limit_of(stream, None) is None


# -- the reset, as an instant ----------------------------------------------------------------


def _at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("resets", "after", "instant"),
    [
        # Mid-November, Oslo is UTC+1.
        (RESETS, "2026-11-13T11:30:00", "2026-11-13T12:20:00"),
        ("3am (Europe/Oslo)", "2026-11-12T22:43:00", "2026-11-13T02:00:00"),
        # A wall time already passed today is tomorrow's.
        (RESETS, "2026-11-13T12:30:00", "2026-11-14T12:20:00"),
        ("12am (Europe/Oslo)", "2026-11-13T10:00:00", "2026-11-13T23:00:00"),
        ("12pm (UTC)", "2026-11-13T10:00:00", "2026-11-13T12:00:00"),
        # In September Oslo is UTC+2; the next day across the change to summer time is +2 too.
        (RESETS, "2026-09-26T10:00:00", "2026-09-26T11:20:00"),
        ("3am (Europe/Oslo)", "2026-03-28T12:00:00", "2026-03-29T01:00:00"),
    ],
)
def test_the_reset_is_the_next_time_that_wall_time_comes_in_its_zone(
    resets: str, after: str, instant: str
) -> None:
    assert reset_instant(resets, after=_at(after)) == _at(instant)


@pytest.mark.parametrize(
    "resets",
    [UNREAD, "3am (Mars/Olympus)", "13pm (Europe/Oslo)", "1:75pm (Europe/Oslo)", "3am", "soon"],
)
def test_a_reset_that_does_not_parse_gives_no_instant(resets: str) -> None:
    assert reset_instant(resets, after=_at("2026-11-13T11:30:00")) is None
    limit = UsageLimit(resets=resets)
    assert with_instant(limit, after=_at("2026-11-13T11:30:00")) == limit


def test_the_instant_is_recorded_as_every_record_stamps_a_moment() -> None:
    limit = with_instant(UsageLimit(resets=RESETS), after=_at("2026-11-13T11:30:00"))
    assert limit == UsageLimit(resets=RESETS, resets_at="2026-11-13T12:20:00.000000Z")


# -- the loop -----------------------------------------------------------------------------------

#: Where the rig's clock starts: noon in Oslo, so the 1:20pm reset is at 11:20Z the same day.
NOON = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
INSTANT = "2026-09-26T11:20:00.000000Z"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[datetime]]:
    """The instant every loop the rig opens next starts its clock at."""
    start = [NOON]
    monkeypatch.setattr(loop_fakes, "ticking_clock", lambda: ticking_clock(start[0]))
    yield start


@dataclass
class LimitDispatcher(FakeDispatcher):
    """A fake dispatcher whose sessions on the calls named end on the account's usage limit."""

    limits: dict[int, UsageLimit] = field(default_factory=dict)

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        limit = self.limits.get(len(self.requests))
        return report if limit is None else report.model_copy(update={"usage_limit": limit})


def _limited_rig(tmp_path: Path, resets: str = RESETS) -> Rig:
    dispatcher = LimitDispatcher(infra={1: "usage_limit"}, limits={1: UsageLimit(resets=resets)})
    return Rig(tmp_path, dispatcher=dispatcher, delays=(60.0, 300.0))


def _events(tmp_path: Path) -> list[Any]:
    return list(read_events(tmp_path / "events.jsonl"))


def _resume(loop: Loop, **kw: Any) -> LimitNotResetError | str:  # noqa: ANN401
    try:
        return loop.resume(**kw).kind
    except LimitNotResetError as exc:
        return exc
    finally:
        loop.close()


def _halted_on_the_limit(tmp_path: Path, rig: Rig) -> Halted:
    loop = rig.open()
    loop.start(plan("s1"))
    step = loop.run()
    loop.close()
    assert step.kind == "halted"
    halts = [e for e in _events(tmp_path) if isinstance(e, Halted)]
    assert [h.reason for h in halts] == ["usage_limit"]
    return halts[0]


def test_a_session_on_the_limit_spends_no_retry_and_no_attempt_and_halts_waiting(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == UsageLimit(resets=RESETS, resets_at=INSTANT)
    assert INSTANT in halt.detail and RESETS in halt.detail
    events = _events(tmp_path)
    assert rig.slept == [], "no retry is waited out inside the limit's window"
    assert [e for e in events if isinstance(e, InfraRetryScheduled)] == []
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert (ended.outcome, ended.cause) == ("infrastructure", "usage_limit")
    assert ended.usage_limit == UsageLimit(resets=RESETS, resets_at=INSTANT)
    assert [r.attempt for r in rig.dispatcher.requests] == [1]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1
    # A plain run of the halted run starts nothing either.
    assert rig.open().run().kind == "halted"
    assert len(rig.dispatcher.requests) == 1


def test_a_resume_before_the_reset_is_refused_with_the_instant_and_starts_nothing(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    written = (tmp_path / "events.jsonl").read_bytes()
    clock[0] = NOON + timedelta(hours=1)  # 11:00Z, twenty minutes before the reset
    refused = _resume(rig.open())
    assert isinstance(refused, LimitNotResetError)
    assert refused.context["resume_after"] == INSTANT
    assert INSTANT in str(refused)
    assert len(rig.dispatcher.requests) == 1
    assert (tmp_path / "events.jsonl").read_bytes() == written


def test_a_resume_after_the_reset_continues_the_same_attempt(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    clock[0] = NOON + timedelta(hours=1, minutes=21)
    assert _resume(rig.open()) == "done"
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]
    events = _events(tmp_path)
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert (resumed.attempt, resumed.point, resumed.limit_reset_by) == (1, "resolve", None)
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1 and line.merge_commit
    assert rig.slept == []


def _limited_review() -> ReviewUnavailableError:
    return ReviewUnavailableError(
        "the session ended with api_error",
        cause="infrastructure",
        session_id="rev-1",
        reviewer_model=FakeReviewer().model,
        usage=(MessageUsage(message_id="r1", usage=usage(7)),),
        usage_limit=UsageLimit(resets=RESETS),
    )


def test_a_review_on_the_limit_is_not_retried_queued_or_rejected_and_the_run_waits(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _limited_review()}), delays=(60.0,))
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == UsageLimit(resets=RESETS, resets_at=INSTANT)
    assert "review" in halt.detail
    events = _events(tmp_path)
    assert len(rig.reviewer.seen) == 1, "a review is not retried inside the limit's window"
    assert [e for e in events if isinstance(e, ReviewUnavailable) and not e.retry] == []
    for kind in (EscalationDecided, Escalated, AttemptRejected, ReviewRan):
        assert [e for e in events if isinstance(e, kind)] == []
    spent = [e.attribution for e in events if isinstance(e, TokensUsed)]
    assert "reviewer:rev-1" in spent
    loop = rig.open()
    assert loop.queue.open_items() == []
    assert loop.state.subtasks["s1"].status == "active"
    loop.close()


def test_the_review_is_still_owed_after_a_resume_past_the_reset(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _limited_review()}))
    _halted_on_the_limit(tmp_path, rig)
    clock[0] = NOON + timedelta(minutes=30)
    assert isinstance(_resume(rig.open()), LimitNotResetError)
    assert len(rig.reviewer.seen) == 1
    clock[0] = NOON + timedelta(hours=2)
    assert _resume(rig.open()) == "done"
    assert [a.attempt for a in rig.reviewer.seen] == [1, 1]
    assert [r.attempt for r in rig.dispatcher.requests] == [1], "no new role session"
    events = _events(tmp_path)
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert (resumed.attempt, resumed.point) == (1, "verify_reading")
    assert [e.result.verdict for e in events if isinstance(e, ReviewRan)] == ["pass"]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1 and line.merge_commit


def test_a_503_keeps_its_retries_as_today(tmp_path: Path, clock: list[datetime]) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "api_error"}), delays=(60.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    assert rig.slept == [60.0]
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]
    events = _events(tmp_path)
    assert [e.delay_s for e in events if isinstance(e, InfraRetryScheduled)] == [60.0]


def test_a_review_s_503_is_retried_once_as_today(tmp_path: Path, clock: list[datetime]) -> None:
    outage = ReviewUnavailableError(
        "the session ended with api_error", cause="infrastructure", session_id="rev-1"
    )
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: outage}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    unavailable = [e for e in _events(tmp_path) if isinstance(e, ReviewUnavailable)]
    assert [(u.cause, u.retry) for u in unavailable] == [("infrastructure", True)]
    assert len(rig.reviewer.seen) == 2


def test_an_unread_reset_halts_waiting_and_resumes_on_the_operator_s_word(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path, resets=UNREAD)
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == UsageLimit(resets=UNREAD, resets_at=None)
    clock[0] = NOON + timedelta(hours=2)
    refused = _resume(rig.open())
    assert isinstance(refused, LimitNotResetError)
    after = datetime.strptime(halt.ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    after += UNREAD_RESET_WAIT
    assert refused.context["resume_after"] == after.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert len(rig.dispatcher.requests) == 1
    assert _resume(rig.open(), limit_reset_by="operator") == "done"
    (resumed,) = [e for e in _events(tmp_path) if isinstance(e, Resumed)]
    assert resumed.limit_reset_by == "operator"
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]


def test_an_unread_reset_resumes_without_a_word_after_the_default_wait(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path, resets=UNREAD)
    _halted_on_the_limit(tmp_path, rig)
    clock[0] = NOON + UNREAD_RESET_WAIT + timedelta(minutes=1)
    assert _resume(rig.open()) == "done"
    (resumed,) = [e for e in _events(tmp_path) if isinstance(e, Resumed)]
    assert resumed.limit_reset_by is None


def test_the_operator_s_word_does_not_override_a_reset_that_was_read(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    clock[0] = NOON + timedelta(minutes=30)
    assert isinstance(_resume(rig.open(), limit_reset_by="operator"), LimitNotResetError)
    assert len(rig.dispatcher.requests) == 1


#: A weekly limit met at the rig's noon, as a recorded stream gave its text, and its reset: 7am in
#: Oslo on 1 October, five days later.
WEEKLY_TEXT = "Oct 1 at 7am (Europe/Oslo)"
WEEKLY_INSTANT = "2026-10-01T05:00:00.000000Z"


def test_a_weekly_limit_halts_until_its_own_instant_days_later_not_hours(
    tmp_path: Path, clock: list[datetime]
) -> None:
    weekly = UsageLimit(resets=WEEKLY_TEXT, resets_at=WEEKLY_INSTANT, limit_type="seven_day")
    dispatcher = LimitDispatcher(infra={1: "usage_limit"}, limits={1: weekly})
    rig = Rig(tmp_path, dispatcher=dispatcher, delays=(60.0,))
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == weekly
    assert "seven_day" in halt.detail and WEEKLY_INSTANT in halt.detail
    printed, status = printed_step("halted", _state(rig))
    assert (printed.get("limit_type"), printed["resume_after"], status) == (
        "seven_day",
        WEEKLY_INSTANT,
        EXIT_WAITING_FOR_LIMIT,
    )
    clock[0] = NOON + UNREAD_RESET_WAIT + timedelta(minutes=1)
    refused = _resume(rig.open())
    assert isinstance(refused, LimitNotResetError)
    assert refused.context["resume_after"] == WEEKLY_INSTANT
    assert len(rig.dispatcher.requests) == 1
    clock[0] = datetime(2026, 10, 1, 5, 1, tzinfo=UTC)
    assert _resume(rig.open()) == "done"
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]


def test_the_loop_keeps_the_event_s_instant_over_the_text_s(
    tmp_path: Path, clock: list[datetime]
) -> None:
    later = "2026-09-26T11:50:00.000000Z"  # half an hour after the text's 1:20pm in Oslo
    limit = UsageLimit(resets=RESETS, resets_at=later, limit_type="five_hour")
    rig = Rig(
        tmp_path,
        dispatcher=LimitDispatcher(infra={1: "usage_limit"}, limits={1: limit}),
        delays=(60.0,),
    )
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == limit
    clock[0] = NOON + timedelta(hours=1, minutes=21)  # past the text's reset, before the event's
    refused = _resume(rig.open())
    assert isinstance(refused, LimitNotResetError)
    assert refused.context["resume_after"] == later


def test_a_kind_of_limit_not_known_here_halts_waiting_all_the_same(
    tmp_path: Path, clock: list[datetime]
) -> None:
    limit = UsageLimit(resets=RESETS, resets_at=INSTANT, limit_type="opus_monthly")
    rig = Rig(
        tmp_path,
        dispatcher=LimitDispatcher(infra={1: "usage_limit"}, limits={1: limit}),
        delays=(60.0,),
    )
    halt = _halted_on_the_limit(tmp_path, rig)
    assert halt.usage_limit == limit
    assert rig.slept == []
    printed, status = printed_step("halted", _state(rig))
    assert (printed.get("limit_type"), status) == ("opus_monthly", EXIT_WAITING_FOR_LIMIT)


@dataclass
class WindowsDispatcher(FakeDispatcher):
    """A fake dispatcher whose every session's stream gave the account's windows."""

    windows: tuple[AccountWindow, ...] = ()

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        return report.model_copy(update={"account_windows": self.windows})


def test_each_session_s_end_records_how_full_the_account_s_windows_were(
    tmp_path: Path, clock: list[datetime]
) -> None:
    windows = (
        AccountWindow(window="five_hour", used_fraction=0.9, resets_at=INSTANT),
        AccountWindow(window="seven_day", used_fraction=0.77, resets_at=WEEKLY_INSTANT),
    )
    rig = Rig(tmp_path, dispatcher=WindowsDispatcher(windows=windows))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    (ended,) = [e for e in _events(tmp_path) if isinstance(e, SessionEnded)]
    assert ended.account_windows == windows
    line = next(
        json.loads(raw)
        for raw in (tmp_path / "events.jsonl").read_text().splitlines()
        if '"session_ended"' in raw
    )
    assert line["account_windows"][0] == {
        "window": "five_hour",
        "used_fraction": 0.9,
        "resets_at": INSTANT,
    }


# -- the command line ---------------------------------------------------------------------------


def _state(rig: Rig) -> Any:  # noqa: ANN401
    loop = rig.open()
    state = loop.state
    loop.close()
    return state


def test_a_run_halted_on_the_limit_prints_its_own_step_and_exit_status(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    printed, status = printed_step("halted", _state(rig))
    assert printed == {
        "step": "waiting_for_limit",
        "limit_type": None,
        "resets": RESETS,
        "resets_at": INSTANT,
        "resume_after": INSTANT,
    }
    assert status == EXIT_WAITING_FOR_LIMIT == 75


def test_every_other_step_prints_as_today(tmp_path: Path, clock: list[datetime]) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "api_error"}), delays=())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    state = _state(rig)
    assert state.halted.reason == "infrastructure_exhausted"
    assert printed_step("halted", state) == ({"step": "halted"}, 1)
    assert printed_step("done", state) == ({"step": "done"}, 0)
    assert printed_step("escalated", state) == ({"step": "escalated"}, 1)
    assert limit_wait(tmp_path, NOON, limit_reset=False) is None


def test_the_command_line_says_when_a_resume_may_go_on(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    refused = limit_wait(tmp_path, NOON + timedelta(hours=1), limit_reset=False)
    assert refused is not None
    assert (refused["step"], refused["resume_after"]) == ("waiting_for_limit", INSTANT)
    assert INSTANT in refused["error"]
    assert limit_wait(tmp_path, NOON + timedelta(hours=2), limit_reset=False) is None


def test_the_command_line_takes_the_operator_s_word_only_for_an_unread_reset(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = _limited_rig(tmp_path, resets=UNREAD)
    _halted_on_the_limit(tmp_path, rig)
    assert limit_wait(tmp_path, NOON + timedelta(hours=1), limit_reset=False) is not None
    assert limit_wait(tmp_path, NOON + timedelta(hours=1), limit_reset=True) is None


def test_a_resume_command_before_the_reset_exits_waiting_before_it_touches_anything(
    tmp_path: Path,
    clock: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = _limited_rig(tmp_path)
    _halted_on_the_limit(tmp_path, rig)
    written = (tmp_path / "events.jsonl").read_bytes()
    now: Callable[[], datetime] = lambda: NOON + timedelta(hours=1)  # noqa: E731
    monkeypatch.setattr(cli, "utc_now", now)
    args = argparse.Namespace(
        run_dir=tmp_path,
        target=tmp_path / "target",
        install=tmp_path / "install",
        review_root=tmp_path / "review-scratch",
        quarantine=None,
        quarantine_why=None,
        confirm=[],
        limit_reset=False,
    )
    status = cli._drive(args, resume=True, registrations=None)  # noqa: SLF001
    assert status == EXIT_WAITING_FOR_LIMIT
    said = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert (said["step"], said["resume_after"]) == ("waiting_for_limit", INSTANT)
    assert (tmp_path / "events.jsonl").read_bytes() == written


# -- replay -------------------------------------------------------------------------------------


def test_a_run_recorded_before_the_limit_had_a_cause_replays_and_resumes_as_before(
    tmp_path: Path, clock: list[datetime]
) -> None:
    # The live run's shape before this change: the limit read as an API error, retried, then
    # the schedule spent and the run halted. Nothing about it is read as a limit now.
    rig = Rig(
        tmp_path,
        dispatcher=FakeDispatcher(infra={1: "api_error", 2: "api_error"}),
        delays=(60.0,),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    state = _state(rig)
    assert state.halted.reason == "infrastructure_exhausted"
    assert state.halt_resumable()
    assert limit_wait(tmp_path, NOON, limit_reset=False) is None
    assert _resume(rig.open()) == "done"
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1, 1]
    assert rig.slept == [60.0]


def test_a_line_with_no_limit_is_written_byte_for_byte_as_before(
    tmp_path: Path, clock: list[datetime]
) -> None:
    rig = Rig(
        tmp_path,
        dispatcher=FakeDispatcher(infra={1: "api_error", 2: "api_error"}),
        delays=(60.0,),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    assert _resume(rig.open()) == "done"
    data = (tmp_path / "events.jsonl").read_bytes()
    assert b'"usage_limit"' not in data
    assert b'"limit_reset_by"' not in data
    assert b'"account_windows"' not in data
    lines = data.splitlines(keepends=True)
    events = _events(tmp_path)
    assert [e.model_dump_json().encode() + b"\n" for e in events] == lines


def _refused(build: Callable[[], object]) -> bool:
    try:
        build()
    except ValidationError:
        return True
    return False


def test_a_limit_is_on_a_line_exactly_when_its_cause_or_reason_is_the_limit() -> None:
    env = {"seq": 1, "ts": "2026-09-26T10:00:00.000000Z", "run_id": "run-1", "gate_mode": "on"}
    limit = {"resets": RESETS, "resets_at": INSTANT}
    halt = {**env, "kind": "halted", "detail": "d"}
    assert _refused(lambda: Halted.model_validate({**halt, "reason": "usage_limit"}))
    assert _refused(
        lambda: Halted.model_validate(
            {**halt, "reason": "infrastructure_exhausted", "usage_limit": limit}
        )
    )
    ended = {
        **env,
        "kind": "session_ended",
        "subtask_id": "s1",
        "attempt": 1,
        "session_id": "sess-1",
        "outcome": "infrastructure",
        "attempt_commit": None,
        "trajectory": None,
        "worktree": None,
        "reading_verified": False,
    }
    assert _refused(lambda: SessionEnded.model_validate({**ended, "cause": "usage_limit"}))
    assert _refused(
        lambda: SessionEnded.model_validate({**ended, "cause": "api_error", "usage_limit": limit})
    )
    assert not _refused(
        lambda: SessionEnded.model_validate({**ended, "cause": "usage_limit", "usage_limit": limit})
    )
