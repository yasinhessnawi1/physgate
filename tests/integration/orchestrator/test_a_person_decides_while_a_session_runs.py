"""A person's queue decision made while a session runs stands; the session cannot write one.

The items file is written by the orchestrator only between sessions and is put
back if it changes during one. A person decides whenever they decide, so their
decisions go to a file of their own that a session's tools may not write and the
hook layer does not put back. Reproduced before the split: a decision appended
during a session was reverted at the session's next hook, after the command had
reported success.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from git_rig import Gate, Reviewer
from kill_cycles import SUBTASKS, build
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import WorktreeRemoved, read_events
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.queue import DECISIONS_NAME

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]


def test_a_decision_made_during_a_session_stands_and_the_session_cannot_write_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = SUBTASKS
    run_dir = tmp_path / "run"
    item_id = f"run-1-{first}"
    install = tmp_path / "install"
    prepare_install(install, Path(__file__).resolve().parents[3])
    session = Script(
        main=[
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool("Bash", command=f"sleep 2; echo forged >> ../../{DECISIONS_NAME}"),
            text("done"),
        ]
    )
    decided: list[int] = []

    def decide_during_the_second_subtask(thread: str, cwd: str, results: int) -> None:
        # The first request of the second subtask's session: it is alive, its hooks on.
        if Path(cwd).name == second and results == 0 and not decided:
            argv = ["queue", "resolve", item_id, "--run-dir", str(run_dir)]
            decided.append(main([*argv, "--decision", "split it", "--by", "yasin"]))

    with serving(session) as (api, url):
        api.on_request = decide_during_the_second_subtask
        build(tmp_path, url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        # The first subtask fails the gate three times and is escalated; the second passes.
        gate = Gate(verdicts=["fail", "fail", "fail", "pass"])
        registrations = Registrations(gate=gate, reviewers={"electrical": Reviewer()})
        args = ["--run-dir", str(run_dir), "--target", str(tmp_path / "target")]
        code = main(["run", *args, "--install", str(install)], registrations)
    out = capsys.readouterr()
    assert code == 0, out.err
    assert decided == [0], "the person's decision was recorded while the session ran"

    decisions = [json.loads(line) for line in (run_dir / DECISIONS_NAME).read_text().splitlines()]
    assert [(d["item_id"], d["decision"], d["resolved_by"]) for d in decisions] == [
        (item_id, "split it", "yasin")
    ]
    streams = [p.read_text() for p in (run_dir / "sessions").glob("*/stdout.jsonl")]
    results: list[str] = []
    for stream in streams:
        for line in stream.splitlines():
            event: dict[str, Any] = json.loads(line)
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results.append(str(block.get("content")))
    refused = [r for r in results if DECISIONS_NAME in r and "protected" in r]
    assert len(refused) == len(streams) == 4  # every session's write, refused
    removed = {
        e.subtask_id: e.reason
        for e in read_events(run_dir / "events.jsonl")
        if isinstance(e, WorktreeRemoved)
    }
    assert removed == {first: "queue_resolved", second: "done"}
