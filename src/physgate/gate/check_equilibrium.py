"""Check 3, static equilibrium and load path: per module, and over the whole graph.

A mount is any node other nodes constrain as supports or as loads:

- a **support** carries ``support_position`` and declares its ``reaction_force``,
  and a ``reaction_moment`` if it is fixed;
- a **load** carries ``mount_position`` and either a ``mass`` (its weight, at
  standard gravity) or a ``load_force``, acting downward. A member with a mass
  and no ``mount_position`` loads the mount somewhere nobody said, so the mount
  is recorded as unchecked, naming it, rather than balanced without its weight.

The declared reactions are held to the loads: both the force balance and the
moment balance must be explained by moving each declared force, weight and
moment within its own rounding, half a unit in its third significant figure
(the rounding model of :mod:`physgate.gate.tolerances`), with positions exact. See
:func:`rounding_miss` for how that is decided exactly.
A mount of pins at one point with a load off that point is refused as unstable
before any of that, since a pin cannot resist a moment. A mount statics can solve
alone is also solved, and a failure returns the solved reactions beside the
declared ones and both residuals (ARCH-080). A mount statics cannot solve is
handled as :data:`physgate.gate.equilibrium.INDETERMINATE_MOUNTS` says. A mount
with a quantity missing is recorded as unchecked.

**A balance the check did not read is never passed.** A check that judges nothing
still gets a pass record from the runner, so every statics quantity in scope must
either enter a judged balance or be named in an unchecked record:

- **A structure with no positions.** When no member of a node declares a position
  but some declare a ``reaction_force``, the node is a structure all the same, and
  its vertical force sum needs no position. It is formed only for a mechanical node,
  and judged by :mod:`physgate.gate.check_equilibrium_forces`, which says how each
  open reading is read, when it fails, passes or is unchecked, and its named limits
  (a dummy reaction pair among them). A pass there is counted apart in the record's
  tool line, since forces alone are weaker evidence than a placed balance.
- **A load that declares both a mass and a load_force.** Nothing in the
  declaration says whether the force is the weight written again or a force on top
  of it. The check's own reading (the weight, as it always read it, reading the mass
  alone, so a load force in a refused unit spoils only the readings that use it)
  decides a failure, and a
  failure stands whatever the other readings say, so a declared force can never
  un-block a mount. A mount that balances under that reading passes only if it
  also balances under the others (the force alone, the two together), and is
  unchecked otherwise.
- **A reaction declared beside positioned supports with no position of its own.**
  The moments cannot be judged; the forces, with that reaction counted, can. A
  mount that balanced without it fails only if the forces miss with it under every
  reading a correct design could mean (the reactions negated, with three or more one
  left out as perhaps not vertical, the reaction's own weight carried or not), and is
  unchecked otherwise.
- **A member with a load_force and no mount_position** loads the mount somewhere
  nobody said. A mount that fails without it still fails; one that balances without
  it is unchecked.
- **Anything else.** A node in scope that declares a reaction, a reaction moment
  or a load force that no mount reads is recorded as unchecked, naming it.

None of these turns a balance the check fails today into a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from physgate.gate import equilibrium
from physgate.gate.check_equilibrium_forces import (
    READINGS,
    Reading,
    explained,
    force_miss,
    forces_refused,
    judge_forces,
    mixed,
    shared,
    weight,
)
from physgate.gate.context import CheckContext
from physgate.gate.equilibrium import (
    STANDARD_GRAVITY,
    ClosedFormSolver,
    EquilibriumSolver,
    Load,
    MountProblem,
    NotSolvableError,
    Reaction,
    Support,
    mechanism,
    reference_point,
)
from physgate.gate.graph import GraphView
from physgate.gate.relations import TermRef, measured, output
from physgate.gate.result import CheckRun, Observation
from physgate.gate.tolerances import ROUNDING_SHARE, holds_within_rounding
from physgate.gate.units import PINT_ERRORS, UnitRefusedError
from physgate.orchestrator.protocols import (
    EquilibriumDetails,
    QuantityRef,
    ReactionValue,
    UncheckedDetails,
)

SPLIT_UNVERIFIED = "load split between supports unverified; needs FEA"
#: The quantities that only mean something inside a structure's balance.
STATICS: tuple[str, ...] = ("reaction_force", "reaction_moment", "load_force")


@dataclass(frozen=True)
class _Mount:
    mount_id: str
    supports: tuple[str, ...]
    loads: tuple[str, ...]
    #: Members with a mass and no ``mount_position``: weight the mount carries
    #: somewhere nobody said, so its balance cannot be checked.
    unplaced: tuple[str, ...] = ()
    #: Members that declare a ``reaction_force`` and no ``support_position``,
    #: beside members that are placed: forces only can count them.
    unplaced_reactions: tuple[str, ...] = ()
    #: ``False`` when no member declares a position: only the force sum is judged.
    positioned: bool = True
    #: Members with a load force, no mass and no ``mount_position``: a load nobody
    #: placed. A mount that fails without them still fails; one that balances
    #: without them cannot be said to balance with them.
    unplaced_forces: tuple[str, ...] = ()

    def reads(self) -> set[str]:
        """Every member whose statics quantities this mount reads or names."""
        return {
            *self.supports,
            *self.loads,
            *self.unplaced,
            *self.unplaced_reactions,
            *self.unplaced_forces,
        }


@dataclass(frozen=True)
class _Declared:
    problem: MountProblem
    reactions: tuple[Reaction, ...]


class _IncompleteError(Exception):
    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def mounts(view: GraphView) -> list[_Mount]:
    """Every node that others constrain as supports or loads, in id order.

    A node with positioned members is a mount as it always was. A mechanical node
    none of whose members declares a position, but some of which declare a
    reaction, is a mount whose force sum alone is judged.
    """
    found = []
    for node_id in view.nodes:
        members = view.constrained_by(node_id)

        def has(member: str, name: str) -> bool:
            return name in view.nodes[member].quantities

        supports = tuple(m for m in members if has(m, "support_position"))
        loads = tuple(m for m in members if has(m, "mount_position") and m not in supports)
        if supports or loads:
            rest = [m for m in members if m not in supports and m not in loads]
            unplaced = tuple(m for m in rest if has(m, "mass"))
            stray = tuple(m for m in rest if has(m, "reaction_force"))
            forces = tuple(m for m in rest if has(m, "load_force") and not has(m, "mass"))
            found.append(_Mount(node_id, supports, loads, unplaced, stray, True, forces))
            continue
        reactors = tuple(m for m in members if has(m, "reaction_force"))
        if reactors and view.nodes[node_id].domain == "mechanical":
            carried = tuple(
                m for m in members if m not in reactors and (has(m, "mass") or has(m, "load_force"))
            )
            found.append(_Mount(node_id, reactors, carried, positioned=False))
    return found


def _si(view: GraphView, node: str, name: str) -> Fraction:
    return measured(view, TermRef(node, name)).magnitude


def _declared(view: GraphView, mount: _Mount, reading: Reading = "weight") -> _Declared:
    """The mount as the graph declares it, in newtons and metres, under ``reading``.

    Raises:
        _IncompleteError: a support or load lacks what it needs.
        UnitRefusedError, pint errors: a quantity's unit is refused.
    """
    missing: list[str] = [
        f"mount_position of {m}, which has a mass and so loads this mount" for m in mount.unplaced
    ]
    supports, reactions, loads = [], [], []
    for s in mount.supports:
        q = view.nodes[s].quantities
        if "reaction_force" not in q:
            missing.append(f"reaction_force of {s}")
            continue
        fixed = "reaction_moment" in q
        supports.append(Support(s, "fixed" if fixed else "pin", _si(view, s, "support_position")))
        moment = _si(view, s, "reaction_moment") if fixed else Fraction(0)
        reactions.append(Reaction(s, _si(view, s, "reaction_force"), moment))
    for ld in mount.loads:
        force = weight(view, ld, reading)
        if force is None:
            missing.append(f"mass or load_force of {ld}")
            continue
        loads.append(Load(ld, force, _si(view, ld, "mount_position")))
    if missing:
        raise _IncompleteError(tuple(missing))
    problem = MountProblem(mount.mount_id, tuple(supports), tuple(loads))
    return _Declared(problem, tuple(reactions))


@dataclass(frozen=True)
class _Generator:
    """One declared number's rounding slack, as a (force, moment about 0) direction.

    ``half_width`` is how far the number may move: half a unit in its third
    significant figure, which is at most ``ROUNDING_SHARE`` of its magnitude. A
    declared 0 has none.
    """

    force: Fraction
    moment: Fraction
    half_width: Fraction


@dataclass(frozen=True)
class _Miss:
    """An equation the declared rounding cannot explain: what, where, by how much."""

    what: str
    x_m: Fraction | None
    residual: Fraction
    bound: Fraction


def _residuals(declared: _Declared) -> tuple[Fraction, Fraction]:
    """The force residual, and the moment residual about the axis's origin."""
    problem = declared.problem
    at = {s.node_id: s.x_m for s in problem.supports}
    force = sum((r.force_n for r in declared.reactions), Fraction(0)) - sum(
        (ld.force_n for ld in problem.loads), Fraction(0)
    )
    moment = sum(
        (r.force_n * at[r.support_id] + r.moment_nm for r in declared.reactions), Fraction(0)
    ) - sum((ld.force_n * ld.x_m for ld in problem.loads), Fraction(0))
    return force, moment


