"""The decomposition is told the gate's quantity names and who writes interface nodes.

The physics gate checks a quantity only under its catalogue name: a value under another name is
recorded as unchecked, and a relation that reads the catalogue's name never fires for it. A real
plan named its gear ratio ``overall_gear_ratio`` and its stall currents ``stall_current_rated`` and
``stall_current_at_max_voltage``, so the run's gate covered less than it seemed to, and the plan's
specification asked a session to write the interface nodes, which the harness writes itself.

So the prompt names every quantity the catalogue holds, generated from it, and says that
interface nodes are the harness's to write. The plan check refuses none of a node's names for
added words: a node of part masses and no total is an honest plan, and a refusal there halts the
run at its first step after a paid call.
"""

from __future__ import annotations

import json
from typing import Any

from physgate.gate.catalogue import KINDS, QUANTITIES
from physgate.orchestrator.decompose import Plan, plan_problems, prompt_for

BRIEF = "A self-balancing robot."
ROLES = ["control", "electrical", "firmware", "mechanical"]


def _quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "brief", "written_by": "electrical"}


def _plan(quantities: dict[str, tuple[float, str]]) -> Plan:
    node: dict[str, Any] = {
        "id": "drivetrain.motor",
        "kind": "interface",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {name: _quantity(v, u) for name, (v, u) in quantities.items()},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-11-02T00:00:00Z",
    }
    modules = [{"name": "drive", "role": "electrical", "module_dir": "modules/drive", "spec": "s"}]
    return Plan.model_validate_json(json.dumps({"modules": modules, "interface_nodes": [node]}))


def _problems(quantities: dict[str, tuple[float, str]]) -> list[str]:
    return plan_problems(_plan(quantities), ["electrical"], BRIEF)


def test_the_prompt_names_every_quantity_of_the_catalogue_with_its_kind_s_unit() -> None:
    prompt = prompt_for(BRIEF, ROLES)
    for name, entry in QUANTITIES.items():
        assert name in prompt, name
        assert KINDS[entry.kind].canonical in prompt, entry.kind


def test_the_prompt_says_interface_nodes_are_written_by_the_harness_and_never_by_a_session() -> (
    None
):
    prompt = prompt_for(BRIEF, ROLES)
    assert "written by the harness" in prompt
    assert "never by a session" in prompt


def test_a_node_holding_part_masses_and_no_total_is_written() -> None:
    """A mass budget's parts beside no total are an honest plan: the prompt carries the names."""
    assert _problems({"battery_mass": (0.12, "kg"), "wheel_mass": (0.05, "kg")}) == []


def test_decorated_names_of_a_relation_s_quantity_are_left_to_the_prompt() -> None:
    """The plan check refuses none of them: a refusal there halted honest plans after a call."""
    assert (
        _problems(
            {
                "overall_gear_ratio": (110.24, "1"),
                "stall_current_at_max_voltage": (1.3, "A"),
                "chassis_thermal_resistance": (2.0, "K/W"),
                "peak_power_draw": (12.0, "W"),
            }
        )
        == []
    )


def test_a_rating_beside_the_catalogue_s_own_name_is_written() -> None:
    """Two values of one quantity: the one the design runs at takes the catalogue's name."""
    assert _problems({"stall_current": (1.3, "A"), "stall_current_rated": (1.5, "A")}) == []


def test_a_name_whose_unit_is_another_kind_is_written() -> None:
    """``mass_flow_rate`` holds ``mass``'s word, and is no mass: its unit says so."""
    assert _problems({"mass_flow_rate": (0.1, "kg/s")}) == []


def test_a_requirement_named_for_a_measured_margin_is_written() -> None:
    """The phase margin is read off a record, by no relation: a threshold may carry its name."""
    assert _problems({"phase_margin_required": (30, "deg")}) == []


def test_an_uncatalogued_length_is_written() -> None:
    assert _problems({"wheel_radius": (0.04, "m")}) == []
