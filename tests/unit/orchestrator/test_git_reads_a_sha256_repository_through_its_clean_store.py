"""The clean store a content read runs against is made with the repository's object format.

A content read never runs inside the repository: it runs against a throwaway bare store that
reaches the repository's objects through alternates. A store of one hash cannot read a single
object of the other, so a store always made as SHA-1 fails closed on every read of a SHA-256
repository. These tests make a small repository of each format with one commit and read a file
back through the clean store.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from physgate.orchestrator.git import diff_text, git

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
