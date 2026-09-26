"""A whole run through the ``physgate`` command, with the real binary and no model.

`physgate decompose`, then `physgate run`, then `physgate resume`, against the
scripted endpoint: the plan is decomposed with one call, the subtask's session
reads, implements and proposes a node under the hooks, the registered test gate
and reviewer pass it, it is merged, and its worktree is removed. The token
account attributes every token to decomposition, a session or a reviewer, and
routing is zero.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import Gate, Reviewer, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.decompose import mint_id
from physgate.orchestrator.events import Merged, TokensUsed, WorktreeRemoved, read_events
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage
from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

INTERFACE: dict[str, Any] = {
    "id": "iface.power_bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}
DRIVER = {**INTERFACE, "id": "electrical.driver", "kind": "component"}
PLAN = {
    "modules": [
        {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "Size it."}
    ],
    "interface_nodes": [INTERFACE],
}


class _PayingReviewer(Reviewer):
    """The test reviewer, reporting the tokens a real one would, so the account sees them."""

    def review(self, artefact: Any) -> ReviewResult:
        result = super().review(artefact)
        usage = Usage(
            input_tokens=40,
            output_tokens=9,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return result.model_copy(update={"usage": (MessageUsage(message_id="r1", usage=usage),)})


def test_decompose_run_and_resume_through_the_command_with_routing_at_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    params = config().model_dump(include={"auth", "gate_mode", "models", "bounds", "token_ceiling"})
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    registrations = Registrations(gate=Gate(), reviewers={"electrical": _PayingReviewer()})

    # One endpoint for the whole run: the run records it at decomposition and
    # refuses to be driven against another.
    with serving(Script(main=[tool("StructuredOutput", **PLAN)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        code = main(
            [
                "decompose",
                str(tmp_path / "brief.md"),
                "--seed",
                "7",
                "--run-id",
                "run-1",
                "--params",
                str(tmp_path / "params.json"),
                "--target",
                str(repo),
                "--run-dir",
                str(run_dir),
            ]
        )
        assert code == 0, capsys.readouterr().err
        capsys.readouterr()
        recorded = json.loads((run_dir / "run.json").read_text())
        assert (recorded["endpoint"], recorded["auth"]) == (url, "api_key")
        assert DUMMY_KEY not in (run_dir / "run.json").read_text()

        subtask = mint_id(7, 0, "power")
        worktree = run_dir / "worktrees" / subtask
        api.script = Script(
            main=[
                tool("Read", file_path=str(worktree / ".physgate" / "specs" / f"{subtask}.md")),
                tool("Bash", command="echo 'x = 1' > modules/power/driver.py"),
                tool(
                    "Write",
                    file_path=str(worktree / ".physgate" / "proposals" / "electrical.driver.json"),
                    content=json.dumps(DRIVER),
                ),
                text("done"),
            ]
        )
        common = ["--run-dir", str(run_dir), "--target", str(repo), "--install", str(install)]
        code = main(["run", *common], registrations)
        out = capsys.readouterr()
        assert code == 0, out.err
        printed = json.loads(out.out)
        code = main(["resume", *common], registrations)
        again = capsys.readouterr()
    assert code == 0, again.err

    assert printed["step"] == "done" and printed["subtasks"] == {subtask: "done"}
    assert printed["tokens"]["routing"] == 0 and printed["tokens"]["session"] > 0
    events = read_events(run_dir / "events.jsonl")
    account = TokenAccount.from_events(events)
    account.assert_no_routing()
    assert account.decomposition_invocations() == 1
    kinds = {a.split(":", 1)[0] for a in account.by_attribution()}
    assert kinds == {"decomposition", "session", "reviewer"}
    attributed = sum(u.total() for u in account.by_kind().values())
    recorded = {
        (e.attribution, e.message_id): e.usage.total() for e in events if isinstance(e, TokensUsed)
    }
    assert attributed == sum(recorded.values()) > 0
    lines = TaskLedger(run_dir / "ledger.jsonl").read_all()
    assert {line.id for line in lines if line.attempt_count >= 1} == {subtask}
    (merged,) = [e for e in events if isinstance(e, Merged)]
    assert lines[-1].merge_commit == merged.merge_commit
    store = Store(run_dir / "store")
    assert store.read_node("electrical.driver")["owner_role"] == "electrical"
    store.close()
    (removed,) = [e for e in events if isinstance(e, WorktreeRemoved)]
    assert removed.outcome == "removed" and not worktree.exists()
    assert len(api.requests) >= 1
