"""Through the dispatcher and the real binary: firmware is built by the admitted PlatformIO tool.

A run that names a provisioned tool environment (``PHYSGATE_TOOL_ENVIRONMENT``) records its tool
servers from the register, as the run command does, and the dispatcher starts them from that
record inside the OS layer, each in its wrapper, with no network. The session writes a module's
PlatformIO project and calls the admitted ``build_project`` tool on it: the build runs offline from
the environment's read-only store, the answer carries the image's flash and RAM use, and nothing
is built into the module, so the committed attempt holds the sources alone.

A project file is the session's own, and PlatformIO runs the Python it names (``extra_scripts``)
inside the build. The second row measures what such code reaches from inside the server's wrapper:
its own directory, and not the worktree, the environment, another session's files, the network or
the session's credential. A build only: no tool here uploads, monitors or opens a device.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from git_rig import config
from scripted_endpoint import text, tool
from test_a_session_is_dispatched_under_the_hooks import SPEC, dispatch, knowledge_reads

from physgate.orchestrator.git import git
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.run_config import RunBounds, RunConfig
from physgate.orchestrator.tool_environment import (
    measure_named,
    recorded_servers,
    server_launches,
)
from physgate.oslayer.probe import Present, judge_here
from physgate.toolenv.manifest import scan

pytestmark = [pytest.mark.integration]

PROVISIONED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")

FIRMWARE_INI = """[env:balboa]
platform = platformio/atmelavr@5.3.0
board = a-star32U4
framework = arduino
"""
FIRMWARE_MAIN = """#include <Arduino.h>
#include <Balboa32U4.h>
Balboa32U4Motors motors;
Balboa32U4Encoders encoders;
void setup() { Serial.begin(115200); }
void loop() {
  int16_t l = encoders.getCountsLeft();
  motors.setSpeeds(l > 100 ? -50 : 50, 50);
  Serial.println(l);
  delay(10);
}
"""
#: Run by PlatformIO before the build, as any project file may ask: it tries each reach, says
#: what got through in the build's output, and stops the build so the output is answered whole.
REACH = """import os, socket
Import("env")
def attempt(name, act):
    try:
        act()
        print("REACH " + name + " reached")
    except Exception:
        print("REACH " + name + " refused")
def write(path):
    with open(path, "w") as handle:
        handle.write("written by a project file's script\\n")
def read(path):
    with open(path) as handle:
        handle.read()
attempt("write_module", lambda: write({module!r} + "/reach-wrote.txt"))
attempt("write_environment", lambda: write({environment!r} + "/reach-wrote.txt"))
own = os.path.dirname(os.environ["PLATFORMIO_BUILD_DIR"])
attempt("write_own", lambda: write(own + "/reach-wrote.txt"))
attempt("read_other_session", lambda: read({secret!r}))
attempt("tcp", lambda: socket.create_connection(("1.1.1.1", 53), timeout=3).close())
credential = [k for k in os.environ if k.startswith(("ANTHROPIC", "CLAUDE"))]
print("REACH credential " + ("reached" if credential else "refused"))
env.Exit(1)
"""
REACHES = (
    "credential",
    "read_other_session",
    "tcp",
    "write_environment",
    "write_module",
    "write_own",
)


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _run_config(root: Path) -> RunConfig:
    """A run naming the environment and the register's servers, inside the layer, network none."""
    path = f"{Path(claude_binary()).parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    layer = judge_here(claude_version=config().claude_version, search_path=path)
    if not isinstance(layer, Present):
        pytest.skip("the OS layer cannot run here")
    measured = measure_named(
        {"interpreter": str(root / "venv" / "bin" / "python3"), "roots": [str(root)]},
        forbidden={},
    )
    return config().model_copy(
        update={
            "tool_environment": measured,
            "tool_servers": recorded_servers(),
            "network": "none",
            "network_enforced": True,
            "os_layer": layer,
            "bounds": RunBounds(
                binary_max_retries=0,
                session_wall_clock_s=900.0,
                session_max_turns=30,
                infra_retry_delays_s=(),
            ),
        }
    )


