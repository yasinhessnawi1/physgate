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
- a line is what a newline ends; a line of prose outside the tables, a line led by a ``#``
  that is no heading among them, is carried as a remark of the sheet or dropped and counted,
  as the command is told; one that holds a pipe or starts with a row id, a code fence, or a
  heading that holds a pipe or a row id, is refused, since a row written there would be
  lost; one that names a row in passing is prose, carried, and refused rather than dropped,
  however its row id is written, unless it is named, alone, by its digest;
- no refusal prints a name it was given or any text of the table but a row's id;
- a number kept from an earlier sheet is read from the table's cell only where the cell
  writes it one way;
- no value, note or remark it writes holds a word that would give the corpus away;
- a column, a line or a cell it does not know how to carry stops it, and nothing is written.

Running it twice gives the same bytes.
"""

from __future__ import annotations

import hashlib
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
    "# Parts sheet\n\n## R1: motor and supply\n\n"
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


# --- What reaches a review holds no telltale word ---------------------------------------------


@pytest.mark.parametrize(
    ("changed", "said"),
    [
        (_row(SHEET, "R1.03", 6, "the answer key says derate"), r"R1\.03.*answer"),
        (_row(SHEET, "R1.05", 2, "QFN-24, see the twin part"), r"R1\.05.*twin"),
        (_row(SHEET, "R1.07", 6, "current injected into the pin"), r"R1\.07.*inject"),
    ],
    ids=["a-note", "a-given-value", "an-inflected-word"],
)
def test_a_value_or_note_that_would_give_the_corpus_away_is_refused_naming_row_and_word(
    changed: str, said: str
) -> None:
    with pytest.raises(converter.SheetRefusedError, match=said):
        converter.convert(changed, label=LABEL)
    with pytest.raises(converter.SheetRefusedError, match=said):
        converter.convert(changed, keep=_old())


# --- Lines outside the tables -----------------------------------------------------------------

PROSE = "Every address read on one day.\n"
WITH_PROSE = SHEET.replace("## R1: motor and supply\n\n", f"## R1: motor and supply\n\n{PROSE}\n")


@pytest.mark.parametrize(
    "line",
    [
        f"R1.08 | voltage | 5 | V | {MOTOR} | {DAY} | — |",
        f"> | R1.08 | voltage | 5 | V | {MOTOR} | {DAY} | — |",
        "R1.08 voltage 5 V",
        "  R1a.02: number of cells 6",
        "- R1.08 voltage 5 V",
        "> R1.08 voltage 5 V",
        "1. R1.08 voltage 5 V",
        "a | b",
    ],
    ids=[
        "a-row-without-its-leading-pipe",
        "a-row-in-a-quote",
        "a-row-id-starting-a-line",
        "an-indented-row-id-starting-a-line",
        "a-row-id-starting-a-bullet",
        "a-row-id-starting-a-quote",
        "a-row-id-starting-a-numbered-item",
        "a-pipe",
    ],
)
def test_a_line_outside_the_tables_that_holds_a_pipe_or_starts_with_a_row_id_is_refused(
    line: str,
) -> None:
    with pytest.raises(converter.SheetRefusedError, match="outside"):
        converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="carry")


@pytest.mark.parametrize(
    "line",
    ["The driver's limit is R1.07 above.", "See R1.03 and R1a.01 for the supply.", "Rated 5 V."],
    ids=["a-row-id-mid-sentence", "two-row-ids-in-passing", "no-row-id"],
)
def test_prose_that_mentions_a_row_in_passing_is_carried(line: str) -> None:
    carried = json.loads(converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="carry"))
    assert carried["remarks"] == [line]


@pytest.mark.parametrize(
    "fence", ["```", "~~~", "  ~~~python"], ids=["backticks", "tildes", "tildes-indented"]
)
def test_a_code_fence_is_refused_since_a_row_inside_it_is_no_table_row(fence: str) -> None:
    fenced = SHEET + f"\n{fence}\n| R1.08 | voltage | 5 | V | {MOTOR} | {DAY} | — |\n{fence}\n"
    with pytest.raises(converter.SheetRefusedError, match="fence"):
        converter.convert(fenced, label=LABEL, prose="carry")


#: Lines that hold a row id, however it is written: in code, emphasis or brackets, in a cell of
#: HTML or a comment, after a word, misspelt, in another case, with a full-width digit, or
#: behind a character that prints as nothing.
ROW_LIKE = [
    f"`R1.08` voltage 5 V {MOTOR}",
    f"**R1.08** voltage 5 V {MOTOR}",
    f"• R1.08 voltage 5 V {MOTOR}",
    f"[R1.08] voltage 5 V {MOTOR}",
    f"Row R1.08: voltage 5 V {MOTOR}",
    "<td>R1.08</td><td>voltage</td><td>5</td>",
    "<!-- R1.08 voltage 5 V -->",
    f"_R1.08_ voltage 5 V {MOTOR}",
    "R1.8 voltage 5 V",
    "r1.08 voltage 5 V",
    "R\uff11.08 voltage 5 V",
    "\u200bR1.08 voltage 5 V",
    "the row R1\u200b.08 at 5 V",
    "R1.08\tvoltage\t5\tV",
    "the part TR1.08 at 5 V",
    "The pack is R1a.01 in passing.",
    "The driver's limit is R1.07 above.",
    "See R1 .08 for the voltage.",
    "See R1. 08 for the voltage.",
    "See R 1.08 for the voltage.",
    "See R1-08 for the voltage.",
    "See R1,08 for the voltage.",
    "See R1_08 for the voltage.",
    "See R1\u00b708 for the voltage.",
    "See R1\u201308 for the voltage.",
    "See R1\u00a0.08 for the voltage.",
    "See R1\u034f.08 for the voltage.",
    "See R1\ufe0f.08 for the voltage.",
    "See R1\u3164.08 for the voltage.",
    "See R1\u0301.08 for the voltage.",
    "See R1\u20dd.08 for the voltage.",
    "See R\u0661.\u0660\u0668 for the voltage.",
    "See row 1.08 for the voltage.",
    "See Row1.08 for the voltage.",
    "See \U0001d411\U0001d7cf.08 for the voltage.",
]
ROW_LIKE_IDS = [
    "in-code",
    "in-emphasis",
    "after-a-bullet-sign",
    "in-brackets",
    "after-a-word",
    "in-an-html-cell",
    "in-an-html-comment",
    "in-underscores",
    "one-digit-after-the-point",
    "lower-case",
    "a-full-width-digit",
    "behind-a-zero-width-space",
    "split-by-a-zero-width-space",
    "tab-separated",
    "inside-a-word",
    "a-lettered-row-in-passing",
    "in-passing",
    "a-space-before-the-point",
    "a-space-after-the-point",
    "a-space-after-the-r",
    "a-hyphen",
    "a-comma",
    "an-underscore",
    "a-middle-dot",
    "an-en-dash",
    "a-no-break-space",
    "a-combining-grapheme-joiner",
    "a-variation-selector",
    "a-hangul-filler",
    "a-combining-accent",
    "an-enclosing-mark",
    "arabic-indic-digits",
    "the-word-row",
    "the-word-row-joined",
    "mathematical-letters",
]
#: Those of them that start with a row id: refused whatever is done with prose.
ROW_LEADS = frozenset({f"**R1.08** voltage 5 V {MOTOR}", "R1.08\tvoltage\t5\tV"})


@pytest.mark.parametrize("line", ROW_LIKE, ids=ROW_LIKE_IDS)
def test_prose_that_holds_a_row_id_anywhere_is_refused_rather_than_dropped(line: str) -> None:
    """Dropped, the line would be counted and gone; a row written in it would be lost."""
    said = r"line \d+: .*row id" + ("" if line in ROW_LEADS else r".*--prose carry")
    with pytest.raises(converter.SheetRefusedError, match=said):
        converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="drop")
    with pytest.raises(converter.SheetRefusedError, match="row id"):
        converter.convert(SHEET + f"\n{line}\n", keep=_old(), prose="drop")


@pytest.mark.parametrize(
    "line",
    [
        "Every address read on one day.",
        "Rated for 1.5 A at 25 °C, per the R1 section.",
        "Rev 2.1 of the datasheet; see section 4.02.",
        "Under 2 - 3 V for 1.02 s, per 0.5 A, after 1, 2 tries.",
        "The arrow 1.02 and the rows 1.02 to 1.05, and R1:02 or R1/02.",
        "See \u04201.08, the Cyrillic look-alike of a P.",
    ],
    ids=[
        "no-number",
        "a-number-after-a-word-ending-in-r",
        "a-version",
        "spaced-numbers-after-words-ending-in-r",
        "words-holding-row-and-separators-not-read",
        "a-cyrillic-er",
    ],
)
def test_prose_that_holds_no_row_id_is_still_dropped_and_counted(line: str) -> None:
    dropped = json.loads(converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="drop"))
    assert "remarks" not in dropped
    assert converter.read_table(SHEET + f"\n{line}\n").prose == (
        (len(SHEET.splitlines()) + 2, line),
    )


#: The lines above that do not start with a row id, after any indent, quote or list marker.
NOT_LEADING = {
    i: line for i, line in zip(ROW_LIKE_IDS, ROW_LIKE, strict=True) if line not in ROW_LEADS
}


@pytest.mark.parametrize("line", NOT_LEADING.values(), ids=NOT_LEADING.keys())
def test_carried_prose_that_holds_a_row_id_is_kept_as_written(line: str) -> None:
    """Carried, nothing is lost: a line that does not start with a row id is kept, as written."""
    carried = json.loads(converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="carry"))
    assert carried["remarks"] == [line]


# --- Dropping, by name, a line of prose that holds a row id ------------------------------------
#
# A sheet whose prose is dropped by decision may name, by digest, the lines of it that hold a row
# id and may go: exactly those, and only while each still is such a line in the table.

#: Two lines of prose that name a row in passing.
NAMING = ("The driver's limit is R1.07 above.", "See `R1.03` for the supply's range.")


def _digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _with(*lines: str) -> str:
    return SHEET + "\n" + "".join(f"{line}\n" for line in lines)


@pytest.mark.parametrize("keep", [False, True], ids=["from-the-table", "keeping-an-earlier-sheet"])
def test_a_named_line_of_prose_that_holds_a_row_id_is_dropped_and_nothing_else_changes(
    keep: bool,  # noqa: FBT001
) -> None:
    text = _with("Every address read on one day.", *NAMING)
    named = [_digest(line) for line in NAMING]
    if keep:
        dropped = converter.convert(text, keep=_old(), prose="drop", drop_named=named)
        assert dropped == converter.convert(SHEET, keep=_old())
    else:
        dropped = converter.convert(text, label=LABEL, prose="drop", drop_named=named)
        assert dropped == converter.convert(SHEET, label=LABEL)


def test_a_line_of_prose_that_holds_a_row_id_and_is_not_named_is_still_refused() -> None:
    with pytest.raises(converter.SheetRefusedError, match=rf"row id.*{_digest(NAMING[1])}"):
        converter.convert(
            _with(*NAMING), label=LABEL, prose="drop", drop_named=[_digest(NAMING[0])]
        )


@pytest.mark.parametrize(
    "named",
    [
        "0" * 64,
        _digest("Every address read on one day."),
        _digest(NAMING[0].lower()),
        _digest(NAMING[0] + " "),
    ],
    ids=["no-line", "a-line-that-holds-no-row-id", "another-case", "a-trailing-space"],
)
def test_a_named_digest_of_no_line_of_prose_that_holds_a_row_id_is_refused(named: str) -> None:
    """A stale or wrong name never passes: it names no line the drop would otherwise refuse."""
    text = _with("Every address read on one day.", *NAMING)
    every = [_digest(line) for line in NAMING]
    with pytest.raises(converter.SheetRefusedError, match="name 3 of 3 matches no line") as no:
        converter.convert(text, label=LABEL, prose="drop", drop_named=[*every, named])
    assert named not in str(no.value)


def test_a_line_is_named_by_its_bytes_as_written() -> None:
    """Spaces after the words are the line's: named without them, it is not that line."""
    line = NAMING[0] + "  "
    named = converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(line)])
    assert named == converter.convert(SHEET, label=LABEL)
    with pytest.raises(converter.SheetRefusedError, match="row id"):
        converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(NAMING[0])])


