"""Check 3 must not pass a structure whose balance it never read.

Two shapes of a broken balance pass today, both written by hand here:

- a structure whose supports declare their reactions and whose loads declare their
  masses, with no positions: no mount is formed, so the check evaluates nothing and
  the runner records a pass, although the vertical forces alone do not balance;
- a load that declares a ``load_force`` beside its ``mass``: the force is never read,
  so a balance that ignores it passes.

The positive control beside each keeps the fix from refusing a correct structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.result import CheckRun
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import EquilibriumDetails

BODY = "mechanical.body"


def body(kg: float) -> dict[str, Any]:
    return node(BODY, domain="mechanical", kind="module", quantities={"mass": (kg, "kg")})


def wheel(side: str, force: float, x: float | None = None) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {"reaction_force": (force, "N"), "mass": (0.02, "kg")}
    if x is not None:
        q["support_position"] = (x, "m")
    return node(f"mechanical.wheel_{side}", domain="mechanical", quantities=q, constrains=[BODY])


def part(
    name: str, kg: float, x: float | None = None, extra_n: float | None = None
) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {"mass": (kg, "kg")}
    if x is not None:
        q["mount_position"] = (x, "m")
    if extra_n is not None:
        q["load_force"] = (extra_n, "N")
    return node(f"electrical.{name}", quantities=q, constrains=[BODY])


def run(tmp_path: Path, *payloads: dict[str, Any]) -> CheckRun:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds(), solver=None)
    return check_equilibrium.run(ctx)


# 0.30 kg carried: 2.94 N, shared by two wheels.
UNPLACED = (part("cell_pack", 0.15), part("frame", 0.10), part("board", 0.05))


def test_a_structure_without_positions_whose_reactions_do_not_carry_its_loads_is_refused(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 2.40), *UNPLACED)
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["fail"]


def test_a_structure_without_positions_whose_reactions_carry_its_loads_is_not_refused(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 1.47), *UNPLACED)
    assert all(o.outcome != "fail" for o in ran.observations)


PLACED = (part("frame", 0.10, x=0.0), part("board", 0.05, x=0.0))


def test_a_load_force_declared_beside_a_mass_is_never_ignored(tmp_path: Path) -> None:
    # Balanced on the weights alone (0.30 kg, 2.94 N); the pack's extra 3 N is unread today.
    ran = run(
        tmp_path,
        body(0.34),
        wheel("left", 1.47, x=-0.05),
        wheel("right", 1.47, x=0.05),
        part("cell_pack", 0.15, x=0.0, extra_n=3.0),
        *PLACED,
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "both a mass and a load_force" in record.message


def test_a_placed_structure_that_balances_its_weights_still_passes(tmp_path: Path) -> None:
    ran = run(
        tmp_path,
        body(0.34),
        wheel("left", 1.47, x=-0.05),
        wheel("right", 1.47, x=0.05),
        part("cell_pack", 0.15, x=0.0),
        *PLACED,
    )
    assert ran.observations == () and ran.evaluated == 1


# --- the structure with no positions: guards against refusing a correct one -----------


def test_massless_supports_that_carry_the_loads_pass_with_one_mount_evaluated(
    tmp_path: Path,
) -> None:
    # With no support weight there is one reading, and it balances.
    light = [
        {**w, "quantities": {"reaction_force": w["quantities"]["reaction_force"]}}
        for w in (wheel("left", 1.47), wheel("right", 1.47))
    ]
    ran = run(tmp_path, body(0.30), *light, *UNPLACED)
    assert ran.observations == () and ran.evaluated == 1


def test_supports_with_weight_leave_a_balanced_structure_unchecked_never_passed(
    tmp_path: Path,
) -> None:
    # Whether the 1.47 N reactions carry the wheels' own 0.02 kg is not declared:
    # one reading balances and the other does not, so neither may decide a pass.
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 1.47), *UNPLACED)
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and ran.evaluated == 0


def test_reactions_that_also_carry_the_wheels_own_weight_are_unchecked_not_refused(
    tmp_path: Path,
) -> None:
    # The ground-contact convention: each wheel's reaction includes its own 0.02 kg,
    # so the reactions are 1.67 N each. Not the check's own reading, and honest.
    ran = run(tmp_path, body(0.34), wheel("left", 1.67), wheel("right", 1.67), *UNPLACED)
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and "some honest readings" in record.message


def test_a_component_structure_whose_own_weight_is_carried_is_unchecked_not_refused(
    tmp_path: Path,
) -> None:
    # A plate of 0.10 kg carrying 0.20 kg: the reactions carry all 0.30 kg.
    plate = node(BODY, domain="mechanical", kind="component", quantities={"mass": (0.10, "kg")})
    ran = run(
        tmp_path,
        plate,
        wheel("left", 1.47),
        wheel("right", 1.47),
        part("cell_pack", 0.15),
        part("board", 0.05),
    )
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked"


def test_a_member_inside_another_member_leaves_the_structure_unchecked(tmp_path: Path) -> None:
    # The board sits on the frame and on the body: its mass could be counted twice.
    board = node(
        "electrical.board",
        quantities={"mass": (0.05, "kg")},
        constrains=[BODY, "electrical.frame"],
    )
    ran = run(
        tmp_path,
        body(0.34),
        wheel("left", 1.0),
        wheel("right", 1.0),
        part("cell_pack", 0.15),
        part("frame", 0.10),
        board,
    )
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and "counted twice" in record.message


def test_a_reaction_that_names_two_mechanical_nodes_is_attributed_to_neither(
    tmp_path: Path,
) -> None:
    axle = node("mechanical.axle", domain="mechanical", kind="module")
    shared = {**wheel("left", 0.5), "constrains": [BODY, "mechanical.axle"]}
    ran = run(tmp_path, body(0.34), axle, shared, wheel("right", 0.5), *UNPLACED)
    assert all(o.outcome != "fail" for o in ran.observations)
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and "another mechanical node" in record.message


def test_a_structure_declaring_reactions_and_carrying_nothing_is_unchecked(tmp_path: Path) -> None:
    ran = run(tmp_path, body(0.04), wheel("left", 5.0), wheel("right", 5.0))
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and ran.evaluated == 0


def test_a_node_outside_the_mechanical_domain_is_never_held_to_a_force_sum(
    tmp_path: Path,
) -> None:
    # A reaction naming an electrical node says nothing about a structure.
    target = node("electrical.driver", quantities={"mass": (0.01, "kg")})
    reactor = node(
        "mechanical.post",
        domain="mechanical",
        quantities={"reaction_force": (9.0, "N")},
        constrains=["electrical.driver"],
    )
    ran = run(
        tmp_path, target, reactor, part("cell_pack", 0.15) | {"constrains": ["electrical.driver"]}
    )
    assert all(o.outcome != "fail" for o in ran.observations)
    assert [o.node for o in ran.observations] == ["mechanical.post"]


def test_a_failing_structure_without_positions_reports_its_force_residual_and_no_moment(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 2.40), *UNPLACED)
    (finding,) = [o for o in ran.observations if o.node == BODY]
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_moment is None
    assert finding.details.residual_force.value == pytest.approx(3.87 - 2.941995)
    assert "only the forces are judged" in finding.message


def test_the_structure_without_positions_is_judged_at_module_scope_when_a_reaction_moves(
    tmp_path: Path,
) -> None:
    root = tmp_path / "g"
    head = graph(root, body(0.34), wheel("left", 1.47), wheel("right", 1.47), *UNPLACED)
    graph(root, wheel("right", 2.40))
    view = GraphView.read(root, base_revision=head)
    ran = check_equilibrium.run(CheckContext(view=view, scope="module", bounds=load_bounds()))
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["fail"]


# --- a load with both a mass and a load_force: read every way ----------------------------


def placed(pack_n: float | None, reaction: float) -> tuple[dict[str, Any], ...]:
    return (
        body(0.34),
        wheel("left", reaction, x=-0.05),
        wheel("right", reaction, x=0.05),
        part("cell_pack", 0.15, x=0.0, extra_n=pack_n),
        *PLACED,
    )


def test_a_mount_failing_under_every_reading_keeps_the_record_it_has_today(
    tmp_path: Path,
) -> None:
    with_force = run(tmp_path / "a", *placed(3.0, 1.0))
    without = run(tmp_path / "b", *placed(None, 1.0))
    assert [o.outcome for o in with_force.observations] == ["fail"]
    assert with_force.observations == without.observations


def test_a_mount_failing_under_the_weight_stays_failed_though_another_reading_balances(
    tmp_path: Path,
) -> None:
    # Reactions of 2.97 N each carry 2.94 N of weight and the 3 N force together, but
    # a declared force must never un-block a mount the weight alone does not balance.
    with_force = run(tmp_path / "a", *placed(3.0, 2.97))
    without = run(tmp_path / "b", *placed(None, 2.97))
    assert [o.outcome for o in with_force.observations] == ["fail"]
    assert with_force.observations == without.observations


def test_a_load_with_a_mass_and_a_load_force_never_passes_on_the_weight_alone(
    tmp_path: Path,
) -> None:
    # Even a zero force leaves a reading (the force alone) under which the weight is
    # gone, so the mount that balances on its weights is unchecked, not passed.
    ran = run(tmp_path, *placed(0.0, 1.47))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0


# --- a reaction beside placed supports, with no position of its own ---------------------


def prop(force: float) -> dict[str, Any]:
    return node(
        "mechanical.prop",
        domain="mechanical",
        quantities={"reaction_force": (force, "N")},
        constrains=[BODY],
    )


def balanced_placed() -> tuple[dict[str, Any], ...]:
    return placed(None, 1.47)


def test_an_unplaced_reaction_that_breaks_the_force_sum_is_refused(tmp_path: Path) -> None:
    ran = run(tmp_path, *balanced_placed(), prop(1.0))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and "mechanical.prop" in finding.message
    assert isinstance(finding.details, EquilibriumDetails)
    assert finding.details.residual_moment is None


def test_an_unplaced_reaction_that_keeps_the_force_sum_leaves_the_moments_unchecked(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, *balanced_placed(), prop(0.0))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "support_position" in record.message


def test_an_unplaced_reaction_beside_a_mount_that_fails_keeps_today_s_record(
    tmp_path: Path,
) -> None:
    with_prop = run(tmp_path / "a", *placed(None, 1.0), prop(0.5))
    without = run(tmp_path / "b", *placed(None, 1.0))
    assert with_prop.observations == without.observations


def test_a_member_with_a_load_force_and_no_position_leaves_the_mount_unchecked(
    tmp_path: Path,
) -> None:
    pushed = node("electrical.cable", quantities={"load_force": (2.0, "N")}, constrains=[BODY])
    ran = run(tmp_path, *balanced_placed(), pushed)
    (record,) = ran.observations
    assert record.outcome == "unchecked"
    assert "mount_position of electrical.cable, which has a load_force" in record.message


# --- statics that no mount reads ----------------------------------------------------------


def test_a_reaction_declared_where_no_structure_reads_it_is_recorded_unchecked(
    tmp_path: Path,
) -> None:
    stand = node("mechanical.stand", domain="mechanical", quantities={"reaction_force": (3.0, "N")})
    ran = run(tmp_path, stand)
    (record,) = ran.observations
    assert record.outcome == "unchecked" and record.node == "mechanical.stand"
    assert ran.evaluated == 0


# --- each reading reads only what it needs; a weight failure always stands ---------------


@pytest.mark.parametrize("unit", ["kg", "degC", "flibbet"])
def test_a_load_force_in_a_refused_unit_never_un_blocks_an_attempt_the_weights_fail(
    tmp_path: Path, unit: str
) -> None:
    # The base balances on its weights; the attempt raises one reaction. The pack's load
    # force is given in a unit the unit check refuses and is not the attempt's own, so
    # only check 3 can refuse the attempt, and the weight reading never reads the force.
    root = tmp_path / "g"
    pack = part("cell_pack", 0.15, x=0.0)
    pack["quantities"]["load_force"] = {
        "value": 3.0,
        "unit": unit,
        "source": "datasheet",
        "written_by": "electrical",
    }
    base = (
        body(0.34),
        wheel("left", 1.47, x=-0.05),
        wheel("right", 1.47, x=0.05),
        pack,
        *PLACED,
    )
    head = graph(root, *base)
    graph(root, wheel("right", 2.40, x=0.05))
    view = GraphView.read(root, base_revision=head)
    result = PhysicsGate().run(view, ("subtask", "module"), "on")
    assert result.verdict == "fail" and result.failing_check == "equilibrium"


def test_a_stale_load_force_never_un_blocks_a_structure_without_positions(
    tmp_path: Path,
) -> None:
    # The pack grew from 0.15 to 0.25 kg and the reactions were left; its load force
    # still says the old weight, 1.471 N. Read by its weight, the structure fails.
    pack = part("cell_pack", 0.25, extra_n=1.471)
    ran = run(tmp_path, body(0.44), wheel("left", 1.47), wheel("right", 1.47), pack, *UNPLACED[1:])
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["fail"]


def massless(side: str, force: float) -> dict[str, Any]:
    payload = wheel(side, force)
    payload["quantities"] = {"reaction_force": payload["quantities"]["reaction_force"]}
    return payload


def test_the_force_sum_allowance_is_half_a_unit_in_each_term_s_third_figure(
    tmp_path: Path,
) -> None:
    # 0.30 kg is 2.941995 N. Missing by 0.030 N, the allowance is 0.005 of 5.913990 N,
    # 0.029570 N: refused. Missing by 0.029 N, it is 0.029565 N: held.
    over = run(
        tmp_path / "a",
        body(0.30),
        massless("left", 1.4859975),
        massless("right", 1.4859975),
        *UNPLACED,
    )
    under = run(
        tmp_path / "b",
        body(0.30),
        massless("left", 1.4854975),
        massless("right", 1.4854975),
        *UNPLACED,
    )
    (finding,) = [o for o in over.observations if o.node == BODY]
    assert finding.outcome == "fail"
    assert "explains at most 0.02956995 N" in finding.message
    assert [o for o in under.observations if o.node == BODY] == []


def test_a_wheel_naming_the_motor_it_drives_still_has_its_reaction_judged(
    tmp_path: Path,
) -> None:
    # A wheel names its electrical motor as well as the body: the motor holds nothing up,
    # so the reaction is still the body's, and an error in it is refused.
    motor = node("electrical.motor_left", quantities={"mass": (0.03, "kg")})
    left = {**wheel("left", 1.47), "constrains": [BODY, "electrical.motor_left"]}
    ran = run(tmp_path, body(0.34), motor, left, wheel("right", 2.40), *UNPLACED)
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["fail"]


def test_reactions_given_on_the_supports_rather_than_the_body_are_unchecked_not_refused(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.30), massless("left", -1.47), massless("right", -1.47), *UNPLACED)
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked"


def test_a_third_reaction_that_may_push_sideways_is_unchecked_not_refused(tmp_path: Path) -> None:
    bumper = massless("bumper", 5.0)
    ran = run(
        tmp_path, body(0.30), massless("left", 1.47), massless("right", 1.47), bumper, *UNPLACED
    )
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked"


def test_a_member_carrying_another_weighted_part_leaves_the_structure_unchecked(
    tmp_path: Path,
) -> None:
    # The pack sits on a bracket that sits on the body: the bracket presses with both.
    bracket = node(
        "mechanical.bracket",
        domain="mechanical",
        quantities={"mass": (0.05, "kg")},
        constrains=[BODY],
    )
    pack = node(
        "electrical.cell_pack", quantities={"mass": (0.15, "kg")}, constrains=["mechanical.bracket"]
    )
    ran = run(
        tmp_path,
        body(0.39),
        massless("left", 1.716),
        massless("right", 1.716),
        bracket,
        pack,
        *UNPLACED[1:],
    )
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked" and "carry other parts" in record.message


def test_a_pass_on_forces_alone_is_counted_apart_in_the_record(tmp_path: Path) -> None:
    ran = run(tmp_path, body(0.30), massless("left", 1.47), massless("right", 1.47), *UNPLACED)
    assert ran.observations == () and "1 passed on forces alone" in ran.tool


def test_a_load_with_a_mass_and_a_load_force_never_passes_a_structure_without_positions(
    tmp_path: Path,
) -> None:
    # The weights balance; read with the pack's 3 N force, they do not. Forces alone
    # pass a structure only if every reading of a doubled load balances.
    pack = part("cell_pack", 0.15, extra_n=3.0)
    ran = run(
        tmp_path, body(0.30), massless("left", 1.47), massless("right", 1.47), pack, *UNPLACED[1:]
    )
    (record,) = [o for o in ran.observations if o.node == BODY]
    assert record.outcome == "unchecked"


def test_module_scope_brings_in_a_mount_through_a_member_it_cannot_place(tmp_path: Path) -> None:
    # The attempt writes a sensor onto a tray; the tray weighs on the body with no
    # position. The body's balance is touched through the tray, so it is in scope.
    root = tmp_path / "g"
    tray = node(
        "mechanical.tray",
        domain="mechanical",
        kind="module",
        quantities={"mass": (0.10, "kg")},
        constrains=[BODY],
    )
    head = graph(root, *placed(None, 1.47), tray)
    graph(
        root,
        node(
            "electrical.sensor", quantities={"mass": (0.01, "kg")}, constrains=["mechanical.tray"]
        ),
    )
    view = GraphView.read(root, base_revision=head)
    ran = check_equilibrium.run(CheckContext(view=view, scope="module", bounds=load_bounds()))
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["unchecked"]
