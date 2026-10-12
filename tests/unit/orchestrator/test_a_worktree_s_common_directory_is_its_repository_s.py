"""A worktree's admin directory is accepted only if it belongs to the repository it was made in.

A linked worktree's admin directory (``<common>/worktrees/<name>``) holds ``commondir``, which
names the directory whose config, hooks, refs and objects git uses for that worktree, and
``gitdir``, which names the worktree's ``.git`` file. A ``commondir`` naming any other directory
would hand the orchestrator's commit a configuration it never checked. So before any git command
runs in a worktree the harness made, ``commondir`` must resolve to the directory the admin
directory sits in, and that directory must be the common directory of the repository the caller
made the worktree in; ``gitdir`` must point back at the worktree's ``.git`` file. Anything else
refuses, and git is not run at all.

The common directory a session's protection is built from is read through the same check, from
the filesystem, never by asking git inside the repository.

Inert markers only: each decoy is an empty repository git created, with nothing configured, and
the swaps rewrite ``commondir`` and ``gitdir`` to name it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.dispatch import run_protected_roots
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import (
    common_dir,
    harness_git,
    verified_git_dir,
    verify_worktree_pointer,
)
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


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repository(path: Path) -> str:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "m1").mkdir()
    (path / "m1" / "a.txt").write_text("0\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "start")
    return _git(path, "rev-parse", "HEAD")


def _run(tmp_path: Path) -> tuple[RunGit, Path, str]:
    """A run with its integration worktree and one subtask's: the run, that worktree, start."""
    repo = tmp_path / "repo"
    start = _repository(repo)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    (worktree / "m1" / "a.txt").write_text("1\n")
    return run, worktree, start


def _admin(worktree: Path) -> Path:
    return Path((worktree / ".git").read_text().removeprefix("gitdir:").strip())


def _decoy(tmp_path: Path) -> Path:
    """An empty repository git created: the common directory a swapped ``commondir`` names."""
    decoy = tmp_path / "decoy"
    _git(tmp_path, "init", "-q", "--bare", str(decoy))
    return decoy


def _git_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every harness git command run from here on (the binary is resolved first)."""
    exe = harness_git().path
    calls: list[list[str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        if argv and argv[0] == exe:
            calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


def _swap_commondir(worktree: Path, decoy: Path) -> None:
    (_admin(worktree) / "commondir").write_text(f"{decoy}\n")


def _swap_gitdir(worktree: Path, decoy: Path) -> None:
    (_admin(worktree) / "gitdir").write_text(f"{decoy / '.git'}\n")


def _decoy_layout(worktree: Path, decoy: Path) -> None:
    """An admin directory laid out as git lays one out, but in another repository.

    It sits at ``<decoy>/worktrees/m1`` with ``commondir`` ``../..`` and a ``gitdir`` naming this
    worktree's ``.git``, so it passes every check that looks at it alone; the worktree's pointer
    names it.
    """
    admin = decoy / "worktrees" / "m1"
    admin.mkdir(parents=True)
    (admin / "HEAD").write_text((_admin(worktree) / "HEAD").read_text())
    (admin / "commondir").write_text("../..\n")
    (admin / "gitdir").write_text(f"{worktree / '.git'}\n")
    (worktree / ".git").write_text(f"gitdir: {admin}\n")


SWAPS = {
    "commondir names a decoy": (_swap_commondir, "another common git directory"),
    "gitdir names another .git": (_swap_gitdir, "disagree"),
    "an admin directory of another repository": (_decoy_layout, "another repository"),
}


def test_an_admin_directory_git_made_verifies_against_its_repository(tmp_path: Path) -> None:
    run, worktree, _ = _run(tmp_path)
    common = common_dir(run.repo)
    assert common == (run.repo / ".git").resolve()
    admin = verify_worktree_pointer(worktree, common=common)
    assert admin == _admin(worktree).resolve()
    assert verified_git_dir(worktree, linked=True, common=common) == admin
    assert len(commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)) == 40


@pytest.mark.parametrize("swap", sorted(SWAPS))
def test_a_role_worktree_s_commit_refuses_before_any_git_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    run, worktree, _ = _run(tmp_path)
    change, reason = SWAPS[swap]
    change(worktree, _decoy(tmp_path))
    before = _git(run.repo, "rev-parse", run.subtask_branch("m1"))
    calls = _git_runs(monkeypatch)
    with pytest.raises(GitError, match=reason):
        commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)
    with pytest.raises(GitError, match=reason):
        run.open_subtask("m1")  # a repair attempt's worktree is read the same way
    assert calls == []
    assert _git(run.repo, "rev-parse", run.subtask_branch("m1")) == before


@pytest.mark.parametrize("swap", sorted(SWAPS))
def test_the_merge_refuses_an_integration_worktree_of_another_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    run, worktree, start = _run(tmp_path)
    attempt = commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)
    change, reason = SWAPS[swap]
    change(run.integration, _decoy(tmp_path))
    calls = _git_runs(monkeypatch)
    with pytest.raises(GitError, match=reason):
        GitMerger(run, removal_timeout_s=60).merge("m1", 1, attempt, "merge m1")
    # The merge's checks of the branch ran, pinned to the repository; nothing ran in the worktree.
    assert not [argv for argv in calls if str(run.integration) in argv], calls
    assert _git(run.repo, "rev-parse", run.run_branch) == start


def test_a_linked_worktree_is_never_verified_without_its_repository(tmp_path: Path) -> None:
    _, worktree, _ = _run(tmp_path)
    with pytest.raises(GitError, match="none was named"):
        verified_git_dir(worktree, linked=True)


def test_a_repository_s_own_git_directory_may_not_name_a_common_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, worktree, _ = _run(tmp_path)
    attempt = commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)
    # git follows a ``commondir`` in any git directory, a main worktree's included.
    (run.repo / ".git" / "commondir").write_text(f"{_decoy(tmp_path)}\n")
    calls = _git_runs(monkeypatch)
    with pytest.raises(GitError, match="commondir"):
        verified_git_dir(run.repo, linked=False)
    with pytest.raises(GitError, match="commondir"):
        common_dir(run.repo)
    with pytest.raises(GitError, match="commondir"):
        GitMerger(run, removal_timeout_s=60).merge("m1", 1, attempt, "merge m1")
    assert calls == []


def test_the_protected_set_is_read_through_the_verification_never_from_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, _ = _run(tmp_path)
    calls = _git_runs(monkeypatch)
    reverted, _ = run_protected_roots(run)
    assert (run.repo / ".git").resolve() / "config" in reverted
    assert calls == []
    # A repository whose git directory does not verify gives no protected set at all, so the
    # session is never installed.
    (run.repo / ".git" / "commondir").write_text(f"{_decoy(tmp_path)}\n")
    with pytest.raises(GitError, match="commondir"):
        run_protected_roots(run)
    assert calls == []


def test_a_repository_that_is_a_linked_worktree_has_its_common_directory_verified(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    start = _repository(origin)
    repo = tmp_path / "repo"
    _git(origin, "worktree", "add", "-q", "-b", "target", str(repo), start)
    assert common_dir(repo) == (origin / ".git").resolve()
    (_admin(repo) / "commondir").write_text(f"{_decoy(tmp_path)}\n")
    with pytest.raises(GitError, match="another common git directory"):
        common_dir(repo)