@pytest.mark.parametrize("prose", [None, "carry"])
def test_a_line_is_named_for_dropping_only_where_the_prose_is_dropped(prose: str | None) -> None:
    with pytest.raises(converter.SheetRefusedError, match="--prose drop"):
        converter.convert(_with(*NAMING), label=LABEL, prose=prose, drop_named=[_digest(NAMING[0])])


@pytest.mark.parametrize(
    "named",
    ["abc", "g" * 64, "0" * 63, "A" * 64, NAMING[0]],
    ids=["short", "not-hex", "63", "upper-case", "the-line-itself"],
)
def test_a_name_that_is_no_sha256_is_refused_and_not_printed(named: str) -> None:
    every = [_digest(line) for line in NAMING]
    with pytest.raises(converter.SheetRefusedError, match="name 3 of 3 .*not 64") as no:
        converter.convert(_with(*NAMING), label=LABEL, prose="drop", drop_named=[*every, named])
    assert named not in str(no.value)


def test_a_name_that_two_lines_written_alike_share_is_refused() -> None:
    """A name lets one line go: of two lines written alike, it cannot say which."""
    twice = _with(NAMING[0], "Every address read on one day.", NAMING[0])
    with pytest.raises(converter.SheetRefusedError, match="name 1 of 1 matches 2 lines"):
        converter.convert(twice, label=LABEL, prose="drop", drop_named=[_digest(NAMING[0])])


