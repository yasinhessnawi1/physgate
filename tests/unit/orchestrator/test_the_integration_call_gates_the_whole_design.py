"""The integration call, the attempt's scopes, and the derived catch-accounting events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGate, Rig, failing_gate_result, passing_gate_result, plan
from orch_helpers import make_config

from physgate.orchestrator.events import (
    EventLog,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    RunStarted,
    StageEntered,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import IntegrationArtefact
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import RunState


def events_of(run_dir: Path) -> list[Any]:
    return read_events(run_dir / "events.jsonl")


def integration_lines(run_dir: Path) -> list[Any]:
    kinds = (IntegrationGateRan, IntegrationGateSkipped, IntegrationEscalated)
    return [e for e in events_of(run_dir) if isinstance(e, kinds)]


# --- the integration call ------------------------------------------------------------


def test_once_every_subtask_merged_the_gate_checks_the_whole_design(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert rig.gate is not None
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    (line,) = integration_lines(tmp_path)
    assert isinstance(line, IntegrationGateRan) and line.result.verdict == "pass"
    (called,) = rig.gate.integrations
    assert isinstance(called, IntegrationArtefact)
    assert called.graph_root == "store"
    merged = [e for e in events_of(tmp_path) if isinstance(e, Merged)]
    assert called.run_head == merged[-1].merge_commit


def test_a_blocking_integration_failure_is_a_queue_item_and_the_run_ends_escalated(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate=FakeGate(integration_verdict="fail"))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "escalated"
    (item,) = loop.queue.open_items()
    loop.close()
    assert item.source == "gate_escalation" and item.subtask_id == "integration"
    assert item.item_id == "run-1-integration"
    assert item.triggering_finding == "the stall current exceeds the driver's rating"
    assert len(item.trajectories) == 2
    lines = integration_lines(tmp_path)
    assert [type(e).__name__ for e in lines] == ["IntegrationGateRan", "IntegrationEscalated"]
    assert lines[1].item_id == item.item_id


def test_under_observe_an_integration_failure_is_recorded_and_nothing_blocks(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate_mode="observe", gate=FakeGate(integration_verdict="fail"))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    assert loop.queue.open_items() == []
    loop.close()
    (line,) = integration_lines(tmp_path)
    assert isinstance(line, IntegrationGateRan)
    assert (line.result.verdict, line.result.mode) == ("fail", "observe")


def test_with_the_gate_off_integration_is_recorded_as_skipped_and_no_gate_is_called(
    tmp_path: Path,
) -> None:
    gate = FakeGate()
    rig = Rig(tmp_path, gate_mode="off", gate=gate)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    (line,) = integration_lines(tmp_path)
    assert isinstance(line, IntegrationGateSkipped)
    assert (line.reason, line.subtasks) == ("gate_mode=off", ())
    assert gate.integrations == []


def test_a_design_with_a_subtask_that_never_merged_is_recorded_as_not_gated(
    tmp_path: Path,
) -> None:
    gate = FakeGate(verdicts=["pass", "fail", "fail", "fail"])  # s1 merges, s2 escalates
    rig = Rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(plan("s1", "s2", "s3"))
    loop.remove("s3", "no longer needed")
    assert loop.run().kind == "done"
    loop.close()
    (line,) = integration_lines(tmp_path)
    assert isinstance(line, IntegrationGateSkipped)
    assert (line.reason, line.subtasks) == ("not_all_merged", ("s2", "s3"))
    assert gate.integrations == []


def test_a_killed_process_escalates_a_recorded_failure_once_on_its_next_pass(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, gate=FakeGate(integration_verdict="fail"))
    loop = rig.open()
    loop.start(plan("s1"))
    # Drive to the integration call, then write its failing line by hand, as a
    # process killed before its escalation would have left the log.
    while loop.state.next_step().kind not in ("integrate",):
        step = loop.state.next_step()
        loop._attempt(step.subtask_id or "", step.attempt or 1, step.point or "resolve")  # noqa: SLF001
    loop.log.emit(IntegrationGateRan, result=failing_gate_result("on"))
    loop.close()
    again = rig.open()
    assert again.run().kind == "escalated"
    assert again.run().kind == "escalated"
    assert len(again.queue.items()) == 1
    again.close()
    assert [type(e).__name__ for e in integration_lines(tmp_path)] == [
        "IntegrationGateRan",
        "IntegrationEscalated",
    ]


# --- the replay refuses an integration line out of place -------------------------------


def _log(tmp_path: Path, gate_mode: str = "on", ids: tuple[str, ...] = ("s1",)) -> EventLog:
    config = make_config(gate_mode=gate_mode)
    state = RunState()
    log = EventLog(
        tmp_path / "events.jsonl", run_id=config.run_id, gate_mode=config.gate_mode, state=state
    )
    log.emit(RunStarted, config_sha256="a" * 64)
    for i in ids:
        entry = PlanEntry(
            subtask_id=i,
            spec_path=f"specs/{i}.md",
            assigned_role="electrical",
            module_dir=f"modules/{i}",
        )
        log.emit(SubtaskPlanned, **entry.model_dump())
    return log


def test_the_replay_refuses_integration_before_every_subtask_is_merged_or_queued(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    with pytest.raises(ValueError, match="before every planned subtask"):
        log.emit(IntegrationGateRan, result=passing_gate_result("on"))
    with pytest.raises(ValueError, match="before every planned subtask"):
        log.emit(IntegrationGateSkipped, reason="not_all_merged", subtasks=("s1",))
    log.close()


def test_the_replay_refuses_a_second_integration_line_and_any_subtask_line_after_it(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path, ids=())
    log.emit(IntegrationGateSkipped, reason="nothing_planned", subtasks=())
    with pytest.raises(ValueError, match="made once"):
        log.emit(IntegrationGateSkipped, reason="nothing_planned", subtasks=())
    with pytest.raises(ValueError):
        entry = PlanEntry(
            subtask_id="late",
            spec_path="specs/late.md",
            assigned_role="electrical",
            module_dir="modules/late",
        )
        log.emit(SubtaskPlanned, **entry.model_dump())
    log.close()


def test_the_replay_refuses_a_subtask_line_after_the_integration_call(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    # A line the subtask's own rules refuse is refused for them.
    with pytest.raises(ValueError, match="no attempt in progress"):
        loop.log.emit(StageEntered, subtask_id="s1", attempt=1, stage="diff")
    # A line no other rule refuses: a subtask planned after the plan was closed.
    late = PlanEntry(
        subtask_id="late",
        spec_path="specs/late.md",
        assigned_role="electrical",
        module_dir="modules/late",
    )
    with pytest.raises(ValueError, match="nothing about a subtask follows the integration"):
        loop.log.emit(SubtaskPlanned, **late.model_dump())
    loop.close()


def test_the_replay_refuses_an_escalation_without_a_blocking_integration_failure(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path, ids=())
    with pytest.raises(ValueError, match="without a blocking"):
        log.emit(IntegrationEscalated, item_id="run-1-integration")
    log.emit(IntegrationGateSkipped, reason="nothing_planned", subtasks=())
    with pytest.raises(ValueError, match="without a blocking"):
        log.emit(IntegrationEscalated, item_id="run-1-integration")
    log.close()


def test_the_replay_refuses_a_skip_whose_reason_is_not_the_run_s(tmp_path: Path) -> None:
    log = _log(tmp_path, gate_mode="on", ids=())
    with pytest.raises(ValueError, match="gate mode"):
        log.emit(IntegrationGateSkipped, reason="gate_mode=off", subtasks=())
    log.close()
    off = _log(tmp_path / "off", gate_mode="off", ids=())
    with pytest.raises(ValueError, match="gate mode"):
        off.emit(IntegrationGateSkipped, reason="nothing_planned", subtasks=())
    off.close()


def test_the_replay_refuses_a_gate_run_on_an_incomplete_design(tmp_path: Path) -> None:
    gate = FakeGate(verdicts=["fail", "fail", "fail"])
    rig = Rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(plan("s1"))
    while loop.state.next_step().kind != "integrate":
        step = loop.state.next_step()
        if step.kind == "escalate":
            loop._escalate(step.subtask_id or "")  # noqa: SLF001
        else:
            loop._attempt(step.subtask_id or "", step.attempt or 1, step.point or "resolve")  # noqa: SLF001
    with pytest.raises(ValueError, match="did not merge"):
        loop.log.emit(IntegrationGateRan, result=passing_gate_result("on"))
    with pytest.raises(ValueError, match="exactly the subtasks"):
        loop.log.emit(IntegrationGateSkipped, reason="not_all_merged", subtasks=("other",))
    loop.close()


# --- the attempt's scopes and base revision ---------------------------------------------


def test_an_attempt_that_completes_its_module_is_checked_at_module_scope(tmp_path: Path) -> None:
    gate = FakeGate()
    rig = Rig(tmp_path, gate=gate)
    loop = rig.open()
    shared = [
        PlanEntry(subtask_id=i, spec_path=f"specs/{i}.md", assigned_role="electrical", module_dir=d)
        for i, d in (("s1", "modules/drive"), ("s2", "modules/drive"), ("s3", "modules/imu"))
    ]
    loop.start(shared)
    loop.run()
    loop.close()
    assert [(a.subtask_id, a.scopes) for a in gate.seen] == [
        ("s1", ("subtask",)),
        ("s2", ("subtask", "module")),
        ("s3", ("subtask", "module")),
    ]
    assert all(a.base_revision == 0 for a in gate.seen)


def test_a_later_subtask_taken_out_of_the_plan_does_not_hold_its_module_open(
    tmp_path: Path,
) -> None:
    gate = FakeGate()
    rig = Rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(
        [
            PlanEntry(
                subtask_id=i,
                spec_path=f"specs/{i}.md",
                assigned_role="electrical",
                module_dir="modules/drive",
            )
            for i in ("s1", "s2")
        ]
    )
    loop.remove("s2", "folded into s1")
    loop.run()
    loop.close()
    assert [(a.subtask_id, a.scopes) for a in gate.seen] == [("s1", ("subtask", "module"))]


# --- the derived catch-accounting events ------------------------------------------------


def test_every_gate_check_becomes_one_event_with_the_reviewer_field_empty(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate_mode="observe", gate=FakeGate(verdicts=["fail"]))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    found = gate_events(events_of(tmp_path))
    assert [(e.subtask_id, e.attempt, e.outcome) for e in found] == [
        ("s1", 1, "fail"),
        ("integration", None, "pass"),
    ]
    assert all(e.reviewer_had_passed is None for e in found)
    assert all(e.gate_mode == "observe" for e in found)
    assert all(e.catalogue_sha256 == "c" * 64 for e in found)
    dumped = found[0].model_dump()
    assert {"check", "value", "node", "module", "reviewer_had_passed"} <= set(dumped)


def test_the_gate_events_command_prints_one_line_per_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    rig = Rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    capsys.readouterr()
    assert main(["gate-events", "--run-dir", str(tmp_path / "run")]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x["subtask_id"] for x in lines] == ["s1", "integration"]
    assert all(x["reviewer_had_passed"] is None for x in lines)
