"""Each review arm of an ablation run, through the ``physgate`` command on the real binary.

`physgate decompose`, then `physgate run`, with the reviewer factory the command registers, every
session on the real binary against the scripted endpoint: no model is called. The paired arm is
the run beside this file's neighbour (the reviewed, rejected, repaired and accepted run); here:

- ``reviewers: off``: the role session runs and the subtask merges on the gate's result alone,
  with its review recorded as skipped and no reviewer session spawned or charged;
- ``reviewers: generalist``: the reviewer session judges with the generalist rubric of the
  role's promoted paired rubric, from a packet that holds the cross standards and none of the
  role's own files, and its review line names that rubric's kind and digest.

The evaluation's requirements for an ablation run (the OS layer, a reviewed plan, an enforced
network) and its clean checkout are other rows' to hold, so this row lets the command past them
and keeps the rest: the harness is measured as its own commit, clean, at both commands alike (the
pinned binary's rig leaves files in the checkout on one pin).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from gate_run import BRIEF, INTERFACE, seed_knowledge, session
from git_rig import Gate, run_params, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from test_a_run_is_reviewed_by_the_claude_reviewer_through_the_command import (
    _config,
    _library,
    _reading,
    _verdict,
    install,
)

from physgate.cli import main
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator import cli
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import ReviewRan, read_events
from physgate.orchestrator.run_config import HarnessState, harness_state
from physgate.reviewers.claude import claude_reviewers
from physgate.reviewers.packet import RECORD_NAME, WORKTREE_NAME
from physgate.reviewers.rubric import NOT_IN_REVIEW, generalist_of, load_rubric

__all__ = ["install"]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]


def _drive(tmp_path: Path, install: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> Any:  # noqa: ANN401
    library, _ = _library(tmp_path / "lib")
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: library)
    monkeypatch.setattr(cli, "refusals", lambda *_a: [])
    measured = harness_state(cli._harness_root())
    clean = HarnessState(commit=measured.commit, clean=True, uncommitted_sha256=None)
    monkeypatch.setattr(cli, "harness_state", lambda _root: clean)
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    arm = _config().model_copy(update={"reviewers": value, "ablation": True})
    (tmp_path / "params.json").write_text(json.dumps(run_params(arm)))
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "Size."}
        ],
        "interface_nodes": [INTERFACE],
    }
    role_steps = session().main
    reviewed: list[str] = []

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        if not cwd.endswith(f"/read/{WORKTREE_NAME}"):
            return role_steps[done] if done < len(role_steps) else text("done")
        reviewed.append(cwd)
        verdict = _verdict("accept")
        if NOT_IN_REVIEW in (Path(cwd).parent / "rubric.md").read_text():
            verdict["items"] = {
                k: v for k, v in verdict["items"].items() if k.startswith(("AC-", "RH-"))
            }
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", review=verdict))
        return steps[done] if done < len(steps) else text("done")

    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        api.script = Script(main=[])
        api.on_request = step
        common = [*where, "--install", str(install), "--review-root", str(tmp_path / "rs")]
        registrations = Registrations(gate=Gate(), reviewer_factory=claude_reviewers)
        code = main(["run", *common], registrations)
    return code, run_dir, library, reviewed


def test_under_reviewers_off_the_subtask_merges_on_the_gate_with_no_reviewer_session(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, run_dir, _, reviewed = _drive(tmp_path, install, monkeypatch, "off")
    out = capsys.readouterr()
    assert code == 0, out.err
    kinds = [json.loads(raw)["kind"] for raw in (run_dir / "events.jsonl").read_text().splitlines()]
    assert kinds.count("review_skipped") == 1 and "review_ran" not in kinds
    assert "merged" in kinds
    assert reviewed == [], "a reviewer session was spawned under reviewers: off"
    assert not (tmp_path / "rs").exists() or not any((tmp_path / "rs").iterdir())
    events = read_events(run_dir / "events.jsonl")
    charged = TokenAccount.from_events(events).by_attribution()
    assert not any(name.startswith("reviewer:") for name in charged), sorted(charged)


def test_under_reviewers_generalist_the_review_is_judged_with_the_generalist_rubric(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, run_dir, library, reviewed = _drive(tmp_path, install, monkeypatch, "generalist")
    out = capsys.readouterr()
    assert code == 0, out.err
    assert len(reviewed) >= 1
    events = read_events(run_dir / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    wanted = generalist_of(load_rubric(library / KNOWLEDGE_ROOT, "electrical"))
    assert ran.result.rubric_kind == "generalist" and ran.result.verdict == "pass"
    assert ran.result.rubric_sha256 == wanted.sha256
    packet = json.loads((tmp_path / "rs" / ran.result.session_id / RECORD_NAME).read_text())
    assert sorted(packet["knowledge_sha256"]) == ["knowledge/cross/standards.md"]
