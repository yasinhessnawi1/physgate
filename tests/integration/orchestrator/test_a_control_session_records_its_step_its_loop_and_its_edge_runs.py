"""Through ``physgate run`` on the real binary: a control session records its runs via the hooks.

A scripted control session on the real binary writes the stand-in control script into its
module and runs it with the session's own ``python3``, as its prompt tells it to. The script
records the nominal step, the loop's frequency response and four edge runs through the writer,
reads the phase margin and the step's peak off its own records, and writes the node proposal
carrying them, each naming its record. Every shell call passes the hook layer.

What is held: the dispatcher collects and seals all six records on the session's end line;
the change check holds both quantities to their records and finds that they agree; the
attempt merges. No model is called: the endpoint is scripted, and the gate observes.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from gate_run import PayingReviewer, build_install
from git_rig import PARAMS, config, target_repo
from knowledge_fixture import fixture_text
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from stand_in_control import CONTROL_SCRIPT, RECORD_IDS

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.knowledge import loader
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import Merged, ProposalsChecked, SessionEnded, read_events
from physgate.orchestrator.git import commit_all
from physgate.orchestrator.run_config import ModelStrings

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


#: The interface the plan declares: the control role's own, so the plan names a role for it.
INTERFACE: dict[str, Any] = {
    "id": "iface.balance",
    "kind": "interface",
    "domain": "control",
    "owner_role": "control",
    "quantities": {
        "rate": {"value": 200, "unit": "Hz", "source": "brief", "written_by": "control"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-10-16T00:00:00Z",
}


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def test_a_control_session_s_records_are_sealed_and_its_quantities_agree_with_them(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reads = [
        tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
        for relative in loader.always_loaded("control")
    ]
    session = Script(
        main=[
            *reads,
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool("Read", file_path=f"{{cwd}}/.physgate/interfaces/{INTERFACE['id']}.json"),
            tool("Write", file_path="{cwd}/modules/control/sim.py", content=CONTROL_SCRIPT),
            tool(
                "Bash",
                command="python3 modules/control/sim.py control.loop",
                description="simulate and record",
            ),
            text("done"),
        ]
    )
    repo = target_repo(tmp_path)
    for relative in loader.always_loaded("control"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fixture_text(relative))
    commit_all(repo, "curated knowledge fixture\n")
    run_dir = tmp_path / "run"
    params = config().model_copy(
        update={
            "gate_mode": "observe",
            "models": ModelStrings(
                decomposition="claude-sonnet-5",
                roles={"control": "claude-sonnet-5"},
                reviewers={"control": "claude-opus-5-5"},
            ),
        }
    )
    (tmp_path / "params.json").write_text(json.dumps(params.model_dump(include=PARAMS)))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot; start with its control.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "balance", "role": "control", "module_dir": "modules/control", "spec": "x"}
        ],
        "interface_nodes": [INTERFACE],
    }
    registrations = Registrations(gate=PhysicsGate(), reviewers={"control": PayingReviewer()})
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
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert ended and ended[0].outcome == "completed", ended
    first = ended[0]
    assert sorted(r.record_id for r in first.series.records) == sorted(RECORD_IDS), first.series
    assert first.series.refused == ()
    checked = next(e for e in events if isinstance(e, ProposalsChecked))
    assert checked.refused_by is None, checked
    assert sorted((c.quantity, c.outcome) for c in checked.series_checks) == [
        ("phase_margin", "agrees"),
        ("step_peak", "agrees"),
    ]
    assert [e for e in events if isinstance(e, Merged)]
