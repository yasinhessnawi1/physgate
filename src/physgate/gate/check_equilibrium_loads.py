"""Check 3, two balances a mount never reads: a torque unit's mount, and a carrier's supported mass.

Both are read the way the rest of check 3 reads an open convention: every plausible reading
is taken; the node **fails** only when every reading misses by more than the declared
rounding, **passes** only when every reading balances, and is **unchecked** otherwise,
naming the readings that balanced. Nothing here turns a balance that fails under its own
reading into a pass.

**A torque unit.** A node that declares both ``torque_peak`` and ``reaction_moment`` is a
unit that delivers a torque and is held by a mount, which reacts it. The reading:

- *the unit as a whole* (a motor and its gearbox mounted as one): the mount reacts the whole
  peak torque, ``reaction_moment == torque_peak``;

and, where the node declares a gear ratio ``r`` (``gear_ratio``, ``external_gear_ratio``;
output over input, above 1), three more, because ``torque_peak`` may be the output torque or
the motor's own:

- *the gearbox alone, torque_peak the output*: the input torque enters through a motor
  mounted elsewhere, so the housing reacts the output less the input, ``torque_peak (1 - 1/r)``;
- *the mount reacting the output, torque_peak the motor's*: ``torque_peak r``;
- *the housing alone, torque_peak the motor's*: ``torque_peak (r - 1)``.

Every reading is a size: a reaction moment written with the opposite sign is the same
balance. **Named limits**, each refused because the reaction matches no reading: a
cantilevered unit whose reaction adds the moment of its own weight; a reaction written as the
mount's rated capacity rather than what it reacts; two motors on one node whose reaction is
their sum. And a reaction that differs from a reading by less than the rounding allowance of
the readings it fails is not refused.

**A carrier.** A node that declares ``supported_mass`` carries the weighted parts whose
``constrains`` edges name it (a pack names the bracket that carries it). Where every such part
names only this carrier at its level, the readings are the whole of their masses, with the
carrier's own mass counted in or left out, as a support's own weight is in the force
readings. Where a part names several carriers at one level (a pack on two brackets; a
drivetrain's two wheels, where a sibling that is a module is read as one with its members),
the split between them is nothing the graph states: each carrier's own share is
**unchecked**, and the **sum** of the sibling carriers' supported masses is judged against the
whole of what names any of them, with their own masses counted in or left out, recorded once
on the first of them in scope. A carrier nobody names is unchecked.

**Named limits** of the carrier readings: a ``constrains`` edge is not "is carried by", so
a carrier whose supported mass is the whole of a **subset** of the parts naming it (a wheel
that names the chassis for clearance, beside the electronics the chassis carries) is
**unchecked**, never refused, up to sixteen parts (beyond that the subsets are not read, and
the carrier is unchecked); and a supported mass written as the carrier's rated capacity
rather than what it carries matches no reading and is refused.
"""

from __future__ import annotations

from fractions import Fraction

from physgate.gate.equilibrium import STANDARD_GRAVITY
from physgate.gate.graph import GraphView
from physgate.gate.relations import TermRef, measured, output
from physgate.gate.result import Observation
from physgate.gate.tolerances import holds_within_rounding
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import EquilibriumDetails, UncheckedDetails

#: The ratio names a torque unit may declare, each dimensionless, output over input.
RATIOS: tuple[str, ...] = ("gear_ratio", "external_gear_ratio")
#: The most parts naming one carrier whose subsets are read; more leaves the carrier unchecked.
SUBSET_PARTS = 16


def _si(view: GraphView, node: str, name: str) -> Fraction:
    return measured(view, TermRef(node, name)).magnitude


def torque_units(view: GraphView) -> list[str]:
    """Every node declaring both a peak torque and a reaction moment, in id order."""
    return sorted(
        n
        for n, node in view.nodes.items()
        if "torque_peak" in node.quantities and "reaction_moment" in node.quantities
    )


def carriers(view: GraphView) -> list[str]:
    """Every node declaring a supported mass, in id order."""
    return sorted(n for n, node in view.nodes.items() if "supported_mass" in node.quantities)


def _unchecked(view: GraphView, node_id: str, why: str, names: tuple[str, ...]) -> Observation:
    return Observation(
        outcome="unchecked",
        node=node_id,
        module=view.module_of(node_id),
        value=None,
        expected=None,
        message=f"{node_id} {why}",
        details=UncheckedDetails(quantities=names),
    )


def _shown(readings: dict[str, Fraction], unit: str) -> str:
    return ", ".join(f"{label} ({output(e, unit).value} {unit})" for label, e in readings.items())


