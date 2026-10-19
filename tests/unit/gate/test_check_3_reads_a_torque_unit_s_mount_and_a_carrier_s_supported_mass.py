"""Check 3 reads two balances no mount reads: a torque unit's mount, a carrier's supported mass.

Each is read under every plausible reading: refused only when every reading misses, passed
only when every reading balances, unchecked otherwise. The hand-made errors here are the
kinds a writer makes: a reaction moment left at an old torque, a supported mass written in
the wrong unit or left stale after the carried mass changed, a value far from any split.
The readings that keep correct designs unrefused are held too: a gearmotor whose
``torque_peak`` is the motor's, so the mount reacts ``T r`` or the housing ``T (r - 1)``;
sibling carriers judged on the sum of their supported masses, each share unchecked; a
carrier whose supported mass is the whole of a subset of what names it. The named limits
(a cantilevered unit, a reaction or a supported mass written as a rated capacity, two
motors on one node) are pinned as refusals, so a change to them is seen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.check_equilibrium_loads import carriers, judge_loads, torque_units
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import EquilibriumDetails, Scope, UncheckedDetails

M = "mechanical"


def unit(
    torque: float, reaction: float, *, ratio: float | None = None, unit: str = "N*m"
) -> dict[str, Any]:
    q: dict[str, Any] = {"torque_peak": (torque, unit), "reaction_moment": (reaction, unit)}
    if ratio is not None:
        q["gear_ratio"] = (ratio, "dimensionless")
    return node(f"{M}.gearboxes", domain=M, quantities=q)


def run(tmp_path: Path, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return check_equilibrium.run(CheckContext(view=view, scope="system", bounds=load_bounds()))


def records(ran: Any, node_id: str) -> list[Any]:
    return [o for o in ran.observations if o.node == node_id]


# --- a torque unit ---------------------------------------------------------------------------


def test_a_reaction_moment_equal_to_the_peak_torque_passes_and_is_counted(tmp_path: Path) -> None:
    ran = run(tmp_path, unit(1.1, 1.1))
    assert records(ran, f"{M}.gearboxes") == [] and ran.evaluated == 1


def test_a_reaction_moment_left_at_an_old_torque_is_refused(tmp_path: Path) -> None:
    # The motors were swapped for a weaker pair and the mount's reaction was not rewritten.
    ran = run(tmp_path, unit(0.38, 1.1))
    (finding,) = records(ran, f"{M}.gearboxes")
    assert finding.outcome == "fail" and isinstance(finding.details, EquilibriumDetails)
    assert finding.value is not None and finding.value.unit == "N*m"
    assert "no reading of the unit's mount gives that" in finding.message
    assert finding.details.residual_force is None and finding.details.residual_moment is not None


def test_a_reaction_moment_in_kilogram_force_centimetres_is_compared_in_one_unit(
    tmp_path: Path,
) -> None:
    # 110 kgf*cm is 10.79 N*m: the same torque written in the sheet's unit passes.
    ran = run(tmp_path, unit(110, 110, unit="kgf*cm"))
    assert records(ran, f"{M}.gearboxes") == []
    (finding,) = records(run(tmp_path / "b", unit(38.7, 110, unit="kgf*cm")), f"{M}.gearboxes")
    assert finding.outcome == "fail"


def test_a_reaction_of_the_opposite_sign_is_the_same_balance(tmp_path: Path) -> None:
    assert records(run(tmp_path, unit(1.1, -1.1)), f"{M}.gearboxes") == []


def test_with_a_gear_ratio_the_gearbox_alone_is_a_second_reading_and_disagreement_is_unchecked(
    tmp_path: Path,
) -> None:
    # Ratio 30: the gearbox alone reacts 1.1 * (1 - 1/30) = 1.063 N*m, 3.3 % below the whole;
    # the whole reading balances and the gearbox reading does not, so the unit is unchecked.
    ran = run(tmp_path, unit(1.1, 1.1, ratio=30))
    (record,) = records(ran, f"{M}.gearboxes")
    assert record.outcome == "unchecked" and "readings disagree" in record.message
    assert isinstance(record.details, UncheckedDetails) and ran.evaluated == 0


@pytest.mark.parametrize(
    ("reaction", "reading"),
    [(3.0, "the mount reacting the output"), (2.9, "the housing alone")],
)
def test_a_gearmotor_whose_torque_peak_is_the_motor_s_is_unchecked_under_its_readings(
    tmp_path: Path, reaction: float, reading: str
) -> None:
    # torque_peak 0.1 N*m is the motor's shaft torque and the ratio is 30: the mount reacts
    # the output, 3 N*m, or the housing alone reacts the output less the input, 2.9 N*m.
    # Either balances one reading and not the whole, so a correct gearmotor is unchecked.
    ran = run(tmp_path, unit(0.1, reaction, ratio=30))
    (record,) = records(ran, f"{M}.gearboxes")
    assert record.outcome == "unchecked" and reading in record.message
    assert "torque_peak the motor's" in record.message


@pytest.mark.parametrize(
    ("quantities", "limit"),
    [
        (
            {"torque_peak": (2, "N*m"), "mass": (0.5, "kg"), "reaction_moment": (2.49, "N*m")},
            "a cantilevered unit whose reaction adds the moment of its own weight",
        ),
        (
            {"torque_peak": (2, "N*m"), "reaction_moment": (5, "N*m")},
            "a reaction written as the mount's rated capacity",
        ),
        (
            {"torque_peak": (2, "N*m"), "reaction_moment": (4, "N*m")},
            "two motors on one node whose reaction is their sum",
        ),
    ],
)
def test_the_torque_unit_s_named_limits_are_refusals_and_pinned(
    tmp_path: Path, quantities: dict[str, Any], limit: str
) -> None:
    # Each is a correct design the readings cannot tell from an error; each is named in
    # the module's docstring, and the evaluation scores such a refusal as the stated limit.
    from physgate.gate import check_equilibrium_loads

    assert limit in " ".join((check_equilibrium_loads.__doc__ or "").split())
    (finding,) = records(
        run(tmp_path, node(f"{M}.motor", domain=M, quantities=quantities)), f"{M}.motor"
    )
    assert finding.outcome == "fail"


def test_a_ratio_cannot_un_block_a_reaction_that_matches_neither_reading(tmp_path: Path) -> None:
    (finding,) = records(run(tmp_path, unit(1.1, 0.5, ratio=30)), f"{M}.gearboxes")
    assert finding.outcome == "fail"


def test_a_torque_in_a_refused_unit_is_unchecked_never_passed(tmp_path: Path) -> None:
    (record,) = records(run(tmp_path, unit(1.1, 1.1, unit="N")), f"{M}.gearboxes")
    assert record.outcome == "unchecked" and "unit check refuses" in record.message


def test_a_reaction_moment_no_mount_reads_is_no_longer_recorded_as_read_by_nothing(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, unit(1.1, 1.1))
    assert not any("no structure" in o.message for o in ran.observations)


# --- a carrier ---------------------------------------------------------------------------


def robot(mass_g: float = 330) -> dict[str, Any]:
    return node(
        f"{M}.robot",
        kind="module",
        domain=M,
        quantities={"mass": (mass_g, "g")},
        constrains=[f"{M}.drivetrain", f"{M}.wheel_left", f"{M}.wheel_right"],
    )


def drivetrain(supported_g: float = 330) -> dict[str, Any]:
    return node(
        f"{M}.drivetrain",
        kind="module",
        domain=M,
        quantities={"supported_mass": (supported_g, "g")},
        constrains=[f"{M}.robot"],
    )


def wheel(side: str, supported_g: float = 165, mass_g: float = 19.8) -> dict[str, Any]:
    return node(
        f"{M}.wheel_{side}",
        domain=M,
        quantities={"mass": (mass_g, "g"), "supported_mass": (supported_g, "g")},
        constrains=[f"{M}.drivetrain"],
    )


def test_a_module_carrier_named_by_the_whole_robot_passes_on_the_whole(tmp_path: Path) -> None:
    ran = run(tmp_path, robot(), drivetrain(), wheel("left"), wheel("right"))
    assert records(ran, f"{M}.drivetrain") == []


def test_a_wheel_at_half_the_robot_is_unchecked_because_the_split_is_not_verified(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, robot(), drivetrain(), wheel("left"), wheel("right"))
    share, total = records(ran, f"{M}.wheel_left")
    assert share.outcome == "unchecked" and "its own share" in share.message
    assert "judged on mechanical.wheel_left" in share.message
    # The sum of the wheels' supported masses, 330 g, is the robot's whole and not the whole
    # with their own masses (369.6 g): the readings disagree, so the sum is unchecked too.
    assert total.outcome == "unchecked" and "sibling carriers" in total.message
    assert [o.outcome for o in records(ran, f"{M}.wheel_right")] == ["unchecked"]


def test_a_supported_mass_written_in_kilograms_for_grams_is_refused(tmp_path: Path) -> None:
    ran = run(
        tmp_path,
        robot(),
        node(
            f"{M}.drivetrain",
            kind="module",
            domain=M,
            quantities={"supported_mass": (330, "kg")},
            constrains=[f"{M}.robot"],
        ),
        wheel("left"),
        wheel("right"),
    )
    (finding,) = records(ran, f"{M}.drivetrain")
    assert finding.outcome == "fail" and isinstance(finding.details, EquilibriumDetails)
    assert finding.value is not None and finding.value.unit == "kg"


def test_a_supported_mass_left_stale_after_the_robot_grew_is_refused(tmp_path: Path) -> None:
    ran = run(tmp_path, robot(400), drivetrain(330), wheel("left"), wheel("right"))
    (finding,) = records(ran, f"{M}.drivetrain")
    assert finding.outcome == "fail"


def test_stale_wheel_shares_are_refused_on_their_sum_only_when_no_reading_matches(
    tmp_path: Path,
) -> None:
    # 165 g each was half of 330 g; with the robot at 400 g, the sum of the two shares,
    # 330 g, is neither 400 g nor 439.6 g (with the wheels' own 19.8 g each), so the stale
    # shares are refused, once, on the first wheel; the second wheel's share is unchecked.
    ran = run(tmp_path, robot(400), drivetrain(400), wheel("left"), wheel("right"))
    outcomes = sorted(o.outcome for o in records(ran, f"{M}.wheel_left"))
    assert outcomes == ["fail", "unchecked"]
    finding = next(o for o in records(ran, f"{M}.wheel_left") if o.outcome == "fail")
    assert "sibling carriers mechanical.wheel_right" in finding.message
    assert [o.outcome for o in records(ran, f"{M}.wheel_right")] == ["unchecked"]
    assert ran.evaluated == 2  # the drivetrain on the whole, the wheels' sum


def test_a_pack_on_two_brackets_passes_on_the_sum_of_their_supported_masses(
    tmp_path: Path,
) -> None:
    # An unequal split, 1.5 kg and 0.5 kg, is a plausible reading of a 2 kg pack on two
    # brackets: each bracket's share is unchecked, and their sum is judged and passes.
    pack = node(
        "electrical.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.b1", f"{M}.b2"]
    )
    b1 = node(f"{M}.b1", domain=M, quantities={"supported_mass": (1.5, "kg")})
    b2 = node(f"{M}.b2", domain=M, quantities={"supported_mass": (0.5, "kg")})
    ran = run(tmp_path, pack, b1, b2)
    assert [o.outcome for o in records(ran, f"{M}.b1")] == ["unchecked"]
    assert [o.outcome for o in records(ran, f"{M}.b2")] == ["unchecked"]
    assert ran.evaluated == 1
    stale = node(f"{M}.b2", domain=M, quantities={"supported_mass": (0.2, "kg")})
    ran = run(tmp_path / "b", pack, b1, stale)
    assert sorted(o.outcome for o in records(ran, f"{M}.b1")) == ["fail", "unchecked"]


def test_a_carrier_whose_supported_mass_is_a_subset_of_what_names_it_is_unchecked(
    tmp_path: Path,
) -> None:
    # A constrains edge is not "is carried by": the wheel names the chassis for clearance,
    # the electronics name it as what carries them, and the chassis declares the latter.
    chassis = node(
        f"{M}.chassis", domain=M, quantities={"supported_mass": (1.0, "kg"), "mass": (0.8, "kg")}
    )
    electronics = node(
        "electrical.electronics", quantities={"mass": (1.0, "kg")}, constrains=[f"{M}.chassis"]
    )
    wheel_ = node(
        f"{M}.wheel", domain=M, quantities={"mass": (0.3, "kg")}, constrains=[f"{M}.chassis"]
    )
    (record,) = records(run(tmp_path, chassis, electronics, wheel_), f"{M}.chassis")
    assert record.outcome == "unchecked" and "a subset of what names it" in record.message
    assert "electrical.electronics" in record.message


def test_a_carrier_named_by_more_parts_than_the_subsets_read_is_unchecked(tmp_path: Path) -> None:
    from physgate.gate.check_equilibrium_loads import SUBSET_PARTS

    parts = [
        node(f"{M}.p{k:02d}", domain=M, quantities={"mass": (1, "kg")}, constrains=[f"{M}.deck"])
        for k in range(SUBSET_PARTS + 1)
    ]
    deck = node(f"{M}.deck", domain=M, quantities={"supported_mass": (3, "kg")})
    (record,) = records(run(tmp_path, deck, *parts), f"{M}.deck")
    assert record.outcome == "unchecked" and "more than the 16" in record.message


def test_a_supported_mass_written_as_a_rated_capacity_is_a_named_limit_and_refused(
    tmp_path: Path,
) -> None:
    from physgate.gate import check_equilibrium_loads

    assert "rated capacity" in (check_equilibrium_loads.__doc__ or "")
    pack = node("electrical.pack", quantities={"mass": (2, "kg")}, constrains=[f"{M}.bracket"])
    bracket = node(
        f"{M}.bracket", domain=M, quantities={"supported_mass": (5, "kg"), "mass": (0.1, "kg")}
    )
    (finding,) = records(run(tmp_path, pack, bracket), f"{M}.bracket")
    assert finding.outcome == "fail"


def test_a_carrier_nobody_names_is_unchecked(tmp_path: Path) -> None:
    lone = node(f"{M}.axle", domain=M, quantities={"supported_mass": (1, "kg")})
    (record,) = records(run(tmp_path, lone), f"{M}.axle")
    assert record.outcome == "unchecked" and "no weighted part names it" in record.message


def test_a_carrier_with_its_own_mass_counted_in_is_unchecked_not_refused(tmp_path: Path) -> None:
    # A bracket of 50 g carrying a 200 g pack and declaring 250 g: the whole with its own
    # mass balances, the whole without does not.
    pack = node("electrical.pack", quantities={"mass": (200, "g")}, constrains=[f"{M}.bracket"])
    bracket = node(
        f"{M}.bracket", domain=M, quantities={"mass": (50, "g"), "supported_mass": (250, "g")}
    )
    (record,) = records(run(tmp_path, pack, bracket), f"{M}.bracket")
    assert record.outcome == "unchecked" and "own mass" in record.message


def test_the_readers_find_every_unit_and_carrier_and_module_scope_limits_them(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", robot(), drivetrain(), wheel("left"), wheel("right"), unit(1.1, 1.1))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    assert torque_units(view) == [f"{M}.gearboxes"]
    assert carriers(view) == [f"{M}.drivetrain", f"{M}.wheel_left", f"{M}.wheel_right"]
    found, judged, read = judge_loads(view, {f"{M}.gearboxes"})
    assert found == [] and judged == 1 and read == {(f"{M}.gearboxes", "reaction_moment")}
    # A group of sibling carriers is judged once, on its first member in scope.
    found, judged, read = judge_loads(view, {f"{M}.wheel_right"})
    assert [o.node for o in found] == [f"{M}.wheel_right"] * 2 and judged == 0
    assert read == {(f"{M}.wheel_right", "supported_mass")}


def test_the_whole_gate_blocks_a_stale_reaction_moment_at_system_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", unit(0.38, 1.1))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["system"], "on")
    assert result.verdict == "fail" and result.failing_check == "equilibrium"


@pytest.mark.parametrize("scope", ["module", "system"])
def test_an_attempt_that_rewrites_the_robot_s_mass_brings_its_carriers_into_scope(
    tmp_path: Path, scope: Scope
) -> None:
    root = tmp_path / "g"
    base = graph(root, robot(), drivetrain(), wheel("left"), wheel("right"))
    graph(root, robot(400))
    view = GraphView.read(root, base_revision=base)
    ran = check_equilibrium.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))
    assert [o.outcome for o in records(ran, f"{M}.drivetrain")] == ["fail"]


# --- nothing the readings touch is passed unread ------------------------------------------


def test_a_reaction_force_beside_a_torque_unit_that_no_mount_reads_is_still_recorded(
    tmp_path: Path,
) -> None:
    # The torque reading reads the reaction moment and nothing else; the force the same node
    # declares, which no structure reads, is recorded as read by nothing, as before.
    stray = node(
        f"{M}.gearboxes",
        domain=M,
        quantities={
            "torque_peak": (1.1, "N*m"),
            "reaction_moment": (1.1, "N*m"),
            "reaction_force": (5, "N"),
        },
    )
    ran = run(tmp_path, stray)
    (record,) = records(ran, f"{M}.gearboxes")
    assert record.outcome == "unchecked" and "no structure" in record.message
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("reaction_force",)
    assert ran.evaluated == 1


def test_a_lone_carrier_gets_no_pass_record_from_the_gate_only_its_unchecked_one(
    tmp_path: Path,
) -> None:
    # A check that judged nothing and left something unchecked writes no pass: the runner's
    # "found nothing wrong (0 evaluated)" never stands beside an unchecked record.
    graph(tmp_path / "g", node(f"{M}.axle", domain=M, quantities={"supported_mass": (1, "kg")}))
    runs: tuple[list[Scope], ...] = (["system"], ["subtask", "module"])
    for scopes in runs:
        result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), scopes, "on")
        equilibrium = [c for c in result.checks if c.name == "equilibrium"]
        assert [c.outcome for c in equilibrium] == ["unchecked"], scopes
        assert result.verdict == "pass"
