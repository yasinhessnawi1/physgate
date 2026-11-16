"""The law library's names, held to every value a real plan wrote under them, and to its spellings.

A new exact name is refused when a value under it is not its kind's, so a name that a real plan
already writes must take every value that plan wrote: otherwise the row fails a correct design
the day it lands. The real plans are the practice set and G11 runs 2 and 4, through their
committed fixtures. Fifteen distinct values sit under seven of the new names (run 4's rated stall
currents, overall gear ratio and wheel no-load speed; the practice set's encoder counts, no-load
current and pack charge); the other five names reach no real plan yet.

Each new name the laws will read also joins the names the hooks guard, so a misspelling of it is
refused at write time. That must not refuse a name a real plan wrote (the 245 names the relation
guard's own test reads), nor a near spelling that says another thing in other words. One refusal
is accepted, and pinned: ``stalled_voltage`` means what ``stall_voltage`` means, so refusing it
redirects a writer to the catalogued spelling.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from law_library_names import (
    NAMES,
    NEAR_SPELLINGS_WRITTEN,
    REAL_VALUES,
    REFUSED_AS_MISSPELLINGS,
)

from physgate.gate.catalogue import QUANTITIES, angles_of, kind_of, shadowing_names
from physgate.gate.units import measure
from physgate.state.vocabulary import shadowing_quantity_names

HERE = Path(__file__).parent
PRACTICE = HERE.parents[2] / "experiments" / "R-PG-02" / "practice" / "corpus-v1"


def _quantities(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        quantities = value.get("quantities")
        if isinstance(quantities, dict):
            yield from quantities.items()
        for inner in value.values():
            yield from _quantities(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _quantities(inner)


def _practice() -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    for path in [PRACTICE / "base.json", *sorted((PRACTICE / "artefacts").glob("*.json"))]:
        found.extend(_quantities(json.loads(path.read_text())))
    return found


def real_values() -> set[tuple[str, float | int, str]]:
    """Every distinct value the practice set and run 4 wrote, as (name, value, unit)."""
    rows = {
        (name, q["value"], q["unit"])
        for name, q in _practice()
        if isinstance(q, dict) and "value" in q and "unit" in q
    }
    run4 = json.loads((HERE / "run4" / "values.json").read_text())
    rows |= {(r["name"], r["value"], r["unit"]) for r in run4}
    return rows


def real_names() -> set[str]:
    """Every quantity name the practice set and G11 runs 2 and 4 wrote."""
    names = {name for name, _ in _practice()}
    names |= {r["name"] for r in json.loads((HERE / "run4" / "values.json").read_text())}
    names |= set(json.loads((HERE / "run2" / "names.json").read_text()))
    return names


def test_the_pinned_values_are_every_real_value_under_a_new_name() -> None:
    # Guard: the values below are read off the fixtures, not typed from memory.
    assert len(real_names()) == 245
    assert {row for row in real_values() if row[0] in NAMES} == set(REAL_VALUES)


@pytest.mark.parametrize(("name", "value", "unit"), REAL_VALUES)
def test_every_real_value_under_a_new_name_passes_its_kind(
    name: str, value: float, unit: str
) -> None:
    assert name in QUANTITIES, f"{name} is not catalogued"
    kind = kind_of(name)
    assert kind is not None and kind.name == NAMES[name]
    measured = measure(kind, value, unit, angles=angles_of(name))
    assert measured.kind is kind


def test_the_real_names_that_become_exact_are_the_seven_with_values() -> None:
    exact = sorted(name for name in real_names() & set(NAMES) if name in QUANTITIES)
    assert exact == sorted({row[0] for row in REAL_VALUES})


def test_no_name_a_real_plan_wrote_is_refused_as_a_misspelling_of_a_new_name() -> None:
    names = sorted(real_names())
    assert shadowing_names(names) == ()
    assert shadowing_quantity_names(names) == ()


def test_a_near_spelling_in_other_words_is_written() -> None:
    assert shadowing_names(NEAR_SPELLINGS_WRITTEN) == ()
    assert shadowing_quantity_names(list(NEAR_SPELLINGS_WRITTEN)) == ()


def test_the_accepted_refusals_redirect_to_the_catalogued_spelling() -> None:
    names = [name for name, _ in REFUSED_AS_MISSPELLINGS]
    assert shadowing_names(names) == tuple(sorted(REFUSED_AS_MISSPELLINGS))
    assert shadowing_quantity_names(names) == tuple(sorted(REFUSED_AS_MISSPELLINGS))
