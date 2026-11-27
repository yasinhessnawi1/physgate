"""What a session leaves in its worktree that is never part of its attempt, and what it shows.

Two kinds. The pathspecs of :data:`LEFT_OUT_OF_THE_COMMIT` keep both out of an attempt's commit,
so neither reaches the change check, the review's export and diff, the proposals or the merged
work; and :func:`clear_left_out` removes both from the worktree, so neither reaches the next
session there:

- **The scratch folder**, :data:`SCRATCH_DIR`: where a session puts a throwaway helper script, a
  plot or a note. It lies beneath ``.physgate``, where the decomposition refuses every module
  directory, so it is never a module's and never collides with one. A record that names code in
  it is refused by the series collector, as a record that names code from any other place
  outside the module is. Code run from it that a record does not name is not seen by the
  collector, so what the folder held is recorded, each entry by its path, its kind, its length
  and its digest, before it is removed (the first :data:`MAX_SCRATCH_NAMED`, and the bytes of at
  most :data:`MAX_SCRATCH_BYTES` read, the record saying where it stopped).
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
still keep what stayed out of the commit, and the next session's start tries again.

**What the end's look marks.** The series writer refuses, in the session's own process, to
write a record while a compiled file lies where the interpreter reads one for a module it
loaded: that catches a cache left there by accident, and nothing more, since the process is
the session's. So the orchestrator looks too, when the session has ended (:func:`end_series`):
a compiled file found where the interpreter reads one in place of the source of a file a
sealed record names (:class:`Beside`, decided from the sealed record's own list of its script
and what it loaded), or of the series writer, marks that record not vouched for in the review's
listing, with the file's path and digest. It looks in the worktree and, for a cache prefix,
in the session's own home and temporary directory. The attempt is not refused for it. A
session can still avoid the mark: by code that removes its own compiled file once it has run,
by a source that rewrites itself, by code run from no file or from a place the look does not
reach (a shared temporary directory a session can write where the OS layer does not deny it,
a path entry outside these places), each of which leaves nothing at the session's end. Only
running the committed script again, in a clean checkout, would show what it computes; the
harness does not.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from physgate.orchestrator.git import common_dir, git, verified_git_dir
from physgate.series.collect import WRITER_PATH
from physgate.series.seal import (
    MAX_ENTRIES,
    NOT_VOUCHED,
    Bytecode,
    ScratchFile,
    SealedRecord,
    SessionSeries,
)

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
#: The most scratch-folder entries one record names, and the most of their bytes read for
#: digests; past either the record says where it stopped.
MAX_SCRATCH_NAMED = 200
MAX_SCRATCH_BYTES = 64 * 1024 * 1024
#: The most entries the look for a cache prefix's files visits in the session's own places.
MAX_LOOKED = 100_000

#: Which of a session's sealed records a compiled file's path lies beside, by their ids.
Concerns = Callable[[str], tuple[str, ...]]


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
    #: Every entry the scratch folder held, recorded before it was removed (the first
    #: :data:`MAX_SCRATCH_NAMED`), how many in all, and where the record stopped at a bound.
    scratch: tuple[ScratchFile, ...] = ()
    scratch_found: int = 0
    scratch_cut: str | None = None
    #: Compiled files that mark a record and were found past the end line's bound, unnamed.
    concerning_unnamed: int = 0
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
    def __init__(self, concerns: Concerns | None = None) -> None:
        self.removed: list[str] = []
        self.count = 0
        self.refused: list[tuple[str, str]] = []
        self.bytecode: list[Bytecode] = []
        self.bytecode_found = 0
        self.complete = True
        self.concerns = concerns
        #: A file that marks a record and could not be named within the end line's bound.
        self.unnamed_concerning = 0
        self.scratch: list[ScratchFile] = []
        self.scratch_found = 0
        self.scratch_read = 0
        self.scratch_unread = 0

    def gone(self, path: str) -> None:
        self.count += 1
        if len(self.removed) < MAX_NAMED:
            self.removed.append(_shown(path))

    def stays(self, path: str, why: str) -> None:
        self.complete = False
        if len(self.refused) < MAX_NAMED:
            self.refused.append((_shown(path), why))

    def compiled(self, path: str, data: bytes | None) -> None:
        """Count a compiled file, and name it where the bound leaves room or it marks a record.

        The first :data:`MAX_NAMED` are named; past them, a file that marks a record is named
        too, up to the end line's bound, so no mark is lost to the first bound.
        """
        self.bytecode_found += 1
        records = self.concerns(path) if self.concerns is not None else ()
        if len(self.bytecode) < MAX_NAMED or (records and len(self.bytecode) < MAX_ENTRIES):
            digest = None if data is None else hashlib.sha256(data).hexdigest()
            length = None if data is None else len(data)
            self.bytecode.append(
                Bytecode(path=_shown(path), sha256=digest, length=length, records=records)
            )
        elif records:
            self.unnamed_concerning += 1

    def scratch_entry(self, parent: int, name: str, path: str, held: os.stat_result) -> None:
        """Record one entry of the scratch folder, before it is removed."""
        self.scratch_found += 1
        if len(self.scratch) >= MAX_SCRATCH_NAMED:
            return
        shown = _shown(path)
        if stat.S_ISLNK(held.st_mode):
            self.scratch.append(ScratchFile(path=shown, kind="link"))
            return
        if not stat.S_ISREG(held.st_mode):
            self.scratch.append(ScratchFile(path=shown, kind="other"))
            return
        digest = None
        if held.st_size <= MAX_COMPILED_BYTES and self.scratch_read + held.st_size <= (
            MAX_SCRATCH_BYTES
        ):
            data = _read_scratch(parent, name, held)
            if data is not None:
                self.scratch_read += len(data)
                digest = hashlib.sha256(data).hexdigest()
        if digest is None:
            self.scratch_unread += 1
        self.scratch.append(
            ScratchFile(path=shown, kind="file", length=held.st_size, sha256=digest)
        )

    def _scratch_cut(self) -> str | None:
        said = []
        if self.scratch_found > len(self.scratch):
            said.append(
                f"named the first {len(self.scratch)} of {self.scratch_found} entries "
                f"(the bound is {MAX_SCRATCH_NAMED})"
            )
        if self.scratch_unread:
            said.append(
                f"{self.scratch_unread} file{'s' * (self.scratch_unread != 1)} named by "
                "length alone: unreadable, over "
                f"{MAX_COMPILED_BYTES} bytes, or past the {MAX_SCRATCH_BYTES} bytes read in all"
            )
        return "; ".join(said) or None

    def done(self) -> LeftOut:
        return LeftOut(
            removed=tuple(self.removed),
            removed_count=self.count,
            refused=tuple(self.refused),
            bytecode=tuple(self.bytecode),
            bytecode_found=self.bytecode_found,
            scratch=tuple(self.scratch),
            scratch_found=self.scratch_found,
            scratch_cut=self._scratch_cut(),
            concerning_unnamed=self.unnamed_concerning,
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


def _remove_tree(
    parent: int, name: str, record: _Found | None = None, path: str | None = None
) -> None:
    """Remove ``name`` beneath ``parent`` and all it holds, by descriptor, following no link.

    A link is removed as a link. An entry that is not what it was listed as when it is reached
    (a directory swapped for a link, say) makes its removal fail, and nothing it points at is
    touched. With ``record``, every entry that is not a directory is recorded there, by its
    ``path`` and what it holds, before it is removed; entries are taken in name order.
    """
    found = os.stat(name, dir_fd=parent, follow_symlinks=False)
    shown = path if path is not None else name
    if not stat.S_ISDIR(found.st_mode):
        if record is not None:
            record.scratch_entry(parent, name, shown, found)
        os.unlink(name, dir_fd=parent)
        return
    fd = _held_dir(parent, name)
    try:
        for entry in sorted(os.listdir(fd)):
            _remove_tree(fd, entry, record, f"{shown}/{entry}")
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


def _read_scratch(parent: int, name: str, listed: os.stat_result) -> bytes | None:
    """The bytes of the regular file ``name``, read without following a link; ``None`` if not.

    A file the session made unreadable is made its owner's first, by name without following a
    link (or, on Linux, through a descriptor that only names it), and read only if what is
    opened is the very file listed.
    """
    try:
        fd = os.open(name, _FILE, dir_fd=parent)
    except PermissionError:
        try:
            if os.chmod in os.supports_follow_symlinks and os.chmod in os.supports_dir_fd:
                os.chmod(name, 0o600, dir_fd=parent, follow_symlinks=False)
            elif hasattr(os, "O_PATH") and os.path.isdir("/proc/self/fd"):
                handle = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    os.chmod(f"/proc/self/fd/{handle}", 0o600)
                finally:
                    os.close(handle)
            fd = os.open(name, _FILE, dir_fd=parent)
        except OSError:
            return None
    except OSError:
        return None
    try:
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode) or (held.st_dev, held.st_ino) != (
            listed.st_dev,
            listed.st_ino,
        ):
            return None
        data = _read_bounded(fd)
        return data
    finally:
        os.close(fd)


def _read_bounded(fd: int) -> bytes | None:
    """At most :data:`MAX_COMPILED_BYTES` from ``fd``; ``None`` where it holds more."""
    chunks, total = [], 0
    while total <= MAX_COMPILED_BYTES:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks) if total <= MAX_COMPILED_BYTES else None


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
        _remove_tree(parent, name, found, str(SCRATCH_DIR))
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
        return _read_bounded(fd)
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


def clear_left_out(worktree: Path, *, repo: Path, concerns: Concerns | None = None) -> LeftOut:
    """Remove the scratch folder and every untracked bytecode file from a session's worktree.

    What the scratch folder holds, and each bytecode file, is recorded by its path and digest
    before it is removed. ``repo`` is the repository the worktree was made in; its pointer is
    verified, and the one git command (the listing of untracked bytecode) runs pinned to its
    admin directory. Every change below the worktree is made through descriptors opened without
    following a link. ``concerns`` names the sealed records each bytecode path lies beside
    (:class:`Beside`): such a file is named on the record past the usual bound.

    It never raises: whatever stays, cannot be recorded or cannot be listed (the worktree's
    pointer not verifying among it) is recorded with its reason, the walk goes on, and the
    result says it is not complete, for the caller to act on.
    """
    found = _Found(concerns)
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


# ── what the session's end marks ─────────────────────────────────────────────


class Beside:
    """Which of a session's sealed records a compiled file lies beside, decided from the records.

    A sealed record lists, as the collector sealed it, its script and every other file of code
    its process reported loading from the worktree; nothing the session writes after its end
    changes that list. A compiled file lies beside such a file ``<dir>/<stem>.py`` where the
    interpreter reads one in place of its source: ``<dir>/__pycache__/<stem>.<tag>.pyc``, a
    ``<dir>/<stem>.pyc`` beside it, or, beneath a cache prefix, any path that ends
    ``/<dir>/<stem>.<tag>.pyc`` (a prefix mirrors the source's absolute path, which ends with its
    path in the worktree). Names are compared in any case, as on a volume that ignores it. The
    series writer counts for every record, named or not: a cache of it could stand in for the
    check it makes. A file that matches no record marks none.
    """

    def __init__(self, records: Iterable[SealedRecord]) -> None:
        """Hold, for each file the records name, its directory, its stem and the records'."""
        by_file: dict[str, set[str]] = {}
        ids: set[str] = set()
        for record in records:
            ids.add(record.record_id)
            for path in (record.script, *(code.path for code in record.loaded)):
                by_file.setdefault(path, set()).add(record.record_id)
        if ids:
            by_file.setdefault(str(WRITER_PATH), set()).update(ids)
        self._named: list[tuple[str, str, tuple[str, ...]]] = []
        for path, held in sorted(by_file.items()):
            named = PurePosixPath(path)
            stem = named.name.rsplit(".", 1)[0] if "." in named.name else named.name
            self._named.append((str(named.parent).casefold(), stem.casefold(), tuple(sorted(held))))

    def __bool__(self) -> bool:
        """Whether any record is held: with none, no file marks anything."""
        return bool(self._named)

    def __call__(self, path: str) -> tuple[str, ...]:
        """The ids of the records ``path`` lies beside, in order; none for any other file."""
        folded = path.casefold()
        if not folded.endswith(".pyc"):
            return ()
        found: set[str] = set()
        rooted = "/" + folded
        for directory, stem, ids in self._named:
            cache = f"/{directory}/__pycache__/{stem}."
            mirrored = f"/{directory}/{stem}."
            at = rooted.rfind(mirrored)
            rest = rooted[at + len(mirrored) :] if at >= 0 else ""
            if (rooted.startswith(cache) and "/" not in rooted[len(cache) :]) or (
                at >= 0 and "/" not in rest and (rest == "pyc" or rest.endswith(".pyc"))
            ):
                found.update(ids)
        return tuple(sorted(found))


