"""The runner: every record stamped with its mode and scope, and the verdict read off them."""

from __future__ import annotations

from pathlib import Path

import pytest
from gate_fixtures import fixed, graph, node, recording, thermal_failure, unchecked

from physgate.gate.context import CheckContext
from physgate.gate.exceptions import GateModeError, NothingCheckedError
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate, scopes_and_base
from physgate.orchestrator.protocols import Artefact, Gate, RunningGateMode

DRIVE = node("electrical.drive", kind="module", quantities={"power_supply": (15, "W")})
MOTOR = node(
    "electrical.motor_left", quantities={"power_draw": (9, "W")}, constrains=["electrical.drive"]
)


@pytest.fixture
def view(tmp_path: Path) -> GraphView:
    graph(tmp_path / "g", DRIVE, MOTOR)
    return GraphView.read(tmp_path / "g", base_revision=0)


def artefact(graph_root: Path) -> Artefact:
    return Artefact(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        attempt_commit="a" * 40,
        worktree="/w",
        graph_root=str(graph_root),
        trajectory="/t",
    )


def test_the_gate_satisfies_the_orchestrator_s_protocol() -> None:
    assert isinstance(PhysicsGate(), Gate)


@pytest.mark.parametrize("mode", ["off", "block", None, ""])
def test_a_mode_in_which_no_gate_runs_is_refused_before_any_check(
    view: GraphView, mode: object
) -> None:
    seen: list[CheckContext] = []
    gate = PhysicsGate((recording("units", seen),))
    with pytest.raises(GateModeError):
        gate.run(view, ["subtask"], mode)  # type: ignore[arg-type]
    assert seen == []


@pytest.mark.parametrize("mode", ["on", "observe"])
def test_every_record_carries_the_mode_the_gate_ran_in(view: GraphView, mode: str) -> None:
    running: RunningGateMode = "on" if mode == "on" else "observe"
    gate = PhysicsGate(
        (fixed("units", [unchecked("gizmo")]), fixed("thermal", [thermal_failure()]))
    )
    result = gate.run(view, ["subtask", "module", "system"], running)
    assert result.mode == running
    assert len(result.checks) >= 3
    assert {r.gate_mode for r in result.checks} == {running}


def test_records_follow_the_registry_then_the_scope_narrowest_first(view: GraphView) -> None:
    gate = PhysicsGate((fixed("units"), fixed("power"), fixed("thermal")))
    result = gate.run(view, ["system", "module", "subtask"], "on")
    assert [(r.name, r.scope) for r in result.checks] == [
        ("units", "subtask"),
        ("power", "module"),
        ("power", "system"),
        ("thermal", "module"),
        ("thermal", "system"),
    ]


def test_a_check_runs_only_where_the_architecture_says_it_runs(view: GraphView) -> None:
    seen: list[CheckContext] = []
    gate = PhysicsGate((recording("units", seen), recording("equilibrium", seen)))
    gate.run(view, ["subtask"], "on")
    assert [c.scope for c in seen] == ["subtask"]
    seen.clear()
    gate.run(view, ["module", "system"], "on")
    assert [c.scope for c in seen] == ["module"]


def test_a_check_that_is_not_registered_never_runs(view: GraphView) -> None:
    seen: list[CheckContext] = []
    gate = PhysicsGate((fixed("units"),))
    unregistered = recording("magnitude", seen)
    gate.run(view, ["subtask"], "on")
    assert seen == [] and unregistered.number == 2


def test_the_same_negative_margin_warns_at_module_and_blocks_at_system(view: GraphView) -> None:
    gate = PhysicsGate((fixed("thermal", [thermal_failure()]),))
    at_module = gate.run(view, ["module"], "on")
    assert at_module.verdict == "pass"
    assert [(r.outcome, r.blocking) for r in at_module.checks] == [("warn", False)]
    assert "1 warning" in at_module.finding
    at_system = gate.run(view, ["system"], "on")
    assert at_system.verdict == "fail" and at_system.failing_check == "thermal"
    assert [(r.outcome, r.blocking) for r in at_system.checks] == [("fail", True)]
    assert at_system.numeric_output is not None and at_system.numeric_output.unit == "K"


def test_observe_records_the_same_failure_and_the_same_verdict(view: GraphView) -> None:
    gate = PhysicsGate((fixed("thermal", [thermal_failure()]),))
    on = gate.run(view, ["system"], "on")
    observed = gate.run(view, ["system"], "observe")
    assert observed.verdict == on.verdict == "fail"
    strip = {"gate_mode"}
    assert [r.model_dump(exclude=strip) for r in observed.checks] == [
        r.model_dump(exclude=strip) for r in on.checks
    ]


