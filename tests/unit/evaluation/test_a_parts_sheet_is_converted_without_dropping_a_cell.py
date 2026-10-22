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
from typing import Any

import parts_sheet_sources as converter
import pytest
from instrument_corpus import BASE_NODES, node, write_corpus

from physgate.evaluation.inject.corpus import Sources, load_corpus, telltales
from physgate.evaluation.inject.exceptions import CorpusError

LABEL = "a parts sheet for the converter's own tests"
HEADER = (
    "| Row | Quantity | Value | Unit | Source URL | Retrieved | Note |\n"
    "|---|---|---|---|---|---|---|\n"
)
DAY = "2026-10-01"
MOTOR, SUPPLY, PKG = (f"https://example.com/{p}" for p in ("motor", "supply", "pkg"))
IMU, DRV, PACK = (f"https://example.com/{p}" for p in ("imu", "drv", "pack"))

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


# --- Keeping an earlier sheet's numbers -------------------------------------------------------
#
# A corpus whose design was written against an earlier, hand-made sheet cites that sheet's
# numbers, some of them picked from a range or a list. Converted from the table alone, such a
# row has no number and the design no longer loads. Kept from the earlier sheet, every field
# it had stays as it was, and the table adds what it lacked: the value as written, and notes.

#: The earlier sheet for ``SHEET``: some numbers picked from the table's ranges and texts, its
#: units its own, no ``given`` and no note.
OLD: dict[str, Any] = {
    "label": "the earlier sheet",
    "rows": {
        "R1.01": {"quantity": "stall current @ 6V", "value": 1.5, "unit": "A", "url": MOTOR},
        "R1.02": {"quantity": "mass", "value": 1.5, "unit": "g", "url": MOTOR},
        "R1.03": {"quantity": "supply range", "value": 5.5, "unit": "V", "url": SUPPLY},
        "R1.04": {"quantity": "output data rates", "value": None, "unit": None, "url": SUPPLY},
        "R1.05": {"quantity": "package", "value": None, "unit": None, "url": PKG},
        "R1.06": {"quantity": "sensitivity", "value": 16384, "unit": "dimensionless", "url": IMU},
        "R1.07": {"quantity": "current limit", "value": 2, "unit": "A", "url": DRV},
        "R1a.01": {
            "quantity": "number of cells",
            "value": 6,
            "unit": "dimensionless",
            "url": PACK,
        },
    },
}


def _old(**rows: dict[str, Any]) -> bytes:
    sheet = {**OLD, "rows": {**OLD["rows"], **rows}}
    return (json.dumps(sheet, indent=1, ensure_ascii=False) + "\n").encode()


def _kept(text: str = SHEET, old: bytes | None = None) -> dict[str, Any]:
    kept: dict[str, Any] = json.loads(converter.convert(text, keep=_old() if old is None else old))
    return kept


def test_keeping_an_earlier_sheet_keeps_every_number_it_gave_and_adds_what_it_lacked() -> None:
    rows = _kept()["rows"]
    assert rows["R1.03"]["value"] == 5.5 and rows["R1.03"]["given"] == "2.7–5.5 V"
    assert rows["R1.06"]["unit"] == "dimensionless" and rows["R1.06"]["given"] == "16384 LSB/g"
    assert rows["R1.07"]["value"] == 2 and rows["R1.07"]["given"] == "up to 2 A"
    assert (
        rows["R1.02"]["given"] == "1.50 g" and rows["R1.02"]["note"] == "weighed with its bracket"
    )
    assert rows["R1.04"]["given"] == "12.5, 26, 52, 104 Hz" and rows["R1.04"]["value"] is None
    # A row the table writes as the kept number in the kept unit gains nothing to give.
    assert "given" not in rows["R1.01"] and "given" not in rows["R1a.01"]
    assert rows["R1a.01"]["note"] == "a | b"


def test_keeping_is_strictly_additive_field_by_field() -> None:
    old = json.loads(_old())
    kept = _kept()
    assert kept["label"] == old["label"]
    assert list(kept["rows"]) == list(old["rows"])
    for row_id, before in old["rows"].items():
        after = kept["rows"][row_id]
        for field, value in before.items():
            assert json.dumps(after[field]) == json.dumps(value), (row_id, field)
        assert set(after) - set(before) <= {"given", "note"}, row_id
        if before["value"] is None:
            assert after["given"], row_id


