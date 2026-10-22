r"""A corpus's parts sheet (``sources.json``) written from its authors' table, every cell kept.

The authors of a corpus write against ``parts_sheet.md``: Markdown tables with the columns
Row, Quantity, Value, Unit, Source URL, Retrieved and Note. A review is given
``sources.json``. This writes the second from the first, and refuses rather than drop a cell:

- a value cell that is one bare number, with a unit cell the gate's unit registry reads,
  becomes the row's ``value`` and ``unit``, the number a derived source may cite;
- every other value cell is kept under ``given``, as written, with its unit cell unless that
  is a dash. A number whose spelling the number does not keep (``1.50``, ``+5``) is kept
  there too, beside its ``value``;
- a note other than a dash becomes the row's ``note``, as written;
- a source cell is an address, or a reference of the form ``same URL``, ``same driver URL``
  or ``same driver URL as above``, which is the address of the nearest row above it;
- the Retrieved column must hold one date for every row, because a row has no field for it.

**Lines outside the tables.** A heading is the table's structure and is not carried. A line
that holds a pipe or a row id is refused: a row written there, without its leading pipe or
inside a quote, would otherwise be lost. A code fence is refused, since a table written inside
one is no table. Every other line is prose, and the command is told what to do with it by
name: ``--prose carry`` writes each line, as written, to the sheet's ``remarks``; ``--prose
drop`` leaves them out and counts them. A text with prose and neither is refused.

**What a review is given holds no telltale word.** Every ``given``, ``note`` and remark the
converter writes is held to the corpus's telltale words, the same list the instrument holds a
review's packet to; one that holds such a word is refused, by its row or line and the word.

**Keeping an earlier sheet's numbers** (``--keep-values-from``). A corpus whose design was
written against an earlier sheet cites that sheet's numbers, some picked by hand from a range
or a list, which the table alone does not make citable. Given that sheet, the converter keeps
every field of it byte for byte, its label included, and adds only what it lacked:

- a row the earlier sheet gave a number keeps that ``value`` and ``unit``; ``given`` is added
  unless the table writes exactly that number in that unit, and the note;
- a row it left without a number gains ``given`` and the note;
- carried prose becomes the sheet's ``remarks``.

It refuses, naming the row, when the two disagree: another set or order of rows, another
quantity or address; a kept number that the table's value cell does not write, or writes in
a way that reads more than one way (inside a thousands separator, with a prefix or a word on
it, in a power of ten, a fraction or a hyphenated range, or with the other sign); a unit cell
the gate reads as another dimension or scale than the kept unit (a unit it cannot read passes,
and is given); an earlier sheet that already gives values, notes or remarks; or one that
writes any key twice, which plain JSON reading would settle silently by keeping the last.

A table whose columns are not those seven, a table line that is not a header, separator or
row, a row with another number of cells, an empty value or quantity, a row id given twice or
a source it cannot follow, stops it with the reason; nothing is written. The sheet is written
indented by one, keys in a fixed order, one newline at the end, so the same table gives the
same bytes. An existing output file is never written over.

Usage::

    uv run python scripts/parts_sheet_sources.py <parts_sheet.md> <sources.json> --label TEXT \
        [--prose carry|drop]
    uv run python scripts/parts_sheet_sources.py <parts_sheet.md> <sources.json> \
        --keep-values-from <earlier sources.json> [--prose carry|drop]

It prints counts only: rows, rows with a number, rows with a given value, rows with neither
(always 0), notes, followed references and prose lines carried or dropped; when keeping, the
numbers kept and the rows whose earlier fields changed (always 0).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physgate.evaluation.inject.corpus import Sources, telltales
from physgate.gate.units import UnitRefusedError, parse

#: The table's columns, in order, as the authors' sheet heads them (case aside).
COLUMNS = ("row", "quantity", "value", "unit", "source url", "retrieved", "note")
#: A cell that says there is nothing in it.
DASHES = frozenset({"", "-", "—", "–"})
#: What the command may be told to do with prose beside the tables.
PROSE = ("carry", "drop")
_DONE = {"carry": "carried", "drop": "dropped"}
#: The only fields keeping adds to an earlier sheet's row, and to the sheet itself.
ADDED = ("given", "note")
SHEET_ADDED = ("remarks",)
_ROW_ID = re.compile(r"R[0-9]+[a-z]?\.[0-9]{2}")
#: A row id anywhere in a line, as a word of its own.
_ROW_MENTION = re.compile(r"(?<![A-Za-z0-9])R[0-9]+[a-z]?\.[0-9]{2}(?![0-9])")
_FENCE = re.compile(r"\s*(```|~~~)")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WHOLE = re.compile(r"[+-]?[0-9]+")
_SEPARATOR = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?")
_ADDRESS = re.compile(r"https?://\S+")
#: ``same URL``, ``same driver URL``, ``same URL as above``: the address of the row above.
_SAME = re.compile(r"same (?:[a-z]+ )?url(?: as above)?", re.IGNORECASE)
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
#: A number written in a value cell, unsigned; the signs and marks around it are read apart.
_TOKEN = re.compile(r"(?<![0-9.])(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
#: A cell that writes a power of ten as ``× 10^3``, ``10³`` or ``2*10**3``: no number in it
#: is the number it reads as.
_POWER = re.compile(r"[×^⁰¹²³⁴⁵⁶⁷⁸⁹⁻]|[0-9]\s*[x*·]\s*10\b|\*\*")
_MINUS = "-−"
#: An en or em dash: between two numbers, a range; before one, perhaps a minus.
_DASH = "–—"
#: A comma, a point or a narrow space between digits: a thousands separator.
_GROUPING = ",.   "
_LETTERS = re.compile(r"[^\W\d_]+")
_HYPHEN_AFTER = re.compile(r"\s*[-−]\s*[0-9.]")


class SheetRefusedError(ValueError):
    """The table holds something the sheet cannot carry whole."""


@dataclass(frozen=True)
class Table:
    """The authors' table as read: its rows, their cells, and the prose beside it."""

    #: Every row, as the table alone gives it, in the table's order.
    rows: dict[str, dict[str, object]]
    #: Every row's seven cells, as written.
    cells: dict[str, list[str]]
    #: Every line of prose, with its line number, as written.
    prose: tuple[tuple[int, str], ...]
    #: Source cells that refer to the address above.
    references: int


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner.removeprefix("|")
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE.split(inner)]


