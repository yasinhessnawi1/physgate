"""Check 6, thermal budget: a margin in kelvin per component, in watts per module.

- **A component** that gives its thermal resistance: its temperature in use is
  the ambient temperature plus thermal resistance times the heat it dissipates,
  and the margin is its maximum temperature minus that, in kelvin.
- **A module** that gives the heat it can reject: the margin is that capacity
  minus the heat its members dissipate, in watts.

Arithmetic on the graph, exact, with absolute temperatures converted to kelvin
first. A negative margin is a finding with the margin (ARCH-080). Whether it
blocks is the architecture's: it warns at module scope and blocks at system
scope, where the same margin is checked again over the whole graph. A component
that gives some of its thermal quantities but not all is recorded as unchecked.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import Instance, instances, output, side, terms_of
from physgate.gate.result import CheckRun, Observation
from physgate.gate.units import PINT, PINT_ERRORS, UnitRefusedError, compare
from physgate.orchestrator.protocols import QuantityRef, ThermalDetails, UncheckedDetails

TOOL = f"arithmetic on the graph, exact ({PINT})"
MARGINS = {"junction_limit": "K", "heat_budget": "W"}


def _in_scope(view: GraphView, instance: Instance, touched: set[str] | None) -> bool:
    if touched is None:
        return True
    subject = instance.subject
    return subject in touched or bool(touched & set(view.nodes[subject].constrains))


def _unchecked(
    view: GraphView, instance: Instance, why: str, names: tuple[str, ...]
) -> Observation:
    return Observation(
        outcome="unchecked",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=None,
        expected=None,
        message=f"the thermal margin of {instance.subject} {why}",
        details=UncheckedDetails(quantities=names),
    )


def _margin(view: GraphView, instance: Instance) -> Fraction:
    load = side(view, instance.left)
    limit = side(view, instance.right)
    if limit is None:  # the right side of a thermal relation is always one limit
        msg = "a thermal relation without its limit"
        raise ValueError(msg)
    return limit.magnitude if load is None else compare(limit, load)


def _judge(view: GraphView, instance: Instance) -> Observation | None:
    unit = MARGINS[instance.relation.name]
    if instance.missing:
        return _unchecked(
            view,
            instance,
            f"cannot be computed: it declares no {', '.join(instance.missing)}",
            instance.missing,
        )
    try:
        margin = _margin(view, instance)
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    if margin >= 0:
        return None
    shown = output(margin, unit)
    terms = terms_of(view, instance)
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=shown,
        expected=f"a margin of at least 0 {unit}",
        message=(
            f"{instance.subject} has a thermal margin of {shown.value} {unit}: "
            f"{instance.expression()} does not hold, so it runs past its limit"
        ),
        details=ThermalDetails(margin=shown),
        quantities=tuple(
            QuantityRef(node_id=t.node_id, name=t.name, value=t.value.value, unit=t.value.unit)
            for t in terms
        )[:3],
    )


def run(ctx: CheckContext) -> CheckRun:
    """Compute every thermal margin in scope."""
    view = ctx.view
    touched = set(view.modules_touched()) if ctx.scope == "module" else None
    margins = [
        i for i in instances(view) if i.relation.name in MARGINS and _in_scope(view, i, touched)
    ]
    observations = [o for o in (_judge(view, i) for i in margins) if o is not None]
    evaluated = sum(1 for i in margins if not i.missing)
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))
