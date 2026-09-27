"""Check 5, energy and mass conservation, per node and per module.

Two balances, each an equality between numbers declared separately:

- **mass:** a module's declared mass is the sum of its members' masses, the
  members being the nodes whose ``constrains`` edges name it;
- **energy:** the power a node takes in is the power it delivers plus the heat
  it dissipates.

sympy computes each imbalance exactly. Because both sides were rounded on their
own, an equality holds within the rounding its terms can carry and no more (the
allowance in :mod:`physgate.gate.tolerances`); past that it is refused with the
imbalance and every term (ARCH-080). A balance with a term missing is recorded as
unchecked.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import Instance, TermRef, instances, measured, output, terms_of
from physgate.gate.result import CheckRun, Observation
from physgate.gate.symbolic import SYMPY, residual
from physgate.gate.tolerances import holds_within_rounding, rounding_allowance
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import ConservationDetails, QuantityRef, UncheckedDetails

TOOL = f"{SYMPY}, with the declared-rounding allowance"
BALANCES = {"mass_sum": "kg", "energy_balance": "W"}


def _in_scope(view: GraphView, instance: Instance, near: set[str]) -> bool:
    """A balance of a node the attempt affected, or of a member of a module it affected.

    An energy balance is a node's own, so it is checked whether or not the node
    belongs to any module.
    """
    subject = instance.subject
    return subject in near or bool(near & set(view.nodes[subject].constrains))


def _values(view: GraphView, side: tuple[object, ...]) -> list[tuple[str, Fraction]]:
    return [(t.spelled(), measured(view, t).magnitude) for t in side if isinstance(t, TermRef)]


def _judge(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for one balance, or ``None`` if it holds within declared rounding."""
    unit = BALANCES[instance.relation.name]
    module = view.module_of(instance.subject)
    if instance.missing:
        return Observation(
            outcome="unchecked",
            node=instance.subject,
            module=module,
            value=None,
            expected=None,
            message=(
                f"'{instance.relation.statement}' cannot be checked at {instance.subject}: "
                f"it declares no {', '.join(instance.missing)}"
            ),
            details=UncheckedDetails(quantities=instance.missing),
        )
    try:
        left, right = _values(view, instance.left), _values(view, instance.right)
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return Observation(
            outcome="unchecked",
            node=instance.subject,
            module=module,
            value=None,
            expected=None,
            message=f"a term at {instance.subject} is in a unit the unit check refuses",
            details=UncheckedDetails(quantities=names),
        )
    imbalance = residual(left, right)
    magnitudes = [v for _, v in (*left, *right)]
    if holds_within_rounding(imbalance, magnitudes):
        return None
    allowed = output(rounding_allowance(magnitudes), unit).value
    shown = output(imbalance, unit)
    first = instance.refs()[0]
    q = view.nodes[first.node].quantities[first.name]
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=module,
        value=shown,
        expected=f"{instance.expression()} to within {allowed} {unit} of declared rounding",
        message=(
            f"{instance.expression()} does not hold: it is off by {shown.value} {unit}, more "
            f"than the {allowed} {unit} that rounding each term to three significant figures "
            f"could explain. '{instance.relation.statement}' is violated at {instance.subject}"
        ),
        details=ConservationDetails(imbalance=shown, terms=terms_of(view, instance)),
        quantities=(QuantityRef(node_id=first.node, name=first.name, value=q.value, unit=q.unit),),
    )


def run(ctx: CheckContext) -> CheckRun:
    """Check every mass and energy balance the attempt could have changed.

    The balances of every node the attempt affected and of the modules those
    belong to.
    """
    view = ctx.view
    near = set(view.affected()) | set(view.modules_touched())
    balances = [
        i for i in instances(view) if i.relation.name in BALANCES and _in_scope(view, i, near)
    ]
    observations = [o for o in (_judge(view, i) for i in balances) if o is not None]
    evaluated = sum(1 for i in balances if not i.missing)
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))
