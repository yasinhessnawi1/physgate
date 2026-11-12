"""What each pin's runtime leaves in the repository's git directory inside the OS layer.

A session's end is held to the git directory being what it was at its start, so whatever the
runtime itself makes there has to be known exactly, per version and per platform, to be made
first by the dispatcher. One sandboxed command is run in a linked worktree, and everything
that appeared in the common git directory is listed with its kind, mode, size and digest.
A platform with no entry has not been measured, and its row fails saying what it found.
"""

from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path

import pytest
from fake_messages_api import tool
from hook_session import pinned_version
from os_layer_rig import Layout, layer_here, make_layout, run_session

pytestmark = pytest.mark.integration

_THREE_DIRECTORIES = {
    "branches": "dir 0o755",
    "objects/info/commit-graphs": "dir 0o755",
    "remotes": "dir 0o755",
}
#: Measured through the real binaries, 12.11.2026 (macOS, Seatbelt).
MADE: dict[tuple[str, str], dict[str, str]] = {
    ("darwin", "2.1.301"): {},
    ("darwin", "2.1.322"): _THREE_DIRECTORIES,
}


def _listing(top: Path) -> dict[str, str]:
    found = {}
    for path in sorted(top.rglob("*")):
        st = path.lstat()
        name = str(path.relative_to(top))
        if stat.S_ISDIR(st.st_mode):
            found[name] = f"dir {oct(st.st_mode & 0o777)}"
        elif stat.S_ISLNK(st.st_mode):
            found[name] = "link"
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            found[name] = f"file {oct(st.st_mode & 0o777)} {st.st_size} {digest}"
    return found


def test_what_appears_in_the_git_directory_is_what_was_measured_for_this_pin(
    tmp_path: Path,
) -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")
    with make_layout(tmp_path) as layout:
        made = _made(layout)
    measured = MADE.get((sys.platform, pinned_version()))
    assert measured is not None, f"not measured on {sys.platform} yet; found {made}"
    assert made == measured, (sys.platform, pinned_version())


def _made(layout: Layout) -> dict[str, str]:
    before = _listing(layout.common)
    run_session(layout, [tool("Bash", command="true", description="x")], layer=True)
    after = _listing(layout.common)
    # What git itself rewrites while a command runs (its index and logs) is not the runtime's.
    return {name: what for name, what in after.items() if name not in before}