def test_a_name_given_twice_is_refused() -> None:
    named = [_digest(NAMING[0]), _digest(NAMING[1]), _digest(NAMING[0])]
    with pytest.raises(converter.SheetRefusedError, match="name 3 of 3 is name 1 given again"):
        converter.convert(_with(*NAMING), label=LABEL, prose="drop", drop_named=named)


@pytest.mark.parametrize(
    "line",
    ["R1.08 | voltage | 5 | V", "### R1.08 voltage 5 V", "- R1.08 voltage 5 V"],
    ids=["a-row-without-its-leading-pipe", "a-heading", "a-row-in-a-list"],
)
def test_naming_a_line_never_lets_a_row_or_a_heading_be_dropped(line: str) -> None:
    with pytest.raises(converter.SheetRefusedError, match=r"line \d+"):
        converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(line)])


def test_the_command_drops_the_lines_it_is_told_to_by_digest_and_says_how_many(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table, out = tmp_path / "parts_sheet.md", tmp_path / "sources.json"
    table.write_text(_with("Every address read on one day.", *NAMING))
    named = [arg for line in NAMING for arg in ("--drop-prose-line-sha256", _digest(line))]
    argv = [str(table), str(out), "--label", LABEL, "--prose", "drop", *named]
    assert converter.main(argv) == 0
    assert out.read_bytes() == converter.convert(SHEET, label=LABEL)
    said = capsys.readouterr().out.split()
    assert said[said.index("prose-dropped") + 1] == "3"
    assert said[said.index("named-dropped") + 1] == "2"  # lines, each named alone
    assert converter.main([*argv[:1], str(tmp_path / "x.json"), *argv[2:-2]]) == 1
    assert "row id" in capsys.readouterr().err


@pytest.mark.parametrize(
    "heading",
    [
        "### R1.08 | voltage | 5 | V",
        "## Motor | supply",
        "## Rows R1.01 to R1.07",
        "## r1.2: the motor",
        "### \u200bR1.08",
    ],
    ids=["a-row-as-a-heading", "a-pipe", "a-row-id", "a-misspelt-row-id", "a-hidden-row-id"],
)
@pytest.mark.parametrize("prose", [None, "carry", "drop"])
def test_a_heading_that_holds_a_pipe_or_a_row_id_is_refused(
    heading: str, prose: str | None
) -> None:
    """A heading is never carried, so a row written in one would be lost, counted or not."""
    with pytest.raises(converter.SheetRefusedError, match=r"line \d+: a heading"):
        converter.convert(SHEET + f"\n{heading}\n", label=LABEL, prose=prose)


def test_a_heading_that_names_a_section_is_still_the_table_s_structure() -> None:
    sections = SHEET.replace("## R1a: pack", "## R1a: pack, 6 cells (see section 4.2)")
    assert converter.convert(sections, label=LABEL) != b""
    assert converter.read_table(sections).prose == ()


@pytest.mark.parametrize(
    "line", ["\u200b", "\ufeff", " \u200d\u2060 "], ids=["zero-width-space", "bom", "joiners"]
)
def test_a_line_of_characters_that_print_as_nothing_is_no_prose(line: str) -> None:
    assert converter.read_table(SHEET + f"\n{line}\n").prose == ()
    assert "remarks" not in json.loads(
        converter.convert(SHEET + f"\n{line}\n", label=LABEL, prose="carry")
    )


def test_prose_must_be_carried_or_dropped_by_name() -> None:
    with pytest.raises(converter.SheetRefusedError, match="prose"):
        converter.convert(WITH_PROSE, label=LABEL)
    carried = json.loads(converter.convert(WITH_PROSE, label=LABEL, prose="carry"))
    assert carried["remarks"] == [PROSE.rstrip("\n")]
    dropped = json.loads(converter.convert(WITH_PROSE, label=LABEL, prose="drop"))
    assert "remarks" not in dropped and dropped["rows"] == carried["rows"]
    assert "remarks" not in json.loads(converter.convert(SHEET, label=LABEL, prose="carry"))


def test_carried_prose_is_held_to_the_telltale_words_and_named_by_line() -> None:
    telling = WITH_PROSE.replace(PROSE, "The planted part is marked.\n")
    with pytest.raises(converter.SheetRefusedError, match=r"line \d+.*planted"):
        converter.convert(telling, label=LABEL, prose="carry")
    assert "remarks" not in json.loads(converter.convert(telling, label=LABEL, prose="drop"))


def test_keeping_carries_prose_as_an_addition_and_stays_additive() -> None:
    kept = json.loads(converter.convert(WITH_PROSE, keep=_old(), prose="carry"))
    assert kept["remarks"] == [PROSE.rstrip("\n")]
    converter._additive(json.loads(_old()), kept)
    with pytest.raises(converter.SheetRefusedError, match="already"):
        converter.convert(WITH_PROSE, keep=_old_with(remarks=["an earlier remark"]), prose="carry")


def test_the_command_says_how_prose_was_handled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = tmp_path / "parts_sheet.md"
    table.write_text(WITH_PROSE)
    assert converter.main([str(table), str(tmp_path / "a.json"), "--label", LABEL]) != 0
    assert not (tmp_path / "a.json").exists()
    assert (
        converter.main([str(table), str(tmp_path / "b.json"), "--label", LABEL, "--prose", "drop"])
        == 0
    )
    assert "prose-dropped 1" in capsys.readouterr().out
    assert (
        converter.main([str(table), str(tmp_path / "c.json"), "--label", LABEL, "--prose", "carry"])
        == 0
    )
    assert "prose-carried 1" in capsys.readouterr().out


# --- A kept number is read from the cell only where it reads one way ---------------------------


def _one(value: str, unit: str, note: str = "—") -> str:
    return HEADER + f"| R1.01 | current | {value} | {unit} | {MOTOR} | {DAY} | {note} |\n"


def _one_old(value: float | None, unit: str | None) -> bytes:
    row = {"quantity": "current", "value": value, "unit": unit, "url": MOTOR}
    return json.dumps({"label": "L", "rows": {"R1.01": row}}).encode()


@pytest.mark.parametrize(
    ("cell", "unit", "kept"),
    [
        ("1,500", "mA", 500),
        ("1,500", "mA", 1),
        ("1.5 × 10^3", "Hz", 1.5),
        ("100k", "ohm", 100),
        ("-40 to 85", "degC", 40),
        ("4.5-5.5", "V", -5.5),
        ("4.5-5.5", "V", 4.5),
        ("1/2", "A", 1),
        ("1.5e3", "A", 1.5),
        ("1.5e3", "A", 3),
        ("QFN-24", "dimensionless", 24),
        ("QFN-24", "dimensionless", -24),
        ("10³", "Hz", 10),
        ("–40 to 85", "degC", 40),
        ("–40 to 85", "degC", -40),
        ("- 5", "V", 5),
    ],
    ids=[
        "a-thousands-separator-right",
        "a-thousands-separator-left",
        "a-power-of-ten",
        "an-si-suffix",
        "a-sign-dropped",
        "a-hyphen-read-as-a-minus",
        "a-hyphenated-range",
        "a-fraction",
        "an-exponent-s-mantissa",
        "an-exponent-s-power",
        "a-number-inside-a-name",
        "a-number-inside-a-name-read-as-negative",
        "a-superscript-power",
        "a-dash-that-may-be-a-minus-read-plus",
        "a-dash-that-may-be-a-minus-read-minus",
        "a-minus-set-apart",
    ],
)
def test_a_kept_number_the_cell_does_not_write_one_way_is_refused(
    cell: str, unit: str, kept: float
) -> None:
    with pytest.raises(converter.SheetRefusedError, match="R1.01"):
        converter.convert(_one(cell, unit), keep=_one_old(kept, unit))


@pytest.mark.parametrize(
    ("cell", "unit", "kept"),
    [
        ("1.5e3", "A", 1500),
        ("-40 to 85", "degC", -40),
        ("-40 to 85", "degC", 85),
        ("2.7–5.5", "V", 5.5),
        ("12.5, 26, 52, 104", "Hz", 26),
        ("5V", "V", 5),
        ("±0.5", "V", 0.5),
        ("up to 2", "A", 2),
    ],
    ids=[
        "an-exponent-read-whole",
        "a-negative-bound",
        "the-other-bound",
        "an-en-dash-range",
        "a-list",
        "a-unit-written-on-the-number",
        "a-plus-or-minus",
        "a-qualified-number",
    ],
)
def test_a_kept_number_the_cell_writes_one_way_is_kept(cell: str, unit: str, kept: float) -> None:
    row = json.loads(converter.convert(_one(cell, unit), keep=_one_old(kept, unit)))["rows"]
    assert row["R1.01"]["value"] == kept and row["R1.01"]["given"] == f"{cell} {unit}"


@pytest.mark.parametrize(
    ("cell", "unit", "kept", "said"),
    [
        ("1 500", "mA", 500, "thousands"),
        ("1 500", "mA", 1, "thousands"),
        ("1 500.5", "mA", 500.5, "thousands"),
        ("1\u2009500", "mA", 500, "thousands"),
        ("1\u202f500", "mA", 1, "thousands"),
        ("1\u00a0500", "mA", 500, "thousands"),
        ("100 k", "ohm", 100, "prefix"),
        ("4.7 M", "ohm", 4.7, "prefix"),
        ("1.5 thousand", "Hz", 1.5, "prefix"),
        ("2 Million", "Hz", 2, "prefix"),
        ("2 x 1.5", "V", 2, "product"),
        ("2 x 1.5", "V", 1.5, "product"),
        ("2*1.5", "V", 2, "product"),
        ("3 · 2", "V", 2, "product"),
        ("1:2", "dimensionless", 1, "ratio"),
        ("1:2", "dimensionless", 2, "ratio"),
        ("30:1", "dimensionless", 1, "ratio"),
        ("about 30:1", "dimensionless", 30, "ratio"),
        ("30:1, 50:1", "dimensionless", 30, "ratio"),
        ("30:2", "dimensionless", 30, "ratio"),
        ("QFN24", "dimensionless", 24, "name"),
        ("1/2", "A", 2, "fraction"),
        ("10\u207b\u00b3", "A", 10, "power of ten"),
        ("1.5 x 10", "Hz", 1.5, "power of ten"),
        ("10**3", "Hz", 10, "power of ten"),
        ("1.2.3", "dimensionless", 0.3, "not among"),
        ("\u201440 to 85", "degC", 40, "dash"),
        ("4.5\u22125.5", "V", 4.5, "hyphenated"),
        ("2 mA", "A", 2, "unit"),
        ("100 kHz", "Hz", 100, "unit"),
        ("2 min", "s", 2, "unit"),
    ],
    ids=[
        "a-plain-space-thousands-right",
        "a-plain-space-thousands-left",
        "a-plain-space-thousands-before-a-fraction",
        "a-thin-space-thousands",
        "a-narrow-no-break-space-thousands",
        "a-no-break-space-thousands",
        "a-spaced-si-prefix",
        "a-spaced-capital-si-prefix",
        "a-word-multiplier",
        "a-capitalised-word-multiplier",
        "a-spaced-product-left",
        "a-spaced-product-right",
        "a-product-with-a-star",
        "a-product-with-a-dot",
        "a-ratio-left",
        "a-ratio-right",
        "a-whole-cell-ratio-read-for-its-one",
        "a-ratio-with-a-word",
        "two-ratios",
        "a-whole-cell-ratio-to-another-number",
        "a-number-after-a-name",
        "a-fraction-s-denominator",
        "a-superscript-minus",
        "times-ten",
        "a-double-star-power",
        "a-number-inside-a-dotted-version",
        "an-em-dash-that-may-be-a-minus",
        "a-range-with-a-true-minus",
        "a-spaced-unit-of-another-scale",
        "a-spaced-prefixed-unit-of-another-scale",
        "a-spaced-unit-of-the-same-dimension",
    ],
)
def test_a_kept_number_in_a_spelling_that_reads_two_ways_is_refused_with_the_reason(
    cell: str, unit: str, kept: float, said: str
) -> None:
    with pytest.raises(converter.SheetRefusedError, match=rf"R1\.01.*{said}"):
        converter.convert(_one(cell, unit), keep=_one_old(kept, unit))


@pytest.mark.parametrize(
    ("cell", "unit", "kept"),
    [
        ("30:1", "dimensionless", 30),
        ("30 : 1", "dimensionless", 30),
        ("3.5:1", "dimensionless", 3.5),
        ("100 mA", "mA", 100),
        ("100 m", "m", 100),
        ("12.5 26 52", "Hz", 26),
        ("1 5000", "mA", 5000),
        ("2 typ", "A", 2),
        ("max 2", "A", 2),
        ("2 x AA", "dimensionless", 2),
        ("\u22125", "V", -5),
        ("\u00b10.5", "V", -0.5),
        ("10%\u201390%", "%", 90),
        ("20\u00b0\u201380\u00b0", "degC", 80),
        ("max: 2", "A", 2),
        ("3.3: typ", "V", 3.3),
        ("2 min", "A", 2),
    ],
    ids=[
        "a-whole-cell-ratio-to-one",
        "a-spaced-whole-cell-ratio-to-one",
        "a-fractional-whole-cell-ratio-to-one",
        "a-spaced-unit",
        "a-spaced-unit-that-is-also-a-prefix",
        "a-list-written-with-spaces",
        "a-spaced-group-of-four-digits-is-no-thousands",
        "a-spaced-word-that-multiplies-nothing",
        "a-word-ending-in-x-before-it",
        "a-letter-x-before-no-number",
        "a-true-minus",
        "a-plus-or-minus-read-minus",
        "a-percent-range",
        "a-degree-range",
        "a-label-and-a-colon-before-it",
        "a-colon-after-it-before-a-word",
        "a-spaced-word-that-reads-as-a-unit-of-another-dimension",
    ],
)
def test_a_kept_number_in_a_spelling_that_reads_one_way_is_kept(
    cell: str, unit: str, kept: float
) -> None:
    row = json.loads(converter.convert(_one(cell, unit), keep=_one_old(kept, unit)))["rows"]
    assert row["R1.01"]["value"] == kept and row["R1.01"]["given"] == f"{cell} {unit}"


def test_a_cell_of_characters_that_print_as_nothing_is_empty() -> None:
    assert "note" not in _rows(_row(SHEET, "R1.02", 6, "\u200b\ufeff |"))["R1.02"]
    with pytest.raises(converter.SheetRefusedError, match="no value"):
        converter.convert(_row(SHEET, "R1.03", 2, "\u200b"), label=LABEL)


# --- A kept number keeps its unit's dimension and scale ----------------------------------------


@pytest.mark.parametrize(
    ("unit", "kept_unit"),
    [("mA", "A"), ("V", "A"), ("kHz", "Hz")],
    ids=["another-scale", "another-dimension", "another-prefix"],
)
def test_a_cell_unit_the_gate_reads_as_another_quantity_is_refused(
    unit: str, kept_unit: str
) -> None:
    with pytest.raises(converter.SheetRefusedError, match=r"R1\.01.*unit"):
        converter.convert(_one("2", unit), keep=_one_old(2, kept_unit))


@pytest.mark.parametrize(
    ("unit", "kept_unit"),
    [("LSB/g", "dimensionless"), ("ampere", "A")],
    ids=["a-unit-the-gate-cannot-read", "the-same-unit-spelt-otherwise"],
)
def test_a_cell_unit_unreadable_or_the_same_passes_and_is_given(unit: str, kept_unit: str) -> None:
    row = json.loads(converter.convert(_one("2", unit), keep=_one_old(2, kept_unit)))["rows"]
    assert row["R1.01"]["unit"] == kept_unit and row["R1.01"]["given"] == f"2 {unit}"


# --- An earlier sheet is read once, every key once ---------------------------------------------


def _old_with(**top: Any) -> bytes:
    return json.dumps({**json.loads(_old()), **top}).encode()


_ROW_15 = f'{{"quantity": "current", "value": 1.5, "unit": "A", "url": "{MOTOR}"}}'
_ROW_2 = f'{{"quantity": "current", "value": 2, "unit": "A", "url": "{MOTOR}"}}'
_FIELD_TWICE = f'{{"quantity": "current", "value": 1.5, "value": 2, "unit": "A", "url": "{MOTOR}"}}'


@pytest.mark.parametrize(
    ("old", "said"),
    [
        (f'{{"label": "L", "rows": {{"R1.01": {_ROW_15}, "R1.01": {_ROW_2}}}}}', "R1.01"),
        (f'{{"label": "L", "rows": {{"R1.01": {_FIELD_TWICE}}}}}', "value"),
    ],
    ids=["a-row-id-twice", "a-field-twice"],
)
def test_an_earlier_sheet_that_writes_a_key_twice_is_refused(old: str, said: str) -> None:
    json.loads(old)  # plain JSON reading takes the last of the two, silently
    with pytest.raises(converter.SheetRefusedError, match=f"twice.*{said}|{said}.*twice"):
        converter.convert(_one("1.5–2", "A"), keep=old.encode())


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s["rows"]["R1.03"].update(quantity="supply voltage"),
        lambda s: s["rows"]["R1.03"].update(url=PKG),
        lambda s: s.update(extra=["x"]),
    ],
    ids=["another-quantity", "another-address", "a-top-level-field-beyond-remarks"],
)
def test_the_additive_check_compares_quantity_address_and_the_sheet_s_own_fields(
    change: Any,
) -> None:
    earlier = json.loads(_old())
    kept = json.loads(converter.convert(SHEET, keep=_old()))
    change(kept)
    with pytest.raises(converter.SheetRefusedError, match="not the earlier sheet"):
        converter._additive(earlier, kept)


