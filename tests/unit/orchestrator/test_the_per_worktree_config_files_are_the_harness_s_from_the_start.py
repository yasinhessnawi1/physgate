"""The empty ``config.worktree`` files are made by the harness, before any session runs.

Claude Code's Linux sandbox makes them itself, empty, in the git directory a session must
not change, the first time a session runs in a linked worktree. Made first by the harness
when it adds a worktree, they are in every session's record from its start: the sandbox
then makes nothing, a session that changes one is still caught, and git reads none of them
while ``extensions.worktreeConfig`` is unset.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.orchestrator.dispatch import changed_since, record_roots
from physgate.orchestrator.git import WORKTREE_CONFIG, add_worktree, common_dir

_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
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


def _repo_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "m.py").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    worktree = tmp_path / "worktrees" / "s1"
    add_worktree(repo, worktree, "subtask/s1", "run")
    return repo, worktree


def test_adding_a_worktree_makes_both_files_empty(tmp_path: Path) -> None:
    repo, _ = _repo_and_worktree(tmp_path)
    common = common_dir(repo)
    for path in (common / WORKTREE_CONFIG, common / "worktrees" / "s1" / WORKTREE_CONFIG):
        assert path.is_file() and path.stat().st_size == 0, path


def test_git_reads_none_of_them_while_worktree_config_is_unset(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    listed = _git(worktree, "config", "--list", "--show-origin")
    assert WORKTREE_CONFIG not in listed
    # Not even one that holds a key: git does not read the file without the extension.
    (common_dir(repo) / "worktrees" / "s1" / WORKTREE_CONFIG).write_text(
        "[core]\n\thooksPath = /nonexistent\n"
    )
    found = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=worktree, env=_ENV, capture_output=True
    )
    assert found.returncode == 1 and found.stdout == b""
    assert _git(worktree, "status", "--porcelain") == ""


def test_a_session_that_changes_one_is_still_caught(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    common = common_dir(repo)
    config = build_config(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(worktree),
            own_branch="subtask/s1",
            store_root=None,
            state_dir=str(tmp_path / "s" / "state"),
            target_dir=str(tmp_path / "s" / "session"),
            claude_config_dir=str(tmp_path / "s" / "config"),
            user_home=str(tmp_path / "s" / "home"),
            token_ceiling=1000,
            extra_protected=(str(common),),
        ),
        current_installation(),
    )
    config_path = tmp_path / "session-config.json"
    config_path.write_text(config.model_dump_json())
    record = record_roots(config_path)
    assert changed_since(record) == []
    (common / WORKTREE_CONFIG).write_text("[core]\n\thooksPath = /nonexistent\n")
    assert str(common / WORKTREE_CONFIG) in changed_since(record)
