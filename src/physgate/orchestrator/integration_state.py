"""Integration's issued state: what the run's record holds that integration's session reads.

Integration checks the modules together after each has merged, and two things it checks exist
only once the run has gone that far: the system-scope result, and each module pair's contract
result. Its specification was written before any module ran, so code writes the rest here, from
the run's event log alone, before integration's session is spawned (ARCH-051):

- the run's gate mode, with the sentence integration's specification states it in;
- the system-scope line: the verdict, the failing check, each blocking failure and warning by its
  check and node, the numeric output and the quantities; or why the check did not run;
- each module pair the plan names, in the recorded order: its first contract result, labelled
  first, and its latest result, or that no result exists for it;
- the system requirements the plan allocates to integration, with the brief's own words for each
  one the plan gives by number, so a bare number never stands for a requirement.

**It is state, never a message** (ARCH-040). Quoting a string keeps it from making a heading, not
from carrying an instruction, so the document renders nothing but:

- text the harness words itself, and enum values, numbers, digests and commits;
- node and interface ids, each only where it holds to the store's id pattern and bound here, where
  it is rendered: the store holds an id to them where it is written, but the event log it is read
  back from holds it to nothing but its type, so an id the store would refuse is shown as a phrase
  of the harness's, never as written;
- identifiers the log's own reading holds to a strict pattern: module names (the plan's name
  pattern), the subtask ids of each pair's sides (minted from those names);
- roles and integration's subtask id (minted from its role's name), which the plan's lines are
  held to the register's names for where they are written, and the log reads back held to
  nothing but their type;
- a unit only as pint's own name for it, after the gate's parser has held it to the shared
  spelling guard; a unit the parser refuses is said to be refused, and never shown;
- a quantity's name only where it is a name of the gate's catalogue: a graph quantity's name is
  held to no pattern at write, so any other is named by its place (a clause by its number in the
  order of its interface's quantity names, which the interface's contract file gives);
- the brief's own words, a person's, for each requirement given by number. A requirement the plan
  gives in words is named by its place in integration's specification, which quotes it.

So it copies no gate finding or check message, no clause's reason (each quotes a unit or a name
as a session wrote it), no session's stream, no reviewer's words and no node's free text; each
failing node's outcome is worded here.

**Its bytes.** UTF-8 with LF line endings and one final newline; every value is quoted as JSON on
one line, so no value, as written before a long line is cut, begins a heading or a numbered line
(a piece of a cut line may: the brief's words are a person's); nothing from a clock, a session, an
attempt or a line's place in the log (a process that takes a run over adds lines of its own), so
what the run recorded fixes the bytes. No line is longer than the transcript's width: a longer one
is cut into pieces, each but the last ending in the transcript's continuation mark, so the Read
tool shows every line whole and the reading check, which counts lines, proves a whole read.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from physgate.gate.catalogue import QUANTITIES
from physgate.gate.units import UnitRefusedError, parse
from physgate.orchestrator.decompose import GATE_MODE_SENTENCES
from physgate.orchestrator.events import IntegrationGateRan
from physgate.reviewers.transcript import cut_line
from physgate.state.schema import NODE_ID_MAX_LENGTH, NODE_ID_PATTERN

if TYPE_CHECKING:
    from physgate.contracts.clause import InterfaceCheck, NodeCheck
    from physgate.contracts.pairs import ContractPair, Side
    from physgate.orchestrator.events import ContractTested
    from physgate.orchestrator.protocols import CheckRecord, NumericOutput, QuantityRef
    from physgate.orchestrator.replay import RunState

#: The document's name, where its session reads it and in its reviewer's packet.
STATE_NAME = "integration_state.md"

HEAD = (
    "The harness built this file from the run's record, its event log, before integration's "
    "session was spawned. It holds the record's state, not a message: the run's gate mode, the "
    "system-scope result, the contract results of each module pair the plan names, and the system "
    "requirements with the brief's own words for each one the plan gives by number. The node ids "
    "in it were chosen by sessions, and each is shown only where it holds to the store's id "
    "pattern; a unit is named by the unit registry's name for it, and a quantity by the gate "
    "catalogue's name, or else by its place. Every value is quoted as JSON, and a line that ends "
    'in " ⏎" goes on in the next.'
)
#: What stands where a node id the store's id pattern or bound would refuse is on the record.
REFUSED_ID = "(a node id the store's id pattern refuses)"
SCOPE_HEAD = (
    "The gate's own words are on its record and are not copied here: they quote units and "
    "quantity names as sessions wrote them."
)
PAIRS_HEAD = (
    "Each module pair the plan names, in the order the run recorded them. A pair's first result "
    "is labelled first; its latest result is the one after the last merge in either of its "
    "modules. A clause is one quantity of an interface, numbered in the order of the quantities' "
    "names in the interface's contract file."
)
REQUIREMENTS_HEAD = (
    "Each requirement the plan allocates to integration, with the module criteria that "
    "contribute to it: one the plan gives by the brief's criterion number, with the brief's own "
    "words for it; one it gives in words, by its place in integration's specification, which "
    "quotes it."
)
#: Why a joined node fails a clause, in the harness's words.
WHY: dict[str, str] = {
    "missing": "it carries no quantity of the clause's name",
    "unit": "its unit is one the gate's parser refuses, or is not in the interface's root units",
    "value": "its value, converted to the interface's unit, is not the interface's",
}


def _q(value: object) -> str:
    """``value`` as JSON on one line, escaped to ASCII."""
    return json.dumps(value)


def _clauses(n: int) -> str:
    return f"{n} clause{'' if n == 1 else 's'} checked"


def _id(node_id: str) -> str:
    """A node id from the log, quoted only where the store's id pattern and bound hold it.

    The store holds every id to them where it is written; the log holds what it reads back to
    nothing, so a log rewritten on disk could put any text here. An honest run's ids all hold.
    """
    if len(node_id) <= NODE_ID_MAX_LENGTH and NODE_ID_PATTERN.fullmatch(node_id):
        return _q(node_id)
    return REFUSED_ID


def _nodes(names: tuple[str, ...]) -> str:
    return ", ".join(_id(name) for name in names) if names else "none"


def _quantity(name: str) -> str:
    """A quantity, by the gate catalogue's name when it is one; never by a name it is not."""
    if name in QUANTITIES:
        return f"quantity {_q(name)}"
    return "a quantity the catalogue does not name"


