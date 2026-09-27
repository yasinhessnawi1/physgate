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
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from physgate.gate import equilibrium
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


@dataclass(frozen=True)
class _Mount:
    mount_id: str
    supports: tuple[str, ...]
    loads: tuple[str, ...]
    #: Members with a mass and no ``mount_position``: weight the mount carries
    #: somewhere nobody said, so its balance cannot be checked.
    unplaced: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Declared:
    problem: MountProblem
    reactions: tuple[Reaction, ...]


class _IncompleteError(Exception):
    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(", ".join(names))
        self.names = names


def mounts(view: GraphView) -> list[_Mount]:
    """Every node that others constrain as supports or loads, in id order."""
    found = []
    for node_id in view.nodes:
        members = view.constrained_by(node_id)
        supports = tuple(m for m in members if "support_position" in view.nodes[m].quantities)
        loads = tuple(
            m for m in members if "mount_position" in view.nodes[m].quantities and m not in supports
        )
        unplaced = tuple(
            m
            for m in members
            if "mass" in view.nodes[m].quantities and m not in supports and m not in loads
        )
        if supports or loads:
            found.append(_Mount(node_id, supports, loads, unplaced))
    return found


def _si(view: GraphView, node: str, name: str) -> Fraction:
    return measured(view, TermRef(node, name)).magnitude


def _declared(view: GraphView, mount: _Mount) -> _Declared:
    """The mount as the graph declares it, in newtons and metres.

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
        q = view.nodes[ld].quantities
        if "mass" in q:
            force = _si(view, ld, "mass") * STANDARD_GRAVITY
        elif "load_force" in q:
            force = _si(view, ld, "load_force")
        else:
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
    module = view.module_of(mount.mount_id)
    try:
        declared = _declared(view, mount)
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


def run(ctx: CheckContext) -> CheckRun:
    """Check every mount the attempt could have changed, or every mount at system scope.

    A mount is in scope at module scope when it, one of its supports or loads, or
    its module is a node the attempt affected: one it wrote, or one those name as
    their targets before or after the attempt, so a support removed from a mount
    brings the mount it left.
    """
    view = ctx.view
    near = set(view.affected()) | set(view.modules_touched())
    found = [
        m
        for m in mounts(view)
        if ctx.scope == "system" or near & {m.mount_id, *m.supports, *m.loads}
    ]
    solver = ctx.solver if ctx.solver is not None else ClosedFormSolver()
    observations = [o for o in (_judge(view, m, solver) for m in found) if o is not None]
    # A mount recorded as unchecked was not judged, so it is not counted as evaluated.
    unchecked = sum(1 for o in observations if o.outcome == "unchecked")
    return CheckRun(
        tool=f"{solver.name}, with the declared-rounding allowance",
        evaluated=len(found) - unchecked,
        observations=tuple(observations),
    )
