"""A unit with a bracketed denominator is read as its product, and a refusal names the spelling.

In a full run, sizing wrote a controller gain in ``1/(rad*s)``. The registry reads that unit, but
the grammar refused it for its brackets, and its refusal named no spelling it would take. The
session wrote the same unit again until its repairs ran out.

So the grammar now takes a bracketed denominator of named units after a ``/``, the leading ``1``
included. It reads the bracket as the chain of divisions it means (``1/(rad*s)`` is ``1/rad/s``),
so the registry is handed a bracket-free product and two spellings of one unit compare equal. It
still refuses a number inside a unit, a nested bracket, a bracket anywhere but a denominator, and a
power that is not a small integer. Each refusal names the spelling the grammar takes for that unit,
where one exists. The gate's pint view and the grammar agree on every form the grammar takes. The
series writer runs alone in a role's interpreter and keeps its own copy of the grammar, so the copy
must be the same code.

Each row catches a refusal and compares it, so a row fails on an assertion before the build.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import pytest

import physgate.series.writer as writer
from physgate import unit_spelling
from physgate.gate import units
from physgate.gate.units import UREG, UnitRefusedError
from physgate.series.exceptions import RecordRefusedError
from physgate.series.record import parse_record
from physgate.unit_spelling import MAX_LENGTH, UnitSpellingError, require_bounded_spelling

sys.path.insert(0, str(Path(__file__).resolve().parent / "series"))
from series_fixture import encode, record_dict  # noqa: E402

#: Units the grammar takes with a bracket, each with the bracket-free product it is read as.
BRACKETED = [
    ("1/(rad*s)", "1/rad/s"),
    ("V/(m*s)", "V/m/s"),
    ("kg/(m**2*s)", "kg/m**2/s"),
    ("m^2/(s^2*kg)", "m^2/s^2/kg"),
    ("1/( rad * s )", "1/rad/s"),
    ("V / (m*s)", "V/m/s"),
    ("N*m/(rad*s**-1)", "N*m/rad/s**-1"),
    ("A/(V)", "A/V"),
    ("1/(rad*s)*kg", "1/rad/s*kg"),
    ("rad/(s)/(m*kg)", "rad/s/m/kg"),
]
#: Units without a bracket, which the grammar takes as they are written.
PLAIN = [
    "s", "1", "1/s", "rad/s", "1/rad/s", "rad**-1*s**-1", "kg*m/s**2", "m**-1", "kg^2",
    "V / A", "µm", "Ω", "delta_degC", "Hz/rad",
]  # fmt: skip
#: Units the grammar refuses, each with the spelling it names for them.
REFUSED_WITH_A_SPELLING = [
    ("1/(rad*(s))", "1/rad/s"),
    ("((m))", "m"),
    ("(m)", "m"),
    ("(m*s)/kg", "m*s/kg"),
    ("1/(m/s)", "s/m"),
    ("(rad*s)**-1", "1/rad/s"),
]
#: Twenty named units in a bracket, squared: its product is longer than the grammar's bound.
_SQUARED = "(" + "*".join(a + b for a in "pq" for b in "abcdefghij") + ")**2"
#: Units the grammar refuses that no spelling of its own, within its bounds, reads as the same.
REFUSED_WITHOUT_A_SPELLING = [
    "10**10**10*m", "m**(10**9)", "1e308*m", "1000*m", "m*2", "2", "m**999", "m**1.5",
    "1/(2*s)", "1/(m**0.5*s)", "1/(s**100)", "m²", "km⁹⁹⁹⁹⁹⁹⁹⁹", "m//s", "m*", "1/()",
    "V/(m*s", "V/(m*s))", "m s", "(m**50)**2", _SQUARED,
]  # fmt: skip


def _spelt(unit: str) -> str:
    """What the grammar makes of ``unit``: the spelling it takes, or its refusal's words."""
    try:
        return require_bounded_spelling(unit)
    except UnitSpellingError as exc:
        return f"refused: {exc}"


def _pint(unit: str) -> dict[str, Any]:
    """The registry's own reading of ``unit``: each unit it names, with its power."""
    return dict(UREG.Quantity(1, unit).unit_items())


def _gate(unit: str) -> dict[str, Any] | str:
    """The units the gate's parser reads ``unit`` as, with their powers, or its refusal's words."""
    try:
        return dict(units.parse(1, unit).unit_items())
    except UnitRefusedError as exc:
        return f"refused: {exc}"


