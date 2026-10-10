"""The packet's git reads the attempt's objects, never the repository's own configuration.

A role session owns its worktree, so it can write the repository's local configuration, its
`.gitattributes`, an `include.path`, and a committed submodule's own configuration. git honours
all of those when it runs with its working directory inside that repository. One honoured key runs
a program of the session's choosing: a submodule whose gitlink moves, diffed under
`diff.submodule=diff`, recurses into the submodule and runs its `diff` driver, and `--no-ext-diff`
and `--no-textconv` on the parent do not reach the recursion.

So the packet runs every git command against a throwaway object store that reaches the attempt's
objects but carries none of its configuration and has no submodule working trees. These tests set
the configuration that would run a program and assert nothing runs, while the diff still shows the
change. The stand-in "program" only creates a marker file, so the test can see whether it ran.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from physgate.reviewers.packet import PacketError, _diff, _git_dir, _object_dirs

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
        ["git", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _marker_program(root: Path) -> tuple[Path, Path]:
    """A program that, if git ever runs it, creates a marker file; and the marker's path."""
    marker = root / "RAN"
    program = root / "prog.sh"
    program.write_text(f'#!/bin/sh\n: > "{marker}"\nexec cat "$1" 2>/dev/null\n')
    os.chmod(program, 0o755)
    return program, marker


def _repo_with_moving_submodule(root: Path, program: Path) -> tuple[Path, str, str]:
    """A superproject that commits a submodule at two commits; the submodule runs ``program``.

    Returns the repository, the base commit and the attempt commit the review would diff.
    """
    sub = root / "sub"
    sub.mkdir()
    _git(sub, "init", "-q", "-b", "m")
    (sub / "f").write_text("one\n")
    (sub / ".gitattributes").write_text("* diff=x\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "s1")
    s1 = _git(sub, "rev-parse", "HEAD")
    (sub / "f").write_text("two\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "s2")
    s2 = _git(sub, "rev-parse", "HEAD")
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "a").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "submodule", "-q", "add", str(sub), "sub")
    _git(repo / "sub", "checkout", "-q", s1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "p-s1")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo / "sub", "checkout", "-q", s2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "p-s2")
    attempt = _git(repo, "rev-parse", "HEAD")
    # The configuration a role session writes: recurse into submodules, and in the submodule map
    # every file to a diff driver that is a program.
    _git(repo, "config", "diff.submodule", "diff")
    _git(repo / "sub", "config", "diff.x.command", f"{program} ran")
    _git(repo / "sub", "config", "diff.x.textconv", f"{program} ran")
    _git(repo / "sub", "config", "diff.external", f"{program} ran")
    return repo, base, attempt


def test_a_committed_submodule_does_not_run_the_repositorys_diff_driver(tmp_path: Path) -> None:
    program, marker = _marker_program(tmp_path)
    repo, base, attempt = _repo_with_moving_submodule(tmp_path, program)
    diff = _diff(repo, base, attempt)
    assert not marker.exists(), "the reviewer's diff ran a role-written program"
    # The change is still shown: the submodule's gitlink moved.
    assert b"sub" in diff and b"160000" in diff


def test_an_include_path_in_the_local_config_is_not_followed(tmp_path: Path) -> None:
    # include.path pulls in more configuration; here it would turn on submodule recursion.
    program, marker = _marker_program(tmp_path)
    repo, base, attempt = _repo_with_moving_submodule(tmp_path, program)
    extra = tmp_path / "extra.cfg"
    extra.write_text("[diff]\n\tsubmodule = diff\n")
    # Replace the direct key with an include, so only a followed include could re-enable recursion.
    _git(repo, "config", "--unset", "diff.submodule")
    with (_git_dir(repo) / "config").open("a") as handle:
        handle.write(f"[include]\n\tpath = {extra}\n")
    _diff(repo, base, attempt)
    assert not marker.exists(), "the reviewer's git followed an include path in the local config"


def test_the_object_store_is_not_the_repository(tmp_path: Path) -> None:
    program, _ = _marker_program(tmp_path)
    repo, _, _ = _repo_with_moving_submodule(tmp_path, program)
    dirs = _object_dirs(repo)
    assert dirs and all(Path(d).is_dir() and d.endswith("objects") for d in dirs)
    assert str((_git_dir(repo) / "objects").resolve()) in dirs


def test_a_git_worktree_s_objects_are_found_in_the_common_dir(tmp_path: Path) -> None:
    program, _ = _marker_program(tmp_path)
    repo, _, _ = _repo_with_moving_submodule(tmp_path, program)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))
    # The worktree's own .git is a file; its objects live in the repository's common dir.
    assert (linked / ".git").is_file()
    common_objects = str((_git_dir(repo) / "objects").resolve())
    assert common_objects in _object_dirs(linked)


def test_a_path_that_is_not_a_repository_is_refused(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    with pytest.raises(PacketError, match="no git directory"):
        _object_dirs(tmp_path / "plain")
