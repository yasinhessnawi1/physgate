"""Check 3's force sum alone: for a structure, or for reactions, that declare no position.

A structure can be written with its reactions and the masses it carries and no
positions at all. Its vertical force sum needs none, so it is judged; its moments,
which need the arms nobody wrote, are not, and the record says so. Check 3 forms such
a structure (:mod:`physgate.gate.check_equilibrium`); this module judges it, and
judges the forces of a placed mount beside which a reaction declares no position.

**Readings.** The declaration leaves some things open, and each open thing is read
every honest way:

- **whose weight a reaction carries.** A free-body diagram isolates one body and draws
  only the external forces on it: a support's own weight acts on the support, not on
  the structure it holds up, and a structure's own weight acts on the structure
  (R. C. Hibbeler, *Engineering Mechanics: Statics*, 14th edition, chapter 5,
  "Equilibrium of a Rigid Body", the free-body diagram; cited from the text's
  standard method, not re-read for this change on 18.10.2026). That is the check's
  own reading. A writer may instead give a wheel's ground contact force, which
  carries the wheel too, or leave a component structure's own weight out of its
  loads. Both are read;
- **a load that declares both a mass and a load force.** The weight alone, the force
  alone, the two together. Each reading reads only what it needs;
- **a reaction's sign.** A writer may give the force on the support rather than on the
  structure. The negated reactions are read too, but only to keep a correct design
  from failing, never to pass one;
- **a reaction that may not be vertical.** With three or more reactions on one
  structure, nothing says each is vertical (a bumper's push, a drive force). Each
  reading leaving one of them out is read, again only to keep a correct design from
  failing;
- **a member's weight inside another's.** A load that names another member (a pack
  that names the board it supplies) may already be in that member's mass: read with it
  and without it;
- **a weight carried through a member.** An outside part that names a member as what
  carries it (a pack on a bracket, a fuse naming the pack) may press on the structure
  through it: read with its weight and without. A member that is a module whose declared
  mass is the sum of the parts naming it is read as one.

**The verdict.** A structure **fails** only if every reading that could explain it
fails, a load with both quantities being read by its weight there (a stale force must
never un-block an error in the weights). It **passes** only if every reading of whose
weight is carried and of every doubly declared load balances, with every reaction as
declared and vertical. Anything else is **unchecked**, with the reason named.

**Named limits.**

- **A dummy reaction pair.** An invented reaction beside an invented load of the same
  size (or a reaction and its negative) adds terms that balance each other and widen
  the rounding allowance by their size. Forces alone cannot see it: the allowance is
  half a unit in each term's third significant figure, so a pair of 200 N hides an
  error of about 2 N. A placed mount sees the same pair's moments.
- **Two reactions, one not vertical.** With two reactions the reading that leaves one
  out is not made, since it would also explain a reaction that carries the whole
  weight by mistake. Such a structure can fail although correct.
- **Moments.** None are judged without positions.
- **A symmetric structure.** The reading that leaves one reaction out is wide where the
  reactions are alike: a tripod with one leg's reaction doubled, or a fourth leg added
  and the reactions not re-split, balances with one leg left out, and is unchecked, not
  refused.
- **Edges between members, and sub-assemblies.** With such an edge both readings must
  balance for a pass, so a correct design with one is mostly unchecked; an error is
  still refused when no reading balances. Only parts that name a member directly are
  read; a part two steps out is not.
- **The placed path's own convention.** A placed mount reads only the check's own
  convention (a support's weight is not a load on what it supports), as it always
  did; a placed design whose reactions carry the wheels' weight still fails there.
  That inconsistency with the readings here is flagged, not loosened, and is watched
  on the practice twins.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from physgate.gate.equilibrium import STANDARD_GRAVITY
from physgate.gate.graph import GraphView
from physgate.gate.relations import TermRef, measured, output
from physgate.gate.result import Observation
from physgate.gate.tolerances import ROUNDING_SHARE, holds_within_rounding
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import (
    EquilibriumDetails,
    QuantityRef,
    ReactionValue,
    UncheckedDetails,
)

#: How a load that declares both a mass and a load force is read: its weight alone,
#: its declared force alone, or the two together. The check's own is the first.
Reading = Literal["weight", "force", "both"]
READINGS: tuple[Reading, ...] = ("weight", "force", "both")
FORCES_ONLY = "force sum only: the structure declares no positions"
#: The fewest reactions on one structure at which one of them may be read as not vertical.
SIDEWAYS_FROM = 3


def si(view: GraphView, node: str, name: str) -> Fraction:
    """A quantity in its kind's SI unit, exactly."""
    return measured(view, TermRef(node, name)).magnitude


