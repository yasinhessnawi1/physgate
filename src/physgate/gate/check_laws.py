"""Check 8, the closed-form laws: every law in the table, wherever its pattern binds it.

The laws are data: each is a row of the law table the gate was built with, a textbook relation
over exact catalogue names, bound to the graph by one of three patterns (see
:mod:`physgate.gate.laws`). This check forms every instance of every law in its scope, measures
each input against its kind, and evaluates the law exactly in fractions. An instance that holds
is counted; one that does not is reported with everything a reader needs to see why: the law,
its source, the instance spelled over nodes, every input as declared and as evaluated with the
quantity's own source and writer, both sides, the residual, the allowance and the digest of the
table that judged it.

**It never decides whether a failure blocks.** Each law's failure is reported the same way
whatever the law's probation state; the runner looks the law up in the table and stamps it.

**An instance it cannot judge is recorded unchecked, naming the law and why, and never passed:**
an input or a required name missing, an excusing name present, an edge into an interface node
or into no node, a subject no member names, an input in a unit the unit check refuses, or a
division by an input that is zero. Each law's count is reported on its own, every law in the
table listed once, so the runner can state each law's reach whatever another law did.

At module scope a law is judged where it reads a node the attempt could have changed, or where
its anchor belongs to a module the attempt touched; at system scope everywhere.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.catalogue import KINDS, QUANTITIES
from physgate.gate.context import CheckContext
from physgate.gate.exceptions import LawRecordError
from physgate.gate.graph import GraphView
from physgate.gate.laws import (
    Binding,
    Evaluation,
    Expression,
    Law,
    LawTable,
    LawTableError,
    Value,
    ZeroDivisorError,
    bindings,
    evaluate,
)
from physgate.gate.relations import TermRef, measured, output
from physgate.gate.result import CheckRun, LawCount, Observation
from physgate.gate.units import PINT, PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import (
    LawDetails,
    LawInput,
    NumericOutput,
    QuantityRef,
    UncheckedDetails,
)

TOOL = f"exact rational arithmetic over the law table; {PINT}"

#: A measured input, or ``None`` where the unit check refuses it.
_Cache = dict[tuple[str, str], Fraction | None]


def run(ctx: CheckContext) -> CheckRun:
    """Judge every law of the gate's table wherever it binds in scope.

    Raises:
        LawTableError: the check was handed no law table.
    """
    table = ctx.laws
    if table is None:
        msg = "the laws check runs only with the law table the gate was built with"
        raise LawTableError(msg)
    view = ctx.view
    near = None if ctx.scope == "system" else set(view.affected()) | set(view.modules_touched())
    cache: _Cache = {}
    observations: list[Observation] = []
    counts: list[LawCount] = []
    for law_id in sorted(table.laws):
        law = table.laws[law_id]
        parsed = law.parsed()
        judged = 0
        failed: list[tuple[Binding, Evaluation]] = []
        for binding in bindings(law, view):
            if near is not None and not _in_scope(view, binding, near):
                continue
            verdict = _judge(law, parsed, view, binding, cache)
            if isinstance(verdict, Observation):
                observations.append(verdict)
                continue
            judged += 1
            if verdict is not None:
                failed.append((binding, verdict))
        observations.extend(
            _failure(law, parsed, table, view, binding, evaluation, judged, cache)
            for binding, evaluation in failed
        )
        counts.append(LawCount(law_id=law_id, evaluated=judged))
    return CheckRun(
        tool=TOOL,
        evaluated=sum(c.evaluated for c in counts),
        observations=tuple(observations),
        law_evaluated=tuple(counts),
    )


def _in_scope(view: GraphView, binding: Binding, near: set[str]) -> bool:
    """An instance reading a node the attempt affected, or anchored in a module it touched."""
    return bool(near & set(binding.nodes())) or bool(
        near & set(view.nodes[binding.anchor].constrains)
    )


def _where(binding: Binding) -> str:
    if binding.target is None:
        return binding.anchor
    return f"{binding.anchor}, over its edge to {binding.target}"


def _names(law: Law, symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(law.symbols[s].name for s in symbols))


def _unchecked(
    law: Law, view: GraphView, binding: Binding, why: str, names: tuple[str, ...]
) -> Observation:
    return Observation(
        outcome="unchecked",
        node=binding.anchor,
        module=view.module_of(binding.anchor),
        value=None,
        expected=None,
        message=f"the {law.id} law cannot be judged at {_where(binding)}: {why}",
        details=UncheckedDetails(quantities=names, law_id=law.id),
    )


def _placed(law: Law, binding: Binding, symbol: str) -> tuple[str, ...]:
    """The nodes a symbol is read on at this instance: one, or every member."""
    place = law.symbols[symbol].place
    if place == "each":
        return dict(binding.members)[symbol]
    if place == "target" and binding.target is not None:
        return (binding.target,)
    return (binding.anchor,)


def _judge(
    law: Law, parsed: Expression, view: GraphView, binding: Binding, cache: _Cache
) -> Observation | Evaluation | None:
    """An unchecked record, the evaluation of a failure, or ``None`` if the law holds."""
    if binding.reason is not None:
        return _unchecked(law, view, binding, binding.reason, binding.about)
    if binding.missing:
        why = f"it declares no {', '.join(binding.missing)} where the law reads it"
        return _unchecked(law, view, binding, why, binding.missing)
    values: dict[str, Value] = {}
    refused: list[str] = []
    for symbol, entry in sorted(law.symbols.items()):
        numbers: list[Fraction] = []
        for node_id in _placed(law, binding, symbol):
            number = _measured(view, node_id, entry.name, cache)
            if number is None:
                refused.append(entry.name)
                continue
            numbers.append(number)
        if entry.place == "each":
            values[symbol] = tuple(numbers)
        elif numbers:
            values[symbol] = numbers[0]
    if refused:
        names = tuple(dict.fromkeys(refused))
        why = f"{', '.join(names)} is in a unit the unit check refuses"
        return _unchecked(law, view, binding, why, names)
    try:
        evaluation = evaluate(law, parsed, values)
    except ZeroDivisorError as exc:
        return _unchecked(law, view, binding, str(exc), _names(law, exc.symbols))
    return None if evaluation.holds else evaluation


def _measured(view: GraphView, node_id: str, name: str, cache: _Cache) -> Fraction | None:
    """One input in its kind's canonical unit, measured once per node and name."""
    key = (node_id, name)
    if key not in cache:
        try:
            cache[key] = measured(view, TermRef(node_id, name)).magnitude
        except (UnitRefusedError, *PINT_ERRORS):
            cache[key] = None
    return cache[key]


