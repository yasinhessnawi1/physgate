"""A later trial's role session reaches nothing an earlier trial of the round left.

A round's trials are runs beside one another beneath one registered run root. An earlier
trial's run directory holds its configuration (every canary of the store), its specification
(written from its task's brief) and its answer. So a session of a later trial must be refused a
read of each: a measured run withholds every registered run root of the stores it names, whole,
and its session reaches only its own worktree there.

The session is installed here as the dispatcher installs one, for the second trial of a
two-trial round on the held-out tier: the install's own request, built into the hook layer's
configuration, is asked about each of the first trial's three files.

Waits on the change in flight that makes a measured run withhold its stores' run roots whole;
until it is on master the hook layer lets these reads through, and the row fails on its
assertion. Once that change is merged here, the row passes and its mark is taken off.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, make_rig

from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root
from physgate.hooks import cli as hooks_cli
from physgate.hooks import paths
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Decomposed, SubtaskPlanned, read_events
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import load_run_config


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _installed(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[InstallRequest, Path]:
    """The request the dispatcher installs the run's role session with, and its worktree."""
    config = load_run_config(run_dir / "run.json")
    events = read_events(run_dir / "events.jsonl")
    (planned,) = [e for e in events if isinstance(e, SubtaskPlanned)]
    (decomposed,) = [e for e in events if isinstance(e, Decomposed)]
    run = RunGit(repo=run_dir / "target", run_dir=run_dir, run_id=config.run_id)
    worktree = run.open_subtask(planned.subtask_id)
    taken: list[InstallRequest] = []
    real_run = subprocess.run

    def install_here(argv: list[str], **kw: Any) -> Any:  # noqa: ANN401
        if list(argv[1:3]) != ["hooks", "install"]:
            return real_run(argv, **kw)  # every other command (git among them) runs as it does

        # The installer's own reading of the command line the dispatcher built.
        def keep(request: InstallRequest, _registry: Any) -> Any:  # noqa: ANN401
            taken.append(request)
            raise SystemExit(0)

        monkeypatch.setattr(hooks_cli, "install", keep)
        with pytest.raises(SystemExit):
            hooks_cli.main(argv[1:])
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", install_here)
    dispatcher = ClaudeDispatcher(
        config=config,
        run=run,
        store_root=run_dir / "store",
        install_bin=run_dir.parent / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=run_dir / "review",
    )
    request = SessionRequest(
        subtask_id=planned.subtask_id,
        attempt=2,
        assigned_role="control",
        spec_path=planned.spec_path,
        module_dir=planned.module_dir,
        model=config.models.roles["control"],
        repair_instruction=None,
        bounds=config.bounds,
        spec_commit=decomposed.spec_commit,
    )
    sdir = run_dir / "sessions" / "later-session"
    dispatcher._install(request, worktree, sdir, None, own_temp=run_dir / "tmp")  # noqa: SLF001
    (made,) = taken
    return made, worktree


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "waits for the sibling-runs fix (fix/sibling-runs-withheld): a measured run withholds "
        "every registered run root of its stores whole, a session reaching its own worktree only"
    ),
)
def test_the_second_trial_s_session_is_refused_the_first_trial_s_record_spec_and_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path)
    status, summary = run_round(
        rig.inputs(tiers=("held_out",), trials=2, tasks=1),
        driver=rig.driver(),
        scorer=_score,
        sleep=lambda _: None,
    )
    assert status == "done"
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / summary["round"]
    record = json.loads((place / ROUND_RECORD).read_bytes())
    first, second = (Path(t["run_dir"]) for t in record["trials"])
    planned = next(e for e in read_events(first / "events.jsonl") if isinstance(e, SubtaskPlanned))
    reached = {
        "configuration": first / "run.json",
        "specification": first / "worktrees" / "_integration" / planned.spec_path,
        # The run branch as merged, checked out in the orchestrator's own worktree.
        "answer": first / "worktrees" / "_integration" / planned.module_dir / "answer.json",
    }
    # The rig, proven before the one assertion the mark waits on: a failure here is no wait.
    # What the row asks about is there, at the path asked: no read of it fails for want of it.
    for name, path in reached.items():
        if not path.is_file():
            pytest.fail(f"the first trial left no {name} at the path the row asks about")
    request, worktree = _installed(second, monkeypatch)
    config = build_config(request, current_installation())
    # And the configuration built is the session's: its own run's record it may not read.
    if paths.protection(str(second / "run.json"), str(worktree), config, writing=False) is None:
        pytest.fail("the session as installed here may read its own run's configuration")
    let_through = sorted(
        name
        for name, path in reached.items()
        if paths.protection(str(path), str(worktree), config, writing=False) is None
    )
    assert let_through == [], f"the later trial's session may read the earlier's {let_through}"
