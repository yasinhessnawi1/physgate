"""The correct designs the delta review probed: each ends unchecked or passes, never refused.

The review wrote forty-odd small graphs that are correct and that items 4 to 6 had refused:
legitimate figures outside a product-class envelope (a 72 V pack, a 300 C hotend), names a
suffix misread (``eddy_current`` in watts, ``servo_position`` in degrees, a negative
``braking_torque``), a gearmotor whose ``torque_peak`` is the motor's, a carrier whose
``constrains`` edges are not all "is carried by", an unequal split over two brackets. Each
is pinned here with the outcome the rulings give it. The named limits the rulings keep are
pinned as refusals, so that a change to them is seen: a cantilevered unit, a reaction or a
supported mass written as a rated capacity, two motors on one node. Two probes put a
catalogued quantity in a unit of the wrong dimension (a reaction moment in newtons); the
unit check refuses those, as it should, and the readings leave them unchecked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_equilibrium, check_magnitude, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate

E, M, C, F = "electrical", "mechanical", "control", "firmware"
CLEAN = "clean"
LIMIT = "a named limit of the readings: refused"
WRONG_UNIT = "a catalogued quantity in a wrong-dimension unit: the unit check refuses it"


def one(domain: str, name: str, value: float, unit: str, node_id: str = "part") -> dict[str, Any]:
    return node(f"{domain}.{node_id}", domain=domain, quantities={name: (value, unit)})


def unit(reaction: float, **more: tuple[float, str]) -> dict[str, Any]:
    q: dict[str, Any] = {"torque_peak": (2, "N*m"), "reaction_moment": (reaction, "N*m"), **more}
    return node(f"{M}.motor", domain=M, quantities=q)


PROBES: list[tuple[str, str, list[dict[str, Any]]]] = [
    # --- figures outside a product-class envelope: no envelope is loaded
    ("72 V supply", CLEAN, [one(E, "supply_voltage", 72, "V")]),
    ("400 V traction bus", CLEAN, [one(E, "supply_voltage", 400, "V")]),
    ("63 V capacitor rating", CLEAN, [one(E, "rated_voltage", 63, "V")]),
    ("100 V breakdown_voltage", CLEAN, [one(E, "breakdown_voltage", 100, "V")]),
    ("77 V clamping_voltage", CLEAN, [one(E, "clamping_voltage", 77, "V")]),
    ("230 V mains_voltage, firmware", CLEAN, [one(F, "mains_voltage", 230, "V")]),
    ("max_temperature 150 degF", CLEAN, [one(E, "max_temperature", 150, "degF")]),
    ("ambient_temperature -40 degC", CLEAN, [one(E, "ambient_temperature", -40, "degC")]),
    ("ambient_temperature -40 degF", CLEAN, [one(E, "ambient_temperature", -40, "degF")]),
    ("ambient_temperature -100 degC", CLEAN, [one(E, "ambient_temperature", -100, "degC")]),
    ("hotend max_temperature 300 degC", CLEAN, [one(M, "max_temperature", 300, "degC")]),
    ("soldering_temperature 350 degC", CLEAN, [one(E, "soldering_temperature", 350, "degC")]),
    ("color_temperature 5000 K", CLEAN, [one(E, "color_temperature", 5000, "K")]),
    ("delta_temperature 40 K", CLEAN, [one(E, "delta_temperature", 40, "K")]),
    ("max_temperature 398 K", CLEAN, [one(E, "max_temperature", 398, "K")]),
    # --- names a suffix would misread
    ("max_supply_voltage_drop 0.5 V", CLEAN, [one(E, "max_supply_voltage_drop", 0.5, "V")]),
    ("wheel_diameter_tolerance 0.1 mm", CLEAN, [one(M, "wheel_diameter_tolerance", 0.1, "mm")]),
    ("pulse_width 1500 us", CLEAN, [one(F, "pulse_width", 1500, "us")]),
    ("pulse_length 1.5 ms", CLEAN, [one(C, "pulse_length", 1.5, "ms")]),
    ("servo_position 90 deg", CLEAN, [one(C, "servo_position", 90, "deg")]),
    ("encoder_position 1024", CLEAN, [one(C, "encoder_position", 1024, "dimensionless")]),
    ("throttle_position 50 percent", CLEAN, [one(C, "throttle_position", 50, "percent")]),
    ("word_length 16 bit", CLEAN, [one(F, "word_length", 16, "bit")]),
    ("bandwidth 100 Hz", CLEAN, [one(C, "bandwidth", 100, "Hz")]),
    ("line_height 1.2", CLEAN, [one(F, "line_height", 1.2, "dimensionless")]),
    ("eddy_current 0.5 W", CLEAN, [one(E, "eddy_current", 0.5, "W")]),
    ("counter_current 2 A", CLEAN, [one(E, "counter_current", 2, "A")]),
    ("spring_force 5 N", CLEAN, [one(M, "spring_force", 5, "N")]),
    ("braking_torque -2 N*m", CLEAN, [one(M, "braking_torque", -2, "N*m")]),
    ("boost_voltage 48 V", CLEAN, [one(E, "boost_voltage", 48, "V")]),
    # --- a torque unit read under every reading
    (
        "gearmotor, torque_peak the motor's, the mount reacts the output",
        CLEAN,
        [
            node(
                f"{M}.gearmotor",
                domain=M,
                quantities={
                    "torque_peak": (0.1, "N*m"),
                    "gear_ratio": (30, "dimensionless"),
                    "reaction_moment": (3, "N*m"),
                },
            )
        ],
    ),
    (
        "gearmotor, torque_peak the motor's, the housing reacts output less input",
        CLEAN,
        [
            node(
                f"{M}.gearmotor",
                domain=M,
                quantities={
                    "torque_peak": (0.1, "N*m"),
                    "gear_ratio": (30, "dimensionless"),
                    "reaction_moment": (2.9, "N*m"),
                },
            )
        ],
    ),
    ("cantilevered unit, reaction adds its weight's moment", LIMIT, [unit(2.49, mass=(0.5, "kg"))]),
    ("reaction written as the mount's rated capacity", LIMIT, [unit(5)]),
    ("two motors on one node, reaction their sum", LIMIT, [unit(4)]),
    (
        "reaction moment in newtons",
        WRONG_UNIT,
        [
            node(
                f"{M}.motor",
                domain=M,
                quantities={"torque_peak": (2, "N*m"), "reaction_moment": (2, "N")},
            )
        ],
    ),
    ("torque unit balanced", CLEAN, [unit(2)]),
    # --- a carrier whose constrains edges are not all "is carried by"
    (
        "chassis carries the electronics; a wheel names it for clearance",
        CLEAN,
        [
            node(
                f"{M}.chassis",
                domain=M,
                quantities={"supported_mass": (1.0, "kg"), "mass": (0.8, "kg")},
            ),
            node(f"{E}.electronics", quantities={"mass": (1.0, "kg")}, constrains=[f"{M}.chassis"]),
            node(
                f"{M}.wheel",
                domain=M,
                quantities={"mass": (0.3, "kg")},
                constrains=[f"{M}.chassis"],
            ),
        ],
    ),
    (
        "supported mass written as the bracket's rated capacity",
        LIMIT,
        [
            node(
                f"{M}.bracket",
                domain=M,
                quantities={"supported_mass": (5, "kg"), "mass": (0.1, "kg")},
            ),
            node(f"{E}.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.bracket"]),
        ],
    ),
    (
        "a pack names the motor it powers; the motor carries a wheel",
        CLEAN,
        [
            node(f"{E}.motor", quantities={"supported_mass": (0.2, "kg"), "mass": (0.3, "kg")}),
            node(f"{E}.pack", quantities={"mass": (2, "kg")}, constrains=[f"{E}.motor"]),
            node(
                f"{M}.wheel", domain=M, quantities={"mass": (0.2, "kg")}, constrains=[f"{E}.motor"]
            ),
        ],
    ),
    (
        "supported mass in newtons",
        WRONG_UNIT,
        [
            node(f"{M}.bracket", domain=M, quantities={"supported_mass": (2, "N")}),
            node(f"{E}.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.bracket"]),
        ],
    ),
    (
        "carrier of zero own mass, supported mass the whole",
        CLEAN,
        [
            node(
                f"{M}.bracket",
                domain=M,
                quantities={"supported_mass": (2, "kg"), "mass": (0, "kg")},
            ),
            node(f"{E}.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.bracket"]),
        ],
    ),
    (
        "a pack on two brackets, split 1.5 and 0.5",
        CLEAN,
        [
            node(f"{M}.b1", domain=M, quantities={"supported_mass": (1.5, "kg")}),
            node(f"{M}.b2", domain=M, quantities={"supported_mass": (0.5, "kg")}),
            node(f"{E}.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.b1", f"{M}.b2"]),
        ],
    ),
]


@pytest.mark.parametrize(("label", "expected", "payloads"), PROBES, ids=[p[0] for p in PROBES])
def test_each_probe_ends_as_the_rulings_say(
    tmp_path: Path, label: str, expected: str, payloads: list[dict[str, Any]]
) -> None:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds())
    failing = {
        name: [o for o in mod.run(ctx).observations if o.outcome == "fail"]
        for name, mod in (
            ("units", check_units),
            ("magnitude", check_magnitude),
            ("equilibrium", check_equilibrium),
        )
    }
    verdict = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["system"], "on").verdict
    if expected == CLEAN:
        assert all(found == [] for found in failing.values()), (label, failing)
        assert verdict == "pass"
    elif expected == LIMIT:
        assert failing["units"] == [] and failing["magnitude"] == []
        assert len(failing["equilibrium"]) == 1 and verdict == "fail"
    else:
        assert len(failing["units"]) == 1 and failing["equilibrium"] == [] and verdict == "fail"


def test_the_probes_cover_the_three_rules_and_the_review_s_count() -> None:
    assert len(PROBES) == 43
    assert sum(1 for _, e, _ in PROBES if e == LIMIT) == 4
    assert sum(1 for _, e, _ in PROBES if e == WRONG_UNIT) == 2
