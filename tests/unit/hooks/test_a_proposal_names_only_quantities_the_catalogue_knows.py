"""A role session's proposal may not name a quantity under a misspelling of a relation's.

A name the catalogue lacks gets a unit parse and, at best, a reading from its suffix: no
relation, no range. A writer who spells ``stall_current`` as ``stall_currnt``, or
``current_limit`` as ``currentlimit``, has stepped out of the headroom relation without
saying so. So a proposal is refused at write time, in the hook and again when the
orchestrator applies it, when a quantity's name is within one insertion or deletion of a
relation's quantity for a name of five characters or fewer, two for a longer one, underscores
ignored; the refusal names the quantity, the relation's quantity it shadows and the nearest
catalogued names. **Every other uncatalogued name is written** (``no_load_current``,
``idle_current``, ``motor_voltage_limit``, ``motor_current_draw``, ``max``, ``mask``), and
the gate records it as unchecked: a different name is not a misspelling, and a session or a
demo run is not blocked on it. The store itself does not refuse such names: a corpus written
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
        ("stall_currnt", "stall_current"),
        ("currentlimit", "current_limit"),
        ("supported_mas", "supported_mass"),
        ("mas", "mass"),
    ],
)
def test_a_misspelling_of_a_relation_s_quantity_is_refused_naming_both(
    config: SessionConfig, name: str, shadowed: str
) -> None:
    told = _write(config, "electrical.driver.json", _named(node("electrical.driver"), name))
    assert graph.SHADOWED_QUANTITY in told and name in told
    assert shadowed in told  # the relation's quantity it shadows, and the nearest names


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("no_load_current", 0.07, "A"),
        ("idle_current", 0.02, "A"),
        ("motor_voltage_limit", 6, "V"),
        ("motor_current_draw", 0.5, "A"),
        ("max", 1, "A"),
        ("mask", 1, "A"),
        ("motor_current", 2.4, "A"),
        ("pack_mass", 0.2, "kg"),
        ("logic_voltage", 3.3, "V"),
        ("mass_without_battery", 0.165, "kg"),
        ("zeta", 1, "A"),
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
        "supported_mas": {"value": 1, "unit": "kg", "source": "d", "written_by": "electrical"},
        "stall_currnt": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
        "zeta": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
    }
    told = _write(config, "electrical.driver.json", payload)
    assert told.index("stall_currnt shadows stall_current") < told.index(
        "supported_mas shadows supported_mass"
    )
    assert "zeta" not in told and told.count("stall_currnt") == 1


def test_cross_role_is_reported_before_a_shadowing_name(config: SessionConfig) -> None:
    told = _write(
        config, "control.loop.json", _named(node("control.loop", "control"), "stall_currnt")
    )
    assert REJECT_CROSS_ROLE in told and graph.SHADOWED_QUANTITY not in told


def test_a_bare_number_is_reported_before_a_shadowing_name(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    payload["quantities"] = {"stall_currnt": 2.4}
    told = _write(config, "electrical.driver.json", payload)
    assert REJECT_MISSING_UNIT in told and graph.SHADOWED_QUANTITY not in told


def test_a_shadowing_name_is_reported_before_a_whole_node_fault(config: SessionConfig) -> None:
    # The name check sits with the quantity checks, before the whole-node validation, so a
    # proposal with both faults is told about its quantities first.
    payload = _named(node("electrical.driver"), "stall_currnt")
    payload["requirements"] = "not a list"
    told = _write(config, "electrical.driver.json", payload)
    assert graph.SHADOWED_QUANTITY in told
