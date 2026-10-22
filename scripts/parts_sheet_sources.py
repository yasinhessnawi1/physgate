"""A corpus's parts sheet (``sources.json``) written from its authors' table, every cell kept.

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

A table whose columns are not those seven, a table line that is not a header, separator or
row, a row with another number of cells, an empty value or quantity, a row id given twice or
a source it cannot follow, stops it with the reason; nothing is written. The sheet is written
indented by one, keys in a fixed order, one newline at the end, so the same table gives the
same bytes. An existing output file is never written over.

Usage::

    uv run python scripts/parts_sheet_sources.py <parts_sheet.md> <sources.json> --label TEXT

It prints counts only: rows, rows with a number, rows with a given value, rows with neither
(always 0), notes and followed references.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from physgate.evaluation.inject.corpus import Sources
from physgate.gate.units import UnitRefusedError, parse

#: The table's columns, in order, as the authors' sheet heads them (case aside).
COLUMNS = ("row", "quantity", "value", "unit", "source url", "retrieved", "note")
#: A cell that says there is nothing in it.
DASHES = frozenset({"", "-", "—", "–"})
_ROW_ID = re.compile(r"R[0-9]+[a-z]?\.[0-9]{2}")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_WHOLE = re.compile(r"[+-]?[0-9]+")
_SEPARATOR = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?")
_ADDRESS = re.compile(r"https?://\S+")
#: ``same URL``, ``same driver URL``, ``same URL as above``: the address of the row above.
_SAME = re.compile(r"same (?:[a-z]+ )?url(?: as above)?", re.IGNORECASE)
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


class SheetRefusedError(ValueError):
    """The table holds something the sheet cannot carry whole."""


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


def _row(cells: list[str], address: str | None) -> dict[str, object]:
    row_id, quantity, value, unit, source, _, note = cells
    if quantity in DASHES:
        msg = f"row {row_id} has no quantity"
        raise SheetRefusedError(msg)
    if value in DASHES:
        msg = f"row {row_id} has no value: a cell that holds nothing cannot be given"
        raise SheetRefusedError(msg)
    if _ADDRESS.fullmatch(source):
        url = source
    elif _SAME.fullmatch(source) and address is not None:
        url = address
    else:
        msg = f"row {row_id} has a source that is no address and no reference it can follow"
        raise SheetRefusedError(msg)
    number = _number(value, unit)
    written = value if unit in DASHES else f"{value} {unit}"
    row: dict[str, object] = {"quantity": quantity, "value": number}
    row["unit"] = unit if number is not None else None
    if number is None or json.dumps(number) != value:
        row["given"] = written
    row["url"] = url
    if note not in DASHES:
        row["note"] = note
    return row


def convert(markdown: str, *, label: str) -> bytes:
    """The parts sheet the table in ``markdown`` gives, as the bytes of ``sources.json``.

    Raises:
        SheetRefusedError: the table holds something the sheet cannot carry whole.
    """
    rows: dict[str, dict[str, object]] = {}
    dates: set[str] = set()
    address: str | None = None
    headed = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        if not line.lstrip().startswith("|"):
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
        address = str(rows[cells[0]]["url"])
        dates.add(cells[5])
    if not rows:
        msg = "the text holds no row of a parts table"
        raise SheetRefusedError(msg)
    if len(dates) != 1 or next(iter(dates)) in DASHES:
        msg = f"the Retrieved column holds {len(dates)} dates; a row has no field for its own"
        raise SheetRefusedError(msg)
    sheet = {"label": label, "rows": rows}
    written = (json.dumps(sheet, indent=1, ensure_ascii=False) + "\n").encode()
    Sources.model_validate_json(written)  # the sheet the corpus loader will read
    return written


def main(argv: list[str] | None = None) -> int:
    """Write the sheet; print counts; 0 when written, 1 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("table", type=Path, help="the authors' parts_sheet.md")
    parser.add_argument("out", type=Path, help="the sources.json to write; must not exist")
    parser.add_argument("--label", required=True, help="the sheet's label")
    args = parser.parse_args(argv)
    out: Path = args.out
    try:
        written = convert(args.table.read_text(encoding="utf-8"), label=args.label)
    except SheetRefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    try:
        with out.open("xb") as handle:
            handle.write(written)
    except FileExistsError:
        print(f"refused: {out} exists, and is never written over", file=sys.stderr)
        return 1
    rows = json.loads(written)["rows"].values()
    references = sum(
        _SAME.fullmatch(_cells(line)[4]) is not None
        for line in args.table.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("|") and len(_cells(line)) == len(COLUMNS)
    )
    print(
        f"rows {len(rows)}"
        f" number {sum(r['value'] is not None for r in rows)}"
        f" given {sum('given' in r for r in rows)}"
        f" given-only {sum(r['value'] is None for r in rows)}"
        f" empty {sum(r['value'] is None and 'given' not in r for r in rows)}"
        f" notes {sum('note' in r for r in rows)}"
        f" references {references}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
