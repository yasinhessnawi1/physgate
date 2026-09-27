"""Check 4: every supply against what draws from it, at module and at system scope."""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_power
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.gate.symbolic import residual
from physgate.orchestrator.protocols import PowerDetails, Scope


def battery(watts: int = 20) -> dict[str, Any]:
    return node("electrical.battery", quantities={"power_supply": (watts, "W")})


def module(name: str, supply: int, draw: int) -> dict[str, Any]:
    return node(
        f"electrical.{name}",
        kind="module",
        quantities={"power_supply": (supply, "W"), "power_draw": (draw, "W")},
        constrains=["electrical.battery"],
    )


def consumer(name: str, watts: float | int, of: str, unit: str = "W") -> dict[str, Any]:
    return node(
        f"electrical.{name}",
        quantities={"power_draw": (watts, unit)},
        constrains=[f"electrical.{of}"],
    )


def check(tmp_path: Path, scope: Scope, *payloads: dict[str, Any], base: int = 0) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=base)
    return check_power.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


def test_a_module_whose_consumers_draw_more_than_its_supply_is_refused_with_the_deficit(
    tmp_path: Path,
) -> None:
    ran = check(
        tmp_path,
        "module",
        battery(),
        module("drive", supply=15, draw=15),
        consumer("motor_left", 9, "drive"),
        consumer("motor_right", 9.2, "drive"),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.drive"
    assert isinstance(finding.details, PowerDetails)
    assert (finding.details.deficit.value, finding.details.deficit.unit) == (3.2, "W")
    assert finding.details.contributing == (
        "electrical.drive",
        "electrical.motor_left",
        "electrical.motor_right",
    )
    assert "exceeds its supply (15 W) by 3.2 W" in finding.message


def test_a_balanced_module_passes(tmp_path: Path) -> None:
    ran = check(
        tmp_path,
        "module",
        battery(),
        module("drive", supply=15, draw=15),
        consumer("motor_left", 7.5, "drive"),
        consumer("motor_right", 7500, "drive", unit="mW"),
    )
    # Two: its consumers against its supply, and its supply against what it draws.
    assert ran.observations == () and ran.evaluated == 2


def test_modules_that_each_balance_but_not_together_pass_at_module_and_fail_at_system(
    tmp_path: Path,
) -> None:
    payloads = (
        battery(20),
        module("drive", supply=15, draw=15),
        module("control", supply=10, draw=10),
        consumer("motor_left", 15, "drive"),
        consumer("mcu", 10, "control"),
    )
    at_module = check(tmp_path / "m", "module", *payloads)
    assert at_module.observations == () and at_module.evaluated == 4
    at_system = check(tmp_path / "s", "system", *payloads)
    (finding,) = at_system.observations
    assert finding.node == "electrical.battery"
    assert isinstance(finding.details, PowerDetails)
    assert finding.details.deficit.value == 5
    assert set(finding.details.contributing) == {
        "electrical.battery",
        "electrical.control",
        "electrical.drive",
    }


def test_at_module_scope_only_the_modules_the_attempt_touched_are_balanced(tmp_path: Path) -> None:
    root = tmp_path / "g"
    head = graph(
        root,
        battery(),
        module("drive", supply=15, draw=15),
        consumer("motor_left", 30, "drive"),  # an earlier deficit, not this attempt's
        module("control", supply=10, draw=10),
    )
    graph(root, consumer("mcu", 5, "control"))
    view = GraphView.read(root, base_revision=head)
    ran = check_power.run(CheckContext(view=view, scope="module", bounds=load_bounds()))
    assert ran.observations == () and ran.evaluated == 2


def test_a_module_with_consumers_and_no_supply_is_unchecked_never_passed(tmp_path: Path) -> None:
    ran = check(
        tmp_path,
        "module",
        node("electrical.drive", kind="module"),
        consumer("motor_left", 9, "drive"),
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0


def test_the_balance_is_exact_and_no_rounding_is_credited(tmp_path: Path) -> None:
    ran = check(
        tmp_path,
        "module",
        module("drive", supply=15, draw=15),
        consumer("motor_left", 15.000001, "drive"),
    )
    (finding,) = ran.observations
    assert finding.outcome == "fail"


def test_the_residual_is_sympy_s_and_exact() -> None:
    assert residual([("supply", Fraction(15))], [("a", Fraction("9.2")), ("b", Fraction(9))]) == (
        Fraction("-3.2")
    )


def test_the_real_gate_refuses_the_joint_deficit_at_system_scope_and_blocks(tmp_path: Path) -> None:
    graph(
        tmp_path / "g",
        battery(20),
        module("drive", supply=15, draw=15),
        module("control", supply=10, draw=10),
    )
    view = GraphView.read(tmp_path / "g", 0)
    result = PhysicsGate().run(view, ["system"], "on")
    assert result.verdict == "fail" and result.failing_check == "power"
    assert PhysicsGate().run(view, ["module"], "on").verdict == "pass"


@pytest.mark.integration
def test_power_balance_over_a_dense_graph_stays_under_a_second(tmp_path: Path) -> None:
    # 40 supplies, and every one of 160 consumers drawing from all of them:
    # 6,400 edges, 128 times the reference workload's. A clock assertion, so it
    # is marked and excluded from the default run, and a red here is repeated
    # before it is believed.
    supplies = [
        node(f"electrical.s{i:02d}", kind="module", quantities={"power_supply": (10_000, "W")})
        for i in range(40)
    ]
    ids = [s["id"] for s in supplies]
    consumers = [
        node(f"electrical.c{i:03d}", quantities={"power_draw": (1.25, "W")}, constrains=ids)
        for i in range(160)
    ]
    graph(tmp_path / "g", *supplies, *consumers)
    view = GraphView.read(tmp_path / "g", 0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds())
    started = time.perf_counter()
    ran = check_power.run(ctx)
    took = time.perf_counter() - started
    assert ran.evaluated == 40 and ran.observations == ()
    print(f"power balance over 6,400 edges: {took:.4f} s")  # the measured number, for the record
    assert took < 1.0, f"power balance over 6,400 edges took {took:.3f} s"


# --- a stage that passes power on is held to what it takes in ---------------------------


def starved() -> tuple[dict[str, Any], ...]:
    # Each module supplies its members in full while drawing 1 W from the battery:
    # every supply balances, and the battery sees 2 W of the 25 W really drawn.
    return (
        battery(20),
        module("drive", supply=15, draw=1),
        module("control", supply=10, draw=1),
        consumer("motor", 15, "drive"),
        consumer("mcu", 10, "control"),
    )


@pytest.mark.parametrize("scope", ["module", "system"])
def test_modules_supplying_more_than_they_draw_upstream_are_refused(
    tmp_path: Path, scope: Scope
) -> None:
    ran = check(tmp_path, scope, *starved())
    found = {(o.node, o.value.value if o.value else None) for o in ran.observations}
    assert found == {("electrical.drive", 14), ("electrical.control", 9)}
    assert all(o.outcome == "fail" for o in ran.observations)
    drive = next(o for o in ran.observations if o.node == "electrical.drive")
    assert "supplies 15 W to what draws from it but draws only 1 W" in drive.message


def test_the_real_gate_blocks_the_starved_modules_at_module_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", *starved())
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["module"], "on")
    assert result.verdict == "fail" and result.failing_check == "power"


def test_a_stage_that_draws_from_a_supply_and_declares_no_draw_is_unchecked(
    tmp_path: Path,
) -> None:
    silent = node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (15, "W")},
        constrains=["electrical.battery"],
    )
    ran = check(tmp_path, "module", battery(), silent)
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "declares no power_draw" in record.message


def test_a_supply_with_nothing_upstream_is_not_held_to_a_draw(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", battery(20), consumer("mcu", 5, "battery"))
    assert ran.observations == () and ran.evaluated == 1
