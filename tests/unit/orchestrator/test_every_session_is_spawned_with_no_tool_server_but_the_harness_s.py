"""Every session is spawned with the tool-server configuration pinned to the harness's own.

A tool server named in a ``.mcp.json`` the session's worktree (or any directory above
it) holds, or in the user scope of its configuration directory, is started by the
binary outside the OS layer: it can write anywhere, read what no session may, and
reach the network whatever the session's network setting says. Today one spawn flag
keeps those sources closed. Every spawn therefore also carries the strict tool-server
mode with an explicit configuration, so a server starts only where the harness names
it, and the size of a server's output is set rather than left to a remote flag.
"""

from __future__ import annotations

import json
from pathlib import Path

from physgate.orchestrator.invocation import (
    MAX_SERVER_OUTPUT_TOKENS,
    NO_TOOL_SERVERS,
    decomposition_argv,
    isolated_env,
    reviewer_argv,
    role_argv,
)


def _server_config(argv: list[str]) -> dict[str, object]:
    assert argv.count("--strict-mcp-config") == 1, argv
    assert argv.count("--mcp-config") == 1, argv
    loaded = json.loads(argv[argv.index("--mcp-config") + 1])
    assert isinstance(loaded, dict)
    return loaded


def test_a_role_session_starts_no_tool_server(tmp_path: Path) -> None:
    argv = role_argv(
        "/bin/claude",
        prompt="p",
        spawn_args=("--setting-sources", "", "--settings", str(tmp_path / "s.json")),
        model="claude-opus-5-5",
        session_id="abc",
        max_turns=3,
        effort="high",
        thinking_display="summarized",
    )
    assert _server_config(argv) == {"mcpServers": {}}


def test_a_reviewer_starts_no_tool_server_and_a_resume_neither(tmp_path: Path) -> None:
    for resume in (False, True):
        argv = reviewer_argv(
            "/bin/claude",
            prompt="p",
            spawn_args=("--setting-sources", "", "--settings", str(tmp_path / "s.json")),
            schema="{}",
            model="claude-sonnet-5",
            session_id="abc",
            max_turns=3,
            effort="high",
            resume=resume,
        )
        assert _server_config(argv) == {"mcpServers": {}}


def test_the_decomposition_call_starts_no_tool_server(tmp_path: Path) -> None:
    argv = decomposition_argv(
        "/bin/claude",
        prompt="p",
        schema="{}",
        model="claude-sonnet-5",
        session_id="abc",
        settings=tmp_path / "settings.json",
        effort="low",
        debug_file=tmp_path / "debug.log",
    )
    assert _server_config(argv) == {"mcpServers": {}}


def test_the_empty_configuration_names_no_server() -> None:
    assert json.loads(NO_TOOL_SERVERS) == {"mcpServers": {}}


def test_a_server_s_output_is_capped_by_the_harness_not_by_a_remote_flag(tmp_path: Path) -> None:
    env = isolated_env(
        home=tmp_path,
        config_dir=tmp_path,
        binary="claude",
        claude_version="2.1.301",
        max_retries=0,
        max_output_tokens=64000,
        base_url=None,
        api_key=None,
    )
    assert env.get("MAX_MCP_OUTPUT_TOKENS") == str(MAX_SERVER_OUTPUT_TOKENS)
    assert MAX_SERVER_OUTPUT_TOKENS == 25_000
