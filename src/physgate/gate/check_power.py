"""Check 4, power balance: every supply against the power drawn by what constrains it.

A supply is a node carrying ``power_supply``; its consumers are the nodes whose
``constrains`` edges name it and that carry ``power_draw``. A module drawing
from a battery is both: the supply of its own consumers, and a consumer of the
battery. The balance is built and evaluated by sympy, exactly, and compared with
no allowance: the design claims these numbers, and a consumer set drawing more
than its supply is refused with the deficit in watts and the contributing nodes
(ARCH-080).

A node that supplies power is either a declared source (the catalogue's
``SOURCES``: a battery declares its energy, a bench or mains supply its rated
output) or it draws what it supplies from a supply it constrains, and is held
to that: the power it supplies is at most the power it draws upstream. A node
that is neither is refused. A declared source is bounded too: its supply is at
most its output rating (a battery's maximum discharge, a supply's rated output)
plus whatever it draws upstream, and a source that declares no rating is
recorded as unchecked, its supply unbounded, never passed. These two relations
are a node's own, so at module scope they are judged for every node the attempt
affected. Without that, two modules each supplying their
members in full while drawing almost nothing from the battery balance at every
supply, and the battery never sees what their members really draw.

Two more relations bound what a supply can be asked for. A consumer's stall current
is at most its supply's current limit, the supply's peak rating: at stall a motor has no
back-EMF and draws its whole stall current, so a driver rated below it is overrun at every
start. A store's maximum continuous discharge is at most its stored energy times the
fastest continuous rate any store class is rated for (the catalogue's ``STORE_CLASSES``),
so an invented rating cannot make a token store a source. Each is refused with its excess,
in amperes or watts.

At module scope the supplies checked are the modules of the nodes the attempt
affected (see :meth:`physgate.gate.graph.GraphView.affected`), a module a
consumer left included, and every current headroom either side of which the attempt
affected; at system scope, every supply in the graph, which is where modules that each
balance but together exceed their battery are refused.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.catalogue import FASTEST, SOURCES
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import (
    Instance,
    Scaled,
    TermRef,
    instances,
    measured,
    output,
    scaled,
)
from physgate.gate.result import CheckRun, Observation
from physgate.gate.symbolic import SYMPY, residual
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import PowerDetails, QuantityRef, UncheckedDetails

TOOL = f"{SYMPY}, over the graph's constrains edges"


def _magnitude(view: GraphView, ref: TermRef) -> Fraction:
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
        supplied = _magnitude(view, supply)
        drawn = [(c.spelled(), _magnitude(view, c)) for c in consumers]
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


def upstream(view: GraphView, node_id: str) -> tuple[str, ...]:
    """The supplies ``node_id`` draws from: the nodes it constrains that declare one."""
    return tuple(
        t
        for t in view.nodes[node_id].constrains
        if t in view.nodes and "power_supply" in view.nodes[t].quantities
    )


def _judge_rating(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for a declared source: its supply against its rating plus its draw."""
    if instance.missing:
        return _unchecked(
            view,
            instance,
            f"cannot be bounded: it declares a source but no output rating "
            f"({', '.join(instance.missing)}); its supply is not bounded",
            instance.missing,
        )
    (supply,) = instance.left
    if not isinstance(supply, TermRef):
        msg = "a source's supply is a single quantity"
        raise TypeError(msg)
    try:
        supplied = _magnitude(view, supply)
        allowed = [
            (t.spelled(), _magnitude(view, t)) for t in instance.right if isinstance(t, TermRef)
        ]
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    margin = residual(allowed, [(supply.spelled(), supplied)])
    if margin >= 0:
        return None
    over = output(-margin, "W")
    bound = output(sum((w for _, w in allowed), Fraction(0)), "W")
    parts = " plus ".join(
        f"{t.name} {output(w, 'W').value} W"
        for t, (_, w) in zip(instance.right, allowed, strict=True)
        if isinstance(t, TermRef)
    )
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=over,
        expected=f"a supply of at most {bound.value} W ({parts})",
        message=(
            f"{instance.subject} supplies {output(supplied, 'W').value} W, more than its "
            f"declared bound of {bound.value} W ({parts}) by {over.value} W; a source "
            f"cannot deliver more than it is rated for"
        ),
        details=PowerDetails(deficit=over, contributing=(instance.subject,)),
        quantities=tuple(
            _ref(view, t) for t in (supply, *instance.right) if isinstance(t, TermRef)
        )[:3],
    )


