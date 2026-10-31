"""Mechanical and electrical are registered for planning only: planned, reviewed, never dispatched.

A plan may name either role, and ``decompose`` accepts it and has the design reviewer judge it
with the design rubric. A run whose plan names either halts at its first dispatch, with the cause
named, before any session of any role is spawned: such a run could never finish, so nothing is
spent on it. The halt is not resumed. Each row takes the suite's dispatchable stand-ins out of the
register and puts the shipped rows back, so it sees what a real run sees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import Rig
from plan_hold_rig import outcome_of
from test_decompose_reviews_the_plan_before_it_writes_anything import (
    BRIEF,
    REVIEWING,
    Calls,
    StandIn,
    _args,
    _exit,
    _verdict,
    calls,  # noqa: F401 - the fixture, by name
)

from physgate import roles
from physgate.knowledge.library import read_library
from physgate.orchestrator.decompose import Outcome
from physgate.orchestrator.events import Halted, read_events
from physgate.orchestrator.plan import Plan
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.run_config import ModelStrings

PLANNED_ONLY = ("mechanical", "electrical")
MODEL, REVIEWER = "claude-sonnet-5", "claude-opus-5-5"


@pytest.fixture
def shipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it ships: the suite's dispatchable stand-ins taken out."""
    for name in PLANNED_ONLY:
        monkeypatch.delitem(roles.ROLES, name, raising=False)
    for row in roles.SHIPPED:
        monkeypatch.setitem(roles.ROLES, row.name, row)


def _node(owner: str) -> dict[str, Any]:
    return {
        "id": f"iface.{owner}",
        "kind": "interface",
        "domain": owner,
        "owner_role": owner,
        "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": owner}},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-31T00:00:00Z",
    }


def _plan() -> Plan:
    spec = "Do it.\n\n## Acceptance criteria\n\n1. It is done.\n"
    answer = {
        "modules": [
            {"name": "frame", "role": "mechanical", "module_dir": "modules/frame", "spec": spec},
            {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": spec},
        ],
        "interface_nodes": [_node("mechanical"), _node("electrical")],
    }
    return Plan.model_validate_json(json.dumps(answer))


class PlannedCalls(Calls):
    """The call, answering a plan with a mechanical and an electrical module."""

    def __call__(self, brief: str, *, workdir: Path, **given: Any) -> Outcome:  # noqa: ANN401
        made = super().__call__(brief, workdir=workdir, **given)
        return made.model_copy(update={"plan": _plan()})


@pytest.mark.usefixtures("calls")
def test_a_plan_naming_mechanical_and_electrical_decomposes_and_is_reviewed_by_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shipped: None
) -> None:
    import physgate.orchestrator.cli as orchestrator_cli

    planned = PlannedCalls()
    monkeypatch.setattr(orchestrator_cli, "call", planned)
    params = {
        **REVIEWING,
        "design_review": "on",
        "models": {
            "decomposition": MODEL,
            "roles": dict.fromkeys(PLANNED_ONLY, MODEL),
            "reviewers": {**dict.fromkeys(PLANNED_ONLY, REVIEWER), "design": REVIEWER},
        },
    }
    reviewer = StandIn(_verdict("pass"))
    found = _exit(_args(tmp_path, params), reviewer)
    assert found == 0, f"decompose refused a plan of the planning roles: {found!r}"
    [under] = reviewer.seen
    assert under.brief == BRIEF
    assert {m.role for m in under.plan.modules} == set(PLANNED_ONLY)
    log = list(read_events(tmp_path / "run" / "events.jsonl"))
    assert {e.assigned_role for e in log if e.kind == "subtask_planned"} == set(PLANNED_ONLY)
    assert log[-1].kind == "design_review_ran"


def test_the_design_reviewer_is_built_with_the_design_rubric_for_such_a_plan(
    shipped: None,
) -> None:
    from physgate.orchestrator.run_config import DESIGN_REVIEWER

    # The plan's reviewer is one reviewer of the plan, whatever roles the plan names.
    assert DESIGN_REVIEWER == "design"
    for name in PLANNED_ONLY:
        row = roles.ROLES.get(name)
        assert row is not None, f"{name} is not in the shipped register"
        assert getattr(row, "planning_only", None) is True, f"{name} is not planning-only"


