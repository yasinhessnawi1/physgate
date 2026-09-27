"""Check 3, static equilibrium and load path, per module.

A mount is any node other nodes constrain as supports or as loads:

- a **support** carries ``support_position`` and declares its ``reaction_force``,
  and a ``reaction_moment`` if it is fixed;
- a **load** carries ``mount_position`` and either a ``mass`` (its weight, at
  standard gravity) or a ``load_force``, acting downward.

The declared reactions are held to the loads: the sum of forces and the sum of
moments about the supports' centroid must each vanish, within the rounding the
declared numbers can carry (the allowance in :mod:`physgate.gate.tolerances`).
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
        if supports or loads:
            found.append(_Mount(node_id, supports, loads))
    return found


def _si(view: GraphView, node: str, name: str) -> Fraction:
    return measured(view, TermRef(node, name)).magnitude


def _declared(view: GraphView, mount: _Mount) -> _Declared:
    """The mount as the graph declares it, in newtons and metres.

    Raises:
        _IncompleteError: a support or load lacks what it needs.
        UnitRefusedError, pint errors: a quantity's unit is refused.
    """
    missing: list[str] = []
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


def _sums(declared: _Declared) -> tuple[Fraction, list[Fraction], Fraction, list[Fraction]]:
    """Force residual and terms, moment residual and terms, of the declared reactions.

    Moments are taken about the supports' centroid, so the terms, and the
    allowance made from them, are the mount's own lever arms wherever it sits.
    """
    problem = declared.problem
    ref = reference_point(problem)
    arm = {s.node_id: s.x_m - ref for s in problem.supports}
    force_terms = [r.force_n for r in declared.reactions] + [-ld.force_n for ld in problem.loads]
    moment_terms = (
        [r.force_n * arm[r.support_id] for r in declared.reactions]
        + [r.moment_nm for r in declared.reactions]
        + [-ld.force_n * (ld.x_m - ref) for ld in problem.loads]
    )
    return sum(force_terms, Fraction(0)), force_terms, sum(moment_terms, Fraction(0)), moment_terms


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
    f_res, f_terms, m_res, m_terms = _sums(declared)
    unstable = mechanism(declared.problem)
    if unstable is not None:
        return _refused(
            view, mount, module, declared, (f_res, m_res), unstable, "none: a mechanism", ()
        )
    balanced = holds_within_rounding(f_res, f_terms) and holds_within_rounding(m_res, m_terms)
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
            f"{output(m_res, 'N*m').value} N*m (rounding allows {m_allow} N*m)"
        )
    )
    worst_is_moment = not holds_within_rounding(m_res, m_terms)
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
    """Check every mount of the modules the attempt touched."""
    view = ctx.view
    near = set(view.own()) | set(view.modules_touched())
    found = [m for m in mounts(view) if near & {m.mount_id, *m.supports, *m.loads}]
    solver = ctx.solver if ctx.solver is not None else ClosedFormSolver()
    observations = [o for o in (_judge(view, m, solver) for m in found) if o is not None]
    return CheckRun(
        tool=f"{solver.name}, with the declared-rounding allowance",
        evaluated=len(found),
        observations=tuple(observations),
    )
