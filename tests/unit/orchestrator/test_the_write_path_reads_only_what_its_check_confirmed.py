"""The write path reads what its check confirmed, and never stages a repository it did not check.

Three rules, each about the moment between a check and the git command it guards:

- The verified git directory carries the common directory its check confirmed. The object
  directories and the object format are read from that value, never from ``commondir`` again,
  so a ``commondir`` rewritten after the check changes nothing the harness reads.
- ``git add --all`` opens a nested repository to stage it, and reads its config. A session's
  worktree is the session's to write, so a ``.git`` anywhere below its top level, of any kind,
  refuses the commit before anything is staged.
- A repository whose own ``.git`` is a file naming a git directory that is not a worktree's
  (``--separate-git-dir``) is refused, as before, in words that fit a repository.

Inert markers only: decoys are empty repositories git created, and a nested ``.git`` is an
empty directory, an empty file, or a repository git created with nothing configured.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import (
    _object_format,
    common_dir,
    git,
    harness_git,
    verified_git_dir,
)
from physgate.orchestrator.merge import RunGit, commit_attempt

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


def _run(tmp_path: Path) -> tuple[RunGit, Path, str]:
    repo = tmp_path / "repo"
    (repo / "m1").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "m1" / "a.txt").write_text("0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    start = _git(repo, "rev-parse", "HEAD")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(start)
    worktree = run.open_subtask("m1")
    return run, worktree, start


def _admin(worktree: Path) -> Path:
    return Path((worktree / ".git").read_text().removeprefix("gitdir:").strip())


def _decoy(tmp_path: Path) -> Path:
    decoy = tmp_path / "decoy"
    _git(tmp_path, "init", "-q", "--bare", "--object-format=sha256", str(decoy))
    return decoy


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


def test_reads_take_the_common_directory_the_check_confirmed(tmp_path: Path) -> None:
    run, worktree, start = _run(tmp_path)
    pinned = verified_git_dir(worktree, linked=True, common=common_dir(run.repo))
    assert pinned.common == (run.repo / ".git").resolve()
    # ``commondir`` rewritten after the check, to a decoy of the other object format with no
    # objects: a reader that read it again would find neither the objects nor the format.
    (_admin(worktree) / "commondir").write_text(f"{_decoy(tmp_path)}\n")
    assert _object_format(worktree, pinned) == "sha1"
    kind = git(worktree, "cat-file", "-t", start, objects_only=True, git_dir=pinned)
    assert kind.strip() == "commit"


def _nested_repository(place: Path) -> None:
    """A repository git created, its git directory then given ``place``'s spelling."""
    _git(place.parent, "init", "-q", str(place.parent))
    if place.name != ".git":
        (place.parent / ".git").rename(place.parent / "renamed")
        (place.parent / "renamed").rename(place)


NESTED: dict[str, Callable[[Path], object]] = {
    "a nested repository": _nested_repository,
    "an empty .git directory": lambda place: place.mkdir(),
    "a .git file": lambda place: place.write_text("gitdir: /nonexistent\n"),
}


def _case_insensitive(directory: Path) -> bool:
    probe = directory / "Case-Probe"
    probe.write_text("")
    try:
        return (directory / "case-probe").exists()
    finally:
        probe.unlink()


@pytest.mark.parametrize("spelling", [".git", ".GIT", ".Git"])
@pytest.mark.parametrize("kind", sorted(NESTED))
@pytest.mark.parametrize("where", ["m1/sub", "m1/deep/er"])
def test_a_worktree_holding_a_git_of_its_own_is_not_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, where: str, spelling: str
) -> None:
    """Whatever the spelling, if the volume lets git open it as ``.git``, staging is refused."""
    if spelling != ".git" and not _case_insensitive(tmp_path):
        pytest.skip("on a case-sensitive volume git does not take this spelling for .git")
    run, worktree, _ = _run(tmp_path)
    place = worktree / where / spelling
    place.parent.mkdir(parents=True)
    (place.parent / "f.txt").write_text("x\n")
    NESTED[kind](place)
    # The control: git itself takes the spelling for a .git here.
    assert os.path.lexists(place.parent / ".git")
    before = _git(run.repo, "rev-parse", run.subtask_branch("m1"))
    calls = _git_runs(monkeypatch)
    with pytest.raises(GitError, match="a git repository of its own") as raised:
        commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)
    assert Path(raised.value.context["path"]) == place.parent / ".git"
    assert not [argv for argv in calls if "add" in argv], calls
    assert _git(run.repo, "rev-parse", run.subtask_branch("m1")) == before


def test_a_worktree_without_a_nested_git_is_committed(tmp_path: Path) -> None:
    run, worktree, _ = _run(tmp_path)
    (worktree / "m1" / "sub").mkdir()
    (worktree / "m1" / "sub" / "git.txt").write_text("a file named like git, not .git\n")
    assert len(commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)) == 40


def test_a_separate_git_directory_is_refused_in_words_for_a_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "--separate-git-dir", str(tmp_path / "gd"), str(repo))
    with pytest.raises(GitError, match="the repository's .git is not a directory the harness"):
        common_dir(repo)
