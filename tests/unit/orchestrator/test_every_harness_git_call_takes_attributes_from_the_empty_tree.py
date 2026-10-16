"""Every git command the harness runs executes its one git and takes attributes from the empty tree.

A ``.gitattributes`` a role commits would otherwise choose how the harness diffs, merges and
adds. Each helper passes ``--attr-source`` and ``GIT_ATTR_SOURCE`` naming git's empty tree: for
a read through the clean store, the empty tree of the store's object format; for a command
inside a repository, the SHA-1 one (a SHA-256 repository fails closed there). And each runs the
binary ``harness_git`` resolved, by its absolute path, never ``git`` looked up on PATH.

The behavioural test uses one inert attribute, ``* text``, whose only effect is the line endings
``git add`` stores. Without the attribute source, ``git add`` stores a CRLF file with LF endings;
under it, the harness stages the file byte for byte.
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
from physgate.orchestrator.git import (
    EMPTY_TREES,
    commit_all,
    git,
    git_timed,
    harness_git,
    verified_git_dir,
)

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
CRLF = b"one\r\ntwo\r\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(root: Path, object_format: str = "sha1") -> tuple[Path, str]:
    """A repository with one commit, of ``object_format``; the repository and the commit."""
    repo = root / f"repo-{object_format}"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run", f"--object-format={object_format}")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    return repo, _git(repo, "rev-parse", "HEAD")


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], dict[str, str]]]:
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def recording_run(argv: list[str], **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    return calls


@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
def test_every_helper_runs_the_resolved_git_with_the_empty_tree_as_attribute_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, object_format: str
) -> None:
    sha1_repo, sha1_commit = _repo(tmp_path)
    (tmp_path / "store-read").mkdir()
    repo, commit = _repo(tmp_path / "store-read", object_format)
    exe = harness_git().path
    calls = _recording(monkeypatch)
    # The clean store is cached per process; start afresh so its creation is recorded too.
    orchestrator_git._object_store.cache_clear()
    own = EMPTY_TREES[object_format]
    sha1 = EMPTY_TREES["sha1"]
    # Each helper, and the attribute source every git call it makes must carry.
    helpers: dict[str, tuple[Callable[[], object], list[str]]] = {
        "in the repository": (lambda: git(sha1_repo, "rev-parse", "HEAD"), [sha1]),
        "pinned to a git directory": (
            lambda: git(
                sha1_repo, "rev-parse", "HEAD", git_dir=verified_git_dir(sha1_repo, linked=False)
            ),
            [sha1],
        ),
        # The format version and the format are read outside any repository; the store and the
        # read use the format's own tree.
        "clean store": (
            lambda: git(repo, "cat-file", "-t", commit, objects_only=True),
            [sha1, sha1, own, own],
        ),
        "timed": (lambda: git_timed(sha1_repo, "rev-parse", "HEAD", timeout=60), [sha1]),
        "materialiser": (lambda: materialise._git(sha1_repo, "rev-parse", sha1_commit), [sha1]),
    }
    for name, (call, trees) in helpers.items():
        before = len(calls)
        call()
        made = calls[before:]
        assert [argv[0] for argv, _ in made] == [exe] * len(trees), (name, made)
        for (argv, env), tree in zip(made, trees, strict=True):
            assert f"--attr-source={tree}" in argv, (name, argv)
            assert argv.index(f"--attr-source={tree}") < argv.index("-c"), (name, argv)
            assert env.get("GIT_ATTR_SOURCE") == tree, (name, argv)


def test_no_helper_looks_git_up_on_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit = _repo(tmp_path)
    calls = _recording(monkeypatch)
    orchestrator_git._object_store.cache_clear()
    # PATH holds no git at all: every helper still runs, because none looks git up there.
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert git(repo, "rev-parse", "HEAD").strip() == commit
    assert git(repo, "cat-file", "-t", commit, objects_only=True).strip() == "commit"
    assert git_timed(repo, "rev-parse", "HEAD", timeout=60)[0] == 0
    assert materialise._git(repo, "rev-parse", "HEAD") == commit
    assert calls and all(Path(argv[0]).is_absolute() for argv, _ in calls)


def _crlf_under_a_committed_text_attribute(root: Path) -> Path:
    """A repository whose committed ``.gitattributes`` says ``* text``, and an unadded CRLF file."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "run")
    (root / ".gitattributes").write_text("* text\n")
    _git(root, "add", ".gitattributes")
    _git(root, "commit", "-q", "-m", "attributes")
    (root / "f.txt").write_bytes(CRLF)
    return root


