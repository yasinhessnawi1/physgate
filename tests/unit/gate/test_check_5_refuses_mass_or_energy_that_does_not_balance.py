"""Check 5: a module's mass and a node's energy balance, within declared rounding only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gate_fixtures import graph, node

from physgate.gate import check_conservation
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import ConservationDetails


def drive(mass: float | int | None) -> dict[str, Any]:
    quantities = {"mass": (mass, "kg")} if mass is not None else {}
    return node("electrical.drive", kind="module", quantities=quantities)


def part(name: str, mass: float | int, unit: str = "kg") -> dict[str, Any]:
    return node(
        f"electrical.{name}", quantities={"mass": (mass, unit)}, constrains=["electrical.drive"]
    )


def converter(inp: float, out: float, heat: float | None) -> dict[str, Any]:
    quantities = {"input_power": (inp, "W"), "output_power": (out, "W")}
    if heat is not None:
        quantities["heat_dissipation"] = (heat, "W")
    return node("electrical.driver", quantities=quantities, constrains=["electrical.drive"])


def check(tmp_path: Path, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return check_conservation.run(CheckContext(view=view, scope="module", bounds=load_bounds()))


def test_a_module_heavier_than_its_parts_is_refused_with_the_imbalance_and_terms(
    tmp_path: Path,
) -> None:
    ran = check(tmp_path, drive(0.9), part("motor_left", 0.2), part("motor_right", 0.2))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.drive"
    details = finding.details
    assert isinstance(details, ConservationDetails)
    assert (details.imbalance.value, details.imbalance.unit) == (0.5, "kg")
    assert [(t.node_id, t.name) for t in details.terms] == [
        ("electrical.drive", "mass"),
        ("electrical.motor_left", "mass"),
        ("electrical.motor_right", "mass"),
    ]


def test_a_module_whose_mass_is_its_parts_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, drive(0.4), part("motor_left", 0.2), part("motor_right", 200, "g"))
    assert ran.observations == () and ran.evaluated == 1


def test_a_difference_rounding_explains_passes_and_one_it_does_not_is_refused(
    tmp_path: Path,
) -> None:
    # Parts 0.123 + 0.456 = 0.579 kg. Allowance 0.005 * (0.58 + 0.579) = 0.0058 kg.
    assert check(tmp_path / "a", drive(0.58), part("a", 0.123), part("b", 0.456)).observations == ()
    (finding,) = check(tmp_path / "b", drive(0.59), part("a", 0.123), part("b", 0.456)).observations
    assert finding.outcome == "fail"


def test_power_in_that_is_not_power_out_plus_heat_is_refused(tmp_path: Path) -> None:
    ran = check(tmp_path, drive(None), converter(10, 9, 0.5))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.driver"
    assert isinstance(finding.details, ConservationDetails)
    assert finding.details.imbalance.value == 0.5
    assert "input_power(electrical.driver) == output_power" in finding.message


def test_an_energy_balance_that_holds_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, drive(None), converter(10, 9, 1))
    assert ran.observations == () and ran.evaluated == 1


def test_a_balance_with_a_term_missing_is_unchecked_never_passed(tmp_path: Path) -> None:
    ran = check(
        tmp_path,
        drive(None),
        part("motor_left", 0.2),
        node(
            "electrical.driver",
            quantities={"input_power": (10, "W")},
            constrains=["electrical.drive"],
        ),
    )
    outcomes = sorted((o.outcome, o.node) for o in ran.observations)
    assert outcomes == [("unchecked", "electrical.drive"), ("unchecked", "electrical.driver")]
    assert ran.evaluated == 0


def test_the_real_gate_refuses_the_imbalance_at_module_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", drive(0.9), part("motor_left", 0.2))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["module"], "on")
    assert result.verdict == "fail" and result.failing_check == "conservation"


def test_only_the_modules_the_attempt_touched_are_balanced(tmp_path: Path) -> None:
    root = tmp_path / "g"
    head = graph(
        root,
        drive(0.9),
        part("motor_left", 0.2),  # an earlier imbalance, not this attempt's
        node("electrical.control", kind="module", quantities={"mass": (0.1, "kg")}),
    )
    graph(
        root,
        node("electrical.mcu", quantities={"mass": (0.1, "kg")}, constrains=["electrical.control"]),
    )
    view = GraphView.read(root, base_revision=head)
    ran = check_conservation.run(CheckContext(view=view, scope="module", bounds=load_bounds()))
    assert ran.observations == () and ran.evaluated == 1


def test_a_part_that_constrains_a_component_for_another_reason_is_not_its_mass(
    tmp_path: Path,
) -> None:
    # A 0.2 kg motor constrains its 0.1 kg driver electrically. The driver is a
    # component, so its mass is not the sum of what constrains it: no balance.
    graph(
        tmp_path / "g",
        node("electrical.driver", quantities={"mass": (0.1, "kg")}),
        node(
            "electrical.motor",
            quantities={"mass": (0.2, "kg")},
            constrains=["electrical.driver"],
        ),
    )
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["module", "system"], "on")
    assert result.verdict == "pass"
    assert not [r for r in result.checks if r.name == "conservation" and r.outcome != "pass"]