def _not_a_source(view: GraphView, instance: Instance, why: str) -> Observation:
    sources = " or ".join(SOURCES)
    q = view.nodes[instance.subject].quantities["power_supply"]
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=output(measured(view, TermRef(instance.subject, "power_supply")).magnitude, "W"),
        expected=f"a declared source ({sources}), or a draw from a supply it constrains",
        message=(
            f"{instance.subject} supplies {q.value} {q.unit} but is not a declared source "
            f"(it declares neither {sources}) and {why}; a node that supplies power either "
            f"is a source or draws what it supplies from one"
        ),
        details=PowerDetails(
            deficit=output(
                measured(view, TermRef(instance.subject, "power_supply")).magnitude, "W"
            ),
            contributing=(instance.subject,),
        ),
        quantities=(_ref(view, TermRef(instance.subject, "power_supply")),),
    )


def _judge_covered(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for a node that supplies power and is not a declared source."""
    feeds = upstream(view, instance.subject)
    try:
        if not feeds:
            return _not_a_source(view, instance, "draws from no supply")
        if instance.missing:
            return _not_a_source(view, instance, f"declares no power_draw from {', '.join(feeds)}")
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    (supply,), (draw,) = instance.left, instance.right
    if not isinstance(supply, TermRef) or not isinstance(draw, TermRef):
        msg = "a covered supply compares two single quantities"
        raise TypeError(msg)
    try:
        supplied, drawn = _magnitude(view, supply), _magnitude(view, draw)
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    margin = residual([(draw.spelled(), drawn)], [(supply.spelled(), supplied)])
    if margin >= 0:
        return None
    short = output(-margin, "W")
    shown_supplied, shown_drawn = output(supplied, "W").value, output(drawn, "W").value
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=short,
        expected=f"a supply of at most the {shown_drawn} W it draws upstream",
        message=(
            f"{instance.subject} supplies {shown_supplied} W to what draws from it but draws "
            f"only {shown_drawn} W from its own supply, {short.value} W short: a stage cannot "
            f"hand out more power than it takes in"
        ),
        details=PowerDetails(deficit=short, contributing=(instance.subject,)),
        quantities=(_ref(view, supply), _ref(view, draw)),
    )


def _amperes(view: GraphView, instance: Instance) -> tuple[TermRef, TermRef]:
    (consumer,), (limit,) = instance.left, instance.right
    if not isinstance(consumer, TermRef) or not isinstance(limit, TermRef):
        msg = "a current headroom compares two single quantities"
        raise TypeError(msg)
    return consumer, limit


def _judge_headroom(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for a consumer whose stall current its supply's current limit cannot carry.

    At stall a brushed motor has no back-EMF, so it draws its stall current, limited only by
    its winding resistance; a supply whose maximum output current is below that cannot start
    or reverse the motor without tripping or exceeding its rating. The limit is the supply's
    peak rating (the catalogue's meaning of ``current_limit``), so a motor run behind current
    limiting below its stall current is not refused by a continuous rating.

    Named limits:

    - **Paralleled drivers.** A motor naming two drivers is held to each driver's limit alone;
      two 1 A drivers sharing a 1.5 A stall are each refused, though together they carry it.
      The relation does not sum the limits of the supplies one consumer names.
    - **A continuous rating written as ``current_limit``** is read as the peak rating the
      name means, so a stall above it is refused; the evaluation scores that as the stated
      limit, by the author's cited row.
    - **A supply in between.** Only the supply the motor's own edge names is read; a limit
      two hops away, past a regulator that declares none, is not.
    """
    consumer, limit = _amperes(view, instance)
    try:
        stall, most = _magnitude(view, consumer), _magnitude(view, limit)
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    if stall < 0 or most < 0:
        # A current written with a sign is a direction, not a rating: comparing it would
        # let a negative stall current pass under any limit.
        return Observation(
            outcome="unchecked",
            node=instance.subject,
            module=view.module_of(instance.subject),
            value=None,
            expected=None,
            message=(
                f"{instance.expression()} cannot be judged: a negative stall current or "
                "current limit is not a magnitude, so the headroom is not compared"
            ),
            details=UncheckedDetails(quantities=tuple(sorted({r.name for r in instance.refs()}))),
        )
    margin = residual([(limit.spelled(), most)], [(consumer.spelled(), stall)])
    if margin >= 0:
        return None
    over = output(-margin, "A")
    shown_stall, shown_limit = output(stall, "A").value, output(most, "A").value
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=over,
        expected=f"a stall current of at most the {shown_limit} A current limit",
        message=(
            f"{consumer.node} stalls at {shown_stall} A, more than the {shown_limit} A current "
            f"limit of {instance.subject} by {over.value} A: at stall a motor has no back-EMF "
            "and draws its stall current, which its supply is not rated to deliver"
        ),
        details=PowerDetails(deficit=over, contributing=(instance.subject, consumer.node)),
        quantities=(_ref(view, limit), _ref(view, consumer)),
    )


