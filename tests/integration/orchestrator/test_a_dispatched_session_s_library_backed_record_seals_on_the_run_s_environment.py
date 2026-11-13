"""Through the dispatcher and the real binary: a library-backed record seals on its environment.

A run that names a provisioned tool environment (``PHYSGATE_TOOL_ENVIRONMENT``), inside the OS
layer with no network. The session's module script imports python-control and MuJoCo from the
environment, records a step response and a loop's frequency response through the writer the run
branch carries, and both seal on the session's end line, each naming the environment once by its
digest. The same script run on a virtual environment the session made, with its own edited copy
of ``control``, is refused at collection, as is one run with ``PYTHONHOME`` pointed at a tree of
the session's own holding such a copy: neither names only the run's environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from git_rig import config
from scripted_endpoint import text, tool
from test_a_session_is_dispatched_under_the_hooks import SPEC, dispatch, knowledge_reads

from physgate.orchestrator.git import commit_all
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.run_config import RunBounds
from physgate.orchestrator.tool_environment import measure_named
from physgate.orchestrator.trajectory import Seal
from physgate.oslayer.probe import Present, judge_here
from physgate.series.collect import REFUSED_DIR, series_library
from physgate.series.reader import read_record, record_path
from physgate.toolenv.manifest import scan

pytestmark = [pytest.mark.integration]

PROVISIONED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")

#: A step response and a loop's frequency response of a fixture plant, recorded under the id
#: given; the numbers are the library's, the plant a fixture's.
STEP = """import sys, os
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
import control, mujoco, numpy
name = sys.argv[1]
loop = control.tf([4, 4], [1, 2, 1, 0])
t, y = control.step_response(control.feedback(loop, 1), numpy.linspace(0.0, 5.0, 51))
series_writer.record(name + "_step", title="Fixture plant, closed-loop step", axis="time",
    x=("time", "s", [float(v) for v in t]), traces=[("position", "m", [float(v) for v in y])],
    inputs={"seed": (7, "dimensionless")}, group="step")
w = numpy.logspace(-1, 1, 21)
mag, phase, w = control.frequency_response(loop, w)
series_writer.record(name + "_loop", title="Fixture plant, loop response", axis="frequency",
    x=("angular_frequency", "rad/s", [float(v) for v in w]),
    traces=[("loop_magnitude", "dimensionless", [float(v) for v in mag]),
            ("loop_phase", "rad", [float(v) for v in phase])],
    inputs={"seed": (7, "dimensionless")}, group="frequency_response")
print("RECORDED " + name + " " + mujoco.__version__)
"""


#: The session's own copy of ``control``, edited, in a virtual environment it makes; the script
#: run on it. Every path is found as the program runs, so no command names the environment.
OWN_VENV = """import control, os, shutil, subprocess, sys
def writable(top):
    for here, _dirs, files in os.walk(top):
        os.chmod(here, 0o755)
        for name in files:
            if not os.path.islink(os.path.join(here, name)):
                os.chmod(os.path.join(here, name), 0o644)
temp = os.path.dirname(os.environ["MPLCONFIGDIR"])
own = os.path.join(temp, "own")
subprocess.run([sys.executable, "-m", "venv", "--without-pip", own], check=True)
site = os.path.join(own, "lib", "python3.12", "site-packages")
library = os.path.dirname(control.__file__)
shutil.copytree(library, os.path.join(site, "control"))
writable(os.path.join(site, "control"))
with open(os.path.join(site, "control", "__init__.py"), "a") as edited:
    edited.write("EDITED = True\\n")
with open(os.path.join(site, "environment.pth"), "w") as rest:
    rest.write(os.path.dirname(library) + "\\n")
subprocess.run([os.path.join(own, "bin", "python"), "step.py", "venv"], check=True)
"""
#: The same, with ``PYTHONHOME`` at a tree of the session's own: the standard library copied in,
#: and the edited ``control`` in its site-packages.
OWN_HOME = """import control, os, shutil, subprocess, sys
def writable(top):
    for here, _dirs, files in os.walk(top):
        os.chmod(here, 0o755)
        for name in files:
            if not os.path.islink(os.path.join(here, name)):
                os.chmod(os.path.join(here, name), 0o644)