def _staged(repo: Path, rev: str) -> bytes:
    return subprocess.run(
        [harness_git().path, "cat-file", "blob", f"{rev}:f.txt"],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        check=True,
    ).stdout


def test_the_committed_attribute_is_live_without_the_attribute_source(tmp_path: Path) -> None:
    # The control: the same git, with no attribute source, applies ``* text`` and stores LF.
    repo = _crlf_under_a_committed_text_attribute(tmp_path / "plain")
    subprocess.run(
        [harness_git().path, "add", "f.txt"], cwd=repo, env=_ENV, capture_output=True, check=True
    )
    assert _staged(repo, "") == b"one\ntwo\n"


def test_the_harness_s_add_stages_a_crlf_file_byte_for_byte_under_the_attribute_source(
    tmp_path: Path,
) -> None:
    repo = _crlf_under_a_committed_text_attribute(tmp_path / "harness")
    commit_all(repo, "the harness commits")
    assert _staged(repo, "HEAD") == CRLF


def test_the_materialiser_s_add_stages_a_crlf_file_byte_for_byte(tmp_path: Path) -> None:
    repo = _crlf_under_a_committed_text_attribute(tmp_path / "instrument")
    materialise._commit(repo, "the instrument commits")
    assert _staged(repo, "HEAD") == CRLF


# ── an attributes file the repository's own config names ──────────────────────────────────
# The attribute source replaces only the in-tree ``.gitattributes``; git still reads the file
# ``core.attributesFile`` names. A repository's local config can name one, so every command
# also sets that key to ``/dev/null``. The marker is the same inert ``* text``.


def _crlf_under_a_configured_attributes_file(root: Path) -> Path:
    """A repository whose local config names an attributes file saying ``* text``; a CRLF file."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "run")
    _git(root, "commit", "-q", "--allow-empty", "-m", "start")
    attributes = root.parent / f"{root.name}.attributes"
    attributes.write_text("* text\n")
    _git(root, "config", "core.attributesFile", str(attributes))
    (root / "f.txt").write_bytes(CRLF)
    return root


def test_the_configured_attributes_file_is_live_without_the_harness_s_setting(
    tmp_path: Path,
) -> None:
    # The control: the same git, under the attribute source alone, applies the file's ``* text``.
    repo = _crlf_under_a_configured_attributes_file(tmp_path / "plain")
    subprocess.run(
        [harness_git().path, f"--attr-source={EMPTY_TREES['sha1']}", "add", "f.txt"],
        cwd=repo,
        env=_ENV,
        capture_output=True,
        check=True,
    )
    assert _staged(repo, "") == b"one\ntwo\n"


def test_the_harness_s_add_ignores_an_attributes_file_the_repository_names(
    tmp_path: Path,
) -> None:
    repo = _crlf_under_a_configured_attributes_file(tmp_path / "harness")
    commit_all(repo, "the harness commits")
    assert _staged(repo, "HEAD") == CRLF


def test_the_materialiser_s_add_ignores_an_attributes_file_the_repository_names(
    tmp_path: Path,
) -> None:
    repo = _crlf_under_a_configured_attributes_file(tmp_path / "instrument")
    materialise._commit(repo, "the instrument commits")
    assert _staged(repo, "HEAD") == CRLF
