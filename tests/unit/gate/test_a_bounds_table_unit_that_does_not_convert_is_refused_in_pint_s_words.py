"""The power fault's last site: a bounds table row whose unit does not convert is refused in words.

A range or an envelope whose unit does not convert to its kind's does not load, and the table's
refusal says why. The reason printed pint's own error, which pint 0.26.1, computing in fractions,
cannot print for a unit with a power other than one: its formatter asks the fraction for the
format ``n``. So a row in ``A**2`` was refused for "Invalid format specifier 'n' for object of
type 'Fraction'", not for its unit. pint's refusal is now put into words as the gate's other
refusals are (``units.pint_message``), whatever the powers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.gate.bounds_table import BOUNDS_NAME, BoundsTableError, load_table

RANGE = """
[meta]
domain = "electrical"
curated_by = "a test"

[[range]]
quantity = "stall_current"
low = 0.36
high = 6.5
unit = "A"
class = "a motor"
source = "a datasheet"
retrieved = 2026-09-26
confirmed = 2026-10-19
note = "a note"
"""

ENVELOPE = """
[meta]
domain = "electrical"
curated_by = "a test"

[[envelope]]
kind = "efficiency"
low = 0
high = 1
unit = "1"
class = "any machine"
source = "a definition"
retrieved = 2026-09-26
confirmed = 2026-10-19
note = "a note"
"""


def _refusal(tmp_path: Path, text: str) -> str:
    directory = tmp_path / "electrical"
    directory.mkdir(parents=True)
    (directory / BOUNDS_NAME).write_text(text)
    with pytest.raises(BoundsTableError) as caught:
        load_table(directory / BOUNDS_NAME)
    return caught.value.context["reason"]


@pytest.mark.parametrize(
    ("unit", "words"),
    [
        (
            "A**2",
            "the unit 'A**2' is not one a current is written in: pint cannot convert "
            "'ampere ** 2' ([current]**2) to 'ampere' ([current])",
        ),
        (
            "kg*m**2",
            "the unit 'kg*m**2' is not one a current is written in: pint cannot convert "
            "'kilogram * meter ** 2' ([mass] * [length]**2) to 'ampere' ([current])",
        ),
        (
            "V",
            "the unit 'V' is not one a current is written in: pint cannot convert 'volt' ([mass] * "
            "[length]**2 * [time]**-3 * [current]**-1) to 'ampere' ([current])",
        ),
    ],
)
def test_a_range_in_a_unit_that_does_not_convert_is_refused_in_pint_s_words(
    tmp_path: Path, unit: str, words: str
) -> None:
    assert words in _refusal(tmp_path, RANGE.replace('unit = "A"', f'unit = "{unit}"'))


def test_an_envelope_in_a_unit_that_does_not_convert_is_refused_in_pint_s_words(
    tmp_path: Path,
) -> None:
    reason = _refusal(tmp_path, ENVELOPE.replace('unit = "1"', 'unit = "m**2"'))
    assert (
        "the unit 'm**2' is not one a efficiency is written in: pint cannot convert 'meter ** 2' "
        "([length]**2) to 'dimensionless' (none)"
    ) in reason


def test_a_range_in_a_unit_the_gate_refuses_keeps_the_gate_s_words(tmp_path: Path) -> None:
    # Guard: the gate's own refusal is its own text, as it was.
    reason = _refusal(tmp_path, RANGE.replace('unit = "A"', 'unit = "dB"'))
    assert (
        "the unit 'dB' is not one a current is written in: the unit 'dB' is logarithmic" in reason
    )