def _generators(declared: _Declared) -> list[_Generator]:
    problem = declared.problem
    at = {s.node_id: s.x_m for s in problem.supports}
    found = []
    for r in declared.reactions:
        found.append(_Generator(Fraction(1), at[r.support_id], ROUNDING_SHARE * abs(r.force_n)))
        found.append(_Generator(Fraction(0), Fraction(1), ROUNDING_SHARE * abs(r.moment_nm)))
    found.extend(
        _Generator(Fraction(-1), -ld.x_m, ROUNDING_SHARE * abs(ld.force_n)) for ld in problem.loads
    )
    return [g for g in found if g.half_width != 0]


def _about(x: Fraction, force: Fraction, moment: Fraction) -> Fraction:
    """A (force, moment about 0) pair's moment about ``x``."""
    return moment - x * force


def rounding_miss(declared: _Declared) -> _Miss | None:
    """The equation declared rounding cannot explain, or ``None`` if it can explain both.

    The rounding model is per number: each declared force, weight and moment is true
    to within half a unit in its third significant figure. The question is
    whether moving each one within its own slack balances both the force row and
    the moment row at once. Positions are taken as exact: a coordinate's
    precision is not relative to its size, and rounding it by a share of its
    value would make the answer depend on where the origin is again.

    The slacks' combined effect on (force, moment) is a zonotope, a centrally
    symmetric polygon whose edges are parallel to the numbers' directions. The
    residual lies inside it exactly when it lies within every edge's supporting
    lines. An edge parallel to a force at position x has a normal that measures
    the moment about x; an edge parallel to a moment has one that measures the
    force. So the test is: the force residual within the force slack, and the
    moment residual about every position that carries a declared number within
    the moment slack about that position. The moments about the supports'
    centroid are tested as well, which settles the one degenerate case, every
    slack a moment. Every quantity is a fraction, so the answer is exact. Row
    operations do not change it, so neither does the choice of origin.
    """
    force, moment = _residuals(declared)
    gens = _generators(declared)
    tests: list[_Miss] = [
        _Miss("forces", None, force, sum((g.half_width * abs(g.force) for g in gens), Fraction(0)))
    ]
    points = {g.moment / g.force for g in gens if g.force != 0}
    points.add(reference_point(declared.problem))
    for x in sorted(points):
        bound = sum((g.half_width * abs(_about(x, g.force, g.moment)) for g in gens), Fraction(0))
        tests.append(_Miss("moments", x, _about(x, force, moment), bound))
    failing = [t for t in tests if abs(t.residual) > t.bound]
    if not failing:
        return None
    return max(failing, key=lambda t: (t.bound == 0, abs(t.residual) / t.bound if t.bound else 0))