def _number(cell: str, unit: str) -> float | int | None:
    """The cell's number, when it is one bare number and the gate reads its unit."""
    if _NUMBER.fullmatch(cell) is None or unit in DASHES:
        return None
    number: float | int = int(cell) if _WHOLE.fullmatch(cell) else float(cell)
    try:
        parse(number, unit)
    except UnitRefusedError:
        return None
    return number


def _url(row_id: str, source: str, address: str | None) -> str:
    if _ADDRESS.fullmatch(source):
        return source
    if _SAME.fullmatch(source) and address is not None:
        return address
    msg = f"row {row_id} has a source that is no address and no reference it can follow"
    raise SheetRefusedError(msg)


def _written(value: str, unit: str) -> str:
    """A value cell as written, with its unit cell unless that is a dash."""
    return value if unit in DASHES else f"{value} {unit}"


def _row(cells: list[str], address: str | None) -> dict[str, object]:
    row_id, quantity, value, unit, source, _, note = cells
    if quantity in DASHES:
        msg = f"row {row_id} has no quantity"
        raise SheetRefusedError(msg)
    if value in DASHES:
        msg = f"row {row_id} has no value: a cell that holds nothing cannot be given"
        raise SheetRefusedError(msg)
    url = _url(row_id, source, address)
    number = _number(value, unit)
    row: dict[str, object] = {"quantity": quantity, "value": number}
    row["unit"] = unit if number is not None else None
    if number is None or json.dumps(number) != value:
        row["given"] = _written(value, unit)
    row["url"] = url
    if note not in DASHES:
        row["note"] = note
    return row


