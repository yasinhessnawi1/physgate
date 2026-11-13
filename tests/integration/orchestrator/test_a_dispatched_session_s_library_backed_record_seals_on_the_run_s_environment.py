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
import subprocess
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
from physgate.series.collect import series_library
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


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _places(interpreter: Path) -> tuple[str, str]:
    """The environment interpreter's own installation, and where ``control`` lies in it."""
    said = subprocess.run(
        [
            str(interpreter),
            "-I",
            "-c",
            "import sys, os, control; print(sys.base_prefix); "
            "print(os.path.dirname(os.path.dirname(control.__file__)))",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.split("\n")
    return said[0], said[1]


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
    base, site = _places(interpreter)
    version = "python3.12"
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
    temp = 'T="$(dirname "$MPLCONFIGDIR")"'
    venv = (
        f"{temp} && python3 -m venv --without-pip $T/own && "
        f"cp -R {site}/control $T/own/lib/{version}/site-packages/control && "
        f"echo 'EDITED = True' >> $T/own/lib/{version}/site-packages/control/__init__.py && "
        f"echo {site} > $T/own/lib/{version}/site-packages/environment.pth && "
        f"cd {module} && $T/own/bin/python step.py venv"
    )
    home = (
        f"{temp} && mkdir -p $T/home/lib && cp -R {base}/lib/{version} $T/home/lib/{version} && "
        f"cp -R {site}/control $T/home/lib/{version}/site-packages/control && "
        f"echo 'EDITED = True' >> $T/home/lib/{version}/site-packages/control/__init__.py && "
        f"echo {site} > $T/home/lib/{version}/site-packages/environment.pth && "
        f"cd {module} && PYTHONHOME=$T/home {base}/bin/{version} step.py home"
    )
    steps = [
        *knowledge_reads(worktree),
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(module / "step.py"), content=STEP),
        tool("Bash", command=f"cd {module} && python3 step.py plant 2>&1 | tail -3"),
        tool("Bash", command=f"({venv}) 2>&1 | tail -3", timeout=600000),
        tool("Bash", command=f"({home}) 2>&1 | tail -3", timeout=600000),
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
    for reason in refused.values():
        assert "not the run's tool environment" in reason, reason
        assert "/control/" in reason, reason
    session_id = Path(str(report.trajectory)).parent.name
    for sealed in series.records:
        held = record_path(run.run_dir, "s1", 1, session_id, sealed.record_id)
        environment = json.loads(held.read_bytes())["producer"]["environment"]
        assert environment == {"roots": [str(root)], "sha256": measured.manifest_digest}
        seal = Seal(sha256=sealed.sha256, length=sealed.length)
        assert read_record(held, seal).producer.environment is not None
    assert scan([root]) == before
