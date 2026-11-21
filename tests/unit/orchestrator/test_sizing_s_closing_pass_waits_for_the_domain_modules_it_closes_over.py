"""Sizing's closing pass is dispatched only once every domain module before it has settled.

The shape of a run whose plan ordered sizing, control, firmware, sizing's closing pass and
integration: control's review ended blocked and raised an item for a person, firmware (which
builds control's design) was held on it, and the closing pass was dispatched in the same second,
because nothing it reads from was waiting. It merged before control and before firmware, so it
judged a graph that lacked both. Under the rule the run starts under, the closing pass is not
dispatched while a domain module has neither merged nor ended without a merge: the run waits on
the queue, the status names the closing pass and the modules it waits for, and once the item is
decided, control merged, firmware released and merged, the closing pass runs, then integration.

A module that waits for the closing pass itself, and a builder held on such a module, are not
waited for. A run recorded before the rule, or that only records decisions, dispatches as it
always did, and a replay of a run started under the rule refuses a closing pass dispatched while
a module is pending.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import loop_fakes
import pytest
from accounted import forged_account_before_each_open, reaccount  # noqa: F401 - the forger
from loop_fakes import FakeDispatcher, Rig
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_builder_is_held_until_the_design_it_implements_merges import (
    ACTS,
    DESIGN,
    LAW,
    P_TILT,
    _sizing_registered,  # noqa: F401 - the autouse fixture, by name
    dispatched_at,
    drive_item,
    index_of,
)
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    CLOSING,
    DRIVE,
    FW,
    IFACE_DRIVE,
    IFACE_TILT,
    INTEG,
    entry,
    hooked,
    node,
    rig_for,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, decide

from physgate.orchestrator import closing_wait
from physgate.orchestrator.events import read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import replay
from physgate.state.store import journal_records_after

#: A row about the order, not about the sign-off a merge owes: the run starts as one recorded
#: before the rule table, which owes none.
BEFORE_THE_RULE = pytest.mark.usefixtures("before_the_sign_off_rule")


def begin(loop: Loop) -> None:
    """Sizing, control, firmware (which builds control's design), the closing pass, integration."""
    plan = [
        entry(BUDGET, "sizing", "budget"),
        entry(DRIVE, "control", "drive"),
        entry(FW, "firmware", "fw"),
        entry(CLOSING, "sizing", "budget"),
        entry(INTEG, "integration", "integration"),
    ]
    requirement = '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
    head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
    summary = DecompositionSummary(
        session_id="decomposition",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.tilt",),
        spec_commit="e" * 40,
        head_revision=head,
        interface_consumers=(InterfaceConsumers(interface="iface.tilt", consumers=("drive",)),),
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=(P_TILT,),
        design_pairs=(DESIGN,),
    )
    loop.record.start(plan, decomposed=summary)


def rigged(tmp_path: Path, *, acts: bool = True, spent: bool = False) -> Rig:
    """Sizing passes, control's review blocks (its second call), every later one passes.

    With ``spent`` control's three attempts fail instead, and it goes to a person with none left.
    """
    rig = rig_for(
        tmp_path,
        interfaces=(IFACE_DRIVE, IFACE_TILT),
        dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"),
    )
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {
            DRIVE: [node(LAW, "control", "iface.tilt", period=10)],
            FW: [node("fw.main", "firmware", "iface.tilt", period=10)],
        }
    )
    if spent:
        rig.reviewer.verdicts[:] = ["pass", "fail", "fail", "fail"]
    else:
        rig.reviewer.results[2] = blocked_review()
    if acts:
        rig.config_overrides.update(ACTS)
    return rig


