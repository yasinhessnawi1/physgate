"""Each new kind holds a value to its unit and its definitional sign, through the gate.

A catalogued name is refused when its unit or sign is not its kind's; a suffix or qualified name
is recorded, never refused. Either way the gate returns a result: a unit with a squared factor
(an area in m**2, a moment of inertia in kg*m**2) that does not convert must give a record, not
an exception. At a64e805f, ``pint_message`` cannot print pint's refusal when either unit has a
power other than one (``Invalid format specifier 'n' for object of type 'Fraction'``), so the
whole gate raises on ``mass`` written in m**2; the two new squared kinds make that reachable by
``drag_area`` in metres or ``body_inertia`` in kg*m. A crash is turned into a test failure here,
never left as an error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate

NODE = "control.plant"


def _gate(tmp_path: Path, name: str, value: float, unit: str) -> Any:
    graph(tmp_path / "g", node(NODE, domain="control", quantities={name: (value, unit)}))
    try:
        return PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the gate raised on {name} = {value} {unit}: {type(exc).__name__}: {exc}")


def _units(result: Any) -> list[Any]:
    return [c for c in result.checks if c.name == "units"]


@pytest.mark.parametrize(
    ("name", "value", "unit", "said", "why"),
    [
        # a wrong dimension under a suffix's new kind: pint's refusal, to the kind's unit
        (
            "drag_area",
            0.013216,
            "m",
            "_area",
            "pint cannot convert 'meter' ([length]) to 'meter ** 2'",
        ),
        (
            "body_inertia",
            0.000605802,
            "kg*m",
            "_inertia",
            "pint cannot convert 'kilogram * meter' ([mass] * [length]) to 'kilogram * meter ** 2'",
        ),
        (
            "sample_period",
            0.01,
            "Hz",
            "_period",
            "pint cannot convert 'hertz' ([time]**-1) to 'second'",
        ),
        (
            "max_ground_speed",
            1.11473,
            "rad/s",
            "_ground_speed",
            "pint cannot convert 'radian / second' ([time]**-1) to 'meter / second'",
        ),
        (
            "proposed_sensitivity_peak",
            2.0,
            "s",
            "_sensitivity_peak",
            "pint cannot convert 'second' ([time]) to 'dimensionless'",
        ),
        (
            "gyro_delay",
            0.00481,
            "m",
            "_delay",
            "pint cannot convert 'meter' ([length]) to 'second'",
        ),
        # a sign the definition rules out
        ("drag_area", -0.013216, "m**2", "_area", "an area is never negative"),
        ("body_inertia", -0.0006, "kg*m**2", "_inertia", "a moment of inertia is never negative"),
        ("sample_period", -0.01, "s", "_period", "a duration is never negative"),
        (
            "angle_decay_one_count_spectral_radius",
            -1.0,
            "1",
            "_spectral_radius",
            "a modulus is never negative",
        ),
        ("motor_off_latency_max", -0.06, "s", "_latency + _max", "a duration is never negative"),
    ],
)
def test_a_new_kind_s_mismatch_under_a_read_name_is_recorded_and_refuses_nothing(
    tmp_path: Path, name: str, value: float, unit: str, said: str, why: str
) -> None:
    result = _gate(tmp_path, name, value, unit)
    assert result.verdict == "pass"
    records = [c for c in _units(result) if c.outcome == "unchecked" and name in c.message]
    # The record names the reading and gives the reason: the kind's dimension, or its sign.
    assert any(
        "refuses nothing" in c.message and said in c.message and why in c.message for c in records
    ), [c.message for c in records]


@pytest.mark.parametrize(
    ("name", "value", "unit", "why"),
    [
        ("motor_resistance", 3.75, "V", "pint cannot convert 'volt'"),
        ("motor_resistance", -3.75, "V/A", "a resistance is never negative"),
        ("torque_constant", 0.053755, "N*m", "pint cannot convert 'newton * meter'"),
        ("update_rate", 100, "s", "pint cannot convert 'second' ([time]) to 'hertz'"),
        (
            "update_rate",
            100,
            "rad/s",
            "the radian to the power 0, and 'rad/s' has it to the power 1",
        ),
        ("sensitivity_peak", 2.4, "rad/s", "pint cannot convert 'radian / second' ([time]**-1)"),
        (
            "sensitivity_peak",
            2.4,
            "rad",
            "the radian to the power 0, and 'rad' has it to the power 1",
        ),
        ("sensitivity_peak", 2.4, "m", "pint cannot convert 'meter' ([length]) to 'dimensionless'"),
        ("sensitivity_peak", -2.4, "1", "a modulus is never negative"),
        ("gain_margin", -0.5, "1", "a modulus is never negative"),
        (
            "bore_diameter",
            0.005,
            "m**2",
            "pint cannot convert 'meter ** 2' ([length]**2) to 'meter'",
        ),
        ("bore_diameter", -0.005, "m", "an extent is never negative"),
    ],
)
def test_a_new_exact_name_s_mismatch_is_refused(
    tmp_path: Path, name: str, value: float, unit: str, why: str
) -> None:
    result = _gate(tmp_path, name, value, unit)
    assert result.verdict == "fail"
    # Refused for its reason: the kind's dimension, its radian or its sign, not another.
    refusals = [c.message for c in _units(result) if c.outcome == "fail" and name in c.message]
    assert len(refusals) == 1 and why in refusals[0], refusals


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("motor_resistance", 3.75, "V/A"),
        ("motor_resistance", 4.0, "ohm"),
        ("torque_constant", 0.053755, "N*m/A"),
        ("torque_constant", -0.053755, "N*m/A"),
        ("update_rate", 100.0000129, "Hz"),
        ("sensitivity_peak", 2.40588, "1"),
        ("gain_margin", 0.51, "1"),
        ("bore_diameter", 5, "mm"),
    ],
)
def test_a_new_exact_name_s_correct_figure_passes(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    result = _gate(tmp_path, name, value, unit)
    assert result.verdict == "pass"
    assert not any(c.outcome == "fail" for c in result.checks)
    # Read under its kind, so the unit check does not call it unknown.
    assert not any("does not know" in c.message and name in c.message for c in _units(result))
