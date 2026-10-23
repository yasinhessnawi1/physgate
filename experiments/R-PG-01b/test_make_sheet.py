"""Tests of make_sheet.sh's work (fullsheet.py) on an invented corpus and table (§2.5).

Run explicitly, on master at the converter's commit or later (the converter is not on the run
branch, which never runs make_sheet.sh): ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CONVERTER = REPO / "scripts" / "parts_sheet_sources.py"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tests" / "unit" / "evaluation"))
import common as C  # noqa: E402
import fullsheet as F  # noqa: E402

pytestmark = pytest.mark.skipif(
    not CONVERTER.is_file(), reason="the converter runs on master only, as make_sheet.sh does"
)

SOURCE = "https://www.pololu.com/product/3575/specs"
TABLE = (
    "A prose line the conversion drops.\n\n"
    "| Row | Quantity | Value | Unit | Source URL | Retrieved | Note |\n"
    "|---|---|---|---|---|---|---|\n"
    f"| R1.01 | stall current @ 6V | 1.5 | A | {SOURCE} | 2026-10-01 | at the stated voltage |\n"
    "| R1.02 | mass (weight) | 9.5 | g | same URL as above | 2026-10-01 | — |\n"
    f"| R5.01 | cell nominal voltage | 1.2 | V | {SOURCE} | 2026-10-01 | — |\n"
    f"| R5.02 | number of cells in the pack | 6 | dimensionless | {SOURCE} | 2026-10-01 | — |\n"
    f"| R6.05 | regulator caveat | see note | — | {SOURCE} | 2026-10-01 "
    "| the vendor site answered with a challenge |\n"
    f"| R8.01 | gyroscope ODR options | 12.5, 26, 52 | Hz | {SOURCE} | 2026-10-01 | settings |\n"
)


def _earlier() -> dict[str, dict[str, Any]]:
    from instrument_corpus import SOURCE_ROWS

    rows = {k: v for k, v in SOURCE_ROWS.items() if k != "R8.01"}
    rows["R6.05"] = {"quantity": "regulator caveat", "value": None, "unit": None, "url": SOURCE}
    rows["R8.01"] = SOURCE_ROWS["R8.01"]
    return rows


def _v1(tmp: Path) -> Path:
    from instrument_corpus import AUTHOR, LABEL, write_corpus

    from physgate.evaluation.inject.corpus import manifest_for, write_manifest

    root = write_corpus(tmp / "v1", rows=_earlier(), sheet_indent=1)
    (root / C.TABLE_NAME).write_text(TABLE)
    write_manifest(root, manifest_for(root, label=LABEL, author_model=AUTHOR))
    return root


def _pins(v1: Path) -> dict[str, Any]:
    import parts_sheet_sources as converter

    edited, facts = F.edit_table((v1 / C.TABLE_NAME).read_bytes(), F.R605)
    sheet = converter.convert(
        edited.decode(), keep=(v1 / "sources.json").read_bytes(), prose="drop"
    )
    counts = F.sheet_counts(sheet)
    return {
        **{k: v for k, v in facts.items() if k != "lines_differing"},
        **{k: v for k, v in counts.items() if k != "remarks"},
        "v1_manifest": C.sha256_file(v1 / "MANIFEST.json"),
        "v1_sheet": C.sha256_file(v1 / "sources.json"),
        "prose_lines": 1,
        "artefacts": 2,
    }


def test_the_edit_changes_one_word_of_one_row_s_note() -> None:
    edited, facts = F.edit_table(TABLE.encode(), F.R605)
    before, after = TABLE.splitlines(), edited.decode().splitlines()
    row = next(i for i, ln in enumerate(before) if ln.startswith("| R6.05 |"))
    assert [(a, b) for a, b in zip(before, after, strict=True) if a != b] == [
        (before[row], before[row].replace("answered", "responded"))
    ]
    assert facts["lines_differing"] == 1 and facts["table_after_bytes"] == len(TABLE.encode()) + 1
    assert facts["note_before"] == C.sha256_bytes(b"the vendor site answered with a challenge")
    assert facts["note_after"] == C.sha256_bytes(b"the vendor site responded with a challenge")
    assert facts["line_before"] == C.sha256_bytes(before[row].encode())


@pytest.mark.parametrize(
    "table",
    [
        TABLE.replace("| R6.05 |", "| R6.06 |"),
        TABLE.replace("site answered", "site replied"),
        TABLE.replace("A prose line", "An answered prose line"),
        TABLE + next(ln for ln in TABLE.splitlines(keepends=True) if ln.startswith("| R6.05")),
    ],
    ids=["no-row", "no-word", "the-word-elsewhere", "the-row-twice"],
)
def test_the_edit_refuses_anything_but_one_word_once(table: str) -> None:
    with pytest.raises(F.Refused):
        F.edit_table(table.encode(), F.R605)


def test_the_corpus_is_made_whole_and_held_to_its_pins(tmp_path: Path) -> None:
    v1 = _v1(tmp_path)
    pins = _pins(v1)
    out, sheet_dir = tmp_path / "v1-fullsheet", tmp_path / "sheet"
    found = F.make(REPO, v1, out, sheet_dir, pins, label="an invented label")
    assert found["sheet"] == pins["sheet"] and found["prose_dropped"] == 1
    assert found["rows_with_neither"] == 0 and found["copied_byte_for_byte"] == found["files"] - 1
    assert (sheet_dir / C.TABLE_NAME).read_bytes().count(b"responded") == 1
    assert (out / C.TABLE_NAME).read_text() == TABLE  # the corpus keeps the unedited table
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["label"] == "an invented label" and manifest["author_model"] == C.AUTHOR_MODEL
    rows = json.loads((out / "sources.json").read_text())["rows"]
    assert rows["R6.05"]["note"] == "the vendor site responded with a challenge"
    assert rows["R1.01"]["value"] == 1.5 and "given" not in rows["R1.01"]


def test_a_pin_that_does_not_hold_refuses_and_nothing_is_written_over(tmp_path: Path) -> None:
    v1 = _v1(tmp_path)
    pins = {**_pins(v1), "notes": 99}
    with pytest.raises(F.Refused, match="notes"):
        F.make(REPO, v1, tmp_path / "a", tmp_path / "s", pins)
    with pytest.raises(F.Refused, match="exists"):
        F.make(REPO, v1, tmp_path / "a", tmp_path / "s2", _pins(v1))


def test_a_changed_earlier_field_is_counted() -> None:
    earlier = json.dumps(
        {"label": "x", "rows": {"R1.01": {"quantity": "q", "value": 1, "unit": "A"}}}
    )
    same = json.dumps(
        {"label": "x", "rows": {"R1.01": {"quantity": "q", "value": 1, "unit": "A", "note": "n"}}}
    )
    moved = json.dumps(
        {"label": "x", "rows": {"R1.01": {"quantity": "q", "value": 2, "unit": "A"}}}
    )
    assert F.kept_whole(earlier.encode(), same.encode()) == 0
    assert F.kept_whole(earlier.encode(), moved.encode()) == 1


def test_the_real_pins_are_the_frozen_file_s() -> None:
    text = " ".join((HERE / "CRITERIA.md").read_text().split())
    for key in ("table_after", "line_before", "line_after", "note_before", "note_after", "sheet"):
        assert F.PINS[key] in text, key
    assert "40,095 bytes, 1,224 lines" in text and F.PINS["sheet_lines"] == 1224