def _where(declared: _Declared, x: Fraction) -> str:
    problem = declared.problem
    named = [s.node_id for s in problem.supports if s.x_m == x] + [
        ld.node_id for ld in problem.loads if ld.x_m == x
    ]
    shown = output(x, "m").value
    return f"{named[0]} at {shown} m" if named else f"{shown} m"


def _matches(declared: tuple[Reaction, ...], solved: tuple[Reaction, ...]) -> bool:
    """Every declared reaction is the solved one, support by support, within declared rounding.

    Balanced sums prove the split only where statics has one answer; a solver that
    splits an indeterminate load gives an answer the sums alone cannot confirm.
    """
    found = {r.support_id: r for r in solved}
    for mine in declared:
        theirs = found.get(mine.support_id)
        if theirs is None:
            return False
        for a, b in ((mine.force_n, theirs.force_n), (mine.moment_nm, theirs.moment_nm)):
            if not holds_within_rounding(a - b, [a, b]):
                return False
    return True


def _values(reactions: tuple[Reaction, ...], fixed: set[str]) -> tuple[ReactionValue, ...]:
    return tuple(
        ReactionValue(
            support=r.support_id,
            force=output(r.force_n, "N"),
            moment=output(r.moment_nm, "N*m") if r.support_id in fixed else None,
        )
        for r in reactions
    )


