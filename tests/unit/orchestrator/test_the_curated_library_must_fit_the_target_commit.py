"""The target's commit is checked, through git, before a curated file is copied onto it.

Judged on the commit the run branch starts from, never a working tree: identical
bytes in an ordinary file pass (the copy then leaves them), anything else where a
curated file or one of its directories goes is refused, and nothing is written.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.orchestrator.decompose import _require_library_fits
from physgate.orchestrator.exceptions import DecompositionError
from physgate.orchestrator.git import commit_all, head_of, init_repo

FILE = Path("knowledge/control/standards.md")
DATA = "# Control\n\ncurated â bytes\n".encode()


def _repo_with(root: Path, write: object) -> tuple[Path, str]:
    repo = root / "target"
    repo.mkdir()
    init_repo(repo)
    (repo / "README.md").write_text("target\n")
    commit_all(repo, "initial\n")
    if callable(write):
        write(repo)
        commit_all(repo, "the target's own content\n")
    return repo, head_of(repo, "HEAD")


def test_a_target_without_the_library_passes(tmp_path: Path) -> None:
    repo, head = _repo_with(tmp_path, None)
    _require_library_fits(repo, head, {FILE: DATA})


def test_identical_bytes_pass(tmp_path: Path) -> None:
    def same(repo: Path) -> None:
        (repo / FILE).parent.mkdir(parents=True)
        (repo / FILE).write_bytes(DATA)

    repo, head = _repo_with(tmp_path, same)
    _require_library_fits(repo, head, {FILE: DATA})


def _other(repo: Path) -> None:
    (repo / FILE).parent.mkdir(parents=True)
    (repo / FILE).write_bytes(DATA + b"one more line\n")


def _link(repo: Path) -> None:
    (repo / FILE).parent.mkdir(parents=True)
    os.symlink("elsewhere.md", repo / FILE)


def _directory(repo: Path) -> None:
    (repo / FILE).mkdir(parents=True)
    (repo / FILE / "inner.md").write_text("x\n")


def _file_for_a_directory(repo: Path) -> None:
    (repo / "knowledge").mkdir()
    (repo / "knowledge" / "control").write_text("a file where a directory goes\n")


@pytest.mark.parametrize(
    "write", [_other, _link, _directory, _file_for_a_directory], ids=lambda f: f.__name__[1:]
)
def test_anything_else_is_refused(tmp_path: Path, write: object) -> None:
    repo, head = _repo_with(tmp_path, write)
    with pytest.raises(DecompositionError, match="the target"):
        _require_library_fits(repo, head, {FILE: DATA})


def test_the_working_tree_does_not_count_only_the_commit(tmp_path: Path) -> None:
    repo, head = _repo_with(tmp_path, None)
    (repo / FILE).parent.mkdir(parents=True)
    (repo / FILE).write_text("uncommitted, and not what the run branch starts from\n")
    _require_library_fits(repo, head, {FILE: DATA})
