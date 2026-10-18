"""Check 3, two balances a mount never reads: a torque unit's mount, and a carrier's supported mass.

Both are read the way the rest of check 3 reads an open convention: every plausible reading
is taken; the node **fails** only when every reading misses by more than the declared
rounding, **passes** only when every reading balances, and is **unchecked** otherwise,
naming the readings that balanced. Nothing here turns a balance that fails under its own
reading into a pass.

**A torque unit.** A node that declares both ``torque_peak`` and ``reaction_moment`` is a
unit that delivers a torque and is held by a mount, which reacts it. The readings:

- *the unit as a whole* (a motor and its gearbox mounted as one): the mount reacts the whole
  peak torque, ``reaction_moment == torque_peak``;
- *the gearbox alone*, where the node declares a gear ratio (``gear_ratio``,
  ``external_gear_ratio``) and its input torque may enter through a motor mounted elsewhere:
  the housing reacts the output torque less the input, ``torque_peak * (1 - 1 / ratio)``.

Both are read as sizes: a reaction moment written with the opposite sign is the same
balance. A named limit: a unit whose reaction differs from its torque by less than the
rounding allowance of the readings it fails is not refused.

**A carrier.** A node that declares ``supported_mass`` carries the weighted parts that name
it (their ``constrains`` edges point at it, as a pack names the bracket that carries it).
The readings, for the parts a carrier is named by:

- *the whole*: the carrier takes all of each part's mass;
- *the share*: each part's mass is split equally among the sibling carriers that part names
  at the carrier's level, where a sibling that is a module is read as one with the siblings
  that are its members (a drivetrain and the two wheels that belong to it are one carrier
  at the whole level, and two at the wheels' level);

each with the carrier's own mass counted in or left out, as a support's own weight is in
the force readings. A carrier nobody names is unchecked. A named limit: an unequal split is
unchecked, never refused, so a carrier whose supported mass matches neither the whole nor an
equal share of what it carries is refused only when it also matches neither with its own
mass added.
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


def _verdict(
    view: GraphView,
    node_id: str,
    declared: tuple[str, Fraction, str],
    readings: dict[str, Fraction],
    what: str,
) -> Observation | None:
    """Pass (None), fail or unchecked for ``declared`` against every reading.

    A failure's details carry the one residual the reading made: a moment for a torque
    unit's mount, a force (the mass miss at standard gravity) for a carrier's load.
    """
    name, value, unit = declared
    balanced = {
        label: expected
        for label, expected in readings.items()
        if holds_within_rounding(value - expected, [value, expected])
    }
    if len(balanced) == len(readings):
        return None
    if balanced:
        names = ", ".join(
            f"{label} ({output(e, unit).value} {unit})" for label, e in balanced.items()
        )
        others = ", ".join(
            f"{label} ({output(e, unit).value} {unit})"
            for label, e in readings.items()
            if label not in balanced
        )
        return _unchecked(
            view,
            node_id,
            f"declares {name} of {output(value, unit).value} {unit}, which balances under "
            f"{names} and not under {others}; the readings disagree, so the {what} is unchecked",
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
            f"{node_id} declares {name} of {output(value, unit).value} {unit}, and no reading of "
            f"the {what} gives that: {expected}; the nearest, {nearest[0]}, misses by {miss.value} "
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
            shown = output(ratio, "dimensionless").value
            label = f"the gearbox alone, its input torque entering elsewhere ({name} {shown})"
            readings[label] = torque * (1 - 1 / ratio)
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


def judge_carrier(view: GraphView, carrier: str) -> Observation | None:
    """The finding for a carrier whose supported mass is not what the parts naming it weigh."""
    parts = _named_by(view, carrier)
    q = view.nodes[carrier].quantities
    if not parts:
        return _unchecked(
            view,
            carrier,
            "declares supported_mass, and no weighted part names it as what carries it, so "
            "there is nothing to hold the mass to",
            ("supported_mass",),
        )
    try:
        supported = _si(view, carrier, "supported_mass")
        whole = sum((_si(view, p, "mass") for p in parts), Fraction(0))
        share = sum(
            (_si(view, p, "mass") / len(_siblings(view, p, carrier)) for p in parts), Fraction(0)
        )
        own = _si(view, carrier, "mass") if "mass" in q else None
    except (UnitRefusedError, *PINT_ERRORS):
        return _unchecked(
            view,
            carrier,
            "has a supported mass, or a mass it carries, in a unit the unit check refuses",
            ("supported_mass", "mass"),
        )
    readings = {"the whole of what names it": whole, "an equal share of what names it": share}
    if own is not None and own != 0:
        readings.update(
            {
                "the whole with its own mass": whole + own,
                "an equal share with its own mass": share + own,
            }
        )
    return _verdict(view, carrier, ("supported_mass", supported, "kg"), readings, "carrier")


def judge_loads(
    view: GraphView, in_scope: set[str] | None
) -> tuple[list[Observation], int, set[tuple[str, str]]]:
    """Every torque unit's and carrier's finding, how many were judged, and the names read.

    ``in_scope`` limits the nodes judged; ``None`` is every node. A node is judged (and
    counted) when its reading gave a pass or a failure; one left unchecked is recorded, not
    counted. The (node, quantity) pairs read are returned, so the check records every other
    statics quantity of those nodes as read by no structure, as before: a torque unit's
    reading reads its reaction moment and nothing else.
    """
    found: list[Observation] = []
    judged = 0
    read: set[tuple[str, str]] = set()
    for node_id in torque_units(view):
        if in_scope is not None and node_id not in in_scope:
            continue
        read.add((node_id, "reaction_moment"))
        finding = judge_torque_unit(view, node_id)
        if finding is None or finding.outcome == "fail":
            judged += 1
        if finding is not None:
            found.append(finding)
    for node_id in carriers(view):
        if in_scope is not None and node_id not in in_scope:
            continue
        read.add((node_id, "supported_mass"))
        finding = judge_carrier(view, node_id)
        if finding is None or finding.outcome == "fail":
            judged += 1
        if finding is not None:
            found.append(finding)
    return found, judged, read
