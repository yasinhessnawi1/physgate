"""Through the dispatcher and the real binary: a session computes and builds with the run's tools.

A run that names a tool environment gives each role session the environment's interpreter as
``python3``, its programs by name, and what its tools need in the session's own temporary
directory, all as the environment's own file says; the session writes nothing of the
environment, and the environment is scanned again when the session has ended.

The first tests use a stand-in environment whose interpreter and program are small scripts that
answer as the real ones do, so they run wherever the binary does. The last one uses a
provisioned environment (``PHYSGATE_TOOL_ENVIRONMENT``) inside the OS layer with no network: a
library-computed margin, and a firmware build whose output lies in the session's temporary
directory, so the attempt the orchestrator commits holds no build artefact.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from git_rig import config
from scripted_endpoint import text, tool
from test_a_session_is_dispatched_under_the_hooks import SPEC, dispatch, knowledge_reads

from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.git import git
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.run_config import RunBounds, RunConfig
from physgate.orchestrator.tool_environment import measure_named
from physgate.oslayer.probe import Absent, Present, judge_here
from physgate.toolenv.manifest import scan
from physgate.toolenv.session import SESSION_FILE

pytestmark = [pytest.mark.integration]

PROVISIONED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
WIRING = {
    "programs": {"report-size": "bin/report-size"},
    "directories": ["core"],
    "links": {"core/store": "store"},
    "variables": {"BUILD_CORE_DIR": "{temp}/core", "BUILD_QUIET": "yes"},
}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _layer() -> Present | Absent:
    path = f"{Path(claude_binary()).parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    return judge_here(claude_version=config().claude_version, search_path=path)


def _program(path: Path, says: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{says}'\n")
    path.chmod(0o755)


def _stand_in(tmp_path: Path) -> dict[str, Any]:
    root = Path(os.path.realpath(tmp_path)) / "tools" / "env"
    (root / "bin").mkdir(parents=True)
    (root / "store").mkdir()
    answer = {
        "version": "3.12.9",
        "prefix": str(root),
        "base_prefix": str(root),
        "physgate": False,
        "distributions": [["control", "0.10.1"]],
    }
    _program(root / "bin" / "python3", json.dumps(answer))
    # A tool that reads its store through the link in the session's own directory, as a build
    # tool does, and says where that directory is.
    report = root / "bin" / "report-size"
    report.write_text(
        "#!/bin/sh\necho 'FLASH 4798 RAM 173'\necho \"CORE=$BUILD_CORE_DIR\"\n"
        'cat "$BUILD_CORE_DIR/store/package.txt"\n'
    )
    report.chmod(0o755)
    (root / "store" / "package.txt").write_text("a package of the store\n")
    (root / SESSION_FILE).write_text(json.dumps(WIRING))
    return {"interpreter": str(root / "bin" / "python3"), "roots": [str(root)], "native": {}}


def _config(named: dict[str, Any], **changes: Any) -> RunConfig:  # noqa: ANN401
    measured = measure_named(named, forbidden={})
    return config().model_copy(update={"tool_environment": measured, **changes})


def test_a_session_finds_the_environment_s_programs_and_variables_as_its_file_says(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    named = _stand_in(tmp_path)
    root = Path(named["roots"][0])
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool(
            "Bash",
            command=(
                "report-size; echo PROGRAM=$(command -v report-size); "
                "echo PYTHON=$(command -v python3); echo QUIET=$BUILD_QUIET; echo PATH=$PATH"
            ),
        ),
        text("done"),
    ]
    api, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg=_config(named))
    told = "\n".join(r.last_user for r in api.requests if r.thread == "main")
    assert report.end.outcome == "completed", report
    sdir = Path(str(report.trajectory)).parent
    lines = told.splitlines()
    assert "FLASH 4798 RAM 173" in lines, told[-2000:]
    assert f"PROGRAM={sdir / 'bin' / 'report-size'}" in lines
    assert f"PYTHON={sdir / 'bin' / 'python3'}" in lines
    assert "QUIET=yes" in lines
    paths = [line for line in lines if line.startswith("PATH=")]
    assert paths and paths[0][5:].split(":")[0] == str(sdir / "bin"), paths
    cores = [line[5:] for line in lines if line.startswith("CORE=")]
    assert cores, told[-1500:]
    core = cores[0]
    assert core.endswith("/core"), core
    assert core.startswith("/var/tmp/pgs/") or core.startswith("/private/var/tmp/pgs/"), core
    assert "a package of the store" in lines
    assert sorted(p.name for p in (sdir / "bin").iterdir()) == ["python3", "report-size"]
    assert str(root / "bin" / "python3") in (sdir / "bin" / "python3").read_text()
    # The session's temporary directory went with the session, and the environment is as it was.
    assert not Path(core).exists()
    assert scan([root]) == before


def _built_write(root: Path) -> dict[str, Any]:
    """A command that writes into the environment by a path it builds as it runs."""
    whole = str(root / "store" / "package.txt")
    half = len(whole) // 2
    return tool(
        "Bash",
        command=(
            f"p=$(printf %s '{whole[:half]}')$(printf %s '{whole[half:]}'); "
            '(echo changed >> "$p") 2>/dev/null && echo ENV-WRITTEN || echo ENV-DENIED'
        ),
    )


def test_a_write_no_layer_refused_is_named_when_the_session_ends_and_nothing_is_committed(
    tmp_path: Path,
    install_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the OS layer the built write lands; the scan after the session names it."""
    absent = Absent(reason="stand-in: the session runs without the sandbox")
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: absent)
    named = _stand_in(tmp_path)
    root = Path(named["roots"][0])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(worktree / "modules" / "power" / "work.txt"), content="x\n"),
        _built_write(root),
        text("done"),
    ]
    with pytest.raises(InvocationError, match="tool environment changed while the session ran"):
        dispatch(tmp_path, install_bin, steps, cfg=_config(named))
    assert (root / "store" / "package.txt").read_text().endswith("changed\n")
    run_dir = tmp_path / "run"
    settled_files = sorted(run_dir.glob("sessions/*/after_stop.json"))
    assert len(settled_files) == 1
    settled = settled_files[0]
    assert (
        "changed while the session ran"
        in json.loads(settled.read_text())["tool_environment_changed"]
    )
    # Nothing the session left was committed: its branch is where it was opened.
    log = git(tmp_path / "target", "log", "--all", "--format=%s")
    assert log.strip() and "attempt" not in log.lower(), log


