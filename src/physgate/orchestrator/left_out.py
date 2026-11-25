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
is touched); and every bytecode file git does not track, ignored ones included, each recorded
first by its path and digest: an interpreter runs a compiled file in place of its source, so it
is evidence of what may have run, and the session's end line carries it to the review. Bytecode
the run branch tracks is never removed, and a session's change to such a file is left out of
the commit. Every removal and every change of a mode goes by descriptor beneath the worktree.
When: as each session starts, so no session finds what an earlier one left, and as it ends,
before its attempt is committed. A removal that fails is recorded, never fatal: the pathspecs
still keep what stayed out of the commit, and the next session's start tries again. A record
whose process could have run a compiled file in place of a source is refused by the series
writer when it is written, so removing the file loses no evidence a record stands on.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.git import common_dir, git, verified_git_dir
from physgate.series.seal import Bytecode

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

_NOFOLLOW_DIR = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_DIRECTORY = os.O_RDONLY | _NOFOLLOW_DIR
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
#: The most bytes of one compiled file read for its digest; a larger one is named undigested.
MAX_COMPILED_BYTES = 16 * 1024 * 1024


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
    #: Every bytecode file found, removed or not, by path with its digest (the first
    #: :data:`MAX_NAMED`), and how many were found in all: evidence of what may have run.
    bytecode: tuple[Bytecode, ...] = ()
    bytecode_found: int = 0
    #: Whether everything was recorded and removed. ``False`` where anything stays, where an
    #: entry could not be recorded, or where the worktree could not be listed: the attempt the
    #: session's end clearing finds so is refused (``SessionSeries.left_out_incomplete``).
    complete: bool = True


#: The longest path a record holds (``Bytecode.path``'s bound).
MAX_PATH_SHOWN = 1024


def _shown(path: str) -> str:
    """``path`` as a record holds it: printable ASCII, cut to the bound with a marker.

    A path past the bound keeps its start, and the marker names the digest of the whole path's
    bytes, so the fact and the path's identity are kept.
    """
    raw = path.encode("utf-8", "surrogateescape")
    shown = "".join(chr(b) if 0x20 <= b < 0x7F and b != 0x5C else f"\\x{b:02x}" for b in raw)
    if len(shown) <= MAX_PATH_SHOWN:
        return shown
    marker = f"...[cut; the whole path's sha256 {hashlib.sha256(raw).hexdigest()}]"
    return shown[: MAX_PATH_SHOWN - len(marker)] + marker


class _Found:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.count = 0
        self.refused: list[tuple[str, str]] = []
        self.bytecode: list[Bytecode] = []
        self.bytecode_found = 0
        self.complete = True

    def gone(self, path: str) -> None:
        self.count += 1
        if len(self.removed) < MAX_NAMED:
            self.removed.append(_shown(path))

    def stays(self, path: str, why: str) -> None:
        self.complete = False
        if len(self.refused) < MAX_NAMED:
            self.refused.append((_shown(path), why))

    def compiled(self, path: str, data: bytes | None) -> None:
        self.bytecode_found += 1
        if len(self.bytecode) < MAX_NAMED:
            digest = None if data is None else hashlib.sha256(data).hexdigest()
            length = None if data is None else len(data)
            self.bytecode.append(Bytecode(path=_shown(path), sha256=digest, length=length))

    def done(self) -> LeftOut:
        return LeftOut(
            removed=tuple(self.removed),
            removed_count=self.count,
            refused=tuple(self.refused),
            bytecode=tuple(self.bytecode),
            bytecode_found=self.bytecode_found,
            complete=self.complete,
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


def _mode_opened_without_following(parent: int, name: str) -> None:
    """Make the directory ``name`` beneath ``parent`` its owner's, where it cannot be opened.

    A directory a session made unreadable cannot be opened for its mode, so the mode is changed
    without following a link: where the platform changes a mode that way, by name; else (Linux)
    on a descriptor that only names the very directory opened, through its entry in ``/proc``.
    It must be a directory with the same identity before and after, else nothing goes on.
    """
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, "not a directory", name)
    if os.chmod in os.supports_follow_symlinks and os.chmod in os.supports_dir_fd:
        os.chmod(name, 0o700, dir_fd=parent, follow_symlinks=False)
    elif hasattr(os, "O_PATH") and os.path.isdir("/proc/self/fd"):
        handle = os.open(name, os.O_PATH | _NOFOLLOW_DIR, dir_fd=parent)
        try:
            os.chmod(f"/proc/self/fd/{handle}", 0o700)
        finally:
            os.close(handle)
    else:
        raise PermissionError(errno.EACCES, "no way to change its mode without a link", name)
    after = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(after.st_mode) or (after.st_dev, after.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        raise NotADirectoryError(errno.ENOTDIR, "it changed while its mode was changed", name)


def _held_dir(parent: int, name: str) -> int:
    """A descriptor on the directory ``name`` beneath ``parent``, made its owner's to change.

    Opened without following a link, and its mode changed on that descriptor, so no name is
    read twice: what was opened is what is changed.
    """
    try:
        fd = os.open(name, _DIRECTORY, dir_fd=parent)
    except PermissionError:
        _mode_opened_without_following(parent, name)
        fd = os.open(name, _DIRECTORY, dir_fd=parent)
    try:
        os.fchmod(fd, 0o700)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _remove_tree(parent: int, name: str) -> None:
    """Remove ``name`` beneath ``parent`` and all it holds, by descriptor, following no link.

    A link is removed as a link. An entry that is not what it was listed as when it is reached
    (a directory swapped for a link, say) makes its removal fail, and nothing it points at is
    touched.
    """
    found = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(found.st_mode):
        os.unlink(name, dir_fd=parent)
        return
    fd = _held_dir(parent, name)
    try:
        for entry in os.listdir(fd):
            _remove_tree(fd, entry)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


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
        _remove_tree(parent, name)
        found.gone(str(SCRATCH_DIR))
    except (OSError, RecursionError) as exc:
        found.stays(str(SCRATCH_DIR), f"it could not be removed ({exc})")
    finally:
        os.close(parent)


def _read_compiled(parent: int, name: str) -> bytes | None:
    """The bytes of the compiled file ``name``, read without following a link; ``None`` if not."""
    try:
        fd = os.open(name, _FILE, dir_fd=parent)
    except OSError:
        return None
    try:
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode) or held.st_size > MAX_COMPILED_BYTES:
            return None
        chunks, total = [], 0
        while total <= MAX_COMPILED_BYTES:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks) if total <= MAX_COMPILED_BYTES else None
    finally:
        os.close(fd)


