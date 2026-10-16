"""The packet reads an attempt's objects only through a git directory the harness's check accepts.

A worktree's ``.git`` file names its admin directory, whose ``commondir`` names the directory its
objects and config live in; the packet builds its object store and reads the object format from
there. So the packet holds the pointer to the same check as the orchestrator's writes: the admin
directory's ``gitdir`` must point back at the worktree's ``.git``, its ``commondir`` must name the
directory it sits in, and a repository's own git directory may not name a ``commondir`` at all.
Anything else is refused with the packet's own error, before any git command runs; the check
itself runs no git inside the repository.

Inert markers only: the decoy is an empty repository git created, and the swaps rewrite
``commondir`` and ``gitdir`` to name it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.git import harness_git
from physgate.reviewers.packet import PacketError, issued_spec_sha256

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
SPEC = b"the specification as issued\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _layout(tmp_path: Path) -> tuple[Path, Path, str, Path]:
    """A repository with an issued spec, a linked worktree of it, the commit, and a decoy."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "spec.md").write_bytes(SPEC)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "issued")
    commit = _git(repo, "rev-parse", "HEAD")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))
    decoy = tmp_path / "decoy"
    _git(tmp_path, "init", "-q", "--bare", str(decoy))
    return repo, linked, commit, decoy


def _admin(worktree: Path) -> Path:
    return Path((worktree / ".git").read_text().removeprefix("gitdir:").strip())


def _git_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    exe = harness_git().path
    calls: list[list[str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        if argv and argv[0] == exe:
            calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


def _commondir(repo: Path, linked: Path, decoy: Path) -> Path:
    (_admin(linked) / "commondir").write_text(f"{decoy}\n")
    return linked


def _gitdir(repo: Path, linked: Path, decoy: Path) -> Path:
    (_admin(linked) / "gitdir").write_text(f"{decoy / '.git'}\n")
    return linked


def _own_commondir(repo: Path, linked: Path, decoy: Path) -> Path:
    (repo / ".git" / "commondir").write_text(f"{decoy}\n")
    return repo


SWAPS: dict[str, tuple[Callable[[Path, Path, Path], Path], str]] = {
    "a worktree's commondir names a decoy": (_commondir, "another common git directory"),
    "a worktree's gitdir names another .git": (_gitdir, "disagree"),
    "a repository's own git directory names a commondir": (_own_commondir, "commondir"),
}


def test_the_issued_spec_is_read_through_a_worktree_git_made(tmp_path: Path) -> None:
    repo, linked, commit, _ = _layout(tmp_path)
    expected = hashlib.sha256(SPEC).hexdigest()
    assert issued_spec_sha256(repo, commit, "spec.md") == expected
    assert issued_spec_sha256(linked, commit, "spec.md") == expected


@pytest.mark.parametrize("swap", sorted(SWAPS))
def test_the_packet_refuses_before_any_git_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    repo, linked, commit, decoy = _layout(tmp_path)
    change, reason = SWAPS[swap]
    place = change(repo, linked, decoy)
    calls = _git_runs(monkeypatch)
    with pytest.raises(PacketError, match=reason):
        issued_spec_sha256(place, commit, "spec.md")
    assert calls == []