def _verdict(
    view: GraphView,
    node_id: str,
    declared: tuple[str, Fraction, str],
    readings: dict[str, Fraction],
    what: str,
    escapes: dict[str, Fraction] | None = None,
    declares: str | None = None,
) -> Observation | None:
    """Pass (None), fail or unchecked for ``declared`` against every reading.

    ``readings`` are the plausible readings: a pass needs every one to balance, a failure
    needs every one to miss. ``escapes`` are readings that can only leave the result
    unchecked (a subset of what names a carrier): one that balances stops a refusal and
    never makes a pass. ``declares`` says what the node declares, after its id. A failure's
    details carry the one residual the nearest reading made: a moment for a torque unit's
    mount, a force (the mass miss at standard gravity) for a carrier's load.
    """
    name, value, unit = declared
    declares = declares or f"declares {name}"
    balanced = {
        label: expected
        for label, expected in readings.items()
        if holds_within_rounding(value - expected, [value, expected])
    }
    if len(balanced) == len(readings):
        return None
    escaped = {
        label: expected
        for label, expected in (escapes or {}).items()
        if holds_within_rounding(value - expected, [value, expected])
    }
    if balanced or escaped:
        others = {label: e for label, e in readings.items() if label not in balanced}
        under = _shown({**balanced, **escaped}, unit)
        return _unchecked(
            view,
            node_id,
            f"{declares} of {output(value, unit).value} {unit}, which balances under {under} "
            f"and not under {_shown(others, unit)}; the readings disagree, so the {what} is "
            "unchecked",
            (name,),
        )
    nearest = min(readings.items(), key=lambda kv: abs(value - kv[1]))
    miss = output(value - nearest[1], unit)
    moment = unit == "N*m"
    details = EquilibriumDetails(
        solved=(),
        declared=(),
        residual_force=None if moment else output((value - nearest[1]) * STANDARD_GRAVITY, "N"),
        residual_moment=miss if moment else None,
        solver=f"the {what} readings, with the declared-rounding allowance",
    )
    expected = ", ".join(f"{label} {output(e, unit).value} {unit}" for label, e in readings.items())
    return Observation(
        outcome="fail",
        node=node_id,
        module=view.module_of(node_id),
        value=miss,
        expected=expected,
        message=(
            f"{node_id} {declares} of {output(value, unit).value} {unit}, and no reading of the "
            f"{what} gives that: {expected}; the nearest, {nearest[0]}, misses by {miss.value} "
            f"{unit}, more than the declared rounding allows"
        ),
        details=details,
    )


def judge_torque_unit(view: GraphView, node_id: str) -> Observation | None:
    """The finding for a torque unit whose reaction moment does not react its torque."""
    q = view.nodes[node_id].quantities
    try:
        torque = abs(_si(view, node_id, "torque_peak"))
        reaction = abs(_si(view, node_id, "reaction_moment"))
        ratios = {r: _si(view, node_id, r) for r in RATIOS if r in q}
    except (UnitRefusedError, *PINT_ERRORS):
        names = tuple(n for n in ("torque_peak", "reaction_moment", *RATIOS) if n in q)
        return _unchecked(
            view,
            node_id,
            "has a torque, reaction moment or ratio in a unit the unit check refuses",
            names,
        )
    readings = {"the unit as a whole, its mount reacting the peak torque": torque}
    for name, ratio in ratios.items():
        if ratio > 1:
            shown = f"{name} {output(ratio, 'dimensionless').value}"
            readings[f"the gearbox alone, torque_peak its output ({shown})"] = torque * (
                1 - 1 / ratio
            )
            readings[f"the mount reacting the output, torque_peak the motor's ({shown})"] = (
                torque * ratio
            )
            readings[f"the housing alone, torque_peak the motor's ({shown})"] = torque * (ratio - 1)
    return _verdict(view, node_id, ("reaction_moment", reaction, "N*m"), readings, "unit's mount")


def _named_by(view: GraphView, carrier: str) -> list[str]:
    """The weighted parts whose edges name ``carrier`` as what carries them, in id order.

    A module's own members name it as their module, not as their carrier, and a module is
    read as one with its members, so they are left out.
    """
    return sorted(
        n
        for n, node in view.nodes.items()
        if carrier in node.constrains
        and "mass" in node.quantities
        and n != carrier
        and not (view.nodes[carrier].kind == "module" and view.module_of(n) == carrier)
    )


def _siblings(view: GraphView, part: str, carrier: str) -> list[str]:
    """The carriers ``part`` names at ``carrier``'s level, ``carrier`` among them."""
    named = [
        c
        for c in view.nodes[part].constrains
        if c in view.nodes and "supported_mass" in view.nodes[c].quantities
    ]
    modules = {c for c in named if view.nodes[c].kind == "module"}
    members = {c for c in named if view.module_of(c) in modules and c not in modules}
    if carrier in members:
        # The level of the parts: the siblings that belong to the same module.
        return sorted(c for c in members if view.module_of(c) == view.module_of(carrier))
    # The whole level: every named carrier that is not a member of another named one.
    return sorted(c for c in named if c not in members)


def group_of(view: GraphView, carrier: str) -> tuple[str, ...]:
    """The carriers that share a part with ``carrier`` at its level, ``carrier`` among them.

    Sibling carriers are judged on the sum of their supported masses, so the group is
    closed: a bracket that shares a pack with a second bracket, which shares a sensor with a
    third, is one group of three.
    """
    group = {carrier}
    pending = [carrier]
    while pending:
        current = pending.pop()
        for part in _named_by(view, current):
            for sibling in _siblings(view, part, carrier):
                if sibling not in group:
                    group.add(sibling)
                    pending.append(sibling)
    return tuple(sorted(group))


