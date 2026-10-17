"""The gate holds a role-written unit to a bounded spelling before its unit registry sees it.

The registry evaluates any arithmetic in a unit exactly, in fractions: the twelve
characters ``10**10**10*m`` kept one process busy until a CPU limit killed it, and the gate
runs inside the orchestrator's own process with no time bound. A length bound does not
bound that work. So the unit check (check 1) and the magnitude check (check 2) parse a unit
only after it matches the shared spelling guard, ``physgate.unit_spelling``: named units
with small integer powers. A unit that does not is refused with the reason, and the
registry is never asked.

The registry is stubbed here once the bounds are loaded, so a refusal that came too late
fails the test instead of stalling it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude, check_units, units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.units import UnitRefusedError, parse

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"
#: Units whose parse has no bound on its cost, or that the spelling does not admit.
UNBOUNDED = ["10**10**10*m", "m**(10**9)", "1e308*A", "km⁹⁹⁹⁹⁹⁹⁹⁹", "A*2", "(A)"]


class _Untouchable:
    """A stand-in registry that records every unit it is asked to read, and reads none."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def Quantity(self, value: Any, unit: str) -> Any:  # noqa: ANN401, N802 - pint's own name
        self.asked.append(unit)
        msg = "the registry was asked to read a unit the spelling refuses"
        raise AssertionError(msg)


def _stubbed(monkeypatch: pytest.MonkeyPatch) -> _Untouchable:
    """The registry replaced, once everything a test builds with the real one is built."""
    stub = _Untouchable()
    monkeypatch.setattr(units, "UREG", stub)
    return stub


@pytest.mark.parametrize("unit", UNBOUNDED)
def test_a_unit_outside_the_spelling_is_refused_before_the_registry_reads_it(
    monkeypatch: pytest.MonkeyPatch, unit: str
) -> None:
    registry = _stubbed(monkeypatch)
    with pytest.raises(UnitRefusedError, match="named units with small integer powers"):
        parse(1, unit)
    assert registry.asked == []


def _context(tmp_path: Path, *payloads: dict[str, Any]) -> CheckContext:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return CheckContext(view=view, scope="subtask", bounds=load_bounds(KNOWLEDGE_DIR))


@pytest.mark.parametrize("unit", UNBOUNDED)
def test_check_1_records_the_refusal_and_never_asks_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unit: str
) -> None:
    ctx = _context(tmp_path, node("electrical.imu", quantities={"sample_rate": (50, unit)}))
    registry = _stubbed(monkeypatch)
    ran = check_units.run(ctx)
    failing = [o for o in ran.observations if o.outcome == "fail"]
    assert failing and all("named units with small integer powers" in o.message for o in failing)
    assert registry.asked == []


@pytest.mark.parametrize("unit", UNBOUNDED)
def test_check_2_leaves_the_quantity_to_check_1_and_never_asks_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unit: str
) -> None:
    motor = node("electrical.motor_left", quantities={"stall_current": (2.4, unit)})
    ctx = _context(tmp_path, motor)
    registry = _stubbed(monkeypatch)
    ran = check_magnitude.run(ctx)
    assert [o.outcome for o in ran.observations] == ["unchecked"]
    assert "unit check refuses" in ran.observations[0].message
    assert registry.asked == []
