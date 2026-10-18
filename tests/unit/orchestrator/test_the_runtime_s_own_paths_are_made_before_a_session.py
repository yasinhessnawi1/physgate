"""What Claude Code makes on its own in a role session is made first, with its own bytes.

Inside the OS layer on macOS, 2.1.301 makes ``.claude/.cc-writes/`` in the worktree and
``.config/git/ignore`` in the session's home, both under roots the sentinel puts back.
The dispatcher makes them before the session's record is taken (M-100's measurement:
the modes and the 23 bytes below), leaves a present path as it is, and writes nothing
through a link.
"""

from __future__ import annotations

from pathlib import Path

from physgate.orchestrator.dispatch import runtime_paths

IGNORE = b"**/.claude/.cc-writes/\n"


def _mode(path: Path) -> int:
    return path.lstat().st_mode & 0o777


def test_both_paths_are_made_with_the_runtime_s_bytes_and_modes(tmp_path: Path) -> None:
    worktree, home = tmp_path / "worktree", tmp_path / "home"
    worktree.mkdir()
    home.mkdir()
    runtime_paths(worktree, home)
    modes = {
        worktree / ".claude": 0o755,
        worktree / ".claude" / ".cc-writes": 0o700,
        home / ".config": 0o700,
        home / ".config" / "git": 0o755,
        home / ".config" / "git" / "ignore": 0o644,
    }
    assert {p: _mode(p) for p in modes} == modes
    assert list((worktree / ".claude" / ".cc-writes").iterdir()) == []
    assert (home / ".config" / "git" / "ignore").read_bytes() == IGNORE
    assert len(IGNORE) == 23
    assert sorted(p.name for p in home.rglob("*")) == [".config", "git", "ignore"]


def test_a_present_path_is_left_as_it_is(tmp_path: Path) -> None:
    worktree, home = tmp_path / "worktree", tmp_path / "home"
    (worktree / ".claude").mkdir(parents=True, mode=0o750)
    (worktree / ".claude").chmod(0o750)
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_bytes(b"*.o\n")
    runtime_paths(worktree, home)
    assert _mode(worktree / ".claude") == 0o750
    assert (worktree / ".claude" / ".cc-writes").is_dir()
    assert (home / ".config" / "git" / "ignore").read_bytes() == b"*.o\n"


def test_nothing_is_made_through_a_link(tmp_path: Path) -> None:
    worktree, home, elsewhere = tmp_path / "worktree", tmp_path / "home", tmp_path / "elsewhere"
    for directory in (worktree, home, elsewhere):
        directory.mkdir()
    (worktree / ".claude").symlink_to(elsewhere)
    (home / ".config").symlink_to(elsewhere)
    runtime_paths(worktree, home)
    assert list(elsewhere.iterdir()) == []
