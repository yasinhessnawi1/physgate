"""Check 4, current headroom: a motor's stall current against its driver's current limit.

At stall a brushed motor has no back-EMF and draws its stall current; a driver whose peak
output current is below that cannot carry it. The catalogue's ``current_limit`` is that peak
rating, so the relation is judged with no allowance, and refused with the excess in amperes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_power, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import RELATIONS
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import PowerDetails, Scope

DRIVER = "electrical.driver"


def driver(amps: float | int = 1, unit: str = "A") -> dict[str, Any]:
    return node(DRIVER, quantities={"current_limit": (amps, unit)})


def motor(amps: float | int = 6, unit: str = "A", side: str = "left") -> dict[str, Any]:
    return node(
        f"electrical.motor_{side}",
        quantities={"stall_current": (amps, unit)},
        constrains=[DRIVER],
    )


def check(tmp_path: Path, scope: Scope, *payloads: dict[str, Any], base: int = 0) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=base)
    return check_power.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


def test_the_headroom_relation_is_judged_by_the_power_check() -> None:
    assert RELATIONS["current_limit"].judged_by == 4
    assert "peak" in RELATIONS["current_limit"].source


@pytest.mark.parametrize("scope", ["module", "system"])
def test_a_6_ampere_stall_on_a_1_ampere_driver_is_refused_with_the_excess(
    tmp_path: Path, scope: Scope
) -> None:
    ran = check(tmp_path, scope, driver(1), motor(6))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == DRIVER
    assert finding.value is not None and (finding.value.value, finding.value.unit) == (5, "A")
    assert isinstance(finding.details, PowerDetails)
    assert finding.details.contributing == (DRIVER, "electrical.motor_left")
    assert "stalls at 6 A, more than the 1 A current limit" in finding.message
    assert ran.evaluated == 1


def test_a_stall_current_equal_to_the_limit_passes_and_is_counted(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", driver(1.8), motor(1.8))
    assert ran.observations == () and ran.evaluated == 1


@pytest.mark.parametrize(
    ("stall", "unit", "refused"),
    [(1600, "mA", False), (1801, "mA", True), (0.0018, "kA", False)],
)
def test_the_comparison_is_made_in_one_unit_whatever_each_side_is_written_in(
    tmp_path: Path, stall: float, unit: str, refused: bool
) -> None:
    ran = check(tmp_path, "system", driver(1.8), motor(stall, unit))
    assert [o.outcome for o in ran.observations] == (["fail"] if refused else [])


def test_each_motor_on_a_driver_is_held_to_the_limit_on_its_own(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", driver(1.8), motor(1.6, side="left"), motor(2.2, side="right"))
    (finding,) = ran.observations
    assert "electrical.motor_right stalls at 2.2 A" in finding.message
    assert ran.evaluated == 2


def test_a_negative_current_is_recorded_as_unchecked_never_passed(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", driver(1), motor(-6))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "not a magnitude" in record.message


def test_a_side_in_a_unit_the_unit_check_refuses_is_unchecked_here(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", driver(1, "V"), motor(6))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "unit the unit check refuses" in record.message


def test_an_attempt_that_writes_only_the_motor_is_judged_against_the_driver(
    tmp_path: Path,
) -> None:
    # The driver is the given design; the attempt writes the motor alone. The relation's
    # subject is the driver, which the attempt reaches through the motor's edge.
    root = tmp_path / "g"
    base = graph(root, driver(1))
    graph(root, motor(6))
    view = GraphView.read(root, base_revision=base)
    ran = check_power.run(CheckContext(view=view, scope="module", bounds=load_bounds()))
    assert [o.outcome for o in ran.observations] == ["fail"]


def test_the_unit_check_no_longer_calls_the_headroom_unjudged(tmp_path: Path) -> None:
    graph(tmp_path / "g", driver(1), motor(6))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))
    assert ran.observations == ()


def test_the_whole_gate_blocks_the_stall_at_module_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", driver(1), motor(6))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask", "module"], "on")
    assert result.verdict == "fail"
    blocking = [r for r in result.checks if r.outcome == "fail" and r.blocking]
    assert [(r.name, r.node) for r in blocking] == [("power", DRIVER)]


def test_a_headroom_left_unchecked_by_a_refused_unit_is_not_counted_as_evaluated(
    tmp_path: Path,
) -> None:
    # Evaluated means judged: a comparison the check could not make is recorded, not counted.
    ran = check(tmp_path, "system", driver(1, "V"), motor(6))
    assert [o.outcome for o in ran.observations] == ["unchecked"] and ran.evaluated == 0


# --- named limits, pinned so the record says what the relation does not do -----------------


def test_paralleled_drivers_are_each_held_to_their_own_limit_a_named_limit(tmp_path: Path) -> None:
    # Two 1 A drivers sharing a 1.5 A stall carry it together; the relation reads each edge
    # alone and refuses both. The evaluation scores this as the stated limit.
    a = node("electrical.driver_a", quantities={"current_limit": (1, "A")})
    b = node("electrical.driver_b", quantities={"current_limit": (1, "A")})
    shared = node(
        "electrical.motor_left",
        quantities={"stall_current": (1.5, "A")},
        constrains=["electrical.driver_a", "electrical.driver_b"],
    )
    ran = check(tmp_path, "system", a, b, shared)
    assert sorted(o.node for o in ran.observations) == [
        "electrical.driver_a",
        "electrical.driver_b",
    ]
    assert all(o.outcome == "fail" for o in ran.observations)


def test_a_limit_past_a_regulator_that_declares_none_is_not_read_a_named_limit(
    tmp_path: Path,
) -> None:
    regulator = node("electrical.reg", constrains=[DRIVER])
    behind = node(
        "electrical.motor_left",
        quantities={"stall_current": (6, "A")},
        constrains=["electrical.reg"],
    )
    ran = check(tmp_path, "system", driver(1), regulator, behind)
    assert ran.observations == () and ran.evaluated == 0
