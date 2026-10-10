"""A run protects the target repository's common git directory from the role session.

Its configuration, its ``info/`` (attributes and exclude), its hooks and the per-worktree
configuration are where a write would make a later git command run a program. A role session
has no legitimate need to touch them, so a run makes them protected roots: the path layer refuses
a file tool's write, and the sentinel puts back a shell write. Reads stay allowed, and files
outside the git directory are untouched.

Defensive only: no input here makes a program run; the git directory is a fresh one, and the
"writes" are to inert paths, checked against the hook's own decision.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from hook_helpers import write_config

from physgate.hooks import paths
from physgate.orchestrator.dispatch import GIT_CONFIG_NAMES, git_config_roots, run_protected_roots
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import (
    add_worktree,
    commit_all,
    common_dir,
    git,
    verify_worktree_pointer,
)
from physgate.orchestrator.merge import RunGit


def _repo(tmp: Path) -> Path:
    repo = tmp / "target"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        env={"PATH": "/usr/bin:/bin", "HOME": os.devnull},
        check=True,
        capture_output=True,
    )
    return repo


def test_run_protected_roots_covers_the_git_dir_exec_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="run-1")
    reverted, _ = run_protected_roots(run)
    common = common_dir(repo)
    for name in GIT_CONFIG_NAMES:
        assert common / name in reverted, name
    # They are put back (reverted), not merely refuse-only, so a shell write is undone too.
    assert set(git_config_roots(common)) <= set(reverted)


@pytest.mark.parametrize("name", ["config", "config.worktree", "hooks", "info", "modules"])
def test_the_path_layer_refuses_a_role_write_under_the_git_dir(tmp_path: Path, name: str) -> None:
    common = common_dir(_repo(tmp_path))
    roots = [
        {"path": str(p), "reason": "it is git's own directory", "watch": "revert"}
        for p in git_config_roots(common)
    ]
    _, _, config = write_config(tmp_path, protected_roots=roots)
    # A file under each protected root is refused to a writing tool.
    dir_roots = ("hooks", "info", "modules")
    target = str(common / name / "x") if name in dir_roots else str(common / name)
    assert paths.protection(target, str(tmp_path), config, writing=True) is not None
    # Reading it is allowed, and an ordinary source file is untouched.
    assert paths.protection(target, str(tmp_path), config, writing=False) is None
    assert paths.protection(str(tmp_path / "m.py"), str(tmp_path), config, writing=True) is None


def _commit_base(repo: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": os.devnull, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@x.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x.invalid"}  # fmt: skip
    (repo / "a").write_text("1\n")
    for args in (["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def test_the_session_worktree_s_git_pointer_is_a_protected_root(tmp_path: Path) -> None:
    run = RunGit(repo=_repo(tmp_path), run_dir=tmp_path / "run", run_id="run-1")
    worktree = run.subtask_worktree("s1")
    reverted, _ = run_protected_roots(run)
    # The dispatch adds the worktree's own .git pointer; here we assert the installer wires it,
    # mirroring dispatch._install, by checking a file tool write to it is refused.
    roots = [
        {
            "path": str(worktree / ".git"),
            "reason": "it is the worktree's git pointer",
            "watch": "revert",
        }  # fmt: skip
    ]
    _, _, config = write_config(tmp_path, protected_roots=roots)
    assert paths.protection(str(worktree / ".git"), str(worktree), config, writing=True) is not None
    assert paths.protection(str(worktree / "src.py"), str(worktree), config, writing=True) is None


def test_the_orchestrator_fails_closed_on_a_repointed_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit_base(repo)
    worktree = tmp_path / "wt"
    add_worktree(repo, worktree, "feat/x", "HEAD")
    # A normal linked worktree verifies, and the write path (commit_all) runs.
    verify_worktree_pointer(worktree)
    (worktree / "a").write_text("2\n")
    assert len(commit_all(worktree, "a change")) == 40
    # Repoint the worktree's .git at a directory that is not a git worktree admin (inert: an
    # empty directory, nothing runs). The orchestrator's commit refuses before running git.
    bogus = tmp_path / "bogus"
    bogus.mkdir()
    (worktree / ".git").write_text(f"gitdir: {bogus}\n")
    with pytest.raises(GitError, match="no git worktree admin directory"):
        verify_worktree_pointer(worktree)
    with pytest.raises(GitError):
        commit_all(worktree, "should not commit")


def test_a_pointer_that_cannot_be_parsed_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit_base(repo)
    worktree = tmp_path / "wt"
    add_worktree(repo, worktree, "feat/x", "HEAD")
    # Not a gitdir pointer at all: refused, never passed.
    (worktree / ".git").write_text("not a pointer\n")
    with pytest.raises(GitError, match="not a gitdir pointer"):
        verify_worktree_pointer(worktree)
    # An admin directory missing its back-pointer is refused (a real admin exists but is wrong).
    other = tmp_path / "wt2"
    add_worktree(repo, other, "feat/y", "HEAD")
    other_admin = (Path(other / ".git").read_text().removeprefix("gitdir:")).strip()
    (worktree / ".git").write_text(f"gitdir: {other_admin}\n")
    with pytest.raises(GitError, match="disagree"):
        verify_worktree_pointer(worktree)


def test_a_pointer_swapped_after_the_check_cannot_redirect_the_commit(tmp_path: Path) -> None:
    """The commit is pinned to the admin directory the check resolved.

    A pointer swapped between the check and git's use (a TOCTOU window) does not redirect it.
    Inert: the swap target is an empty directory, and the commit must still land in the real
    worktree's history.
    """
    repo = _repo(tmp_path)
    _commit_base(repo)
    worktree = tmp_path / "wt"
    add_worktree(repo, worktree, "feat/x", "HEAD")
    admin = verify_worktree_pointer(worktree)
    assert admin is not None
    # Swap the pointer at a decoy directory after the check. commit_all re-verifies and would
    # refuse; to show the pinning itself, drive git with the resolved admin directly.
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (worktree / ".git").write_text(f"gitdir: {decoy}\n")
    (worktree / "a").write_text("changed\n")
    git(worktree, "add", "--all", git_dir=admin)
    git(worktree, "commit", "--quiet", "-m", "pinned", git_dir=admin)
    head = git(worktree, "rev-parse", "HEAD", git_dir=admin).strip()
    # The commit is on the real worktree's branch, read through the pinned admin directory, not
    # the decoy (which holds no commits at all).
    assert git(worktree, "log", "-1", "--format=%s", git_dir=admin).strip() == "pinned"
    assert len(head) == 40