def _measure(value: float | int, unit: str) -> str:
    """A value in the unit registry's own names for its unit, or said to be in a refused unit.

    The unit is held to the gate's parser first (the shared spelling guard, then the registry),
    and only the registry's names for what it parsed are written, each with its power: a name
    the registry does not define never parses, so no word of the unit as written is shown.
    """
    try:
        items = parse(value, unit).unit_items()
    except UnitRefusedError:
        return f"{_q(value)}, in a unit the gate's parser refuses"
    named = " * ".join(name if power == 1 else f"{name}**{power}" for name, power in items)
    return f"{_q(value)} {_q(named or 'dimensionless')}"


def _output(output: NumericOutput | None) -> str:
    return _measure(output.value, output.unit) if output is not None else "none"


def _ref(ref: QuantityRef) -> str:
    return f"node {_id(ref.node_id)}, {_quantity(ref.name)}, {_measure(ref.value, ref.unit)}"


def _record(record: CheckRecord) -> str:
    where = f"node {_id(record.node)}" if record.node is not None else "no one node"
    value = f"; value {_output(record.value)}" if record.value is not None else ""
    return f"  - Check {_q(record.name)} at {_q(record.scope)} scope, on {where}{value}."


def _system_scope(state: RunState) -> list[str]:
    ran = state.integration
    if ran is None:
        return ["There is no system-scope line on the record."]
    if not isinstance(ran, IntegrationGateRan):
        return [
            f"The system-scope check did not run, for the reason {_q(ran.reason)}: there is no "
            "system-scope result."
        ]
    result = ran.result
    blocking = [r for r in result.checks if r.outcome == "fail" and r.blocking]
    warnings = [r for r in result.checks if r.outcome == "warn"]
    failing = _q(result.failing_check) if result.failing_check is not None else "none"
    return [
        f"The system-scope check ran in mode {_q(result.mode)}, and its verdict is "
        f"{_q(result.verdict)}. {SCOPE_HEAD}",
        "",
        f"- Failing check: {failing}.",
        f"- Blocking failures: {len(blocking)}{':' if blocking else '.'}",
        *(_record(record) for record in blocking),
        f"- Warnings: {len(warnings)}{':' if warnings else '.'}",
        *(_record(record) for record in warnings),
        f"- Numeric output: {_output(result.numeric_output)}.",
        *(f"- Quantity: {_ref(ref)}." for ref in result.quantities),
        *([] if result.quantities else ["- Quantities: none."]),
        f"- Catalogue: {_q(result.catalogue_sha256)}.",
    ]


def _side(name: str, side: Side) -> str:
    return (
        f"- {name}: module {_q(side.module)}, role {_q(side.role)}, subtask {_q(side.subtask_id)}."
    )


def _node(check: NodeCheck) -> str:
    said = f"node {_id(check.node)} ({check.side}) {_q(check.outcome)}"
    return said if check.outcome == "pass" else f"{said}: {WHY[check.outcome]}"


