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


def merged(run: RunGit, commit: str, records: dict[str, str] | None = None) -> str:
    text = merge_message("m1", 1, commit, "pass", "pass")
    return GitMerger(run, removal_timeout_s=60.0).merge("m1", 1, commit, text, records=records)


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


# --- the module's files as they stand at the attempt's commit --------------------------------


def module_attempt(tmp_path: Path) -> tuple[RunGit, str]:
    repo, start = _target(tmp_path, "plain")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    module = worktree / "m1"
    (module / "README.md").write_text("limits: run-1-ctl")
    (module / "é note.md").write_text("run-1-fw")
    (module / "big.md").write_text("big-id " + "x" * (1 << 20))
    (module / "latin.md").write_bytes(b"caf\xe9 run-1-latin\n")
    (module / "deep").mkdir()
    (module / "deep" / "more.md").write_text("run-1-deep\n")
    (module / "link.md").symlink_to("outside-id-target.md")
    for other in ("m1-sibling", "m10"):
        (worktree / other).mkdir()
        (worktree / other / "a.md").write_text(f"{other}-id\n")
    (worktree / "outside.md").write_text("outside-id\n")
    return run, commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)


def test_the_module_text_is_every_file_under_the_module_as_the_commit_holds_it(
    tmp_path: Path,
) -> None:
    run, commit = module_attempt(tmp_path)
    text = GitMerger(run, removal_timeout_s=60.0).module_text(commit, "m1")
    # A file with a non-ASCII name, a nested file and a file that is not UTF-8 are read.
    # The files are told apart: a file with no last newline does not run into the next.
    assert {"run-1-ctl", "run-1-fw", "run-1-deep", "run-1-latin"} <= set(text.split())
    assert "big-id" not in text
    # Another directory, a sibling that starts with the same letters and a link are not.
    for left_out in ("outside-id", "m1-sibling-id", "m10-id"):
        assert left_out not in text


def test_the_module_text_holds_what_an_earlier_merge_wrote_and_this_attempt_left_alone(
    tmp_path: Path,
) -> None:
    run, commit = module_attempt(tmp_path)
    merger = GitMerger(run, removal_timeout_s=60.0)
    merger.merge("m1", 1, commit, merge_message("m1", 1, commit, "pass", "pass"))
    worktree = run.open_subtask("m2")
    (worktree / "m2").mkdir(exist_ok=True)
    (worktree / "m2" / "README.md").write_text("another module\n")
    again = commit_attempt(worktree, "m2", 1, "sess-2", repo=run.repo)
    assert "run-1-ctl" not in merger.module_text(again, "m2")
    assert "run-1-ctl" in merger.module_text(commit, "m1")


def test_the_module_unread_names_each_file_the_text_left_out_for_its_size(tmp_path: Path) -> None:
    run, commit = module_attempt(tmp_path)
    merger = GitMerger(run, removal_timeout_s=60.0)
    # Only the file over the bound: not a link, not a sibling directory's file, not a small one.
    assert merger.module_unread(commit, "m1") == ("m1/big.md",)
    assert merger.module_unread(commit, "m10") == ()
