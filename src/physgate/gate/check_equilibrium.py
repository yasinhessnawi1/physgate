"""Check 3, static equilibrium and load path: per module, and over the whole graph.

A mount is any node other nodes constrain as supports or as loads:

- a **support** carries ``support_position`` and declares its ``reaction_force``,
  and a ``reaction_moment`` if it is fixed;
- a **load** carries ``mount_position`` and either a ``mass`` (its weight, at
  standard gravity) or a ``load_force``, acting downward. A member with a mass
  and no ``mount_position`` loads the mount somewhere nobody said, so the mount
  is recorded as unchecked, naming it, rather than balanced without its weight.

The declared reactions are held to the loads: the sum of forces, and the sum of
moments about every support position, must each vanish within the rounding the
declared numbers can carry (the allowance in :mod:`physgate.gate.tolerances`,
made from that equation's own terms).
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
from physgate.gate.tolerances import holds_within_rounding, rounding_allowance
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
class _Moments:
    """The moment equation about one point: where, its residual, and its terms."""

    about: str
    x_m: Fraction
    residual: Fraction
    terms: list[Fraction]


def _about(declared: _Declared, label: str, x_m: Fraction) -> _Moments:
    problem = declared.problem
    at = {s.node_id: s.x_m for s in problem.supports}
    terms = (
        [r.force_n * (at[r.support_id] - x_m) for r in declared.reactions]
        + [r.moment_nm for r in declared.reactions]
        + [-ld.force_n * (ld.x_m - x_m) for ld in problem.loads]
    )
    return _Moments(label, x_m, sum(terms, Fraction(0)), terms)


def _ratio(m: _Moments) -> Fraction | None:
    """How far past its allowance a moment residual is; ``None`` for a miss with none."""
    allowance = rounding_allowance(m.terms)
    if allowance == 0:
        return None if m.residual != 0 else Fraction(0)
    return abs(m.residual) / allowance


def _sums(declared: _Declared) -> tuple[Fraction, list[Fraction], _Moments, bool]:
    """The force residual and terms, the worst moment equation, and whether all moments hold.

    The moment equation is held about **every support position**, each against
    the allowance made from its own terms. A mount in equilibrium is in
    equilibrium about every point, so this refuses nothing a correct declaration
    passes; but the allowance about any one point grows with the lever arms to
    it, and a support that carries nothing still lengthens the arms to the point
    it stands at. Held about every support, no support the declaration adds can
    widen the allowance about the others. A mount with no support is held about
    its loads' centroid.
    """
    problem = declared.problem
    force_terms = [r.force_n for r in declared.reactions] + [-ld.force_n for ld in problem.loads]
    points: dict[Fraction, str] = {}
    for support in problem.supports:
        points.setdefault(support.x_m, support.node_id)
    if not points:
        points[reference_point(problem)] = "the loads' centroid"
    about = [_about(declared, label, x) for x, label in points.items()]
    failing = [m for m in about if not holds_within_rounding(m.residual, m.terms)]
    candidates = failing or about
    worst = max(candidates, key=lambda m: (_ratio(m) is None, _ratio(m) or 0))
    return sum(force_terms, Fraction(0)), force_terms, worst, not failing


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
    f_res, f_terms, moments, moments_hold = _sums(declared)
    m_res, m_terms = moments.residual, moments.terms
    unstable = mechanism(declared.problem)
    if unstable is not None:
        return _refused(
            view, mount, module, declared, (f_res, m_res), unstable, "none: a mechanism", ()
        )
    balanced = holds_within_rounding(f_res, f_terms) and moments_hold
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
    f_allow = output(rounding_allowance(f_terms), "N").value
    m_allow = output(rounding_allowance(m_terms), "N*m").value
    reason = (
        "the reaction split on this mount needs FEA, which is not available"
        if blocked_for_fea
        else f"its declared reactions are not the ones {method} finds, support by support"
        if determinate and balanced
        else (
            f"its declared reactions do not balance its loads: the forces miss by "
            f"{output(f_res, 'N').value} N (rounding allows {f_allow} N) and the moments by "
            f"{output(m_res, 'N*m').value} N*m (rounding allows {m_allow} N*m) about "
            f"{moments.about} at {output(moments.x_m, 'm').value} m"
        )
    )
    worst_is_moment = not moments_hold
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