def _writer(unit: str) -> str:
    """What the series writer makes of ``unit`` on an axis: the unit, or its refusal's words."""
    try:
        return str(writer._unit(unit, "the axis time"))  # noqa: SLF001 - the writer's own check
    except writer.SeriesWriterError as exc:
        return f"refused: {exc}"


@pytest.mark.parametrize(("unit", "product"), BRACKETED)
def test_a_bracketed_denominator_is_taken_and_read_as_its_product(unit: str, product: str) -> None:
    assert _spelt(unit) == product
    assert _spelt(product) == product


@pytest.mark.parametrize("unit", PLAIN)
def test_a_unit_without_a_bracket_is_taken_as_it_is_written(unit: str) -> None:
    assert _spelt(unit) == unit


@pytest.mark.parametrize(("unit", "product"), BRACKETED + [(unit, unit) for unit in PLAIN])
def test_the_gate_s_pint_view_and_the_grammar_agree_on_every_form_it_takes(
    unit: str, product: str
) -> None:
    # Three readings of one unit: the gate's parser, pint's own reading of the unit as written,
    # and pint's reading of the spelling the grammar makes of it.
    assert _gate(unit) == _pint(unit) == _pint(product)
    assert _gate(unit) == _gate(product)


def test_the_registry_is_handed_the_product_and_never_a_bracket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    real = UREG.Quantity

    def recording(value: Any, unit: str) -> Any:  # noqa: ANN401 - pint's own signature
        asked.append(unit)
        return real(value, unit)

    monkeypatch.setattr(units.UREG, "Quantity", recording)
    for unit, _ in BRACKETED:
        _gate(unit)
    assert asked == [product for _, product in BRACKETED]


@pytest.mark.parametrize(("unit", "spelling"), REFUSED_WITH_A_SPELLING)
def test_a_refusal_names_the_spelling_the_grammar_takes_for_that_unit(
    unit: str, spelling: str
) -> None:
    said = _spelt(unit)
    assert said.startswith("refused: ") and "named units with small integer powers" in said
    assert said.endswith(f"; write it as {spelling}")
    # The spelling named is one the grammar takes, and the unit pint reads in the refused form.
    assert _spelt(spelling) == spelling
    assert _pint(unit) == _pint(spelling)


@pytest.mark.parametrize("unit", REFUSED_WITHOUT_A_SPELLING)
def test_a_number_a_nested_power_or_a_fractional_power_is_refused_with_no_spelling(
    unit: str,
) -> None:
    said = _spelt(unit)
    assert said.startswith("refused: ") and "named units with small integer powers" in said
    assert "write it as" not in said


def test_a_unit_over_the_length_bound_is_refused_naming_a_spelling_within_it() -> None:
    long = "1/(" + "*".join(["m"] * 31) + ")"
    assert len(long) > MAX_LENGTH
    assert _spelt(long).endswith("; write it as 1/m**31")
    assert str(_gate(long)).endswith("; write it as 1/m**31")
    assert _writer(long).endswith("; write it as 1/m**31")


@pytest.mark.parametrize(("unit", "spelling"), [("1/(rad*(s))", "1/rad/s"), ("1/(m/s)", "s/m")])
def test_the_gate_the_record_and_the_writer_name_the_same_spelling(
    unit: str, spelling: str
) -> None:
    assert str(_gate(unit)).endswith(f"; write it as {spelling}")
    assert _writer(unit).endswith(f"; write it as {spelling}")
    record = record_dict()
    record["traces"][0]["unit"] = unit
    try:
        parse_record(encode(record))
        said = "taken"
    except RecordRefusedError as exc:
        said = str(exc)
    assert f"write it as {spelling}" in said


@pytest.mark.parametrize("unit", [u for u, _ in BRACKETED] + PLAIN)
def test_the_series_writer_takes_every_form_the_grammar_takes(unit: str) -> None:
    assert _writer(unit) == unit


def test_the_series_writer_s_copy_of_the_grammar_is_the_same_code() -> None:
    assert writer.UNIT_GRAMMAR_PATTERN == unit_spelling.PATTERN
    for name in ("accepted_spelling", "_spelling_product", "_spelling_term"):
        own, copy = getattr(unit_spelling, name, None), getattr(writer, name, None)
        assert own is not None and copy is not None, name
        assert inspect.getsource(own) == inspect.getsource(copy), name
    assert getattr(writer, "_SPELLING_TOKEN", None) is not None
    assert writer._SPELLING_TOKEN.pattern == unit_spelling._SPELLING_TOKEN.pattern  # noqa: SLF001
