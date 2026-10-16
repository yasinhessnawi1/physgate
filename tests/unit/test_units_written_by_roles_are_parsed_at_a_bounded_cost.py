"""A unit is held to a spelling whose parse has a bounded cost, before any registry sees it.

The guard is shared: the simulation-record format uses it now, and the physics gate's own
unit parser is meant to. So besides what it refuses, this file holds what the gate needs
to know before it adopts it: every unit the gate's catalogue and bounds tables name today
is admitted, and the module imports nothing the gate's import fence would have to weigh.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any

import pytest

import physgate.unit_spelling as spelling
from physgate.gate.catalogue import KINDS
from physgate.unit_spelling import MAX_LENGTH, UnitSpellingError, require_bounded_spelling

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "unit",
    [
        "10**10**10*m",
        "m**(10**9)",
        "1e308*m",
        "1000*m",
        "m*2",
        "2",
        "(m)",
        "m**999",
        "m**1.5",
        "m\n",
        "m\t*s",
        "",
        "m*",
        "*m",
        "m//s",
    ],
)
def test_a_unit_whose_parse_could_cost_without_bound_is_refused(unit: str) -> None:
    with pytest.raises(UnitSpellingError, match="named units with small integer powers"):
        require_bounded_spelling(unit)


def test_a_unit_longer_than_the_gate_s_bound_is_refused() -> None:
    longest = "m*" * ((MAX_LENGTH - 1) // 2) + "m"
    assert len(longest) <= MAX_LENGTH
    assert require_bounded_spelling(longest) == longest
    with pytest.raises(UnitSpellingError):
        require_bounded_spelling(longest + "*m")


@pytest.mark.parametrize(
    "unit",
    ["s", "1", "1/s", "rad/s", "kg*m/s**2", "m**-1", "kg^2", "V / A", "µm", "Ω", "delta_degC"],
)
def test_the_units_simulations_write_are_admitted(unit: str) -> None:
    assert require_bounded_spelling(unit) == unit


def _bounds_units() -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "unit" and isinstance(value, str):
                    found.add(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for table in sorted((REPOSITORY / "knowledge").glob("*/bounds.toml")):
        walk(tomllib.loads(table.read_text()))
    return found


def test_every_unit_the_gate_names_today_is_admitted() -> None:
    canonical = {kind.canonical for kind in KINDS.values()}
    tables = _bounds_units()
    assert canonical, "the catalogue named no unit"
    assert tables, "the bounds tables named no unit"
    for unit in sorted(canonical | tables):
        require_bounded_spelling(unit)


def test_the_guard_imports_nothing_but_the_standard_library_s_re() -> None:
    tree = ast.parse(Path(spelling.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"__future__", "re"}


@pytest.mark.parametrize("unit", ["m²", "km⁹⁹⁹⁹⁹⁹⁹⁹", "m½", "Ⅹ", "ｍ", "m٣", "s⁻¹"])
def test_a_character_the_registry_could_read_as_a_number_is_refused(unit: str) -> None:
    # The registry reads superscript digits as an exponent: "km⁹⁹⁹⁹⁹⁹⁹⁹" parses as the
    # kilometre to the 99,999,999th power, and converting it ran until a CPU limit killed
    # it. A guard that took every letter in Unicode admitted them as letters.
    with pytest.raises(UnitSpellingError):
        require_bounded_spelling(unit)


def test_a_name_holds_only_ascii_letters_the_underscore_and_three_unit_letters() -> None:
    admitted = {
        chr(code)
        for code in range(0x110000)
        if not 0xD800 <= code <= 0xDFFF and spelling.UNIT_SPELLING.fullmatch("m" + chr(code))
    }
    letters = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
    assert admitted == letters | {"µ", "μ", "Ω"}
