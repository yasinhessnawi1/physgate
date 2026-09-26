"""The loop's position comes from its file: resume, infrastructure, halts, the ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeGraph, FakeReviewer, KilledError, Rig, plan

from physgate.orchestrator.events import (
    DiffChecked,
    EventLog,
    Halted,
    Incident,
    InfraRetryScheduled,
    Resumed,
    SessionEnded,
    StageEntered,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, RunStateError
from physgate.orchestrator.replay import RunState
from physgate.state.task_ledger import TaskLedger

EIGHT = ["resolve", "spawn", "verify_reading", "implement", "gate", "review", "decide", "diff"]


def stages(path: Path, subtask: str) -> list[str]:
    return [
        e.stage
        for e in read_events(path)
        if isinstance(e, StageEntered) and e.subtask_id == subtask
    ]


def test_a_merged_attempt_passes_the_eight_stages_in_order_each_a_timestamped_line(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    assert stages(tmp_path / "events.jsonl", "s1") == EIGHT
    assert stages(tmp_path / "events.jsonl", "s2") == EIGHT
    assert all(e.ts.endswith("Z") for e in read_events(tmp_path / "events.jsonl"))


def test_the_ledger_counts_dispatched_subtasks_and_a_removed_one_is_a_missing_id(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1", "s2", "s3"))
    loop.remove("s2", "the brief no longer needs it")
    loop.run()
    loop.close()
    lines = TaskLedger(tmp_path / "ledger.jsonl").read_all()
    dispatched = {line.id for line in lines if line.attempt_count >= 1}
    assert dispatched == {"s1", "s3"}
    assert len(dispatched) == len({r.subtask_id for r in rig.dispatcher.requests})
    assert [(line.id, line.attempt_count) for line in lines if line.id == "s2"] == [("s2", 0)]
    with pytest.raises(ValueError, match="only a subtask not yet dispatched"):
        reopened = rig.open()
        reopened.remove("s1", "too late")


def test_a_fresh_process_rebuilds_the_same_state_and_ledger_from_the_log(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(verdicts=["fail"]))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    loop.run()
    written = list(loop.state.ledger)
    loop.close()
    replayed = RunState()
    EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on", state=replayed).close()
    assert replayed.ledger == written
    assert TaskLedger(tmp_path / "ledger.jsonl").read_all() == written
    assert replayed.next_step().kind == "done"


def test_a_kill_after_the_session_resumes_at_its_checkpoint_without_a_new_session(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(kill_on=1))
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    rig.reviewer.kill_on = None
    again = rig.open()
    with pytest.raises(RunStateError, match="interrupted"):
        again.run()
    assert again.resume().kind == "done"
    again.close()
    events = read_events(tmp_path / "events.jsonl")
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert (resumed.attempt, resumed.point) == (1, "verify_reading")
    assert len(rig.dispatcher.requests) == 1
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1 and line.merge_commit


def test_a_kill_inside_the_session_resumes_with_a_fresh_session_on_the_same_attempt(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(kill_on=1))
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]
    (resumed,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Resumed)]
    assert resumed.point == "resolve"


def test_an_infrastructure_failure_retries_the_same_attempt_and_spends_no_budget(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "api_error"}), delays=(60.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    assert rig.slept == [60.0]
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]
    events = read_events(tmp_path / "events.jsonl")
    ended = [(e.outcome, e.cause) for e in events if isinstance(e, SessionEnded)]
    assert ended == [("infrastructure", "api_error"), ("completed", None)]
    assert [e.delay_s for e in events if isinstance(e, InfraRetryScheduled)] == [60.0]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1


@pytest.mark.parametrize("cause", ["wall_clock", "turn_limit", "no_result", "unexpected_exit"])
def test_every_infrastructure_cause_is_recorded_and_none_spends_an_attempt(
    tmp_path: Path, cause: str
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: cause}), delays=(1.0,))  # type: ignore[dict-item]
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    causes = [
        e.cause for e in read_events(tmp_path / "events.jsonl") if isinstance(e, SessionEnded)
    ]
    assert causes == [cause, None]
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1]


def test_an_exhausted_schedule_halts_the_run_and_resume_continues_the_same_attempt(
    tmp_path: Path,
) -> None:
    rig = Rig(
        tmp_path, dispatcher=FakeDispatcher(infra={1: "api_error", 2: "api_error"}), delays=(5.0,)
    )
    loop = rig.open()
    loop.start(plan("s1"))
    step = loop.run()
    loop.close()
    assert step.kind == "halted"
    (halt,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Halted)]
    assert halt.reason == "infrastructure_exhausted"
    assert "api_error after 1 infrastructure retries" in halt.detail
    assert rig.open().run().kind == "halted"
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 1, 1]
    assert rig.slept == [5.0]
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.attempt_count == 1 and line.merge_commit


def test_a_cross_role_write_halts_the_run_before_the_next_dispatch(tmp_path: Path) -> None:
    rig = Rig(tmp_path, diff=FakeGraph(divergent={1: ("motor.left written by control",)}))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "halted"
    loop.close()
    assert {r.subtask_id for r in rig.dispatcher.requests} == {"s1"}
    events = read_events(tmp_path / "events.jsonl")
    assert [e.divergences for e in events if isinstance(e, DiffChecked)] == [
        ("motor.left written by control",)
    ]
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "cross_role_write"
    with pytest.raises(RunStateError, match="halted for incident"):
        rig.open().resume()


def test_reading_not_completed_is_a_rejected_attempt_with_a_reason(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(unread={1}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    second = rig.dispatcher.requests[1].repair_instruction
    assert second is not None and "required reading" in second
    assert rig.gate is not None and len(rig.gate.seen) == 1


def _started(tmp_path: Path) -> EventLog:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    return EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on", state=RunState())


@pytest.mark.parametrize(
    ("stage", "attempt"),
    [("spawn", 1), ("gate", 1), ("review", 1), ("decide", 1), ("diff", 1), ("resolve", 2)],
)
def test_a_stage_out_of_order_is_refused_at_write_time(
    tmp_path: Path, stage: str, attempt: int
) -> None:
    log = _started(tmp_path)
    with pytest.raises(ValueError):
        log.emit(StageEntered, subtask_id="s1", attempt=attempt, stage=stage)
    log.close()


def test_a_file_with_a_stage_out_of_order_does_not_open(tmp_path: Path) -> None:
    log = _started(tmp_path)
    log.close()
    raw = (tmp_path / "events.jsonl").read_bytes().splitlines(keepends=True)
    forged = raw[-1].replace(b'"subtask_planned"', b'"stage_entered"')
    line = (
        b'{"seq": %d, "ts": "2026-09-26T12:00:01.000000Z", "run_id": "run-1", "gate_mode": "on", '
        b'"kind": "stage_entered", "subtask_id": "s1", "attempt": 1, "stage": "review"}\n'
    ) % len(raw)
    assert forged
    (tmp_path / "events.jsonl").write_bytes(b"".join(raw) + line)
    with pytest.raises(CorruptEventLogError):
        EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on", state=RunState())


def test_nothing_but_a_resume_may_follow_a_halt(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "api_error"}), delays=())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    with pytest.raises(ValueError, match="halted"):
        loop.log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
    loop.close()


def _through_the_gate(log: EventLog, verdict_fails: bool) -> None:
    from loop_fakes import failing_gate_result, sha

    from physgate.orchestrator.events import GateRan, ProposalsChecked
    from physgate.orchestrator.protocols import GateResult, RunningGateMode

    for stage in ("resolve", "spawn"):
        log.emit(StageEntered, subtask_id="s1", attempt=1, stage=stage)
    log.emit(
        SessionEnded,
        subtask_id="s1",
        attempt=1,
        session_id="sess-1",
        outcome="completed",
        cause=None,
        attempt_commit=sha("c"),
        trajectory="t",
        worktree="w",
        reading_verified=True,
    )
    for stage in ("verify_reading", "implement"):
        log.emit(StageEntered, subtask_id="s1", attempt=1, stage=stage)
    log.emit(
        ProposalsChecked,
        subtask_id="s1",
        attempt=1,
        checked_commit=sha("c"),
        refused_by=None,
        reason=None,
        subject=None,
        graph_root="g",
    )
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="gate")
    mode: RunningGateMode = "on"
    result = (
        failing_gate_result(mode)
        if verdict_fails
        else GateResult(
            verdict="pass",
            mode=mode,
            finding="ok",
            failing_check=None,
            numeric_output=None,
            quantities=(),
        )
    )
    log.emit(GateRan, subtask_id="s1", attempt=1, result=result)


def test_the_record_refuses_a_review_after_a_blocking_gate_failed(tmp_path: Path) -> None:
    log = _started(tmp_path)
    _through_the_gate(log, verdict_fails=True)
    with pytest.raises(ValueError, match="'review' cannot follow"):
        log.emit(StageEntered, subtask_id="s1", attempt=1, stage="review")
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="decide")
    log.close()


def test_the_record_allows_a_review_after_a_passing_gate(tmp_path: Path) -> None:
    log = _started(tmp_path)
    _through_the_gate(log, verdict_fails=False)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="review")
    log.close()


def test_the_record_refuses_a_merge_of_any_commit_but_the_checked_one(tmp_path: Path) -> None:
    from loop_fakes import sha

    from physgate.orchestrator.events import Merged, ReviewRan
    from physgate.orchestrator.protocols import ReviewResult

    log = _started(tmp_path)
    _through_the_gate(log, verdict_fails=False)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="review")
    review = ReviewResult(
        verdict="pass", finding="ok", reviewer_model="claude-opus-5", session_id="r", usage=()
    )
    log.emit(ReviewRan, subtask_id="s1", attempt=1, result=review)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="decide")
    with pytest.raises(ValueError, match="other than the one that was checked"):
        log.emit(
            Merged,
            subtask_id="s1",
            attempt=1,
            attempt_commit=sha("something else"),
            merge_commit=sha("m"),
        )
    log.emit(Merged, subtask_id="s1", attempt=1, attempt_commit=sha("c"), merge_commit=sha("m"))
    log.close()


def _to_decide(tmp_path: Path) -> EventLog:
    from physgate.orchestrator.events import ReviewRan
    from physgate.orchestrator.protocols import ReviewResult

    log = _started(tmp_path)
    _through_the_gate(log, verdict_fails=False)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="review")
    review = ReviewResult(
        verdict="pass", finding="ok", reviewer_model="claude-opus-5", session_id="r", usage=()
    )
    log.emit(ReviewRan, subtask_id="s1", attempt=1, result=review)
    log.emit(StageEntered, subtask_id="s1", attempt=1, stage="decide")
    return log


def _intent(
    log: EventLog, node_id: str = "electrical.x", expected: int = 1, role: str = "electrical"
) -> None:
    from physgate.orchestrator.events import WriteIntended

    log.emit(
        WriteIntended,
        subtask_id="s1",
        attempt=1,
        node_id=node_id,
        payload_sha256="d" * 64,
        actor_role=role,
        expected_revision=expected,
    )


def test_the_record_holds_every_store_write_to_its_intent(tmp_path: Path) -> None:
    from loop_fakes import sha

    from physgate.orchestrator.events import Merged, WriteDone

    log = _to_decide(tmp_path)
    with pytest.raises(ValueError, match="write intent"):
        _intent(log, expected=2)  # not the next revision
    with pytest.raises(ValueError, match="write intent"):
        _intent(log, role="control")  # not the subtask's role
    _intent(log)
    with pytest.raises(ValueError, match="write intent"):
        _intent(log, node_id="electrical.y", expected=2)  # one pending at a time
    with pytest.raises(ValueError, match="other than|unaccounted"):
        log.emit(Merged, subtask_id="s1", attempt=1, attempt_commit=sha("c"), merge_commit=sha("m"))
    with pytest.raises(ValueError, match="a write cannot"):
        log.emit(WriteDone, subtask_id="s1", attempt=1, node_id="electrical.x", revision=2)
    log.emit(WriteDone, subtask_id="s1", attempt=1, node_id="electrical.x", revision=1)
    with pytest.raises(ValueError, match="write intent"):
        _intent(log, expected=2)  # the same node twice in one attempt
    log.emit(Merged, subtask_id="s1", attempt=1, attempt_commit=sha("c"), merge_commit=sha("m"))
    log.close()


def test_a_node_file_repair_is_recorded_only_between_the_session_and_its_judgement(
    tmp_path: Path,
) -> None:
    from physgate.orchestrator.events import NodeFilesRepaired

    log = _to_decide(tmp_path)
    with pytest.raises(ValueError, match="node-file repair"):
        log.emit(NodeFilesRepaired, subtask_id="s1", attempt=1, repaired=1, quarantined=())
    log.close()


class _ForeignAtOpen(FakeGraph):
    """A journal holding one line nobody intended, found before any subtask is active."""

    def records_after(self, revision: int) -> list[Any]:
        from types import SimpleNamespace

        line = SimpleNamespace(rev=revision + 1, op="write", node_id="electrical.x", payload={})
        return [line]


def test_a_foreign_line_found_when_no_subtask_is_active_is_an_incident_with_no_subtask(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, diff=_ForeignAtOpen())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.subtask_id is None and incident.cause == "foreign_journal_line"
    assert rig.dispatcher.requests == []


class _Unrecoverable(FakeGraph):
    def reopen(self) -> tuple[int, tuple[str, ...]]:
        from physgate.state.exceptions import CorruptRecordError

        raise CorruptRecordError("a node file the journal never named", path="nodes/x.json")


def test_node_files_that_recovery_cannot_repair_halt_the_run_as_an_incident(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(halted={1}), diff=_Unrecoverable())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, Incident)]
    assert incident.cause == "node_files_unrecoverable" and incident.subtask_id == "s1"
    assert rig.gate is not None and rig.gate.seen == []
