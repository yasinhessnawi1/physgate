"""M-201: the source check shows a number in a unit with a power, and never crashes on it.

The source check writes each number it reports as its value and its unit in pint's short
symbols (``7.5 V``). It printed the unit with pint's ``~`` format, which pint 0.26.1, computing
in fractions, cannot do for a power other than one: its formatter asks the fraction for the
format ``n``, which a fraction does not support (M-200, in the gate). So a corpus number in
``kg*m**2`` or ``m/s**2`` that its source does not support raised ``ValueError`` from the inject
command's source check instead of a fact. The unit is now spelt from its factors, in pint's
short symbols and order, so a fact reads as pint would have written it where pint can.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pint
import pytest
from instrument_corpus import BASE_NODES, MAGNITUDE_ARTEFACT, SOURCE_ROWS, node, write_corpus

from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.source_check import _shown, check_sources
from physgate.gate.units import parse

PACK = "electrical.battery"
ELSEWHERE = "https://www.pololu.com/product/0000"  # an address no row of the sheet has
#: A registry that computes in floats: pint can print every unit there, so its text is the measure.
PLAIN = pint.UnitRegistry()


def _shown_or_fail(value: float, unit: str) -> str:
    try:
        return _shown(parse(value, unit))
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the source check raised on {value} {unit}: {type(exc).__name__}: {exc}")


@pytest.mark.parametrize(
    ("value", "unit", "shown"),
    [
        (0.5, "kg*m**2", "0.5 kg * m ** 2"),
        (9.81, "m/s**2", "9.81 m / s ** 2"),
        (2, "rad/s**2", "2 rad / s ** 2"),
    ],
)
def test_a_number_in_a_unit_with_a_power_is_shown(value: float, unit: str, shown: str) -> None:
    assert _shown_or_fail(value, unit) == shown


@pytest.mark.parametrize(
    "unit", ["V", "kg*m", "N*m/A", "mA*h", "um", "degC", "1/s", "kg*m**2", "m/s**2"]
)
def test_a_unit_is_shown_as_pint_s_short_format_shows_it(unit: str) -> None:
    # Guard where pint can print the unit; pint's own short text everywhere.
    assert _shown_or_fail(1.5, unit) == f"1.5 {PLAIN.Unit(unit):~}"


def _corpus(tmp_path: Path, unit: str) -> Path:
    clean = node(PACK, quantities={"mass": (0.5, unit)})
    clean["quantities"]["mass"]["source"] = ELSEWHERE
    injected: dict[str, Any] = node(PACK, quantities={"mass": (70.0, unit)})
    injected["quantities"]["mass"]["source"] = ELSEWHERE
    artefact = {
        **MAGNITUDE_ARTEFACT,
        "clean": {"nodes": [clean]},
        "injected": {"nodes": [injected]},
    }
    return write_corpus(
        tmp_path / "c", artefacts=(artefact,), base_nodes=BASE_NODES, rows=dict(SOURCE_ROWS)
    )


def test_a_corpus_number_in_a_squared_unit_is_reported_not_raised(tmp_path: Path) -> None:
    corpus = load_corpus(_corpus(tmp_path, "kg*m**2"))
    try:
        found = check_sources(corpus)
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"check_sources raised: {type(exc).__name__}: {exc}")
    (finding,) = [f for f in found if f.node == PACK]
    assert finding.kind == "unresolved"
    assert finding.fact() == (
        f"revision m1: mass of {PACK} is 0.5 kg * m ** 2, and no row at its source gives a number "
        f"of that kind ({ELSEWHERE})"
    )
