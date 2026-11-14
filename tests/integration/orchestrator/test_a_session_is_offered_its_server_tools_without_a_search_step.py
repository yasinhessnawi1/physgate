"""A session is offered its tool servers' tools directly, never behind the binary's search step.

The binary can defer a server's tools: it leaves them out of the request's tools, lists their
names in the conversation's text, and offers its own search tool to load them on demand. 2.1.322
does so by default; 2.1.301 does so against a first-party API host and not against another
address, such as the scripted endpoint here, unless told to (``ENABLE_TOOL_SEARCH=true``). The
search tool is not on any profile's closed list, so a session told to search first would have its
admitted tools only by a call the tools hook refuses. Each profile's settings deny the search
tool, and with it denied the binary offers every server tool directly (measured on both pins).

- With tool search turned on, as on the live host, a session whose settings carry its profile's
  deny is offered the stand-in server's tool in the request's tools, not deferred, and is not
  offered the search tool.
- Without that deny, the same session gets the tool deferred: the row sees deferral.
- With deferral on, a server tool is put to the session's tool hooks by its own name and input,
  whether it is loaded through the search step first or called directly; a hook that refuses it
  stops it before the server is called. So the closed list, the register's refusals and the
  argument rule, which decide on that name and input, hold through a deferred call too.

The binaries are named by ``PHYSGATE_PINNED_BINS`` (separated like ``PATH``), or else
``PHYSGATE_CLAUDE_BIN``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, FakeMessagesApi, Script, serving, text, tool

from physgate.hooks.settings import PROFILE_DENIED
from physgate.orchestrator.invocation import role_argv

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

SEARCH = "ToolSearch"
STAND_IN_TOOL = "mcp__standin__measure"

#: A stand-in tool server: it logs each method it is asked, and lists one tool that answers.
SERVER = """
import json, sys
log = open(sys.argv[1], "a")
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if message.get("id") is None:
        continue
    method = message.get("method")
    log.write(method + "\\n")
    log.flush()
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "standin", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "measure", "description": "measure a value",
                             "inputSchema": {"type": "object",
                                             "properties": {"value": {"type": "string"}}}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "measured"}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""

#: A tool hook that records what it is asked, and refuses every server tool (exit 2).
HOOK = """#!/bin/sh
input=$(cat)
printf '%s\\n' "$input" >> "{log}"
case "$input" in
  *'"tool_name":"mcp__'*|*'"tool_name": "mcp__'*) echo "not available" >&2; exit 2 ;;
esac
exit 0
"""


def _session(
    binary: str,
    root: Path,
    steps: list[dict[str, Any]],
    *,
    deny: tuple[str, ...],
    hook: bool = False,
) -> tuple[FakeMessagesApi, Path, Path]:
    """Run a role session with the stand-in server and tool search turned on."""
    cwd, home, config = root / "wt", root / "home", root / "config"
    for directory in (cwd, home, config):
        directory.mkdir(parents=True)
    server, calls, asked = root / "server.py", root / "server.log", root / "hook.log"
    server.write_text(SERVER)
    calls.touch()
    asked.touch()
    settings: dict[str, Any] = {"permissions": {"deny": list(deny)}}
    if hook:
        script = root / "hook.sh"
        script.write_text(HOOK.format(log=asked))
        script.chmod(0o755)
        command = {"type": "command", "command": str(script)}
        settings["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [command]}]}
    (root / "settings.json").write_text(json.dumps(settings))
    command = {"type": "stdio", "command": sys.executable, "args": ["-I", str(server), str(calls)]}
    argv = role_argv(
        binary,
        prompt="ok",
        spawn_args=("--setting-sources", "", "--settings", str(root / "settings.json")),
        model="claude-sonnet-5",
        session_id="44444444-4444-4444-8444-444444444444",
        max_turns=4,
        effort="low",
        thinking_display="omitted",
        tool_servers=json.dumps({"mcpServers": {"standin": command}}),
        wrappers=(sys.executable,),
    )
    with serving(Script(main=[*steps, text("done")])) as (api, url):
        subprocess.run(
            argv,
            env={
                "HOME": str(home),
                "PATH": "/usr/bin:/bin",
                "TERM": "dumb",
                "CLAUDE_CONFIG_DIR": str(config),
                "CLAUDE_CODE_MAX_RETRIES": "0",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "DISABLE_TELEMETRY": "1",
                "MAX_MCP_OUTPUT_TOKENS": "25000",
                # As against the live host: the binary's search step is on.
                "ENABLE_TOOL_SEARCH": "true",
                "ANTHROPIC_BASE_URL": url,
                "ANTHROPIC_API_KEY": DUMMY_KEY,
            },
            cwd=cwd,
            input="",
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    return api, calls, asked


def _asked(log: Path) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for line in log.read_text().splitlines():
        if line.strip():
            event = json.loads(line)
            out.append((event.get("tool_name", ""), event.get("tool_input") or {}))
    return out


@pytest.mark.parametrize("binary", BINARIES)
def test_with_its_profile_s_deny_a_session_is_offered_the_server_tool_directly(
    binary: str, tmp_path: Path
) -> None:
    api, _, _ = _session(binary, tmp_path, [], deny=PROFILE_DENIED["role"])
    assert api.requests, "the binary sent no request"
    first = api.requests[0]
    assert STAND_IN_TOOL in first.offered_tools, (first.offered_tools, first.deferred_tools)
    assert STAND_IN_TOOL not in first.deferred_tools, first.deferred_tools
    assert SEARCH not in first.offered_tools, first.offered_tools


@pytest.mark.parametrize("binary", BINARIES)
def test_without_the_deny_the_server_tool_is_deferred(binary: str, tmp_path: Path) -> None:
    api, _, _ = _session(binary, tmp_path, [], deny=())
    first = api.requests[0]
    assert STAND_IN_TOOL in first.deferred_tools, (first.offered_tools, first.deferred_tools)
    assert STAND_IN_TOOL not in first.offered_tools, first.offered_tools
    assert SEARCH in first.offered_tools, first.offered_tools


@pytest.mark.parametrize(
    "steps",
    [
        pytest.param(
            [
                tool(SEARCH, query=f"select:{STAND_IN_TOOL}", max_results=1),
                tool(STAND_IN_TOOL, value="through-search"),
            ],
            id="through-the-search-step",
        ),
        pytest.param([tool(STAND_IN_TOOL, value="direct")], id="called-directly"),
    ],
)
@pytest.mark.parametrize("binary", BINARIES)
def test_a_deferred_server_tool_is_put_to_the_hooks_by_its_own_name_and_refused_there(
    binary: str, steps: list[dict[str, Any]], tmp_path: Path
) -> None:
    api, calls, asked = _session(binary, tmp_path, steps, deny=(), hook=True)
    assert STAND_IN_TOOL in api.requests[0].deferred_tools, "the tool was not deferred"
    put = _asked(asked)
    assert (STAND_IN_TOOL, steps[-1]["input"]) in put, put
    assert "tools/call" not in calls.read_text().split(), "a refused tool reached its server"