def _canonical(name: str) -> str:
    return KINDS[QUANTITIES[name].kind].canonical


def _unit(law: Law, parsed: Expression) -> str:
    """The unit both sides are evaluated in: a bare term's kind's, else the first term's."""
    monomials = parsed.monomials()
    for monomial in monomials:
        if len(monomial.powers) == 1 and monomial.powers[0][1] == 1:
            return _canonical(law.symbols[monomial.powers[0][0]].name)
    factors = []
    for symbol, power in monomials[0].powers:
        canonical = _canonical(law.symbols[symbol].name)
        if canonical == "dimensionless":
            continue
        spelled = f"({canonical})" if any(c in canonical for c in "*/") else canonical
        factors.append(spelled if power == 1 else f"{spelled}**{power}")
    return "*".join(factors) or "dimensionless"


def _source(law: Law) -> str:
    s = law.source
    reading = "read in full" if s.reading == "in full" else "read through a secondary source"
    return f"{s.title}, {s.edition} edition, {s.section} ({s.kind}; {reading}, {s.read})"


def _spelled(law: Law, binding: Binding) -> str:
    """The row's expression with each symbol replaced by the quantity it reads at this instance.

    A summed symbol becomes the sum of its members, in parentheses unless it is a whole side.
    """
    text = law.expression.encode()
    starts = [0]
    for written in text.split(b"\n"):
        starts.append(starts[-1] + len(written) + 1)
    names = law.symbol_positions()
    whole = law.whole_sides()
    for symbol, line, start, end in sorted(names, key=lambda n: (n[1], n[2]), reverse=True):
        name = law.symbols[symbol].name
        nodes = _placed(law, binding, symbol)
        spelled = " + ".join(f"{name}({n})" for n in nodes)
        if len(nodes) > 1 and (line, start) not in whole:
            spelled = f"({spelled})"
        at = starts[line - 1]
        text = text[: at + start] + spelled.encode() + text[at + end :]
    return text.decode()