def weight(view: GraphView, node: str, reading: Reading) -> Fraction | None:
    """What ``node`` presses down with under ``reading``; ``None`` if it declares neither.

    Each reading reads only what it needs, so a quantity in a refused unit spoils only
    the readings that use it: the weight reading of a node with a mass never reads its
    load force. A node with one of the two has that one under every reading.

    Raises:
        UnitRefusedError, pint errors: a quantity this reading reads is refused.
    """
    q = view.nodes[node].quantities
    has_mass, has_force = "mass" in q, "load_force" in q

    def mass() -> Fraction:
        return si(view, node, "mass") * STANDARD_GRAVITY

    def force() -> Fraction:
        return si(view, node, "load_force")

    if has_mass and has_force:
        if reading == "weight":
            return mass()
        return force() if reading == "force" else mass() + force()
    if has_mass:
        return mass()
    if has_force:
        return force()
    return None


def mixed(view: GraphView, nodes: tuple[str, ...]) -> tuple[str, ...]:
    """Those of ``nodes`` that declare both a mass and a load force."""
    return tuple(n for n in nodes if {"mass", "load_force"} <= set(view.nodes[n].quantities))


def force_miss(
    reactions: list[Fraction], loads: list[Fraction]
) -> tuple[Fraction, Fraction] | None:
    """The force residual and what rounding explains, or ``None`` if rounding explains it.

    The allowance is :mod:`physgate.gate.tolerances`' for an equality: half a unit in
    each term's third significant figure, summed over every reaction and every load.
    """
    residual = sum(reactions, Fraction(0)) - sum(loads, Fraction(0))
    terms = [*reactions, *loads]
    if holds_within_rounding(residual, terms):
        return None
    return residual, ROUNDING_SHARE * sum((abs(t) for t in terms), Fraction(0))


def reaction_ref(view: GraphView, support: str) -> QuantityRef:
    """A support's declared reaction, as a finding names it."""
    q = view.nodes[support].quantities["reaction_force"]
    return QuantityRef(node_id=support, name="reaction_force", value=q.value, unit=q.unit)


def unchecked(mount_id: str, module: str | None, why: str, names: tuple[str, ...]) -> Observation:
    """A mount the check could not judge, and why."""
    return Observation(
        outcome="unchecked",
        node=mount_id,
        module=module,
        value=None,
        expected=None,
        message=f"mount {mount_id} {why}",
        details=UncheckedDetails(quantities=names),
    )


def forces_refused(
    view: GraphView,
    mount_id: str,
    supports: tuple[str, ...],
    miss: tuple[Fraction, Fraction],
    how: str,
) -> Observation:
    """A mount whose declared reactions do not carry its loads, by forces alone."""
    residual, bound = miss
    declared = tuple(
        ReactionValue(support=s, force=output(si(view, s, "reaction_force"), "N"), moment=None)
        for s in supports
    )
    return Observation(
        outcome="fail",
        node=mount_id,
        module=view.module_of(mount_id),
        value=output(residual, "N"),
        expected="declared reactions that carry the loads, within declared rounding",
        message=(
            f"mount {mount_id}: its declared reactions do not carry its loads ({how}): "
            f"the forces miss by {output(residual, 'N').value} N, and moving each declared "
            f"force and weight within half a unit in its third significant figure explains "
            f"at most {output(bound, 'N').value} N"
        ),
        details=EquilibriumDetails(
            solved=(),
            declared=declared,
            residual_force=output(residual, "N"),
            residual_moment=None,
            solver=FORCES_ONLY,
        ),
        quantities=tuple(reaction_ref(view, s) for s in supports)[:3],
    )


