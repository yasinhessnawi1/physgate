"""``scripts/parts_sheet_sources.py``: a corpus's parts sheet from its authors' table, whole.

The authors of a corpus write against ``parts_sheet.md``, a Markdown table whose value cells
hold single numbers, ranges, lists, qualified numbers and text, and whose last column holds
notes. A review is given ``sources.json``. A sheet written by hand from the table kept only
the rows that are one number and dropped every note, so a reviewer saw an empty row where the
authors saw a range. The converter writes the sheet from the table and refuses to leave any
cell out:

- a value cell that is one bare number, with a unit the gate reads, becomes the row's number
  and unit, which a derived source may cite; every other value cell is kept as written under
  ``given``, with its unit, and a number whose spelling the number alone does not keep
  (``1.50``) keeps its spelling there too;
- every note is carried across as written;
- a source cell is an address, or ``same URL``, ``same supply URL`` or ``same URL as above``
  for the address of the nearest row above;
- the retrieval date is one date for the whole sheet, so no row's date is dropped;
- a column, a line or a cell it does not know how to carry stops it, and nothing is written.

Running it twice gives the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import parts_sheet_sources as converter
import pytest

from physgate.evaluation.inject.corpus import Sources, telltales

LABEL = "a parts sheet for the converter's own tests"
HEADER = (
    "| Row | Quantity | Value | Unit | Source URL | Retrieved | Note |\n"
    "|---|---|---|---|---|---|---|\n"
)
DAY = "2026-10-01"

SHEET = (
    "# Parts sheet\n\nEvery address read on one day.\n\n## R1: motor and supply\n\n"
    + HEADER
    + f"| R1.01 | stall current @ 6V | 1.5 | A | https://example.com/motor | {DAY} | — |\n"
    + f"| R1.02 | mass | 1.50 | g | same URL as above | {DAY} | weighed with its bracket |\n"
    + f"| R1.03 | supply range | 2.7–5.5 | V | https://example.com/supply | {DAY} | min and max |\n"
    + f"| R1.04 | output data rates | 12.5, 26, 52, 104 | Hz | same supply URL | {DAY} | — |\n"
    + f"| R1.05 | package | QFN-24 | — | https://example.com/pkg | {DAY} | a text value |\n"
    + f"| R1.06 | sensitivity | 16384 | LSB/g | https://example.com/imu | {DAY} | - |\n"
    + f"| R1.07 | current limit | up to 2 | A | https://example.com/drv | {DAY} "
    + "| set by a resistor |\n"
    + "\n## R1a: pack\n\n"
    + HEADER
    + f"| R1a.01 | number of cells | 6 | dimensionless | https://example.com/pack | {DAY} "
    + "| a \\| b |\n"
)


def _rows(text: str = SHEET) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = json.loads(converter.convert(text, label=LABEL))["rows"]
    return rows


def test_a_bare_number_with_a_unit_the_gate_reads_is_the_row_s_citable_number() -> None:
    rows = _rows()
    assert rows["R1.01"] == {
        "quantity": "stall current @ 6V",
        "value": 1.5,
        "unit": "A",
        "url": "https://example.com/motor",
    }
    assert rows["R1a.01"]["value"] == 6 and type(rows["R1a.01"]["value"]) is int
    assert rows["R1a.01"]["unit"] == "dimensionless"


@pytest.mark.parametrize(
    ("row", "given"),
    [
        ("R1.03", "2.7–5.5 V"),
        ("R1.04", "12.5, 26, 52, 104 Hz"),
        ("R1.05", "QFN-24"),
        ("R1.06", "16384 LSB/g"),
        ("R1.07", "up to 2 A"),
    ],
    ids=["a-range", "a-list", "a-text", "a-unit-the-gate-cannot-read", "a-qualified-number"],
)
def test_every_other_value_cell_is_given_as_written_with_its_unit(row: str, given: str) -> None:
    found = _rows()[row]
    assert found["given"] == given
    assert found["value"] is None and found["unit"] is None


def test_a_number_whose_spelling_the_number_does_not_keep_is_given_as_well() -> None:
    found = _rows()["R1.02"]
    assert found["value"] == 1.5 and found["unit"] == "g"
    assert found["given"] == "1.50 g"


def test_every_note_is_carried_across_as_written_and_a_dash_is_no_note() -> None:
    rows = _rows()
    assert rows["R1.02"]["note"] == "weighed with its bracket"
    assert rows["R1.03"]["note"] == "min and max"
    assert rows["R1a.01"]["note"] == "a | b"
    assert "note" not in rows["R1.01"] and "note" not in rows["R1.06"]


def test_same_url_is_the_address_of_the_nearest_row_above() -> None:
    rows = _rows()
    assert rows["R1.02"]["url"] == "https://example.com/motor"
    assert rows["R1.04"]["url"] == "https://example.com/supply"


def test_every_row_of_the_table_has_a_number_or_a_given_value_and_keeps_its_order() -> None:
    rows = _rows()
    assert list(rows) == ["R1.01", "R1.02", "R1.03", "R1.04", "R1.05", "R1.06", "R1.07", "R1a.01"]
    assert all(r["value"] is not None or r.get("given") for r in rows.values())


def test_rows_keep_the_table_s_order_even_where_it_is_not_sorted() -> None:
    lines = SHEET.splitlines(keepends=True)
    six, seven = (
        next(n for n, x in enumerate(lines) if x.startswith(f"| {r} |")) for r in ("R1.06", "R1.07")
    )
    lines[six], lines[seven] = lines[seven], lines[six]
    assert list(_rows("".join(lines)))[5:7] == ["R1.07", "R1.06"]


def test_the_sheet_is_a_valid_parts_sheet_that_holds_no_telltale_word() -> None:
    written = converter.convert(SHEET, label=LABEL)
    sheet = Sources.model_validate_json(written)
    assert sheet.label == LABEL
    assert telltales(written.decode()) == []


def test_the_same_table_gives_the_same_bytes_and_the_command_writes_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = tmp_path / "parts_sheet.md"
    table.write_text(SHEET)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert converter.main([str(table), str(first), "--label", LABEL]) == 0
    assert converter.main([str(table), str(second), "--label", LABEL]) == 0
    assert first.read_bytes() == second.read_bytes() == converter.convert(SHEET, label=LABEL)
    assert first.read_bytes().endswith(b"}\n")
    said = capsys.readouterr().out
    assert "rows 8" in said and "empty 0" in said and "notes 5" in said


def test_the_command_writes_over_no_file(tmp_path: Path) -> None:
    table = tmp_path / "parts_sheet.md"
    table.write_text(SHEET)
    out = tmp_path / "sources.json"
    out.write_text("kept")
    assert converter.main([str(table), str(out), "--label", LABEL]) != 0
    assert out.read_text() == "kept"


def _row(text: str, row: str, cell: int, to: str) -> str:
    """``text`` with one cell of one row replaced."""
    lines = text.splitlines(keepends=True)
    for n, line in enumerate(lines):
        if line.startswith(f"| {row} |"):
            cells = line.rstrip("\n").split(" | ")
            cells[cell] = to
            lines[n] = " | ".join(cells) + "\n"
    return "".join(lines)


@pytest.mark.parametrize(
    ("changed", "said"),
    [
        (SHEET.replace("| Note |", "| Note | Extra |"), "column"),
        (SHEET.replace("| Source URL |", "| Address |"), "column"),
        (SHEET.replace(f" | {DAY} | — |\n", " |\n", 1), "cells"),
        (_row(SHEET, "R1.03", 2, ""), "value"),
        (_row(SHEET, "R1.03", 2, "—"), "value"),
        (_row(SHEET, "R1.03", 1, "-"), "quantity"),
        (_row(SHEET, "R1.03", 4, "datasheet table 4"), "source"),
        (_row(SHEET, "R1.03", 4, "same URL as R1.01"), "source"),
        (_row(SHEET, "R1.03", 4, "same URL as https://example.com/pkg"), "source"),
        (_row(SHEET, "R1.01", 4, "same URL as above"), "source"),
        (_row(SHEET, "R1.03", 5, "2026-10-02"), "date"),
        (_row(SHEET, "R1.03", 0, "| R1.01"), "twice"),
        (_row(SHEET, "R1.03", 0, "| R1.3"), "line"),
        (SHEET.replace("| R1.01 |", "| R1.01  ", 1), "line"),
        ("# no table here\n", "no row"),
    ],
    ids=[
        "a-column-it-does-not-know",
        "a-renamed-column",
        "a-row-with-a-cell-missing",
        "an-empty-value",
        "a-dash-for-a-value",
        "a-row-with-no-quantity",
        "a-source-that-is-no-address",
        "a-reference-it-cannot-follow",
        "a-reference-that-names-its-own-address",
        "a-reference-with-nothing-above",
        "a-second-retrieval-date",
        "a-row-id-twice",
        "a-table-line-that-is-no-row",
        "a-row-line-it-cannot-split",
        "no-table",
    ],
)
def test_a_table_it_cannot_carry_whole_is_refused(changed: str, said: str) -> None:
    assert changed != SHEET
    with pytest.raises(converter.SheetRefusedError, match=said):
        converter.convert(changed, label=LABEL)


def test_a_refused_table_writes_nothing(tmp_path: Path) -> None:
    table = tmp_path / "parts_sheet.md"
    table.write_text(_row(SHEET, "R1.03", 2, ""))
    out = tmp_path / "sources.json"
    assert converter.main([str(table), str(out), "--label", LABEL]) != 0
    assert not out.exists()
