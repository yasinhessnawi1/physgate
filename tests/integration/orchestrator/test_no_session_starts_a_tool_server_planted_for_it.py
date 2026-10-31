"""No session starts a tool server that a file around it names: only the harness's own count.

A tool server is a process the binary starts itself, outside the OS layer, so one that
a session could name would act with none of the session's limits. The places a server
can be named from are planted around every kind of session the harness spawns (a
``.mcp.json`` in its working directory and in the directory above, and the user scope
of its configuration directory), each naming a probe that records its own start. The
real binary is then run with the harness's arguments against the scripted endpoint.

- With the harness's arguments, no probe starts and no server's tool is offered.
- With the settings-source flag taken out as well, still none does: the strict
  tool-server mode holds by itself.
- With both taken out, the probe starts and its tool is offered, which shows the probe
  sees a server that starts.

The binaries are named by ``PHYSGATE_PINNED_BINS`` (separated like ``PATH``), or else
``PHYSGATE_CLAUDE_BIN``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text

from physgate.orchestrator.invocation import (
    NO_TOOL_SERVERS,
    decomposition_argv,
    reviewer_argv,
    role_argv,
)

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

#: A tool server that appends a line to its marker file the moment it starts, then answers
#: the protocol's opening with one tool, so a server that starts is seen whatever follows.
PROBE = """
import json, sys
with open(sys.argv[1], "a") as marker:
    marker.write("started\\n")
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if message.get("id") is None:
        continue
    method = message.get("method")
    if method == "initialize":
        version = message.get("params", {}).get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "probe", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "planted", "description": "planted",
                             "inputSchema": {"type": "object", "properties": {}}}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""

PLANTED_TOOL = "mcp__probe__planted"


def _plant(root: Path) -> tuple[Path, Path, Path, Path]:
    """A working directory with a server named in every place around it; the markers."""
    top, cwd, home, config = root / "top", root / "top" / "wt", root / "home", root / "config"
    for directory in (cwd, home, config):
        directory.mkdir(parents=True)
    probe = root / "probe.py"
    probe.write_text(PROBE)
    markers = (root / "cwd.marker", root / "parent.marker", root / "user.marker")

    def named(marker: Path) -> str:
        args = ["-I", str(probe), str(marker)]
        command = {"type": "stdio", "command": sys.executable, "args": args}
        return json.dumps({"mcpServers": {"probe": command}})

    (cwd / ".mcp.json").write_text(named(markers[0]))
    (top / ".mcp.json").write_text(named(markers[1]))
    (config / ".claude.json").write_text(named(markers[2]))
    return cwd, home, config, root


def _started(root: Path) -> list[str]:
    return sorted(m.name for m in root.glob("*.marker") if m.read_text())


def _without(argv: list[str], *drop: str) -> list[str]:
    """``argv`` with each named option and its value taken out."""
    out: list[str] = []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg in drop:
            takes_value = arg != "--strict-mcp-config"
            skip = takes_value and i + 1 < len(argv)
            continue
        out.append(arg)
    return out


def _role(binary: str, root: Path) -> list[str]:
    return role_argv(
        binary,
        prompt="ok",
        spawn_args=("--setting-sources", ""),
        model="claude-sonnet-5",
        session_id="11111111-1111-4111-8111-111111111111",
        max_turns=1,
        effort="low",
        thinking_display="omitted",
    )


def _reviewer(binary: str, root: Path) -> list[str]:
    return reviewer_argv(
        binary,
        prompt="ok",
        spawn_args=("--setting-sources", ""),
        schema='{"type":"object","properties":{"ok":{"type":"string"}},"required":["ok"]}',
        model="claude-sonnet-5",
        session_id="22222222-2222-4222-8222-222222222222",
        max_turns=1,
        effort="low",
    )


def _decomposition(binary: str, root: Path) -> list[str]:
    settings = root / "settings.json"
    settings.write_text("{}")
    return decomposition_argv(
        binary,
        prompt="ok",
        schema='{"type":"object","properties":{"ok":{"type":"string"}},"required":["ok"]}',
        model="claude-sonnet-5",
        session_id="33333333-3333-4333-8333-333333333333",
        settings=settings,
        effort="low",
        debug_file=root / "debug.log",
    )


KINDS: dict[str, Callable[[str, Path], list[str]]] = {
    "role": _role,
    "reviewer": _reviewer,
    "decomposition": _decomposition,
}


def _run(argv: list[str], cwd: Path, home: Path, config: Path, url: str) -> None:
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "TERM": "dumb",
        "CLAUDE_CONFIG_DIR": str(config),
        "CLAUDE_CODE_MAX_RETRIES": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "ANTHROPIC_BASE_URL": url,
        "ANTHROPIC_API_KEY": DUMMY_KEY,
    }
    subprocess.run(
        argv,
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _offered(binary: str, root: Path, argv: list[str]) -> tuple[list[str], set[str]]:
    cwd, home, config, _ = _plant(root)
    with serving(Script(main=[text("ok")])) as (api, url):
        _run(argv, cwd, home, config, url)
        offered = {name for request in api.requests for name in request.offered_tools}
    return _started(root), offered


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("binary", BINARIES)
def test_the_harness_s_arguments_start_no_planted_server(
    binary: str, kind: str, tmp_path: Path
) -> None:
    argv = KINDS[kind](binary, tmp_path)
    assert "--mcp-config" in argv, argv
    assert argv[argv.index("--mcp-config") + 1] == NO_TOOL_SERVERS
    started, offered = _offered(binary, tmp_path, argv)
    assert started == [], f"{kind} started a planted server: {started}"
    assert not {t for t in offered if t.startswith("mcp__")}, offered


@pytest.mark.parametrize("binary", BINARIES)
def test_the_strict_mode_holds_without_the_settings_source_flag(
    binary: str, tmp_path: Path
) -> None:
    argv = _without(_role(binary, tmp_path), "--setting-sources")
    assert "--setting-sources" not in argv
    assert "--strict-mcp-config" in argv, argv
    started, offered = _offered(binary, tmp_path, argv)
    assert started == [], started
    assert PLANTED_TOOL not in offered, offered


@pytest.mark.parametrize("binary", BINARIES)
def test_the_probe_sees_a_planted_server_that_starts(binary: str, tmp_path: Path) -> None:
    argv = _without(
        _role(binary, tmp_path), "--setting-sources", "--strict-mcp-config", "--mcp-config"
    )
    started, offered = _offered(binary, tmp_path, argv)
    assert started, "with nothing pinned the planted servers should start"
    assert PLANTED_TOOL in offered, offered
