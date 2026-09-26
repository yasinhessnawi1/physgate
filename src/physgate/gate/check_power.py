"""Check 4, power balance: every supply against the power drawn by what constrains it.

A supply is a node carrying ``power_supply``; its consumers are the nodes whose
``constrains`` edges name it and that carry ``power_draw``. A module drawing
from a battery is both: the supply of its own consumers, and a consumer of the
battery. The balance is built and evaluated by sympy, exactly, and compared with
no allowance: the design claims these numbers, and a consumer set drawing more
than its supply is refused with the deficit in watts and the contributing nodes
(ARCH-080).

At module scope the supplies checked are the modules the attempt touched; at
system scope, every supply in the graph, which is where modules that each
balance but together exceed their battery are refused.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import Instance, TermRef, instances, measured, output
from physgate.gate.result import CheckRun, Observation
from physgate.gate.symbolic import SYMPY, residual
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import PowerDetails, QuantityRef, UncheckedDetails

TOOL = f"{SYMPY}, over the graph's constrains edges"


def _watts(view: GraphView, ref: TermRef) -> Fraction:
    return measured(view, ref).magnitude


def _ref(view: GraphView, ref: TermRef) -> QuantityRef:
    q = view.nodes[ref.node].quantities[ref.name]
    return QuantityRef(node_id=ref.node, name=ref.name, value=q.value, unit=q.unit)


def _unchecked(
    view: GraphView, instance: Instance, why: str, names: tuple[str, ...]
) -> Observation:
    return Observation(
        outcome="unchecked",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=None,
        expected=None,
        message=f"the power budget of {instance.subject} {why}",
        details=UncheckedDetails(quantities=names),
    )


def _judge(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for one supply, or ``None`` if its consumers fit within it."""
    if instance.missing:
        return _unchecked(
            view,
            instance,
            "cannot be checked: consumers draw from it and it declares no supply",
            instance.missing,
        )
    supply = instance.right[0]
    if not isinstance(supply, TermRef):  # a power budget's right side is one supply
        msg = "a power budget's supply is a single quantity"
        raise TypeError(msg)
    try:
        consumers = [t for t in instance.left if isinstance(t, TermRef)]
        supplied = _watts(view, supply)
        drawn = [(c.spelled(), _watts(view, c)) for c in consumers]
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    margin = residual([(supply.spelled(), supplied)], drawn)
    if margin >= 0:
        return None
    deficit = output(-margin, "W")
    total = output(sum((w for _, w in drawn), Fraction(0)), "W")
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=deficit,
        expected=f"consumers drawing at most the {output(supplied, 'W').value} W supplied",
        message=(
            f"power drawn by the consumers on {instance.subject} ({total.value} W) exceeds its "
            f"supply ({output(supplied, 'W').value} W) by {deficit.value} W; it cannot run as "
            f"designed. Consumers: {', '.join(c.node for c in consumers)}"
        ),
        details=PowerDetails(
            deficit=deficit, contributing=(instance.subject, *(c.node for c in consumers))
        ),
        quantities=tuple(_ref(view, r) for r in (supply, *consumers))[:3],
    )


def run(ctx: CheckContext) -> CheckRun:
    """Balance every supply in scope against its consumers."""
    view = ctx.view
    budgets = [i for i in instances(view) if i.relation.name == "power_budget"]
    if ctx.scope == "module":
        touched = set(view.modules_touched())
        budgets = [i for i in budgets if i.subject in touched]
    observations = [o for o in (_judge(view, i) for i in budgets) if o is not None]
    evaluated = sum(1 for i in budgets if not i.missing)
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))