def _secret(run_dir: Path) -> Path:
    return run_dir / "sessions" / "an-earlier-session" / "login.txt"


def _plant(run: RunGit) -> None:
    secret = _secret(run.run_dir)
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("another session's login\n")


def _wrapped_platformio(report: object) -> str:
    record = json.loads(
        (Path(str(report.trajectory)).parent / "process.json").read_text()  # type: ignore[attr-defined]
    )
    argv = record["argv"]
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert sorted(servers) == ["control", "mujoco", "platformio"], servers
    return str(servers["platformio"]["command"])


def test_a_session_builds_firmware_through_the_admitted_tool_with_nothing_built_in_its_module(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    if not PROVISIONED:
        pytest.skip("no provisioned tool environment named")
    root = Path(PROVISIONED)
    cfg = _run_config(root)
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    module = worktree / "modules" / "power"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(module / "platformio.ini"), content=FIRMWARE_INI),
        tool("Write", file_path=str(module / "src" / "main.cpp"), content=FIRMWARE_MAIN),
        tool("mcp__platformio__build_project", projectDir=str(module), environment="balboa"),
        text("done"),
    ]
    api, (report, _), run = dispatch(
        tmp_path, install_bin, steps, cfg=cfg, tool_servers=server_launches(cfg)
    )
    assert report.end.outcome == "completed", report
    command = _wrapped_platformio(report)
    assert command == "/usr/bin/sandbox-exec" or command.endswith("/bwrap"), command
    told = "\n".join(r.last_user for r in api.requests if r.thread == "main")
    # The tool's own answer, from the build's size line: the Balboa image the offline proof built.
    assert re.search(r'"success":\s*true', told), told[-3000:]
    assert re.search(r'"flashUsageBytes":\s*4798\b', told), told[-3000:]
    assert re.search(r'"ramUsageBytes":\s*173\b', told), told[-3000:]
    # Nothing was built or logged into the module: the server writes its own directory only.
    assert sorted(p.name for p in module.iterdir()) == ["platformio.ini", "src"]
    assert report.attempt_commit is not None
    committed = git(run.repo, "ls-tree", "-r", "--name-only", report.attempt_commit).splitlines()
    assert "modules/power/src/main.cpp" in committed
    assert not [p for p in committed if ".pio" in p or p.endswith((".elf", ".hex", ".o"))]
    assert scan([root]) == before


def test_a_project_file_s_own_script_reaches_the_server_s_directory_and_nothing_else(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    if not PROVISIONED:
        pytest.skip("no provisioned tool environment named")
    root = Path(PROVISIONED)
    cfg = _run_config(root)
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    module = worktree / "modules" / "power"
    reach = REACH.format(
        module=str(module), environment=str(root), secret=str(_secret(tmp_path / "run"))
    )
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool(
            "Write",
            file_path=str(module / "platformio.ini"),
            content=FIRMWARE_INI + "extra_scripts = pre:reach.py\n",
        ),
        tool("Write", file_path=str(module / "reach.py"), content=reach),
        tool("Write", file_path=str(module / "src" / "main.cpp"), content=FIRMWARE_MAIN),
        tool("mcp__platformio__build_project", projectDir=str(module), environment="balboa"),
        text("done"),
    ]
    api, (report, _), _run = dispatch(
        tmp_path,
        install_bin,
        steps,
        cfg=cfg,
        before=_plant,
        tool_servers=server_launches(cfg),
    )
    assert report.end.outcome == "completed", report
    told = "\n".join(r.last_user for r in api.requests if r.thread == "main")
    # The build's output reaches the model as escaped JSON: each line is read by its words.
    found = dict(re.findall(r"REACH (\w+) (reached|refused)", told))
    assert sorted(found) == list(REACHES), told[-3000:]
    assert found["write_own"] == "reached", found
    for name in REACHES:
        if name != "write_own":
            assert found[name] == "refused", (name, found)
    assert not (module / "reach-wrote.txt").exists()
    assert not (root / "reach-wrote.txt").exists()
    assert scan([root]) == before
