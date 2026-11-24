"""The lines of a recorded run, and each line's verdict against a price sheet.

**The lines** are the plan's parts a person answered "find": the choice is read through
:func:`physgate.orchestrator.parts.parts_choices`, from the run's release line, and the domain and
label from the plan's component list, in the plan's order. They are not a bill of materials a
design produced: a part a person has or makes is no line, and a run that made no parts decision
has no lines at all, which is never a pass.

**The rules**, each with its source:

- every line has the five facts of ARCH-120: availability, unit price, minimum order quantity,
  order multiple and lead time to Norway. A missing fact is named;
- a line whose node id no sheet entry names is "not found in the sheet";
- a lead time the sheet holds only in general, not to Norway, is "unverifiable for Norway": the
  lead-time limit is then not judged, and the line is not passed;
- a part that is not purchasable fails (ARCH-120: every line purchasable);
- the frozen risk table's row on sourcing in Norway: a lead time *above* four weeks to Norway
  fails, and so does a minimum order *above* five times the quantity needed. Exactly four weeks
  and exactly five times pass. The second is judged only where a quantity needed is known, and
  a run records none: only a person's stated quantity, given to the check, lets it be judged.

**The verdict** of a line is ``fails`` if any rule judged fails; else ``incomplete`` if the line
is not found, a fact is missing, or a rule is not judged; else ``passes``.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Literal

from physgate.build.bom.sheet import FACTS, Count, Entry, Sheet
from physgate.orchestrator.parts import parts_choices

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from physgate.orchestrator.replay import RunState

Verdict = Literal["passes", "incomplete", "fails"]
Outcome = Literal["met", "fails", "not judged"]

#: The frozen risk table's lead-time limit, four weeks to Norway, in days. Above it fails.
LEAD_TIME_LIMIT_DAYS = Fraction(28)

#: The frozen risk table's limit on a minimum order: five times the quantity needed. Above fails.
MINIMUM_ORDER_FACTOR = 5

NOT_FOUND = "not found in the sheet"
UNVERIFIABLE = "unverifiable for Norway: the sheet gives only a generic lead time"
NO_QUANTITY = "quantity needed not recorded: the minimum-order rule is not judged"


@dataclass(frozen=True)
class Line:
    """One part a person left to find: its plan node id, its domain and its label."""

    node: str
    domain: str
    label: str


@dataclass(frozen=True)
class Finding:
    """What one rule said of one line."""

    rule: Literal["availability", "lead_time", "minimum_order"]
    outcome: Outcome
    message: str


@dataclass(frozen=True)
class LineResult:
    """One line's verdict and everything it rests on."""

    line: Line
    entry: Entry | None
    missing: tuple[str, ...]
    findings: tuple[Finding, ...]
    quantity: Count | None
    verdict: Verdict


def lines_of(state: RunState) -> tuple[Line, ...]:
    """The plan's parts a person answered "find", in the plan's order.

    A run that asks nothing has none.

    Raises:
        PartsChoiceError: the run asks which parts a person has and is not released yet.
    """
    choices = parts_choices(state)
    lines: list[Line] = []
    for component in state.components or ():
        held = choices.get(component.node)
        if held is not None and held.choice == "find":
            lines.append(Line(node=component.node, domain=component.domain, label=component.label))
    return tuple(lines)


def _availability(entry: Entry) -> Finding | None:
    held = entry.facts.availability
    if held is None:
        return None
    if held.status == "not_purchasable":
        return Finding("availability", "fails", "the part is not purchasable")
    return Finding("availability", "met", f"the part is {held.status.replace('_', ' ')}")


def _lead_time(entry: Entry) -> Finding:
    held = entry.facts.lead_time_to_norway
    if held is None:
        return Finding("lead_time", "not judged", "no lead time: the four-week limit is not judged")
    if held.scope != "norway":
        return Finding("lead_time", "not judged", UNVERIFIABLE)
    shown = f"{held.value} {held.unit} to Norway"
    if held.days() > LEAD_TIME_LIMIT_DAYS:
        return Finding("lead_time", "fails", f"{shown} is above the four-week limit")
    return Finding("lead_time", "met", f"{shown} is within the four-week limit")


def _minimum_order(entry: Entry, quantity: Count | None) -> Finding:
    held = entry.facts.minimum_order_quantity
    if held is None:
        return Finding(
            "minimum_order", "not judged", "no minimum order: the five-times rule is not judged"
        )
    if quantity is None:
        return Finding("minimum_order", "not judged", NO_QUANTITY)
    limit = MINIMUM_ORDER_FACTOR * quantity.value
    shown = f"minimum order {held.value} against {quantity.value} needed (limit {limit})"
    if held.value > limit:
        return Finding("minimum_order", "fails", f"{shown} is above five times the need")
    return Finding("minimum_order", "met", f"{shown} is within five times the need")


def _verdict(entry: Entry | None, missing: tuple[str, ...], found: tuple[Finding, ...]) -> Verdict:
    if any(one.outcome == "fails" for one in found):
        return "fails"
    if entry is None or missing or any(one.outcome == "not judged" for one in found):
        return "incomplete"
    return "passes"


def check_line(line: Line, sheet: Sheet, quantity: Count | None) -> LineResult:
    """One line's verdict against ``sheet``, with the quantity needed if a person stated one."""
    entry = sheet.entry_for(line.node)
    if entry is None:
        return LineResult(line, None, FACTS, (), quantity, "incomplete")
    missing = tuple(name for name in FACTS if getattr(entry.facts, name) is None)
    availability = _availability(entry)
    found = (
        *(() if availability is None else (availability,)),
        _lead_time(entry),
        _minimum_order(entry, quantity),
    )
    return LineResult(line, entry, missing, found, quantity, _verdict(entry, missing, found))


def check_lines(
    lines: Iterable[Line], sheet: Sheet, quantities: Mapping[str, Count]
) -> tuple[LineResult, ...]:
    """Every line's verdict, in the order given."""
    return tuple(check_line(line, sheet, quantities.get(line.node)) for line in lines)


#: The command's exit status for each outcome over the lines.
EXIT_PASSES = 0
EXIT_FAILS = 1
EXIT_REFUSED = 2
EXIT_INCOMPLETE = 3
EXIT_NO_LINES = 4


def exit_status(results: tuple[LineResult, ...]) -> int:
    """The exit status over the lines.

    0 if there are lines and every one passes; 1 if any fails; 3 if none fails and any is
    incomplete; 4 if there are none.
    """
    if not results:
        return EXIT_NO_LINES
    verdicts = {one.verdict for one in results}
    if "fails" in verdicts:
        return EXIT_FAILS
    if "incomplete" in verdicts:
        return EXIT_INCOMPLETE
    return EXIT_PASSES
