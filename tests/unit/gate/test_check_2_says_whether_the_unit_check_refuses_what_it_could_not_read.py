"""M-198 check, C7: check 2 says the unit check refuses a value only where the unit check does.

Check 2 cannot compare a value with its kind's range or envelope when the value is not in a unit
or of a sign its kind has. For a catalogued name, or a unit that does not parse, the unit check
refuses that value, and check 2's record says so. For a name the gate only reads, by a suffix
or by qualifier words (``duty_cycle_max``, ``gearbox_efficiency``), the unit check records the
mismatch and refuses nothing; check 2's record said "the unit check refuses" there too, which
was untrue. It now says what the unit check does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView

NODE = "control.plant"
REFUSES = "are in a unit the unit check refuses, so no range could be applied"
RECORDS = (
    "are not in a unit or of a sign of the kind their name is read as, which the unit check "
    "records and does not refuse, so no range could be applied"
)


def _ran(tmp_path: Path, name: str, value: float, unit: str) -> tuple[Any, Any]:
    graph(tmp_path / "g", node(NODE, domain="control", quantities={name: (value, unit)}))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="subtask", bounds=load_bounds())
    return check_units.run(ctx), check_magnitude.run(ctx)


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("duty_cycle_max", 0.5, "A"),
        ("duty_cycle_max", -0.5, "1"),
        ("gearbox_efficiency", 0.9, "s"),
        ("gearbox_efficiency_implied", -0.5, "1"),
    ],
)
def test_a_read_name_check_1_only_records_is_not_said_to_be_refused(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    units, magnitude = _ran(tmp_path, name, value, unit)
    assert not any(o.outcome == "fail" for o in units.observations)
    (record,) = [o.message for o in magnitude.observations]
    assert "the unit check refuses" not in record
    assert record == f"{name} of {NODE} {RECORDS}"


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("duty_cycle", 0.5, "A"),
        ("efficiency", -0.5, "1"),
        # a unit that does not parse is refused by the unit check whatever the name
        ("duty_cycle_max", 0.5, "furlong_per_fortnightly"),
    ],
)
def test_a_value_check_1_refuses_is_said_to_be_refused_as_before(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    # Guard: the words at a64e805f.
    units, magnitude = _ran(tmp_path, name, value, unit)
    assert any(o.outcome == "fail" and name in o.message for o in units.observations)
    assert [o.message for o in magnitude.observations] == [f"{name} of {NODE} {REFUSES}"]
