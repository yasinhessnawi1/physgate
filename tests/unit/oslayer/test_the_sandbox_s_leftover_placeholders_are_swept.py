"""A placeholder the Linux sandbox left in a worktree is removed before anything is committed.

Only a named path is considered, reached without following a link at any step,
in a directory that is still the one recorded before the session; and only a
provable placeholder is removed: a new, empty, regular file with one link and no
write permission. Everything else at a named path is refused and recorded, and a
file a planted link points at, anywhere, survives.
"""

from __future__ import annotations

import os
from pathlib import Path

from physgate.oslayer import placeholders


def _placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    path.chmod(0o444)


def _worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    (worktree / ".claude").mkdir(parents=True)
    return worktree


def test_new_placeholders_at_named_paths_are_removed_and_named(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    _placeholder(worktree / ".mcp.json")  # there before the session: left alone
    before = placeholders.snapshot(str(worktree))
    _placeholder(worktree / ".bashrc")
    _placeholder(worktree / ".claude" / "settings.local.json")
    _placeholder(worktree / "unnamed.txt")  # not a name the sandbox holds: never considered
    swept = placeholders.sweep(str(worktree), before)
    assert swept.removed == [".bashrc", ".claude/settings.local.json"]
    assert swept.refused == []
    assert (worktree / ".mcp.json").exists() and (worktree / "unnamed.txt").exists()


def test_a_planted_link_to_a_directory_is_never_followed(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside = tmp_path / "outside"
    marker = outside / "settings.json"
    _placeholder(marker)  # shaped exactly like a placeholder, outside the worktree
    before = placeholders.snapshot(str(worktree))
    (worktree / ".claude").symlink_to(outside)  # the session plants the link
    swept = placeholders.sweep(str(worktree), before)
    assert marker.exists(), "a file outside the worktree was deleted through a link"
    assert swept.removed == []


def test_a_directory_replaced_by_a_link_after_the_snapshot_is_refused(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    outside = tmp_path / "outside"
    marker = outside / "settings.json"
    _placeholder(marker)
    before = placeholders.snapshot(str(worktree))
    (worktree / ".claude").rmdir()
    (worktree / ".claude").symlink_to(outside)
    swept = placeholders.sweep(str(worktree), before)
    assert marker.exists()
    assert swept.removed == [] and [p for p, _ in swept.refused] == [".claude"]


def test_a_link_at_a_named_path_is_refused_and_its_target_survives(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    marker = tmp_path / "outside" / "marker"
    _placeholder(marker)
    before = placeholders.snapshot(str(worktree))
    (worktree / ".bashrc").symlink_to(marker)
    os.link(marker, worktree / ".zshrc")  # a second name for the outside file
    swept = placeholders.sweep(str(worktree), before)
    assert marker.exists() and (worktree / ".bashrc").is_symlink()
    assert (worktree / ".zshrc").exists()
    assert dict(swept.refused) == {
        ".bashrc": "not a regular file",
        ".zshrc": "it has another name",
    }


def test_what_is_not_a_placeholder_is_refused_and_recorded(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    before = placeholders.snapshot(str(worktree))
    (worktree / ".profile").write_text("")  # empty but writable: the agent's own
    (worktree / "HEAD").write_text("x")
    (worktree / "HEAD").chmod(0o444)  # read-only but not empty
    (worktree / "config").mkdir()  # a directory is never removed
    swept = placeholders.sweep(str(worktree), before)
    assert swept.removed == []
    assert dict(swept.refused) == {
        ".profile": "it is writable",
        "HEAD": "not empty",
        "config": "not a regular file",
    }
    assert (worktree / ".profile").exists() and (worktree / "config").is_dir()


def test_a_session_that_left_nothing_sweeps_nothing(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    before = placeholders.snapshot(str(worktree))
    swept = placeholders.sweep(str(worktree), before)
    assert swept.removed == [] and swept.refused == []