temp = os.path.dirname(os.environ["MPLCONFIGDIR"])
home = os.path.join(temp, "home")
stdlib = os.path.join(home, "lib", "python3.12")
shutil.copytree(os.path.join(sys.base_prefix, "lib", "python3.12"), stdlib, symlinks=True)
writable(home)
site = os.path.join(stdlib, "site-packages")
library = os.path.dirname(control.__file__)
shutil.copytree(library, os.path.join(site, "control"))
writable(os.path.join(site, "control"))
with open(os.path.join(site, "control", "__init__.py"), "a") as edited:
    edited.write("EDITED = True\\n")
with open(os.path.join(site, "environment.pth"), "w") as rest:
    rest.write(os.path.dirname(library) + "\\n")
base = os.path.realpath(sys._base_executable)
env = dict(os.environ, PYTHONHOME=home)
subprocess.run([base, "step.py", "home"], check=True, env=env)
"""


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _with_the_writer(run: RunGit) -> None:
    """The run branch carries the writer, as decomposition puts it there."""
    for relative, data in series_library().items():
        path = run.integration / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    commit_all(run.integration, "the series writer\n")


def test_a_library_backed_record_seals_and_a_session_s_own_copy_of_the_library_does_not(
    tmp_path: Path,
    install_bin: Path,
) -> None:
    if not PROVISIONED:
        pytest.skip("no provisioned tool environment named")
    path = f"{Path(claude_binary()).parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    layer = judge_here(claude_version=config().claude_version, search_path=path)
    if not isinstance(layer, Present):
        pytest.skip("the OS layer cannot run here")
    root = Path(PROVISIONED)
    interpreter = root / "venv" / "bin" / "python3"
    measured = measure_named({"interpreter": str(interpreter), "roots": [str(root)]}, forbidden={})
    cfg = config().model_copy(
        update={
            "tool_environment": measured,
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
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    module = worktree / "modules" / "power"
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(module / "step.py"), content=STEP),
        tool("Bash", command=f"cd {module} && python3 step.py plant 2>&1 | tail -3"),
        tool("Bash", command=f"cd {module} && python3 - <<'EOF' 2>&1 | tail -3\n{OWN_VENV}EOF"),
        tool("Bash", command=f"cd {module} && python3 - <<'EOF' 2>&1 | tail -3\n{OWN_HOME}EOF"),
        text("done"),
    ]
    api, (report, _), run = dispatch(tmp_path, install_bin, steps, cfg=cfg, before=_with_the_writer)
    assert report.end.outcome == "completed", report
    told = [r.last_user for r in api.requests if r.thread == "main"]
    recorded = [line for said in told for line in said.splitlines() if line.startswith("RECORDED ")]
    assert len(recorded) == 3, told[-3:]
    series = report.series
    assert sorted(r.record_id for r in series.records) == ["plant_loop", "plant_step"], series
    refused = {e.name: e.reason for e in series.refused}
    assert sorted(refused) == [
        "home_loop.json",
        "home_step.json",
        "venv_loop.json",
        "venv_step.json",
    ], series
    session_id = Path(str(report.trajectory)).parent.name
    kept = run.run_dir / "series" / REFUSED_DIR / "s1" / "1" / session_id
    for name, reason in refused.items():
        assert "not the run's tool environment" in reason, reason
        # The session's own edited copy is named by its path in the session's temporary
        # directory, never left out.
        loaded = json.loads((kept / name).read_bytes())["producer"]["loaded"]
        copies = [e["path"] for e in loaded if e["path"].endswith("/control/__init__.py")]
        assert copies and all("/pgs/" in path for path in copies), (name, copies)
    for sealed in series.records:
        held = record_path(run.run_dir, "s1", 1, session_id, sealed.record_id)
        environment = json.loads(held.read_bytes())["producer"]["environment"]
        assert environment == {"roots": [str(root)], "sha256": measured.manifest_digest}
        seal = Seal(sha256=sealed.sha256, length=sealed.length)
        assert read_record(held, seal).producer.environment is not None
    assert scan([root]) == before
