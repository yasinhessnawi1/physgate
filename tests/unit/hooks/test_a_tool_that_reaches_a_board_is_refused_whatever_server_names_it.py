"""A tool that reaches a board is refused by its name, whatever server the call names.

The register holds, apart from any server, the names of the tools a PlatformIO tool server offers
that reach a board, a port or a probe (upload, flash, monitor, serial, device, debug, test and the
like). No server entry may admit one: a register that does is refused when it is loaded. And the
hooks, which read the register's file without its schema, refuse a call to one of them under any
server's name, even where a file written by hand admits it and a session's list names it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event, write_config

from physgate.hooks import server_arguments, tools
from physgate.hooks.config import HookInput, SessionConfig
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.register import REGISTER_FILE, load_register

#: Every tool of the community PlatformIO server whose name says it reaches a board.
BOARD_TOOLS = frozenset({
    "agent_flash_monitor_verify", "agent_generate_board_report", "agent_monitor_health",
    "agent_resolve_target", "capture_serial_window", "coredump", "debug_cmd", "debug_list",
    "debug_start", "debug_stop", "flash_verification", "get_board_info", "get_monitor_status",
    "list_boards", "list_devices", "list_targets", "memory_watch", "monitor_capture",
    "port_diagnose", "power_profile", "run_target", "run_tests", "serial_session_list",
    "serial_session_read", "serial_session_start", "serial_session_stop", "serial_session_write",
    "start_monitor", "stop_monitor", "upload_filesystem", "upload_firmware", "upload_ota",
})  # fmt: skip
#: The server names a call may give: the one that offered them, ours, and one nobody has.
SERVERS = ("platformio", "firmware", "control", "mujoco")
BASE = ["Bash", "Edit", "NotebookEdit", "Read", "Write"]


def _on_file() -> set[str]:
    named = json.loads(REGISTER_FILE.read_text(encoding="utf-8")).get("refused_tools", [])
    return set(named)


def test_the_register_names_every_tool_that_reaches_a_board_apart_from_any_server() -> None:
    assert _on_file() == BOARD_TOOLS
    admitted = {tool for entry in load_register().servers.values() for tool in entry.tools}
    assert not admitted & BOARD_TOOLS


def _entry(tools: dict[str, dict[str, str]]) -> dict[str, Any]:
    return {"command": "{root}/bin/server", "relative_paths": "refused", "tools": tools}


def _loads(path: Path) -> bool:
    try:
        load_register(path)
    except ToolEnvironmentError:
        return False
    return True


def test_a_register_whose_server_admits_one_is_refused_whatever_the_server_is_called(
    tmp_path: Path,
) -> None:
    path = tmp_path / "register.json"
    refused = sorted(BOARD_TOOLS)
    path.write_text(
        json.dumps({"servers": {"firmware": _entry({"build": {}})}, "refused_tools": refused})
    )
    assert _loads(path), "a register that admits no board tool is refused"
    for server in SERVERS:
        for tool in refused:
            body = {"servers": {server: _entry({"build": {}, tool: {}})}, "refused_tools": refused}
            path.write_text(json.dumps(body))
            assert not _loads(path), (server, tool)


@pytest.fixture
def written_by_hand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A register file the schema never saw: every server admits every board tool.
    body = {
        "servers": {server: _entry(dict.fromkeys(BOARD_TOOLS, {})) for server in SERVERS},
        "refused_tools": sorted(BOARD_TOOLS),
    }
    path = tmp_path / "register.json"
    path.write_text(json.dumps(body))
    monkeypatch.setattr(server_arguments, "REGISTER_FILE", str(path))


@pytest.mark.usefixtures("written_by_hand")
def test_the_hooks_refuse_a_call_to_one_under_any_server_name_though_the_file_admits_it(
    tmp_path: Path,
) -> None:
    names = [f"mcp__{server}__{tool}" for server in SERVERS for tool in sorted(BOARD_TOOLS)]
    root = tmp_path.resolve() / "session"
    root.mkdir()
    config: SessionConfig = write_config(root, tools_allowed=[*BASE, *names])[2]
    for name in names:
        hook_input = HookInput.model_validate(
            event(tool_name=name, cwd=config.worktree, tool_input={})
        )
        decision = tools.pre_tool_use(hook_input, config)
        assert not decision.allow, name
        assert "reaches a board" in decision.reason, (name, decision.reason)


@pytest.mark.parametrize("refused", [None, "upload_firmware", [1], {"upload_firmware": 1}])
def test_a_register_file_without_its_refused_tools_judges_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: object
) -> None:
    # The file the hooks read names the refused tools as a list of names, or no call is judged:
    # the hook stops, and a hook that stops refuses the call.
    body: dict[str, object] = {"servers": {"control": _entry({"margins": {}})}}
    if refused is not None:
        body["refused_tools"] = refused
    path = tmp_path / "register.json"
    path.write_text(json.dumps(body))
    monkeypatch.setattr(server_arguments, "REGISTER_FILE", str(path))
    root = tmp_path.resolve() / "session"
    root.mkdir()
    config = write_config(root, tools_allowed=[*BASE, "mcp__control__margins"])[2]
    hook_input = HookInput.model_validate(
        event(tool_name="mcp__control__margins", cwd=config.worktree, tool_input={})
    )
    with pytest.raises((KeyError, TypeError)):
        tools.pre_tool_use(hook_input, config)
