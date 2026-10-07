"""A review with no verdict goes to a person, spends no repair attempt, and is never a pass.

Blocked (a safety-critical check the issued specification gives no input for), an
invalid or missing verdict, unfinished reading, a compacted or overflowing
session: each escalates at once. An infrastructure failure is retried once, and
escalates if the retry fails too. In every case catch accounting records no
reviewer verdict for the attempt. A reject that also carries a blocking defect is
an ordinary reject, whose repair instruction names the defect.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    Event,
    GateRan,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import (
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)
from physgate.orchestrator.replay import RunState

BLOCKING = SpecDefect(finding="no unstable pole is given", blocking=True, item="DS-4")


def _unavailable(cause: str, **extra: object) -> ReviewUnavailableError:
    return ReviewUnavailableError(
        f"the review reached no verdict: {cause}",
        cause=cause,  # type: ignore[arg-type]
        session_id=f"rev-{cause}",
        reviewer_model="claude-opus-5-5",
        usage=(
            MessageUsage(
                message_id=f"u-{cause}",
                usage=Usage(
                    input_tokens=5,
                    output_tokens=1,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            ),
        ),
        **extra,  # type: ignore[arg-type]
    )


def _run(tmp_path: Path, reviewer: FakeReviewer) -> list[Event]:
    rig = Rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    rig_requests.append(len(rig.dispatcher.requests))
    return read_events(tmp_path / "events.jsonl")


rig_requests: list[int] = []


@pytest.mark.parametrize(
    "cause",
    [
        "blocking_spec_defect",
        "invalid_verdict",
        "no_verdict",
        "reading_incomplete",
        "compacted",
        "context_exceeded",
        "refused",
        "unprepared",
    ],
)
def test_a_final_cause_escalates_at_once_and_spends_no_attempt(tmp_path: Path, cause: str) -> None:
    extra = {"spec_defects": (BLOCKING,)} if cause == "blocking_spec_defect" else {}
    reviewer = FakeReviewer(unavailable={1: _unavailable(cause, **extra)})
    events = _run(tmp_path, reviewer)
    unavailable = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert [(u.cause, u.retry) for u in unavailable] == [(cause, False)]
    assert [e for e in events if isinstance(e, Escalated)]
    assert not [e for e in events if isinstance(e, AttemptRejected | Merged | ReviewRan)]
    assert rig_requests[-1] == 1 and len(reviewer.seen) == 1  # one session, one review
    spent = [
        e for e in events if isinstance(e, TokensUsed) and e.attribution.startswith("reviewer:")
    ]
    assert [e.message_id for e in spent] == [f"u-{cause}"]


def test_the_queue_item_names_what_the_issued_specification_lacks(tmp_path: Path) -> None:
    reviewer = FakeReviewer(
        unavailable={1: _unavailable("blocking_spec_defect", spec_defects=(BLOCKING,))}
    )
    rig = Rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    (item,) = loop.queue.open_items()
    loop.close()
    assert item.source == "review_unavailable"
    assert "no unstable pole is given" in item.decision_required
    assert "No repair attempt was spent" in item.decision_required
    assert loop.state.subtasks["s1"].status == "escalated"


def test_infrastructure_is_retried_once_then_the_verdict_stands(tmp_path: Path) -> None:
    reviewer = FakeReviewer(unavailable={1: _unavailable("infrastructure")})
    events = _run(tmp_path, reviewer)
    assert [(e.cause, e.retry) for e in events if isinstance(e, ReviewUnavailable)] == [
        ("infrastructure", True)
    ]
    assert any(isinstance(e, ReviewRan) for e in events)
    assert any(isinstance(e, Merged) for e in events)


def test_infrastructure_twice_escalates(tmp_path: Path) -> None:
    reviewer = FakeReviewer(
        unavailable={1: _unavailable("infrastructure"), 2: _unavailable("infrastructure")}
    )
    events = _run(tmp_path, reviewer)
    assert [(e.cause, e.retry) for e in events if isinstance(e, ReviewUnavailable)] == [
        ("infrastructure", True),
        ("infrastructure", False),
    ]
    assert [e for e in events if isinstance(e, Escalated)]
    assert not [e for e in events if isinstance(e, Merged | AttemptRejected)]


def test_catch_accounting_records_no_reviewer_verdict_for_it(tmp_path: Path) -> None:
    reviewer = FakeReviewer(
        unavailable={1: _unavailable("blocking_spec_defect", spec_defects=(BLOCKING,))}
    )
    rig = Rig(tmp_path, reviewer=reviewer, gate_mode="observe")
    rig.gate = FakeGate(verdicts=["fail"])
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e for e in events if isinstance(e, GateRan)]
    stamped = gate_events(events, "d" * 64)
    assert stamped and all(e.reviewer_had_passed is None for e in stamped)


def test_a_reject_beside_a_blocking_defect_is_an_ordinary_reject(tmp_path: Path) -> None:
    rejecting = ReviewResult(
        verdict="fail",
        finding="the gain is outside its range",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=(),
        failing_item="AC-1",
        items=(
            ItemVerdict(item="AC-1", section="acceptance_criteria", result="unmet", evidence="x:1"),
        ),
        spec_defects=(BLOCKING,),
    )
    rig = Rig(tmp_path, reviewer=FakeReviewer(results={1: rejecting}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e.attempt for e in events if isinstance(e, AttemptRejected)][:1] == [1]
    second = rig.dispatcher.requests[1].repair_instruction or ""
    assert "no unstable pole is given" in second and "Do not supply the missing input" in second
    assert not [e for e in events if isinstance(e, ReviewUnavailable)]


def test_the_record_refuses_a_verdict_or_another_try_after_no_verdict(tmp_path: Path) -> None:
    reviewer = FakeReviewer(
        unavailable={1: _unavailable("infrastructure"), 2: _unavailable("infrastructure")}
    )
    events = _run(tmp_path, reviewer)
    final = max(i for i, e in enumerate(events) if isinstance(e, ReviewUnavailable))
    state = RunState()
    for event in events[: final + 1]:
        state.record(event)
    last = events[final]
    assert isinstance(last, ReviewUnavailable) and not last.retry
    review = ReviewRan(
        **last.model_dump(include={"seq", "ts", "run_id", "gate_mode", "subtask_id", "attempt"}),
        result=ReviewResult(
            verdict="pass", finding="ok", reviewer_model="claude-opus-5-5", session_id="x", usage=()
        ),
    )
    with pytest.raises(ValueError, match="a review line"):
        state.check(review)
    with pytest.raises(ValueError, match="an unavailable review"):
        state.check(last.model_copy(update={"retry": True}))
    with pytest.raises(ValueError, match="only an infrastructure failure"):
        ReviewUnavailable(**{**last.model_dump(), "cause": "invalid_verdict", "retry": True})