def read_table(markdown: str) -> Table:
    """The authors' table in ``markdown``, every line accounted for.

    Raises:
        SheetRefusedError: a line or a cell the sheet cannot carry whole.
    """
    rows: dict[str, dict[str, object]] = {}
    cells_of: dict[str, list[str]] = {}
    prose: list[tuple[int, str]] = []
    dates: set[str] = set()
    address: str | None = None
    headed = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        if not line.strip():
            continue
        if _FENCE.match(line):
            msg = f"line {number}: a code fence; a table written inside one is not read as one"
            raise SheetRefusedError(msg)
        if not line.lstrip().startswith("|"):
            if line.lstrip().startswith("#"):
                continue
            if "|" in line or _ROW_MENTION.search(line):
                msg = (
                    f"line {number}: a line outside the tables holds a pipe or a row id, and a "
                    "row written there would be lost"
                )
                raise SheetRefusedError(msg)
            prose.append((number, line))
            continue
        cells = _cells(line)
        if _SEPARATOR.fullmatch(line.strip()):
            if not headed:
                msg = f"line {number}: a table separator with no header above it"
                raise SheetRefusedError(msg)
            continue
        if _ROW_ID.fullmatch(cells[0]) is None:
            if tuple(c.casefold() for c in cells) != COLUMNS:
                msg = f"line {number}: a table line that is neither a row nor the columns {COLUMNS}"
                raise SheetRefusedError(msg)
            headed = True
            continue
        if not headed:
            msg = f"line {number}: a row before any header"
            raise SheetRefusedError(msg)
        if len(cells) != len(COLUMNS):
            msg = f"line {number}: a row has {len(cells)} cells, not {len(COLUMNS)}"
            raise SheetRefusedError(msg)
        if cells[0] in rows:
            msg = f"row {cells[0]} is written twice"
            raise SheetRefusedError(msg)
        rows[cells[0]] = _row(cells, address)
        cells_of[cells[0]] = cells
        address = str(rows[cells[0]]["url"])
        dates.add(cells[5])
    if not rows:
        msg = "the text holds no row of a parts table"
        raise SheetRefusedError(msg)
    if len(dates) != 1 or next(iter(dates)) in DASHES:
        msg = f"the Retrieved column holds {len(dates)} dates; a row has no field for its own"
        raise SheetRefusedError(msg)
    references = sum(_SAME.fullmatch(c[4]) is not None for c in cells_of.values())
    return Table(rows=rows, cells=cells_of, prose=tuple(prose), references=references)


def _reading(
    cell: str, start: int, end: int, units: tuple[str, ...]
) -> tuple[tuple[int, ...], str]:
    """The signs the number at ``cell[start:end]`` is written with, or why it reads two ways.

    Returns the signs (``(1,)``, ``(-1,)``, or both for ``±``) and an empty reason, or no
    signs and the reason the number reads more than one way.
    """
    before, after = cell[:start], cell[end:]
    if (before[-1:] and before[-1] in _GROUPING and before[-2:-1].isdigit()) or (
        after[:1] and after[0] in _GROUPING and after[1:2].isdigit()
    ):
        return (), "written inside a thousands separator"
    suffix = _LETTERS.match(after)
    if suffix and suffix.group(0) not in units:
        return (), "written with a prefix or a word on it, so it may be another number"
    if before[-1:].isalpha():
        return (), "written inside a name"
    if before.rstrip().endswith("/") or after.lstrip().startswith("/"):
        return (), "written in a fraction"
    if _HYPHEN_AFTER.match(after):
        return (), "written in a hyphenated range, which may be a subtraction"
    if before[-1:] and before[-1] in _MINUS:
        left = before[:-1].rstrip()
        if left[-1:].isdigit():
            return (), "written in a hyphenated range, which may be a subtraction"
        if left[-1:].isalpha():
            return (), "written inside a name"
        return (-1,), ""
    if before.rstrip()[-1:] in _MINUS and before.rstrip():
        return (), "written after a minus set apart from it"
    if before[-1:] == "±":
        return (1, -1), ""
    if before.rstrip()[-1:] in _DASH and before.rstrip():
        left = before.rstrip()[:-1].rstrip()
        if not left or not (left[-1].isalnum() or left[-1] in "%°"):
            return (), "written after a dash that may be a minus"
    return (1,), ""


def _unread(cell: str, number: float, units: tuple[str, ...]) -> str:
    """Why ``cell`` does not write ``number`` one way, or an empty string when it does."""
    if _POWER.search(cell):
        return "in a cell that writes a power of ten"
    why = ""
    for found in _TOKEN.finditer(cell):
        read = float(found.group(0))
        if abs(number) != read:
            continue
        signs, reason = _reading(cell, found.start(), found.end(), units)
        if not reason and number in tuple(s * read for s in signs):
            return ""
        why = why or reason or "written there with the other sign"
    return why or "not among the numbers the table's cell writes"


