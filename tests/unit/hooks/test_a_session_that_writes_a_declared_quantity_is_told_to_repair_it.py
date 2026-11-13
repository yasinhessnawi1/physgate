"""A session's proposal that touches a declared quantity is refused, and the session can repair it.

A quantity a person declared is fixed by a person: a session cannot add one, change one, drop
one, or write the reserved source without the decision that declares it. The hook, the first
line, refuses such a proposal as it is written, for ``declared_forged`` (added, or the reserved
source without the record) or ``declared_fixed`` (changed or dropped), and the message names the
quantity and says that declared parts are fixed by a person. A role may still add quantities of
its own to a declared node and write the declared ones as they stand. Where a proposal breaks
an earlier rule, the reason given is that rule's.
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
from physgate.state.store import Store

RESERVED = "declared by the person"
FORGED = "declared_forged"
FIXED = "declared_fixed"
MOTOR = "electrical.motor"


def _declared(value: float = 0.4, unit: str = "kg") -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "source": RESERVED,
        "written_by": "electrical",
        "declared": {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "yasin"},
    }


def _plain(value: float = 2.4) -> dict[str, Any]:
    return {"value": value, "unit": "A", "source": "datasheet", "written_by": "electrical"}


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    store = Store(tmp_path / "store")
    try:
        held = node(MOTOR, "electrical", quantities={"mass": _declared()})
        assert store.declare(held, ["run-1-parts-1"]).accepted
    finally:
        store.close()
    make_store(tmp_path / "other", node("electrical.driver", "electrical"))
    _, _, cfg = write_config(tmp_path, role="electrical")
    return cfg


def _write(config: SessionConfig, node_id: str, content: dict[str, Any]) -> str:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / f"{node_id}.json"
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": json.dumps(content)},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _with(quantities: dict[str, Any], node_id: str = MOTOR) -> dict[str, Any]:
    return node(node_id, "electrical", quantities=quantities)


def test_the_declared_quantity_as_it_stands_and_a_role_s_own_are_allowed(
    config: SessionConfig,
) -> None:
    ok = {"stall_current": _plain(3.0), "mass": _declared(), "extra": _plain(1.0)}
    assert _write(config, MOTOR, _with(ok)) == "allow"


def test_a_declared_quantity_a_session_adds_is_refused_naming_it(config: SessionConfig) -> None:
    told = _write(
        config,
        "electrical.driver",
        _with({"mass": _declared()}, "electrical.driver"),
    )
    assert FORGED in told and "mass" in told
    assert "fixed by a person" in told


def test_a_changed_declared_quantity_is_refused_naming_it(config: SessionConfig) -> None:
    told = _write(config, MOTOR, _with({"stall_current": _plain(), "mass": _declared(0.9)}))
    assert FIXED in told and "mass" in told
    assert "fixed by a person" in told


def test_a_dropped_declared_quantity_is_refused_naming_it(config: SessionConfig) -> None:
    told = _write(config, MOTOR, _with({"stall_current": _plain()}))
    assert FIXED in told and "mass" in told
    assert "fixed by a person" in told


def test_a_plain_quantity_made_a_declared_one_is_refused_as_forged(config: SessionConfig) -> None:
    told = _write(config, MOTOR, _with({"stall_current": _declared(2.4, "A"), "mass": _declared()}))
    assert FORGED in told and "stall_current" in told


@pytest.mark.parametrize(
    "source", [RESERVED, "Declared", "user-declared", "Declared By The Person"]
)
def test_the_reserved_source_without_the_record_is_declared_forged_not_a_missing_unit(
    config: SessionConfig, source: str
) -> None:
    quantity = {"value": 1.0, "unit": "A", "source": source, "written_by": "electrical"}
    told = _write(config, MOTOR, _with({"stall_current": quantity, "mass": _declared()}))
    assert FORGED in told and "stall_current" in told
    assert REJECT_MISSING_UNIT not in told


def test_a_bare_number_keeps_its_old_reason(config: SessionConfig) -> None:
    bare = {"value": 1.0, "source": "x", "written_by": "electrical"}
    told = _write(config, MOTOR, _with({"stall_current": bare, "mass": _declared()}))
    assert REJECT_MISSING_UNIT in told and FORGED not in told


def test_an_earlier_rule_keeps_its_reason_where_a_declared_fault_is_crossed_with_it(
    config: SessionConfig,
) -> None:
    other = node(MOTOR, "mechanical", quantities={"mass": _declared(0.9)})
    told = _write(config, MOTOR, other)
    assert graph.OWNER_CHANGE in told or REJECT_CROSS_ROLE in told
    assert FIXED not in told and FORGED not in told
