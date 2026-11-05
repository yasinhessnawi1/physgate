"""The gate judges what a real plan writes, with no check loosened (ARCH-080 amended).

G11's run 4 wrote three interface nodes and one sizing node. On those nodes, as they were written,
the magnitude check found nothing with a bound and the power check no relation: a consumer and its
supply sat on one node, and no envelope or range covered any name sizing wrote. Here the same
nodes, unchanged (``run4/``), are judged at the scopes sizing's opening pass now gets, and both
checks evaluate; the same node with a stall above its own limit is refused; a stall current no
limit bounds is recorded as unchecked, never passed; the two kinds whose span is a definition (an
efficiency, a duty cycle: 0 to 1) are held to it in every domain; and the inertial sensor's output-
data-rate range holds under its own name in firmware as in electrical.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude, check_power
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import (
    AttemptScope,
    GateResult,
    PassDetails,
    PowerDetails,
    Scope,
    UncheckedDetails,
)

RUN4 = Path(__file__).parent / "run4"
SIZING = "sizing.drivetrain_result"


def run4_interfaces() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads((RUN4 / "plan_interfaces.json").read_text())
    return loaded


def run4_sizing(**changes: tuple[float | int, str]) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RUN4 / f"{SIZING}.json").read_text())
    for name, (value, unit) in changes.items():
        payload["quantities"][name] = {
            **payload["quantities"][name],
            "value": value,
            "unit": unit,
        }
    return payload


def opening(tmp_path: Path, sizing: dict[str, Any]) -> GraphView:
    """Run 4's graph as sizing's opening attempt saw it: the plan's interfaces below its base."""
    root = tmp_path / "g"
    head = graph(root, *run4_interfaces())
    graph(root, sizing)
    return GraphView.read(root, base_revision=head)


#: The scopes sizing's opening pass is checked at (``Loop._scopes``).
OPENING: tuple[AttemptScope, ...] = ("subtask", "module")


def evaluated(result: GateResult, check: str, scope: str) -> int:
    """How many the check judged at ``scope``: its pass record's count, or 0 where it has none."""
    return sum(
        r.details.evaluated
        for r in result.checks
        if r.name == check
        and r.scope == scope
        and r.outcome == "pass"
        and isinstance(r.details, PassDetails)
    )


def test_run_4_s_own_sizing_node_is_judged_by_the_power_and_magnitude_checks(
    tmp_path: Path,
) -> None:
    view = opening(tmp_path, run4_sizing())
    assert view.own() == (SIZING,)
    result = PhysicsGate().run(view, OPENING, "on")
    assert result.verdict == "pass"
    # 1.35 A stall against the 1.8 A limit, both on sizing's own node.
    assert evaluated(result, "power", "module") >= 1
    # external_stage_efficiency 0.9, against the efficiency envelope.
    assert evaluated(result, "magnitude", "subtask") >= 1


def test_run_4_s_node_stalling_above_its_own_limit_is_refused_at_module_scope(
    tmp_path: Path,
) -> None:
    view = opening(tmp_path, run4_sizing(stall_current=(2.1, "A")))
    result = PhysicsGate().run(view, OPENING, "on")
    assert result.verdict == "fail" and result.failing_check == "power"
    failed = [r for r in result.checks if r.name == "power" and r.outcome == "fail"]
    assert failed and all(r.scope == "module" and r.blocking for r in failed)
    mine = [r for r in failed if r.node == SIZING]
    assert len(mine) == 1
    assert mine[0].value is not None
    assert (round(float(mine[0].value.value), 9), mine[0].value.unit) == (0.3, "A")


def power(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "p", *payloads)
    view = GraphView.read(tmp_path / "p", base_revision=0)
    return check_power.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


