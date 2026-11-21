"""A scripted run of a slice with a control module: the record it leaves, step by step.

No model runs: the sessions, gate and reviewer are the loop's stand-ins, and the loop, the queue,
replay, the status the page is served and the whole-design export are the real ones. The slice
plans sizing, a control module, an electrical one and integration. Control's role owes a person's
sign-off on the values it merged; the rows assert, for each way the run can go, the lines that
tell the story in order, the queue's item, the status served and what the export writes.

In a run that acts, the integration call waits for the person: signed, the run reaches its end;
rejected, the module is reopened for its one fix while an attempt is left, and with none left the
run ends escalated for that reason. In a run that records decisions, nothing is waited for: the
run records, ends escalated with the sign-off owed, and the export writes its record of what is
owed beside the answer. Each row fails where the rule table is empty, since no sign-off is then
owed and control completes at its merge.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGate, Rig
from sign_off_rig import (
    CLOSING,
    CONTROL,
    ELECTRICAL,
    SIZING,
    JournalGraph,
    declaring,
    journal_plan,
    journal_rig,
    layer,
    plant,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_sign_off_item_is_raised_by_code_at_every_clean_merge_that_owes_one import FIRST
from test_a_sign_off_owed_holds_the_integration_call_and_refuses_a_declaration_of_its_module import (  # noqa: E501
    resume as _resume,
)
from ui_rig import context_over, fake_ui, serving

from physgate.evaluation.whole.export import UNSIGNED, Export, export_whole_run, record_path
from physgate.orchestrator import record
from physgate.orchestrator.events import (
    DecisionTaken,
    Event,
    ModuleCompleted,
    SubtaskReopened,
    read_events,
)
from physgate.orchestrator.queue import QueueItem, read_queue, sign_off_item_id
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import Step, replay
from physgate.state.store import Store

SECOND = sign_off_item_id("run-1", CONTROL, 2)
THIRD = sign_off_item_id("run-1", CONTROL, 3)

#: The lines that tell what happened to the run, in the order written; the rest is bookkeeping.
STORY = frozenset(
    {
        "merged",
        "diff_checked",
        "sign_offs_raised",
        "no_follow_up_owed",
        "decision_taken",
        "subtask_reopened",
        "sign_off_fix_ended",
        "integration_gate_ran",
        "completion_declared",
        "module_completed",
    }
)


def story(events: list[Event]) -> list[str]:
    return [e.kind for e in events if e.kind in STORY]


#: The graph the export reads, by the contract's own names: a controller and its settings.
CONTROLLER = {
    "sensor_delay": (0.0048, "s"),
    "compute_delay": (0.002, "s"),
    "period": (0.01, "s"),
    "command_limit": (0.75, "1"),
    "angle_gain": (1.6643, "1/rad"),
    "rate_gain": (0.191, "s/rad"),
    "distance_gain": (0.2853, "1/m"),
    "speed_gain": (1.3421, "s/m"),
}
SETTINGS = {
    "update_rate": (100, "Hz"),
    "gyro_output_data_rate": (208, "Hz"),
    "gyro_full_scale": (1000, "deg/s"),
    "pwm_frequency": (20000, "Hz"),
    "pwm_full_scale": (400, "count"),
    "encoder_counts_per_wheel_revolution": (1322.9, "count"),
}
NOTE = "the margins are on the loop that runs"
RECORDED_AFTER = "the sign-off is owed and nobody signed it"


def drive(rig: Rig, *, acts: bool = True, closing: bool = False) -> tuple[list[Event], Step]:
    """The slice started with integration declaring every module, and driven to where it stops."""
    loop = rig.open()
    declaring(loop, (SIZING, CONTROL, ELECTRICAL), (SIZING, ELECTRICAL))
    plan = journal_plan(closing=closing)
    summary = DecompositionSummary(
        session_id="decomp-1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.none",),
        spec_commit="a" * 40,
        head_revision=1,
    )
    loop.record.start(plan, decomposed=summary)
    if acts:
        layer(loop)
    step = loop.run()
    loop.close()
    return read_events(rig.run_dir / "events.jsonl"), step


def run(tmp_path: Path, *, acts: bool = True, **fields: Any) -> tuple[Rig, list[Event], Step]:  # noqa: ANN401
    """The slice driven to the step it ends at, or waits at."""
    rig, graph = journal_rig(tmp_path, acts=acts, **fields)
    assert isinstance(graph, JournalGraph)
    events, step = drive(rig, acts=acts)
    return rig, events, step


def sign_item_by(run_dir: Path, item_id: str) -> QueueItem:
    return next(i for i in read_queue(run_dir).items if i.item_id == item_id)


def sign_item(run_dir: Path) -> QueueItem:
    (item,) = [i for i in read_queue(run_dir).items if i.source == "sign_off"][:1]
    return item


def served(tmp_path: Path, run_dir: Path) -> dict[str, Any]:
    """The status the page is served for the run at ``run_dir``, over the real server."""
    root = tmp_path / "served"
    shutil.copytree(run_dir, root / "the-run")
    with serving(context_over(root, ui_root=fake_ui(tmp_path / "checkout"))) as live:
        code, _, body = live.request("GET", "/api/runs/0/the-run/status")
    assert code == 200, body[:300]
    found: dict[str, Any] = json.loads(body)
    return found


def exported(tmp_path: Path, run_dir: Path) -> tuple[Export, Path]:
    """The whole-design export over the run's log, beside a store holding a whole contract."""
    copy = Path(os.path.realpath(tmp_path)) / "copy"
    (copy / "store").mkdir(parents=True)
    (copy / "events.jsonl").write_bytes((run_dir / "events.jsonl").read_bytes())
    store = Store(copy / "store")
    try:
        for node_id, owner, domain, values in (
            ("balance.controller", "control", "control", CONTROLLER),
            ("firmware.loop_timing", "firmware", "firmware", SETTINGS),
        ):
            node: dict[str, Any] = {
                "id": node_id,
                "kind": "module",
                "domain": domain,
                "owner_role": owner,
                "quantities": {
                    name: {"value": v, "unit": u, "source": "fixture", "written_by": owner}
                    for name, (v, u) in values.items()
                },
                "requirements": [],
                "constrains": [],
                "model": None,
                "geometry_hash": "none",
                "updated": "2026-11-21",
            }
            assert store.write_node(node, owner).accepted
    finally:
        store.close()
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    return export_whole_run(copy, out), out


