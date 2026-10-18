"""Check 3 reads two balances no mount reads: a torque unit's mount, a carrier's supported mass.

Each is read under every plausible reading: refused only when every reading misses, passed
only when every reading balances, unchecked otherwise. The hand-made errors here are the
kinds a writer makes: a reaction moment left at an old torque, a supported mass written in
the wrong unit or left stale after the carried mass changed, a value far from any split.
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
from physgate.orchestrator.protocols import EquilibriumDetails, UncheckedDetails

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
    (record,) = records(ran, f"{M}.wheel_left")
    assert record.outcome == "unchecked" and "an equal share" in record.message


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


def test_a_stale_wheel_share_is_refused_only_when_no_reading_matches(tmp_path: Path) -> None:
    # 165 g was half of 330 g; with the robot at 400 g, neither 400 nor 200, with or without
    # the wheel's own 19.8 g, gives 165, so the stale share is refused.
    ran = run(tmp_path, robot(400), drivetrain(400), wheel("left"), wheel("right"))
    (finding,) = records(ran, f"{M}.wheel_left")
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
    assert found == [] and judged == 1 and read == {f"{M}.gearboxes"}


def test_the_whole_gate_blocks_a_stale_reaction_moment_at_system_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", unit(0.38, 1.1))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["system"], "on")
    assert result.verdict == "fail" and result.failing_check == "equilibrium"


@pytest.mark.parametrize("scope", ["module", "system"])
def test_an_attempt_that_rewrites_the_robot_s_mass_brings_its_carriers_into_scope(
    tmp_path: Path, scope: str
) -> None:
    root = tmp_path / "g"
    base = graph(root, robot(), drivetrain(), wheel("left"), wheel("right"))
    graph(root, robot(400))
    view = GraphView.read(root, base_revision=base)
    ran = check_equilibrium.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))
    assert [o.outcome for o in records(ran, f"{M}.drivetrain")] == ["fail"]