# --- No refusal prints a name or the text of the table ------------------------------------------
#
# A blind conversion may be scripted by an agent that is never to read the corpus. A refusal
# names a line by its number (and a line that may be named, by its digest), a row by its id, a
# telltale by the list's own word, and a name by its place among those given: never a name,
# and never any other text of the table.

#: A word no refusal may print: written into what each refusal is about, or passed as a name.
WORD = "Quokkazanzibar"
#: A line of prose that names a row, holding the word.
SAYING = f"The {WORD} limit is R1.07 above."


def _keeping(**rows: dict[str, Any]) -> list[str]:
    return ["--keep-values-from", _old(**rows).decode()]


#: Each refusal, as the command is run: the table, and its arguments after the two paths.
REFUSALS: dict[str, tuple[str, list[str]]] = {
    "an-unnamed-line-that-holds-a-row-id": (_with(SAYING), ["--prose", "drop"]),
    "the-line-passed-as-its-own-name": (
        _with(SAYING),
        ["--prose", "drop", "--drop-prose-line-sha256", SAYING],
    ),
    "a-line-with-no-row-id-passed-as-a-name": (
        _with(SAYING, f"The {WORD} part."),
        ["--prose", "drop", "--drop-prose-line-sha256", f"The {WORD} part."],
    ),
    "a-stale-name": (
        _with(SAYING),
        [
            "--prose",
            "drop",
            "--drop-prose-line-sha256",
            _digest(SAYING),
            "--drop-prose-line-sha256",
            _digest(SAYING + " "),
        ],
    ),
    "a-name-given-twice": (
        _with(SAYING),
        ["--prose", "drop", *(["--drop-prose-line-sha256", _digest(SAYING)] * 2)],
    ),
    "a-name-two-lines-share": (
        _with(SAYING, SAYING),
        ["--prose", "drop", "--drop-prose-line-sha256", _digest(SAYING)],
    ),
    "a-name-where-the-prose-is-carried": (
        _with(SAYING),
        ["--prose", "carry", "--drop-prose-line-sha256", _digest(SAYING)],
    ),
    "prose-told-nothing": (_with(SAYING), []),
    "a-heading-that-holds-a-row-id": (_with(f"## {WORD} R1.08"), ["--prose", "drop"]),
    "a-heading-that-holds-a-pipe": (_with(f"## {WORD} | b"), ["--prose", "drop"]),
    "a-row-without-its-leading-pipe": (_with(f"R1.08 | {WORD} | 5 | V"), ["--prose", "drop"]),
    "a-line-that-holds-a-pipe": (_with(f"{WORD} | b"), ["--prose", "carry"]),
    "a-code-fence": (_with(f"```{WORD}", "```"), ["--prose", "carry"]),
    "a-carriage-return-in-a-line": (_with(f"{WORD}\rR1.07"), ["--prose", "carry"]),
    "a-telltale-in-carried-prose": (_with(f"The planted {WORD} part."), ["--prose", "carry"]),
    "a-telltale-in-a-note": (_row(SHEET, "R1.03", 6, f"the {WORD} answer"), []),
    "a-table-line-that-is-no-row": (SHEET + f"| {WORD} | b |\n", []),
    "a-row-with-no-quantity": (_row(_row(SHEET, "R1.03", 1, "-"), "R1.03", 6, WORD), []),
    "a-source-that-is-no-address": (_row(SHEET, "R1.03", 4, f"the {WORD} datasheet"), []),
    "an-earlier-sheet-that-is-no-parts-sheet": (
        SHEET,
        _keeping(**{"R1.03": {**OLD["rows"]["R1.03"], "value": WORD}}),
    ),
    "a-kept-number-the-cell-does-not-write": (
        _row(SHEET, "R1.03", 2, f"2.7–5.5 {WORD}"),
        _keeping(**{"R1.03": {**OLD["rows"]["R1.03"], "value": 4.0}}),
    ),
}