def test_a_kept_sheet_lets_a_design_that_cites_a_picked_number_load(tmp_path: Path) -> None:
    driver = node("electrical.driver", quantities={"current_limit": (2, "A")})
    driver["quantities"]["current_limit"]["source"] = "derived: [R1.07]"
    base = (driver, *BASE_NODES[1:])
    kept = json.loads(converter.convert(SHEET, keep=_old()))["rows"]
    load_corpus(write_corpus(tmp_path / "kept", base_nodes=base, rows=kept))
    alone = json.loads(converter.convert(SHEET, label=LABEL))["rows"]
    with pytest.raises(CorpusError, match="not one number"):
        load_corpus(write_corpus(tmp_path / "alone", base_nodes=base, rows=alone))


def _without(old: bytes, row_id: str) -> bytes:
    sheet = json.loads(old)
    del sheet["rows"][row_id]
    return json.dumps(sheet).encode()


def _reorder(old: bytes) -> bytes:
    sheet = json.loads(old)
    sheet["rows"] = dict(reversed(sheet["rows"].items()))
    return json.dumps(sheet).encode()


@pytest.mark.parametrize(
    ("table", "old", "said"),
    [
        (SHEET, _old(**{"R1.03": {**OLD["rows"]["R1.03"], "value": 4.0}}), "R1.03"),
        (SHEET, _old(**{"R1.01": {**OLD["rows"]["R1.01"], "value": -1.5}}), "R1.01"),
        (SHEET, _old(**{"R1.05": {**OLD["rows"]["R1.05"], "quantity": "case"}}), "R1.05"),
        (SHEET, _old(**{"R1.04": {**OLD["rows"]["R1.04"], "url": PKG}}), "R1.04"),
        (SHEET, _old(**{"R2.01": {**OLD["rows"]["R1.05"]}}), "R2.01"),
        (SHEET, _without(_old(), "R1.07"), "R1.07"),
        (SHEET, _reorder(_old()), "order"),
        (SHEET, _old(**{"R1.05": {**OLD["rows"]["R1.05"], "given": "QFN-24"}}), "already"),
    ],
    ids=[
        "a-kept-number-the-table-does-not-hold",
        "a-kept-number-whose-sign-the-table-does-not-hold",
        "another-quantity",
        "another-address",
        "a-row-the-table-lacks",
        "a-row-the-earlier-sheet-lacks",
        "another-order",
        "an-earlier-sheet-that-already-gives-values",
    ],
)
def test_an_earlier_sheet_the_table_does_not_match_is_refused_and_named(
    table: str, old: bytes, said: str
) -> None:
    with pytest.raises(converter.SheetRefusedError, match=said):
        converter.convert(table, keep=old)


def test_keeping_takes_the_earlier_sheet_s_label_and_refuses_another() -> None:
    assert _kept()["label"] == OLD["label"]
    with pytest.raises(converter.SheetRefusedError, match="label"):
        converter.convert(SHEET, label=LABEL, keep=_old())


def test_the_command_keeps_an_earlier_sheet_s_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table, old = tmp_path / "parts_sheet.md", tmp_path / "old.json"
    table.write_text(SHEET)
    old.write_bytes(_old())
    out = tmp_path / "sources.json"
    assert converter.main([str(table), str(out), "--keep-values-from", str(old)]) == 0
    assert out.read_bytes() == converter.convert(SHEET, keep=_old())
    said = capsys.readouterr().out
    assert "kept 6" in said and "changed 0" in said and "empty 0" in said
    assert converter.main([str(table), str(tmp_path / "x.json")]) != 0  # no label, nothing kept


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s["rows"]["R1.03"].update(value=5.0),
        lambda s: s["rows"]["R1.03"].update(min=2.7),
        lambda s: s["rows"].pop("R1.05"),
        lambda s: s.update(label="another"),
    ],
    ids=["a-changed-number", "a-field-beyond-given-and-note", "a-dropped-row", "another-label"],
)
def test_a_kept_sheet_that_is_not_strictly_additive_is_refused_before_it_is_written(
    change: Any,
) -> None:
    """The last check before writing: whatever built the kept sheet, it adds and never changes."""
    earlier = json.loads(_old())
    kept = json.loads(converter.convert(SHEET, keep=_old()))
    converter._additive(earlier, kept)
    change(kept)
    with pytest.raises(converter.SheetRefusedError, match="not the earlier sheet"):
        converter._additive(earlier, kept)


def test_convert_holds_every_kept_sheet_to_the_additive_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = converter._kept

    def changing(*args: Any) -> dict[str, Any]:
        row = built(*args)
        return {**row, "unit": "mA"} if row["unit"] == "A" else row

    monkeypatch.setattr(converter, "_kept", changing)
    with pytest.raises(converter.SheetRefusedError, match="not the earlier sheet"):
        converter.convert(SHEET, keep=_old())