def files_in(out: Path) -> list[str]:
    return sorted(p.name for p in out.parent.iterdir()) if out.parent.exists() else []


def completed(events: list[Event]) -> list[str]:
    return [e.subtask_id for e in events if isinstance(e, ModuleCompleted)]


# --- a run that acts waits for the person ------------------------------------------------------


def test_an_acting_run_waits_with_the_sign_off_item_open_and_is_served_as_waiting(
    tmp_path: Path,
) -> None:
    rig, events, step = run(tmp_path / "run")
    assert step.kind == "wait"
    # Every module merged, the control module's values were bound, and no call was made.
    assert story(events) == [
        "merged",
        "diff_checked",
        "merged",
        "diff_checked",
        "sign_offs_raised",
        "merged",
        "diff_checked",
        "no_follow_up_owed",
    ]
    item = sign_item(rig.run_dir)
    assert (item.item_id, item.subtask_id, item.source) == (FIRST, CONTROL, "sign_off")
    assert item.consequence is not None
    assert (item.consequence.on_approve, item.consequence.on_reject) == ("sign", "reopen_fix")
    assert [(q.node_id, q.name) for q in item.quantities] == [
        ("ctl.loop", "phase_margin"),
        ("ctl.loop", "gain_margin"),
        ("ctl.loop", "sample_rate"),
    ]
    assert 'Node "ctl.loop"' in item.artefact_diff
    assert read_queue(rig.run_dir).open_items() == [item]
    found = served(tmp_path, rig.run_dir)
    assert found["acts"] is True
    assert found["next_step"]["kind"] == "wait"
    assert found["sign_offs_owed"] == [CONTROL]
    assert found["sign_offs_open_to_decide"] == [CONTROL]
    # The export reads a run still waiting as unfinished and writes nothing.
    export, out = exported(tmp_path / "ex", rig.run_dir)
    assert export.status == "unfinished"
    assert files_in(out) == []


def test_a_signed_run_reaches_its_end_and_exports_with_nothing_owed(tmp_path: Path) -> None:
    rig, _, step = run(tmp_path / "run")
    assert step.kind == "wait"
    decide(rig.run_dir, "approve", NOTE, item_id=FIRST)
    events, step = _resume(rig)
    assert step.kind == "done"
    assert story(events)[7:] == [
        "no_follow_up_owed",
        "decision_taken",
        "integration_gate_ran",
        "completion_declared",
        "merged",
        "diff_checked",
        "module_completed",
        "module_completed",
        "module_completed",
    ]
    assert completed(events) == [SIZING, CONTROL, ELECTRICAL]
    assert replay(events).sign_offs_open() == []
    found = served(tmp_path, rig.run_dir)
    assert found["next_step"]["kind"] == "done"
    assert found["sign_offs_owed"] == []
    export, out = exported(tmp_path / "ex", rig.run_dir)
    assert export.status == "exported"
    assert export.sign_offs_owed == ()
    assert files_in(out) == ["whole_run.json", "whole_run.json.record.json"]
    assert json.loads(record_path(out).read_bytes())["sign_off"] is None