@pytest.mark.parametrize("scope", ["module", "system"])
def test_a_stall_and_a_limit_on_one_node_are_held_to_each_other(
    tmp_path: Path, scope: Scope
) -> None:
    one = node(
        "electrical.drive", quantities={"stall_current": (2.1, "A"), "current_limit": (1.8, "A")}
    )
    ran = power(tmp_path, scope, one)
    assert len(ran.observations) == 1
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.drive"
    assert isinstance(finding.details, PowerDetails)
    assert finding.value is not None and round(float(finding.value.value), 9) == 0.3
    assert ran.evaluated == 1


def test_a_stall_at_its_own_limit_passes_and_is_counted(tmp_path: Path) -> None:
    one = node(
        "electrical.drive", quantities={"stall_current": (1.8, "A"), "current_limit": (1.8, "A")}
    )
    ran = power(tmp_path, "system", one)
    assert ran.observations == () and ran.evaluated == 1


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param((), id="no-edge"),
        pytest.param(("electrical.board",), id="an-edge-to-a-node-with-no-limit"),
    ],
)
def test_a_stall_current_no_limit_bounds_is_recorded_unchecked(
    tmp_path: Path, edges: Sequence[str]
) -> None:
    board = node("electrical.board", quantities={"supply_voltage": (7.2, "V")})
    motor = node(
        "electrical.motor_left", quantities={"stall_current": (1.5, "A")}, constrains=edges
    )
    ran = power(tmp_path, "system", board, motor)
    unchecked = [o for o in ran.observations if o.outcome == "unchecked"]
    assert [o.node for o in unchecked] == ["electrical.motor_left"]
    assert isinstance(unchecked[0].details, UncheckedDetails)
    assert "current_limit" in unchecked[0].details.quantities
    assert ran.evaluated == 0


def test_a_stall_its_supply_bounds_is_not_also_recorded_unchecked(tmp_path: Path) -> None:
    driver = node("electrical.driver", quantities={"current_limit": (1.8, "A")})
    motor = node(
        "electrical.motor_left",
        quantities={"stall_current": (1.5, "A")},
        constrains=["electrical.driver"],
    )
    ran = power(tmp_path, "system", driver, motor)
    assert ran.observations == () and ran.evaluated == 1


def magnitude(tmp_path: Path, payload: dict[str, Any]) -> Any:
    graph(tmp_path / "m", payload)
    view = GraphView.read(tmp_path / "m", base_revision=0)
    return check_magnitude.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))


@pytest.mark.parametrize("domain", ["control", "firmware", "cross", "electrical"])
@pytest.mark.parametrize(
    ("name", "value", "refused"),
    [
        ("efficiency", 1.2, True),
        ("efficiency", 0.9, False),
        ("gearbox_efficiency", 1.05, True),
        ("gearbox_efficiency", 0.73, False),
        ("duty_cycle", 1.3, True),
        ("duty_cycle", 0.75, False),
        ("pwm_duty_cycle", 1.01, True),
        ("pwm_duty_cycle", 0.0, False),
    ],
)
def test_an_efficiency_and_a_duty_cycle_are_held_to_0_to_1_in_every_domain(
    tmp_path: Path, domain: str, name: str, value: float, refused: bool
) -> None:
    ran = magnitude(
        tmp_path, node(f"{domain}.part", domain=domain, quantities={name: (value, "1")})
    )
    assert ran.evaluated == 1
    assert [o.outcome for o in ran.observations] == (["fail"] if refused else [])


@pytest.mark.parametrize("domain", ["firmware", "electrical"])
@pytest.mark.parametrize(("rate", "refused"), [(208, False), (64_000, True), (0.5, True)])
def test_an_inertial_sensor_s_output_data_rate_is_held_to_the_makers_range(
    tmp_path: Path, domain: str, rate: float, refused: bool
) -> None:
    payload = node(f"{domain}.imu", domain=domain, quantities={"output_data_rate": (rate, "Hz")})
    ran = magnitude(tmp_path, payload)
    assert ran.evaluated == 1
    assert [o.outcome for o in ran.observations] == (["fail"] if refused else [])
