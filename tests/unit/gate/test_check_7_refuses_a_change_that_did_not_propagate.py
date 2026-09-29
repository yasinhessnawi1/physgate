"""Check 7: a changed quantity reaches every node it constrains, or the node says why not.

The architecture's acceptance test is the first group, verbatim: a motor swapped
for one with a different stall current, with the current budget, the loop gain
and the mount inertia left as they were, fails; with all three rewritten it
passes; with one justified and two rewritten it passes (ARCH-082). The rest pin
each reading of "changed", "rewritten" and "the same commit" the check makes,
each with the case that would pass if the reading were looser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import changed, integrated, node

from physgate.gate import check_propagation
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.exceptions import ChangeHistoryError
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.gate.registry import RegisteredCheck
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.protocols import (
    ChangeSet,
    CheckRecord,
    GateResult,
    PropagationDetails,
    UncheckedDetails,
)

MOTOR = "motor.left"
BUDGET, GAIN, MOUNT = "power.budget", "control.loop_gain", "chassis.mount"
REASON = "the budget was sized for a 4 A stall and keeps its headroom"


def motor(amps: float = 2.4, constrains: tuple[str, ...] = (BUDGET, GAIN, MOUNT)) -> dict[str, Any]:
    return node(MOTOR, quantities={"stall_current": (amps, "A")}, constrains=constrains)


def budget(amps: float = 5.0, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - node fields
    return {**node(BUDGET, kind="module", quantities={"current_limit": (amps, "A")}), **extra}


def gain(value: float = 12.0, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - node fields
    return {
        **node(GAIN, domain="control", quantities={"loop_gain": (value, "dimensionless")}),
        **extra,
    }


def mount(inertia: float = 0.004, **extra: Any) -> dict[str, Any]:  # noqa: ANN401 - node fields
    payload = node(
        MOUNT, domain="mechanical", quantities={"moment_of_inertia": (inertia, "kg*m**2")}
    )
    return {**payload, **extra}


BASE = (motor(), budget(), gain(), mount())


def judged(root: Path, history: ChangeHistory | None) -> list[CheckRecord]:
    """Check 7 alone, through the runner, at system scope, with its records stamped."""
    gate = PhysicsGate((RegisteredCheck(name="propagation", run=check_propagation.run),))
    return list(gate.run(GraphView.read(root, 0, history), ("system",), "on").checks)


def failures(records: list[CheckRecord]) -> list[CheckRecord]:
    return [r for r in records if r.outcome == "fail"]


def unwritten(records: list[CheckRecord]) -> set[str]:
    return {
        edge
        for r in failures(records)
        if isinstance(r.details, PropagationDetails)
        for edge in r.details.unwritten
    }


def unchecked(records: list[CheckRecord]) -> list[CheckRecord]:
    return [r for r in records if r.outcome == "unchecked"]


def evaluated(records: list[CheckRecord]) -> int:
    (passed,) = [r for r in records if r.outcome == "pass"]
    return passed.details.evaluated  # type: ignore[union-attr]


# --- the architecture's acceptance test, verbatim ---------------------------------------


def test_a_motor_swapped_with_nothing_it_constrains_rewritten_fails_naming_the_three_edges(
    tmp_path: Path,
) -> None:
    history = changed(tmp_path / "g", BASE, [motor(3.1)])
    records = judged(tmp_path / "g", history)
    (failure,) = failures(records)
    assert failure.blocking and failure.node == MOTOR and failure.scope == "system"
    assert isinstance(failure.details, PropagationDetails)
    assert failure.details.unwritten == (
        f"{MOTOR}->{MOUNT}",
        f"{MOTOR}->{GAIN}",
        f"{MOTOR}->{BUDGET}",
    )
    assert failure.value is not None and (failure.value.value, failure.value.unit) == (3.1, "A")
    assert "stall_current" in failure.message


def test_the_same_swap_passes_when_all_three_are_rewritten_after_it(tmp_path: Path) -> None:
    history = changed(
        tmp_path / "g", BASE, [motor(3.1)], [budget(6.0)], [gain(10.0)], [mount(0.005)]
    )
    records = judged(tmp_path / "g", history)
    assert failures(records) == [] and unchecked(records) == []
    assert evaluated(records) == 3


def test_the_same_swap_passes_when_one_is_justified_and_two_are_rewritten(tmp_path: Path) -> None:
    excused = budget(no_change_justified={MOTOR: REASON})
    history = changed(tmp_path / "g", BASE, [motor(3.1)], [excused], [gain(10.0)], [mount(0.005)])
    records = judged(tmp_path / "g", history)
    assert failures(records) == []
    (justified,) = unchecked(records)
    assert BUDGET in justified.message and REASON in justified.message
    assert "not verified" in justified.message
    assert isinstance(justified.details, UncheckedDetails)
    assert justified.details.quantities == ("stall_current",)
    assert evaluated(records) == 2  # the justified edge is not counted as passed


def test_the_same_swap_fails_naming_only_the_edge_left_unwritten(tmp_path: Path) -> None:
    history = changed(tmp_path / "g", BASE, [motor(3.1)], [budget(6.0)], [gain(10.0)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{MOUNT}"}


def test_the_swap_is_refused_by_the_registered_gate_at_the_integration_call(
    tmp_path: Path,
) -> None:
    """Criterion 2: the real runner, the loop's call, on a design that breaks only check 7."""
    history = changed(tmp_path / "g", BASE, [motor(3.1)])
    gate = default_registrations().gate
    assert gate is not None
    result: GateResult = gate.check_integration(integrated(tmp_path / "g", history), mode="on")
    assert result.verdict == "fail" and result.failing_check == "propagation"
    blocking = {r.name for r in result.checks if r.outcome == "fail" and r.blocking}
    assert blocking == {"propagation"}
    assert [q.name for q in result.quantities] == ["stall_current"]
    observed = gate.check_integration(integrated(tmp_path / "g", history), mode="observe")
    assert observed.verdict == "fail" and observed.mode == "observe"
    assert all(r.gate_mode == "observe" for r in observed.checks)