def test_the_real_library_holds_both_roles_curated_reading() -> None:
    root = Path(__file__).resolve().parents[3]
    assert read_library(root, PLANNED_ONLY)


def _entry(subtask_id: str, role: str) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id,
        spec_path=f"specs/{subtask_id}.md",
        assigned_role=role,
        module_dir=f"modules/{subtask_id}",
    )


def _rig(tmp_path: Path, planned: tuple[str, ...]) -> Rig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    named = sorted(set(planned))
    models = ModelStrings(
        decomposition=MODEL,
        roles=dict.fromkeys(named, MODEL),
        reviewers=dict.fromkeys(named, REVIEWER),
    )
    return Rig(tmp_path, config_overrides={"models": models})


@pytest.mark.parametrize(
    "planned",
    [("mechanical",), ("electrical",), ("control", "mechanical"), ("electrical", "control")],
)
def test_a_run_whose_plan_names_a_planning_role_halts_before_any_dispatch(
    tmp_path: Path, shipped: None, planned: tuple[str, ...]
) -> None:
    rig = _rig(tmp_path / "run", planned)
    loop = outcome_of(rig.open)
    assert not isinstance(loop, Exception), f"the run was refused at its start: {loop!r}"
    try:
        loop.start([_entry(f"s{i}", role) for i, role in enumerate(planned, 1)])
        step = outcome_of(loop.run)
    finally:
        loop.close()
    assert not isinstance(step, Exception), step
    assert step.kind == "halted"
    log = list(read_events(tmp_path / "run" / "events.jsonl"))
    halts = [e for e in log if isinstance(e, Halted)]
    assert [h.reason for h in halts] == ["role_not_built"]
    unbuilt = [r for r in planned if r in PLANNED_ONLY]
    assert all(role in halts[0].detail for role in unbuilt), halts[0].detail
    assert not [e for e in log if e.kind in ("stage_entered", "session_spawned")]
    assert rig.dispatcher.requests == []


def test_a_run_halted_on_a_planning_role_is_not_resumed(tmp_path: Path, shipped: None) -> None:
    rig = _rig(tmp_path / "run", ("mechanical",))
    loop = outcome_of(rig.open)
    assert not isinstance(loop, Exception), f"the run was refused at its start: {loop!r}"
    try:
        loop.start([_entry("s1", "mechanical")])
        outcome_of(loop.run)
    finally:
        loop.close()
    again = rig.open()
    try:
        refused = outcome_of(again.resume)
    finally:
        again.close()
    assert isinstance(refused, Exception)
    assert "role_not_built" in str(refused)
    assert rig.dispatcher.requests == []


def test_a_run_of_built_roles_is_dispatched_as_before(tmp_path: Path, shipped: None) -> None:
    rig = _rig(tmp_path / "run", ("control",))
    loop = rig.open()
    try:
        loop.start([_entry("s1", "control")])
        outcome_of(loop.run)
    finally:
        loop.close()
    log = list(read_events(tmp_path / "run" / "events.jsonl"))
    assert not [e for e in log if isinstance(e, Halted) and e.reason == "role_not_built"]
    assert [r.assigned_role for r in rig.dispatcher.requests][:1] == ["control"]


def test_the_suite_s_stand_ins_stay_dispatchable(tmp_path: Path) -> None:
    # The stand-ins the suite registers are dispatchable rows over the shipped ones: the
    # check reads the row, never the name.
    dispatchable = getattr(roles, "dispatchable", None)
    assert dispatchable is not None, "the register answers no dispatchability"
    assert dispatchable("mechanical") and dispatchable("electrical")
    assert dispatchable("control") and dispatchable("integration")


def test_the_check_reads_the_shipped_rows(shipped: None) -> None:
    dispatchable = getattr(roles, "dispatchable", None)
    assert dispatchable is not None, "the register answers no dispatchability"
    assert not dispatchable("mechanical")
    assert not dispatchable("electrical")
    assert dispatchable("control") and dispatchable("firmware") and dispatchable("integration")
