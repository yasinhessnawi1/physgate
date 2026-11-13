"""Through the dispatcher and the real binary: a tool server reaches nothing outside its directory.

The binary starts a session's tool servers itself, outside the sandbox around the session's shell
commands. A stand-in server (``reach_probe_server.py``) tries six reaches when it starts: a write
outside its own directory (into the worktree), a read of a file no session may read (another
session's directory), a TCP connection out, a name lookup, a serial device opened for writing, and
a write into its own directory. It tells what got through in the names of the tools it lists,
which the binary sends to the model, so the test reads them from the scripted endpoint.

Run unwrapped, the same server reaches what it tries (the control). Inside the OS layer the
dispatcher starts it in its wrapper, and it reaches its own directory and nothing else. Without
the layer no server is offered at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from git_rig import config
from scripted_endpoint import text, tool
from test_a_session_is_dispatched_under_the_hooks import SPEC, dispatch, knowledge_reads

from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import NO_TOOL_SERVERS, claude_binary
from physgate.orchestrator.merge import RunGit
from physgate.oslayer.containment import ServerLaunch
from physgate.oslayer.probe import Absent, Present, judge_here

pytestmark = [pytest.mark.integration]

PROBE = Path(__file__).with_name("reach_probe_server.py")
#: A serial device that exists on every Mac (measured on the laptop); on Linux the denied
#: names, which a runner has none of, so the row is vacuous there and says so.
DEVICE = "/dev/cu.debug-console" if sys.platform == "darwin" else "/dev/ttyACM0"
REACHES = ("device", "dns", "read_denied", "tcp", "write_outside", "write_own")


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _layer() -> Present | Absent:
    path = f"{Path(claude_binary()).parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    return judge_here(claude_version=config().claude_version, search_path=path)


def _secret(run_dir: Path) -> Path:
    return run_dir / "sessions" / "an-earlier-session" / "login.txt"


def _plant(run: RunGit) -> None:
    secret = _secret(run.run_dir)
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("another session's login\n")


def _launch(root: Path, write: Path, secret: Path) -> ServerLaunch:
    # Copied out of the harness's checkout, which no session reads and so no server either: a
    # real server comes from the run's tool environment, which every session reads.
    probe = root / "server" / PROBE.name
    probe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROBE, probe)
    return ServerLaunch(
        name="probe",
        command=os.path.realpath(sys.executable),
        args=(
            "-I",
            str(probe),
            "--write",
            str(write),
            "--read",
            str(secret),
            "--device",
            DEVICE,
        ),
    )


def _told(api: Any) -> dict[str, str]:  # noqa: ANN401 - the scripted endpoint's own record
    """Each reach and its outcome, as the server's tool names told the model."""
    found: dict[str, str] = {}
    for request in api.requests:
        for name in request.offered_tools:
            if name.startswith("mcp__probe__"):
                reach, _, outcome = name.removeprefix("mcp__probe__").rpartition("_")
                found[reach] = outcome
    return found


def test_unwrapped_the_server_reaches_what_it_tries(tmp_path: Path) -> None:
    """The control: the same server, started as the binary would without a wrapper."""
    own = tmp_path / "own"
    own.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x\n")
    done = subprocess.run(
        [*_launch_argv(tmp_path, tmp_path / "wrote.txt", secret), "--once"],
        env={**os.environ, "TMPDIR": str(own)},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    found = json.loads(done.stdout)
    assert sorted(found) == list(REACHES)
    for reach in ("write_outside", "read_denied", "tcp", "dns", "write_own"):
        assert found[reach] is True, (reach, found)
    assert found["device"] is os.path.exists(DEVICE), found
    assert (tmp_path / "wrote.txt").exists()


def _launch_argv(root: Path, write: Path, secret: Path) -> list[str]:
    launch = _launch(root, write, secret)
    return [launch.command, *launch.args]


def test_inside_the_os_layer_a_server_reaches_its_own_directory_and_nothing_else(
    tmp_path: Path, install_bin: Path
) -> None:
    layer = _layer()
    assert isinstance(layer, Present), layer
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [*knowledge_reads(worktree), tool("Read", file_path=str(worktree / SPEC)), text("done")]
    api, (report, _), _ = dispatch(
        tmp_path,
        install_bin,
        steps,
        before=_plant,
        tool_servers=(_launch(tmp_path, worktree / "server-wrote.txt", _secret(tmp_path / "run")),),
    )
    assert report.end.outcome == "completed", report
    found = _told(api)
    assert sorted(found) == list(REACHES), found
    assert found["write_own"] == "reached", found
    for reach in ("write_outside", "read_denied", "tcp", "dns", "device"):
        assert found[reach] == "refused", (reach, found)
    assert not (worktree / "server-wrote.txt").exists()
    record = json.loads((Path(str(report.trajectory)).parent / "process.json").read_text())
    argv = record["argv"]
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert list(servers) == ["probe"]
    assert servers["probe"]["command"] in ("/usr/bin/sandbox-exec",) or servers["probe"][
        "command"
    ].endswith("/bwrap"), servers


def test_without_the_os_layer_no_server_is_offered(
    tmp_path: Path, install_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    absent = Absent(reason="stand-in: the session runs without the sandbox")
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: absent)
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [*knowledge_reads(worktree), tool("Read", file_path=str(worktree / SPEC)), text("done")]
    api, (report, _), _ = dispatch(
        tmp_path,
        install_bin,
        steps,
        before=_plant,
        tool_servers=(_launch(tmp_path, worktree / "server-wrote.txt", _secret(tmp_path / "run")),),
    )
    assert report.end.outcome == "completed", report
    assert _told(api) == {}
    assert api.requests and not any(
        name.startswith("mcp__") for r in api.requests for name in r.offered_tools
    )
    record = json.loads((Path(str(report.trajectory)).parent / "process.json").read_text())
    assert record["argv"][record["argv"].index("--mcp-config") + 1] == NO_TOOL_SERVERS
    assert not (worktree / "server-wrote.txt").exists()