def _share_unchecked(view: GraphView, carrier: str, group: tuple[str, ...], on: str) -> Observation:
    parts = ", ".join(_named_by(view, carrier))
    return _unchecked(
        view,
        carrier,
        f"declares supported_mass, and {parts} name it among {len(group)} carriers at its level "
        f"({', '.join(group)}); its own share of what they carry is nothing the graph states, "
        f"so it is unchecked, and the sum of their supported masses is judged on {on}",
        ("supported_mass",),
    )


def judge_group(
    view: GraphView, group: tuple[str, ...], on: str | None = None
) -> Observation | None:
    """The finding for a carrier, or a group of sibling carriers, on what names them.

    One carrier is a group of one. The finding is recorded on ``on``, the first of the
    group in scope, else on the first of the group.
    """
    node_id = on or group[0]
    parts = sorted({p for c in group for p in _named_by(view, c)})
    one = len(group) == 1
    if not parts:
        return _unchecked(
            view,
            node_id,
            "declares supported_mass, and no weighted part names it as what carries it, so "
            "there is nothing to hold the mass to",
            ("supported_mass",),
        )
    try:
        supported = sum((_si(view, c, "supported_mass") for c in group), Fraction(0))
        masses = {p: _si(view, p, "mass") for p in parts}
        own = sum(
            (_si(view, c, "mass") for c in group if "mass" in view.nodes[c].quantities),
            Fraction(0),
        )
    except (UnitRefusedError, *PINT_ERRORS):
        return _unchecked(
            view,
            node_id,
            "has a supported mass, or a mass it carries, in a unit the unit check refuses",
            ("supported_mass", "mass"),
        )
    if len(parts) > SUBSET_PARTS:
        return _unchecked(
            view,
            node_id,
            f"is named by {len(parts)} weighted parts, more than the {SUBSET_PARTS} whose "
            "subsets the carrier readings read, so it is unchecked",
            ("supported_mass",),
        )
    them = "it" if one else "them"
    owns = "its own mass" if one else "their own masses"
    whole = sum(masses.values(), Fraction(0))
    readings = {f"the whole of what names {them}": whole}
    if own != 0:
        readings[f"the whole with {owns}"] = whole + own
    escapes: dict[str, Fraction] = {}
    # Every proper, non-empty subset of the parts, by bitmask (the gate imports no itertools).
    for mask in range(1, (1 << len(parts)) - 1):
        subset = [p for k, p in enumerate(parts) if mask >> k & 1]
        total = sum((masses[p] for p in subset), Fraction(0))
        label = f"the whole of a subset of what names {them} ({', '.join(subset)})"
        escapes[label] = total
        if own != 0:
            escapes[f"{label} with {owns}"] = total + own
    others = ", ".join(c for c in group if c != node_id)
    declares = (
        None if one else f"and its sibling carriers {others} declare supported_mass summing to"
    )
    return _verdict(
        view,
        node_id,
        ("supported_mass", supported, "kg"),
        readings,
        "carrier" if one else "sibling carriers",
        escapes,
        declares,
    )


def judge_carrier(view: GraphView, carrier: str) -> Observation | None:
    """The finding for a carrier that shares no part with a sibling, on what names it."""
    return judge_group(view, (carrier,))


def judge_loads(
    view: GraphView, in_scope: set[str] | None
) -> tuple[list[Observation], int, set[tuple[str, str]]]:
    """Every torque unit's and carrier's finding, how many were judged, and the names read.

    ``in_scope`` limits the nodes judged; ``None`` is every node. A node is judged (and
    counted) when its reading gave a pass or a failure; one left unchecked is recorded, not
    counted. A group of sibling carriers is judged once, on its first member in scope. The
    (node, quantity) pairs read are returned, so the check records every other statics
    quantity of those nodes as read by no structure, as before: a torque unit's reading reads
    its reaction moment and nothing else.
    """
    found: list[Observation] = []
    judged = 0
    read: set[tuple[str, str]] = set()

    def take(finding: Observation | None) -> None:
        nonlocal judged
        if finding is None or finding.outcome == "fail":
            judged += 1
        if finding is not None:
            found.append(finding)

    for node_id in torque_units(view):
        if in_scope is not None and node_id not in in_scope:
            continue
        read.add((node_id, "reaction_moment"))
        take(judge_torque_unit(view, node_id))
    judged_on: dict[tuple[str, ...], str] = {}
    for node_id in carriers(view):
        if in_scope is not None and node_id not in in_scope:
            continue
        read.add((node_id, "supported_mass"))
        group = group_of(view, node_id)
        if len(group) == 1:
            take(judge_group(view, group))
            continue
        first = judged_on.setdefault(group, node_id)
        found.append(_share_unchecked(view, node_id, group, first))
        if first == node_id:
            take(judge_group(view, group, node_id))
    return found, judged, read
