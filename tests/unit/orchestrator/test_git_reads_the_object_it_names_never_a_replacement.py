"""Every git command the harness runs reads and writes the exact object it names.

git's replace mechanism (``refs/replace/*``) makes git silently show one object in place of
another. A role can write refs in a repository it works in, so a replace ref would let a read,
a diff or a merge act on an object other than the one the harness named. The harness turns
replace objects off on every git call it makes, through the environment each git helper builds.

These tests make a repository with one commit holding a file that says "original", add a replace
ref pointing that file's blob at one that says "replacement", check plain git now shows the
replacement, and assert the harness's reads still return "original". Reads that run against the
clean object store would not see the replace ref in any case (the store reaches the repository's
objects through alternates and holds no refs of its own); the reads that run inside the
repository are the ones the environment protects. A last test records every git call each helper
makes and checks its environment carries the switch.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.inject import materialise
from physgate.orchestrator import git as orchestrator_git
from physgate.orchestrator.git import diff_text, git, git_timed, harness_git

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
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _git(cwd: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _replaced_repo(root: Path) -> tuple[Path, str, str]:
    """A repository whose one file's blob is replaced; the repository, commit and blob."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "f.txt").write_text("original\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    commit = _git(repo, "rev-parse", "HEAD")
    blob = _git(repo, "rev-parse", f"{commit}:f.txt")
    other = _git(repo, "hash-object", "-w", "--stdin", stdin="replacement\n")
    _git(repo, "replace", blob, other)
    # The replace ref is live: git without the switch shows the substitute.
    assert _git(repo, "cat-file", "blob", blob) == "replacement"
    return repo, commit, blob


def test_an_in_repository_read_returns_the_named_blob(tmp_path: Path) -> None:
    repo, commit, blob = _replaced_repo(tmp_path)
    assert git(repo, "cat-file", "blob", blob) == "original\n"
    assert git(repo, "show", f"{commit}:f.txt") == "original\n"
    diff = git(repo, "diff", "--no-color", _EMPTY_TREE, commit)
    assert "+original" in diff
    assert "replacement" not in diff


def test_a_read_pinned_to_the_git_directory_returns_the_named_blob(tmp_path: Path) -> None:
    repo, _, blob = _replaced_repo(tmp_path)
    assert git(repo, "cat-file", "blob", blob, git_dir=repo / ".git") == "original\n"


def test_a_clean_store_read_returns_the_named_blob(tmp_path: Path) -> None:
    repo, commit, blob = _replaced_repo(tmp_path)
    assert git(repo, "cat-file", "blob", blob, objects_only=True) == "original\n"
    diff = diff_text(repo, _EMPTY_TREE, commit)
    assert "+original" in diff
    assert "replacement" not in diff


def test_the_materialiser_s_read_returns_the_named_blob(tmp_path: Path) -> None:
    repo, _, blob = _replaced_repo(tmp_path)
    assert materialise._git(repo, "cat-file", "blob", blob) == "original"


def test_every_git_helper_runs_git_with_replace_objects_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, blob = _replaced_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    # The clean store is cached per process; start afresh so its creation is recorded too.
    orchestrator_git._object_store.cache_clear()
    helpers: dict[str, Callable[[], object]] = {
        "in the repository": lambda: git(repo, "rev-parse", "HEAD"),
        "pinned to a git directory": lambda: git(repo, "rev-parse", "HEAD", git_dir=repo / ".git"),
        "clean store (format read, store made, read)": lambda: git(
            repo, "cat-file", "blob", blob, objects_only=True
        ),
        "timed": lambda: git_timed(repo, "rev-parse", "HEAD", timeout=60),
        "materialiser": lambda: materialise._git(repo, "rev-parse", commit),
    }
    for name, call in helpers.items():
        before = len(calls)
        call()
        made = [argv for argv, _ in calls[before:] if argv and argv[0] == harness_git().path]
        assert made, f"the {name} helper ran no git call that was recorded"
        if name.startswith("clean store"):
            assert len(made) == 3, made

    git_calls = [(argv, env) for argv, env in calls if argv and argv[0] == harness_git().path]
    for argv, env in git_calls:
        assert env.get("GIT_NO_REPLACE_OBJECTS") == "1", argv