def _remove_bytecode(worktree: Path, relative: str, found: _Found) -> None:
    """Record one listed bytecode path and remove it; whatever goes wrong is recorded for it."""
    counted = found.bytecode_found
    try:
        _record_and_remove(worktree, relative, found)
    except Exception as exc:  # noqa: BLE001 - recorded for the entry, never out of an attempt's end
        if found.bytecode_found == counted:
            found.compiled(relative, None)
        found.stays(relative, f"it could not be recorded or removed ({type(exc).__name__})")


def _record_and_remove(worktree: Path, relative: str, found: _Found) -> None:
    *above, name = relative.rstrip("/").split("/")
    try:
        parent = _open_parents(worktree, tuple(above))
    except OSError as exc:
        found.compiled(relative, None)
        found.stays(relative, f"a folder above it could not be opened ({exc.strerror})")
        return
    try:
        held = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISDIR(held.st_mode):
            found.stays(relative, "it is a directory")
            return
        found.compiled(relative, _read_compiled(parent, name))
        try:
            os.unlink(name, dir_fd=parent)
        except PermissionError:
            if not above or above[-1].casefold() != BYTECODE_DIR:
                raise
            # A bytecode folder the session made unwritable: changed on its own descriptor.
            os.fchmod(parent, 0o700)
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


def _open_bytecode_folders(worktree: Path, found: _Found) -> None:
    """Make every bytecode folder in the worktree listable; record a directory that is not.

    git lists nothing beneath a directory it cannot open, so a bytecode folder a session made
    unlistable would keep its files from the record and the removal: each is opened here by
    descriptor, its mode changed on that descriptor (:func:`_held_dir`). Any other directory
    that cannot be listed is recorded, and the clearing is then not complete.
    """
    pending: list[tuple[str, ...]] = [()]
    while pending:
        parts = pending.pop()
        try:
            fd = _open_parents(worktree, parts)
        except OSError as exc:
            found.stays("/".join(parts) or ".", f"it cannot be listed ({exc.strerror})")
            continue
        try:
            for name in os.listdir(fd):
                if name.casefold() == ".git":
                    continue
                try:
                    held = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISDIR(held.st_mode):
                        continue
                    if name.casefold() == BYTECODE_DIR:
                        os.close(_held_dir(fd, name))
                except OSError as exc:
                    shown = "/".join((*parts, name))
                    found.stays(shown, f"it cannot be opened ({exc.strerror})")
                    continue
                pending.append((*parts, name))
        except OSError as exc:
            found.stays("/".join(parts) or ".", f"it cannot be listed ({exc.strerror})")
        finally:
            os.close(fd)


def clear_left_out(worktree: Path, *, repo: Path) -> LeftOut:
    """Remove the scratch folder and every untracked bytecode file from a session's worktree.

    Each bytecode file is recorded by its path and digest before it is removed. ``repo`` is the
    repository the worktree was made in; its pointer is verified, and the one git command (the
    listing of untracked bytecode) runs pinned to its admin directory. Every change below the
    worktree is made through descriptors opened without following a link.

    It never raises: whatever stays, cannot be recorded or cannot be listed (the worktree's
    pointer not verifying among it) is recorded with its reason, the walk goes on, and the
    result says it is not complete, for the caller to act on.
    """
    found = _Found()
    try:
        _clear_scratch(worktree, found)
    except Exception as exc:  # noqa: BLE001 - recorded, never out of an attempt's end
        found.stays(str(SCRATCH_DIR), f"it could not be cleared ({type(exc).__name__})")
    try:
        _open_bytecode_folders(worktree, found)
    except Exception as exc:  # noqa: BLE001 - recorded, never out of an attempt's end
        found.stays(".", f"the worktree could not be walked ({type(exc).__name__})")
    try:
        admin = verified_git_dir(worktree, linked=True, common=common_dir(repo))
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
    except Exception as exc:  # noqa: BLE001 - recorded, never out of an attempt's end
        found.stays(".", f"the worktree's untracked bytecode could not be listed ({exc})")
        return found.done()
    for relative in sorted(p for p in listed.split("\0") if p):
        _remove_bytecode(worktree, relative, found)
    return found.done()