def shared(view: GraphView, mount_id: str, reactors: tuple[str, ...]) -> tuple[str, ...]:
    """Those of ``reactors`` whose reaction could be meant for another mechanical node.

    A node declares one reaction force. If it names more than one mechanical node,
    nothing says which of them that force holds up, so it is attributed to none. A
    node of another domain it names (a wheel naming the motor that drives it) holds
    nothing up, and does not count.
    """
    return tuple(
        r
        for r in reactors
        if any(
            t != mount_id and t in view.nodes and view.nodes[t].domain == "mechanical"
            for t in view.nodes[r].constrains
        )
    )


def nested(view: GraphView, members: tuple[str, ...]) -> tuple[str, ...]:
    """Members that constrain another member: a mass that may be counted twice."""
    inside = set(members)
    return tuple(m for m in members if inside & (set(view.nodes[m].constrains) - {m}))


def carrying(view: GraphView, mount_id: str, members: tuple[str, ...]) -> tuple[str, ...]:
    """Weighted parts outside the structure that name one of its members as what carries them.

    A bracket that holds a pack presses on the structure with the pack's weight as well
    as its own, and only its own is declared on it; a wheel a motor names may or may not
    carry that motor. Nothing says which, so both readings are made. A member that is a
    module whose declared mass is the sum of the parts naming it already holds their
    weight, and is read as one.
    """
    inside = {mount_id, *members}
    found = []
    for m in members:
        outside = [
            other
            for other in view.constrained_by(m)
            if other not in inside and {"mass", "load_force"} & set(view.nodes[other].quantities)
        ]
        if outside and not _sums_its_parts(view, m):
            found += [o for o in outside if o not in found]
    return tuple(found)


def _sums_its_parts(view: GraphView, member: str) -> bool:
    """A module whose declared mass is, within rounding, the masses of every part naming it."""
    node = view.nodes[member]
    if node.kind != "module" or "mass" not in node.quantities:
        return False
    try:
        parts = [
            si(view, p, "mass")
            for p in view.constrained_by(member)
            if "mass" in view.nodes[p].quantities
        ]
        whole = si(view, member, "mass")
    except (UnitRefusedError, *PINT_ERRORS):
        return False
    return holds_within_rounding(whole - sum(parts, Fraction(0)), [whole, *parts])


@dataclass(frozen=True)
class _Terms:
    """One structure's numbers, read once: what every reading is built from."""

    reactions: dict[str, Fraction]
    #: Each load's weight under the check's own reading.
    weights: dict[str, Fraction]
    #: The loads under the other readings of a doubly declared load; ``None`` for a
    #: reading whose quantities are refused.
    others: dict[Reading, dict[str, Fraction] | None]
    #: The supports' own weights, and the structure's own weight if it is a component.
    supports_own: list[Fraction]
    own: list[Fraction]
    #: Loads that name another member: perhaps counted twice, so read with and without.
    nested: tuple[str, ...]
    #: The weights of outside parts a member may carry: read with and without.
    carried: list[Fraction]


def _loads_under(
    view: GraphView, loads: tuple[str, ...], reading: Reading
) -> dict[str, Fraction] | None:
    try:
        return {ld: w for ld in loads if (w := weight(view, ld, reading)) is not None}
    except (UnitRefusedError, *PINT_ERRORS):
        return None


def _terms(
    view: GraphView, mount_id: str, supports: tuple[str, ...], loads: tuple[str, ...]
) -> _Terms:
    """The numbers the readings need.

    Raises:
        UnitRefusedError, pint errors: a quantity the check's own reading needs is refused,
            or an outside part's weight that a member may carry.
    """
    structure = view.nodes[mount_id]
    weights = {ld: w for ld in loads if (w := weight(view, ld, "weight")) is not None}
    outside = carrying(view, mount_id, (*supports, *loads))
    return _Terms(
        reactions={s: si(view, s, "reaction_force") for s in supports},
        weights=weights,
        others={r: _loads_under(view, loads, r) for r in READINGS if r != "weight"},
        supports_own=[
            si(view, s, "mass") * STANDARD_GRAVITY
            for s in supports
            if "mass" in view.nodes[s].quantities
        ],
        own=(
            [si(view, mount_id, "mass") * STANDARD_GRAVITY]
            if structure.kind != "module" and "mass" in structure.quantities
            else []
        ),
        nested=tuple(n for n in nested(view, (*supports, *loads)) if n in loads),
        carried=[w for o in outside if (w := weight(view, o, "weight")) is not None],
    )


