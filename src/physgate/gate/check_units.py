"""Check 1, unit consistency: every quantity and every relation an attempt touches.

At subtask scope over the nodes the attempt wrote, and at system scope over every
node, the ones the decomposition wrote included:

1. every quantity's unit must parse; a name the catalogue does not know is
   recorded as unchecked, never as passed;
2. every relation instance that reads one of those nodes is evaluated on its
   declared units, as written: its two sides must be in units pint can compare,
   and pint's own refusal, naming the expression and both sides, is the finding;
3. every known quantity not already refused must meet its kind (the rules in
   :mod:`physgate.gate.units`), its sign included: a negative mass or power is
   refused here.

A relation no check judges (its ``judged_by`` is ``None``) has only its units
checked here, and a record says so: whether it holds is counted as unchecked.

Returns the offending expression and both unit sides (ARCH-080).
"""

from __future__ import annotations

from typing import Any

from physgate.gate.catalogue import kind_of
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import Factor, Instance, Product, instances, touching
from physgate.gate.result import CheckRun, Observation
from physgate.gate.units import (
    PINT,
    PINT_ERRORS,
    UREG,
    SignRefusedError,
    UnitRefusedError,
    measure,
    parse,
    pint_message,
)
from physgate.orchestrator.protocols import (
    NumericOutput,
    QuantityRef,
    UncheckedDetails,
    UnitDetails,
)

TOOL = f"{PINT}, with the gate's unit catalogue"


class _MismatchError(Exception):
    """Two terms whose units do not combine, and pint's refusal."""

    def __init__(self, left: str, right: str, exc: Exception) -> None:
        super().__init__(pint_message(exc))
        self.left, self.right = left, right


def _declared(view: GraphView, node: str, name: str) -> Any:
    q = view.nodes[node].quantities[name]
    raw = parse(q.value, q.unit)
    kind = kind_of(name)
    # An absolute temperature enters arithmetic in kelvin, never in an offset unit.
    return raw.to("K") if kind is not None and kind.absolute else raw


def _sum(view: GraphView, factors: tuple[Factor, ...]) -> Any:
    total: Any = None
    for factor in factors:
        value = (
            _declared(view, factor.left.node, factor.left.name)
            * _declared(view, factor.right.node, factor.right.name)
            if isinstance(factor, Product)
            else _declared(view, factor.node, factor.name)
        )
        if total is None:
            total = value
            continue
        try:
            total = total + value
        except PINT_ERRORS as exc:
            raise _MismatchError(str(total.units), str(value.units), exc) from None
    return total if total is not None else UREG.Quantity(0)


def _refs(view: GraphView, instance: Instance) -> tuple[QuantityRef, ...]:
    refs = []
    for ref in instance.refs()[:3]:
        q = view.nodes[ref.node].quantities[ref.name]
        refs.append(QuantityRef(node_id=ref.node, name=ref.name, value=q.value, unit=q.unit))
    return tuple(refs)


def _relation_finding(view: GraphView, instance: Instance) -> Observation | None:
    """Pint's refusal of an instance's declared units, or ``None`` if its sides compare."""
    try:
        left = _sum(view, instance.left)
        right = _sum(view, instance.right)
        try:
            left - right  # noqa: B018 - pint's refusal is the finding
        except PINT_ERRORS as exc:
            raise _MismatchError(str(left.units), str(right.units), exc) from None
    except UnitRefusedError as exc:
        return Observation(
            outcome="fail",
            node=instance.subject,
            module=view.module_of(instance.subject),
            value=None,
            expected="every term of the relation in a unit pint can read",
            message=f"{instance.expression()} cannot be evaluated: {exc}",
            details=UnitDetails(
                expression=instance.expression(), left_unit="unreadable", right_unit="unreadable"
            ),
            quantities=_refs(view, instance),
        )
    except _MismatchError as mismatch:
        return Observation(
            outcome="fail",
            node=instance.subject,
            module=view.module_of(instance.subject),
            value=None,
            expected=f"both sides of '{instance.relation.statement}' in one kind of unit",
            message=(
                f"{instance.expression()} compares '{mismatch.left}' with '{mismatch.right}': "
                f"{mismatch}. The relation cannot be evaluated, so nothing that depends on it "
                "can be trusted"
            ),
            details=UnitDetails(
                expression=instance.expression(),
                left_unit=mismatch.left,
                right_unit=mismatch.right,
            ),
            quantities=_refs(view, instance),
        )
    return None


