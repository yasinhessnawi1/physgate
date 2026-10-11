"""A commit or merge runs only in a git directory the harness confirmed, never one git finds.

Checking a worktree's ``.git`` pointer file says nothing when ``.git`` is not a file. With no
``.git`` at all, git looks in the parent directories and commits into whatever repository holds
the run directory; with a directory, or a link to one, git takes that as the repository. Each
of those let a commit or a merge land in a repository the harness never chose (measured before
the fix: a role worktree's commit went into the enclosing repository, or into the decoy). Now a
worktree the harness made must hold a pointer that verifies, and the target repository either
such a pointer or a real ``.git`` directory; anything else refuses before git runs.

Inert markers only: the enclosing repository and the decoy are fresh repositories git created,
with nothing configured; the swaps remove, replace or link the ``.git`` entry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from physgate.orchestrator.apply import GitChangeChecker
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import commit_all, verified_git_dir
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
SWAPS = ("absent", "directory", "link")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repository(path: Path, file: str) -> str:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / file).write_text("0\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "start")
    return _git(path, "rev-parse", "HEAD")


def _layout(tmp_path: Path) -> tuple[Path, RunGit, str]:
    """A run whose directory sits inside another repository: (that repository, the run, start)."""
    outer = tmp_path / "outer"
    _repository(outer, "outer.txt")
    repo = tmp_path / "repo"
    start = _repository(repo, "m1.txt")
    run = RunGit(repo=repo, run_dir=outer / "run", run_id="r1")
    run.open_run_branch(start)
    return outer, run, start


def _swap(tmp_path: Path, place: Path, swap: str) -> Path:
    """Replace ``place``'s ``.git``; returns the decoy git directory git would have used."""
    decoy = tmp_path / "decoy"
    _repository(decoy, "decoy.txt")
    dot = place / ".git"
    if dot.is_dir() and not dot.is_symlink():
        shutil.rmtree(dot)
    else:
        dot.unlink()
    if swap == "directory":
        shutil.move(str(decoy / ".git"), str(dot))
        return dot
    if swap == "link":
        dot.symlink_to(decoy / ".git")
    return decoy / ".git"


def _heads(outer: Path, decoy_git: Path) -> tuple[str, str]:
    """The enclosing repository's head and the decoy's: where an unverified git would commit."""
    return _git(outer, "rev-parse", "HEAD"), _git(
        outer, "--git-dir", str(decoy_git), "rev-parse", "HEAD"
    )


@pytest.mark.parametrize("swap", SWAPS)
def test_a_role_worktree_s_commit_refuses_a_git_directory_it_cannot_verify(
    tmp_path: Path, swap: str
) -> None:
    outer, run, _ = _layout(tmp_path)
    worktree = run.open_subtask("m1")
    (worktree / "m1.txt").write_text("1\n")
    decoy_git = _swap(tmp_path, worktree, swap)
    before = _heads(outer, decoy_git)
    with pytest.raises(GitError):
        commit_attempt(worktree, "m1", 1, "sess-1")
    with pytest.raises(GitError):
        run.open_subtask("m1")  # a repair attempt's worktree is read the same way
    assert _heads(outer, decoy_git) == before


@pytest.mark.parametrize("swap", SWAPS)
def test_the_merge_refuses_an_integration_worktree_it_cannot_verify(
    tmp_path: Path, swap: str
) -> None:
    outer, run, start = _layout(tmp_path)
    worktree = run.open_subtask("m1")
    (worktree / "m1.txt").write_text("1\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1")
    decoy_git = _swap(tmp_path, run.integration, swap)
    before = _heads(outer, decoy_git)
    with pytest.raises(GitError):
        GitMerger(run, removal_timeout_s=60).merge("m1", 1, attempt, "merge m1")
    assert _heads(outer, decoy_git) == before
    assert _git(run.repo, "rev-parse", run.run_branch) == start


@pytest.mark.parametrize("swap", ["absent", "link", "empty"])
def test_the_target_repository_must_hold_a_git_directory_the_harness_can_verify(
    tmp_path: Path, swap: str
) -> None:
    outer, run, start = _layout(tmp_path)
    worktree = run.open_subtask("m1")
    (worktree / "m1.txt").write_text("1\n")
    attempt = commit_attempt(worktree, "m1", 1, "sess-1")
    real = tmp_path / "real-git"
    shutil.move(str(run.repo / ".git"), str(real))
    if swap == "link":
        (run.repo / ".git").symlink_to(real)
    elif swap == "empty":
        (run.repo / ".git").mkdir()
    graph = tmp_path / "graph"
    graph.mkdir()
    outer_head = _git(outer, "rev-parse", "HEAD")
    merger = GitMerger(run, removal_timeout_s=60)
    with pytest.raises(GitError):
        merger.merge("m1", 1, attempt, "merge m1")
    with pytest.raises(GitError):
        GitChangeChecker(run, graph, {"m1": "m1"}).check("m1", attempt, "role")
    with pytest.raises(GitError):
        merger.run_branch_moved(start, attempt)
    assert merger.remove_worktree("m1").outcome == "refused"
    assert _git(outer, "rev-parse", "HEAD") == outer_head


def test_an_ordinary_repository_s_own_git_directory_is_the_one_pinned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repository(repo, "a.txt")
    assert verified_git_dir(repo, linked=False) == (repo / ".git").resolve()
    with pytest.raises(GitError):
        verified_git_dir(repo, linked=True)  # not a worktree the harness made
    (repo / "a.txt").write_text("1\n")
    commit = commit_all(repo, "the harness commits")
    assert _git(repo, "rev-parse", "HEAD") == commit