def _digest_found(parent: int, name: str) -> tuple[str | None, int | None]:
    data = _read_compiled(parent, name)
    if data is None:
        return None, None
    return hashlib.sha256(data).hexdigest(), len(data)


def caches_beneath(places: Iterable[Path], concerns: Concerns) -> tuple[list[Bytecode], str | None]:
    """Every compiled file beneath ``places`` that lies beside a record, and why the look stopped.

    The places are the session's own (its home, its temporary directory), where a cache prefix
    it set would put a compiled file. Walked by descriptor, following no link, entries in name
    order, at most :data:`MAX_LOOKED` of them; each file named as a record's cache is recorded
    by its absolute path and digest and left where it lies. ``None`` for the reason where the
    look was whole; else what kept it from being whole (a directory that cannot be listed, the
    bound).
    """
    found: list[Bytecode] = []
    looked = 0
    for place in places:
        try:
            top = os.open(place, _DIRECTORY)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return found, f"{_shown(str(place))} could not be listed ({exc.strerror})"
        pending: list[tuple[int, str]] = [(top, str(place))]
        try:
            while pending:
                fd, shown = pending.pop()
                try:
                    for name in sorted(os.listdir(fd)):
                        looked += 1
                        if looked > MAX_LOOKED:
                            return found, (
                                f"the look stopped at its bound of {MAX_LOOKED} entries in the "
                                "session's own directories"
                            )
                        path = f"{shown}/{name}"
                        held = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(held.st_mode):
                            try:
                                inner = os.open(name, _DIRECTORY, dir_fd=fd)
                            except OSError as exc:
                                return found, f"{_shown(path)} could not be listed ({exc.strerror})"
                            pending.append((inner, path))
                            continue
                        records = concerns(path)
                        if records:
                            digest, length = _digest_found(fd, name)
                            found.append(
                                Bytecode(
                                    path=_shown(path), sha256=digest, length=length, records=records
                                )
                            )
                except OSError as exc:
                    return found, f"{_shown(shown)} could not be listed ({exc.strerror})"
                finally:
                    os.close(fd)
        finally:
            for fd, _ in pending:
                os.close(fd)
    return found, None


