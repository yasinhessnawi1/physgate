"""The harness reads git's own files exactly as git reads them, or refuses.

Where the harness parses a git file itself and git parses the same file another way, the
harness checks one thing while git uses another. Each case below was measured on git 2.54, and
each test carries git's own reading of the same bytes as its control:

- ``commondir`` and a ``.git`` pointer: git removes only trailing CR and LF. A blank at either
  end is part of the path to git, so ``../..`` followed by two spaces names the directory
  ``..``-and-two-spaces, which a check that trimmed it would never look at. Such a path is
  refused; CR, LF and repeated newlines are read as git reads them.
- A ``.git`` pointer must begin ``gitdir: `` with its space; without it git refuses the file.
- An admin directory's ``gitdir`` names the worktree's ``.git`` relative to the admin
  directory, not to wherever the harness happens to run.
- ``objects/info/alternates`` is not parsed by the harness at all: the clean store's own git
  follows it, so a relative entry means what git says it means.
- The object format: git honours ``extensions.objectformat`` only at format version 1, refuses
  a version-0 repository that names it, and refuses every version above 1.

Inert markers only: every decoy is an empty repository git created; nothing is configured.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import physgate.orchestrator.git as orchestrator_git
from physgate.orchestrator.dispatch import run_protected_roots
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import common_dir, git, verified_git_dir
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


def _plain(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    done = _plain(cwd, *args)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _run(tmp_path: Path) -> tuple[RunGit, Path]:
    repo = tmp_path / "repo"
    (repo / "m1").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "m1" / "a.txt").write_text("0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    return run, run.open_subtask("m1")


def _admin(worktree: Path) -> Path:
    return Path((worktree / ".git").read_text().removeprefix("gitdir: ").strip())


def _verify(run: RunGit, worktree: Path) -> Path:
    return verified_git_dir(worktree, linked=True, common=common_dir(run.repo)).common


def _git_common(admin: Path) -> str:
    """The common directory git itself takes for ``admin``, blanks kept: the control."""
    done = _plain(admin, "--git-dir", str(admin), "rev-parse", "--git-common-dir")
    assert done.returncode == 0, done.stderr
    return done.stdout.rstrip("\n")


@pytest.mark.parametrize("value", ["../..  \n", " ../..\n", "../..\t\n"])
def test_a_commondir_git_reads_with_its_blanks_is_refused(tmp_path: Path, value: str) -> None:
    run, worktree = _run(tmp_path)
    admin = _admin(worktree)
    real = _verify(run, worktree)
    # A decoy where git looks when it keeps the blanks: ``worktrees/..  `` for the first case.
    named = (admin / value.rstrip("\n")).resolve() if value.startswith("..") else None
    if named is not None:
        _git(tmp_path, "init", "-q", "--bare", str(named))
    (admin / "commondir").write_text(value)
    if named is not None:
        assert Path(_git_common(admin)).resolve() == named != real  # git reads the decoy
    with pytest.raises(GitError, match="git would read differently"):
        _verify(run, worktree)
    with pytest.raises(GitError, match="git would read differently"):
        commit_attempt(worktree, "m1", 1, "sess-1", repo=run.repo)


@pytest.mark.parametrize("value", ["../..\r\n", "../..\n\n\n", "../.."])
def test_a_commondir_git_reads_as_the_common_directory_is_accepted(
    tmp_path: Path, value: str
) -> None:
    run, worktree = _run(tmp_path)
    admin = _admin(worktree)
    (admin / "commondir").write_text(value)
    assert Path(_git_common(admin)).resolve() == (run.repo / ".git").resolve()
    assert _verify(run, worktree) == (run.repo / ".git").resolve()


#: Each pointer git refuses: its shape, what git says, and what the harness says.
POINTERS = {
    "no space after gitdir:": (
        "gitdir:{admin}\n",
        "invalid gitfile format",
        "not a gitdir pointer",
    ),
    "trailing blanks": ("gitdir: {admin}  \n", None, "git would read differently"),
    "a leading blank": ("gitdir:  {admin}\n", None, "git would read differently"),
    "a second line": ("gitdir: {admin}\nmore\n", None, "git would read differently"),
}


@pytest.mark.parametrize("case", sorted(POINTERS))
def test_a_pointer_git_would_not_read_as_written_is_refused(tmp_path: Path, case: str) -> None:
    run, worktree = _run(tmp_path)
    admin = _admin(worktree)
    shape, says, refusal = POINTERS[case]
    (worktree / ".git").write_text(shape.format(admin=admin))
    control = _plain(worktree, "rev-parse", "--git-dir")
    assert control.returncode != 0, control.stdout  # git refuses the file as written
    if says is not None:
        assert says in control.stderr
    with pytest.raises(GitError, match=refusal):
        _verify(run, worktree)


@pytest.mark.parametrize("ending", ["\r\n", "\n\n"])
def test_a_pointer_git_reads_is_accepted(tmp_path: Path, ending: str) -> None:
    run, worktree = _run(tmp_path)
    admin = _admin(worktree)
    (worktree / ".git").write_text(f"gitdir: {admin}{ending}")
    assert Path(_git(worktree, "rev-parse", "--git-dir")).resolve() == admin.resolve()
    assert _verify(run, worktree) == (run.repo / ".git").resolve()


def test_a_relative_gitdir_is_read_against_its_admin_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, worktree = _run(tmp_path)
    admin = _admin(worktree)
    relative = os.path.relpath(worktree / ".git", admin)
    (admin / "gitdir").write_text(relative + "\n")
    # Wherever the harness runs, the back-pointer names the worktree's .git.
    monkeypatch.chdir(tmp_path)
    assert _verify(run, worktree) == (run.repo / ".git").resolve()


def test_an_alternate_is_followed_by_git_never_parsed_by_the_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    (other / "o.txt").write_text("only in the alternate\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "other")
    only_there = _git(other, "rev-parse", "HEAD")
    repo = tmp_path / "work" / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    # Relative to the object directory that names it, as git reads it.
    entry = os.path.relpath(other / ".git" / "objects", repo / ".git" / "objects")
    (repo / ".git" / "objects" / "info" / "alternates").write_text(f"{entry}\n")
    # The same text read against the harness's own directory names a decoy instead.
    elsewhere = tmp_path / "work" / "repo" / ".git" / "objects" / "x" / "y"
    elsewhere.mkdir(parents=True)
    decoy = (elsewhere / entry).resolve()
    decoy.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(elsewhere)
    orchestrator_git._object_store.cache_clear()
    dirs = orchestrator_git._object_dirs(repo)
    assert dirs == (str((repo / ".git" / "objects").resolve()),)
    assert str(decoy) not in dirs
    assert git(repo, "cat-file", "-t", only_there, objects_only=True).strip() == "commit"


@pytest.mark.parametrize(
    ("version", "named", "says", "refusal"),
    [
        ("0", "sha256", "v1-only extension", "names an object format at a format version"),
        ("2", "sha256", "version", "format version is one git refuses"),
        ("2", None, "version", "format version is one git refuses"),
    ],
)
def test_an_object_format_git_would_refuse_is_refused(
    tmp_path: Path, version: str, named: str | None, says: str, refusal: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    config = str(repo / ".git" / "config")
    _git(repo, "config", "--file", config, "core.repositoryformatversion", version)
    if named is not None:
        _git(repo, "config", "--file", config, "extensions.objectformat", named)
    control = _plain(repo, "rev-parse", "--show-object-format")
    assert control.returncode != 0 and says in control.stderr, control.stderr
    with pytest.raises(GitError, match=refusal):
        orchestrator_git._object_format(repo)


@pytest.mark.parametrize(
    ("version", "named", "expected"),
    [("1", "sha256", "sha256"), ("0", "sha256", None), ("2", None, None), ("1", None, "sha1")],
)
def test_a_repository_named_by_a_relative_path_is_read_from_its_own_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    named: str | None,
    expected: str | None,
) -> None:
    """The config git is handed is the file checked here, whatever the working directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    config = str(repo / ".git" / "config")
    _git(repo, "config", "--file", config, "core.repositoryformatversion", version)
    if named is not None:
        _git(repo, "config", "--file", config, "extensions.objectformat", named)
    monkeypatch.chdir(tmp_path)
    if expected is None:
        with pytest.raises(GitError, match="format version"):
            orchestrator_git._object_format(Path("repo"))
    else:
        assert orchestrator_git._object_format(Path("repo")) == expected


def test_a_missing_config_is_an_error_never_a_key_that_is_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".git" / "config").unlink()
    with pytest.raises(GitError, match="no config file"):
        orchestrator_git._object_format(repo)


def test_a_gitdir_git_would_read_another_way_refuses_the_protected_set(tmp_path: Path) -> None:
    run, worktree = _run(tmp_path)
    # The control: the ordinary layout gives a set holding the worktree's pointer.
    reverted, _ = run_protected_roots(run)
    assert (worktree / ".git").resolve() in [Path(p).resolve() for p in reverted]
    admin = _admin(worktree)
    (admin / "gitdir").write_text(f"{worktree / '.git'}  \n")
    with pytest.raises(GitError, match="git would read differently"):
        run_protected_roots(run)
