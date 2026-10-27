"""Integration's issued state: what the run's record holds that integration's session reads.

Integration checks the modules together after each has merged, and two things it checks exist
only once the run has gone that far: the system-scope result, and each module pair's contract
result. Its specification was written before any module ran, so code writes the rest here, from
the run's event log alone, before integration's session is spawned (ARCH-051):

- the run's gate mode, with the sentence integration's specification states it in;
- the system-scope line: the verdict, the failing check, the finding, the numeric output and the
  quantities, or why the check did not run;
- each module pair the plan names, in the recorded order: its first contract result, labelled
  first, and its latest result, or that no result exists for it;
- the system requirements the plan allocates to integration, with the brief's own words for each
  one the plan gives by number, so a bare number never stands for a requirement.

It is state, never a message (ARCH-040): it reads only those lines' structured fields, so no
session's stream, no reviewer's words, no repair instruction and no node's free text reach it. The
gate's finding is quoted as the gate recorded it.

**Its bytes.** UTF-8 with LF line endings and one final newline; every recorded string and number
is quoted as JSON on one line, so no recorded text can begin a heading or a numbered line of its
own; nothing from a clock, a session, an attempt or a line's place in the log (a process that
takes a run over adds lines of its own), so what the run recorded fixes the bytes. No line is
longer than the transcript's width: a longer one is cut into pieces, each but the last ending in
the transcript's continuation mark, so the Read tool shows every line whole and the reading check,
which counts lines, proves a whole read.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from physgate.orchestrator.decompose import GATE_MODE_SENTENCES
from physgate.orchestrator.events import IntegrationGateRan
from physgate.reviewers.transcript import cut_line

if TYPE_CHECKING:
    from physgate.contracts.clause import InterfaceCheck
    from physgate.contracts.pairs import ContractPair, Side
    from physgate.orchestrator.events import ContractTested
    from physgate.orchestrator.replay import RunState

#: The document's name, where its session reads it and in its reviewer's packet.
STATE_NAME = "integration_state.md"

HEAD = (
    "The harness wrote this file from the run's event log before integration's session was "
    "spawned. It holds the record's state, not a message: the run's gate mode, the system-scope "
    "result, the contract results of each module pair the plan names, and the system requirements "
    "with the brief's own words for each one the plan gives by number. No session wrote any of "
    'it. Every recorded value is quoted as JSON, and a line that ends in " ⏎" goes on in the '
    "next."
)
PAIRS_HEAD = (
    "Each module pair the plan names, in the order the run recorded them. A pair's first result "
    "is labelled first; its latest result is the one after the last merge in either of its "
    "modules."
)
REQUIREMENTS_HEAD = (
    "Each requirement the plan allocates to integration, as the plan gives it, with the module "
    "criteria that contribute to it; where the plan gives one by the brief's criterion number, "
    "the brief's own words for it."
)


def _q(value: object) -> str:
    """``value`` as JSON on one line, escaped to ASCII."""
    return json.dumps(value)


def _clauses(n: int) -> str:
    return f"{n} clause{'' if n == 1 else 's'} checked"


def _nodes(names: tuple[str, ...]) -> str:
    return ", ".join(_q(name) for name in names) if names else "none"


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
    output = result.numeric_output
    quantities = [
        f"- Quantity: node {_q(ref.node_id)}, quantity {_q(ref.name)}, {_q(ref.value)} "
        f"{_q(ref.unit)}."
        for ref in result.quantities
    ] or ["- Quantities: none."]
    failing = _q(result.failing_check) if result.failing_check is not None else "none"
    return [
        f"The system-scope check ran in mode {_q(result.mode)}, and its verdict is "
        f"{_q(result.verdict)}.",
        "",
        f"- Failing check: {failing}.",
        f"- Finding: {_q(result.finding)}.",
        f"- Numeric output: {f'{_q(output.value)} {_q(output.unit)}' if output else 'none'}.",
        *quantities,
        f"- Catalogue: {_q(result.catalogue_sha256)}.",
    ]


def _side(name: str, side: Side) -> str:
    return (
        f"- {name}: module {_q(side.module)}, role {_q(side.role)}, subtask {_q(side.subtask_id)}."
    )


def _interface(check: InterfaceCheck) -> list[str]:
    unjoined = (
        "; not joined on: " + ", ".join(_q(side) for side in check.not_joined)
        if check.not_joined
        else ""
    )
    lines = [
        f"- Interface {_q(check.interface)}: {_q(check.outcome)}, "
        f"{_clauses(check.clauses_checked)}; producer nodes {_nodes(check.producer_nodes)}; "
        f"consumer nodes {_nodes(check.consumer_nodes)}{unjoined}."
    ]
    for clause in check.clauses:
        nodes = "; ".join(
            f"node {_q(node.node)} ({node.side}) {_q(node.outcome)}"
            + (f", because {_q(node.reason)}" if node.reason is not None else "")
            for node in clause.nodes
        )
        lines.append(
            f"  - Clause {_q(clause.quantity)}: {_q(clause.outcome)}"
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
        f"- Interfaces: {', '.join(_q(i) for i in pair.interfaces)}.",
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


def _requirements(state: RunState) -> list[str]:
    requirements = state.system_requirements
    if requirements is None:
        return ["The run records no system requirements."]
    if not requirements:
        return ["The plan allocates no system requirement to integration."]
    words = {entry.criterion: entry.words for entry in state.brief_words}
    lines = [REQUIREMENTS_HEAD, ""]
    for item in requirements:
        said = words.get(item.requirement)
        given = f", in the brief's words: {_q(said)}." if said is not None else "."
        contributing = "; ".join(
            f"criterion {_q(part.criterion)} of module {_q(part.module)}"
            for part in item.contributing
        )
        lines.extend(
            [
                f"- Requirement {_q(item.requirement)}{given}",
                f"  - Contributing: {contributing}.",
            ]
        )
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