def _unjudged(view: GraphView, instance: Instance) -> Observation:
    """The record for a relation whose units agree and whose comparison no check makes."""
    return Observation(
        outcome="unchecked",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=None,
        expected=None,
        message=(
            f"{instance.expression()}: its units were checked and agree, but whether it holds "
            f"('{instance.relation.statement}') is not one of the gate's checks, so it is "
            "counted as unchecked, never as passed"
        ),
        details=UncheckedDetails(quantities=tuple(sorted({r.name for r in instance.refs()}))),
    )


def run(ctx: CheckContext) -> CheckRun:
    """Check the units of the attempt's own nodes and of every relation they are in."""
    view = ctx.view
    # At system scope every node, the decomposition's included; otherwise the attempt's.
    own = tuple(view.nodes) if ctx.scope == "system" else view.own()
    observations: list[Observation] = []
    refused: set[tuple[str, str]] = set()
    evaluated = 0
    for node_id in own:
        unknown = []
        for name, q in view.nodes[node_id].quantities.items():
            evaluated += 1
            if kind_of(name) is None:
                unknown.append(name)
            try:
                parse(q.value, q.unit)
            except UnitRefusedError as exc:
                refused.add((node_id, name))
                observations.append(
                    _quantity_finding(view, node_id, name, str(exc), "a unit pint can read")
                )
        if unknown:
            observations.append(
                Observation(
                    outcome="unchecked",
                    node=node_id,
                    module=view.module_of(node_id),
                    value=None,
                    expected=None,
                    message=(
                        f"{node_id} carries quantities the gate's catalogue does not know "
                        f"({', '.join(sorted(unknown))}): their units were parsed and their "
                        "magnitudes looked up, and no relation or kind was checked"
                    ),
                    details=UncheckedDetails(quantities=tuple(sorted(unknown))),
                )
            )
    for instance in touching(instances(view), own):
        if instance.missing or any((r.node, r.name) in refused for r in instance.refs()):
            continue
        if not instance.left or not instance.right:
            # A side with no terms (a supply nothing draws from yet) has no unit to
            # compare; reading it as a dimensionless zero was a false refusal. It
            # is recorded, so the attempt's coverage counts it, and never passed.
            observations.append(
                Observation(
                    outcome="unchecked",
                    node=instance.subject,
                    module=view.module_of(instance.subject),
                    value=None,
                    expected=None,
                    message=(
                        f"{instance.expression()}: the relation has no terms on one side yet, "
                        "so there is nothing to compare its units with"
                    ),
                    details=UncheckedDetails(
                        quantities=tuple(sorted({r.name for r in instance.refs()}))
                    ),
                )
            )
            continue
        evaluated += 1
        finding = _relation_finding(view, instance)
        if finding is not None:
            observations.append(finding)
            refused.update((r.node, r.name) for r in instance.refs())
        elif instance.relation.judged_by is None:
            observations.append(_unjudged(view, instance))
    for node_id in own:
        for name, q in view.nodes[node_id].quantities.items():
            kind = kind_of(name)
            if kind is None or (node_id, name) in refused:
                continue
            try:
                measure(kind, q.value, q.unit)
            except PINT_ERRORS as exc:
                observations.append(
                    _quantity_finding(view, node_id, name, pint_message(exc), kind.canonical)
                )
            except SignRefusedError as exc:
                observations.append(
                    _quantity_finding(view, node_id, name, str(exc), kind.canonical, exc.wanted)
                )
            except UnitRefusedError as exc:
                observations.append(
                    _quantity_finding(view, node_id, name, str(exc), kind.canonical)
                )
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))


def _quantity_finding(
    view: GraphView,
    node_id: str,
    name: str,
    reason: str,
    wanted: str,
    value_wanted: str | None = None,
) -> Observation:
    q = view.nodes[node_id].quantities[name]
    kind = kind_of(name)
    said = kind.name.replace("_", " ") if kind is not None else "quantity"
    what = ("an " if said[0] in "aeiou" else "a ") + said
    return Observation(
        outcome="fail",
        node=node_id,
        module=view.module_of(node_id),
        value=NumericOutput(value=q.value, unit=q.unit),
        expected=f"{what} {value_wanted}" if value_wanted else f"{what} in {wanted}",
        message=f"{name} of {node_id} is {q.value} {q.unit}, and {what} cannot be: {reason}",
        details=UnitDetails(
            expression=f"{name}({node_id}) = {q.value} {q.unit}",
            left_unit=q.unit,
            right_unit=wanted,
        ),
        quantities=(QuantityRef(node_id=node_id, name=name, value=q.value, unit=q.unit),),
    )
