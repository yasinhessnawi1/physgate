"""Check 2, magnitude plausibility: each value against its sourced range.

At subtask scope, over the nodes the attempt wrote, every quantity the catalogue
knows is looked up in its domain's bounds table and compared with the range
exactly, in the range's unit: the bounds are what the source says, and rounding
is never credited toward a pass. A value outside is refused with the value, the
range and the range's source (ARCH-080). A quantity with no range in its
domain's table is recorded as unchecked for magnitude, never as passed.
"""

from __future__ import annotations

from physgate.gate.bounds_table import BoundsTable, Range
from physgate.gate.catalogue import kind_of
from physgate.gate.context import CheckContext
from physgate.gate.result import CheckRun, Observation
from physgate.gate.units import PINT_ERRORS, UnitRefusedError, compare, measure
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
    hit: tuple[Range, BoundsTable],
) -> Observation:
    (node_id, module), (value, unit), (found, table) = where, declared, hit
    span = f"{found.low} to {found.high} {found.unit}"
    return Observation(
        outcome="fail",
        node=node_id,
        module=module,
        value=NumericOutput(value=value, unit=unit),
        expected=f"{span} for a {found.component_class}",
        message=(
            f"{name} of {node_id} is {value} {unit}, outside {span}, the range for a "
            f"{found.component_class} ({found.source}; read {found.retrieved.isoformat()}). "
            f"Note on the range: {found.note}"
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
    for node_id in view.own():
        node = view.nodes[node_id]
        no_range: list[str] = []
        unreadable: list[str] = []
        for name, q in node.quantities.items():
            kind = kind_of(name)
            if kind is None:
                continue  # the unit check records it as unknown
            hit = ctx.bounds.lookup(node.domain, name)
            if hit is None:
                no_range.append(name)
                continue
            found, table = hit
            try:
                value = measure(kind, q.value, q.unit)
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
            (no_range, "have no sourced range for their domain"),
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
