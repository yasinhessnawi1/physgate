"""A blocked review is a review: on the log as one, and routed to a person.

Blocked means a safety-critical check the issued specification gives no input for,
and nothing the attempt did wrong. The review line records it with its verdict,
its model, its tokens and its defects, the same as a pass or a fail. Its routing
is the one a review with no verdict gets: the subtask goes to the approval queue
at once, no repair attempt is spent, and catch accounting records no reviewer
verdict for the attempt, never a pass or a fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGate, FakeReviewer, KilledError, Rig, plan

from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    GateRan,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    StageEntered,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import (
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)
from physgate.orchestrator.replay import RunState
from physgate.state.task_ledger import TaskLedger

BLOCKING = SpecDefect(finding="no unstable pole is given", blocking=True, item="DS-4")
NOTE = SpecDefect(finding="the sample rate is stated twice", blocking=False)


def blocked_review(*defects: SpecDefect) -> ReviewResult:
    return ReviewResult(
        verdict="blocked",
        finding="the stability check cannot be decided: no unstable pole is given",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=(
            MessageUsage(
                message_id="b-1",
                usage=Usage(
                    input_tokens=9,
                    output_tokens=2,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            ),
        ),
        items=(
            ItemVerdict(
                item="DS-4", section="domain_standards", result="not evaluable", evidence="spec:3"
            ),
        ),
        spec_defects=defects or (BLOCKING,),
    )


def _rig(tmp_path: Path, **extra: object) -> Rig:
    reviewer = FakeReviewer(results={1: blocked_review()})
    return Rig(tmp_path, reviewer=reviewer, **extra)  # type: ignore[arg-type]


def test_a_blocked_review_is_on_the_log_as_a_review(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    assert ran.result.verdict == "blocked"
    assert ran.result.reviewer_model == "claude-opus-5-5"
    assert ran.result.spec_defects == (BLOCKING,)
    assert not [e for e in events if isinstance(e, ReviewUnavailable)]
    spent = [e for e in events if isinstance(e, TokensUsed) and e.attribution == "reviewer:rev-1"]
    assert [e.message_id for e in spent] == ["b-1"]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.review_result == "blocked" and line.merge_commit is None


def test_it_goes_to_a_person_at_once_and_spends_no_attempt(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    (item,) = loop.queue.open_items()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e for e in events if isinstance(e, Escalated)]
    assert not [e for e in events if isinstance(e, AttemptRejected | Merged)]
    decided = [e for e in events if isinstance(e, StageEntered) and e.stage == "decide"]
    assert not decided
    assert len(rig.dispatcher.requests) == 1 and len(rig.reviewer.seen) == 1
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1
    assert loop.state.subtasks["s1"].status == "escalated"
    assert item.source == "review_blocked"
    assert "was blocked" in item.decision_required
    assert "no unstable pole is given" in item.decision_required
    assert "No repair attempt was spent" in item.decision_required
    assert item.triggering_finding == blocked_review().finding


def test_a_non_blocking_defect_beside_it_is_a_note_on_the_item(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(results={1: blocked_review(BLOCKING, NOTE)}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    (item,) = loop.queue.open_items()
    loop.close()
    assert "Notes: specification defect: the sample rate is stated twice" in item.decision_required


def test_catch_accounting_records_no_reviewer_verdict_for_it(tmp_path: Path) -> None:
    rig = _rig(tmp_path, gate_mode="observe")
    rig.gate = FakeGate(verdicts=["fail"])
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e for e in events if isinstance(e, GateRan)]
    assert [e.result.verdict for e in events if isinstance(e, ReviewRan)] == ["blocked"]
    stamped = gate_events(events, "d" * 64)
    assert stamped
    assert {(e.reviewer_had_passed, e.reviewer_basis, e.review_seq) for e in stamped} == {
        (None, None, None)
    }


def test_a_process_killed_before_the_escalation_escalates_on_resume_without_reviewing_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))

    def killed(self: Loop, subtask_id: str, blocked: ReviewRan) -> None:
        raise KilledError

    with monkeypatch.context() as patch:
        patch.setattr(Loop, "_escalate_blocked", killed)
        with pytest.raises(KilledError):
            loop.run()
    loop.close()
    again = rig.open()
    again.run()
    (item,) = again.queue.open_items()
    again.close()
    assert item.source == "review_blocked"
    events = read_events(tmp_path / "events.jsonl")
    assert len([e for e in events if isinstance(e, ReviewRan)]) == 1
    assert len(rig.reviewer.seen) == 1 and len(rig.dispatcher.requests) == 1
    assert [e for e in events if isinstance(e, Escalated)]


def test_the_record_refuses_a_merge_decision_or_another_review_after_it(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    at = next(i for i, e in enumerate(events) if isinstance(e, ReviewRan))
    state = RunState()
    for event in events[: at + 1]:
        state.record(event)
    assert state.next_step().kind == "escalate"
    assert state.interrupted() is None
    ran = events[at]
    assert isinstance(ran, ReviewRan)
    envelope = ran.model_dump(include={"seq", "ts", "run_id", "gate_mode"})
    decide = StageEntered(
        **{**envelope, "seq": ran.seq + 1}, subtask_id="s1", attempt=1, stage="decide"
    )
    with pytest.raises(ValueError, match="cannot follow"):
        state.check(decide)
    again = ran.model_copy(update={"seq": ran.seq + 1})
    with pytest.raises(ValueError, match="a review line cannot come"):
        state.check(again)


def test_a_blocked_result_carries_a_blocking_defect_and_no_rejecting_finding() -> None:
    with pytest.raises(ValueError, match="blocked is a blocking specification defect"):
        blocked_review(NOTE)
    unmet = ItemVerdict(item="AC-1", section="acceptance_criteria", result="unmet", evidence="x")
    fields = blocked_review().model_dump(exclude={"usage", "items", "spec_defects"})
    with pytest.raises(ValueError, match="blocked is a blocking specification defect"):
        ReviewResult(**fields, usage=(), items=(unmet,), spec_defects=(BLOCKING,))


def test_a_review_with_no_verdict_cannot_say_it_was_blocked() -> None:
    """``review_unavailable`` is for no verdict at all; blocked has no cause of its own there."""
    fields: dict[str, Any] = {
        "seq": 1,
        "ts": "2026-10-08T00:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "subtask_id": "s1",
        "attempt": 1,
        "detail": "no verdict",
        "retry": False,
        "session_id": "rev-1",
        "reviewer_model": "claude-opus-5-5",
    }
    assert ReviewUnavailable(**fields, cause="no_verdict").cause == "no_verdict"
    with pytest.raises(ValueError, match=r"1 validation error for ReviewUnavailable\ncause"):
        ReviewUnavailable(**fields, cause="blocking_spec_defect")  # type: ignore[arg-type]
