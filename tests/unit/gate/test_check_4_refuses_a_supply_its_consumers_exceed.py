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
    """A declared source: a battery declares the energy it stores and its discharge rating."""
    return node(
        "electrical.battery",
        quantities={
            "power_supply": (watts, "W"),
            "energy_capacity": (20, "W*h"),
            "max_discharge_power": (watts, "W"),
        },
    )


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
    assert ran.observations == () and ran.evaluated == 3


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
    assert at_module.observations == () and at_module.evaluated == 5
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
        battery(),
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
        node(
            f"electrical.s{i:02d}",
            kind="module",
            # Declared sources, so each is judged only as a supply to its consumers.
            quantities={"power_supply": (10_000, "W"), "rated_output_power": (10_000, "W")},
        )
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
    # Forty budgets, and forty supplies held to their ratings.
    assert ran.evaluated == 80 and ran.observations == ()
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


def test_a_stage_that_draws_from_a_supply_and_declares_no_draw_is_refused(
    tmp_path: Path,
) -> None:
    silent = node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (15, "W")},
        constrains=["electrical.battery"],
    )
    ran = check(tmp_path, "module", battery(), silent)
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.drive"
    assert "declares no power_draw from electrical.battery" in finding.message


def test_a_declared_source_with_nothing_upstream_is_not_held_to_a_draw(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", battery(20), consumer("mcu", 5, "battery"))
    assert ran.observations == () and ran.evaluated == 2


def test_a_bench_supply_is_a_declared_source(tmp_path: Path) -> None:
    bench = node(
        "electrical.bench",
        quantities={"power_supply": (30, "W"), "rated_output_power": (30, "W")},
    )
    ran = check(tmp_path, "system", bench, consumer("mcu", 5, "bench"))
    assert ran.observations == ()


def test_a_module_that_drops_its_upstream_edge_and_draw_is_refused_as_no_source(
    tmp_path: Path,
) -> None:
    # The drive supplied 15 W while drawing 5 W from a 5 W
    # battery, and was refused. Rewritten with no edge and no draw, it passed as a
    # source of its own. A node that supplies power is a declared source, or draws
    # what it supplies from one.
    payloads = (
        battery(5),
        node("electrical.drive", kind="module", quantities={"power_supply": (15, "W")}),
        consumer("motor", 15, "drive"),
    )
    for scope in ("module", "system"):
        ran = check(tmp_path / scope, scope, *payloads)
        (finding,) = ran.observations
        assert finding.outcome == "fail" and finding.node == "electrical.drive"
        assert "is not a declared source" in finding.message
        assert "draws from no supply" in finding.message


# --- a declared source is bounded by its rating ------------------------------------------


def test_a_bench_supply_that_delivers_more_than_its_rating_is_refused(tmp_path: Path) -> None:
    # Rated 5 W, supplying 15 W: the design contradicts its own rating.
    bench = node(
        "electrical.bench",
        quantities={"power_supply": (15, "W"), "rated_output_power": (5, "W")},
    )
    for scope in ("module", "system"):
        ran = check(tmp_path / scope, scope, bench, consumer("motor", 15, "bench"))
        (finding,) = ran.observations
        assert finding.outcome == "fail" and finding.node == "electrical.bench"
        assert "more than its declared bound of 5 W (rated_output_power 5 W) by 10 W" in (
            finding.message
        )


def test_a_battery_with_a_discharge_rating_that_covers_its_supply_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", battery(20), consumer("mcu", 20, "battery"))
    assert ran.observations == () and ran.evaluated == 2


def test_a_battery_supplying_past_its_discharge_rating_is_refused(tmp_path: Path) -> None:
    hot = node(
        "electrical.battery",
        quantities={
            "power_supply": (30, "W"),
            "energy_capacity": (20, "W*h"),
            "max_discharge_power": (20, "W"),
        },
    )
    (finding,) = check(tmp_path, "system", hot, consumer("mcu", 30, "battery")).observations
    assert finding.outcome == "fail" and "(max_discharge_power 20 W) by 10 W" in finding.message


def test_a_source_with_no_output_rating_is_unchecked_never_passed(tmp_path: Path) -> None:
    unrated = node(
        "electrical.battery",
        quantities={"power_supply": (20, "W"), "energy_capacity": (20, "W*h")},
    )
    ran = check(tmp_path, "system", unrated, consumer("mcu", 5, "battery"))
    (record,) = ran.observations
    assert record.outcome == "unchecked"
    assert "declares a source but no output rating (max_discharge_power)" in record.message
    assert "its supply is not bounded" in record.message


def token_sources(rating: float | None) -> tuple[dict[str, Any], ...]:
    """Modules supplying 25 W while drawing 2 W, each declaring a token 1 mWh store."""

    def stage(name: str, supply: int) -> dict[str, Any]:
        q: dict[str, tuple[float | int, str]] = {
            "power_supply": (supply, "W"),
            "power_draw": (1, "W"),
            "energy_capacity": (0.001, "W*h"),
        }
        if rating is not None:
            q["max_discharge_power"] = (rating, "W")
        return node(
            f"electrical.{name}", kind="module", quantities=q, constrains=["electrical.battery"]
        )

    return (
        battery(20),
        stage("drive", 15),
        stage("control", 10),
        consumer("motor", 15, "drive"),
        consumer("mcu", 10, "control"),
    )


@pytest.mark.parametrize("scope", ["module", "system"])
def test_a_token_energy_store_does_not_exempt_a_module_from_a_bound(
    tmp_path: Path, scope: Scope
) -> None:
    # The modules declare 1 mWh each, and no discharge rating: their supplies are
    # not bounded, which is recorded against each, never passed.
    ran = check(tmp_path / "bare", scope, *token_sources(None))
    unchecked = {o.node for o in ran.observations if o.outcome == "unchecked"}
    assert unchecked == {"electrical.drive", "electrical.control"}
    # With a 1 W rating each, supply is held to rating plus draw: 2 W, not 15 or 10.
    ran = check(tmp_path / "rated", scope, *token_sources(1))
    refused = {(o.node, o.value.value if o.value else None) for o in ran.observations}
    assert refused == {("electrical.drive", 13), ("electrical.control", 8)}


def test_a_source_that_also_draws_is_held_to_its_rating_plus_its_draw(tmp_path: Path) -> None:
    # A battery-backed module draws 1 W from the mains and supplies 15 W.
    mains = node(
        "electrical.mains",
        quantities={"power_supply": (100, "W"), "rated_output_power": (100, "W")},
    )

    def ups(rating: int) -> dict[str, Any]:
        return node(
            "electrical.ups",
            kind="module",
            quantities={
                "power_supply": (15, "W"),
                "power_draw": (1, "W"),
                "energy_capacity": (20, "W*h"),
                "max_discharge_power": (rating, "W"),
            },
            constrains=["electrical.mains"],
        )

    motor = consumer("motor", 15, "ups")
    (finding,) = check(tmp_path / "short", "system", mains, ups(10), motor).observations
    assert finding.node == "electrical.ups" and finding.value is not None
    assert finding.value.value == 4
    assert check(tmp_path / "enough", "system", mains, ups(14), motor).observations == ()


def test_a_source_that_also_draws_and_declares_no_rating_is_unchecked_not_passed(
    tmp_path: Path,
) -> None:
    # The same battery-backed module, drawing 1 W from the mains and supplying
    # 15 W, but its battery declares only the energy it stores, no discharge
    # rating. Drawing from an upstream supply must not exempt a declared source
    # from being bounded: with no rating catalogued, its supply is recorded
    # unchecked, never passed silently.
    mains = node(
        "electrical.mains",
        quantities={"power_supply": (100, "W"), "rated_output_power": (100, "W")},
    )
    ups = node(
        "electrical.ups",
        kind="module",
        quantities={
            "power_supply": (15, "W"),
            "power_draw": (1, "W"),
            "energy_capacity": (20, "W*h"),
        },
        constrains=["electrical.mains"],
    )
    motor = consumer("motor", 15, "ups")
    ran = check(tmp_path, "system", mains, ups, motor)
    assert all(o.outcome != "pass" for o in ran.observations)
    (unchecked,) = [o for o in ran.observations if o.outcome == "unchecked"]
    assert unchecked.node == "electrical.ups"
    assert "no output rating (max_discharge_power)" in unchecked.message


@pytest.mark.parametrize("stored", [0, -5])
def test_a_stored_energy_of_zero_or_less_is_refused_by_the_unit_check(
    tmp_path: Path, stored: int
) -> None:
    drive = node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (15, "W"), "energy_capacity": (stored, "W*h")},
    )
    graph(tmp_path / "g", drive, consumer("motor", 15, "drive"))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "fail" and result.failing_check == "units"
    (finding,) = [r for r in result.checks if r.outcome == "fail"]
    assert "an energy is never zero or negative" in finding.message
