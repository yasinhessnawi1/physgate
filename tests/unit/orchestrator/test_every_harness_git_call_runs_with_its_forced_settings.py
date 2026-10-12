"""Every git command the harness runs carries the settings it forces, as git itself reports them.

Two of those settings have no inert marker. The file-system monitor (``core.fsmonitor``) is
either git's own background daemon or a program a repository names, so any value but ``false``
would start something. A diff's ``--no-ext-diff`` and ``--no-textconv`` change nothing while
the diff reads through the clean store, which holds no configuration and takes attributes from
the empty tree, so no external diff or textconv program can be named there. So these tests
check the settings themselves: each helper asks git, with no marker configured anywhere, for
the value it is running with (``git config --get``), and the diff's argument list is read for
its switches. The repository's attributes-file setting is checked the same way here; its
behavioural test (a CRLF file under an attributes file with ``* text``) sits with the other
attribute tests.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.inject import materialise
from physgate.orchestrator.git import diff_text, git, git_timed

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
#: Each forced setting and the value every harness git command must run with. The commit graph
#: is a cache of parents git trusts over the commits, kept in the object directory.
FORCED = {
    "core.fsmonitor": "false",
    "core.attributesFile": "/dev/null",
    "core.commitGraph": "false",
}
#: What the orchestrator's commands force besides: no automatic maintenance, which would go on
#: writing the repository's git directory after the command that started it had returned.
NO_MAINTENANCE = {"gc.auto": "0", "maintenance.auto": "false"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(root: Path) -> tuple[Path, str, str]:
    """A repository with two commits, and no setting of its own; it, the first and the second."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "m.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "m.txt").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "two")
    return repo, first, _git(repo, "rev-parse", "HEAD")


def _value_in_force(repo: Path) -> dict[str, Callable[[str, str], bool]]:
    """Per helper: whether git, run by that helper, holds ``key`` at exactly ``value``.

    ``git config --get <key> <pattern>`` exits 0 only if the value in force matches, and 1 if
    the key is set nowhere; nothing in the repository sets either key, so a match can only
    come from the helper's own ``-c``.
    """

    def exact(value: str) -> str:
        return f"^{value}$"

    return {
        "in the repository": lambda key, value: (
            git(repo, "config", "--get", key, exact(value)).strip() == value
        ),
        "pinned to a git directory": lambda key, value: (
            git(repo, "config", "--get", key, exact(value), git_dir=repo / ".git").strip() == value
        ),
        "clean store": lambda key, value: (
            git(repo, "config", "--get", key, exact(value), objects_only=True).strip() == value
        ),
        "timed": lambda key, value: (
            git_timed(repo, "config", "--get", key, exact(value), timeout=60)[0] == 0
        ),
        "materialiser": lambda key, value: (
            materialise._git(repo, "config", "--get", key, exact(value)) == value
        ),
    }


@pytest.mark.parametrize("key", sorted(FORCED))
def test_every_helper_runs_git_with_the_forced_setting_in_force(tmp_path: Path, key: str) -> None:
    repo, _, _ = _repo(tmp_path)
    # The control: the repository itself sets neither key, so plain git finds no value.
    plain = subprocess.run(
        ["git", "config", "--get", key], cwd=repo, env=_ENV, capture_output=True, check=False
    )
    assert plain.returncode == 1, plain
    # A helper whose git finds no value raises (its git exits 1) or answers false.
    for name, holds in _value_in_force(repo).items():
        assert holds(key, FORCED[key]), (name, key)


def test_the_reviewer_s_diff_turns_external_diff_and_textconv_programs_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, first, second = _repo(tmp_path)
    calls: list[list[str]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    assert "+two" in diff_text(repo, first, second)
    diffs = [argv for argv in calls if "diff" in argv and argv[-2:] == [first, second]]
    assert len(diffs) == 1, calls
    switches = diffs[0][diffs[0].index("diff") + 1 : -2]
    assert "--no-ext-diff" in switches, diffs[0]
    assert "--no-textconv" in switches, diffs[0]


@pytest.mark.parametrize("key", sorted(NO_MAINTENANCE))
def test_the_orchestrator_s_git_starts_no_maintenance_of_its_own(tmp_path: Path, key: str) -> None:
    repo, _, _ = _repo(tmp_path)
    plain = subprocess.run(
        ["git", "config", "--get", key], cwd=repo, env=_ENV, capture_output=True, check=False
    )
    assert plain.returncode == 1, plain
    for name, holds in _value_in_force(repo).items():
        if name == "materialiser":
            continue
        assert holds(key, NO_MAINTENANCE[key]), (name, key)


def test_the_materialiser_reads_no_shallow_or_graft_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _, _ = _repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    materialise._git(repo, "rev-parse", "HEAD")
    ran = [(argv, env) for argv, env in calls if argv[-2:] == ["rev-parse", "HEAD"]]
    assert len(ran) == 1, calls
    argv, env = ran[0]
    assert env.get("GIT_SHALLOW_FILE") == "", env
    assert env.get("GIT_GRAFT_FILE") == "", env
    assert "core.commitGraph=false" in argv, argv