def _judge(view: GraphView, mount: _Mount, solver: EquilibriumSolver) -> Observation | None:
    """The finding for one mount, or ``None`` if it holds under every reading of it."""
    if not mount.positioned:
        return judge_forces(view, mount.mount_id, mount.supports, mount.loads)
    found = _judge_reading(view, mount, solver, "weight")
    doubled = mixed(view, mount.loads)
    # A failure under the check's own reading stands: a second reading that happens to
    # balance must never un-block a mount. A pass needs every reading to balance.
    if doubled and found is None:
        others = [_judge_reading(view, mount, solver, r) for r in READINGS if r != "weight"]
        if any(o is not None for o in others):
            return _unchecked(
                mount,
                view.module_of(mount.mount_id),
                f"cannot be checked: {', '.join(doubled)} declare both a mass and a load_force, "
                "and the reactions balance under some readings of them and not others "
                "(the weight alone, the force alone, the two together)",
                tuple(f"load_force of {n}" for n in doubled),
            )
    if found is None and mount.unplaced_forces:
        return _unchecked(
            mount,
            view.module_of(mount.mount_id),
            "cannot be checked: it declares no "
            + ", ".join(
                f"mount_position of {m}, which has a load_force and so loads this mount"
                for m in mount.unplaced_forces
            ),
            tuple(f"mount_position of {m}" for m in mount.unplaced_forces),
        )
    if found is not None or not mount.unplaced_reactions:
        return found
    return _judge_stray_reactions(view, mount)


