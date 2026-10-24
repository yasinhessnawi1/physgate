"""A row of the parts sheet gives its value as its authors wrote it, and its note.

A row's ``value`` and ``unit`` are the one number a derived source may cite. A row that is
not one number (a range, a list, a text) has none, and a sheet that held only that gave a
reviewer an empty row where its authors had a range. So a row may also carry:

- ``given``: the value cell as its authors wrote it, with its unit. A sheet that gives it on
  any row gives it on every row with no number, so no row of such a sheet is empty;
- ``note``: the authors' note on the row.

Both are words: read without the whitespace around them, so a cell of spaces is no value.
The sheet may also carry ``remarks``, lines its authors wrote beside the table.

Neither is citable: a derived source still cites a number, and a row with only ``given``
gives none. A sheet written before these fields existed has neither on any row; it loads as
it did, its bytes and so its manifest's digest unchanged, and a review is given those bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from instrument_corpus import BASE_NODES, SOURCE, SOURCE_ROWS, node, write_corpus
from pydantic import ValidationError

from physgate.evaluation.inject.corpus import (
    SOURCES_NAME,
    Sources,
    digest,
    load_corpus,
)
from physgate.evaluation.inject.exceptions import CorpusError

REPO = Path(__file__).resolve().parents[3]
#: Two committed sheets written before ``given`` and ``note`` existed, with their manifests'
#: digests as their experiment froze them. Both must load unchanged.
OLD_CORPORA = {
    "corpora/injected-errors/fresh-v1": (
        "e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c"
    ),
    "experiments/R-PG-02/practice/corpus-v1": (
        "ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0"
    ),
}
#: Their one shared sheet's digest.
OLD_SHEET_SHA256 = "bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91"

RANGE: dict[str, Any] = {
    "quantity": "supply range",
    "value": None,
    "unit": None,
    "given": "2.7–5.5 V",
    "note": "min and max",
    "url": SOURCE,
}


def _sheet(**rows: dict[str, Any]) -> Sources:
    return Sources.model_validate_json(json.dumps({"label": "a sheet", "rows": rows}))


def test_a_row_that_is_not_one_number_gives_its_value_as_written_and_its_note() -> None:
    sheet = _sheet(**{"R1.01": RANGE, "R1.02": SOURCE_ROWS["R1.01"]})
    assert sheet.rows["R1.01"].given == "2.7–5.5 V"
    assert sheet.rows["R1.01"].note == "min and max"
    assert sheet.rows["R1.02"].given is None and sheet.rows["R1.02"].note is None


def test_a_row_with_its_number_may_give_its_spelling_and_a_note() -> None:
    row = {**SOURCE_ROWS["R1.01"], "given": "1.50 A", "note": "at 6 V"}
    assert _sheet(**{"R1.01": row}).rows["R1.01"].value == 1.5


def test_a_sheet_that_gives_values_gives_one_on_every_row_with_no_number() -> None:
    empty = {"quantity": "package", "value": None, "unit": None, "url": SOURCE}
    with pytest.raises(ValidationError, match="every row with no number"):
        _sheet(**{"R1.01": RANGE, "R1.02": empty})


def test_a_sheet_written_before_given_existed_loads_with_its_empty_rows() -> None:
    sheet = _sheet(**SOURCE_ROWS)
    assert sheet.rows["R8.01"].value is None and sheet.rows["R8.01"].given is None


@pytest.mark.parametrize(
    "row",
    [
        {**RANGE, "given": ""},
        {**RANGE, "note": ""},
        {**RANGE, "given": "   "},
        {**RANGE, "given": "\u00a0\t"},
        {**RANGE, "note": "  "},
        {**RANGE, "given": 2.7},
        {**RANGE, "min": 2.7},
    ],
    ids=[
        "an-empty-given",
        "an-empty-note",
        "a-blank-given",
        "a-given-of-a-no-break-space-and-a-tab",
        "a-blank-note",
        "a-number-as-given",
        "a-field-it-does-not-know",
    ],
)
def test_a_row_s_given_and_note_are_words_and_nothing_else_is_added(row: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _sheet(**{"R1.01": row})


def test_a_derived_source_cannot_cite_a_row_that_only_gives_its_value(tmp_path: Path) -> None:
    rows = {**SOURCE_ROWS, "R8.01": {**SOURCE_ROWS["R8.01"], "given": "12.5 to 1600 Hz"}}
    imu = node("electrical.imu", quantities={"sample_rate": (1000, "Hz")})
    imu["quantities"]["sample_rate"]["source"] = "derived: [R8.01]"
    root = write_corpus(tmp_path / "corpus", base_nodes=(*BASE_NODES[:2], imu), rows=rows)
    with pytest.raises(CorpusError, match="not one number"):
        load_corpus(root)


@pytest.mark.parametrize("where", sorted(OLD_CORPORA))
def test_a_committed_sheet_written_before_given_loads_unchanged(where: str) -> None:
    root = REPO / where
    corpus = load_corpus(root)
    assert corpus.manifest_sha256 == OLD_CORPORA[where] == digest(root / "MANIFEST.json")
    assert digest(root / SOURCES_NAME) == OLD_SHEET_SHA256
    assert corpus.parts_sheet == (root / SOURCES_NAME).read_bytes()
    assert all(r.given is None and r.note is None for r in corpus.sources.rows.values())


def test_a_given_value_and_a_note_are_read_without_their_surrounding_whitespace() -> None:
    row = {**RANGE, "given": " 2.7–5.5 V\u00a0", "note": "\tmin and max "}
    sheet = _sheet(**{"R1.01": row})
    assert sheet.rows["R1.01"].given == "2.7–5.5 V" and sheet.rows["R1.01"].note == "min and max"


def test_a_sheet_may_carry_its_authors_remarks_as_lines() -> None:
    sheet = Sources.model_validate_json(
        json.dumps({"label": "a sheet", "rows": {"R1.01": RANGE}, "remarks": ["one", "two"]})
    )
    assert sheet.remarks == ("one", "two")
    assert _sheet(**{"R1.01": RANGE}).remarks is None


@pytest.mark.parametrize(
    "remarks", [[], [""], ["   "], [2]], ids=["none", "an-empty-line", "a-blank-line", "a-number"]
)
def test_remarks_are_lines_of_words(remarks: list[object]) -> None:
    with pytest.raises(ValidationError):
        Sources.model_validate_json(
            json.dumps({"label": "a sheet", "rows": {"R1.01": RANGE}, "remarks": remarks})
        )


# --- What the account says of the sheet is what its bytes hold ---------------------------------
#
# A packet's account says the sheet gives values as written, notes or remarks exactly when a row
# or the sheet holds one. A field written as null, or holding only characters that print as
# nothing, would put the key in the bytes a review reads while the account says nothing of it.


@pytest.mark.parametrize(
    "row",
    [{**SOURCE_ROWS["R1.01"], "given": None}, {**SOURCE_ROWS["R1.01"], "note": None}],
    ids=["a-null-given", "a-null-note"],
)
def test_an_optional_field_written_as_null_is_refused(row: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="null"):
        _sheet(**{"R1.01": row})


def test_remarks_written_as_null_are_refused() -> None:
    with pytest.raises(ValidationError, match="null"):
        Sources.model_validate_json(
            json.dumps({"label": "a sheet", "rows": {"R1.01": RANGE}, "remarks": None})
        )


@pytest.mark.parametrize(
    "text",
    ["​", "﻿", " ​‍\t", "⁠ ‌"],
    ids=["a-zero-width-space", "a-byte-order-mark", "joiners-and-whitespace", "a-word-joiner"],
)
def test_a_field_of_characters_that_print_as_nothing_holds_no_words(text: str) -> None:
    for row in ({**RANGE, "note": text}, {**RANGE, "given": text}):
        with pytest.raises(ValidationError):
            _sheet(**{"R1.01": row})
    with pytest.raises(ValidationError):
        Sources.model_validate_json(
            json.dumps({"label": "a sheet", "rows": {"R1.01": RANGE}, "remarks": [text]})
        )


def test_words_beside_a_zero_width_character_are_still_words() -> None:
    sheet = _sheet(**{"R1.01": {**RANGE, "note": "​min and max﻿ "}})
    assert sheet.rows["R1.01"].note == "min and max"
