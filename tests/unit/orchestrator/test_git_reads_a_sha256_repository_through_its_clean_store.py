"""The clean store a content read runs against is made with the repository's object format.

A content read never runs inside the repository: it runs against a throwaway bare store that
reaches the repository's objects through alternates. A store of one hash cannot read a single
object of the other, so a store always made as SHA-1 fails closed on every read of a SHA-256
repository. These tests make a small repository of each format with one commit and read a file
back through the clean store.

The format is read from the repository's config file as data, by git run outside the repository:
asking git inside it would apply the very config the clean store exists to keep out.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import _object_format, diff_text, git

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

_EMPTY_TREE = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
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


def _one_commit_repo(root: Path, object_format: str) -> tuple[Path, str]:
    repo = root / object_format
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run", f"--object-format={object_format}")
    (repo / "m.txt").write_text("held in the commit\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    return repo, _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_a_file_is_read_back_through_the_clean_store(tmp_path: Path, object_format: str) -> None:
    repo, commit = _one_commit_repo(tmp_path, object_format)
    assert _git(repo, "rev-parse", "--show-object-format") == object_format

    content = git(repo, "cat-file", "blob", f"{commit}:m.txt", objects_only=True)
    assert content == "held in the commit\n"

    diff = diff_text(repo, _EMPTY_TREE[object_format], commit)
    assert "+held in the commit" in diff


def _inside(path: Path, repo: Path) -> bool:
    return Path(path).resolve().is_relative_to(repo.resolve())


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_the_format_is_read_without_running_git_inside_the_repository(
    tmp_path: Path, object_format: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _one_commit_repo(tmp_path, object_format)
    calls: list[tuple[list[str], Any, dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), kwargs.get("cwd"), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    assert _object_format(repo) == object_format
    assert calls, "the format was not read through git"
    for argv, cwd, env in calls:
        assert cwd is not None and not _inside(cwd, repo), f"git ran inside the repository: {cwd}"
        for flag in ("--git-dir", "-C", "--work-tree"):
            if flag in argv:
                assert not _inside(Path(argv[argv.index(flag) + 1]), repo), argv
        assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env


def test_a_linked_worktree_s_format_is_read_from_the_common_config(tmp_path: Path) -> None:
    repo, _ = _one_commit_repo(tmp_path, "sha256")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))
    assert (linked / ".git").is_file()
    assert _object_format(linked) == "sha256"


def test_an_unknown_object_format_is_refused(tmp_path: Path) -> None:
    repo, _ = _one_commit_repo(tmp_path, "sha1")
    with (repo / ".git" / "config").open("a") as handle:
        handle.write("[extensions]\n\tobjectformat = md5\n")
    with pytest.raises(GitError, match="object format"):
        _object_format(repo)
