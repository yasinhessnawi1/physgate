"""What the block states as a convention is the schema's own, and the unit grammar is the parser's.

The name's character classes and the set of a term's signs are read from the schema's pattern and
``Literal``; a schema that allows a capital in a name or a sign of 2 moves the block. The unit
grammar the block prints is held to the one parser a law's units are read with: every spelling it
shows as written is read, every one it shows as refused is refused, and the reviewer's own
accepted and refused spellings are read as they were found. The block no longer promises that a
delay is taken as stated, that a mode is set aside, or that every other rule it states is refused:
the four rules the scorer reads without refusing are named in :func:`accepted_gaps` and held as
accepted, so the block cannot promise a refusal that is not there.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

import pytest
from answer_form_cases import Case, accepted_gaps
from pydantic import StringConstraints
from pydantic.fields import FieldInfo

import physgate.evaluation.whole.form as form
import physgate.evaluation.whole.law as law_module
from physgate.evaluation.whole.answer import parse_answer_scoped

BLOCK = form.render_answer_form()
ONE_LINE = " ".join(BLOCK.split())

#: Spellings found accepted by the parser, and found refused (the reviewer's, and the block's own).
ACCEPTED = ["rad*s", "rad**2", "rad^2", "1/(rad*s)", "1/rad*s", "rad * s", "s**-1", "1/rad"]
REFUSED = ["rad s", "rad.s", "rad·s", "(rad*s)/rad", "2*rad", "rad ** 2", "(rad*s)", "1/(1/s)"]


# ── the name and the sign are the schema's ──────────────────────────────────────────────────────


def test_a_name_that_may_hold_a_capital_is_told_to_hold_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "one character of a-z then at most 31 characters of a-z, 0-9, _" in ONE_LINE
    monkeypatch.setattr(
        law_module,
        "Name",
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")],
    )
    changed = " ".join(form.render_answer_form().split())
    assert "one character of A-Z, a-z then at most 31 characters of A-Z, a-z, 0-9, _" in changed


def test_a_name_pattern_that_is_not_a_first_class_a_later_class_and_a_length_is_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(law_module, "Name", Annotated[str, StringConstraints(pattern=r"^[a-z]+$")])
    with pytest.raises(form.FormError, match="pattern"):
        form.render_answer_form()


def test_a_sign_set_that_is_widened_is_told_widened(monkeypatch: pytest.MonkeyPatch) -> None:
    assert '"sign": the number 1 or -1,' in ONE_LINE
    field: FieldInfo = law_module.Term.model_fields["sign"]
    monkeypatch.setattr(field, "annotation", Literal[1, -1, 2])
    assert '"sign": the number 1, -1 or 2,' in " ".join(form.render_answer_form().split())


def test_the_reserved_name_s_unit_and_the_unit_symbols_are_read_from_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "it is the period above, in s," in ONE_LINE and "The symbols are rad and s," in ONE_LINE
    monkeypatch.setitem(law_module.SIGNALS, "wheel_speed", "m/s")
    monkeypatch.setitem(form.SIGNAL_MEANINGS, "wheel_speed", "x")
    assert "The symbols are m, rad and s," in " ".join(form.render_answer_form().split())


# ── the unit grammar the block prints is the parser's ────────────────────────────────────────────


def _read(unit: str) -> bool:
    try:
        law_module.dimension(unit)
    except law_module.LawRefused:
        return False
    return True


@pytest.mark.parametrize("unit", getattr(form, "UNIT_WRITTEN", ("<missing>",)))
def test_each_unit_the_block_shows_as_written_is_read_by_the_parser_and_is_in_the_block(
    unit: str,
) -> None:
    assert _read(unit)
    assert unit in BLOCK


@pytest.mark.parametrize("unit", getattr(form, "UNIT_NOT_WRITTEN", ("<missing>",)))
def test_each_unit_the_block_shows_as_refused_is_refused_by_the_parser_and_is_in_the_block(
    unit: str,
) -> None:
    assert not _read(unit)
    assert unit in BLOCK


def test_the_quotient_the_block_gives_as_an_example_is_read_as_it_says() -> None:
    long, short = getattr(form, "UNIT_QUOTIENT", ("<missing>", "<missing>"))
    assert law_module.dimension(long) == law_module.dimension(short) == (("rad", -1), ("s", 1))
    assert f"{long} is {short}" in ONE_LINE


@pytest.mark.parametrize("unit", ACCEPTED)
def test_a_spelling_the_parser_reads_is_read(unit: str) -> None:
    assert _read(unit)


@pytest.mark.parametrize("unit", REFUSED)
def test_a_spelling_the_parser_refuses_is_refused(unit: str) -> None:
    assert not _read(unit)


def test_the_block_names_the_ways_a_unit_is_refused_that_the_parser_refuses_for() -> None:
    for words in (
        "a space or a dot between symbols",
        "a number other than a leading 1",
        "a bracket anywhere else",
        "a space inside a power",
    ):
        assert words in ONE_LINE


def test_a_bracket_after_a_slash_is_the_one_bracket_the_parser_takes() -> None:
    assert _read("1/(rad*s)") and _read("rad/(s)")
    assert not _read("(rad)") and not _read("1/rad*(s)")


# ── sentences that were over-promised are not there, and what is true is ─────────────────────────


@pytest.mark.parametrize(
    "words",
    [
        "taken as stated",
        "any other breach",
        "set aside",
        "even if nothing reads it",
        "keep such memory",
        "flagged",
        "lower-case letter",
    ],
)
def test_the_block_no_longer_says(words: str) -> None:
    assert words not in ONE_LINE


@pytest.mark.parametrize(
    "words",
    [
        "State the delays your design has. ",
        "and that the command does not read makes the loop unstable",
        "A state the command reads is judged with the loop, like any other.",
        "A state that keeps its value exactly (a leak of exactly 1) is allowed where the loop "
        "drives it back. If the tilt, its rate or the reference feeds such a state and the "
        "command reads it, the answer is then reported in a class of its own.",
        "since the last update, over the period; that needs a memory state holding the last "
        "wheel_reference.",
        "A leak that is not exactly 1 but within a rounding error of it is judged unstable.",
        "A positive command drives the wheels forward: the wheel_angle and the wheel_speed "
        "increase",
        "the body leaning forward over wheels that stay put reads as a negative wheel_angle",
        "No sensor of the kit gives the tilt: the gyro gives its rate (tilt_rate). "
        "A law that reads tilt is judged as if it knew the tilt exactly.",
        "wheel_reference: an angle in rad that advances at the commanded wheel speed in rad/s",
        '"update_rate" and the controller\'s "period" are two statements: each is held to its own '
        "range, and nothing else ties one to the other.",
        "with no byte-order mark",
        "and each key once",
        "the number 1 or -1",
        "A coefficient's name is its own: a state or a line may bear the same name.",
    ],
)
def test_the_block_says(words: str) -> None:
    assert words in ONE_LINE


def test_the_block_names_no_number_that_is_the_scorer_s_own_tolerance_for_a_held_state() -> None:
    assert not re.search(r"1e-\d+|1 - 1e|0\.99999", BLOCK)


@pytest.mark.parametrize("gap", accepted_gaps(), ids=lambda case: case.label)
def test_a_rule_the_block_states_and_the_scorer_does_not_refuse_is_never_listed_as_refused(
    gap: object,
) -> None:
    assert isinstance(gap, Case)
    parse_answer_scoped(gap.data)  # read, not refused
    assert "any other breach" not in ONE_LINE and "rule stated above" not in ONE_LINE
