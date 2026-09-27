"""Static equilibrium of a mount: the problem, the solver boundary, and the closed form.

A mount is a planar problem: forces along one vertical axis, positive upward;
positions along one horizontal axis, in metres; moments positive
counter-clockwise, so an upward force to the right of the reference point has a
positive moment. A load's force is its weight or declared force, acting
downward.

The check asks whether moving each declared force, weight and moment within its
own rounding (half a unit in its third significant figure) balances forces and
moments at once, with positions exact; ``rounding_miss`` in the check decides
it exactly. The answer does not depend on where the origin is, or on any point
the declaration could move. :func:`reference_point` is one more point the check
tests moments about, and the point it reports a mount with no support at.

A mount that cannot resist a moment at all, pins at one point with a load off
that point, is a mechanism, not a structure: :func:`mechanism` names it, and no
solver is asked to split its load.

The solver boundary is a Protocol so an FEA solver can stand behind it later
without the check changing: it takes the problem as reduced from the graph, not
a mesh, and a solver that meshes builds the mesh itself from the geometry the
nodes reference. What ships is the closed form, for the mounts statics can solve
alone: one fixed support, or two supports that resist no moment. It says so, by
raising, for any other mount, and never guesses a split.

What happens to a mount the closed form cannot solve is one decision, held in
:data:`INDETERMINATE_MOUNTS`:

- ``"resultant"`` (decided 26.09.2026): check what physics allows without the
  split, that the declared reactions' force and moment sums balance the loads.
  If they do not, the mount is refused; if they do, it passes with a record,
  counted and never silent, that the load split between supports is unverified
  and needs FEA;
- ``"block"``: refuse every such mount, because the split cannot be checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, Protocol, runtime_checkable

from physgate.gate.exceptions import GateError

#: What check 3 does with a mount the closed form cannot solve.
INDETERMINATE_MOUNTS: Literal["block", "resultant"] = "resultant"

#: Standard gravity, the conventional value adopted in 1901 by the 3rd CGPM, exactly, in m/s^2.
STANDARD_GRAVITY = Fraction("9.80665")


class NotSolvableError(GateError):
    """A mount this solver cannot solve: statically indeterminate, or not a structure."""


@dataclass(frozen=True)
class Support:
    """A support at ``x_m``: ``fixed`` resists a moment, ``pin`` does not."""

    node_id: str
    kind: Literal["fixed", "pin"]
    x_m: Fraction


@dataclass(frozen=True)
class Load:
    """A downward force of ``force_n`` newtons at ``x_m``."""

    node_id: str
    force_n: Fraction
    x_m: Fraction


@dataclass(frozen=True)
class Reaction:
    """What a support pushes back with: upward force, and counter-clockwise moment."""

    support_id: str
    force_n: Fraction
    moment_nm: Fraction


@dataclass(frozen=True)
class MountProblem:
    """One mount, as the graph declares it."""

    mount_id: str
    supports: tuple[Support, ...]
    loads: tuple[Load, ...]


@dataclass(frozen=True)
class MountSolution:
    """The reactions a solver found, and which solver found them."""

    reactions: tuple[Reaction, ...]
    solver: str


@runtime_checkable
class EquilibriumSolver(Protocol):
    """Anything that solves a mount's reactions: the closed form now, FEA later."""

    @property
    def name(self) -> str:
        """The solver's name and method, recorded with every result."""
        ...

    def solve(self, problem: MountProblem) -> MountSolution:
        """The reactions that hold ``problem`` in equilibrium.

        Raises:
            NotSolvableError: this solver cannot solve it.
        """
        ...


def reference_point(problem: MountProblem) -> Fraction:
    """A point of the mount: the centroid of its supports, else of its loads, else the origin.

    The check holds moments about every support; this is the point it uses for a
    mount with no support, which fails its force sum whatever the point.
    """
    points = [s.x_m for s in problem.supports] or [ld.x_m for ld in problem.loads]
    return sum(points, Fraction(0)) / len(points) if points else Fraction(0)


def mechanism(problem: MountProblem) -> str | None:
    """Why ``problem`` is a mechanism, or ``None`` if it is not one.

    Pins resist no moment, so pins that all stand at one point, with no fixed
    support, turn about that point under any load that is off it. Such a mount
    is unstable whatever its declared reactions say.
    """
    supports = problem.supports
    if not supports or any(s.kind == "fixed" for s in supports):
        return None
    if len({s.x_m for s in supports}) != 1:
        return None
    pivot = supports[0].x_m
    turning = sum((ld.force_n * (ld.x_m - pivot) for ld in problem.loads), Fraction(0))
    if turning == 0:
        return None
    what = "a single pin cannot" if len(supports) == 1 else "pins at one point cannot"
    return f"unstable: {what} resist a moment"


class ClosedFormSolver:
    """Statics alone: one fixed support, one pin under its loads, or two pins apart."""

    @property
    def name(self) -> str:
        """The solver's name, as results record it."""
        return "closed-form statics (sum of forces and moments)"

    def solve(self, problem: MountProblem) -> MountSolution:
        """Solve a statically determinate mount exactly.

        Raises:
            NotSolvableError: the mount is not one fixed support, one pin with its
                loads' moment about it zero, or two pins at two different positions.
        """
        total = sum((load.force_n for load in problem.loads), Fraction(0))
        supports = problem.supports
        if len(supports) == 1 and mechanism(problem) is None:
            (s,) = supports
            moment = sum((load.force_n * (load.x_m - s.x_m) for load in problem.loads), Fraction(0))
            return MountSolution(
                reactions=(Reaction(support_id=s.node_id, force_n=total, moment_nm=moment),),
                solver=self.name,
            )
        if (
            len(supports) == 2
            and all(s.kind == "pin" for s in supports)
            and supports[0].x_m != supports[1].x_m
        ):
            a, b = supports
            about_a = sum(
                (load.force_n * (load.x_m - a.x_m) for load in problem.loads), Fraction(0)
            )
            at_b = about_a / (b.x_m - a.x_m)
            return MountSolution(
                reactions=(
                    Reaction(support_id=a.node_id, force_n=total - at_b, moment_nm=Fraction(0)),
                    Reaction(support_id=b.node_id, force_n=at_b, moment_nm=Fraction(0)),
                ),
                solver=self.name,
            )
        msg = "statics alone cannot split the load between these supports"
        raise NotSolvableError(
            msg,
            mount=problem.mount_id,
            supports=str(len(supports)),
            fixed=str(sum(1 for s in supports if s.kind == "fixed")),
        )
