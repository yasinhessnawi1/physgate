"""The loop over fakes: gate before review, three attempts then the queue, merge rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    AttemptRejected,
    GateRan,
    GateSkipped,
    Merged,
    ReviewRan,
    StageEntered,
    read_events,
)
from physgate.orchestrator.exceptions import (
    GateNotRegisteredError,
    MergePreconditionError,
    ModelSeparationError,
    ReviewerNotRegisteredError,
)
from physgate.orchestrator.replay import RunState, project_ledger, require_mergeable
from physgate.orchestrator.run_config import ModelStrings
from physgate.state.task_ledger import TaskLedger, TaskLine

pytestmark = pytest.mark.injected


def test_a_gate_failed_attempt_is_never_reviewed_and_spends_no_review_tokens(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate=FakeGate(verdicts=["fail", "fail", "fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    step = loop.run()
    loop.close()
    assert step.kind == "done"
    assert len(rig.gate.seen) == 3  # type: ignore[union-attr]
    assert rig.reviewer.seen == []
    events = read_events(tmp_path / "events.jsonl")
    assert not [e for e in events if isinstance(e, ReviewRan)]
    kinds = TokenAccount.from_events(events).by_kind()
    assert kinds["reviewer"].total() == 0
    assert kinds["session"].total() > 0


def test_three_rejections_repair_by_template_then_escalate_with_the_five_things(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate=FakeGate(verdicts=["fail", "fail", "fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    instructions = [r.repair_instruction for r in rig.dispatcher.requests]
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 2, 3]
    assert instructions[0] is None
    assert instructions[1] is not None and "Finding: the stall current" in instructions[1]
    assert "Failing check" not in instructions[1]
    assert instructions[2] is not None and "Failing check: bounds" in instructions[2]
    assert "Computed value: 3.4 A" in instructions[2]
    queue = loop.queue.open_items()
    assert len(queue) == 1
    item = queue[0]
    assert item.decision_required and item.artefact_diff.startswith("diff --git")
    assert item.triggering_finding == "the stall current exceeds the driver's rating"
    assert [q.name for q in item.quantities] == ["stall_current"]
    assert len(item.trajectories) == 3
    assert loop.state.subtasks["s1"].status == "escalated"
    assert rig.merger.merges == []


def test_no_fourth_attempt_exists_even_in_the_record(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate=FakeGate(verdicts=["fail", "fail", "fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    with pytest.raises(ValueError):
        loop.log.emit(StageEntered, subtask_id="s1", attempt=4, stage="resolve")
    with pytest.raises(ValueError, match="cannot start"):
        loop.log.emit(StageEntered, subtask_id="s1", attempt=3, stage="resolve")
    loop.close()
    rejections = [
        e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, AttemptRejected)
    ]
    assert [e.attempt for e in rejections] == [1, 2, 3]


def test_a_merge_happens_only_once_the_ledger_on_disk_shows_both_results(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    (line,) = rig.merger.ledger_at_merge
    assert line.gate_result == "pass" and line.review_result == "pass"
    (message,) = rig.merger.messages
    assert (
        message.startswith("Merge subtask s1, attempt 1") and "Gate: pass. Review: pass." in message
    )
    final = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert final is not None and final.merge_commit is not None


def _forge(path: Path, **fields: object) -> Path:
    base: dict[str, object] = {
        "id": "s1",
        "spec_path": "specs/s1.md",
        "assigned_role": "electrical",
        "attempt_count": 1,
    }
    ledger = TaskLedger(path)
    ledger.append(TaskLine.model_validate(base | fields))
    ledger.close()
    return path


@pytest.mark.parametrize(
    ("mode", "fields"),
    [
        ("on", {"gate_result": "pass"}),
        ("on", {"review_result": "pass"}),
        ("on", {}),
        ("on", {"gate_result": "fail", "review_result": "pass"}),
        ("on", {"gate_result": "skipped", "review_result": "pass"}),
        ("on", {"gate_result": "pass", "review_result": "fail"}),
        ("observe", {"gate_result": "skipped", "review_result": "pass"}),
        ("off", {"gate_result": "pass", "review_result": "pass"}),
    ],
    ids=[
        "no review result",
        "no gate result",
        "neither",
        "a failed gate while it blocks",
        "a skipped gate while it blocks",
        "a failed review",
        "a skipped gate while it observes",
        "a pass while the gate is off",
    ],
)
def test_a_forged_ledger_line_is_refused_at_merge(
    tmp_path: Path, mode: str, fields: dict[str, object]
) -> None:
    path = _forge(tmp_path / "ledger.jsonl", **fields)
    with pytest.raises(MergePreconditionError):
        require_mergeable(path, "s1", mode)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mode", "gate_result"), [("on", "pass"), ("observe", "fail"), ("off", "skipped")]
)
def test_a_line_the_mode_allows_is_mergeable(tmp_path: Path, mode: str, gate_result: str) -> None:
    path = _forge(tmp_path / "ledger.jsonl", gate_result=gate_result, review_result="pass")
    assert require_mergeable(path, "s1", mode).id == "s1"  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["on", "observe"])
def test_the_loop_refuses_to_start_without_a_gate_in_a_mode_that_needs_one(
    tmp_path: Path, mode: str
) -> None:
    with pytest.raises(GateNotRegisteredError, match="no gate is registered"):
        Rig(tmp_path, gate_mode=mode, gate=None).open()  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []


def test_with_the_gate_off_the_stage_is_skipped_on_the_record_and_review_still_runs(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate_mode="off", gate=None)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    skipped = [e for e in events if isinstance(e, GateSkipped)]
    assert [(e.attempt, e.reason) for e in skipped] == [(1, "gate_mode=off")]
    assert not [e for e in events if isinstance(e, GateRan)]
    assert len(rig.reviewer.seen) == 1
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.gate_result == "skipped" and line.merge_commit


def test_a_registered_gate_is_never_called_when_the_gate_is_off(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate_mode="off")
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    assert rig.gate is not None and rig.gate.seen == []


def test_an_observing_gate_logs_its_failure_and_does_not_block(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate_mode="observe", gate=FakeGate(verdicts=["fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, GateRan)]
    assert ran.result.verdict == "fail" and ran.result.mode == "observe"
    assert [e for e in events if isinstance(e, Merged)]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.gate_result == "fail" and line.merge_commit


def test_a_reviewer_on_the_implementers_model_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(model="claude-sonnet-4-5"),
        config_overrides={"models": _models(reviewer="claude-sonnet-4-5")},
    )
    with pytest.raises(ModelSeparationError):
        rig.open()
    assert not (tmp_path / "run.json").exists()


def test_a_reviewer_not_on_its_pinned_model_is_refused(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(model="claude-haiku-4-5"))
    with pytest.raises(ReviewerNotRegisteredError):
        rig.open()


def _models(*, reviewer: str) -> ModelStrings:
    return ModelStrings(
        decomposition="claude-opus-5",
        roles={"electrical": "claude-sonnet-4-5"},
        reviewers={"electrical": reviewer},
    )


def test_a_rejecting_reviewer_spends_an_attempt_and_its_tokens_are_its_own(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(verdicts=["fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 2]
    second = rig.dispatcher.requests[1].repair_instruction
    assert second is not None and "rejected by the reviewer" in second
    account = TokenAccount.from_events(read_events(tmp_path / "events.jsonl"))
    assert set(account.by_attribution()) == {
        "session:sess-1",
        "session:sess-2",
        "reviewer:rev-1",
        "reviewer:rev-2",
    }
    account.assert_no_routing()


def test_a_ledger_that_lost_the_review_result_stops_the_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The injected fault: the ledger on disk never receives the review result,
    # as if the projection had been skipped or the file edited. The loop reads the
    # ledger back before merging, so the merge must not happen.
    import physgate.orchestrator.record as loop_module

    def losing_review_lines(state: RunState, ledger: TaskLedger) -> int:
        kept = [line for line in state.ledger if line.review_result is None]
        shadow = RunState()
        shadow.ledger = kept
        return project_ledger(shadow, ledger)

    monkeypatch.setattr(loop_module, "project_ledger", losing_review_lines)
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(MergePreconditionError):
        loop.run()
    loop.close()
    assert rig.merger.merges == []


def test_a_reviewer_whose_model_changes_after_start_is_refused_at_the_review(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    rig.reviewer.model = "claude-sonnet-4-5"
    with pytest.raises(ModelSeparationError):
        loop.run()
    loop.close()
    assert rig.reviewer.seen == []


def test_a_ledger_holding_a_line_the_log_does_not_imply_refuses_the_run(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    _forge(tmp_path / "ledger.jsonl", gate_result="pass", review_result="pass")
    with pytest.raises(MergePreconditionError, match="disagrees"):
        rig.open()


def test_each_rejection_carries_its_finding_key_and_whether_it_repeats(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate=FakeGate(verdicts=["pass", "fail", "fail"]))
    rig.reviewer.verdicts = ["fail"]
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    rejected = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, AttemptRejected)]
    assert [e.finding_key for e in rejected] == [
        "review|-|-",
        "gate|motor.left|bounds",
        "gate|motor.left|bounds",
    ]
    assert [e.repeats_previous for e in rejected] == [False, False, True]


def test_the_record_refuses_a_rejection_whose_key_or_repeat_flag_is_wrong(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate=FakeGate(verdicts=["fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    real_emit = loop.record.log.emit
    calls: list[str] = []

    def lying_emit(kind: Any, **fields: Any) -> Any:
        if kind is AttemptRejected and not calls:
            calls.append("lied")
            with pytest.raises(ValueError, match="key"):
                real_emit(kind, **{**fields, "repeats_previous": True})
            with pytest.raises(ValueError, match="key"):
                real_emit(kind, **{**fields, "finding_key": "gate|-|-"})
        return real_emit(kind, **fields)

    loop.record.log.emit = lying_emit  # type: ignore[method-assign]
    loop.run()
    loop.close()
    assert calls == ["lied"]
