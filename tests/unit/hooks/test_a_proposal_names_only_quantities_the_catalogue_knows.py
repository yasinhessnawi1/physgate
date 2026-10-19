"""A role session's proposal may not name a quantity under a name that shadows a relation's.

A name the catalogue lacks gets a unit parse and, at best, a reading from its suffix: no
relation, no range. A writer who renames ``stall_current`` to ``motor_current`` has stepped
out of the headroom relation without saying so. So a proposal is refused at write time, in the
hook and again when the orchestrator applies it, when a quantity's name ends in the last word
of a quantity a relation reads; the refusal names the quantity, the relation's quantity it
shadows and the nearest catalogued names. **Every other uncatalogued name is written**
(``logic_voltage``, ``wheel_diameter``, ``mass_without_battery``, ``zeta``), and the gate
records it as unchecked; a ``spring_force`` or a ``charge_capacity`` ends in a relation
quantity's word (``load_force``, ``energy_capacity``) and is refused like ``motor_current``.
The store itself does not refuse such names: a corpus written
straight into a store, outside the hooks, is unaffected.

The rule runs after the store's own (owner, interface, a bare number), so where a proposal
breaks two the reason given is the store's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event, make_store, node, write_config

from physgate.hooks import graph
from physgate.hooks.config import HookInput, SessionConfig
from physgate.state.protocol import REJECT_CROSS_ROLE, REJECT_MISSING_UNIT


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    make_store(tmp_path / "store", node("electrical.motor", "electrical"))
    _, _, cfg = write_config(tmp_path, role="electrical")
    return cfg


def _write(config: SessionConfig, name: str, content: dict[str, Any]) -> str:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / name
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(content)},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _named(
    payload: dict[str, Any], name: str, value: float = 2.4, unit: str = "A"
) -> dict[str, Any]:
    return {
        **payload,
        "quantities": {
            name: {"value": value, "unit": unit, "source": "datasheet", "written_by": "electrical"}
        },
    }


def test_a_catalogued_name_is_allowed(config: SessionConfig) -> None:
    assert (
        _write(config, "electrical.driver.json", _named(node("electrical.driver"), "current_limit"))
        == "allow"
    )


@pytest.mark.parametrize(
    ("name", "shadowed"),
    [
        ("motor_current", "stall_current"),
        ("pack_mass", "mass"),
        ("discharge_power", "max_discharge_power"),
        ("mount_moment", "reaction_moment"),
        ("spring_force", "load_force"),
        ("charge_capacity", "energy_capacity"),
    ],
)
def test_a_name_that_shadows_a_relation_s_quantity_is_refused_naming_both(
    config: SessionConfig, name: str, shadowed: str
) -> None:
    told = _write(config, "electrical.driver.json", _named(node("electrical.driver"), name))
    assert graph.SHADOWED_QUANTITY in told and name in told
    assert shadowed in told  # the relation's quantity it shadows, and the nearest names


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("logic_voltage", 3.3, "V"),
        ("wheel_diameter", 70, "mm"),
        ("zeta", 1, "A"),
        ("mass_without_battery", 0.165, "kg"),
        ("motor_voltage_maximum", 6, "V"),
        ("counts_per_wheel_revolution", 1320, "dimensionless"),
    ],
)
def test_every_other_uncatalogued_name_is_written(
    config: SessionConfig, name: str, value: float, unit: str
) -> None:
    # The gate records such a name as unchecked; the hook does not stand in its way.
    assert (
        _write(
            config, "electrical.driver.json", _named(node("electrical.driver"), name, value, unit)
        )
        == "allow"
    )


def test_every_shadowing_name_is_listed_once(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    payload["quantities"] = {
        "current_limit": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
        "pack_mass": {"value": 1, "unit": "kg", "source": "d", "written_by": "electrical"},
        "motor_current": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
        "zeta": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
    }
    told = _write(config, "electrical.driver.json", payload)
    assert told.index("motor_current shadows stall_current") < told.index("pack_mass shadows mass")
    assert "zeta" not in told and told.count("motor_current") == 1


def test_cross_role_is_reported_before_a_shadowing_name(config: SessionConfig) -> None:
    told = _write(
        config, "control.loop.json", _named(node("control.loop", "control"), "motor_current")
    )
    assert REJECT_CROSS_ROLE in told and graph.SHADOWED_QUANTITY not in told


def test_a_bare_number_is_reported_before_a_shadowing_name(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    payload["quantities"] = {"motor_current": 2.4}
    told = _write(config, "electrical.driver.json", payload)
    assert REJECT_MISSING_UNIT in told and graph.SHADOWED_QUANTITY not in told


def test_a_shadowing_name_is_reported_before_a_whole_node_fault(config: SessionConfig) -> None:
    # The name check sits with the quantity checks, before the whole-node validation, so a
    # proposal with both faults is told about its quantities first.
    payload = _named(node("electrical.driver"), "motor_current")
    payload["requirements"] = "not a list"
    told = _write(config, "electrical.driver.json", payload)
    assert graph.SHADOWED_QUANTITY in told
