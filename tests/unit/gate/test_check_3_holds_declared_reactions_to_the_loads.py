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
    assert "miss by -0.980665 N*m" in finding.message
    assert "explains at most 0.004903325 N*m" in finding.message


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


def test_a_mount_whose_forces_miss_while_its_moments_balance_is_refused(tmp_path: Path) -> None:
    # Standoffs at -0.1 and 0.1 m and the load at 0: the moments balance for any
    # equal pair, so only the force sum can catch the wrong total.
    ran = check(
        tmp_path,
        support("standoff_a", -0.1, 3),
        support("standoff_b", 0.1, 3),
        load("pcb", 0, 1),
    )
    (finding,) = ran.observations
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_force.value == pytest.approx(6 - 9.80665)
    # Refused by the sums, not only by the split the closed form finds. About the
    # centroid the moments balance; about each support the missing force has an arm.
    assert "the forces miss by" in finding.message


def test_an_indeterminate_mount_whose_moments_balance_but_forces_do_not_is_refused(
    tmp_path: Path,
) -> None:
    # Four standoffs symmetric about the load: equal reactions balance the moments
    # whatever their size, so the force sum is the only thing that can refuse this.
    symmetric = [("a", -0.15), ("b", -0.05), ("c", 0.05), ("d", 0.15)]
    ran = check(
        tmp_path,
        *(support(f"standoff_{n}", x, 5) for n, x in symmetric),
        load("pcb", 0, 4),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail"
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_force.value == pytest.approx(20 - 4 * 9.80665)


def test_only_the_mounts_the_attempt_touched_are_checked(tmp_path: Path) -> None:
    root = tmp_path / "g"
    head = graph(
        root,
        mount(),
        support("bearing", 0, 9.80665, moment=0),  # an earlier imbalance, not this attempt's
        load("wheel", 0.1, 1),
        node("mechanical.arm", domain="mechanical", kind="module"),
    )
    graph(root, node("mechanical.clip", domain="mechanical", constrains=["mechanical.arm"]))
    view = GraphView.read(root, base_revision=head)
    ctx = CheckContext(view=view, scope="module", bounds=load_bounds())
    ran = check_equilibrium.run(ctx)
    assert ran.observations == () and ran.evaluated == 0


# --- where the mount sits changes nothing ------------------------------------------------


def shifted(offset: int, *payloads: dict[str, Any]) -> list[dict[str, Any]]:
    """The same mount moved ``offset`` metres along its axis."""
    moved = []
    for payload in payloads:
        quantities = dict(payload["quantities"])
        for name in ("support_position", "mount_position"):
            if name in quantities:
                value = quantities[name]["value"]
                quantities[name] = {**quantities[name], "value": value + offset}
        moved.append({**payload, "quantities": quantities})
    return moved


@pytest.mark.parametrize("offset", [0, 1000])
def test_all_the_weight_on_the_far_standoff_is_refused_wherever_the_plate_sits(
    tmp_path: Path, offset: int
) -> None:
    # 1 kg over the standoff at 0.2 m, the whole reaction declared on the one at 0:
    # the forces balance and the moments miss by 1.96 N*m. About the axis's origin a
    # plate 1000 m away was allowed 98 N*m of error, and passed.
    ran = check(
        tmp_path,
        *shifted(
            offset,
            support("standoff_a", 0, 9.80665),
            support("standoff_b", 0.1, 0),
            support("standoff_c", 0.2, 0),
            load("pcb", 0.2, 1),
        ),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "do not balance" in finding.message
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_moment.value == pytest.approx(-1.96133)


@pytest.mark.parametrize("offset", [0, 1000])
def test_a_single_pin_with_its_load_off_the_pin_is_refused_as_unstable(
    tmp_path: Path, offset: int
) -> None:
    # The declared force balances the weight, but nothing resists its moment.
    ran = check(tmp_path, *shifted(offset, support("standoff_a", 0, 9.80665), load("pcb", 0.1, 1)))
    (finding,) = ran.observations
    assert finding.outcome == "fail"
    assert "unstable: a single pin cannot resist a moment" in finding.message
    assert "FEA" not in finding.message
    assert isinstance(finding.details, EquilibriumDetails) and finding.details.solved == ()


def test_pins_at_one_point_with_the_load_off_it_are_unstable_even_under_the_block_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(equilibrium, "INDETERMINATE_MOUNTS", "block")
    ran = check(
        tmp_path,
        support("standoff_a", 0.3, 4.903325),
        support("standoff_b", 0.3, 4.903325),
        load("pcb", 0.1, 1),
    )
    (finding,) = ran.observations
    assert "unstable: pins at one point cannot resist a moment" in finding.message


def test_a_single_pin_directly_under_its_load_is_solved_and_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, support("standoff_a", 0.1, 9.81), load("pcb", 0.1, 1))
    assert ran.observations == () and ran.evaluated == 1


def test_a_cantilever_far_from_the_origin_declaring_no_moment_is_still_refused(
    tmp_path: Path,
) -> None:
    ran = check(
        tmp_path, *shifted(1000, support("bearing", 0, 9.80665, moment=0), load("wheel", 0.1, 1))
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail"
    assert "miss by -0.980665 N*m" in finding.message
    assert "explains at most 0.004903325 N*m" in finding.message


def test_moments_are_taken_about_the_supports_centroid() -> None:
    plate = MountProblem(
        "m",
        (Support("a", "pin", Fraction(1000)), Support("b", "pin", Fraction(1002, 1))),
        (Load("l", Fraction(10), Fraction(1001)),),
    )
    assert equilibrium.reference_point(plate) == 1001
    assert equilibrium.mechanism(plate) is None


def test_a_mount_recorded_as_unchecked_is_not_counted_as_evaluated(tmp_path: Path) -> None:
    ran = check(
        tmp_path, *(support(f"standoff_{n}", x, 9.80665) for n, x in FOUR), load("pcb", 0.15, 4)
    )
    assert [o.outcome for o in ran.observations] == ["unchecked"] and ran.evaluated == 0


def test_a_member_with_a_mass_and_no_position_leaves_the_mount_unchecked(tmp_path: Path) -> None:
    # The board balances on the bearing; the 5 kg pack weighs on the plate too,
    # at a place nobody wrote, so the balance cannot be checked without it.
    pack = node(
        "mechanical.battery_pack",
        domain="mechanical",
        quantities={"mass": (5, "kg")},
        constrains=[MOUNT],
    )
    ran = check(tmp_path, support("bearing", 0, 9.80665, moment=0), load("board", 0, 1), pack)
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0
    assert "mount_position of mechanical.battery_pack, which has a mass" in record.message


def test_a_module_whose_members_have_masses_and_no_supports_is_not_a_mount(
    tmp_path: Path,
) -> None:
    member = node("mechanical.arm", domain="mechanical", quantities={"mass": (1, "kg")})
    ran = check(tmp_path, {**member, "constrains": [MOUNT]})
    assert ran.observations == () and ran.evaluated == 0


def test_a_mount_whose_moments_hold_about_its_one_support_but_forces_miss_is_refused(
    tmp_path: Path,
) -> None:
    # The load stands on the fixed support: every lever arm is zero, so only the
    # force sum can refuse a declared 5 N against a 9.80665 N weight.
    ran = check(tmp_path, support("bearing", 0, 5, moment=0), load("wheel", 0, 1))
    (finding,) = ran.observations
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_moment.value == 0
    assert finding.details.residual_force.value == pytest.approx(5 - 9.80665)


# --- moments about every support: a support that carries nothing widens nothing --------

W = 9.80665


def plate(
    *supports: tuple[str, float, float], loads: tuple[tuple[str, float, float], ...]
) -> list[dict[str, Any]]:
    return [support(n, x, f) for n, x, f in supports] + [load(n, x, kg) for n, x, kg in loads]


def test_a_far_support_carrying_nothing_does_not_widen_the_allowance(tmp_path: Path) -> None:
    # All the weight declared on the standoff at 0 while the
    # load stands at 0.2 m, plus a fourth support at 1000 m declaring 0 N. About
    # the centroid the allowance grew to about 25 N*m; about the standoff at 0 it
    # is 0.0098 N*m, and the 1.96 N*m miss is refused there.
    ran = check(
        tmp_path,
        *plate(
            ("standoff_a", 0, W),
            ("standoff_b", 0.1, 0),
            ("standoff_c", 0.2, 0),
            ("standoff_far", 1000, 0),
            loads=(("pcb", 0.2, 1),),
        ),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "do not balance" in finding.message
    assert isinstance(finding.details, EquilibriumDetails)
    assert abs(finding.details.residual_moment.value) == pytest.approx(1.96133)


def test_pins_at_one_point_with_a_far_empty_pin_are_refused(tmp_path: Path) -> None:
    # Two pins at 0 share the weight of a load 0.1 m away, and a
    # pin at 1000 m declares 0 N. The far pin makes the pins stand at two points,
    # so this is no longer the mechanism rule's; the moments about the pins at 0
    # miss by 0.98 N*m against an allowance of 0.0049 N*m.
    ran = check(
        tmp_path,
        *plate(
            ("standoff_a", 0, W / 2),
            ("standoff_b", 0, W / 2),
            ("standoff_far", 1000, 0),
            loads=(("pcb", 0.1, 1),),
        ),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "do not balance" in finding.message
    assert "about mechanical.standoff_a at 0 m" in finding.message


def test_a_far_support_that_carries_its_share_passes(tmp_path: Path) -> None:
    # Supports at 0, 500 and 1000 m under a 1 kg load at 500 m, declared to three
    # figures as a quarter, a half and a quarter: balanced about every support.
    ran = check(
        tmp_path,
        *plate(
            ("standoff_a", 0, 2.45),
            ("standoff_b", 500, 4.90),
            ("standoff_c", 1000, 2.45),
            loads=(("pcb", 500, 1),),
        ),
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "balances its loads in total" in record.message


def test_a_determinate_plate_with_a_far_support_carrying_its_share_passes(
    tmp_path: Path,
) -> None:
    # Two pins at 0 and 1000 m, the load at 250 m: 7.35 N and 2.45 N to three figures.
    ran = check(
        tmp_path,
        *plate(("standoff_a", 0, 7.35), ("standoff_b", 1000, 2.45), loads=(("pcb", 250, 1),)),
    )
    assert ran.observations == () and ran.evaluated == 1


# --- the rounding model per number: can each declared value's own slack balance it? ----


def far_pair(offset: float = 0) -> list[dict[str, Any]]:
    """All the weight on the wrong standoff, plus 1000 kg standing on its own support at 1000 m."""
    return plate(
        ("standoff_a", offset + 0, W),
        ("standoff_b", offset + 0.1, 0),
        ("standoff_c", offset + 0.2, 0),
        ("standoff_far", offset + 1000, 1000 * 9.80665),
        loads=(("pcb", offset + 0.2, 1), ("ballast", offset + 1000, 1000)),
    )


def test_a_smaller_far_pair_cannot_explain_the_miss_and_is_refused(tmp_path: Path) -> None:
    # 10 kg standing on a support at 10 m. Its slack, 0.49 N, would have to
    # move by 0.196 N and the near standoff's by the same to balance, and the near
    # standoff's slack is 0.049 N: no change within rounding explains it.
    ran = check(
        tmp_path,
        *plate(
            ("standoff_a", 0, W),
            ("standoff_b", 0.1, 0),
            ("standoff_c", 0.2, 0),
            ("standoff_far", 10, 98.0665),
            loads=(("pcb", 0.2, 1), ("ballast", 10, 10)),
        ),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "do not balance" in finding.message


def test_a_heavy_far_pair_is_explained_by_rounding_and_the_witness_balances_exactly() -> None:
    # The far pair under the rounding model: each declared number is true to half a unit in
    # its third significant figure. Moving the far reaction up by 0.00196 N (its
    # slack is 49 N) and the near one down by the same (its slack is 0.049 N)
    # balances forces and moments exactly, so the per-number model cannot refuse
    # it. What it cannot verify, the split, is recorded as unchecked.
    w = Fraction("9.80665")
    shift = Fraction("0.00196133")
    supports = ((Fraction(0), w - shift), (Fraction(1000), 1000 * w + shift))
    loads = ((Fraction("0.2"), w), (Fraction(1000), 1000 * w))
    assert sum(r for _, r in supports) - sum(f for _, f in loads) == 0
    assert sum(r * x for x, r in supports) - sum(f * x for x, f in loads) == 0
    assert shift <= Fraction(5, 1000) * w and shift <= Fraction(5, 1000) * 1000 * w


@pytest.mark.parametrize(
    "case", ["far pair", "sound plate", "wrong plate", "wrong indeterminate plate"]
)
def test_the_verdict_does_not_depend_on_where_the_mount_sits(tmp_path: Path, case: str) -> None:
    def build(offset: float) -> list[dict[str, Any]]:
        if case == "far pair":
            return far_pair(offset)
        if case == "wrong indeterminate plate":
            # Three standoffs, so no closed form checks the split: only the balance.
            return plate(
                ("standoff_a", offset, W),
                ("standoff_b", offset + 0.1, 0),
                ("standoff_c", offset + 0.2, 0),
                loads=(("pcb", offset + 0.2, 1),),
            )
        split = (14.71, 4.903) if case == "sound plate" else (4.903, 14.71)
        return plate(
            ("standoff_a", offset, split[0]),
            ("standoff_b", offset + 0.2, split[1]),
            loads=(("battery", offset + 0.05, 2),),
        )

    near = check(tmp_path / "near", *build(0))
    far = check(tmp_path / "far", *build(1000))
    assert [o.outcome for o in near.observations] == [o.outcome for o in far.observations]
    assert near.evaluated == far.evaluated


def _aggregate_about_every_support_misses(declared: Any) -> bool:
    """The check this replaced: each support's moments against 0.005 of their terms."""
    problem = declared.problem
    at = {s.node_id: s.x_m for s in problem.supports}
    for x in {s.x_m for s in problem.supports}:
        terms = (
            [r.force_n * (at[r.support_id] - x) for r in declared.reactions]
            + [r.moment_nm for r in declared.reactions]
            + [-ld.force_n * (ld.x_m - x) for ld in problem.loads]
        )
        if abs(sum(terms, Fraction(0))) > Fraction(5, 1000) * sum(abs(t) for t in terms):
            return True
    return False


def test_holding_moments_about_every_support_adds_nothing_the_per_number_test_lacks() -> None:
    # Each support's aggregate test is the per-number test's edge normal to that
    # support's reaction, so every mount it refuses is refused already. Checked
    # over seeded random mounts, exact fractions throughout.
    import random

    rng = random.Random(20260927)
    refused_by_old = 0
    for _ in range(3000):
        n = rng.randint(1, 4)
        supports = tuple(
            Support(f"s{i}", rng.choice(["pin", "fixed"]), Fraction(rng.randint(-50, 50), 10))
            for i in range(n)
        )
        reactions = tuple(
            Reaction(
                s.node_id,
                Fraction(rng.randint(0, 400), 10),
                Fraction(rng.randint(-40, 40), 10) if s.kind == "fixed" else Fraction(0),
            )
            for s in supports
        )
        loads = tuple(
            Load(f"l{j}", Fraction(rng.randint(0, 400), 10), Fraction(rng.randint(-50, 50), 10))
            for j in range(rng.randint(1, 3))
        )
        declared = check_equilibrium._Declared(MountProblem("m", supports, loads), reactions)
        if _aggregate_about_every_support_misses(declared):
            refused_by_old += 1
            assert check_equilibrium.rounding_miss(declared) is not None, declared
    assert refused_by_old > 1000
