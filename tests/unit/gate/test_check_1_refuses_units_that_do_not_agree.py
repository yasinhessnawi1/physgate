"""Check 1: every quantity and every relation an attempt touches is unit-consistent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pint
import pytest
from gate_fixtures import graph, node

from physgate.gate import check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import KINDS, QUANTITIES, RELATIONS, Entry, Kind
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import instances, side
from physgate.gate.runner import PhysicsGate
from physgate.gate.units import (
    PINT_ERRORS,
    Measured,
    UnitRefusedError,
    add,
    measure,
    pint_message,
)
from physgate.orchestrator.protocols import UncheckedDetails, UnitDetails

K = KINDS


def q(kind: str, value: float | int, unit: str) -> Measured:
    return measure(K[kind], value, unit)


# --- the kind rules pint cannot see, each with a passing and a refusing side -------

PASSING: list[tuple[str, Callable[[], Measured]]] = [
    ("a frequency in Hz", lambda: q("frequency", 50, "Hz")),
    ("an angular velocity in rpm", lambda: q("angular_velocity", 300, "rpm")),
    (
        "two angular velocities added",
        lambda: add(q("angular_velocity", 1, "rad/s"), q("angular_velocity", 60, "rpm")),
    ),
    ("a torque in N*m", lambda: q("torque", 0.5, "N*m")),
    ("a torque in kgf*cm", lambda: q("torque", 5, "kgf*cm")),
    ("a torque in N*mm", lambda: q("torque", 1, "N*mm")),
    ("a torque in ozf*in", lambda: q("torque", 1, "ozf*in")),
    ("an energy in Wh", lambda: q("energy", 20, "Wh")),
    ("an energy in W*s", lambda: q("energy", 1, "W*s")),
    ("an energy in kJ", lambda: q("energy", 1, "kJ")),
    ("a temperature in degC", lambda: q("temperature", 85, "degC")),
    ("a difference in K", lambda: q("temperature_difference", 30, "K")),
    ("a difference in delta_degC", lambda: q("temperature_difference", 30, "delta_degC")),
    (
        "a temperature plus a rise",
        lambda: add(q("temperature", 85, "degC"), q("temperature_difference", 30, "K")),
    ),
    ("a current in mA", lambda: q("current", 2400, "mA")),
]

REFUSED: list[tuple[str, Callable[[], Measured], str]] = [
    ("a frequency written in rad/s", lambda: q("frequency", 50, "rad/s"), "radian to the power 0"),
    (
        "an angular velocity written in Hz",
        lambda: q("angular_velocity", 5, "Hz"),
        "radian to the power 1",
    ),
    (
        "1 Hz + 1 rad/s",
        lambda: add(q("frequency", 1, "Hz"), q("angular_velocity", 1, "rad/s")),
        "a frequency is not added to an angular velocity",
    ),
    ("a torque written in J", lambda: q("torque", 0.5, "J"), "a torque is written as force*length"),
    ("an energy written in N*m", lambda: q("energy", 20, "N*m"), "an energy is written as energy"),
    (
        "a torque added to an energy",
        lambda: add(q("torque", 1, "N*m"), q("energy", 1, "J")),
        "a torque is not added to an energy",
    ),
    (
        "a difference written in degC",
        lambda: q("temperature_difference", 30, "degC"),
        "offset unit",
    ),
    (
        "two absolute temperatures added",
        lambda: add(q("temperature", 85, "degC"), q("temperature", 25, "degC")),
        "never added",
    ),
    ("a current written in V", lambda: q("current", 2.4, "V"), "cannot convert"),
    ("a unit pint cannot read", lambda: q("current", 1, "foo"), "not one pint can read"),
    ("a unit spelled as a sum", lambda: q("current", 1, "A + V"), "not one pint can read"),
    ("a unit longer than the bound", lambda: q("current", 1, "A" * 70), "longer than 64"),
]


@pytest.mark.parametrize(("case", "make"), PASSING, ids=[c for c, _ in PASSING])
def test_a_quantity_written_as_its_kind_passes(case: str, make: Callable[[], Measured]) -> None:
    assert make().quantity is not None


@pytest.mark.parametrize(("case", "make", "reason"), REFUSED, ids=[c for c, _, _ in REFUSED])
def test_a_quantity_not_written_as_its_kind_is_refused(
    case: str, make: Callable[[], Measured], reason: str
) -> None:
    with pytest.raises((UnitRefusedError, *PINT_ERRORS)) as caught:
        make()
    text = (
        str(caught.value)
        if isinstance(caught.value, UnitRefusedError)
        else pint_message(caught.value)
    )
    assert reason in text


def test_the_frequency_rule_is_needed_because_pint_alone_passes_the_sum() -> None:
    # The control: unit arithmetic alone adds 1 Hz to 1 rad/s and answers 2 rad/s.
    ureg = pint.UnitRegistry()
    assert (ureg.Quantity(1, "Hz") + ureg.Quantity(1, "rad/s")).to("rad/s").magnitude == 2


def test_the_torque_rule_is_needed_because_pint_alone_converts_it_to_energy() -> None:
    ureg = pint.UnitRegistry()
    assert ureg.Quantity(1, "N*m").to("J").magnitude == 1


def test_a_temperature_in_degrees_celsius_is_converted_to_kelvin_exactly() -> None:
    assert str(q("temperature", 85, "degC").magnitude) == "7163/20"


# --- the catalogue: every entry sourced, every relation evaluable -------------------


def test_every_kind_entry_and_relation_names_its_source() -> None:
    assert KINDS and QUANTITIES and RELATIONS
    assert all(k.source.strip() for k in KINDS.values())
    assert all(e.source.strip() for e in QUANTITIES.values())
    assert all(r.source.strip() for r in RELATIONS.values())


def test_an_entry_without_a_source_cannot_be_built() -> None:
    with pytest.raises(ValueError, match="source"):
        Entry(name="gizmo", kind="current")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Entry(name="gizmo", kind="current", source="")
    with pytest.raises(ValueError):
        Kind(name="gizmo", canonical="A", source="")


def test_every_catalogue_unit_is_one_pint_reads() -> None:
    for kind in KINDS.values():
        measure(kind, 1, kind.canonical if not kind.absolute else "K")


ALL_RELATIONS = (
    node("electrical.battery", quantities={"power_supply": (24, "W")}),
    node(
        "electrical.drive",
        kind="module",
        quantities={
            "power_supply": (15, "W"),
            "power_draw": (15, "W"),
            "mass": (0.3, "kg"),
            "heat_rejection_capacity": (4, "W"),
        },
        constrains=["electrical.battery"],
    ),
    node(
        "electrical.driver",
        quantities={
            "current_limit": (3, "A"),
            "input_power": (10, "W"),
            "output_power": (9, "W"),
            "heat_dissipation": (1, "W"),
            "thermal_resistance": (40, "K/W"),
            "ambient_temperature": (25, "degC"),
            "max_temperature": (125, "degC"),
            "mass": (0.1, "kg"),
        },
        constrains=["electrical.drive"],
    ),
    node(
        "electrical.motor_left",
        quantities={"power_draw": (9, "W"), "stall_current": (2.4, "A"), "mass": (0.2, "kg")},
        constrains=["electrical.drive", "electrical.driver"],
    ),
)


def test_every_relation_in_the_catalogue_is_instantiated_and_its_kinds_combine(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", *ALL_RELATIONS)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    found = instances(view)
    assert {i.relation.name for i in found} == set(RELATIONS)
    for instance in found:
        assert not instance.missing, instance.expression()
        left, right = side(view, instance.left), side(view, instance.right)
        assert left is not None and right is not None
        assert left.kind.name == right.kind.name or {left.kind.name, right.kind.name} == {
            "temperature",
            "temperature_difference",
        }, instance.expression()


# --- check 1 over a graph -----------------------------------------------------------


def run_check(
    tmp_path: Path, *payloads: dict[str, Any], base: tuple[dict[str, Any], ...] = ()
) -> Any:
    root = tmp_path / "g"
    head = graph(root, *base) if base else 0
    graph(root, *payloads)
    view = GraphView.read(root, base_revision=head)
    return check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))


DRIVER_IN = {
    "volts": node("electrical.driver", quantities={"current_limit": (2.4, "V")}),
    "milliamps": node("electrical.driver", quantities={"current_limit": (2400, "mA")}),
}
MOTOR = node(
    "electrical.motor_left",
    quantities={"stall_current": (2.4, "A")},
    constrains=["electrical.driver"],
)


def test_a_current_compared_with_a_voltage_is_refused_naming_the_expression_and_both_sides(
    tmp_path: Path,
) -> None:
    ran = run_check(tmp_path, DRIVER_IN["volts"], MOTOR)
    (finding,) = [o for o in ran.observations if o.outcome == "fail"]
    assert isinstance(finding.details, UnitDetails)
    assert finding.details.expression == (
        "stall_current(electrical.motor_left) <= current_limit(electrical.driver)"
    )
    assert (finding.details.left_unit, finding.details.right_unit) == ("ampere", "volt")
    # pint's own refusal is the finding's reason.
    assert "pint cannot convert 'ampere' ([current]) to 'volt'" in finding.message


def test_the_same_comparison_in_milliamps_passes(tmp_path: Path) -> None:
    ran = run_check(tmp_path, DRIVER_IN["milliamps"], MOTOR)
    assert [o for o in ran.observations if o.outcome == "fail"] == []
    assert ran.evaluated == 3  # two quantities and one relation


def test_a_power_draw_written_in_amperes_is_refused_where_it_meets_its_supply(
    tmp_path: Path,
) -> None:
    ran = run_check(
        tmp_path,
        node("electrical.drive", kind="module", quantities={"power_supply": (15, "W")}),
        node(
            "electrical.motor_left",
            quantities={"power_draw": (2.4, "A")},
            constrains=["electrical.drive"],
        ),
    )
    (finding,) = [o for o in ran.observations if o.outcome == "fail"]
    assert finding.node == "electrical.drive"
    assert "ampere" in finding.message and "watt" in finding.message


def test_a_quantity_in_no_relation_is_held_to_its_kind(tmp_path: Path) -> None:
    ran = run_check(tmp_path, node("electrical.imu", quantities={"sample_rate": (50, "rad/s")}))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "radian to the power 0" in finding.message
    assert finding.details.form == "units"


def test_an_unreadable_unit_is_refused(tmp_path: Path) -> None:
    ran = run_check(tmp_path, node("electrical.imu", quantities={"sample_rate": (50, "herz")}))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "not one pint can read" in finding.message


def test_quantities_the_catalogue_does_not_know_are_recorded_as_unchecked(tmp_path: Path) -> None:
    ran = run_check(
        tmp_path,
        node("electrical.imu", quantities={"gizmo_rate": (3, "Hz"), "widget": (1, "m")}),
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked"
    assert record.details.quantities == ("gizmo_rate", "widget")


def test_only_the_attempt_s_own_nodes_are_checked(tmp_path: Path) -> None:
    earlier = node("electrical.imu", quantities={"sample_rate": (50, "rad/s")})
    ran = run_check(tmp_path, node("electrical.led"), base=(earlier,))
    assert ran.observations == ()


def test_the_unchecked_count_is_on_the_gate_result_of_every_attempt(tmp_path: Path) -> None:
    root = tmp_path / "g"
    graph(
        root,
        node("electrical.imu", quantities={"gizmo_rate": (3, "Hz"), "sample_rate": (50, "Hz")}),
    )
    result = PhysicsGate().run(GraphView.read(root, base_revision=0), ["subtask"], "on")
    unchecked = [r for r in result.checks if r.outcome == "unchecked" and r.name == "units"]
    names = [d.quantities for r in unchecked if isinstance(d := r.details, UncheckedDetails)]
    assert len(unchecked) == len(names) == 1 and names[0] == ("gizmo_rate",)
    assert result.verdict == "pass"


def test_a_temperature_limit_written_in_degrees_celsius_is_not_refused(tmp_path: Path) -> None:
    # 25 degC + 40 K/W * 2 W <= 125 degC: pint alone refuses the sum with an offset
    # unit; the absolute temperature enters in kelvin, so the relation is readable.
    ran = run_check(
        tmp_path,
        node(
            "electrical.driver",
            quantities={
                "thermal_resistance": (40, "K/W"),
                "heat_dissipation": (2, "W"),
                "ambient_temperature": (25, "degC"),
                "max_temperature": (125, "degC"),
            },
        ),
    )
    assert ran.observations == () and ran.evaluated == 5


def test_a_supply_nothing_draws_from_is_not_a_unit_error(tmp_path: Path) -> None:
    # Found by the injected-error suite: an empty side of a relation was read as
    # a dimensionless zero, and compared with watts, which pint refuses.
    ran = run_check(
        tmp_path,
        node("electrical.battery", quantities={"power_supply": (20, "W")}),
        node("electrical.drive", kind="module", quantities={"heat_rejection_capacity": (3, "W")}),
    )
    assert [o for o in ran.observations if o.outcome == "fail"] == []
