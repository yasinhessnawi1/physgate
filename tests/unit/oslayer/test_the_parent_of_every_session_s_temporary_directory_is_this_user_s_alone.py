"""The parent of every session's own temporary directory is this user's alone, or none is made.

Every session's directory lies directly beneath one parent, which every session is refused but for
its own child. A parent someone else could have made or could still change would undo that: one
that is a link to elsewhere, one open to the group or to everyone, or a file in its place. Each is
refused, and no child is made. (A parent another user owns is refused by the same check; a test
running as one user cannot make one.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.oslayer.session_temp import make_session_temp


def test_a_parent_made_here_is_this_user_s_alone_and_gets_a_child(tmp_path: Path) -> None:
    child = make_session_temp(str(tmp_path / "pgs"))
    assert child.parent == tmp_path / "pgs" and child.is_dir()
    assert (tmp_path / "pgs").stat().st_mode & 0o077 == 0


def test_a_parent_that_is_a_link_is_refused_and_no_child_is_made(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    (tmp_path / "pgs").symlink_to(target)
    with pytest.raises(OSError, match="alone"):
        make_session_temp(str(tmp_path / "pgs"))
    assert list(target.iterdir()) == []


def test_a_parent_open_to_others_is_refused_and_no_child_is_made(tmp_path: Path) -> None:
    parent = tmp_path / "pgs"
    parent.mkdir()
    parent.chmod(0o755)
    with pytest.raises(OSError, match="alone"):
        make_session_temp(str(parent))
    assert list(parent.iterdir()) == []


def test_a_file_in_the_parent_s_place_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pgs").write_text("not a directory\n")
    with pytest.raises(OSError, match="alone"):
        make_session_temp(str(tmp_path / "pgs"))