def end_series(
    series: SessionSeries, cleared: LeftOut, concerns: Concerns, *, own: Iterable[Path] = ()
) -> SessionSeries:
    """The session's end line's series: what the collector sealed, with what the end found.

    The bytecode the end clearing found (each file that lies beside a sealed record carrying
    its ids), every record's cache beneath the session's own places ``own``, whether the
    clearing was complete, and what the scratch folder held. Where the look could not be whole
    (a place that cannot be listed, a bound reached), every sealed record of the session is not
    vouched for, and ``not_vouched`` says why. Unchanged where the end found nothing.
    """
    bytecode = list(cleared.bytecode)
    found = cleared.bytecode_found
    why: list[str] = []
    if series.records and concerns:
        elsewhere, stopped = caches_beneath(own, concerns)
        room = MAX_ENTRIES - len(bytecode)
        bytecode += elsewhere[:room]
        found += len(elsewhere)
        if stopped is not None:
            why.append(stopped)
        if len(elsewhere) > room or cleared.concerning_unnamed:
            why.append(
                f"more files lay beside its records than the {MAX_ENTRIES} an end line names"
            )
    update: dict[str, object] = {}
    if found or not cleared.complete:
        update |= {
            "bytecode": tuple(bytecode),
            "bytecode_found": found,
            "left_out_incomplete": not cleared.complete,
        }
    if why:
        update["not_vouched"] = (
            f"{NOT_VOUCHED}: the look for bytecode beside its code was not whole: " + "; ".join(why)
        )[:500]
    if cleared.scratch_found:
        update |= {
            "scratch": cleared.scratch,
            "scratch_found": cleared.scratch_found,
            "scratch_cut": cleared.scratch_cut,
        }
    return series.model_copy(update=update) if update else series