def _load_sets(terms: _Terms, by_load: dict[str, Fraction]) -> list[list[Fraction]]:
    """Every reading of what the structure carries, from one reading of its loads.

    With and without the loads that name another member (they may be inside it), and
    with and without the outside parts a member may carry; then each convention of
    whose own weight the reactions carry.
    """
    kept = [list(by_load.values())]
    if terms.nested:
        kept.append([w for ld, w in by_load.items() if ld not in terms.nested])
    carried = [[], terms.carried] if terms.carried else [[]]
    supports_too = ([], terms.supports_own) if terms.supports_own else ([],)
    own_too = ([], terms.own) if terms.own else ([],)
    return [[*k, *c, *s, *o] for k in kept for c in carried for s in supports_too for o in own_too]


def reaction_readings(declared: list[Fraction]) -> list[list[Fraction]]:
    """Every reading of the reactions a correct design could mean.

    As declared, negated, and, with enough reactions, each one left out as perhaps not
    vertical.
    """
    found = [declared, [-r for r in declared]]
    if len(declared) >= SIDEWAYS_FROM:
        for k in range(len(declared)):
            rest = declared[:k] + declared[k + 1 :]
            found += [rest, [-r for r in rest]]
    return found


def explained(declared: list[Fraction], load_sets: list[list[Fraction]]) -> bool:
    """Whether some reading of the reactions balances some reading of the loads."""
    return any(
        force_miss(reactions, loads) is None
        for reactions in reaction_readings(declared)
        for loads in load_sets
    )


def judge_forces(
    view: GraphView,
    mount_id: str,
    supports: tuple[str, ...],
    loads: tuple[str, ...],
) -> Observation | None:
    """A structure that declares reactions and no positions: its force sum alone.

    See the module's docstring for the readings and the verdict. Returns ``None`` for a
    pass.
    """
    module = view.module_of(mount_id)
    names = tuple(f"reaction_force of {s}" for s in supports)
    attributed = shared(view, mount_id, supports)
    if attributed:
        why = (
            f"cannot be checked: {', '.join(attributed)} declare a reaction and name another "
            "mechanical node as well, so which structure that reaction holds up is not said"
        )
        return unchecked(mount_id, module, why, names)
    if not loads:
        why = "declares reactions but no member it carries, so there is no load to hold them to"
        return unchecked(mount_id, module, why, names)
    try:
        terms = _terms(view, mount_id, supports, loads)
    except (UnitRefusedError, *PINT_ERRORS):
        return unchecked(mount_id, module, "has a quantity in a unit the unit check refuses", names)
    declared = list(terms.reactions.values())
    # A failure: every reading that could explain the design misses, the loads read by
    # their weight. The check's own reading gives the reported residual.
    canonical = force_miss(declared, list(terms.weights.values()))
    if canonical is not None and not explained(declared, _load_sets(terms, terms.weights)):
        how = (
            "no positions are declared, so only the forces are judged, under every reading of "
            "whose weight the reactions carry and of their sign"
        )
        return forces_refused(view, mount_id, supports, canonical, how)
    # A pass: every reading of what is carried, and of every doubly declared load,
    # balances, with the reactions as declared.
    load_readings: list[dict[str, Fraction] | None] = [terms.weights]
    if mixed(view, loads):
        load_readings += list(terms.others.values())
    if all(
        lr is not None and force_miss(declared, loads_) is None
        for lr in load_readings
        for loads_ in (_load_sets(terms, lr) if lr is not None else [[]])
    ):
        return None
    why = (
        "cannot be checked: its reactions carry its loads under some honest readings and "
        "not others (whether a support's or the structure's own weight is carried, whether a "
        "member's weight sits inside another's or an outside part's weight reaches it, a "
        "reaction's sign or direction, or how a load declaring both a mass and a load_force "
        "is read)"
    )
    return unchecked(mount_id, module, why, names)
