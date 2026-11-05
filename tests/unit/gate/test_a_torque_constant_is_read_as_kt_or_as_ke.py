"""A motor's torque constant is read in N*m/A or in V*s/rad, both correct in SI.

A motor's torque constant Kt, the torque per ampere, and its back-EMF constant Ke, the voltage per
unit of angular speed, are one number in SI: a data sheet gives either, Kt in N*m/A or Ke in
V*s/rad. pint takes the radian as one, so 0.05 V*s/rad converts to 0.05 N*m/A exactly, with no
factor lost. At 470b3f34 the catalogued ``torque_constant`` took the radian to the power 0 only,
so a correct Ke was refused ("a torque constant is written with the radian to the power 0, and
'V*s/rad' has it to the power -1"). It is now read at the power 0 or -1, as a ``_frequency`` is
read at 0 or 1; its dimension is still read, so a torque or a radian too many is still refused.
The value read is never anything but the name's own: no relation and no range takes it
(test_a_name_read_at_either_radian_power_reaches_no_relation_or_range).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate.catalogue import KINDS
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.gate.units import measure

NODE = "electrical.motor"


def _gate(tmp_path: Path, name: str, value: float, unit: str) -> Any:
    graph(tmp_path / "g", node(NODE, quantities={name: (value, unit)}))
    try:
        return PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the gate raised on {name} = {value} {unit}: {type(exc).__name__}: {exc}")


def _units(result: Any) -> list[Any]:
    return [c for c in result.checks if c.name == "units"]


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        (0.05, "V*s/rad"),  # Ke, as a data sheet gives it
        (0.053755, "N*m/A"),  # Kt
        (53.755, "mN*m/A"),
        (0.05, "V*s"),  # Ke with the radian left out
        (-0.05, "V*s/rad"),  # signed by convention: its unit is read, not its sign
    ],
)
def test_a_torque_constant_in_n_m_per_a_or_in_v_s_per_rad_passes(
    tmp_path: Path, value: float, unit: str
) -> None:
    result = _gate(tmp_path, "torque_constant", value, unit)
    assert [c.message for c in result.checks if c.outcome == "fail"] == []
    assert result.verdict == "pass"
    assert not any("does not know" in c.message for c in _units(result))


@pytest.mark.parametrize(("unit", "power"), [("V*s/rad**2", -2), ("V*s*rad", 1), ("N*m*rad/A", 1)])
def test_a_torque_constant_with_another_power_of_the_radian_is_refused(
    tmp_path: Path, unit: str, power: int
) -> None:
    result = _gate(tmp_path, "torque_constant", 0.05, unit)
    assert result.verdict == "fail"
    (refusal,) = [c.message for c in _units(result) if c.outcome == "fail"]
    assert (
        f"a torque constant is written with the radian to the power 0 or -1, and {unit!r} has it "
        f"to the power {power}"
    ) in refusal


@pytest.mark.parametrize("unit", ["N*m", "V/rad", "A/N/m"])
def test_a_torque_constant_in_another_dimension_is_still_refused(tmp_path: Path, unit: str) -> None:
    # Guard: the radian's powers widen, the dimension does not.
    result = _gate(tmp_path, "torque_constant", 0.05, unit)
    assert result.verdict == "fail"
    refusals = [c.message for c in _units(result) if c.outcome == "fail"]
    assert len(refusals) == 1
    assert "pint cannot convert" in refusals[0], refusals


def test_a_qualified_torque_constant_in_v_s_per_rad_is_read_without_a_mismatch(
    tmp_path: Path,
) -> None:
    result = _gate(tmp_path, "torque_constant_max", 0.05, "V*s/rad")
    assert result.verdict == "pass"
    assert not any("refuses nothing" in c.message for c in _units(result)), [
        c.message for c in _units(result)
    ]


def test_ke_converts_to_kt_with_no_factor_lost() -> None:
    # Guard: unlike a frequency in rad/s read as hertz, no 2 pi is missing: in SI the two
    # constants are one number.
    read = measure(KINDS["torque_constant"], 0.05, "V*s/rad", angles=(0, -1))
    assert read.magnitude == Fraction(1, 20)
    assert read.magnitude == measure(KINDS["torque_constant"], 0.05, "N*m/A").magnitude