def _interface(check: InterfaceCheck) -> list[str]:
    unjoined = (
        "; not joined on: " + ", ".join(_q(side) for side in check.not_joined)
        if check.not_joined
        else ""
    )
    lines = [
        f"- Interface {_id(check.interface)}: {_q(check.outcome)}, "
        f"{_clauses(check.clauses_checked)}; producer nodes {_nodes(check.producer_nodes)}; "
        f"consumer nodes {_nodes(check.consumer_nodes)}{unjoined}."
    ]
    total = len(check.clauses)
    for number, clause in enumerate(check.clauses, start=1):
        named = f", {_quantity(clause.quantity)}" if clause.quantity in QUANTITIES else ""
        nodes = "; ".join(_node(node) for node in clause.nodes)
        lines.append(
            f"  - Clause {number} of {total}{named}: {_q(clause.outcome)}"
            + (f"; {nodes}" if nodes else "")
            + "."
        )
    return lines


def _result(label: str, line: ContractTested) -> list[str]:
    result = line.result
    lines = [
        f"{label}: {_q(result.outcome)}, {_clauses(result.clauses_checked)}, at "
        f"commit {_q(line.commit)}, journal revision {line.revision}, definition "
        f"{_q(result.definition_sha256)}.",
        "",
    ]
    for check in result.interfaces:
        lines.extend(_interface(check))
    return lines


def _pair(number: int, pair: ContractPair, state: RunState) -> list[str]:
    lines = [
        f"### Pair {number}: {_q(pair.producer.module)} to {_q(pair.consumer.module)}",
        "",
        _side("Producer", pair.producer),
        _side("Consumer", pair.consumer),
        f"- Interfaces: {', '.join(_id(i) for i in pair.interfaces)}.",
        "",
    ]
    results = [line for line in state.contracts if line.result.pair == pair]
    if not results:
        return [*lines, "No contract result exists for this pair."]
    first, latest = results[0], results[-1]
    lines.extend([*_result("First result, labelled first", first), ""])
    if latest is first:
        lines.append("Latest result: the first result is the latest.")
    else:
        lines.extend(_result("Latest result", latest))
    return lines


def _contracts(state: RunState) -> list[str]:
    pairs = state.contract_pairs
    if pairs is None:
        return ["The run records no contract pairs."]
    lines = [PAIRS_HEAD]
    for number, pair in enumerate(pairs, start=1):
        lines.extend(["", *_pair(number, pair, state)])
    return lines


def _criterion(requirement: str) -> bool:
    """Whether the plan gives ``requirement`` as a criterion number of the brief's."""
    return requirement.isascii() and requirement.isdigit() and len(requirement) <= 6


def _requirements(state: RunState) -> list[str]:
    requirements = state.system_requirements
    if requirements is None:
        return ["The run records no system requirements."]
    if not requirements:
        return ["The plan allocates no system requirement to integration."]
    words = {entry.criterion: entry.words for entry in state.brief_words}
    lines = [REQUIREMENTS_HEAD, ""]
    for place, item in enumerate(requirements, start=1):
        if not _criterion(item.requirement):
            given = (
                f"- Requirement {place}: given in words, as integration's specification quotes it."
            )
        elif item.requirement in words:
            given = (
                f"- Requirement {place}: the brief's criterion {_q(item.requirement)}, in the "
                f"brief's words: {_q(words[item.requirement])}."
            )
        else:
            given = f"- Requirement {place}: the brief's criterion {_q(item.requirement)}."
        contributing = "; ".join(
            f"criterion {_q(part.criterion)} of module {_q(part.module)}"
            for part in item.contributing
        )
        lines.extend([given, f"  - Contributing: {contributing}."])
    return lines


def issued_state(state: RunState) -> bytes:
    """Integration's issued state, built from the run's record alone, as the session reads it."""
    mode = state.gate_mode
    gate = (
        f"The run's gate mode is {_q(mode)}. {GATE_MODE_SENTENCES[mode]}"
        if mode is not None
        else "The run's gate mode is not on the record."
    )
    lines = [
        "# Integration's issued state",
        "",
        HEAD,
        "",
        f"Integration's subtask: {_q(state.completion_subtask)}.",
        "",
        "## Gate mode",
        "",
        gate,
        "",
        "## System-scope result",
        "",
        *_system_scope(state),
        "",
        "## Contract results",
        "",
        *_contracts(state),
        "",
        "## System requirements",
        "",
        *_requirements(state),
    ]
    text = "\n".join(piece for line in lines for piece in cut_line(line)) + "\n"
    return text.encode("utf-8")