@pytest.mark.parametrize(("table", "args"), REFUSALS.values(), ids=REFUSALS.keys())
def test_no_refusal_prints_a_name_or_the_text_of_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], table: str, args: list[str]
) -> None:
    path, out = tmp_path / "parts_sheet.md", tmp_path / "sources.json"
    path.write_bytes(table.encode("utf-8"))
    if args[:1] == ["--keep-values-from"]:
        (tmp_path / "old.json").write_text(args[1])
        args = ["--keep-values-from", str(tmp_path / "old.json"), *args[2:]]
    else:
        args = ["--label", LABEL, *args]
    assert converter.main([str(path), str(out), *args]) == 1
    assert not out.exists()
    said = capsys.readouterr()
    printed = (said.out + said.err).casefold()
    assert "refused" in printed
    assert WORD.casefold() not in printed
    names = [args[i + 1] for i, a in enumerate(args) if a == "--drop-prose-line-sha256"]
    assert not [n for n in names if n.casefold() in printed], "a name given was printed"


def test_a_cell_s_unit_is_not_printed_where_it_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(converter.SheetRefusedError, match=r"R1\.01.*unit") as refused:
        converter.convert(_one("2", "kHz"), keep=_one_old(2, "Hz"))
    assert "kHz" not in str(refused.value)


