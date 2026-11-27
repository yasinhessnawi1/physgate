"""Where the harness keeps its own temporary files: a directory of the process's, no session's.

The orchestrator makes throwaway git stores it reads its change checks and review packets
through, scans' scratch folders and the like. In the shared temporary directories a session's
commands could change them (a store's configuration rewrites the diff a reviewer is shown) or
read them. So each harness process keeps them in a directory of its own, directly beneath one
parent of them all, ``/var/tmp/pgh``: a sibling of the sessions' own temporary directories'
parent, outside every place the OS layer makes writable, and named in every role and baseline
session's configuration as a root no tool or command of the session reads or writes, on every
layer.

The process's directory is made on first use and removed when the process exits.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import secrets
import shutil
import stat
from pathlib import Path

#: The parent of every harness process's own temporary directory.
HARNESS_TEMPS = "/var/tmp/pgh"

_OWN: dict[tuple[int, str], Path] = {}


def harness_temps_root() -> str:
    """The parent of every harness process's own temporary directory on this machine."""
    return HARNESS_TEMPS


def _parent(root: Path) -> Path:
    """``root`` made where missing, and held to be a directory of this user's alone.

    Raises:
        OSError: it cannot be made, or it is a link, not a directory, not this user's, or open
            to another user.
    """
    with contextlib.suppress(FileExistsError):
        root.mkdir(mode=0o700)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        msg = f"{root} is not a directory of this user's alone, so no harness directory is made"
        raise OSError(msg)
    return root


def harness_temp_dir(parent: str | None = None) -> Path:
    """This process's own temporary directory, where it really is; made on the first call.

    Every later call in the process returns the same directory, which is removed when the
    process exits. A ``tempfile`` call names it as its ``dir``.

    Raises:
        OSError: the parent cannot be made, or it is not a directory of this user's alone.
    """
    root = parent or harness_temps_root()
    # Keyed by the process too: a forked child makes and removes a directory of its own, and
    # never the one its parent still uses.
    key = (os.getpid(), root)
    made = _OWN.get(key)
    if made is not None and made.is_dir():
        return made
    child = _parent(Path(root)) / secrets.token_hex(5)
    child.mkdir(mode=0o700)
    made = Path(os.path.realpath(child))
    _OWN[key] = made
    atexit.register(_remove, made, os.getpid())
    return made


def _remove(made: Path, owner: int) -> None:
    """Remove ``made`` at exit, in the process that made it alone."""
    if os.getpid() == owner:
        shutil.rmtree(made, ignore_errors=True)
