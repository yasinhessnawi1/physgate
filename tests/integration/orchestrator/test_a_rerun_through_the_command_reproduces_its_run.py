"""A rerun through the ``physgate`` command reproduces a scripted run exactly.

The real binary, the real hooks' installation and the real physics gate, with
every model call answered by the scripted endpoint on this machine. One run is
decomposed and driven through the command; then ``rerun`` makes it again from its
own record, through the same two commands, against the same endpoint, and the
comparison must find no divergence in any record. Then a rerun whose session
writes a node with a bare number where a quantity belongs is named at the line,
subtask, attempt and stage where it parts. The hooks refuse that write, so the
decisions stay the recorded run's and only the exact comparison can see it.

The brief is the physics gate's stand-in: the drive power module of the
self-balancing robot, not the reference design's brief. The gate observes, so
the module merges and the integration gate runs.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from gate_run import INTERFACE, PayingReviewer, build_install, seed_knowledge, session
from git_rig import PARAMS, config, target_repo
from scripted_endpoint import DUMMY_KEY, FakeMessagesApi, Script, serving, tool
from stand_in_drive_plan import DRIVE_MODULE, STAND_IN_BRIEF

from physgate.cli import main
from physgate.evaluation.observe.rerun import Comparison, rerun, through_the_command
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.cli import Registrations

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

PLAN = {
    "modules": [
        {"name": "drive", "role": "electrical", "module_dir": "modules/power", "spec": "Size it."}
    ],
    "interface_nodes": [INTERFACE],
}


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def registrations() -> Registrations:
    return Registrations(gate=PhysicsGate(), reviewers={"electrical": PayingReviewer()})


def one_script(payloads: tuple[dict[str, Any], ...]) -> tuple[Script, Callable[..., Any]]:
    """One script for both calls: the plan to the decomposition, the session's steps after."""
    plan = tool("StructuredOutput", **PLAN)

    def on_request(thread: str, cwd: str, done: int) -> dict[str, Any] | None:
        return plan if cwd.endswith("/decomposition/cwd") and done == 0 else None

    return session(*payloads), on_request


def serve(api: FakeMessagesApi, payloads: tuple[dict[str, Any], ...]) -> None:
    api.script, api.on_request = one_script(payloads)


def record_a_run(tmp_path: Path, repo: Path, install: Path, api: FakeMessagesApi) -> Path:
    params = config().model_dump(include=PARAMS)
    params["gate_mode"] = "observe"
    (tmp_path / "params.json").write_text(json.dumps(params))
    run_dir = tmp_path / "run-a"
    serve(api, DRIVE_MODULE)
    code = main(
        [
            "decompose",
            str(tmp_path / "brief.md"),
            "--seed",
            "7",
            "--run-id",
            "run-a",
            "--params",
            str(tmp_path / "params.json"),
            "--target",
            str(repo),
            "--run-dir",
            str(run_dir),
        ]
    )
    assert code == 0
    code = main(
        [
            "run",
            "--run-dir",
            str(run_dir),
            "--target",
            str(repo),
            "--install",
            str(install),
            "--review-root",
            str(tmp_path / "rs"),
        ],
        registrations(),
    )
    assert code == 0
    return run_dir


def rerun_of(run: Path, tmp_path: Path, repo: Path, install: Path, run_id: str) -> Comparison:
    return rerun(
        run,
        brief=tmp_path / "brief.md",
        run_id=run_id,
        run_dir=tmp_path / run_id,
        target=repo,
        install=install,
        review_root=tmp_path / "rs",
        driver=through_the_command(registrations()),
    )


def test_a_scripted_run_rerun_through_the_command_reproduces_every_record(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    (tmp_path / "brief.md").write_text(STAND_IN_BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    with serving(Script(main=[])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        run = record_a_run(tmp_path, repo, install, api)
        serve(api, DRIVE_MODULE)
        same = rerun_of(run, tmp_path, repo, install, "run-b")
        assert api.failures == []
        evidence = os.environ.get("PHYSGATE_EVIDENCE_DIR")
        if evidence:
            (Path(evidence) / "scripted_rerun.json").write_text(same.model_dump_json(indent=1))
        assert same.level == "exact"
        assert {k: v for k, v in same.exact.items() if v is not None} == {}
        assert same.decisions is None and same.reproduced
        assert same.decisions_compared >= 5

        # The same, as a person runs it: ``physgate rerun``, exit 0 and both ids printed.
        serve(api, DRIVE_MODULE)
        capsys.readouterr()
        argv = ["rerun", str(run), "--brief", str(tmp_path / "brief.md"), "--run-id", "run-d"]
        where = ["--run-dir", str(tmp_path / "run-d"), "--target", str(repo)]
        code = main(
            [*argv, *where, "--install", str(install), "--review-root", str(tmp_path / "rs")],
            registrations(),
        )
        out = capsys.readouterr()
        assert code == 0, out.out[-4000:] + out.err
        shown = json.loads(out.out[out.out.rindex("\n{\n") + 1 :])
        assert (shown["reproduced"], shown["rule"], shown["first"]) == (True, "exact", None)
        assert shown["recorded_manifest_id"] == same.recorded_manifest_id

        # One proposal with a bare number where a quantity belongs.
        bare = dict(DRIVE_MODULE[0])
        bare["quantities"] = {"power_supply": 20}
        serve(api, (bare, *DRIVE_MODULE[1:]))
        parted = rerun_of(run, tmp_path, repo, install, "run-c")
    first = parted.first
    assert not parted.reproduced and first is not None
    assert (first.record, first.field) == ("events", "attempt_commit")
    assert (first.subtask_id, first.attempt, first.stage) == ("drive-c18c5d", 1, "spawn")
    events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines()]
    ended = next(e for e in events if e["kind"] == "session_ended")
    assert first.seq == ended["seq"]
    # The hooks refuse the bare number at the write, so the attempt holds one proposal
    # fewer and every decision is the recorded run's: the change is in the work, and
    # the exact comparison is what names it.
    assert parted.decisions is None
    assert parted.exact["events"] == first