# --- A line is what a newline ends ------------------------------------------------------------


@pytest.mark.parametrize(
    "inside",
    ["\u2028", "\u2029", "\x0c", "\x0b", "\x85", "\x1c"],
    ids=["line-separator", "paragraph-separator", "form-feed", "vertical-tab", "nel", "fs"],
)
def test_a_line_is_named_whole_whatever_other_line_break_it_holds(inside: str) -> None:
    line = f"The driver's limit is R1.07{inside}above."
    whole = converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(line)])
    assert whole == converter.convert(SHEET, label=LABEL)
    first = line.split(inside)[0]
    with pytest.raises(converter.SheetRefusedError, match="row id"):
        converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(first)])
    carried = json.loads(converter.convert(_with(line), label=LABEL, prose="carry"))
    assert carried["remarks"] == [line]


def test_a_row_after_another_line_break_is_no_row_but_a_line_that_holds_a_pipe() -> None:
    hidden = f"A remark\u2028| R1.08 | voltage | 5 | V | {MOTOR} | {DAY} | — |"
    with pytest.raises(converter.SheetRefusedError, match="outside the tables holds a pipe"):
        converter.convert(_with(hidden), label=LABEL, prose="carry")


def test_a_table_whose_lines_end_in_a_carriage_return_and_a_newline_reads_as_one_with_newlines(
    tmp_path: Path,
) -> None:
    text = _with("Every address read on one day.", *NAMING)
    named = [_digest(line) for line in NAMING]
    crlf = text.replace("\n", "\r\n")
    for prose in ("carry", "drop"):
        drop = named if prose == "drop" else []
        assert converter.convert(crlf, label=LABEL, prose=prose, drop_named=drop) == (
            converter.convert(text, label=LABEL, prose=prose, drop_named=drop)
        )
    table, out = tmp_path / "parts_sheet.md", tmp_path / "sources.json"
    table.write_bytes(crlf.encode())
    names = [a for d in named for a in ("--drop-prose-line-sha256", d)]
    assert converter.main([str(table), str(out), "--label", LABEL, "--prose", "drop", *names]) == 0
    assert out.read_bytes() == converter.convert(text, label=LABEL, prose="drop", drop_named=named)


