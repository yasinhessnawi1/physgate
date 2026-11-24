"""What a session leaves in its worktree that is never part of its attempt.

Two kinds. The pathspecs of :data:`LEFT_OUT_OF_THE_COMMIT` keep both out of an attempt's commit,
so neither reaches the change check, the review's export and diff, the proposals or the merged
work; and :func:`clear_left_out` removes both from the worktree, so neither reaches the next
session there:

- **The scratch folder**, :data:`SCRATCH_DIR`: where a session puts a throwaway helper script, a
  plot or a note. It lies beneath ``.physgate``, where the decomposition refuses every module
  directory, so it is never a module's and never collides with one. Code run from it is code
  from outside every module, which the series collector refuses as it refuses code from any
  other place outside the module: a curve cannot stand on a helper the attempt does not commit.
- **Bytecode**, named in any case: whatever a ``__pycache__`` directory holds and every ``.pyc``
  file, anywhere in the worktree. An interpreter caches each module it imports beside that
  module's source, so a script importing another module's code left that module's cache outside
  its own module, and the attempt out of scope. Every session is spawned writing none
  (:data:`~physgate.orchestrator.invocation.SESSION_PYTHON`); this holds for a program that
  ignores that.

What is removed: everything the scratch folder holds, whatever git says of it, reached without
following a link (a link in the folder's place is removed as a link, and nothing it points at
is touched); and every bytecode file git does not track, ignored ones included. Bytecode the
run branch tracks is never removed, and a session's change to such a file is left out of the
commit. When: as each session starts, so no session finds what an earlier one left, and as it
ends, before its attempt is committed. A removal that fails is recorded, never fatal: the
pathspecs still keep what stayed out of the commit, and the next session's start tries again.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.git import common_dir, git, verified_git_dir

#: The one folder in a session's worktree whose contents are never part of its attempt.
SCRATCH_DIR = PurePosixPath(".physgate/scratch")
#: The name a directory of bytecode has; a module directory with a part of this name, in any
#: case, would have its files left out of every commit, so the decomposition refuses one.
BYTECODE_DIR = "__pycache__"
_BYTECODE = (f"**/{BYTECODE_DIR}/**", "**/*.pyc")
#: What ``git add`` is told to leave out of an attempt's commit: the scratch folder by its exact
#: name from the worktree's top, and bytecode in any case, anywhere.
LEFT_OUT_OF_THE_COMMIT = (
    f":(exclude,top,literal){SCRATCH_DIR}",
    *(f":(exclude,top,glob,icase){pattern}" for pattern in _BYTECODE),
)
_BYTECODE_LISTED = tuple(f":(top,glob,icase){pattern}" for pattern in _BYTECODE)
#: The most removed paths a record names one by one; past it they are counted.
MAX_NAMED = 50

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class LeftOut(BaseModel):
    """What one clearing removed from a worktree, and what it could not remove, with why.

    Each path is relative to the worktree, its bytes that are not printable ASCII escaped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The first :data:`MAX_NAMED` paths removed, in the order they were removed.
    removed: tuple[str, ...] = ()
    #: How many paths were removed in all; a folder counts once.
    removed_count: int = 0
    #: Each path that stays, with the reason.
    refused: tuple[tuple[str, str], ...] = ()


def _shown(path: str) -> str:
    raw = path.encode("utf-8", "surrogateescape")
    return "".join(chr(b) if 0x20 <= b < 0x7F and b != 0x5C else f"\\x{b:02x}" for b in raw)


class _Found:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.count = 0
        self.refused: list[tuple[str, str]] = []

    def gone(self, path: str) -> None:
        self.count += 1
        if len(self.removed) < MAX_NAMED:
            self.removed.append(_shown(path))

    def stays(self, path: str, why: str) -> None:
        if len(self.refused) < MAX_NAMED:
            self.refused.append((_shown(path), why))

    def done(self) -> LeftOut:
        return LeftOut(
            removed=tuple(self.removed), removed_count=self.count, refused=tuple(self.refused)
        )