def test_a_rejected_sign_off_sends_the_module_back_for_its_fix_and_the_run_waits_on_the_new_one(
    tmp_path: Path,
) -> None:
    rig, graph = journal_rig(tmp_path / "run")

    def rejecting() -> None:
        decide(rig.run_dir, "reject", NOTE, item_id=FIRST)

    rig.dispatcher.during[3] = rejecting
    events, step = drive(rig)
    assert step.kind == "wait"
    assert story(events) == [
        "merged",
        "diff_checked",
        "merged",
        "diff_checked",
        "sign_offs_raised",
        "merged",
        "diff_checked",
        "decision_taken",
        "subtask_reopened",
        "merged",
        "diff_checked",
        "sign_offs_raised",
        "no_follow_up_owed",
    ]
    (reopen,) = [e for e in events if isinstance(e, SubtaskReopened)]
    assert (reopen.subtask_id, reopen.item_id, reopen.attempt) == (CONTROL, FIRST, 2)
    second = sign_item_by(rig.run_dir, SECOND)
    assert second.subtask_id == CONTROL
    assert [i.item_id for i in read_queue(rig.run_dir).open_items()] == [SECOND]
    found = served(tmp_path, rig.run_dir)
    assert found["next_step"]["kind"] == "wait"
    assert found["sign_offs_open_to_decide"] == [CONTROL]
    decide(rig.run_dir, "approve", NOTE, item_id=SECOND)
    events, step = _resume(rig)
    assert step.kind == "done"
    assert completed(events) == [SIZING, CONTROL, ELECTRICAL]


def test_a_rejected_sign_off_with_no_attempt_left_ends_the_run_escalated_for_that_reason(
    tmp_path: Path,
) -> None:
    # The control module merges at its third attempt and is reopened at its fourth, the last.
    rig, graph = journal_rig(tmp_path / "run", gate=FakeGate(verdicts=["pass", "fail", "fail"]))
    graph.writes[CLOSING] = [[plant(0.40)]]
    events, step = drive(rig, closing=True)
    assert step.kind == "wait"
    latest = sign_item_by(rig.run_dir, THIRD)
    assert latest.consequence is not None
    assert latest.consequence.on_reject == "record_only"
    decide(rig.run_dir, "reject", NOTE, item_id=THIRD)
    events, step = _resume(rig)
    assert step.kind == "escalated"
    (decision,) = [e for e in events if isinstance(e, DecisionTaken) and e.item_id == THIRD]
    assert (decision.effect, decision.why_not) == ("none", "no_attempt_left")
    assert replay(events).sign_offs_open() == [CONTROL]
    assert completed(events) == [SIZING, ELECTRICAL]
    found = served(tmp_path, rig.run_dir)
    assert found["next_step"]["kind"] == "escalated"
    assert found["sign_offs_owed"] == [CONTROL]
    assert found["sign_offs_open_to_decide"] == []
    # A run that acts and ends unsigned is not exported as a finished one.
    export, out = exported(tmp_path / "ex", rig.run_dir)
    assert export.status == "unfinished"
    assert files_in(out) == []


# --- a run that records decisions waits for no one ---------------------------------------------


def test_a_recording_run_records_ends_escalated_and_exports_its_record_of_what_is_owed(
    tmp_path: Path,
) -> None:
    rig, events, step = run(tmp_path / "run", acts=False)
    assert step.kind == "escalated"
    # No decision is taken, the call is made; sizing and the electrical module complete.
    assert story(events) == [
        "merged",
        "diff_checked",
        "merged",
        "diff_checked",
        "sign_offs_raised",
        "merged",
        "diff_checked",
        "integration_gate_ran",
        "completion_declared",
        "merged",
        "diff_checked",
        "module_completed",
        "module_completed",
    ]
    assert completed(events) == [SIZING, ELECTRICAL]
    item = sign_item(rig.run_dir)
    assert (item.item_id, item.subtask_id) == (FIRST, CONTROL)
    assert item.consequence is None
    found = served(tmp_path, rig.run_dir)
    assert found["acts"] is False
    assert found["next_step"]["kind"] == "escalated"
    assert found["sign_offs_owed"] == [CONTROL]
    assert found["sign_offs_open_to_decide"] == []
    export, out = exported(tmp_path / "ex", rig.run_dir)
    assert export.status == "exported"
    assert export.sign_offs_owed == (CONTROL,)
    assert files_in(out) == ["whole_run.json", "whole_run.json.record.json"]
    written = json.loads(record_path(out).read_bytes())
    assert written["sign_offs_owed"] == [CONTROL]
    assert written["status"] == "exported"
    assert written["answer"] == "whole_run.json"
    assert written["answer_sha256"] == export.sha256
    assert written["sign_off"] == UNSIGNED


def test_the_same_slice_before_the_rule_table_owes_nothing_and_completes_control_at_its_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard, not a row of the rule: it shows what the other rows differ from."""
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)
    rig, events, step = run(tmp_path / "run", acts=False)
    assert step.kind == "done"
    assert "sign_offs_raised" not in story(events)
    assert completed(events) == [SIZING, CONTROL, ELECTRICAL]
    assert read_queue(rig.run_dir).items == ()