def _other_quantity(cell_unit: str, kept_unit: str) -> str:
    """Why the cell's unit is not the kept unit, when the gate reads both; else empty."""
    if cell_unit == kept_unit or cell_unit in DASHES:
        return ""
    try:
        cell, kept = parse(1, cell_unit), parse(1, kept_unit)
    except UnitRefusedError:
        return ""
    if cell.dimensionality != kept.dimensionality:
        return "of another dimension"
    if not math.isclose(cell.to(kept.units).magnitude, 1.0, rel_tol=1e-12):
        return "of another scale"
    return ""


def _kept(
    row_id: str, cells: list[str], fresh: dict[str, object], before: dict[str, Any]
) -> dict[str, Any]:
    """The earlier sheet's row, every field as it was, with what the table adds to it."""
    value, unit = cells[2], cells[3]
    written = _written(value, unit)
    for field in ("quantity", "url"):
        if fresh[field] != before[field]:
            msg = f"row {row_id}: the table and the earlier sheet give it another {field}"
            raise SheetRefusedError(msg)
    row = dict(before)
    if before["value"] is None:
        row["given"] = written
    else:
        why = _unread(value, before["value"], (unit, str(before["unit"])))
        if why:
            msg = f"row {row_id}: the earlier sheet's number {before['value']} is {why}"
            raise SheetRefusedError(msg)
        other = _other_quantity(unit, str(before["unit"]))
        if other:
            msg = (
                f"row {row_id}: the table's unit {unit!r} is {other} than the earlier "
                f"sheet's unit {before['unit']!r}"
            )
            raise SheetRefusedError(msg)
        if json.dumps(before["value"]) != value or unit != before["unit"]:
            row["given"] = written
    if "note" in fresh:
        row["note"] = fresh["note"]
    return row


