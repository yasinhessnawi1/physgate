"""What Claude Code makes on its own in a role session is made first, with its own bytes.

Inside the OS layer on macOS, 2.1.301 makes ``.claude/.cc-writes/`` in the worktree and
``.config/git/ignore`` in the session's home, both under roots the sentinel puts back.
The dispatcher makes them before the session's record is taken (as measured:
the modes and the 23 bytes below), leaves a present path as it is, and writes nothing
through a link.
"""

from __future__ import annotations

from pathlib import Path

from physgate.orchestrator.dispatch import runtime_git_paths, runtime_paths

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


#: What 2.1.322 makes in the target repository's git directory when a session starts inside
#: the OS layer (measured on macOS through the real binary, 12.11.2026): three empty
#: directories, each 0755. 2.1.301 makes none of them.
GIT_MADE = ("branches", "remotes", "objects/info/commit-graphs")


def _git_dir(tmp_path: Path) -> Path:
    git_dir = tmp_path / "repo" / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    return git_dir


def _entries(top: Path) -> list[str]:
    return sorted(str(p.relative_to(top)) for p in top.rglob("*"))


def test_on_2_1_322_the_three_directories_the_runtime_makes_in_the_git_directory_are_made_first(
    tmp_path: Path,
) -> None:
    git_dir = _git_dir(tmp_path)
    runtime_git_paths(git_dir, "2.1.322", platform="darwin")
    made = {name: git_dir / name for name in GIT_MADE}
    assert {name: path.is_dir() and not path.is_symlink() for name, path in made.items()} == (
        dict.fromkeys(GIT_MADE, True)
    )
    assert {name: _mode(path) for name, path in made.items()} == dict.fromkeys(GIT_MADE, 0o755)
    assert all(list(path.iterdir()) == [] for path in made.values())
    assert _entries(git_dir) == sorted([*GIT_MADE, "objects", "objects/info"])


def test_on_the_earlier_pins_nothing_is_made_in_the_git_directory(tmp_path: Path) -> None:
    for version in ("2.1.272", "2.1.283", "2.1.301"):
        git_dir = _git_dir(tmp_path / version)
        runtime_git_paths(git_dir, version)
        assert _entries(git_dir) == ["objects", "objects/info"], version


def test_a_directory_already_there_is_left_as_it_is_and_the_others_are_made(
    tmp_path: Path,
) -> None:
    git_dir = _git_dir(tmp_path)
    (git_dir / "remotes").mkdir(mode=0o700)
    (git_dir / "remotes").chmod(0o700)
    (git_dir / "remotes" / "origin").write_text("URL: x\n")
    runtime_git_paths(git_dir, "2.1.322", platform="darwin")
    assert _mode(git_dir / "remotes") == 0o700
    assert (git_dir / "remotes" / "origin").read_text() == "URL: x\n"
    assert (git_dir / "branches").is_dir() and (git_dir / "objects/info/commit-graphs").is_dir()


def test_nothing_is_made_in_the_git_directory_through_a_link_or_beneath_a_missing_parent(
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git_dir = tmp_path / "repo" / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "objects").symlink_to(elsewhere)
    (git_dir / "branches").symlink_to(elsewhere)
    try:
        runtime_git_paths(git_dir, "2.1.322", platform="darwin")
    except OSError as exc:  # a path in the way is left alone, never an error
        raise AssertionError(f"a link in the way was not left alone: {exc!r}") from exc
    assert list(elsewhere.iterdir()) == []
    assert (git_dir / "remotes").is_dir()  # the one with nothing in its way
    bare = tmp_path / "bare" / ".git"
    bare.mkdir(parents=True)
    runtime_git_paths(
        bare, "2.1.322", platform="darwin"
    )  # no objects/info to make the third beneath
    assert _entries(bare) == ["branches", "remotes"]


#: On Linux (bubblewrap, CI, 12.11.2026) 2.1.322 leaves four more entries there: three marker
#: directories of its own, each 0755, and an empty ``alternates`` file, 0644.
LINUX_MORE = {
    "info/.claude-sandbox-noreplace": "dir 0o755",
    "objects/info/.claude-sandbox-noreplace": "dir 0o755",
    "objects/info/alternates": "file 0o644 0",
    "objects/info/commit-graphs/.claude-sandbox-noreplace": "dir 0o755",
}


def _kinds(top: Path) -> dict[str, str]:
    found = {}
    for path in sorted(top.rglob("*")):
        name = str(path.relative_to(top))
        if path.is_dir():
            found[name] = f"dir {oct(_mode(path))}"
        else:
            found[name] = f"file {oct(_mode(path))} {path.stat().st_size}"
    return found


def test_on_linux_2_1_322_s_four_further_entries_are_made_first_too(tmp_path: Path) -> None:
    git_dir = _git_dir(tmp_path)
    (git_dir / "info").mkdir()
    runtime_git_paths(git_dir, "2.1.322", platform="linux")
    expected = {
        "info": "dir 0o755",
        "objects": "dir 0o755",
        "objects/info": "dir 0o755",
        **dict.fromkeys(GIT_MADE, "dir 0o755"),
        **LINUX_MORE,
    }
    made = _kinds(git_dir)
    assert {name: made.get(name) for name in LINUX_MORE} == LINUX_MORE
    assert sorted(made) == sorted(expected)


def test_on_macos_none_of_linux_s_further_entries_is_made(tmp_path: Path) -> None:
    git_dir = _git_dir(tmp_path)
    (git_dir / "info").mkdir()
    runtime_git_paths(git_dir, "2.1.322", platform="darwin")
    assert sorted(_kinds(git_dir)) == sorted([*GIT_MADE, "info", "objects", "objects/info"])


def test_an_alternates_file_already_there_keeps_its_bytes(tmp_path: Path) -> None:
    git_dir = _git_dir(tmp_path)
    (git_dir / "objects" / "info" / "alternates").write_text("/elsewhere/objects\n")
    runtime_git_paths(git_dir, "2.1.322", platform="linux")
    assert (git_dir / "objects" / "info" / "alternates").read_text() == "/elsewhere/objects\n"