@pytest.mark.parametrize(
    "line",
    ["Every address\rread on one day.", "Every address read on one day.\r\r"],
    ids=["inside-a-line", "two-before-the-newline"],
)
def test_a_carriage_return_that_ends_no_line_is_refused(line: str) -> None:
    with pytest.raises(converter.SheetRefusedError, match=r"line \d+ holds a carriage return"):
        converter.convert(_with(line), label=LABEL, prose="carry")


def test_the_command_reads_the_table_s_bytes_and_translates_no_line_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Read as text with newlines translated, a lone carriage return would end a line."""
    table, out = tmp_path / "parts_sheet.md", tmp_path / "sources.json"
    table.write_bytes(_with("Every address\rread on one day.").encode())
    assert converter.main([str(table), str(out), "--label", LABEL, "--prose", "carry"]) == 1
    assert "carriage return" in capsys.readouterr().err
    table.write_bytes(b"\xff" + SHEET.encode())
    assert converter.main([str(table), str(out), "--label", LABEL]) == 1
    assert "not UTF-8" in capsys.readouterr().err
    assert not out.exists()


# --- A line led by a # that is no heading is prose ------------------------------------------------

#: Lines led by a ``#`` that CommonMark reads as a paragraph's, not a heading.
NOT_HEADINGS = ["#tag and a remark", "####### seven of them", "    # four spaces before it"]


@pytest.mark.parametrize("line", NOT_HEADINGS, ids=["no-space", "seven", "indented-four"])
def test_a_line_led_by_a_hash_that_is_no_heading_is_prose_carried_or_counted(
    line: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert converter.read_table(_with(line)).prose == ((len(SHEET.splitlines()) + 2, line),)
    carried = json.loads(converter.convert(_with(line), label=LABEL, prose="carry"))
    assert carried["remarks"] == [line]
    table = tmp_path / "parts_sheet.md"
    table.write_text(_with(line))
    argv = [str(table), str(tmp_path / "s.json"), "--label", LABEL, "--prose", "drop"]
    assert converter.main(argv) == 0
    assert "prose-dropped 1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "lead", ["#tag", "#######", "    #"], ids=["no-space", "seven", "indented"]
)
def test_a_line_led_by_a_hash_that_is_no_heading_and_holds_a_row_id_is_not_dropped_unnamed(
    lead: str,
) -> None:
    line = f"{lead} The driver's limit is R1.07 above."
    with pytest.raises(converter.SheetRefusedError, match=r"line \d+: a line of prose holds a row"):
        converter.convert(_with(line), label=LABEL, prose="drop")
    named = converter.convert(_with(line), label=LABEL, prose="drop", drop_named=[_digest(line)])
    assert named == converter.convert(SHEET, label=LABEL)


@pytest.mark.parametrize(
    "heading",
    ["# Parts", "   ### Indented three", "######", "##\tTabbed", "## "],
    ids=["one", "indented-three", "six-alone", "a-tab", "empty"],
)
def test_a_heading_is_the_table_s_structure_and_is_neither_carried_nor_counted(
    heading: str,
) -> None:
    assert converter.read_table(_with(heading)).prose == ()
    assert "remarks" not in json.loads(
        converter.convert(_with(heading), label=LABEL, prose="carry")
    )