def _judge_reading(
    view: GraphView, mount: _Mount, solver: EquilibriumSolver, reading: Reading
) -> Observation | None:
    """The finding for a positioned mount read one way, or ``None`` if it holds."""
    module = view.module_of(mount.mount_id)
    try:
        declared = _declared(view, mount, reading)
    except _IncompleteError as exc:
        return _unchecked(mount, module, f"cannot be checked: it declares no {exc}", exc.names)
    except (UnitRefusedError, *PINT_ERRORS):
        names = (*mount.supports, *mount.loads)
        return _unchecked(mount, module, "has a quantity in a unit the unit check refuses", names)
    f_res, m_origin = _residuals(declared)
    miss = rounding_miss(declared)
    at = miss.x_m if miss is not None and miss.x_m is not None else None
    at = at if at is not None else reference_point(declared.problem)
    m_res = _about(at, f_res, m_origin)
    unstable = mechanism(declared.problem)
    if unstable is not None:
        return _refused(
            view, mount, module, declared, (f_res, m_res), unstable, "none: a mechanism", ()
        )
    balanced = miss is None
    try:
        solution = solver.solve(declared.problem)
        solved, method, determinate = solution.reactions, solution.solver, True
    except NotSolvableError:
        solved, method, determinate = (), "none: statics alone cannot split this load", False
    if not determinate and equilibrium.INDETERMINATE_MOUNTS == "resultant":
        method = "resultant equilibrium only; the split between supports needs FEA"
        if balanced:
            return _unchecked(
                mount,
                module,
                f"balances its loads in total; {SPLIT_UNVERIFIED}",
                tuple(f"reaction_force of {s}" for s in mount.supports),
            )
    elif determinate and balanced and _matches(declared.reactions, solved):
        return None
    blocked_for_fea = not determinate and equilibrium.INDETERMINATE_MOUNTS == "block"
    if miss is None:
        why = ""
    elif miss.what == "forces":
        why = (
            f"the forces miss by {output(f_res, 'N').value} N, and moving each declared "
            f"force and weight within half a unit in its third significant figure "
            f"explains at most {output(miss.bound, 'N').value} N"
        )
    else:
        where = _where(declared, at)
        why = (
            f"the moments about {where} miss by {output(m_res, 'N*m').value} N*m, and "
            f"moving each declared force, weight and moment within half a unit in its "
            f"third significant figure explains at most {output(miss.bound, 'N*m').value} N*m"
        )
    reason = (
        "the reaction split on this mount needs FEA, which is not available"
        if blocked_for_fea
        else f"its declared reactions are not the ones {method} finds, support by support"
        if determinate and balanced
        else f"its declared reactions do not balance its loads: {why}"
    )
    worst_is_moment = miss is not None and miss.what == "moments"
    return _refused(
        view,
        mount,
        module,
        declared,
        (f_res, m_res),
        reason,
        method,
        solved,
        worst_is_moment=worst_is_moment,
    )


def _refused(
    view: GraphView,
    mount: _Mount,
    module: str | None,
    declared: _Declared,
    residuals: tuple[Fraction, Fraction],
    reason: str,
    method: str,
    solved: tuple[Reaction, ...],
    *,
    worst_is_moment: bool = True,
) -> Observation:
    fixed = {s.node_id for s in declared.problem.supports if s.kind == "fixed"}
    residual_force, residual_moment = output(residuals[0], "N"), output(residuals[1], "N*m")
    return Observation(
        outcome="fail",
        node=mount.mount_id,
        module=module,
        value=residual_moment if worst_is_moment else residual_force,
        expected="declared reactions that balance the loads, within declared rounding",
        message=f"mount {mount.mount_id}: {reason}",
        details=EquilibriumDetails(
            solved=_values(solved, fixed),
            declared=_values(declared.reactions, fixed),
            residual_force=residual_force,
            residual_moment=residual_moment,
            solver=method,
        ),
        quantities=tuple(_reaction_ref(view, s) for s in mount.supports)[:3],
    )


def _reaction_ref(view: GraphView, support: str) -> QuantityRef:
    q = view.nodes[support].quantities["reaction_force"]
    return QuantityRef(node_id=support, name="reaction_force", value=q.value, unit=q.unit)


def _unchecked(mount: _Mount, module: str | None, why: str, names: tuple[str, ...]) -> Observation:
    return Observation(
        outcome="unchecked",
        node=mount.mount_id,
        module=module,
        value=None,
        expected=None,
        message=f"mount {mount.mount_id} {why}",
        details=UncheckedDetails(quantities=names),
    )


