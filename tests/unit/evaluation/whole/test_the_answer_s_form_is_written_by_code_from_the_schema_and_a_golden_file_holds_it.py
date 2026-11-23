"""The block that tells a designer the answer's form is written by code and held by a golden file.

Four things are pinned. The block equals its committed golden file byte for byte, so any change
to it is a visible line of a diff. Its digest is the golden's sha256. Every fact the schema holds
(a range, a size limit, a unit, a name) is read from the schema: a constant moved in the row below
moves the block, and a constant the block does not tell moves nothing. And what a designer must
not be told is not in it.

The golden is regenerated, in the same change as the schema's, by writing
``render_answer_form()`` to it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from pydantic.fields import FieldInfo

import physgate.evaluation.whole.answer as answer_module
import physgate.evaluation.whole.form as form
import physgate.evaluation.whole.law as law_module

GOLDEN = Path(__file__).with_name("answer_form_block.golden.txt")

#: Numbers the reference brief's requirements name (settings and bounds): a block that held one
#: would tell the designer a bound, and no setting of the form is any of them.
REQUIREMENT_NUMBERS = (
    "99",
    "101",
    "208",
    "1322",
    "1323",
    "1324",
    "19800",
    "20200",
    "20000",
    "0.75",
    "1.8",
)


def test_the_block_is_its_golden_file_byte_for_byte() -> None:
    assert form.render_answer_form().encode("utf-8") == GOLDEN.read_bytes()


def test_the_digest_is_the_golden_s_sha256_and_the_same_on_every_call() -> None:
    assert form.answer_form_sha256() == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    assert form.answer_form_sha256() == form.answer_form_sha256()
    assert re.fullmatch(r"[0-9a-f]{64}", form.answer_form_sha256())


def test_the_block_holds_no_placeholder_and_ends_on_one_newline() -> None:
    block = form.render_answer_form()
    assert "$" not in block
    assert block.startswith("THE ANSWER\n")
    assert block.endswith("}\n") and not block.endswith("\n\n")
    assert all(len(line) <= 100 for line in block.splitlines())


def test_the_block_tells_the_file_the_designer_writes_and_the_example_it_quotes() -> None:
    block = form.render_answer_form()
    assert f"Write one file, {form.ANSWER_FILE}," in block
    quoted = "\n".join("  " + line if line else line for line in form.example_text().splitlines())
    assert quoted in block


# ── what a designer must not be told ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "word",
    [
        "vector",
        "analysed_controller",
        "gyro_sensitivity",
        "files",
        "no_interface_statement",
        "compute_delay_flags",
        "compute_delay_omitted",
        "native",
        "state_feedback",
        "incremental",
        "corner",
        "digest",
        "cfa93bec",
        "1e-12",
        "radius",
        "frozen",
        "held-out",
        "reference answer",
        "headline",
    ],
)
def test_the_block_does_not_name_what_a_designer_is_not_told(word: str) -> None:
    assert word not in form.render_answer_form().lower()


@pytest.mark.parametrize("number", REQUIREMENT_NUMBERS)
def test_the_block_holds_no_number_a_requirement_names(number: str) -> None:
    assert (
        re.search(rf"(?<![0-9.]){re.escape(number)}(?![0-9.])", form.render_answer_form()) is None
    )


def test_the_block_asks_for_no_test_vectors_and_says_it_is_not_a_design() -> None:
    block = form.render_answer_form()
    assert "vector" not in block.lower()
    assert "not a design, not advice and not a starting point" in " ".join(block.split())


# ── a fact the schema holds moves the block when it moves ──────────────────────────────────────

_TOLD_CONSTANTS = [
    (answer_module, "MAX_ANSWER_BYTES", 70_001, "70001"),
    (answer_module, "MAX_DELAY_SAMPLES", 77, "77 periods"),
    (answer_module, "LAW_MAGNITUDE", 3e6, "3000000"),
    (law_module, "MAX_MEMORY", 9, "at most 9 states"),
    (law_module, "MAX_LINES", 33, "1 to 33 lines"),
    (law_module, "MAX_TERMS", 17, "1 to 17 terms"),
    (law_module, "MAX_COEFFICIENTS", 34, "At most 34."),
    (law_module, "MAX_FACTORS", 5, "at most 5)"),
    (law_module, "PERIOD", "loop_period", '"loop_period"'),
]
_NOT_TOLD_CONSTANTS = [
    (answer_module, "MAX_MAGNITUDE", 1e9),
    (answer_module, "MAX_FILES", 7),
    (answer_module, "MAX_PATH_LENGTH", 7),
    (law_module, "MAX_VECTORS", 7),
    (law_module, "MAX_ROWS", 7),
    (law_module, "MAX_TOTAL_ROWS", 7),
    (law_module, "MAX_CHECK_WORK", 7),
    (law_module, "MAX_FILE_BYTES", 7),
    (law_module, "DUTY_TOLERANCE", 0.5),
    (law_module, "COUNT_TOLERANCE", 7),
    (law_module, "MIN_ROWS", 7),
    (law_module, "PIN_RELATIVE", 0.5),
    (law_module, "PIN_STEPS", 7),
]


@pytest.mark.parametrize(("module", "name", "value", "shown"), _TOLD_CONSTANTS)
def test_a_constant_the_block_tells_moves_the_block(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str, value: object, shown: str
) -> None:
    before = form.render_answer_form()
    monkeypatch.setattr(module, name, value)
    after = form.render_answer_form()
    assert after != before
    assert shown in after


@pytest.mark.parametrize(("module", "name", "value"), _NOT_TOLD_CONSTANTS)
def test_a_constant_the_block_does_not_tell_moves_nothing(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str, value: object
) -> None:
    before = form.render_answer_form()
    monkeypatch.setattr(module, name, value)
    assert form.render_answer_form() == before


def _bound() -> answer_module.FieldBound:
    return answer_module.FieldBound(2, 777, "a test's own bound")


@pytest.mark.parametrize(
    "key", ["period", "command_limit", "sensor_delay", "compute_delay", *answer_module.SETTINGS]
)
def test_a_range_the_block_tells_is_read_from_the_schema_s_bounds(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    name = answer_module.SETTINGS[key][1] if key in answer_module.SETTINGS else key
    if f"ParametersV3.{key}" in form.NOT_TOLD:
        pytest.skip("not told")
    before = form.render_answer_form()
    monkeypatch.setitem(answer_module.FIELD_BOUNDS, name, _bound())
    after = form.render_answer_form()
    assert after != before
    assert "from 2 to 777" in after


@pytest.mark.parametrize(
    "name", sorted(k.split(".", 1)[1] for k in form.NOT_TOLD if k.startswith("FIELD_BOUNDS."))
)
def test_a_bound_the_block_does_not_tell_moves_nothing(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    before = form.render_answer_form()
    monkeypatch.setitem(answer_module.FIELD_BOUNDS, name, _bound())
    assert form.render_answer_form() == before


def test_a_setting_s_unit_and_a_whole_number_rule_are_read_from_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(answer_module.SETTINGS, "update_rate", ("kHz", "update_rate"))
    assert "update_rate                          kHz" in form.render_answer_form()


def test_the_name_length_and_a_line_s_unit_length_are_read_from_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Annotated

    from annotated_types import MaxLen
    from pydantic import StringConstraints

    monkeypatch.setattr(
        law_module, "Name", Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,40}$")]
    )
    assert "at most 40 of a-z" in form.render_answer_form()
    monkeypatch.undo()
    field: FieldInfo = law_module.Line.model_fields["unit"]
    monkeypatch.setattr(field, "metadata", [MaxLen(41)])
    block = form.render_answer_form()
    assert "unit is at most 40 characters" in block  # the smaller of a line's and a state's
    state: FieldInfo = law_module.Memory.model_fields["unit"]
    monkeypatch.setattr(state, "metadata", [MaxLen(44)])
    assert "unit is at most 41 characters" in form.render_answer_form()


def test_the_timing_units_are_the_ones_the_schema_refuses_every_other_for() -> None:
    assert form._timing_units() == {  # noqa: SLF001
        "period": "s",
        "command_limit": "1",
        "sensor_delay": "s",
        "compute_delay": "s",
    }


def test_a_signal_the_schema_adds_is_not_written_until_it_is_described(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(law_module.SIGNALS, "accelerometer", "m/s**2")
    with pytest.raises(form.FormError, match="signals"):
        form.render_answer_form()


def test_a_field_the_schema_adds_is_not_written_until_it_is_placed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "SampledLaw.compute_delay_flags",
        "WholeRunV3.files",
        "ParametersV3.gyro_sensitivity",
    ):
        patched = {k: v for k, v in form.NOT_TOLD.items() if k != key}
        monkeypatch.setattr(form, "NOT_TOLD", patched)
        with pytest.raises(form.FormError):
            form.render_answer_form()
        monkeypatch.undo()
    assert form.render_answer_form().encode() == GOLDEN.read_bytes()


def test_the_digits_a_law_may_carry_are_the_law_module_s_own_statement() -> None:
    found = re.search(r"at most (\d+) significant digits", law_module.__doc__ or "")
    assert found is not None
    assert int(found.group(1)) == form.SIGNIFICANT_DIGITS
