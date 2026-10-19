"""Check 2, magnitude plausibility: each value against its sourced range or envelope.

At subtask scope over the nodes the attempt wrote, and at system scope over every
node (the decomposition's included), every quantity with a kind (a catalogued name,
or one whose suffix gives it a kind) is looked up in the bounds table: the range for
its name in the writer's own domain first, else the envelope for its kind, which
holds in every domain. The comparison is exact, in the bound's unit: the bounds are
what the source says, and rounding is never credited toward a pass. An envelope
bounds the size of a value, so the sign stays the unit check's. A value outside is
refused with the value, the span and its source (ARCH-080). A quantity with no range
for its name and no envelope for its kind is recorded as unchecked for magnitude,
never as passed.

No envelope is loaded today: each drafted one (a voltage, a temperature, a mass, a length)
is a product-class assumption, not physics, and is withheld in the cross-domain table's
comments until a ruling loads it, so a quantity with no range for its name in its domain
is unchecked.

Named limit: a range applies to every quantity of its name in its domain, and its note
says which class it was drawn from. The electrical ``sample_rate`` range is an inertial
sensor's output data rates, so an electrical node that samples faster for another reason
(an analogue-to-digital converter, an audio codec) is refused by it; the evaluation
scores such a refusal as this stated limit.
"""

from __future__ import annotations

from physgate.gate.bounds_table import Bound, BoundsTable, Envelope
from physgate.gate.catalogue import kind_of
from physgate.gate.context import CheckContext
from physgate.gate.result import CheckRun, Observation
from physgate.gate.units import PINT_ERRORS, Measured, UnitRefusedError, compare, measure
from physgate.orchestrator.protocols import (
    MagnitudeDetails,
    NumericOutput,
    QuantityRef,
    UncheckedDetails,
)

TOOL = "the gate's sourced bounds table"


def _outside(
    where: tuple[str, str | None],
    name: str,
    declared: tuple[float | int, str],
    hit: tuple[Bound, BoundsTable],
) -> Observation:
    (node_id, module), (value, unit), (found, table) = where, declared, hit
    span = f"{found.low} to {found.high} {found.unit}"
    what = (
        f"the envelope for the size of any {found.kind} of a {found.component_class}"
        if isinstance(found, Envelope)
        else f"the range for a {found.component_class}"
    )
    return Observation(
        outcome="fail",
        node=node_id,
        module=module,
        value=NumericOutput(value=value, unit=unit),
        expected=f"{span} for a {found.component_class}",
        message=(
            f"{name} of {node_id} is {value} {unit}, outside {span}, {what} ({found.source}; "
            f"read {found.retrieved.isoformat()}). Note on the span: {found.note}"
        ),
        details=MagnitudeDetails(
            value=NumericOutput(value=value, unit=unit),
            low=NumericOutput(value=found.low, unit=found.unit),
            high=NumericOutput(value=found.high, unit=found.unit),
            source=found.source,
            table_sha256=table.sha256,
        ),
        quantities=(QuantityRef(node_id=node_id, name=name, value=value, unit=unit),),
    )


def run(ctx: CheckContext) -> CheckRun:
    """Compare every catalogued quantity of the attempt's own nodes with its range."""
    view = ctx.view
    observations: list[Observation] = []
    evaluated = 0
    # At system scope every node, the decomposition's included; otherwise the attempt's.
    for node_id in tuple(view.nodes) if ctx.scope == "system" else view.own():
        node = view.nodes[node_id]
        no_range: list[str] = []
        unreadable: list[str] = []
        for name, q in node.quantities.items():
            kind = kind_of(name)
            if kind is None:
                continue  # the unit check records it as unknown
            hit = ctx.bounds.lookup(node.domain, name, kind.name)
            if hit is None:
                no_range.append(name)
                continue
            found, table = hit
            try:
                value = measure(kind, q.value, q.unit)
                if isinstance(found, Envelope):
                    # The size of the value: the sign is the unit check's business.
                    value = Measured(kind=kind, quantity=abs(value.quantity))
                below = compare(value, measure(kind, found.low, found.unit)) < 0
                above = compare(value, measure(kind, found.high, found.unit)) > 0
            except (UnitRefusedError, *PINT_ERRORS):
                unreadable.append(name)  # the unit check refuses it with the reason
                continue
            evaluated += 1
            if below or above:
                observations.append(
                    _outside((node_id, view.module_of(node_id)), name, (q.value, q.unit), hit)
                )
        for names, why in (
            (no_range, "have no sourced range for their domain and no envelope for their kind"),
            (unreadable, "are in a unit the unit check refuses, so no range could be applied"),
        ):
            if names:
                observations.append(
                    Observation(
                        outcome="unchecked",
                        node=node_id,
                        module=view.module_of(node_id),
                        value=None,
                        expected=None,
                        message=f"{', '.join(sorted(names))} of {node_id} {why}",
                        details=UncheckedDetails(quantities=tuple(sorted(names))),
                    )
                )
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))
