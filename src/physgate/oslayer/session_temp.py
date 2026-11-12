"""Where each session's own temporary directory is made: directly beneath one parent of them all.

Claude Code keeps a session's temporary files, its background commands' output among them, in the
directory ``CLAUDE_CODE_TMPDIR`` names. Every session runs as the same user, so a directory's mode
keeps no session from another's: the parent of them all is refused to every session's every read
and write, on every layer, and only the session's own child beneath it is opened again.

The parent is ``/var/tmp/pgs``. It lies outside every place the OS layer makes writable (``/tmp``
and the per-user temporary directory are), so a sibling made after a session started is still
denied to that session's commands. A child's name is 10 hexadecimal digits, so even its resolved
spelling on macOS (``/private/var/tmp/pgs/<10>``, 31 characters) is short enough for Claude Code
to take it.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from pathlib import Path

#: The parent of every session's own temporary directory.
SESSION_TEMPS = "/var/tmp/pgs"


def session_temps_root() -> str:
    """The parent of every session's own temporary directory on this machine."""
    return SESSION_TEMPS


def make_session_temp(parent: str | None = None) -> Path:
    """Make a new session's own temporary directory, directly beneath the parent of them all.

    Raises:
        OSError: the parent cannot be made, or it is a link, not a directory, not this user's,
            or open to another user; or the child cannot be made.
    """
    root = Path(parent or session_temps_root())
    with contextlib.suppress(FileExistsError):
        root.mkdir(mode=0o700)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        msg = f"{root} is not a directory of this user's alone, so no session's directory is made"
        raise OSError(msg)
    child = root / secrets.token_hex(5)
    child.mkdir(mode=0o700)
    return child
