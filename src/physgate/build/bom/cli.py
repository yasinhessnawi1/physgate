"""``physgate bom check <run>``: the parts a person left to find, checked against a price sheet.

Reads the run's event log and the sheet, prints a table and a verdict per line (or the same as
data with ``--json``), and writes nothing. No network call is made and nothing can be ordered.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from physgate.build.bom.check import (
    EXIT_REFUSED,
    NOT_FOUND,
    LineResult,
    check_lines,
    exit_status,
    lines_of,
)
from physgate.build.bom.sheet import (
    EXAMPLE_SHEET,
    FACTS,
    Availability,
    Count,
    LeadTime,
    Named,
    Price,
    Quantities,
    Sheet,
    SheetError,
    SourcedCount,
    load_quantities,
    load_sheet,
)
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.replay import replay

if TYPE_CHECKING:
    from collections.abc import Mapping

EVENTS = "events.jsonl"

SHOWN = "shown, not measured: an offline check against an example sheet, not live distributor data"
LINES_ARE = (
    "the plan's parts a person answered 'find', not a bill of materials a design produced; "
    "a run with no parts decision has no lines, and no lines is not a pass"
)
LEFT_OUT = (
    "not in this check: a live distributor (it needs credentials; which one is the owner's "
    "decision), the orchestrator sending a failing line back to a role, and the measurement "
    "the risk table asks for. The check only reads: it cannot order"
)
EXAMPLE_MARK = "*"
EXAMPLE_NOTE = (
    f"{EXAMPLE_MARK} example value: written for the demonstration, not a price or a figure "
    "read from a distributor"
)

DESCRIPTION = (
    f"Check a recorded run's parts against an offline price sheet. Lines: {LINES_ARE}. "
    "Each line is given the five facts ARCH-120 asks (availability, unit price, minimum order "
    "quantity, order multiple, lead time to Norway) or has the missing ones named; a lead time "
    "that is only generic is marked unverifiable for Norway; a lead time above four weeks to "
    "Norway and a minimum order above five times the quantity needed fail. The run records no "
    "quantity needed, so the minimum-order rule is judged only for the quantities --quantities "
    "states. Verdict per line: passes, incomplete or fails. Exit status: 0 every line passes, "
    "1 a line fails, 3 none fails and a line is incomplete, 4 no lines, 2 refused. "
    f"The default sheet is an example fixture. This is {SHOWN}; {LEFT_OUT}."
)


def add_parser(subparsers: Any) -> None:  # noqa: ANN401 - argparse's private subparsers type
    """Register ``bom check``."""
    bom = subparsers.add_parser("bom", help="the parts to buy, checked offline (read only)")
    actions = bom.add_subparsers(dest="bom_action", required=True)
    check = actions.add_parser(
        "check",
        help="check the parts a person answered 'find' against an offline price sheet",
        description=DESCRIPTION,
    )
    check.add_argument("run", type=Path, help="the recorded run's directory (read, never written)")
    check.add_argument(
        "--sheet",
        type=Path,
        default=EXAMPLE_SHEET,
        help="the price sheet (default: the committed example fixture)",
    )
    check.add_argument(
        "--quantities",
        type=Path,
        help=(
            "a file of the quantity needed per node id, each {value, unit: '1'}, as a person "
            "states it: an operator's input, recorded as such in the output"
        ),
    )
    check.add_argument("--json", action="store_true", help="print the same as data")
    check.set_defaults(func=_check)


def _refuse(message: str, **context: str) -> int:
    print(json.dumps({"error": message, **context}, sort_keys=True), file=sys.stderr)
    return EXIT_REFUSED


def _check(args: argparse.Namespace) -> int:
    run_dir: Path = args.run.resolve()
    events = run_dir / EVENTS
    if not events.is_file():
        return _refuse("no run-event log in the run directory", run_dir=str(run_dir))
    try:
        sheet = load_sheet(args.sheet)
        given = None if args.quantities is None else load_quantities(args.quantities)
    except SheetError as exc:
        return _refuse(str(exc))
    try:
        lines = lines_of(replay(read_events(events)))
    except OrchestratorError as exc:
        return _refuse(str(exc), **exc.context)
    quantities: Mapping[str, Count] = {} if given is None else given.quantities
    strays = sorted(set(quantities) - {line.node for line in lines})
    if strays:
        return _refuse(
            "the quantities name a node that is no line of this run", nodes=", ".join(strays)
        )
    results = check_lines(lines, sheet, quantities)
    status = exit_status(results)
    if args.json:
        print(json.dumps(_data(run_dir, sheet, given, args.quantities, results, status), indent=1))
    else:
        print(_table(run_dir, sheet, given, args.quantities, results))
    return status


# --- the data ---------------------------------------------------------------------------------


def _is_example(fact: Named | Availability | Price | SourcedCount | LeadTime | None) -> bool:
    return fact is not None and fact.source.kind == "example"


def _fact_data(fact: Availability | Price | SourcedCount | LeadTime | None) -> object:
    if fact is None:
        return None
    return {**fact.model_dump(mode="json"), "example_value": _is_example(fact)}


def _result_data(result: LineResult) -> dict[str, object]:
    entry = result.entry
    facts = (
        None if entry is None else {name: _fact_data(getattr(entry.facts, name)) for name in FACTS}
    )
    return {
        "node": result.line.node,
        "domain": result.line.domain,
        "label": result.line.label,
        "found_in_sheet": entry is not None,
        "description": None if entry is None else entry.description,
        "maker": None if entry is None else entry.maker.model_dump(mode="json"),
        "maker_part_number": (
            None
            if entry is None or entry.maker_part_number is None
            else entry.maker_part_number.model_dump(mode="json")
        ),
        "facts": facts,
        "missing": list(result.missing),
        "findings": [
            {"rule": one.rule, "outcome": one.outcome, "message": one.message}
            for one in result.findings
        ],
        "quantity_needed": (
            None
            if result.quantity is None
            else {**result.quantity.model_dump(mode="json"), "stated_by": "operator"}
        ),
        "verdict": result.verdict,
    }


def _data(
    run_dir: Path,
    sheet: Sheet,
    given: Quantities | None,
    quantities_file: Path | None,
    results: tuple[LineResult, ...],
    status: int,
) -> dict[str, object]:
    return {
        "shown": SHOWN,
        "lines_are": LINES_ARE,
        "left_out": LEFT_OUT,
        "run": str(run_dir),
        "sheet": sheet.header.model_dump(mode="json"),
        "quantities": (
            None
            if given is None
            else {
                "operator_input": True,
                "stated_by": given.stated_by,
                "file": str(quantities_file),
            }
        ),
        "lines": [_result_data(one) for one in results],
        "summary": _summary(results),
        "exit_status": status,
    }


def _summary(results: tuple[LineResult, ...]) -> dict[str, int]:
    counts = Counter(one.verdict for one in results)
    return {"lines": len(results), **{v: counts[v] for v in ("passes", "incomplete", "fails")}}


# --- the table --------------------------------------------------------------------------------


def _marked(text: str, fact: Named | Availability | Price | SourcedCount | LeadTime) -> str:
    return text + (EXAMPLE_MARK if _is_example(fact) else "")


def _cell(name: str, result: LineResult) -> str:
    if result.entry is None:
        return "-"
    fact = getattr(result.entry.facts, name)
    if fact is None:
        return "MISSING"
    if isinstance(fact, Availability):
        return _marked(fact.status.replace("_", " "), fact)
    if isinstance(fact, LeadTime):
        where = "Norway" if fact.scope == "norway" else "generic"
        return _marked(f"{fact.value} {fact.unit} ({where})", fact)
    if isinstance(fact, Price):
        return _marked(f"{fact.value} {fact.unit}", fact)
    assert isinstance(fact, SourcedCount)
    return _marked(f"{fact.value}", fact)


HEADINGS = (
    "line",
    "domain",
    "available",
    "unit price",
    "min order",
    "multiple",
    "lead time",
    "verdict",
)


def _rows(results: tuple[LineResult, ...]) -> list[tuple[str, ...]]:
    return [
        (one.line.node, one.line.domain, *(_cell(name, one) for name in FACTS), one.verdict.upper())
        for one in results
    ]


def _grid(rows: list[tuple[str, ...]]) -> list[str]:
    widths = [max(len(row[i]) for row in [HEADINGS, *rows]) for i in range(len(HEADINGS))]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in [HEADINGS, *rows]
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return lines


def _part(result: LineResult) -> str:
    entry = result.entry
    if entry is None:
        return NOT_FOUND
    number = entry.maker_part_number
    named = _marked(entry.maker.value, entry.maker)
    named += " " + (
        _marked(number.value, number) if number is not None else "(part number not stated)"
    )
    return f"{entry.description}; {named}"


def _reasons(result: LineResult) -> list[str]:
    said = [f"{result.line.node} ({result.line.domain}) '{result.line.label}': {result.verdict}"]
    said.append(f"  part: {_part(result)}")
    if result.entry is not None:
        said.append(f"  missing: {', '.join(result.missing) if result.missing else 'none'}")
    if result.quantity is not None:
        said.append(f"  quantity needed: {result.quantity.value} (operator's input)")
    said.extend(
        f"  {one.rule.replace('_', ' ')}: {one.outcome}: {one.message}" for one in result.findings
    )
    return said


def _table(
    run_dir: Path,
    sheet: Sheet,
    given: Quantities | None,
    quantities_file: Path | None,
    results: tuple[LineResult, ...],
) -> str:
    header = sheet.header
    out = [
        f"physgate bom check: {SHOWN}.",
        f"run: {run_dir}",
        f"lines: {LINES_ARE}.",
        f"sheet: {header.kind}, written for {header.written_for}, on {header.written_on}: "
        f"{header.statement}",
        (
            "quantities: none given; the run records none"
            if given is None
            else f"quantities: operator's input, stated by {given.stated_by} in {quantities_file}"
        ),
        "",
    ]
    if not results:
        out.append("no lines: the run made no parts decision, or a person answered 'find' to none.")
        out.append("No lines is not a pass.")
    else:
        out.extend(_grid(_rows(results)))
        out.append("")
        for one in results:
            out.extend(_reasons(one))
        summary = _summary(results)
        out.append("")
        out.append(
            f"{summary['lines']} lines: {summary['passes']} pass, {summary['incomplete']} "
            f"incomplete, {summary['fails']} fail."
        )
        out.append(EXAMPLE_NOTE + ".")
    out.append(LEFT_OUT[0].upper() + LEFT_OUT[1:] + ".")
    return "\n".join(out)
