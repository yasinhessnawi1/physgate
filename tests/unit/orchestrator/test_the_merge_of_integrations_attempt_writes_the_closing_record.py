"""The merge writes the closing record into the merge commit, and nothing else beside it.

The record is the harness's, built from the run's log: the merge's tree holds it whatever the
attempt wrote, and the attempt's own tree is left as it was. Only the record's one path is
written; a merge with none writes none.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_every_merge_path_git_call_is_pinned_or_in_the_store import _git, _target

from physgate.orchestrator.carried import CLOSING_RECORD_PATH
from physgate.orchestrator.exceptions import MergeRefusedError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt, merge_message

RECORD = '{\n  "decisions": []\n}\n'


def attempt(tmp_path: Path) -> tuple[RunGit, str]:
    repo, start = _target(tmp_path, "plain")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    (worktree / "m1" / "README.md").write_text("limits\n")
    return run, commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)


def merged(run: RunGit, commit: str, **kw: dict[str, str]) -> str:
    text = merge_message("m1", 1, commit, "pass", "pass")
    return GitMerger(run, removal_timeout_s=60.0).merge("m1", 1, commit, text, **kw)


def test_the_merge_commit_holds_the_record_and_the_attempt_does_not(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path)
    merge = merged(run, commit, records={CLOSING_RECORD_PATH: RECORD})
    held = _git(run.repo, "ls-tree", "--name-only", merge, "--", CLOSING_RECORD_PATH)
    assert held == CLOSING_RECORD_PATH
    assert _git(run.repo, "show", f"{merge}:{CLOSING_RECORD_PATH}") + "\n" == RECORD
    assert _git(run.repo, "show", f"{merge}:m1/README.md") == "limits"
    assert _git(run.repo, "log", "-1", "--format=%P", merge).split()[1] == commit
    assert _git(run.repo, "ls-tree", "--name-only", commit, "--", CLOSING_RECORD_PATH) == ""
    assert _git(run.integration, "status", "--porcelain") == ""


def test_a_merge_with_no_record_writes_none(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path)
    merge = merged(run, commit)
    assert _git(run.repo, "ls-tree", "--name-only", merge, "--", CLOSING_RECORD_PATH) == ""


def test_a_merge_writes_the_one_path_and_no_other(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path)
    before = head_of(run.repo, run.run_branch)
    with pytest.raises(MergeRefusedError):
        merged(run, commit, records={"m1/other.json": RECORD})
    assert head_of(run.repo, run.run_branch) == before


def test_a_merge_already_made_is_returned_not_made_twice(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path)
    first = merged(run, commit, records={CLOSING_RECORD_PATH: RECORD})
    assert merged(run, commit, records={CLOSING_RECORD_PATH: RECORD}) == first