def test_a_check_with_nothing_wrong_leaves_one_pass_record_with_its_count(
    view: GraphView,
) -> None:
    result = PhysicsGate((fixed("units", evaluated=7),)).run(view, ["subtask"], "on")
    assert result.verdict == "pass" and result.finding == "every check passed"
    (record,) = result.checks
    assert record.outcome == "pass" and record.details.form == "pass"
    assert record.details.evaluated == 7
    assert record.reviewer_had_passed is None


def test_unchecked_quantities_are_recorded_and_never_counted_as_passed(view: GraphView) -> None:
    result = PhysicsGate((fixed("units", [unchecked("gizmo", "widget")]),)).run(
        view, ["subtask"], "on"
    )
    outcomes = [r.outcome for r in result.checks]
    assert outcomes == ["pass", "unchecked"]
    assert result.checks[1].details.quantities == ("gizmo", "widget")  # type: ignore[union-attr]


def test_the_first_blocking_failure_is_the_finding_and_others_are_counted(
    view: GraphView,
) -> None:
    failures = [thermal_failure("electrical.a", -2), thermal_failure("electrical.b", -9)]
    result = PhysicsGate((fixed("thermal", failures),)).run(view, ["system"], "on")
    assert result.finding.startswith("electrical.a runs 2 K above its limit")
    assert "1 more blocking finding" in result.finding
    assert [q.node_id for q in result.quantities] == ["electrical.a", "electrical.b"]


def test_at_most_three_quantities_travel_with_the_verdict(view: GraphView) -> None:
    failures = [thermal_failure(f"electrical.n{i}", -1) for i in range(5)]
    result = PhysicsGate((fixed("thermal", failures),)).run(view, ["system"], "on")
    assert len(result.quantities) == 3
    assert len([r for r in result.checks if r.outcome == "fail"]) == 5


def test_a_call_in_which_no_check_runs_gives_no_verdict(view: GraphView) -> None:
    with pytest.raises(NothingCheckedError):
        PhysicsGate((fixed("units"),)).run(view, ["module"], "on")
    with pytest.raises(NothingCheckedError):
        PhysicsGate(()).run(view, ["subtask", "module", "system"], "on")


def test_the_same_graph_gives_the_same_records_byte_for_byte(tmp_path: Path) -> None:
    graph(tmp_path / "g", DRIVE, MOTOR)
    registry = (
        fixed("units", [unchecked("b"), unchecked("a")]),
        fixed("thermal", [thermal_failure("electrical.b", -1), thermal_failure("electrical.a")]),
    )
    first = PhysicsGate(registry).check(artefact(tmp_path / "g"), mode="on")
    second = PhysicsGate(registry).check(artefact(tmp_path / "g"), mode="on")
    assert first.model_dump_json() == second.model_dump_json()


def test_records_do_not_depend_on_the_order_a_check_reports_them_in(view: GraphView) -> None:
    # A check that walks a set or a mapping may report the same findings in
    # another order on another run; the records must not follow it.
    found = [thermal_failure("electrical.b", -1), thermal_failure("electrical.a", -3)]
    forward = PhysicsGate((fixed("thermal", found),)).run(view, ["system"], "on")
    backward = PhysicsGate((fixed("thermal", found[::-1]),)).run(view, ["system"], "on")
    assert forward.model_dump_json() == backward.model_dump_json()
    assert [r.node for r in forward.checks] == ["electrical.a", "electrical.b"]


def test_check_reads_the_graph_at_the_artefact_s_root(tmp_path: Path) -> None:
    graph(tmp_path / "g", DRIVE, MOTOR)
    seen: list[CheckContext] = []
    result = PhysicsGate((recording("units", seen),)).check(artefact(tmp_path / "g"), mode="on")
    assert result.verdict == "pass"
    assert list(seen[0].view.nodes) == ["electrical.drive", "electrical.motor_left"]


def test_the_bridge_checks_an_attempt_at_subtask_scope_with_every_node_its_own(
    tmp_path: Path,
) -> None:
    # Until the orchestrator's artefact carries its scopes and base revision, an
    # attempt is checked at subtask scope and every node counts as its own. The
    # bridge goes when the artefact carries both, and a test then asserts it is gone.
    assert scopes_and_base(artefact(tmp_path)) == (("subtask",), 0)
