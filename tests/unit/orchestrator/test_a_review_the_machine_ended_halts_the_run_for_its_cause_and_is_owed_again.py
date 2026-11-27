"""A review the machine ended halts the run for the machine's cause, and is owed again on resume.

It is never sent to a person, and never counted as the harness's own fail. A refused credential
halts the run ``credential_refused`` at once, never retried and nothing spent of the attempt; an
OS layer that would not start halts it ``os_layer_unavailable``, as a role session's end does; any
other machine end is retried once at once (as a review always was), then once after each delay of
the run's retry ladder, and then halts the run ``infrastructure_exhausted``. That is one try more
than a role session gets. A resume goes on at the attempt's checkpoint, the review owed again. A
review with no verdict for the reviewer's own reasons still goes to a person at once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loop_fakes import FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    Escalated,
    Event,
    Halted,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.replay import replay


def _ended(cause: str, session_cause: str | None, n: int) -> ReviewUnavailableError:
    return ReviewUnavailableError(
        f"the review reached no verdict: {cause}",
        cause=cause,  # type: ignore[arg-type]
        session_id=f"rev-down-{n}",
        reviewer_model="claude-opus-5-5",
        usage=(
            MessageUsage(
                message_id=f"u-{n}",
                usage=Usage(
                    input_tokens=5,
                    output_tokens=1,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            ),
        ),
        session_cause=session_cause,
    )


def _down(times: int, session_cause: str | None = "api_error") -> FakeReviewer:
    """A reviewer whose session the machine ends on its first ``times`` calls, then passes."""
    return FakeReviewer(
        unavailable={n: _ended("infrastructure", session_cause, n) for n in range(1, times + 1)}
    )


def _run(rig: Rig) -> list[Event]:
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return read_events(rig.run_dir / "events.jsonl")


def _resumed(rig: Rig) -> list[Event]:
    """The run resumed by a fresh process whose reviewer passes."""
    rig.reviewer = FakeReviewer()
    loop = rig.open()
    loop.resume()
    loop.close()
    return read_events(rig.run_dir / "events.jsonl")


def _halts(events: list[Event]) -> list[str]:
    return [e.reason for e in events if isinstance(e, Halted)]


def _retries(events: list[Event]) -> list[tuple[str, bool]]:
    return [(e.cause, e.retry) for e in events if isinstance(e, ReviewUnavailable)]


def test_a_refused_credential_halts_the_run_at_once_and_its_review_is_owed_again(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, reviewer=_down(1, "credential_refused"), delays=(30.0, 60.0))
    events = _run(rig)
    assert len(rig.reviewer.seen) == 1, "a refused credential is never retried"
    assert _halts(events) == ["credential_refused"]
    assert _retries(events) == [], "no review line: it is not the review's end"
    assert not [e for e in events if isinstance(e, Escalated | Merged)]
    assert rig.slept == []
    # What the review spent is the reviewer's, as any review's.
    spent = [e.message_id for e in events if isinstance(e, TokensUsed)]
    assert "u-1" in spent
    assert replay(events).next_step().kind == "halted"
    after = _resumed(rig)
    assert [e for e in after if isinstance(e, ReviewRan)]
    assert [e for e in after if isinstance(e, Merged)]
    assert not [e for e in after if isinstance(e, Escalated)]


def test_with_no_ladder_a_machine_end_is_retried_once_at_once_then_halts_the_run(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, reviewer=_down(2), delays=())
    events = _run(rig)
    assert len(rig.reviewer.seen) == 2
    assert _retries(events) == [("infrastructure", True)]
    assert _halts(events) == ["infrastructure_exhausted"]
    assert not [e for e in events if isinstance(e, Escalated | Merged)]
    assert rig.slept == []
    after = _resumed(rig)
    assert [e for e in after if isinstance(e, Merged)]


def test_with_a_ladder_of_two_a_machine_end_is_tried_three_times_more_then_halts_the_run(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, reviewer=_down(4), delays=(30.0, 60.0))
    events = _run(rig)
    assert len(rig.reviewer.seen) == 4, "the first end, one retry at once, then the ladder's two"
    assert _retries(events) == [("infrastructure", True)] * 3
    assert rig.slept == [30.0, 60.0]
    assert _halts(events) == ["infrastructure_exhausted"]
    assert not [e for e in events if isinstance(e, Escalated | Merged)]


def test_a_review_the_ladder_lets_pass_merges_and_halts_nothing(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=_down(3), delays=(30.0, 60.0))
    events = _run(rig)
    assert len(rig.reviewer.seen) == 4
    assert rig.slept == [30.0, 60.0]
    assert _halts(events) == []
    assert [e for e in events if isinstance(e, Merged)]


@pytest.mark.parametrize(
    ("session_cause", "halt"),
    [("sandbox_unavailable", "os_layer_unavailable"), ("disk_full", "disk_full")],
)
def test_an_os_layer_or_a_full_disk_halts_the_run_as_a_role_session_s_end_does(
    tmp_path: Path, session_cause: str, halt: str
) -> None:
    rig = Rig(tmp_path, reviewer=_down(1, session_cause), delays=(30.0,))
    events = _run(rig)
    assert len(rig.reviewer.seen) == 1
    assert _halts(events) == [halt]
    assert not [e for e in events if isinstance(e, Escalated)]


@pytest.mark.parametrize("cause", ["no_verdict", "invalid_verdict", "refused"])
def test_a_review_with_no_verdict_for_its_own_reasons_still_goes_to_a_person(
    tmp_path: Path, cause: str
) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _ended(cause, None, 1)}))
    events = _run(rig)
    assert len(rig.reviewer.seen) == 1
    assert _retries(events) == [(cause, False)]
    assert _halts(events) == []
    assert [e for e in events if isinstance(e, Escalated)]


def test_a_log_recorded_with_one_retry_and_then_a_final_machine_end_still_replays(
    tmp_path: Path,
) -> None:
    # The shape every run before this rule recorded for a review the machine ended twice: a retry
    # line, then a final one of the same cause, which ends the attempt for a person. Made here from
    # a retry followed by a final end of the reviewer's own, whose cause is then written as the
    # machine's, as the earlier loop wrote it; the log is read up to that line.
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(
            unavailable={
                1: _ended("infrastructure", "api_error", 1),
                2: _ended("no_verdict", None, 2),
            }
        ),
    )
    _run(rig)
    log = tmp_path / "events.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    end = next(
        k for k, x in enumerate(lines) if x["kind"] == "review_unavailable" and not x["retry"]
    )
    lines = lines[: end + 1]
    lines[end]["cause"] = "infrastructure"
    log.write_text("".join(json.dumps(x) + "\n" for x in lines))
    events = read_events(log)
    assert _retries(events) == [("infrastructure", True), ("infrastructure", False)]
    now = replay(events).subtasks["s1"].attempts[-1]
    assert now.unavailable_final is not None
