"""A node proposal is checked as it is written, with the store's rules, without opening the store.

The rules run in the store's order, so where a proposal breaks two of them the
reason given is the one the store would give. Each guard is tested with a
second fault present as well as alone, because a later check catching the
same input in the wrong place looks exactly like the right check working.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import bash, event, make_store, node, write_config

from physgate.hooks import graph
from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import HookInput
from physgate.hooks.snapshot import signatures
from physgate.state.protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
)
from physgate.state.store import Store

INTERFACE = "iface.electrical.p01"


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    make_store(
        tmp_path / "store",
        node("electrical.motor", "electrical"),
        node("control.loop", "control"),
        node(INTERFACE, "electrical", kind="interface"),
    )
    _, _, cfg = write_config(tmp_path, role="electrical")
    return cfg


def _write(config: SessionConfig, name: str, content: object) -> str:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / name
    body = content if isinstance(content, str) else json.dumps(content)
    hook_input = HookInput.model_validate(
        event(
            tool_name="Write",
            cwd=config.worktree,
            tool_input={"file_path": str(target), "content": body},
        )
    )
    decision = graph.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _bash(config: SessionConfig, command: str) -> str:
    decision = graph.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=config.worktree)), config
    )
    return "allow" if decision.allow else decision.reason


def _bare(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "quantities": {"stall_current": 2.4}}


# --- each rule alone -------------------------------------------------------------


def test_a_new_node_owned_by_the_session_is_allowed(config: SessionConfig) -> None:
    assert _write(config, "electrical.driver.json", node("electrical.driver")) == "allow"


def test_a_new_node_naming_another_owner_is_refused_with_the_stores_reason(
    config: SessionConfig,
) -> None:
    told = _write(config, "control.gain.json", node("control.gain", "control"))
    assert REJECT_CROSS_ROLE in told and "must name this session's role" in told


def test_an_update_to_the_sessions_own_node_is_allowed(config: SessionConfig) -> None:
    assert (
        _write(config, "electrical.motor.json", node("electrical.motor", quantities={})) == "allow"
    )


def test_an_update_to_another_roles_node_is_refused_even_if_it_names_the_session(
    config: SessionConfig,
) -> None:
    # A foreign writer must not clear itself by putting its own name in the payload.
    told = _write(config, "control.loop.json", node("control.loop", "electrical"))
    assert REJECT_CROSS_ROLE in told and "owned by the control role" in told


def test_handing_ones_own_node_to_another_role_is_refused(config: SessionConfig) -> None:
    # The store would accept this from the current owner. The hook does not:
    # owners are assigned when the task is decomposed, not by the roles.
    told = _write(config, "electrical.motor.json", node("electrical.motor", "sizing"))
    assert graph.OWNER_CHANGE in told and "assigned when the task is decomposed" in told


def test_keeping_the_owner_while_changing_the_node_is_allowed(config: SessionConfig) -> None:
    changed = node("electrical.motor", "electrical", constrains=["power.budget"])
    assert _write(config, "electrical.motor.json", changed) == "allow"


def test_an_existing_interface_node_is_refused(config: SessionConfig) -> None:
    told = _write(config, f"{INTERFACE}.json", node(INTERFACE, kind="interface", quantities={}))
    assert REJECT_INTERFACE_IMMUTABLE in told


def test_a_bare_number_is_refused_with_the_schemas_own_message(config: SessionConfig) -> None:
    told = _write(config, "electrical.driver.json", _bare(node("electrical.driver")))
    assert REJECT_MISSING_UNIT in told
    assert "stall_current" in told and "valid dictionary" in told


def test_a_quantity_without_a_unit_is_refused(config: SessionConfig) -> None:
    payload = node("electrical.driver")
    del payload["quantities"]["stall_current"]["unit"]
    told = _write(config, "electrical.driver.json", payload)
    assert REJECT_MISSING_UNIT in told and "unit" in told


@pytest.mark.parametrize(
    ("name", "content", "fragment"),
    [
        ("electrical.driver.json", "not json", "one whole node"),
        ("electrical.driver.json", [1, 2], "one whole node"),
        ("electrical.other.json", node("electrical.driver"), "named after the node"),
        ("x.json", node("../x"), "dotted identifier"),
        ("electrical.driver.json", {**node("electrical.driver"), "extra": 1}, "extra"),
        ("electrical.driver.json", {**node("electrical.driver"), "kind": "gadget"}, "kind"),
        ("notes.txt", node("electrical.driver"), "one whole node"),
    ],
)
def test_a_malformed_proposal_is_refused(
    config: SessionConfig, name: str, content: object, fragment: str
) -> None:
    told = _write(config, name, content)
    assert told.startswith("This node proposal is refused") and fragment in told


# --- two faults at once: the store's order decides the reason ----------------------


def test_cross_role_is_reported_before_a_bare_number(config: SessionConfig) -> None:
    told = _write(config, "control.loop.json", _bare(node("control.loop", "control")))
    assert REJECT_CROSS_ROLE in told and REJECT_MISSING_UNIT not in told


def test_an_interface_is_reported_before_a_bare_number(config: SessionConfig) -> None:
    told = _write(config, f"{INTERFACE}.json", _bare(node(INTERFACE, kind="interface")))
    assert REJECT_INTERFACE_IMMUTABLE in told and REJECT_MISSING_UNIT not in told


def test_cross_role_is_reported_before_an_interface(config: SessionConfig) -> None:
    make_store(
        Path(config.store_root or ""), node("iface.control.p02", "control", kind="interface")
    )
    told = _write(
        config, "iface.control.p02.json", node("iface.control.p02", "control", kind="interface")
    )
    assert REJECT_CROSS_ROLE in told and REJECT_INTERFACE_IMMUTABLE not in told


def test_a_misnamed_file_is_reported_before_ownership(config: SessionConfig) -> None:
    told = _write(config, "electrical.other.json", node("control.loop", "control"))
    assert "named after the node" in told and REJECT_CROSS_ROLE not in told


# --- the other tools and routes ---------------------------------------------------


def test_an_edit_is_checked_on_the_content_it_would_leave(config: SessionConfig) -> None:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / "electrical.driver.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(node("electrical.driver")))

    def edit(old: str, new: str) -> bool:
        hook_input = HookInput.model_validate(
            event(
                tool_name="Edit",
                cwd=config.worktree,
                tool_input={"file_path": str(target), "old_string": old, "new_string": new},
            )
        )
        return graph.pre_tool_use(hook_input, config).allow

    assert edit('"value": 2.4', '"value": 3.1')
    assert not edit(
        '{"value": 2.4, "unit": "A", "source": "datasheet", "written_by": "electrical"}', "2.4"
    )


def test_a_notebook_edit_into_the_proposals_is_refused(config: SessionConfig) -> None:
    target = Path(config.worktree) / graph.PROPOSALS_DIR / "x.ipynb"
    hook_input = HookInput.model_validate(
        event(
            tool_name="NotebookEdit", tool_input={"notebook_path": str(target), "new_source": "x"}
        )
    )
    assert not graph.pre_tool_use(hook_input, config).allow


def test_files_outside_the_proposals_are_not_this_hooks_business(config: SessionConfig) -> None:
    target = Path(config.worktree) / "notes.json"
    hook_input = HookInput.model_validate(
        event(tool_name="Write", tool_input={"file_path": str(target), "content": "not a node"})
    )
    assert graph.pre_tool_use(hook_input, config).allow


@pytest.mark.parametrize(
    "command",
    [
        "echo '{}' > .physgate/proposals/electrical.driver.json",
        "cp /tmp/node.json .physgate/proposals/electrical.driver.json",
        "python3 -c \"open('.physgate/proposals/x.json','w').write('{}')\"",
        "rm -rf .physgate",
        "cd .physgate/proposals && echo '{}' > x.json",
        "sed -i '' s/2.4/9.9/ .physgate/proposals/electrical.motor.json",
    ],
)
def test_a_proposal_written_through_the_shell_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) == graph.SHELL_WRITE


@pytest.mark.parametrize(
    "command",
    [
        "cat .physgate/proposals/electrical.motor.json",
        "ls -la .physgate/proposals",
        "ls",
        "git status",
    ],
)
def test_reading_the_proposals_through_the_shell_is_allowed(
    config: SessionConfig, command: str
) -> None:
    assert _bash(config, command) == "allow"


# --- the journal is read, never written --------------------------------------------


def test_the_check_works_against_a_store_nothing_can_write(config: SessionConfig) -> None:
    root = Path(config.store_root or "")
    entries = [root, root / "nodes", *root.rglob("*")]
    modes = {p: os.stat(p).st_mode for p in entries}
    try:
        for p in entries:
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        assert REJECT_CROSS_ROLE in _write(config, "control.loop.json", node("control.loop"))
        assert _write(config, "electrical.driver.json", node("electrical.driver")) == "allow"
    finally:
        for p, mode in modes.items():
            os.chmod(p, stat.S_IMODE(mode))


def test_a_thousand_checks_leave_every_byte_and_signature_of_the_store_as_it_was(
    config: SessionConfig,
) -> None:
    root = str(config.store_root)
    before = signatures([root])
    contents = {p: Path(p).read_bytes() for p in before if os.path.isfile(p)}
    for n in range(1000):
        _write(config, "control.loop.json" if n % 2 else "electrical.driver.json", node("x.y"))
    assert signatures([root]) == before
    assert {p: Path(p).read_bytes() for p in contents} == contents


def test_the_check_never_constructs_a_store(
    config: SessionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        msg = "a hook opened the store"
        raise AssertionError(msg)

    monkeypatch.setattr(Store, "__init__", forbidden)
    monkeypatch.setattr(Store, "recover", forbidden)
    assert REJECT_CROSS_ROLE in _write(config, "control.loop.json", node("control.loop"))
    assert REJECT_INTERFACE_IMMUTABLE in _write(
        config, f"{INTERFACE}.json", node(INTERFACE, kind="interface", quantities={})
    )


def test_with_no_store_configured_every_node_is_new(tmp_path: Path) -> None:
    _, _, cfg = write_config(tmp_path, role="electrical", store_root=None)
    assert _write(cfg, "control.loop.json", node("control.loop", "electrical")) == "allow"
    assert REJECT_CROSS_ROLE in _write(cfg, "control.loop.json", node("control.loop", "control"))