def _inputs(law: Law, view: GraphView, binding: Binding, cache: _Cache) -> tuple[LawInput, ...]:
    """Every input of the instance, the anchor's first, with the quantity's own provenance.

    Each canonical value is the one the law was evaluated at, read back from the measurements.
    """
    ordered = [law.anchor, *sorted(s for s in law.symbols if s != law.anchor)]
    found: dict[tuple[str, str], LawInput] = {}
    for symbol in ordered:
        name = law.symbols[symbol].name
        for node_id in _placed(law, binding, symbol):
            if (node_id, name) in found:
                continue
            q = view.nodes[node_id].quantities[name]
            magnitude = cache.get((node_id, name))
            if magnitude is None:
                msg = "a law was judged on an input that was not measured"
                raise LawRecordError(msg, law=law.id, node=node_id)
            found[(node_id, name)] = LawInput(
                node_id=node_id,
                name=name,
                declared=NumericOutput(value=q.value, unit=q.unit),
                canonical=output(magnitude, _canonical(name)),
                source=q.source,
                written_by=q.written_by,
            )
    return tuple(found.values())


def _failure(
    law: Law,
    parsed: Expression,
    table: LawTable,
    view: GraphView,
    binding: Binding,
    evaluation: Evaluation,
    judged: int,
    cache: _Cache,
) -> Observation:
    """The record of a law that does not hold at one instance."""
    unit = _unit(law, parsed)
    expression = _spelled(law, binding)
    left, right = output(evaluation.left, unit), output(evaluation.right, unit)
    residual = output(evaluation.residual, unit)
    allowance = None if evaluation.allowance is None else output(evaluation.allowance, unit)
    inputs = _inputs(law, view, binding, cache)
    if allowance is None:
        expected = expression
        found = (
            f"{left.value} {unit} {parsed.comparator} {right.value} {unit} is false, by "
            f"{residual.value} {unit}"
        )
    else:
        expected = f"{expression} to within {allowance.value} {unit}"
        found = (
            f"{left.value} {unit} against {right.value} {unit} is off by {residual.value} {unit}, "
            f"more than the {allowance.value} {unit} its {law.tolerance} tolerance allows"
        )
    return Observation(
        outcome="fail",
        node=binding.anchor,
        module=view.module_of(binding.anchor),
        value=residual,
        expected=expected,
        message=(
            f"the {law.id} law does not hold at {_where(binding)}: {expression}, and {found}. "
            f"'{law.statement}'"
        ),
        details=LawDetails(
            law_id=law.id,
            statement=law.statement,
            source=_source(law),
            law_status=law.status,
            expression=expression,
            inputs=inputs,
            left=left,
            right=right,
            comparator=parsed.comparator,
            tolerance=law.tolerance,
            residual=residual,
            allowance=allowance,
            laws_sha256=table.sha256,
            evaluated=judged,
        ),
        quantities=tuple(
            QuantityRef(
                node_id=i.node_id, name=i.name, value=i.declared.value, unit=i.declared.unit
            )
            for i in inputs[:3]
        ),
    )