def _judge_stray_reactions(view: GraphView, mount: _Mount) -> Observation | None:
    """A placed mount that balanced, beside reactions with no position: forces only.

    The stray reactions push on the mount too. Counted, if the forces then miss, the
    mount fails; if they hold, the moments with those reactions cannot be judged.
    """
    module = view.module_of(mount.mount_id)
    stray = mount.unplaced_reactions
    names = tuple(f"support_position of {s}" for s in stray)
    attributed = shared(view, mount.mount_id, stray)
    why = (
        f"cannot be checked: {', '.join(stray)} declare a reaction_force on it and no "
        "support_position, so its moments cannot be judged"
    )
    if attributed:
        return _unchecked(mount, module, why, names)
    try:
        declared = _declared(view, mount)
        reactions = [r.force_n for r in declared.reactions]
        reactions += [_si(view, s, "reaction_force") for s in stray]
        stray_own = [
            _si(view, s, "mass") * STANDARD_GRAVITY
            for s in stray
            if "mass" in view.nodes[s].quantities
        ]
    except (UnitRefusedError, *PINT_ERRORS):
        return _unchecked(mount, module, why, names)
    loads = [ld.force_n for ld in declared.problem.loads]
    miss = force_miss(reactions, loads)
    # A reaction with no position may be the other sign or not vertical (a bumper's
    # push), so the forces fail only if no such reading of them balances.
    load_sets = [loads, [*loads, *stray_own]] if stray_own else [loads]
    if miss is None or explained(reactions, load_sets):
        return _unchecked(mount, module, why, names)
    how = f"counting the reactions of {', '.join(stray)}, which declare no position"
    return forces_refused(view, mount.mount_id, (*mount.supports, *stray), miss, how)


def _unread(view: GraphView, nodes: list[str], read: set[str]) -> list[Observation]:
    """A record for each node that declares statics quantities no mount reads."""
    found = []
    for node_id in nodes:
        if node_id in read:
            continue
        names = tuple(n for n in STATICS if n in view.nodes[node_id].quantities)
        if not names:
            continue
        found.append(
            Observation(
                outcome="unchecked",
                node=node_id,
                module=view.module_of(node_id),
                value=None,
                expected=None,
                message=(
                    f"{node_id} declares {', '.join(names)}, but no structure it belongs to "
                    "could be identified from its edges, so no balance reads it"
                ),
                details=UncheckedDetails(quantities=names),
            )
        )
    return found


def run(ctx: CheckContext) -> CheckRun:
    """Check every mount the attempt could have changed, or every mount at system scope.

    A mount is in scope at module scope when it, one of its members, or its module is
    a node the attempt affected: one it wrote, or one those name as their targets
    before or after the attempt, so a support removed from a mount brings the mount
    it left. A node in scope declaring a statics quantity that no mount reads is
    recorded as unchecked, so a balance nobody could read is never a silent pass.
    """
    view = ctx.view
    near = set(view.affected()) | set(view.modules_touched())
    every = mounts(view)
    found = [m for m in every if ctx.scope == "system" or near & {m.mount_id, *m.reads()}]
    solver = ctx.solver if ctx.solver is not None else ClosedFormSolver()
    judged = [(m, _judge(view, m, solver)) for m in found]
    observations = [o for _, o in judged if o is not None]
    # A mount recorded as unchecked was not judged, so it is not counted as evaluated.
    unchecked = sum(1 for o in observations if o.outcome == "unchecked")
    # A pass on forces alone is weaker than a placed one, so the record says how many.
    by_forces = sum(1 for m, o in judged if not m.positioned and o is None)
    in_scope = [n for n in view.nodes if ctx.scope == "system" or n in near]
    read = {n for m in every for n in m.reads()}
    observations += _unread(view, in_scope, read)
    tool = f"{solver.name}, with the declared-rounding allowance"
    if by_forces:
        tool += f"; {by_forces} passed on forces alone, with no positions declared"
    return CheckRun(
        tool=tool,
        evaluated=len(found) - unchecked,
        observations=tuple(observations),
    )
