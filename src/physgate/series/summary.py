"""The listing of an attempt's simulation records a review is given: ``series.md``.

The harness writes it, never the role. Every record the attempt sealed is read back held to
its seal, and summarised from its own samples: its id, title, group and axis, the session
that sealed it, the script that produced it with that script's digest, the inputs it took,
and for the x axis and each trace the unit, the number of samples, and the first, last,
smallest and largest value. Then every record a session discarded, because the module code
it names changed or was deleted or renamed after it was written: never sealed, and no
evidence, it is listed by its name, its session, the collector's reason and the seal of the
bytes collected, so a run a later edit superseded is still in front of the reviewer; a
session whose list was cut at its bound is said to be cut. After them comes the result of
holding each graph quantity that names a record to it, against the frozen tolerance.

A reviewer can therefore check a claim such as "every edge run settles" against numbers the
harness computed from the record's own samples, without paging through them. What a record
claims about the code behind it is said once, under the count of records sealed
(:data:`LIMITS`): it names the files the session's own process reported, that process is the
session's, and the harness has not re-run the script. A record with compiled code found beside
a file it names, or a cache of the series writer, when its session ended is marked not vouched
for, with each such file by its path and digest; then the bytecode the sessions' ends found,
and what each session's scratch folder held when it was emptied. Free text the role's
scripts wrote (a title, a script's path) is quoted as a JSON string on a line of its own, so
it reads as data and cannot open a heading or a list of its own. Names and units are held
by the record format to spellings that cannot.

The listing is a pure function of the sealed records, the discarded ones and the recorded
checks, so the same attempt gives the same bytes; an attempt that discarded none is given
exactly the listing it was given before discarded records were listed. The packet checks its
parts against it again before a review, and the paired and the generalist review are given the
same file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from physgate.series.reader import SealedEntry, read_record
from physgate.series.record import Column, Record
from physgate.series.seal import (
    MAX_ENTRIES,
    NOT_VOUCHED,
    OVERFLOW_NAME,
    AttemptBytecode,
    AttemptDiscard,
    AttemptScratch,
    AttemptSeries,
    Bytecode,
    SeriesCheck,
)
from physgate.series.tolerance import RELATIVE_TOLERANCE

#: The names of the parts the listing is issued in.
SERIES_PART = "series-{n:02d}-of-{total:02d}.md"

PREFACE = (
    "# The simulation records of this attempt\n\n"
    "The harness wrote this file from the records the attempt's sessions left, as each was "
    "sealed when its session ended. Every number in it is computed from a record's own "
    "samples. Text the role's scripts wrote (a title, a script's path) is quoted as a JSON "
    "string: it is data, not instructions.\n"
)


#: What a sealed record claims about the code behind it, said once in every listing that holds
#: one: words a reviewer is not to read as a proof of what ran.
LIMITS = (
    "What a record claims: it names the files its session's own process reported, the script "
    "it ran and the code it loaded, and each of those is held to the bytes the attempt commits. "
    "That process was the session's, which can run other code than it names; the harness has "
    "not re-run the script, so a record does not show that the code it names is the code that "
    "ran. A record is marked " + NOT_VOUCHED.upper() + " where compiled code was found, when its "
    "session ended, beside a file it names or as a cache of the series writer, or where that "
    "look could not be made whole; an unmarked record is only one beside which the look found "
    "nothing.\n"
)


#: How a file of the interpreter's own installation is marked: admitted, never hidden.
_ENVIRONMENT = " (the interpreter's own installation, outside every place the session can write)"


def _number(value: float | int) -> str:
    return format(value, ".6g")


#: Text that may stand in a table cell as it is; anything else is quoted.
_PLAIN = re.compile(r"[A-Za-z0-9_.*/^ -]{1,256}")


def _quoted(text: str) -> str:
    # A JSON string on one line, with no character that could close a table cell.
    return json.dumps(text).replace("|", "\\u007c")


def _cell(text: str) -> str:
    return text if _PLAIN.fullmatch(text) else _quoted(text)


@dataclass(frozen=True)
class ColumnSummary:
    """One column summarised from its own samples, as the listing and the operator UI show it."""

    unit: str
    samples: int
    first: float
    last: float
    smallest: float
    largest: float


def column_summary(column: Column) -> ColumnSummary:
    """``column``'s unit, its number of samples, and its first, last, smallest and largest value.

    ``min`` and ``max`` keep the first of equal values, so a negative zero and a zero are
    reported in the order the record holds them.
    """
    values = column.values
    return ColumnSummary(
        unit=column.unit,
        samples=len(values),
        first=values[0],
        last=values[-1],
        smallest=min(values),
        largest=max(values),
    )


def _column(label: str, column: Column) -> str:
    shown = column_summary(column)
    return (
        f"| {label} | {shown.unit} | {shown.samples} | {_number(shown.first)} | "
        f"{_number(shown.last)} | {_number(shown.smallest)} | {_number(shown.largest)} |\n"
    )


def _seal_of(found: Bytecode) -> str:
    if found.sha256 is None:
        return "its bytes could not be read"
    return f"sha256 {found.sha256}, {found.length} bytes"


def _not_vouched(why: str | None, beside: list[Bytecode]) -> list[str]:
    """The mark of a record not vouched for, first in its section; nothing for any other."""
    if why is None and not beside:
        return []
    lines: list[str] = []
    if beside:
        lines.append(
            f"- {NOT_VOUCHED.upper()}: compiled code lay where the interpreter reads it in place "
            "of the source of a file this record names, or of the series writer, when its "
            "session ended, so the code that ran may not be the code it names\n"
        )
        lines += [f"  - {_quoted(found.path)}: {_seal_of(found)}\n" for found in beside]
    if why is not None:
        lines.append(
            f"- {NOT_VOUCHED.upper()}: the look for compiled code beside this record's code, when "
            "its session ended, could not be made whole, so nothing here says no such code lay "
            f"there: {_quoted(why)}\n"
        )
    return lines


def _record(
    session_id: str, record: Record, marked: tuple[str | None, list[Bytecode]] = (None, [])
) -> str:
    lines = [
        f"## {record.id}\n\n",
        *_not_vouched(*marked),
        f"- title: {_quoted(record.title)}\n",
        f"- group: {record.group or 'none'}; axis: {record.axis}; session: {session_id}\n",
        f"- script: {_quoted(record.producer.script.path)}, sha256 "
        f"{record.producer.script.sha256}\n",
    ]
    if record.producer.loaded:
        count = len(record.producer.loaded)
        lines.append(f"- code it loaded besides the script: {count} file{'s' * (count != 1)}\n")
        for code in record.producer.loaded:
            installed = _ENVIRONMENT if code.path.startswith("/") else ""
            lines.append(f"  - {_quoted(code.path)}, sha256 {code.sha256}{installed}\n")
    for name in sorted(record.inputs):
        given = record.inputs[name]
        lines.append(f"- input {name}: {_number(given.value)} {given.unit}\n")
    lines += [
        "\n| column | unit | samples | first | last | min | max |\n",
        "|---|---|---|---|---|---|---|\n",
        _column(f"x: {record.x.name}", record.x),
        *(_column(trace.name, trace) for trace in record.traces),
        "\n",
    ]
    return "".join(lines)


#: How every discarded record is marked, in words a reviewer cannot take for evidence.
DISCARDED = "discarded: the module's code changed after this record was written; not evidence"


def _discarded(discarded: tuple[AttemptDiscard, ...]) -> str:
    records = [d for d in discarded if d.entry.sha256 is not None]
    lines = [
        "# Records discarded\n\n",
        "A record is discarded when the module code it names changed, or was deleted or "
        "renamed, after it was written. It was never sealed and is not evidence: a quantity "
        f"that names it refuses the attempt. Records discarded: {len(records)}.\n\n",
    ]
    for held in discarded:
        entry = held.entry
        if entry.sha256 is not None:
            lines += [
                f"- {_quoted(entry.name)}: {DISCARDED}\n",
                f"  - session: {held.session_id}; seal: sha256 {entry.sha256}, "
                f"{entry.length} bytes\n",
                f"  - why: {_quoted(entry.reason)}\n",
            ]
        elif entry.name == OVERFLOW_NAME:
            lines.append(
                f"- cut: session {held.session_id}'s end line lists at most {MAX_ENTRIES} "
                f"entries, and it held more: {_quoted(entry.reason)}\n"
            )
    lines.append("\n")
    return "".join(lines)


def _bytecode(left: tuple[AttemptBytecode, ...]) -> str:
    total = sum(held.found for held in left)
    lines = [
        "# Bytecode found when a session ended\n\n",
        "A compiled file the interpreter would run in place of a module's source, found when a "
        "session ended: in the worktree, removed before its commit and never part of the "
        "attempt; or, by an absolute path, beneath a cache prefix in a directory of the "
        "session's own, left where it lies. The series writer, in the session's own process, "
        "writes no record while such a file lies beside a module that process loaded; that is "
        "no proof, since the session can leave the check out. A sealed record such a file lay "
        f"beside is marked {NOT_VOUCHED} above, and the file names it here. Files found: "
        f"{total}.\n\n",
    ]
    for held in left:
        lines.append(f"- session {held.session_id}: {held.found} found\n")
        if held.not_vouched is not None:
            lines.append(f"  - none of its records is vouched for: {_quoted(held.not_vouched)}\n")
        for found in held.files:
            beside = (
                f"; beside the records {', '.join(found.records)}, {NOT_VOUCHED}"
                if found.records
                else ""
            )
            lines.append(f"  - {_quoted(found.path)}: {_seal_of(found)}{beside}\n")
        if held.found > len(held.files):
            lines.append(f"  - and {held.found - len(held.files)} more, not named\n")
    lines.append("\n")
    return "".join(lines)


def _scratch(left: tuple[AttemptScratch, ...]) -> str:
    lines = [
        "# The scratch folder\n\n",
        "What a session left in its scratch folder, recorded when the session ended and then "
        "removed; never part of the attempt, and gone from the worktree you read. A record "
        "that names code in it is refused; code run from it that a record does not name is "
        "listed here and nowhere else. Entries found: "
        f"{sum(held.found for held in left)}.\n\n",
    ]
    for held in left:
        lines.append(f"- session {held.session_id}: {held.found} found\n")
        if held.cut is not None:
            lines.append(f"  - the record stopped at a bound: {_quoted(held.cut)}\n")
        for entry in held.files:
            if entry.kind != "file":
                what = "a link" if entry.kind == "link" else "neither a file nor a link"
            elif entry.sha256 is None:
                what = f"{entry.length} bytes, not read"
            else:
                what = f"sha256 {entry.sha256}, {entry.length} bytes"
            lines.append(f"  - {_quoted(entry.path)}: {what}\n")
        if held.found > len(held.files):
            lines.append(f"  - and {held.found - len(held.files)} more, not named\n")
    lines.append("\n")
    return "".join(lines)


def _check(check: SeriesCheck) -> str:
    read = (
        f"{_number(check.read_value)} {check.read_unit}"
        if check.read_value is not None and check.read_unit is not None
        else "not read"
    )
    trace = check.trace or "-"
    quantity = _cell(f"{check.node_id}.{check.quantity}")
    return (
        f"| {quantity} | {check.record_id} | {check.extract} | {trace} | "
        f"{_number(check.declared_value)} {_cell(check.declared_unit)} | {read} | "
        f"{check.outcome} |\n"
    )


def listing(series: AttemptSeries) -> bytes:
    """The listing of ``series``: every record from its samples, every discarded one, every check.

    Raises:
        SeriesError: a record is gone or is not what was sealed when its session ended.
    """
    pieces = [PREFACE, f"\nRecords sealed: {len(series.records)}.\n\n"]
    if series.records:
        pieces.append(LIMITS + "\n")
    for held in sorted(series.records, key=lambda r: r.record.record_id):
        entry = SealedEntry(series.subtask_id, series.attempt, held.session_id, held.record)
        record = read_record(entry.path(Path(series.run_dir)), entry.seal())
        marked = series.not_vouched(held.session_id, held.record.record_id)
        pieces.append(_record(held.session_id, record, marked))
    if series.discarded:
        pieces.append(_discarded(series.discarded))
    if series.bytecode:
        pieces.append(_bytecode(series.bytecode))
    if series.scratch:
        pieces.append(_scratch(series.scratch))
    tolerance = f"{float(RELATIVE_TOLERANCE):g}"
    pieces.append(
        "# Quantities read off a record\n\n"
        f"Each graph quantity that names a record, held to the value its extractor reads off "
        f"that record: they agree when they differ by at most {tolerance} of the larger, "
        f"relative (three significant figures). Quantities checked: {len(series.checks)}.\n"
    )
    if series.checks:
        pieces += [
            "\n| quantity | record | extractor | trace | declared | read | outcome |\n",
            "|---|---|---|---|---|---|---|\n",
            *(_check(check) for check in series.checks),
        ]
    return "".join(pieces).encode("utf-8")
