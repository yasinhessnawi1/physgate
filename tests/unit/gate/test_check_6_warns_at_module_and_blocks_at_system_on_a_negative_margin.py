"""Check 6: thermal margins in K and in W; the same negative margin warns, then blocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gate_fixtures import graph, node

from physgate.gate import check_thermal
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import Scope, ThermalDetails

DRIVE = node("electrical.drive", kind="module")


def driver(watts: float | int, ambient: tuple[float | int, str] = (25, "degC")) -> dict[str, Any]:
    """A driver: 40 K/W to ambient, limited to 125 degC."""
    return node(
        "electrical.driver",
        quantities={
            "thermal_resistance": (40, "K/W"),
            "heat_dissipation": (watts, "W"),
            "ambient_temperature": ambient,
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.drive"],
    )


def check(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return check_thermal.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


def test_a_component_past_its_temperature_limit_has_a_negative_margin_in_kelvin(
    tmp_path: Path,
) -> None:
    # 25 degC + 40 K/W * 2.6 W = 129 degC, against a limit of 125 degC: -4 K.
    ran = check(tmp_path, "module", DRIVE, driver(2.6))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.driver"
    assert isinstance(finding.details, ThermalDetails)
    assert (finding.details.margin.value, finding.details.margin.unit) == (-4, "K")


def test_a_component_within_its_limit_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, "module", DRIVE, driver(2.5))  # exactly 125 degC: margin 0
    assert ran.observations == () and ran.evaluated == 1


def test_ambient_in_kelvin_and_in_celsius_give_the_same_margin(tmp_path: Path) -> None:
    celsius = check(tmp_path / "c", "system", DRIVE, driver(2.6)).observations[0]
    kelvin = check(tmp_path / "k", "system", DRIVE, driver(2.6, (298.15, "K"))).observations[0]
    assert celsius.details == kelvin.details


def test_a_module_rejecting_less_heat_than_its_members_make_has_a_negative_margin_in_watts(
    tmp_path: Path,
) -> None:
    ran = check(
        tmp_path,
        "module",
        node("electrical.drive", kind="module", quantities={"heat_rejection_capacity": (3, "W")}),
        node(
            "electrical.a",
            quantities={"heat_dissipation": (2, "W")},
            constrains=["electrical.drive"],
        ),
        node(
            "electrical.b",
            quantities={"heat_dissipation": (1.5, "W")},
            constrains=["electrical.drive"],
        ),
    )
    (finding,) = ran.observations
    assert isinstance(finding.details, ThermalDetails)
    assert (finding.details.margin.value, finding.details.margin.unit) == (-0.5, "W")


def test_a_component_giving_only_some_thermal_quantities_is_unchecked(tmp_path: Path) -> None:
    partial = node(
        "electrical.driver",
        quantities={"thermal_resistance": (40, "K/W")},
        constrains=["electrical.drive"],
    )
    (record,) = check(tmp_path, "module", DRIVE, partial).observations
    assert record.outcome == "unchecked"


def test_the_same_negative_margin_warns_at_module_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", DRIVE, driver(2.6))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["module"], "on")
    assert result.verdict == "pass"
    thermal = [r for r in result.checks if r.name == "thermal"]
    assert [(r.outcome, r.blocking, r.scope) for r in thermal] == [("warn", False, "module")]
    assert "1 warning" in result.finding


def test_the_same_negative_margin_blocks_at_system_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", DRIVE, driver(2.6))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["system"], "on")
    assert result.verdict == "fail" and result.failing_check == "thermal"
    thermal = [r for r in result.checks if r.name == "thermal"]
    assert [(r.outcome, r.blocking, r.scope) for r in thermal] == [("fail", True, "system")]
    assert result.numeric_output is not None and result.numeric_output.unit == "K"
