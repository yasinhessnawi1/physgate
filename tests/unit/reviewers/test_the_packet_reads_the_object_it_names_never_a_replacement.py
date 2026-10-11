"""The review packet's git reads return the exact object a commit names, never a replacement.

git's replace mechanism (``refs/replace/*``) makes git silently show one object in place of
another, and a role can write refs in the repository it works in. The packet reads through a
clean object store that holds no refs of its own, and runs git with replace objects off as well.
These tests replace a committed file's blob with one that says "replacement" and assert the
packet's diff, export and specification digest still read "original", and that every git call
the packet makes carries the switch.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.reviewers import packet
from physgate.reviewers.packet import _diff, _export, issued_spec_sha256

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


def _replaced_repo(root: Path) -> tuple[Path, str]:
    """A repository whose one file's blob is replaced; the repository and its commit."""
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
    assert _git(repo, "cat-file", "blob", blob) == "replacement"
    return repo, commit


def test_the_packet_s_reads_return_the_named_blob(tmp_path: Path) -> None:
    repo, commit = _replaced_repo(tmp_path)
    diff = _diff(repo, _EMPTY_TREE, commit).decode()
    assert "+original" in diff
    assert "replacement" not in diff
    _export(repo, commit, tmp_path / "export")
    assert (tmp_path / "export" / "f.txt").read_text() == "original\n"
    assert issued_spec_sha256(repo, commit, "f.txt") == hashlib.sha256(b"original\n").hexdigest()


def test_every_packet_git_call_runs_with_replace_objects_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit = _replaced_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    # The store is cached per process; start afresh so its creation is recorded too.
    packet._object_store.cache_clear()
    _diff(repo, _EMPTY_TREE, commit)

    git_calls = [(argv, env) for argv, env in calls if argv and argv[0] == "git"]
    assert any("init" in argv for argv, _ in git_calls), "the store's creation was not recorded"
    assert any("config" in argv for argv, _ in git_calls), "the format read was not recorded"
    assert any("diff" in argv for argv, _ in git_calls), "the diff was not recorded"
    for argv, env in git_calls:
        assert env.get("GIT_NO_REPLACE_OBJECTS") == "1", argv
