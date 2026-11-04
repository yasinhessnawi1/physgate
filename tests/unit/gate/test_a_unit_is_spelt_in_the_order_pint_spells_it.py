"""M-198 check, C1: a unit of several factors is spelt in the order pint itself spells it.

pint 0.26.1 spells a unit (``pint.Unit``) with its factors sorted by name, ``meter * newton`` for
``N*m``, and the container of a unit's factors (``UnitsContainer``, what a ``DimensionalityError``
carries) in the order the factors were written, ``newton * meter``. At a64e805f the unit check
printed a pint unit at its two relation-mismatch sites and pint's error's containers in its
refusal, so a relation whose term is in ``N*m`` read ``compares 'kilogram' with 'meter * newton':
pint cannot convert 'kilogram' ([mass]) to 'newton * meter' (...)``. M-200's ``unit_text`` kept the
written order for both, so the first quote changed to ``'newton * meter'``: a refusal's words
moved where pint could print them. They are a64e805f's again: a unit in pint's sorted order, a
container in its written order.

pint's own text is the measure: a registry that computes in floats can print every unit, so each
spelling is compared with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pint
import pytest
from gate_fixtures import graph, node

from physgate.gate.catalogue import KINDS
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.gate.units import UREG, measure, unit_text
from physgate.orchestrator.protocols import Scope

M = "mechanical"
#: A registry that computes in floats: pint can print every unit there, so its text is the measure.
PLAIN = pint.UnitRegistry()


def _gate(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    try:
        return PhysicsGate().run(GraphView.read(tmp_path / "g", 0), [scope], "on")
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the gate raised: {type(exc).__name__}: {exc}")


def _refusals(result: Any) -> list[str]:
    return [c.message for c in result.checks if c.name == "units" and c.outcome == "fail"]


@pytest.mark.parametrize(
    "unit",
    [
        # written in an order other than pint's
        "N*m",
        "N*m/A",
        "V*A",
        "s*A",
        "W/m/K",
        "V*s/rad",
        "mA*h",
        # with a power other than one
        "N*m**2",
        "s**2*A/kg",
        # already in pint's order
        "kg*m",
        "kg*m**2",
        "rad/s**2",
        "1/s",
        "m",
    ],
)
def test_a_unit_is_spelt_as_pint_spells_it(unit: str) -> None:
    assert unit_text(UREG.Unit(unit)) == str(PLAIN.Unit(unit))


@pytest.mark.parametrize(
    ("unit", "written"),
    [("N*m", "newton * meter"), ("s*A", "second * ampere"), ("W/m/K", "watt / meter / kelvin")],
)
def test_the_factors_pint_s_error_carries_keep_the_order_they_were_written_in(
    unit: str, written: str
) -> None:
    # Guard: a DimensionalityError carries a container, which pint prints as written.
    with pytest.raises(pint.DimensionalityError) as caught:
        measure(KINDS["mass"], 1, unit)
    assert str(caught.value.units1) == written
    assert unit_text(caught.value.units1) == written


@pytest.mark.parametrize(("unit", "spelt"), [("N*m", "meter * newton"), ("s*A", "ampere * second")])
def test_a_relation_with_a_term_in_a_unit_of_two_factors_is_worded_as_at_a64e805f(
    tmp_path: Path, unit: str, spelt: str
) -> None:
    result = _gate(
        tmp_path,
        "subtask",
        node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")}),
        node(f"{M}.pack", domain=M, quantities={"mass": (6, unit)}, constrains=[f"{M}.robot"]),
    )
    written = {"N*m": "newton * meter", "s*A": "second * ampere"}[unit]
    dims = {"N*m": "[mass] * [length]**2 * [time]**-2", "s*A": "[time] * [current]"}[unit]
    assert _refusals(result) == [
        f"mass(mechanical.robot) == mass(mechanical.pack) compares 'kilogram' with '{spelt}': "
        f"pint cannot convert 'kilogram' ([mass]) to '{written}' ({dims}). The relation cannot be "
        "evaluated, so nothing that depends on it can be trusted"
    ]


def test_a_sum_with_a_member_in_a_unit_of_two_factors_is_worded_as_at_a64e805f(
    tmp_path: Path,
) -> None:
    result = _gate(
        tmp_path,
        "system",
        node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")}),
        node(f"{M}.pack", domain=M, quantities={"mass": (2, "kg")}, constrains=[f"{M}.robot"]),
        node(f"{M}.arm", domain=M, quantities={"mass": (3, "N*m")}, constrains=[f"{M}.robot"]),
    )
    assert (
        "mass(mechanical.robot) == mass(mechanical.arm) + mass(mechanical.pack) compares "
        "'meter * newton' with 'kilogram': pint cannot convert 'newton * meter' ([mass] * "
        "[length]**2 * [time]**-2) to 'kilogram' ([mass]). The relation cannot be evaluated, so "
        "nothing that depends on it can be trusted"
    ) in _refusals(result)
