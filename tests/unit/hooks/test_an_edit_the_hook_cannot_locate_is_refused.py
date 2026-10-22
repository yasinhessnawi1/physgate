"""An Edit to a node proposal is checked only where the hook can say what it would leave.

The hook checks an Edit on the file it would leave, which it computes by replacing
the old text in the file as it reads it. Claude Code finds the old text more
loosely than an exact match: it takes curly quotes for straight ones, and handles
line endings the hook reads differently. Where the hook cannot find the old text,
it used to check the file unchanged, and allowed an edit that Claude Code then
made. An Edit is now refused unless its old text occurs in the hook's reading of
the file exactly once, or, with ``replace_all``, at least once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hook_helpers import event, make_store, node, write_config

from physgate.hooks import graph
from physgate.hooks.config import HookInput, SessionConfig
from physgate.state.protocol import REJECT_MISSING_UNIT

QUANTITY = '{"value": 2.4, "unit": "A", "source": "datasheet", "written_by": "electrical"}'


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    make_store(tmp_path / "store", node("electrical.motor", "electrical"))
    _, _, cfg = write_config(tmp_path, role="electrical")
    return cfg


def _on_disk(config: SessionConfig, content: str) -> Path:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / "electrical.driver.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode())
    return target


def _edit(config: SessionConfig, target: Path, old: str, new: str, **more: object) -> str:
    hook_input = HookInput.model_validate(
        event(
            tool_name="Edit",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "old_string": old, "new_string": new, **more},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def test_an_edit_whose_old_text_has_curly_quotes_is_refused(config: SessionConfig) -> None:
    # Claude Code finds this old text in the file and writes a bare number there.
    target = _on_disk(config, json.dumps(node("electrical.driver")))
    curly = QUANTITY.replace('"', "“")
    told = _edit(config, target, curly, "2.4")
    assert told != "allow"
    assert "occurs 0 times" in told


def test_an_edit_across_a_lone_carriage_return_is_refused(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    target = _on_disk(config, json.dumps(payload, indent=1).replace("\n", "\r"))
    old = '"stall_current": {\r  "value": 2.4,'
    told = _edit(config, target, old, '"stall_current": 2.4, "x": {\r  "value": 2.4,')
    assert told != "allow"
    assert "occurs 0 times" in told


def test_an_edit_whose_old_text_occurs_twice_without_replace_all_is_refused(
    config: SessionConfig,
) -> None:
    payload = node("electrical.driver")
    payload["quantities"]["stall_torque"] = {**payload["quantities"]["stall_current"]}
    payload["quantities"]["stall_torque"]["unit"] = "A"
    target = _on_disk(config, json.dumps(payload))
    told = _edit(config, target, '"unit": "A"', '"unit": "V"')
    assert told != "allow"
    assert "occurs 2 times" in told


def test_an_edit_whose_old_text_occurs_twice_with_replace_all_is_checked(
    config: SessionConfig,
) -> None:
    payload = node("electrical.driver")
    payload["quantities"]["stall_torque"] = {**payload["quantities"]["stall_current"]}
    target = _on_disk(config, json.dumps(payload))
    assert _edit(config, target, '"value": 2.4', '"value": 3.1', replace_all=True) == "allow"
    told = _edit(config, target, QUANTITY, "2.4", replace_all=True)
    assert REJECT_MISSING_UNIT in told


def test_an_edit_to_a_proposal_that_does_not_exist_is_refused(config: SessionConfig) -> None:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / "electrical.driver.json"
    assert _edit(config, target, "x", json.dumps(node("electrical.driver"))) != "allow"


def test_an_edit_found_once_is_checked_as_before(config: SessionConfig) -> None:
    target = _on_disk(config, json.dumps(node("electrical.driver")))
    assert _edit(config, target, '"value": 2.4', '"value": 3.1') == "allow"
    told = _edit(config, target, QUANTITY, "2.4")
    assert told != "allow" and "occurs" not in told
