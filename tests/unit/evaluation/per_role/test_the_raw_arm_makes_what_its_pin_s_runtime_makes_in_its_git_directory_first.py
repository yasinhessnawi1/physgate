"""The raw arm makes what its pin's runtime makes in its git directory, before its session.

A version's runtime makes entries of its own in the git directory of the repository a
session works in. For a role session the dispatcher makes them first, per version and
platform, so they are part of the record taken before the session and never read as the
session's doing. The raw arm is a role session on the brief: its work area is a repository
of its own, and the same entries are made there, by the same function, before anything of
the session is installed. A pin whose runtime makes none gets none.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest
from task_fixtures import own_task
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import LEAKY, _script, _setup

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task
from physgate.orchestrator.dispatch import runtime_git_paths

TASK = parse_task(json.dumps(own_task()).encode())


def _entries(git_dir: Path) -> set[str]:
    return {str(p.relative_to(git_dir)) for p in git_dir.rglob("*")}


def _made_by(version: str, tmp_path: Path) -> set[str]:
    """What the dispatcher's function adds to a fresh repository's git directory."""
    fresh = tmp_path / f"fresh-{version}"
    fresh.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True, capture_output=True)
    before = _entries(fresh / ".git")
    runtime_git_paths(fresh / ".git", version)
    return _entries(fresh / ".git") - before


def _run(tmp_path: Path, version: str, install: Path | None = None) -> Path:
    setup = _setup(tmp_path, _script(tmp_path / "claude", LEAKY))
    setup = dataclasses.replace(setup, claude_version=version)
    if install is not None:
        setup = dataclasses.replace(setup, install_bin=install)
    work = tmp_path / "work"
    raw.run_raw(TASK, setup, work, cap=10**9)
    return work / "worktree" / ".git"


def test_the_new_pin_s_entries_are_in_the_raw_arm_s_git_directory(tmp_path: Path) -> None:
    expected = _made_by("2.1.322", tmp_path)
    assert {"remotes", "objects/info/commit-graphs"} <= expected
    git_dir = _run(tmp_path, "2.1.322")
    assert expected <= _entries(git_dir)
    for name in sorted(expected):
        made, held = git_dir / name, tmp_path / "fresh-2.1.322" / ".git" / name
        assert made.is_dir() == held.is_dir()
        assert (made.stat().st_mode & 0o777) == (held.stat().st_mode & 0o777), name


def test_a_pin_whose_runtime_makes_nothing_there_gets_nothing(tmp_path: Path) -> None:
    assert _made_by("2.1.301", tmp_path) == set()
    git_dir = _run(tmp_path, "2.1.301")
    assert not (git_dir / "remotes").exists()
    assert not (git_dir / "objects" / "info" / "commit-graphs").exists()


def test_they_are_made_before_anything_of_the_session_is_installed(tmp_path: Path) -> None:
    # The installer stand-in looks for the entry when it runs: the record a real installer
    # takes of the session's start has to hold it already.
    seen = tmp_path / "seen-at-install"
    settings = tmp_path / "settings.json"
    hooks = {"hooks": {"SessionEnd": [{"hooks": [{"command": "true", "timeout": 5}]}]}}
    settings.write_text(json.dumps(hooks))
    out = {"settings": str(settings), "config": "c", "spawn_args": [], "spawn_env": {}}
    there = tmp_path / "work" / "worktree" / ".git" / "remotes"
    install = _script(
        tmp_path / "install-looking",
        f"test -d '{there}' && touch '{seen}'\necho '{json.dumps(out)}'\n",
    )
    _run(tmp_path, "2.1.322", install)
    assert seen.exists(), "the entries were not there when the session was installed"


def test_the_raw_arm_makes_them_with_the_dispatcher_s_own_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, str, str]] = []

    def spy(git_dir: Path, claude_version: str, platform: str = sys.platform) -> None:
        calls.append((git_dir, claude_version, platform))

    monkeypatch.setattr(raw, "runtime_git_paths", spy)
    git_dir = _run(tmp_path, "2.1.322")
    assert [(g.resolve(), v, p) for g, v, p in calls] == [
        (git_dir.resolve(), "2.1.322", sys.platform)
    ]
