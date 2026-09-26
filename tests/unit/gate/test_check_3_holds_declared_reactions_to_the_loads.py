"""Check 3: a mount's declared reactions against its loads, solved where statics can."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_equilibrium, equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.equilibrium import (
    ClosedFormSolver,
    EquilibriumSolver,
    Load,
    MountProblem,
    MountSolution,
    NotSolvableError,
    Reaction,
    Support,
)
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import EquilibriumDetails, UncheckedDetails

MOUNT = "mechanical.chassis_plate"


def mount() -> dict[str, Any]:
    return node(MOUNT, domain="mechanical", kind="module")


def support(
    name: str, x: float | int, force: float | int, moment: float | int | None = None
) -> dict[str, Any]:
    q: dict[str, tuple[float | int, str]] = {
        "support_position": (x, "m"),
        "reaction_force": (force, "N"),
    }
    if moment is not None:
        q["reaction_moment"] = (moment, "N*m")
    return node(f"mechanical.{name}", domain="mechanical", quantities=q, constrains=[MOUNT])


def load(name: str, x: float | int, kg: float | int) -> dict[str, Any]:
    return node(
        f"mechanical.{name}",
        domain="mechanical",
        quantities={"mount_position": (x, "m"), "mass": (kg, "kg")},
        constrains=[MOUNT],
    )


def check(
    tmp_path: Path, *payloads: dict[str, Any], solver: EquilibriumSolver | None = None
) -> Any:
    graph(tmp_path / "g", mount(), *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="module", bounds=load_bounds(), solver=solver)
    return check_equilibrium.run(ctx)


def test_the_setting_is_the_one_decided_resultant_equilibrium() -> None:
    assert equilibrium.INDETERMINATE_MOUNTS == "resultant"


# --- the cantilever: one fixed support ------------------------------------------------


def test_a_cantilever_declaring_no_moment_reaction_is_refused_with_reactions_and_residual(
    tmp_path: Path,
) -> None:
    # 1 kg at 0.1 m: the moment at the support is 0.980665 N*m; declared 0.
    ran = check(tmp_path, support("bearing", 0, 9.80665, moment=0), load("wheel", 0.1, 1))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == MOUNT
    details = finding.details
    assert isinstance(details, EquilibriumDetails)
    assert details.residual_moment.value == pytest.approx(-0.980665)
    assert details.residual_force.value == 0
    (solved,) = details.solved
    assert solved.force.value == pytest.approx(9.80665)
    assert solved.moment is not None and solved.moment.value == pytest.approx(0.980665)
    (declared,) = details.declared
    assert declared.moment is not None and declared.moment.value == 0
    assert "moments by -0.980665 N*m (rounding allows 0.004903325 N*m)" in finding.message


def test_a_cantilever_declaring_its_moment_to_three_figures_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, support("bearing", 0, 9.81, moment=0.981), load("wheel", 0.1, 1))
    assert ran.observations == () and ran.evaluated == 1


# --- plates: two standoffs are solved, four are not ------------------------------------


def test_a_balanced_two_standoff_plate_passes(tmp_path: Path) -> None:
    # 2 kg at 0.05 m on standoffs at 0 and 0.2 m: 14.709975 N and 4.903325 N.
    ran = check(
        tmp_path,
        support("standoff_a", 0, 14.71),
        support("standoff_b", 0.2, 4.903),
        load("battery", 0.05, 2),
    )
    assert ran.observations == ()


def test_a_two_standoff_plate_with_the_split_wrong_is_refused_with_the_solved_split(
    tmp_path: Path,
) -> None:
    # The totals balance (9.806 + 9.807 N), but the split is the wrong way round.
    ran = check(
        tmp_path,
        support("standoff_a", 0, 9.806),
        support("standoff_b", 0.2, 9.807),
        load("battery", 0.05, 2),
    )
    (finding,) = ran.observations
    assert isinstance(finding.details, EquilibriumDetails)
    solved = {r.support: r.force.value for r in finding.details.solved}
    assert solved["mechanical.standoff_a"] == pytest.approx(14.709975)
    assert solved["mechanical.standoff_b"] == pytest.approx(4.903325)


FOUR = [("a", 0.0), ("b", 0.1), ("c", 0.2), ("d", 0.3)]


def test_a_four_standoff_plate_whose_totals_balance_passes_with_the_split_unverified(
    tmp_path: Path,
) -> None:
    # 4 kg at 0.15 m, carried equally: the force and moment sums both balance.
    ran = check(
        tmp_path, *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR), load("pcb", 0.15, 4)
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked"
    assert "load split between supports unverified; needs FEA" in record.message
    assert isinstance(record.details, UncheckedDetails)
    assert len(record.details.quantities) == 4


def test_a_four_standoff_plate_whose_totals_do_not_balance_is_refused(tmp_path: Path) -> None:
    ran = check(tmp_path, *(support(f"standoff_{n}", x, 5) for n, x in FOUR), load("pcb", 0.15, 4))
    (finding,) = ran.observations
    assert finding.outcome == "fail"
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.solved == ()
    assert finding.details.residual_force.value == pytest.approx(20 - 4 * 9.80665)
    assert "needs FEA" in finding.details.solver


def test_with_the_block_setting_an_indeterminate_mount_is_refused_even_when_it_balances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(equilibrium, "INDETERMINATE_MOUNTS", "block")
    ran = check(
        tmp_path, *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR), load("pcb", 0.15, 4)
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail"
    assert "needs FEA, which is not available" in finding.message


# --- through the real gate --------------------------------------------------------------


def test_the_real_gate_blocks_the_cantilever_and_counts_the_unverified_split(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "c", mount(), support("bearing", 0, 9.80665, moment=0), load("wheel", 0.1, 1))
    refused = PhysicsGate().run(GraphView.read(tmp_path / "c", 0), ["module"], "on")
    assert refused.verdict == "fail" and refused.failing_check == "equilibrium"
    graph(
        tmp_path / "p",
        mount(),
        *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR),
        load("pcb", 0.15, 4),
    )
    passed = PhysicsGate().run(GraphView.read(tmp_path / "p", 0), ["module"], "on")
    assert passed.verdict == "pass"
    notes = [r for r in passed.checks if r.name == "equilibrium" and r.outcome == "unchecked"]
    assert len(notes) == 1 and "needs FEA" in notes[0].message


# --- incomplete mounts, and the solver boundary ----------------------------------------


def test_a_support_that_declares_no_reaction_is_unchecked(tmp_path: Path) -> None:
    bare = node(
        "mechanical.standoff_a",
        domain="mechanical",
        quantities={"support_position": (0, "m")},
        constrains=[MOUNT],
    )
    (record,) = check(tmp_path, bare, load("pcb", 0.1, 1)).observations
    assert record.outcome == "unchecked" and "reaction_force of mechanical.standoff_a" in (
        record.message
    )


def test_the_closed_form_refuses_what_statics_cannot_solve() -> None:
    four = MountProblem(
        "m",
        tuple(Support(f"s{i}", "pin", Fraction(i, 10)) for i in range(4)),
        (Load("l", Fraction(10), Fraction(1, 10)),),
    )
    with pytest.raises(NotSolvableError):
        ClosedFormSolver().solve(four)
    same_place = MountProblem(
        "m", (Support("a", "pin", Fraction(0)), Support("b", "pin", Fraction(0))), ()
    )
    with pytest.raises(NotSolvableError):
        ClosedFormSolver().solve(same_place)


@dataclass
class FixtureSolver:
    """A stand-in for a solver behind the boundary: it answers from a table."""

    answers: dict[str, MountSolution]

    @property
    def name(self) -> str:
        return "fixture answers"

    def solve(self, problem: MountProblem) -> MountSolution:
        if problem.mount_id not in self.answers:
            msg = "no fixture answer"
            raise NotSolvableError(msg, mount=problem.mount_id)
        return self.answers[problem.mount_id]


def test_another_solver_stands_behind_the_same_boundary(tmp_path: Path) -> None:
    fixture = FixtureSolver(
        {
            MOUNT: MountSolution(
                reactions=tuple(
                    Reaction(f"mechanical.standoff_{n}", Fraction("9.80665"), Fraction(0))
                    for n, _ in FOUR
                ),
                solver="fixture answers",
            )
        }
    )
    assert isinstance(fixture, EquilibriumSolver) and isinstance(
        ClosedFormSolver(), EquilibriumSolver
    )
    ran = check(
        tmp_path,
        *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR),
        load("pcb", 0.15, 4),
        solver=fixture,
    )
    # A solver that can split the load: the mount is solved, not left unverified.
    assert ran.observations == ()
    assert ran.tool.startswith("fixture answers")


def test_a_solved_split_is_held_support_by_support_not_only_in_total(tmp_path: Path) -> None:
    uneven = FixtureSolver(
        {
            MOUNT: MountSolution(
                reactions=(
                    Reaction("mechanical.standoff_a", Fraction("4"), Fraction(0)),
                    Reaction("mechanical.standoff_b", Fraction("15.2266"), Fraction(0)),
                    Reaction("mechanical.standoff_c", Fraction("15.2266"), Fraction(0)),
                    Reaction("mechanical.standoff_d", Fraction("4.7734"), Fraction(0)),
                ),
                solver="fixture answers",
            )
        }
    )
    ran = check(
        tmp_path,
        *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR),
        load("pcb", 0.15, 4),
        solver=uneven,
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "support by support" in finding.message
    assert isinstance(finding.details, EquilibriumDetails)
    assert [r.force.value for r in finding.details.solved] == [4, 15.2266, 15.2266, 4.7734]
