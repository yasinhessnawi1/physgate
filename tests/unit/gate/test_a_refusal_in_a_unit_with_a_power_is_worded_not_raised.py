"""A unit refusal on a unit with a power other than one is worded, never raised.

pint 0.26.1, computing in fractions, cannot print a unit whose power is not one: its formatter asks
the fraction for the format ``n``, which a fraction does not support. The unit check put pint's
refusal into words by printing the units pint names, so a quantity of a known kind written in a
unit such as ``m**2`` or ``rad/s**2`` that does not convert to its kind's unit raised
``ValueError`` from the gate instead of being refused: ``mass`` in ``m**2``, and a mass sum whose
member's mass is in ``m**2``. The two squared kinds the catalogue widening adds (an area, a moment
of inertia) make such a unit an ordinary slip.

The words are put together from pint's own fields, as the dimensions already were, in pint's own
spelling (``meter ** 2``, ``radian / second ** 2``). Where pint can print the unit (every power one
or minus one) the words are byte for byte what they were.
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
from physgate.gate.units import UREG, _dimensions, measure, pint_message, unit_text
from physgate.orchestrator.protocols import Scope

NODE = "control.plant"
M = "mechanical"


def _gate(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    try:
        return PhysicsGate().run(GraphView.read(tmp_path / "g", 0), [scope], "on")
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the gate raised: {type(exc).__name__}: {exc}")


def _refusals(result: Any) -> list[str]:
    return [c.message for c in result.checks if c.name == "units" and c.outcome == "fail"]


@pytest.mark.parametrize(
    ("name", "value", "unit", "words"),
    [
        (
            "mass",
            2,
            "m**2",
            "mass of control.plant is 2 m**2, and a mass cannot be: pint cannot convert "
            "'meter ** 2' ([length]**2) to 'kilogram' ([mass])",
        ),
        (
            "no_load_speed",
            5,
            "rad/s**2",
            "no_load_speed of control.plant is 5 rad/s**2, and an angular velocity cannot be: pint "
            "cannot convert 'radian / second ** 2' ([time]**-2) to 'radian / second' ([time]**-1)",
        ),
        (
            "supply_voltage",
            3,
            "kg*m**2",
            "supply_voltage of control.plant is 3 kg*m**2, and a voltage cannot be: pint cannot "
            "convert 'kilogram * meter ** 2' ([mass] * [length]**2) to 'volt' ([mass] * "
            "[length]**2 * [time]**-3 * [current]**-1)",
        ),
    ],
)
def test_a_known_kind_in_a_powered_unit_of_another_dimension_is_refused_in_pint_s_words(
    tmp_path: Path, name: str, value: float, unit: str, words: str
) -> None:
    result = _gate(
        tmp_path, "subtask", node(NODE, domain="control", quantities={name: (value, unit)})
    )
    assert result.verdict == "fail"
    assert _refusals(result) == [words]


@pytest.mark.parametrize("scope", ["subtask", "system"])
def test_a_relation_whose_term_is_in_a_powered_unit_is_refused_in_pint_s_words(
    tmp_path: Path, scope: Scope
) -> None:
    result = _gate(
        tmp_path,
        scope,
        node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")}),
        node(f"{M}.pack", domain=M, quantities={"mass": (6, "m**2")}, constrains=[f"{M}.robot"]),
    )
    assert result.verdict == "fail"
    assert (
        "mass(mechanical.robot) == mass(mechanical.pack) compares 'kilogram' with 'meter ** 2': "
        "pint cannot convert 'kilogram' ([mass]) to 'meter ** 2' ([length]**2). The relation "
        "cannot be evaluated, so nothing that depends on it can be trusted"
    ) in _refusals(result)


@pytest.mark.parametrize(
    ("name", "value", "unit", "words"),
    [
        (
            "mass",
            2,
            "m",
            "mass of control.plant is 2 m, and a mass cannot be: pint cannot convert 'meter' "
            "([length]) to 'kilogram' ([mass])",
        ),
        (
            "supply_voltage",
            2,
            "W/s",
            "supply_voltage of control.plant is 2 W/s, and a voltage cannot be: pint cannot "
            "convert 'watt / second' ([mass] * [length]**2 * [time]**-4) to 'volt' ([mass] * "
            "[length]**2 * [time]**-3 * [current]**-1)",
        ),
        (
            "no_load_speed",
            2,
            "rad*m/s",
            "no_load_speed of control.plant is 2 rad*m/s, and an angular velocity cannot be: pint "
            "cannot convert 'radian * meter / second' ([length] * [time]**-1) to 'radian / second' "
            "([time]**-1)",
        ),
    ],
)
def test_a_refusal_pint_could_print_is_worded_as_it_was(
    tmp_path: Path, name: str, value: float, unit: str, words: str
) -> None:
    # Guard: the words at a64e805f, where every power is one or minus one.
    result = _gate(
        tmp_path, "subtask", node(NODE, domain="control", quantities={name: (value, unit)})
    )
    assert _refusals(result) == [words]


def test_a_relation_refusal_pint_could_print_is_worded_as_it_was(tmp_path: Path) -> None:
    # Guard: the words at a64e805f.
    result = _gate(
        tmp_path,
        "subtask",
        node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")}),
        node(f"{M}.pack", domain=M, quantities={"mass": (6, "m")}, constrains=[f"{M}.robot"]),
    )
    assert _refusals(result) == [
        "mass(mechanical.robot) == mass(mechanical.pack) compares 'kilogram' with 'meter': pint "
        "cannot convert 'kilogram' ([mass]) to 'meter' ([length]). The relation cannot be "
        "evaluated, so nothing that depends on it can be trusted"
    ]


@pytest.mark.parametrize(
    ("kind", "unit"),
    [
        ("mass", "m"),
        ("mass", "1/s"),
        ("mass", "1/m/s"),
        ("voltage", "A*s/kg"),
        ("current", "kg*m/s"),
        ("torque", "V/A"),
        ("time", "dimensionless"),
        ("length", "s*A/kg/K"),
    ],
)
def test_where_pint_can_print_the_units_the_words_are_pint_s_own(kind: str, unit: str) -> None:
    # Guard: the units pint itself prints, whenever it can, are the ones the refusal names.
    with pytest.raises(pint.DimensionalityError) as caught:
        measure(KINDS[kind], 1, unit)
    exc = caught.value
    assert pint_message(exc) == (
        f"pint cannot convert '{exc.units1}' ({_dimensions(exc.dim1)}) to "
        f"'{exc.units2}' ({_dimensions(exc.dim2)})"
    )


@pytest.mark.parametrize(
    ("units", "text"),
    [
        (UREG.Unit("m**2"), "meter ** 2"),
        (UREG.Unit("1/s**2"), "1 / second ** 2"),
        # pint sorts a unit's factors by name
        (UREG.Unit("kg*m**2/s**3/A"), "kilogram * meter ** 2 / ampere / second ** 3"),
        (UREG.Unit("dimensionless"), "dimensionless"),
        ("dimensionless", "dimensionless"),
    ],
)
def test_a_unit_is_spelt_from_its_factors_and_a_named_one_is_its_name(
    units: Any, text: str
) -> None:
    # pint names a unit by a string in some of its errors; that string is the unit's text.
    try:
        spelt = unit_text(units)
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"unit_text raised on {units!r}: {type(exc).__name__}: {exc}")
    assert spelt == text


def test_a_sum_whose_terms_are_in_units_that_do_not_add_is_refused_in_pint_s_words(
    tmp_path: Path,
) -> None:
    # The relation's sum of members parts before its two sides are compared: one member in kg,
    # one in m**2.
    result = _gate(
        tmp_path,
        "system",
        node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")}),
        node(f"{M}.pack", domain=M, quantities={"mass": (2, "kg")}, constrains=[f"{M}.robot"]),
        node(f"{M}.arm", domain=M, quantities={"mass": (3, "m**2")}, constrains=[f"{M}.robot"]),
    )
    assert result.verdict == "fail"
    assert (
        "mass(mechanical.robot) == mass(mechanical.arm) + mass(mechanical.pack) compares "
        "'meter ** 2' with 'kilogram': pint cannot convert 'meter ** 2' ([length]**2) to "
        "'kilogram' ([mass]). The relation cannot be evaluated, so nothing that depends on it can "
        "be trusted"
    ) in _refusals(result)
