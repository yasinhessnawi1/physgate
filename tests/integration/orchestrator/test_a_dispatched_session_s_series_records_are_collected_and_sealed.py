"""Through ``physgate run``: a session's series record is collected and sealed by real dispatch.

A scripted session on the real binary writes a script into its module and runs it with the
session's own ``python3``; the script records one series through the writer that
decomposition put into the run branch. The dispatcher, not the test, collects the outbox
before it commits: the record is sealed on the session's end line, it reads back held to
that seal, and no commit of the run holds it, nor the interpreter's cache of the writer.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from gate_run import INTERFACE, PayingReviewer, build_install, seed_knowledge
from git_rig import PARAMS, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.knowledge import loader
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import SessionEnded, read_events
from physgate.series.reader import attempt_records, read_record

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
    pytest.mark.skipif(
        shutil.which("python3", path="/usr/bin:/bin") is None,
        reason="no python3 on a session's path on this machine",
    ),
]

#: A stand-in simulation: no physics, numbers made up and labelled so.
SCRIPT = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
series_writer.record("step", title="Stand-in step, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01, 0.02]), traces=[("position", "m", [0.0, 0.02, 0.05])],
    inputs={"seed": (7, "dimensionless")})
"""


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def test_a_record_a_session_writes_is_sealed_on_its_end_and_never_committed(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reads = [
        tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
        for relative in loader.always_loaded("electrical")
    ]
    session = Script(
        main=[
            *reads,
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool("Write", file_path="{cwd}/modules/power/sim.py", content=SCRIPT),
            tool("Bash", command="python3 modules/power/sim.py", description="record"),
            text("done"),
        ]
    )
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    (tmp_path / "params.json").write_text(json.dumps(config().model_dump(include=PARAMS)))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot; start with its power.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "drive", "role": "electrical", "module_dir": "modules/power", "spec": "x"}
        ],
        "interface_nodes": [INTERFACE],
    }
    registrations = Registrations(gate=PhysicsGate(), reviewers={"electrical": PayingReviewer()})
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        common = ["--target", str(repo), "--run-dir", str(run_dir)]
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *common]) == 0
        capsys.readouterr()
        api.script = session
        main(
            ["run", *common, "--install", str(install), "--review-root", str(tmp_path / "rs")],
            registrations,
        )
        capsys.readouterr()
    events = read_events(run_dir / "events.jsonl")
    (ended,) = [e for e in events if isinstance(e, SessionEnded)]
    assert ended.outcome == "completed"
    assert [r.record_id for r in ended.series.records] == ["step"], ended.series
    assert ended.series.refused == ()
    (entry,) = attempt_records(events, ended.subtask_id, ended.attempt)
    record = read_record(entry.path(run_dir), entry.seal())
    assert record.producer.script.path == "modules/power/sim.py"
    assert ended.attempt_commit is not None
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ended.attempt_commit],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "modules/power/sim.py" in listed
    assert ".physgate/lib/series_writer.py" in listed
    assert not [f for f in listed if f.startswith(".physgate/series")]
    assert not [f for f in listed if f.startswith(".physgate/lib/__pycache__")]