def _open_parents(worktree: Path, parts: tuple[str, ...]) -> int:
    """A descriptor on ``worktree/parts...``, each part opened without following a link."""
    fd = os.open(worktree, _DIRECTORY)
    for part in parts:
        try:
            following = os.open(part, _DIRECTORY, dir_fd=fd)
        finally:
            os.close(fd)
        fd = following
    return fd


def _opened_up(parent: int, name: str) -> None:
    """Make the directory ``name`` and every directory beneath it its owner's to list and change.

    A session can leave a directory it may not list or change, which no removal gets past. Each
    is found by a listing that follows no link and changed by name from its parent, as the
    directory it was listed as.
    """
    stack = [(os.dup(parent), name)]
    while stack:
        above, here = stack.pop()
        try:
            os.chmod(here, 0o700, dir_fd=above)
            fd = os.open(here, _DIRECTORY, dir_fd=above)
        except OSError:
            continue  # left as it is: the removal then says why it stays
        finally:
            os.close(above)
        try:
            for entry in os.listdir(fd):
                if stat.S_ISDIR(os.stat(entry, dir_fd=fd, follow_symlinks=False).st_mode):
                    stack.append((os.dup(fd), entry))
        finally:
            os.close(fd)


def _clear_scratch(worktree: Path, found: _Found) -> None:
    *above, name = SCRATCH_DIR.parts
    try:
        parent = _open_parents(worktree, tuple(above))
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            # A link or something else in ``.physgate``'s place: nothing beneath it is reached,
            # and git stages no folder through it.
            why = f"the folder above it is not a directory ({exc.strerror})"
            found.stays(str(SCRATCH_DIR), why)
        return
    try:
        # By its exact name: on a volume that ignores case another spelling would open too.
        if name not in os.listdir(parent):
            return
        held = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(held.st_mode):
            os.unlink(name, dir_fd=parent)
        else:
            _opened_up(parent, name)
            shutil.rmtree(name, dir_fd=parent)
        found.gone(str(SCRATCH_DIR))
    except OSError as exc:
        found.stays(str(SCRATCH_DIR), f"it could not be removed ({exc.strerror})")
    finally:
        os.close(parent)


def _remove_bytecode(worktree: Path, relative: str, found: _Found) -> None:
    *above, name = relative.split("/")
    try:
        parent = _open_parents(worktree, tuple(above))
    except OSError as exc:
        found.stays(relative, f"a folder above it could not be opened ({exc.strerror})")
        return
    try:
        held = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISDIR(held.st_mode):
            found.stays(relative, "it is a directory")
            return
        os.unlink(name, dir_fd=parent)
        found.gone(relative)
    except OSError as exc:
        found.stays(relative, f"it could not be removed ({exc.strerror})")
    finally:
        os.close(parent)
    if above and above[-1].casefold() == BYTECODE_DIR:
        try:
            grand = _open_parents(worktree, tuple(above[:-1]))
        except OSError:
            return
        try:
            os.rmdir(above[-1], dir_fd=grand)
        except OSError:
            pass  # not empty yet, or already gone: either way nothing of it is committed
        finally:
            os.close(grand)


def clear_left_out(worktree: Path, *, repo: Path) -> LeftOut:
    """Remove the scratch folder and every untracked bytecode file from a session's worktree.

    ``repo`` is the repository the worktree was made in; its pointer is verified, and the one
    git command (the listing of untracked bytecode) runs pinned to its admin directory.

    Raises:
        GitError: the worktree's pointer does not verify, or git cannot list its files.
    """
    admin = verified_git_dir(worktree, linked=True, common=common_dir(repo))
    found = _Found()
    _clear_scratch(worktree, found)
    listed = git(
        worktree,
        "ls-files",
        "-z",
        "--others",
        "--",
        *_BYTECODE_LISTED,
        git_dir=admin,
        errors="surrogateescape",
    )
    for relative in sorted(p for p in listed.split("\0") if p):
        _remove_bytecode(worktree, relative, found)
    return found.done()