def _judge_discharge(view: GraphView, instance: Instance) -> Observation | None:
    """The finding for a store rated to discharge faster than any store class can."""
    (rating,), (stored,) = instance.left, instance.right
    if not isinstance(rating, TermRef) or not isinstance(stored, Scaled):
        msg = "a discharge rate compares a rating with a scaled stored energy"
        raise TypeError(msg)
    try:
        watts = _magnitude(view, rating)
        joules = measured(view, stored.ref).magnitude
        bound = scaled(view, stored).magnitude
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(sorted({r.name for r in instance.refs()}))
        return _unchecked(view, instance, "is in a unit the unit check refuses", names)
    margin = residual([(stored.spelled(), bound)], [(rating.spelled(), watts)])
    if margin >= 0:
        return None
    over = output(-margin, "W")
    shown_wh = output(joules / SECONDS_PER_HOUR, "W*h").value
    rate = output(watts * SECONDS_PER_HOUR / joules, "1/h").value
    return Observation(
        outcome="fail",
        node=instance.subject,
        module=view.module_of(instance.subject),
        value=over,
        expected=(
            f"a maximum continuous discharge of at most {output(bound, 'W').value} W "
            f"({stored.factor} per hour times {shown_wh} W*h)"
        ),
        message=(
            f"{instance.subject} stores {shown_wh} W*h and declares a maximum continuous "
            f"discharge of {output(watts, 'W').value} W, a rate of {rate} per hour; no class of "
            f"energy store is rated to discharge continuously faster than {stored.factor} per "
            f"hour ({FASTEST.name}), so the rating exceeds what it stores allows by "
            f"{over.value} W"
        ),
        details=PowerDetails(deficit=over, contributing=(instance.subject,)),
        quantities=tuple(_ref(view, r) for r in instance.refs()),
    )


JUDGES = {
    "power_budget": _judge,
    "supply_covered": _judge_covered,
    "source_rating": _judge_rating,
    "current_limit": _judge_headroom,
    "discharge_rate": _judge_discharge,
}
#: Relations about one node's own numbers: at module scope they are judged for
#: every node the attempt affected, not only for modules.
OWN = {"supply_covered", "source_rating", "discharge_rate"}
#: Relations between two components: at module scope they are judged wherever the
#: attempt affected either side.
BETWEEN = {"current_limit"}
SECONDS_PER_HOUR = Fraction(3600)


def run(ctx: CheckContext) -> CheckRun:
    """Balance every supply in scope against its consumers, and against what it draws."""
    view = ctx.view
    budgets = [i for i in instances(view) if i.relation.name in JUDGES]
    if ctx.scope == "module":
        touched = set(view.modules_touched())
        near = touched | set(view.affected())
        budgets = [
            i
            for i in budgets
            if (i.nodes() & near if i.relation.name in BETWEEN else set())
            or i.subject in (near if i.relation.name in OWN else touched)
        ]
    judged = [(i, JUDGES[i.relation.name](view, i)) for i in budgets]
    observations = [o for _, o in judged if o is not None]
    # Evaluated means judged: a relation with a term missing, or one left unchecked because
    # a side is in a refused unit, was recorded and not compared, so it is not counted.
    evaluated = sum(
        1 for i, o in judged if not i.missing and (o is None or o.outcome != "unchecked")
    )
    return CheckRun(tool=TOOL, evaluated=evaluated, observations=tuple(observations))