def test_inside_the_os_layer_the_same_write_is_refused_and_the_session_ends_as_any_other(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    if not isinstance(_layer(), Present):
        pytest.skip("the OS layer cannot run here")
    named = _stand_in(tmp_path)
    root = Path(named["roots"][0])
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    out = worktree / "modules" / "power" / "work.txt"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(out), content="x\n"),
        _built_write(root),
        text("done"),
    ]
    api, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg=_config(named))
    assert report.end.outcome == "completed" and report.attempt_commit is not None
    told = [r.last_user for r in api.requests if r.thread == "main"]
    assert any("ENV-DENIED" in said for said in told), told
    assert not any("ENV-WRITTEN" in said for said in told)
    assert scan([root]) == before


MARGINS = """import json, control
gm, pm, sm, wpc, wgc, wms = control.stability_margins(control.tf([4, 4], [1, 2, 1, 0]))
print("MARGINS " + json.dumps({"phase_margin_deg": float(pm)}))
"""
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


def test_a_session_computes_a_margin_and_builds_firmware_offline_with_nothing_built_in_its_module(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    if not PROVISIONED:
        pytest.skip("no provisioned tool environment named")
    layer = _layer()
    if not isinstance(layer, Present):
        pytest.skip("the OS layer cannot run here")
    root = Path(PROVISIONED)
    named = {"interpreter": str(root / "venv" / "bin" / "python3"), "roots": [str(root)]}
    cfg = _config(
        named,
        network="none",
        network_enforced=True,
        os_layer=layer,
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=900.0,
            session_max_turns=30,
            infra_retry_delays_s=(),
        ),
    )
    assert cfg.tool_environment is not None
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    module = worktree / "modules" / "power"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(module / "margins.py"), content=MARGINS),
        tool("Write", file_path=str(module / "platformio.ini"), content=FIRMWARE_INI),
        tool("Write", file_path=str(module / "src" / "main.cpp"), content=FIRMWARE_MAIN),
        # Each by the module's full path: a session's shell keeps its directory between calls.
        tool("Bash", command=f"cd {module} && python3 margins.py"),
        tool("Bash", command=f"cd {module} && pio run 2>&1 | tail -6", timeout=600000),
        # A plain read, as any command naming the session's temporary directory must be.
        tool("Bash", command="ls $PLATFORMIO_BUILD_DIR/balboa/firmware.elf"),
        text("done"),
    ]
    api, (report, _), run = dispatch(tmp_path, install_bin, steps, cfg=cfg)
    assert report.end.outcome == "completed", report
    told = "\n".join(r.last_user for r in api.requests if r.thread == "main")
    found = [line for line in told.splitlines() if line.startswith("MARGINS ")]
    assert found, told[-3000:]
    margins = found[0]
    assert json.loads(margins[8:])["phase_margin_deg"] == pytest.approx(28.0202, abs=1e-3)
    assert "used 4798 bytes from 28672 bytes" in told and "used 173 bytes from 2560 bytes" in told
    assert "[SUCCESS]" in told
    assert [line for line in told.splitlines() if line.endswith("/pio-build/balboa/firmware.elf")]
    # Nothing was built into the module, so the committed attempt holds no build artefact.
    assert not (module / ".pio").exists()
    assert report.attempt_commit is not None
    committed = git(run.repo, "ls-tree", "-r", "--name-only", report.attempt_commit).splitlines()
    assert "modules/power/src/main.cpp" in committed
    assert not [p for p in committed if ".pio/" in p or p.endswith((".elf", ".hex", ".o"))]
    assert scan([root]) == before