def _once(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object whose every key is written once."""
    keys = [k for k, _ in pairs]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        msg = f"the earlier sheet writes {twice} twice in one object"
        raise SheetRefusedError(msg)
    return dict(pairs)


def _earlier(keep: bytes, ids: list[str]) -> dict[str, Any]:
    """The earlier sheet, held to the table's rows.

    Raises:
        SheetRefusedError: it is not a parts sheet, writes a key twice, already gives
            values, notes or remarks, or holds other rows.
    """
    try:
        earlier: dict[str, Any] = json.loads(keep, object_pairs_hook=_once)
        rows: dict[str, dict[str, Any]] = earlier["rows"]
        given = sorted(k for k, r in rows.items() if any(f in r for f in ADDED))
    except SheetRefusedError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        msg = f"the earlier sheet is not a parts sheet: {exc}"
        raise SheetRefusedError(msg) from exc
    if given or any(f in earlier for f in SHEET_ADDED):
        msg = f"the earlier sheet already gives values, notes or remarks, at {given[:5]}"
        raise SheetRefusedError(msg)
    try:
        Sources.model_validate_json(keep)
    except ValueError as exc:
        msg = f"the earlier sheet is not a parts sheet: {exc}"
        raise SheetRefusedError(msg) from exc
    if set(rows) != set(ids):
        odd = sorted(set(rows) ^ set(ids))
        msg = f"the table and the earlier sheet hold other rows: {odd[:10]}"
        raise SheetRefusedError(msg)
    if list(rows) != ids:
        msg = "the table and the earlier sheet hold their rows in another order"
        raise SheetRefusedError(msg)
    return earlier


def _held_blind(where: str, text: str) -> None:
    """Refuse ``text``, written where a review reads it, if it holds a telltale word."""
    found = telltales(text)
    if found:
        msg = f"{where} holds a word that would give the corpus away: {found}"
        raise SheetRefusedError(msg)


def convert(
    markdown: str,
    *,
    label: str | None = None,
    keep: bytes | None = None,
    prose: str | None = None,
) -> bytes:
    """The parts sheet the table in ``markdown`` gives, as the bytes of ``sources.json``.

    With ``keep``, an earlier sheet's bytes, every field of that sheet is kept as it was and
    the table adds only ``given``, ``note`` and carried ``remarks``; the label is the earlier
    sheet's. ``prose`` says what to do with lines of prose beside the tables: ``carry`` or
    ``drop``; a text that has some needs it.

    Raises:
        SheetRefusedError: the table holds something the sheet cannot carry whole; it and
            the earlier sheet disagree; prose is there and ``prose`` does not say what to do
            with it; what would be written holds a telltale word; or no label is given and
            none is kept.
    """
    table = read_table(markdown)
    if prose is not None and prose not in PROSE:
        msg = f"prose is carried or dropped, {PROSE}, not {prose!r}"
        raise SheetRefusedError(msg)
    if table.prose and prose is None:
        msg = (
            f"the text holds {len(table.prose)} lines of prose beside its tables; carry them "
            "as the sheet's remarks or drop them, by name (--prose carry or --prose drop)"
        )
        raise SheetRefusedError(msg)
    sheet: dict[str, Any] = {"label": label, "rows": table.rows}
    earlier: dict[str, Any] | None = None
    if keep is not None:
        earlier = _earlier(keep, list(table.rows))
        if label is not None and label != earlier["label"]:
            msg = "a kept sheet keeps the earlier sheet's label, and another label was given"
            raise SheetRefusedError(msg)
        sheet = {
            "label": earlier["label"],
            "rows": {
                k: _kept(k, table.cells[k], table.rows[k], r) for k, r in earlier["rows"].items()
            },
        }
    elif label is None:
        msg = "a sheet converted from the table alone needs a label"
        raise SheetRefusedError(msg)
    if prose == "carry" and table.prose:
        sheet["remarks"] = [line for _, line in table.prose]
        for number, line in table.prose:
            _held_blind(f"line {number}'s prose", line)
    for row_id, row in sheet["rows"].items():
        for field in ADDED:
            if field in row:
                _held_blind(f"row {row_id}'s {field}", str(row[field]))
    if earlier is not None:
        _additive(earlier, sheet)
    written = (json.dumps(sheet, indent=1, ensure_ascii=False) + "\n").encode()
    Sources.model_validate_json(written)  # the sheet the corpus loader will read
    return written


def _additive(earlier: dict[str, Any], sheet: dict[str, Any]) -> None:
    """Refuse a kept sheet that is not the earlier one with only values, notes and remarks."""
    same = all(json.dumps(sheet.get(f)) == json.dumps(v) for f, v in earlier.items() if f != "rows")
    same = same and set(sheet) - set(earlier) <= set(SHEET_ADDED)
    same = same and list(earlier["rows"]) == list(sheet["rows"])
    for row_id, before in earlier["rows"].items() if same else ():
        after = sheet["rows"][row_id]
        same = same and all(json.dumps(after.get(f)) == json.dumps(v) for f, v in before.items())
        same = same and set(after) - set(before) <= set(ADDED)
    if not same:
        msg = "the kept sheet is not the earlier sheet with values, notes and remarks added"
        raise SheetRefusedError(msg)


def main(argv: list[str] | None = None) -> int:
    """Write the sheet; print counts; 0 when written, 1 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("table", type=Path, help="the authors' parts_sheet.md")
    parser.add_argument("out", type=Path, help="the sources.json to write; must not exist")
    parser.add_argument("--label", help="the sheet's label; when keeping, the earlier sheet's")
    parser.add_argument(
        "--keep-values-from",
        type=Path,
        help="an earlier sources.json whose every field is kept, the table adding to it",
    )
    parser.add_argument(
        "--prose",
        choices=PROSE,
        help="carry the prose beside the tables as the sheet's remarks, or drop it",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    earlier: Path | None = args.keep_values_from
    keep = earlier.read_bytes() if earlier is not None else None
    text = args.table.read_text(encoding="utf-8")
    try:
        written = convert(text, label=args.label, keep=keep, prose=args.prose)
    except SheetRefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    try:
        with out.open("xb") as handle:
            handle.write(written)
    except FileExistsError:
        print(f"refused: {out} exists, and is never written over", file=sys.stderr)
        return 1
    table = read_table(text)
    rows = json.loads(written)["rows"].values()
    print(
        f"rows {len(rows)}"
        f" number {sum(r['value'] is not None for r in rows)}"
        f" given {sum('given' in r for r in rows)}"
        f" given-only {sum(r['value'] is None for r in rows)}"
        f" empty {sum(r['value'] is None and 'given' not in r for r in rows)}"
        f" notes {sum('note' in r for r in rows)}"
        f" references {table.references}"
        + (f" prose-{_DONE[args.prose]} {len(table.prose)}" if table.prose else "")
    )
    if keep is not None:
        before = json.loads(keep)["rows"]
        after = json.loads(written)["rows"]
        changed = sum(
            any(json.dumps(after[k].get(f)) != json.dumps(v) for f, v in r.items())
            for k, r in before.items()
        )
        print(f"kept {sum(r['value'] is not None for r in before.values())} changed {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
