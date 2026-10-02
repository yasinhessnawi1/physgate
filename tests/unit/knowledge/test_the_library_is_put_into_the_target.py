"""``knowledge.library``: exactly the planned roles' curated files, byte for byte, or a refusal.

The orchestrator copies these into the target's run branch at decomposition, so a
role session reads the real curated content in its own worktree. Every refusal
here is one the reading hook would otherwise only meet at a session's start, or
never: content that is missing, empty, or already in the target with other bytes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.knowledge import loader
from physgate.knowledge.library import LibraryError, put_into, read_library
from physgate.orchestrator.run_config import harness_root


def _library(root: Path, roles: tuple[str, ...] = ("control", "firmware")) -> Path:
    for relative in sorted({p for role in roles for p in loader.always_loaded(role)}):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"# {relative}\n\nbytes \xe2 that must survive\n".encode())
    (root / "knowledge" / "staging").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "staging" / "candidate.md").write_text("never copied\n")
    (root / "knowledge" / "electrical").mkdir(parents=True, exist_ok=True)
    (root / "knowledge" / "electrical" / "bounds.toml").write_text("never copied\n")
    return root


def test_it_reads_exactly_the_always_loaded_set_of_the_planned_roles(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib")
    contents = read_library(library, ["firmware", "control", "control"])
    expected = {p for role in ("control", "firmware") for p in loader.always_loaded(role)}
    assert set(contents) == expected
    assert len(contents) == 5  # cross's standards once, and each role's own pair
    for relative, data in contents.items():
        assert data == (library / relative).read_bytes()


def test_no_library_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LibraryError, match="no source checkout"):
        read_library(None, ["control"])


@pytest.mark.parametrize("damage", ["missing", "empty", "whitespace", "link", "directory"])
def test_a_role_whose_curated_file_is_unusable_is_refused(tmp_path: Path, damage: str) -> None:
    library = _library(tmp_path / "lib")
    target = library / "knowledge" / "control" / "skill.md"
    target.unlink()
    if damage == "empty":
        target.write_bytes(b"")
    elif damage == "whitespace":
        target.write_text("  \n\t\n")
    elif damage == "link":
        os.symlink(library / "knowledge" / "control" / "standards.md", target)
    elif damage == "directory":
        target.mkdir()
    with pytest.raises(LibraryError) as refused:
        read_library(library, ["control"])
    assert refused.value.context == {"role": "control", "path": "knowledge/control/skill.md"}


def test_it_writes_the_bytes_exactly_and_nothing_else(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    contents = read_library(library, ["control", "firmware"])
    assert put_into(worktree, contents) == tuple(sorted(contents))
    for relative, data in contents.items():
        assert (worktree / relative).read_bytes() == data
    written = sorted(p.relative_to(worktree) for p in worktree.rglob("*") if p.is_file())
    assert written == sorted(contents)


def test_a_file_already_there_with_the_same_bytes_is_left_alone(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib")
    worktree = tmp_path / "worktree"
    contents = read_library(library, ["control"])
    put_into(worktree, contents)
    one = worktree / "knowledge" / "control" / "standards.md"
    before = one.stat().st_mtime_ns, one.stat().st_ino
    put_into(worktree, contents)
    assert (one.stat().st_mtime_ns, one.stat().st_ino) == before


@pytest.mark.parametrize("conflict", ["other-bytes", "link", "directory", "file-for-a-directory"])
def test_a_conflict_in_the_target_is_refused_and_nothing_is_written(
    tmp_path: Path, conflict: str
) -> None:
    library = _library(tmp_path / "lib")
    worktree = tmp_path / "worktree"
    contents = read_library(library, ["control", "firmware"])
    if conflict == "file-for-a-directory":
        (worktree / "knowledge").mkdir(parents=True)
        (worktree / "knowledge" / "firmware").write_text("a file where a directory goes\n")
    else:
        spot = worktree / "knowledge" / "firmware" / "standards.md"
        spot.parent.mkdir(parents=True)
        if conflict == "other-bytes":
            spot.write_text("the target's own standards\n")
        elif conflict == "link":
            os.symlink(library / "knowledge" / "firmware" / "standards.md", spot)
        else:
            spot.mkdir()
    before = sorted(str(p) for p in worktree.rglob("*"))
    with pytest.raises(LibraryError, match="the target"):
        put_into(worktree, contents)
    assert sorted(str(p) for p in worktree.rglob("*")) == before


def test_a_link_on_the_way_to_the_library_is_refused(tmp_path: Path) -> None:
    library = _library(tmp_path / "lib")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, worktree / "knowledge")
    with pytest.raises(LibraryError, match="other than a directory"):
        put_into(worktree, read_library(library, ["control"]))
    assert list(elsewhere.iterdir()) == []


def test_the_real_library_serves_the_two_curated_roles_and_refuses_one_without_content() -> None:
    real = harness_root()
    assert real is not None
    contents = read_library(real, ["control", "firmware"])
    for relative, data in contents.items():
        assert data == (real / relative).read_bytes()
        assert len(data) > 1000, relative  # curated, not a fixture
    with pytest.raises(LibraryError, match="no curated file"):
        read_library(real, ["mechanical"])
