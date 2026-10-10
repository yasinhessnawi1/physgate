"""The generalist baseline retries an infrastructure end once, and a refused verdict never.

A run through the ``physgate`` command is reviewed and merged; then ``physgate generalist``
reviews its attempt again, through the real binary against the scripted endpoint. When
the generalist's first session is answered by an API error, the binary ends it as an API
error, the review is retried once with a fresh session, and that one's verdict is the
baseline. When the generalist sends its verdict as a malformed string on every call, the
binary's cap on refused verdicts ends the session, the review is an invalid verdict, and it
is not retried: one session, one line saying so, and the command fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gate_run import BRIEF, INTERFACE, seed_knowledge, session
from git_rig import PARAMS, Gate, config, target_repo
from scripted_endpoint import DUMMY_KEY, FakeMessagesApi, Script, failure, serving, text, tool
from test_a_run_is_reviewed_by_the_claude_reviewer_through_the_command import (
    _library,
    _reading,
    _verdict,
)
from test_a_run_is_reviewed_by_the_claude_reviewer_through_the_command import (
    install as install,  # noqa: F401 - the module's fixture
)
from test_a_run_is_reviewed_by_the_claude_reviewer_through_the_command import (
    pytestmark as pytestmark,  # the same binary requirement
)

from physgate.cli import main
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import ReviewRan, ReviewUnavailable, SubtaskPlanned, read_events
from physgate.reviewers.claude import claude_reviewers
from physgate.reviewers.packet import WORKTREE_NAME
from physgate.reviewers.rubric import NOT_IN_REVIEW


def _generalist_items(verdict: dict[str, Any]) -> dict[str, Any]:
    """The verdict as a generalist gives it: its domain items are not answered."""
    verdict["items"] = {k: v for k, v in verdict["items"].items() if k.startswith(("AC-", "RH-"))}
    return verdict


class Sessions:
    """The scripted endpoint's answers: the run's sessions accept; the generalist's as told."""

    def __init__(self, generalist: str) -> None:
        self.generalist = generalist
        self.role_steps = session().main
        self.generalist_reviews: list[str] = []

    def __call__(self, _thread: str, cwd: str, done: int) -> dict[str, Any]:
        if not cwd.endswith(f"/read/{WORKTREE_NAME}"):
            return self.role_steps[done] if done < len(self.role_steps) else text("done")
        reading = [tool("Read", file_path=p) for p in _reading(cwd)]
        if NOT_IN_REVIEW not in (Path(cwd).parent / "rubric.md").read_text():
            steps = [*reading, tool("StructuredOutput", review=_verdict("accept"))]
            return steps[done] if done < len(steps) else text("done")
        if cwd not in self.generalist_reviews:
            self.generalist_reviews.append(cwd)
        verdict = _generalist_items(_verdict("accept"))
        if self.generalist == "api_error_first" and self.generalist_reviews.index(cwd) == 0:
            return failure(500, "api_error", "Internal server error")
        if self.generalist == "never_corrects":
            if done < len(reading):
                return reading[done]
            return tool("StructuredOutput", review=json.dumps(verdict) + "}")
        steps = [*reading, tool("StructuredOutput", review=verdict)]
        return steps[done] if done < len(steps) else text("done")


def _run_then_generalist(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    generalist: str,
) -> tuple[int, Path, Sessions, FakeMessagesApi]:
    library, _ = _library(tmp_path / "lib")
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: library)
    repo = target_repo(tmp_path)
    seed_knowledge(repo)
    run_dir = tmp_path / "run"
    (tmp_path / "params.json").write_text(json.dumps(config().model_dump(include=PARAMS)))
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "power", "role": "electrical", "module_dir": "modules/power", "spec": "Size."}
        ],
        "interface_nodes": [INTERFACE],
    }
    sessions = Sessions(generalist)
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        assert main(["decompose", str(tmp_path / "brief.md"), *args, *where]) == 0
        capsys.readouterr()
        api.script = Script(main=[])
        api.on_request = sessions
        common = [*where, "--install", str(install), "--review-root", str(tmp_path / "rs")]
        registrations = Registrations(gate=Gate(), reviewer_factory=claude_reviewers)
        code = main(["run", *common], registrations)
        assert code == 0, capsys.readouterr().err
        capsys.readouterr()
        planned = read_events(run_dir / "events.jsonl")
        subtask = next(e.subtask_id for e in planned if isinstance(e, SubtaskPlanned))
        baseline = tmp_path / "generalist"
        generalist_code = main(
            [
                "generalist",
                *common,
                *("--subtask", subtask, "--attempt", "1", "--out", str(baseline)),
                *("--run-id", "run-1-generalist", "--prices", "2026-09-27"),
            ]
        )
        capsys.readouterr()
    return generalist_code, baseline, sessions, api


def test_an_api_error_is_retried_once_with_a_fresh_session_and_its_verdict_stands(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, baseline, sessions, _ = _run_then_generalist(
        tmp_path, install, monkeypatch, capsys, "api_error_first"
    )
    assert code == 0
    assert len(sessions.generalist_reviews) == 2  # the first session, then a fresh one
    events = read_events(baseline / "events.jsonl")
    unavailable = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert [(e.cause, e.retry) for e in unavailable] == [("infrastructure", True)]
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    assert ran.result.verdict == "pass" and ran.result.rubric_kind == "generalist"
    assert ran.result.session_id != unavailable[0].session_id
    assert (baseline / "baseline.json").is_file()


def test_a_verdict_the_binary_s_cap_refused_is_not_retried(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, baseline, sessions, _ = _run_then_generalist(
        tmp_path, install, monkeypatch, capsys, "never_corrects"
    )
    assert code == 2
    assert len(sessions.generalist_reviews) == 1  # no fresh session
    events = read_events(baseline / "events.jsonl")
    unavailable = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert [(e.cause, e.retry) for e in unavailable] == [("invalid_verdict", False)]
    assert "after 5 attempts" in unavailable[0].detail
    assert not [e for e in events if isinstance(e, ReviewRan)]
    assert not (baseline / "baseline.json").exists()