def test_check_7_runs_only_at_system_scope(tmp_path: Path) -> None:
    changed(tmp_path / "g", BASE, [motor(3.1)])
    gate = default_registrations().gate
    assert isinstance(gate, PhysicsGate)
    attempt = gate.run(GraphView.read(tmp_path / "g", 4), ("subtask", "module"), "on")
    assert "propagation" not in {r.name for r in attempt.checks}


# --- what "changed" means -------------------------------------------------------------


def test_a_target_rewritten_with_the_same_numbers_has_not_followed(tmp_path: Path) -> None:
    history = changed(
        tmp_path / "g", BASE, [motor(3.1)], [budget(5.0)], [gain(10.0)], [mount(0.005)]
    )
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


def test_a_target_respelled_in_another_unit_has_not_followed(tmp_path: Path) -> None:
    respelled = {
        **budget(),
        "quantities": {
            "current_limit": {
                **budget()["quantities"]["current_limit"],
                "value": 5000.0,
                "unit": "mA",
            }
        },
    }
    history = changed(tmp_path / "g", BASE, [motor(3.1)], [respelled], [gain(10.0)], [mount(0.005)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


def test_a_source_respelled_in_another_unit_owes_nothing(tmp_path: Path) -> None:
    respelled = {
        **motor(),
        "quantities": {
            "stall_current": {
                **motor()["quantities"]["stall_current"],
                "value": 2400.0,
                "unit": "mA",
            }
        },
    }
    records = judged(tmp_path / "g", changed(tmp_path / "g", BASE, [respelled]))
    assert failures(records) == [] and evaluated(records) == 0


def test_a_source_rewritten_with_the_same_numbers_owes_nothing(tmp_path: Path) -> None:
    records = judged(tmp_path / "g", changed(tmp_path / "g", BASE, [motor(2.4)]))
    assert failures(records) == [] and evaluated(records) == 0


def test_a_source_that_gains_a_quantity_has_changed(tmp_path: Path) -> None:
    grown = {
        **motor(),
        "quantities": {
            **motor()["quantities"],
            "mass": {"value": 0.1, "unit": "kg", "source": "datasheet", "written_by": "electrical"},
        },
    }
    records = judged(tmp_path / "g", changed(tmp_path / "g", BASE, [grown]))
    assert len(unwritten(records)) == 3


def test_a_created_node_owes_what_it_constrains_that_existed_before_it(tmp_path: Path) -> None:
    """Adding a motor without revisiting the budget is the swap's error again."""
    base = (budget(), gain(), mount())
    records = judged(tmp_path / "g", changed(tmp_path / "g", base, [motor(3.1)]))
    assert len(unwritten(records)) == 3


def test_a_created_node_owes_nothing_to_targets_created_with_it_or_after(tmp_path: Path) -> None:
    history = changed(tmp_path / "g", (), [motor(3.1), budget()], [gain(), mount()])
    records = judged(tmp_path / "g", history)
    assert failures(records) == [] and evaluated(records) == 3


# --- what "the same commit, or later" means -------------------------------------------------


def test_a_target_rewritten_in_the_same_change_set_has_followed(tmp_path: Path) -> None:
    history = changed(tmp_path / "g", BASE, [motor(3.1), budget(6.0), gain(10.0), mount(0.005)])
    assert failures(judged(tmp_path / "g", history)) == []


def test_a_target_rewritten_before_the_change_has_not_followed(tmp_path: Path) -> None:
    history = changed(tmp_path / "g", BASE, [budget(6.0), gain(10.0), mount(0.005)], [motor(3.1)])
    assert len(unwritten(judged(tmp_path / "g", history))) == 3


def test_a_second_change_is_owed_again(tmp_path: Path) -> None:
    history = changed(
        tmp_path / "g", BASE, [motor(3.1)], [budget(6.0), gain(10.0), mount(0.005)], [motor(3.5)]
    )
    assert len(unwritten(judged(tmp_path / "g", history))) == 3


def test_an_edge_the_change_dropped_is_still_owed(tmp_path: Path) -> None:
    dropped = motor(3.1, constrains=(GAIN, MOUNT))
    history = changed(tmp_path / "g", BASE, [dropped], [gain(10.0)], [mount(0.005)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


# --- the justification ----------------------------------------------------------------------


def test_a_justification_written_before_the_source_changed_again_covers_nothing(
    tmp_path: Path,
) -> None:
    excused = budget(no_change_justified={MOTOR: REASON})
    history = changed(
        tmp_path / "g",
        BASE,
        [motor(3.1)],
        [excused, gain(10.0), mount(0.005)],
        [motor(3.6)],
        [gain(9.0)],
        [mount(0.006)],
    )
    records = judged(tmp_path / "g", history)
    assert unwritten(records) == {f"{MOTOR}->{BUDGET}"} and unchecked(records) == []


def test_a_justification_in_the_given_design_covers_no_change_made_after_it(
    tmp_path: Path,
) -> None:
    base = (motor(), budget(no_change_justified={MOTOR: REASON}), gain(), mount())
    history = changed(tmp_path / "g", base, [motor(3.1)], [gain(10.0)], [mount(0.005)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


def test_a_justification_for_another_source_does_not_cover_this_one(tmp_path: Path) -> None:
    excused = budget(no_change_justified={"motor.right": REASON})
    history = changed(tmp_path / "g", BASE, [motor(3.1)], [excused], [gain(10.0)], [mount(0.005)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


def test_a_justification_on_the_source_does_not_excuse_it(tmp_path: Path) -> None:
    """The changer excusing itself is not the target's owner saying the target is fine."""
    self_excused = {**motor(3.1), "no_change_justified": {BUDGET: REASON}}
    history = changed(tmp_path / "g", BASE, [self_excused], [gain(10.0)], [mount(0.005)])
    assert unwritten(judged(tmp_path / "g", history)) == {f"{MOTOR}->{BUDGET}"}


# --- what the check records as unchecked ---------------------------------------------------


def test_an_edge_into_an_interface_is_unchecked_not_failed(tmp_path: Path) -> None:
    bus = node("iface.power_bus", kind="interface", quantities={"supply_voltage": (12, "V")})
    base = (motor(constrains=("iface.power_bus",)), bus)
    records = judged(
        tmp_path / "g", changed(tmp_path / "g", base, [motor(3.1, constrains=("iface.power_bus",))])
    )
    (record,) = unchecked(records)
    assert failures(records) == [] and "interface" in record.message


def test_an_edge_into_a_node_that_does_not_exist_is_unchecked_not_failed(tmp_path: Path) -> None:
    records = judged(
        tmp_path / "g", changed(tmp_path / "g", (), [motor(3.1, constrains=("power.nowhere",))])
    )
    (record,) = unchecked(records)
    assert failures(records) == [] and "not in the graph" in record.message


def test_with_no_history_nothing_is_passed_and_the_unjudged_quantities_are_named(
    tmp_path: Path,
) -> None:
    changed(tmp_path / "g", BASE, [motor(3.1)])
    records = judged(tmp_path / "g", None)
    (record,) = unchecked(records)
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("stall_current",)
    assert [r.outcome for r in records] == ["pass", "unchecked"]
    assert evaluated(records) == 0


def test_with_no_history_and_no_edges_there_is_nothing_to_judge(tmp_path: Path) -> None:
    changed(tmp_path / "g", (budget(), gain()))
    assert (
        unchecked(judged(tmp_path / "g", None)) == []
        and evaluated(judged(tmp_path / "g", None)) == 0
    )


# --- chains and cycles ----------------------------------------------------------------------------


def test_a_rewritten_target_owes_its_own_targets(tmp_path: Path) -> None:
    battery = node("power.battery", kind="module", quantities={"energy_capacity": (20, "W*h")})
    chained = budget(constrains=["power.battery"])
    base = (motor(constrains=(BUDGET,)), {**chained}, battery)
    history = changed(
        tmp_path / "g",
        base,
        [motor(3.1, constrains=(BUDGET,))],
        [budget(6.0, constrains=["power.battery"])],
    )
    assert unwritten(judged(tmp_path / "g", history)) == {f"{BUDGET}->power.battery"}


def test_a_cycle_across_owners_is_closed_only_by_a_justification(tmp_path: Path) -> None:
    a = motor(constrains=(GAIN,))
    b = gain(constrains=[MOTOR])
    history = changed(
        tmp_path / "g", (a, b), [motor(3.1, constrains=(GAIN,))], [gain(10.0, constrains=[MOTOR])]
    )
    assert unwritten(judged(tmp_path / "g", history)) == {f"{GAIN}->{MOTOR}"}
    root = tmp_path / "h"
    closed = {
        **motor(3.1, constrains=(GAIN,)),
        "no_change_justified": {GAIN: "the gain was retuned for this motor"},
    }
    history = changed(
        root, (a, b), [motor(3.1, constrains=(GAIN,))], [gain(10.0, constrains=[MOTOR])], [closed]
    )
    records = judged(root, history)
    assert failures(records) == [] and len(unchecked(records)) == 1


# --- a history that is not this journal's -------------------------------------------------------


@pytest.mark.parametrize(
    "history",
    [
        ChangeHistory(baseline=4, change_sets=()),
        ChangeHistory(
            baseline=4, change_sets=(ChangeSet(subtask_id="s1", attempt=1, revisions=(5, 6)),)
        ),
        ChangeHistory(baseline=9, change_sets=()),
        ChangeHistory(
            baseline=4,
            change_sets=(
                ChangeSet(subtask_id="s2", attempt=1, revisions=(5,)),
                ChangeSet(subtask_id="s1", attempt=1, revisions=(5,)),
            ),
        ),
    ],
    ids=[
        "a revision left out",
        "a revision the journal lacks",
        "a baseline past the head",
        "a revision twice",
    ],
)
def test_a_history_that_does_not_describe_the_journal_is_refused(
    tmp_path: Path, history: ChangeHistory
) -> None:
    changed(tmp_path / "g", BASE, [motor(3.1)])
    with pytest.raises(ChangeHistoryError):
        GraphView.read(tmp_path / "g", 0, history)


def test_the_check_reads_what_the_context_hands_it(tmp_path: Path) -> None:
    history = changed(tmp_path / "g", BASE, [motor(3.1)])
    ctx = CheckContext(
        view=GraphView.read(tmp_path / "g", 0, history), scope="system", bounds=load_bounds()
    )
    ran = check_propagation.run(ctx)
    assert ran.tool.startswith("graph traversal") and len(ran.observations) == 1


@pytest.mark.integration
def test_propagation_over_a_dense_graph_is_measured(tmp_path: Path) -> None:
    # The dense graph the power check is timed on: 40 supplies and 160 consumers
    # each constraining all of them, 6,400 edges, created in sixteen change sets
    # of ten, then every supply rewritten in a seventeenth. A measurement, not a
    # bound: the time is printed for the record and nothing is asserted about it.
    import time

    supplies = [
        node(f"electrical.s{i:02d}", kind="module", quantities={"power_supply": (10_000, "W")})
        for i in range(40)
    ]
    ids = [s["id"] for s in supplies]
    consumers = [
        node(f"electrical.c{i:03d}", quantities={"power_draw": (1.25, "W")}, constrains=ids)
        for i in range(160)
    ]
    rewritten = [
        node(f"electrical.s{i:02d}", kind="module", quantities={"power_supply": (12_000, "W")})
        for i in range(40)
    ]
    sets = [consumers[i : i + 10] for i in range(0, 160, 10)]
    history = changed(tmp_path / "g", supplies, *sets, rewritten)
    view = GraphView.read(tmp_path / "g", 0, history)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds())
    started = time.perf_counter()
    ran = check_propagation.run(ctx)
    took = time.perf_counter() - started
    assert ran.evaluated == 6400 and ran.observations == ()
    print(f"propagation over 6,400 edges in 17 change sets: {took:.4f} s")