def go(rig: Rig, monkeypatch: pytest.MonkeyPatch, *, first: bool) -> str:
    """One process: the step it stopped at, or what escaped."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW))
    if first:
        begin(loop)
    if rig.config_overrides.get("queue_decisions") == "act":
        _layer(loop)
    try:
        return (loop.run() if first else loop.resume()).kind
    finally:
        loop.close()


def run_until_it_waits(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> str:
    return go(rig, monkeypatch, first=True)


def state_of(rig: Rig) -> Any:  # noqa: ANN401 - the replayed state
    return replay(read_events(rig.run_dir / "events.jsonl"))


# --- the shape of the recorded run, end to end ----------------------------------------------------


@BEFORE_THE_RULE
def test_the_closing_pass_waits_while_control_is_with_a_person_and_runs_after_both_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert run_until_it_waits(rig, monkeypatch) == "wait"
    rows = lines(rig)
    assert rows[0]["closing_wait"] == "hold"
    item = drive_item(rows)
    # control is with a person, firmware is held on it, and the closing pass is not dispatched.
    (held,) = of(rows, "builder_held")
    assert (held["subtask_id"], held["why"], held["item_id"]) == (FW, "escalated", item)
    assert of(rows, "stage_entered", subtask_id=CLOSING) == []
    assert of(rows, "integration_gate_ran") == []
    step = state_of(rig).next_step()
    assert (step.kind, step.subtask_id) == ("wait", CLOSING)
    assert refusal(rows) is None

    decide(rig.run_dir, "approve", "decided by hand", item_id=item)
    assert go(rig, monkeypatch, first=False) == "done"
    rows = lines(rig)
    order = [
        index_of(rows, "merged", subtask_id=DRIVE),
        index_of(rows, "builder_released", subtask_id=FW),
        dispatched_at(rows, FW),
        index_of(rows, "merged", subtask_id=FW),
        dispatched_at(rows, CLOSING),
        index_of(rows, "merged", subtask_id=CLOSING),
        index_of(rows, "integration_gate_ran"),
    ]
    assert order == sorted(order)
    assert len(set(order)) == len(order)
    assert refusal(rows) is None


@BEFORE_THE_RULE
def test_a_module_that_ends_unmerged_on_a_reject_lets_the_closing_pass_run_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path, spent=True)
    assert run_until_it_waits(rig, monkeypatch) == "wait"
    rows = lines(rig)
    assert of(rows, "stage_entered", subtask_id=CLOSING) == []
    decide(rig.run_dir, "reject", "no attempt is left", item_id=drive_item(rows))
    reaccount(rig.run_dir)
    assert go(rig, monkeypatch, first=False) == "done"
    rows = lines(rig)
    # control and firmware ended without a merge, so nothing is waited for: the closing pass ran.
    assert of(rows, "merged", subtask_id=DRIVE) == of(rows, "merged", subtask_id=FW) == []
    assert index_of(rows, "merged", subtask_id=CLOSING) < index_of(rows, "integration_gate_skipped")
    assert refusal(rows) is None


def test_the_status_names_the_closing_pass_and_the_modules_it_waits_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert run_until_it_waits(rig, monkeypatch) == "wait"
    state = state_of(rig)
    assert closing_wait.closing_waits(state) == {
        "closing_waits": [{"subtask_id": CLOSING, "pending": [DRIVE, FW]}]
    }


@BEFORE_THE_RULE
def test_nothing_is_printed_of_a_closing_pass_that_waits_for_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert run_until_it_waits(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", "decided by hand", item_id=drive_item(lines(rig)))
    assert go(rig, monkeypatch, first=False) == "done"
    assert closing_wait.closing_waits(state_of(rig)) == {}


# --- a run before the rule, and a run that only records ----------------------------------------


def started_before_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, acts: bool = True
) -> Rig:
    monkeypatch.setattr("physgate.orchestrator.record.CLOSING_WAIT", None)
    rig = rigged(tmp_path, acts=acts)
    run_until_it_waits(rig, monkeypatch)
    return rig


def test_a_run_started_before_the_rule_dispatches_the_closing_pass_and_replays_as_it_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = started_before_the_rule(tmp_path, monkeypatch)
    rows = lines(rig)
    assert "closing_wait" not in rows[0]
    assert index_of(rows, "stage_entered", subtask_id=CLOSING, stage="resolve") > index_of(
        rows, "escalated", subtask_id=DRIVE
    )
    assert refusal(rows) is None


def test_a_replay_refuses_a_closing_pass_dispatched_while_a_module_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = started_before_the_rule(tmp_path, monkeypatch)
    rows = lines(rig)
    assert refusal(rows) is None
    rows[0] = rows[0] | {"closing_wait": "hold"}
    why = refusal(rows)
    assert why is not None
    assert CLOSING in why
    assert DRIVE in why


def test_a_run_that_only_records_decisions_writes_no_mark_and_dispatches_as_it_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path, acts=False)
    run_until_it_waits(rig, monkeypatch)
    rows = lines(rig)
    assert "closing_wait" not in rows[0]
    assert closing_wait.closing_waits(state_of(rig)) == {}
    assert refusal(rows) is None


# --- ways to wait forever --------------------------------------------------------------------


def stub(
    statuses: dict[str, str],
    *,
    roles: dict[str, str] | None = None,
    designers: dict[str, str] | None = None,
    undecided: bool = True,
    items: dict[str, str | None] | None = None,
    closers: tuple[str, ...] = (),
) -> Any:  # noqa: ANN401 - a stand-in for the replayed state
    """A state of subtasks in plan order, the last of them sizing's closing pass.

    ``closers`` name the subtasks of sizing's module directory when it is not the last one.
    """
    order = list(statuses)
    sizing = {order[0], *closers} if closers else {order[0], order[-1]}
    roles = roles or {}
    items = items or {}
    subtasks = {
        s: SimpleNamespace(
            status=st,
            queue_item=items.get(s, f"item-{s}" if st == "escalated" else None),
            next_resolve=1,
            attempts=[],
            plan=SimpleNamespace(
                subtask_id=s,
                assigned_role=roles.get(s, "sizing" if s in sizing else "control"),
                module_dir="modules/sizing" if s in sizing else f"modules/{s}",
            ),
        )
        for s, st in statuses.items()
    }
    pairs = [SimpleNamespace(designer=d, builder=b) for b, d in (designers or {}).items()]
    return SimpleNamespace(
        acts=True,
        closing_wait=True,
        order=order,
        subtasks=subtasks,
        completion_subtask=None,
        design_pairs=pairs or None,
        design_waits=SimpleNamespace(open={}),
        undecided=lambda _item: undecided,
        integrated=lambda: order,
    )


def test_a_module_waiting_for_the_closing_pass_is_not_waited_for() -> None:
    state = stub({"z0": "done", "a": "waiting", "zc": "planned"})
    assert closing_wait.pending(state, "zc") == []


def test_a_builder_whose_designer_waits_for_the_closing_pass_is_not_waited_for() -> None:
    state = stub(
        {"z0": "done", "a": "waiting", "b": "planned", "zc": "planned"}, designers={"b": "a"}
    )
    assert closing_wait.pending(state, "zc") == []


def test_a_chain_of_builders_on_a_module_waiting_for_the_closing_pass_is_not_waited_for() -> None:
    state = stub(
        {"z0": "done", "a": "waiting", "b": "planned", "c": "planned", "zc": "planned"},
        designers={"b": "a", "c": "b"},
    )
    assert closing_wait.pending(state, "zc") == []


def test_a_module_with_a_person_is_waited_for_and_one_whose_item_was_decided_is_not() -> None:
    assert closing_wait.pending(stub({"z0": "done", "a": "escalated", "zc": "planned"}), "zc") == [
        "a"
    ]
    decided = stub({"z0": "done", "a": "escalated", "zc": "planned"}, undecided=False)
    assert closing_wait.pending(decided, "zc") == []


def test_a_module_that_ended_without_a_merge_is_not_waited_for() -> None:
    state = stub({"z0": "done", "a": "rejected", "b": "removed", "c": "done", "zc": "planned"})
    assert closing_wait.pending(state, "zc") == []


def test_a_module_escalated_with_no_item_waits_on_no_one() -> None:
    state = stub({"z0": "done", "a": "escalated", "zc": "planned"}, items={"a": None})
    assert closing_wait.pending(state, "zc") == []


def test_a_module_planned_after_the_closing_pass_is_not_waited_for() -> None:
    state = stub({"z0": "done", "zc": "planned", "late": "escalated"}, closers=("zc",))
    assert closing_wait.pending(state, "zc") == []


def test_a_plan_with_no_domain_module_waits_for_nothing() -> None:
    assert closing_wait.pending(stub({"z0": "done", "zc": "planned"}), "zc") == []


def test_a_closing_pass_waits_only_in_a_run_started_under_the_rule_that_acts() -> None:
    state = stub({"z0": "done", "a": "escalated", "zc": "planned"})
    assert closing_wait.waits(state, "zc")
    state.closing_wait = False
    assert not closing_wait.waits(state, "zc")
    state.closing_wait = True
    state.acts = False
    assert not closing_wait.waits(state, "zc")


def test_a_module_that_is_not_a_closing_pass_never_waits() -> None:
    state = stub(
        {"z0": "done", "a": "escalated", "b": "planned", "zc": "planned"}, roles={"b": "firmware"}
    )
    assert not closing_wait.waits(state, "b")


def test_a_closing_pass_that_is_not_due_a_dispatch_waits_for_nothing() -> None:
    state = stub({"z0": "done", "a": "escalated", "zc": "done"})
    assert closing_wait.pending(state, "zc") == ["a"]
    assert not closing_wait.waits(state, "zc")
    assert closing_wait.closing_waits(state) == {}


def test_the_first_line_of_a_run_that_acts_carries_the_mark_and_is_omitted_otherwise() -> None:
    assert loop_fakes is not None
    from physgate.orchestrator.events import RunStarted

    base: dict[str, Any] = {
        "seq": 0,
        "ts": "2026-11-21T10:00:00.000000Z",
        "run_id": "r",
        "gate_mode": "on",
        "config_sha256": "0" * 64,
    }
    assert "closing_wait" not in json.loads(RunStarted(**base).model_dump_json())
    marked = json.loads(RunStarted(**base, closing_wait="hold").model_dump_json())
    assert marked["closing_wait"] == "hold"
