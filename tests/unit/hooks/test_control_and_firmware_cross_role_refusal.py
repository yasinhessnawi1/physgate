"""Control and firmware, through the real hook: cross-role write refusal, confirmed.

Not new enforcement. ``hooks/graph.py``'s ownership rules (``_owner_is_the_session``
and friends) are already generic over any role string, and the test file beside
this one already exercises ``"control"`` as a foreign owner against an
``"electrical"`` session. What neither that file nor anything else in the suite
has exercised is ``"control"`` and ``"firmware"`` as the *acting* session role: a
control session's write to its own nodes lands, and its write to a firmware
node is refused, and the same the other way round. This file does exactly
that, symmetrically, and nothing else: if it needed a change to ``src/`` to
pass, that would be the finding, not a quiet fix. It did not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hook_helpers import make_store, node, write_config

from physgate.hooks import graph
from physgate.hooks.config import HookInput, SessionConfig
from physgate.state.protocol import REJECT_CROSS_ROLE


def _write(config: SessionConfig, name: str, content: object) -> str:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / name
    body = content if isinstance(content, str) else json.dumps(content)
    hook_input = HookInput.model_validate(
        {
            "session_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
            "cwd": config.worktree,
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": body},
        }
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    make_store(
        tmp_path / "store",
        node("control.loop_gain", "control"),
        node("firmware.loop_period", "firmware"),
    )
    _, _, cfg = write_config(tmp_path, role="control")
    return cfg


def test_a_control_session_writes_its_own_node(config: SessionConfig) -> None:
    assert _write(config, "control.loop_gain.json", node("control.loop_gain", "control")) == "allow"


def test_a_control_session_creating_a_new_control_node_is_allowed(
    config: SessionConfig,
) -> None:
    assert _write(config, "control.margin.json", node("control.margin", "control")) == "allow"


def test_a_control_session_writing_a_firmware_node_is_refused(config: SessionConfig) -> None:
    told = _write(config, "firmware.loop_period.json", node("firmware.loop_period", "firmware"))
    assert REJECT_CROSS_ROLE in told
    assert "owned by the firmware role" in told
    assert "this session is the control role" in told


def test_a_control_session_creating_a_new_firmware_node_is_refused(
    config: SessionConfig,
) -> None:
    told = _write(config, "firmware.timer.json", node("firmware.timer", "firmware"))
    assert REJECT_CROSS_ROLE in told
    assert "must name this session's role, control, as its owner" in told


@pytest.fixture
def firmware_config(tmp_path: Path) -> SessionConfig:
    make_store(
        tmp_path / "store",
        node("control.loop_gain", "control"),
        node("firmware.loop_period", "firmware"),
    )
    _, _, cfg = write_config(tmp_path, role="firmware")
    return cfg


def test_a_firmware_session_writes_its_own_node(firmware_config: SessionConfig) -> None:
    content = node("firmware.loop_period", "firmware")
    assert _write(firmware_config, "firmware.loop_period.json", content) == "allow"


def test_a_firmware_session_creating_a_new_firmware_node_is_allowed(
    firmware_config: SessionConfig,
) -> None:
    assert _write(firmware_config, "firmware.timer.json", node("firmware.timer", "firmware")) == (
        "allow"
    )


def test_a_firmware_session_writing_a_control_node_is_refused(
    firmware_config: SessionConfig,
) -> None:
    told = _write(firmware_config, "control.loop_gain.json", node("control.loop_gain", "control"))
    assert REJECT_CROSS_ROLE in told
    assert "owned by the control role" in told
    assert "this session is the firmware role" in told


def test_a_firmware_session_creating_a_new_control_node_is_refused(
    firmware_config: SessionConfig,
) -> None:
    told = _write(firmware_config, "control.margin.json", node("control.margin", "control"))
    assert REJECT_CROSS_ROLE in told
    assert "must name this session's role, firmware, as its owner" in told
