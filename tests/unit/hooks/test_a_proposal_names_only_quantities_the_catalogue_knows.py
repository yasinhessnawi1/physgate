"""A role session's proposal may name only quantities the gate's catalogue knows.

A name the catalogue lacks gets a unit parse and, at best, a dimension from its suffix: no
relation, no range. A writer who renames ``stall_current`` to ``motor_current`` has stepped
out of the headroom relation without saying so. So a proposal is refused at write time, in the
hook and again when the orchestrator applies it, when any quantity's name is not catalogued;
the refusal names the quantities and the nearest catalogued names. The store itself does not
refuse such names: a corpus written straight into a store, outside the hooks, is unaffected,
and the gate keeps recording the names it does not know as unchecked.

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


def test_a_name_the_catalogue_lacks_is_refused_naming_it_and_the_nearest_catalogued_name(
    config: SessionConfig,
) -> None:
    told = _write(
        config, "electrical.driver.json", _named(node("electrical.driver"), "motor_current")
    )
    assert graph.UNKNOWN_QUANTITY in told and "motor_current" in told
    assert "stall_current" in told  # the nearest catalogued names are offered


def test_a_name_whose_suffix_gives_the_gate_a_kind_is_refused_all_the_same(
    config: SessionConfig,
) -> None:
    # The suffix rule is the gate's reading of a corpus written outside the hooks, not a
    # licence for a session: a session writes the catalogue's names.
    told = _write(
        config, "electrical.driver.json", _named(node("electrical.driver"), "pack_mass", 0.2, "kg")
    )
    assert graph.UNKNOWN_QUANTITY in told and "pack_mass" in told


def test_every_unknown_name_is_listed_once(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    payload["quantities"] = {
        "current_limit": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
        "zeta": {"value": 1, "unit": "A", "source": "d", "written_by": "electrical"},
        "alpha_q": {"value": 1, "unit": "V", "source": "d", "written_by": "electrical"},
    }
    told = _write(config, "electrical.driver.json", payload)
    assert "alpha_q, zeta" in told


def test_cross_role_is_reported_before_an_unknown_name(config: SessionConfig) -> None:
    told = _write(
        config, "control.loop.json", _named(node("control.loop", "control"), "motor_current")
    )
    assert REJECT_CROSS_ROLE in told and graph.UNKNOWN_QUANTITY not in told


def test_a_bare_number_is_reported_before_an_unknown_name(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    payload["quantities"] = {"motor_current": 2.4}
    told = _write(config, "electrical.driver.json", payload)
    assert REJECT_MISSING_UNIT in told and graph.UNKNOWN_QUANTITY not in told


def test_an_unknown_name_is_reported_before_a_whole_node_fault(config: SessionConfig) -> None:
    # The name check sits with the quantity checks, before the whole-node validation, so a
    # proposal with both faults is told about its quantities first.
    payload = _named(node("electrical.driver"), "motor_current")
    payload["requirements"] = "not a list"
    told = _write(config, "electrical.driver.json", payload)
    assert graph.UNKNOWN_QUANTITY in told
