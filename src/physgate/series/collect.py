"""Collecting a session's series records when it ends, before the attempt is committed.

A role's scripts write records into the worktree's outbox, ``.physgate/series/``. When the
session has ended, and before the orchestrator commits what it left, every entry of the
outbox is taken out of the worktree:

- a valid record whose code the attempt will commit is **copied** into
  ``<run>/series/<subtask>/<attempt>/<session>/`` and sealed;
- anything else is moved aside, refused with its reason or discarded, and listed;
- the outbox is left empty, so git never carries a record: the review packet issues the diff
  in parts of at most 20,000 bytes and refuses a longer line, which one columnar record is.

**What makes a record sealable**, beyond the record format itself:

- its file is named for its id, is a regular file with one name, and fits the session's
  bounds on count and bytes;
- the script that produced it, and every file of code the producing process loaded, lie in
  the attempt's module directory (the writer itself excepted), where the attempt commits;
  code run from anywhere else, a scratch script under ``/tmp`` for instance, is refused;
- each of those files still has the digest the writer recorded, so the curve was not written
  by an earlier version of that code; the blob of each is sealed with the record, and the
  change check holds the attempt commit to every one of them, so the code is code the attempt
  commits with exactly those bytes (ignored or never-added code refuses the record there).

What this cannot prove is that the script produced the curve: a script that writes a curve
it did not compute names itself honestly. Re-running the script is that proof, and it is not
made here.

**Never through a link.** The outbox is in the role's worktree, so a role could make it, or
the directory above it, a link to somewhere else, and a collector that moved and deleted
through it would move and delete there. The outbox's real path must be exactly the worktree's
own, the directory is opened once without following a link, and every listing, open, rename
and removal is made relative to that one open directory. A record is copied, never renamed
into the run, so no inode a role chose (one with a second name it keeps) ends up sealed; a
file with a second name is refused.

**Before every session**, whatever an earlier session left in the outbox (an orchestrator
killed before it collected) is moved aside, so a record is always the session's own.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import physgate.series.writer as writer
from physgate.orchestrator.trajectory import seal
from physgate.series.exceptions import RecordRefusedError, RecordTamperedError
from physgate.series.reader import SERIES_DIR, record_path
from physgate.series.record import (
    MAX_FILE_BYTES,
    MAX_RECORDS_PER_SESSION,
    MAX_SESSION_BYTES,
    CodeFile,
    Record,
    parse_record,
)
from physgate.series.seal import (
    MAX_ENTRIES,
    NAME_PATTERN,
    CodeBlob,
    CodeDigest,
    SealedRecord,
    SessionSeries,
    SetAside,
)

#: The outbox, relative to the worktree.
OUTBOX = PurePosixPath(".physgate/series")
#: Where the writer lives in a worktree: the one file of code outside the module a record may
#: name as loaded.
WRITER_PATH = PurePosixPath(".physgate/lib/series_writer.py")
#: Beneath ``<run>/series``, where what was not sealed is kept. No subtask id can take either
#: name, since a subtask id begins with a letter or a digit.
REFUSED_DIR = "_refused"
DISCARDED_DIR = "_discarded"
#: The most bytes one file of code may hold, when the collector reads it to check its digest.
MAX_CODE_BYTES = 16 * 1024 * 1024

_RECORD_FILE = re.compile(NAME_PATTERN.removesuffix("$") + r"\.json$")
_NOFOLLOW_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def writer_source() -> bytes:
    """The writer's bytes as the harness ships them: what a run puts at :data:`WRITER_PATH`."""
    return Path(writer.__file__).read_bytes()


def series_library() -> dict[Path, bytes]:
    """What decomposition puts into a run branch for series records: the writer, by its path."""
    return {Path(WRITER_PATH): writer_source()}


class _RefusedError(Exception):
    """A file is not sealed; the message is the reason the session's end records."""


def _printable(name: str) -> str:
    shown = name.encode("unicode_escape").decode("ascii")
    return (shown or "(empty name)")[:200]


@dataclass
class _Listing:
    """What is set aside, held under the bound the session's end line may carry."""

    entries: list[SetAside] = field(default_factory=list)
    overflow: int = 0

    def add(self, name: str, reason: str) -> None:
        if len(self.entries) < MAX_ENTRIES - 1:
            self.entries.append(SetAside(name=_printable(name), reason=reason[:500]))
        else:
            self.overflow += 1

    def done(self) -> tuple[SetAside, ...]:
        if self.overflow:
            more = f"{self.overflow} more entries, set aside like the ones above"
            return (*self.entries, SetAside(name="(more)", reason=more))
        return tuple(self.entries)


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
#: What opening a link without following it, or a non-directory as one, raises.
_NOT_A_DIRECTORY = frozenset({errno.ELOOP, errno.ENOTDIR})


def _open_chain(base: Path, parts: tuple[str, ...]) -> int:
    """The directory ``parts`` beneath ``base``, reached one component at a time.

    Each component is opened relative to the last and never through a link, so a directory
    swapped for a link between any check and this open is refused rather than followed.

    Raises:
        OSError: a component is missing, a link, or not a directory.
    """
    fd = os.open(base, _DIRECTORY_FLAGS)
    try:
        for part in parts:
            inner = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = inner
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_outbox(worktree: Path) -> int | None:
    """The outbox opened as a directory, or ``None`` if there is none.

    Raises:
        _RefusedError: the outbox, or a directory on the way to it, is a link or not a
            directory.
    """
    base = Path(os.path.realpath(worktree))
    try:
        return _open_chain(base, OUTBOX.parts)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in _NOT_A_DIRECTORY:
            msg = "the outbox, or a directory on the way to it, is a link or not a directory"
        else:
            msg = f"the outbox cannot be opened as a directory ({exc.strerror})"
        raise _RefusedError(msg) from None


@dataclass(frozen=True)
class _Place:
    """A directory beneath the run directory's real path, made and opened without a link.

    The run's records are the orchestrator's, but a process a session left running could
    plant a link where one of these directories goes; the place is reached one component
    at a time from the run directory, so a planted link is refused rather than written
    through.
    """

    base: Path
    parts: tuple[str, ...]

    def open(self) -> int:
        """The directory, made where missing, opened one component at a time."""
        # The base is the run directory's own real path: nothing a session placed is on it.
        self.base.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.base, _DIRECTORY_FLAGS)
        try:
            for part in self.parts:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o755, dir_fd=fd)
                inner = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = inner
        except OSError as exc:
            os.close(fd)
            msg = "a directory of the run's series records is a link or not a directory"
            raise RecordTamperedError(
                msg, base=str(self.base), parts="/".join(self.parts), error=exc.strerror or ""
            ) from None
        except BaseException:
            os.close(fd)
            raise
        return fd


def _free_name(directory: int, name: str) -> str:
    """``name``, or ``name.<n>`` with the lowest ``n`` not taken: set aside, never overwritten."""
    candidate, n = name, 0
    while True:
        try:
            os.stat(candidate, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return candidate
        n += 1
        candidate = f"{name}.{n}"


def _move_aside(fd: int, name: str, into: _Place) -> None:
    destination = into.open()
    try:
        os.rename(name, _free_name(destination, name), src_dir_fd=fd, dst_dir_fd=destination)
    finally:
        os.close(destination)


def _move_outbox_aside(worktree: Path, into: _Place) -> str:
    """Move the outbox itself, never followed, when it cannot be opened as a directory.

    Only from a parent that is a real directory of the worktree: when the parent is itself a
    link, nothing is moved, since a move reached through it would act on another directory.
    The link then stays, and the change check refuses an attempt whose commit holds a link.

    Returns:
        What was done, for the reason the session's end records.
    """
    base = Path(os.path.realpath(worktree))
    try:
        parent = _open_chain(base, OUTBOX.parent.parts)
    except OSError:
        return "nothing was collected or moved, since its directory is reached through a link"
    try:
        _move_aside(parent, OUTBOX.name, into)
    finally:
        os.close(parent)
    return "it was moved aside, not followed"


def empty_outbox(worktree: Path, run_dir: Path, session_id: str) -> tuple[SetAside, ...]:
    """Move aside whatever the outbox holds before a session starts, and list it.

    Returns:
        What was found, each named with the reason it was not this session's.
    """
    record_path(run_dir, "s", 1, session_id, "x")  # the session id, held to its pattern
    into = _Place(Path(os.path.realpath(run_dir)), (SERIES_DIR, DISCARDED_DIR, session_id))
    listing = _Listing()
    try:
        fd = _open_outbox(worktree)
    except _RefusedError as exc:
        done = _move_outbox_aside(worktree, into)
        listing.add(str(OUTBOX), f"{exc}; {done}")
        return listing.done()
    if fd is None:
        return ()
    try:
        for name in sorted(os.listdir(fd)):
            _move_aside(fd, name, into)
            listing.add(name, "left in the outbox before this session began")
    finally:
        os.close(fd)
    return listing.done()


#: The interpreter's bytecode cache of the writer: written beside it whenever a script imports
#: it, and outside the module, so left in place it would put every recording attempt out of
#: scope at the change check.
WRITER_CACHE = re.compile(r"series_writer\.[A-Za-z0-9_.-]+\.pyc")


def _clear_writer_cache(base: Path, listing: _Listing) -> None:
    """Remove the interpreter's cache of the writer, and nothing else, before the commit.

    Only regular files named as that cache, in ``.physgate/lib/__pycache__`` reached without a
    link; the directory is removed only if that leaves it empty. Anything else there stays,
    and the change check refuses the attempt that committed it.
    """
    lib = WRITER_PATH.parent.parts
    try:
        fd = _open_chain(base, (*lib, "__pycache__"))
    except OSError:
        return
    try:
        for name in sorted(os.listdir(fd)):
            found = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if WRITER_CACHE.fullmatch(name) and stat.S_ISREG(found.st_mode):
                os.unlink(name, dir_fd=fd)
                listing.add(
                    f"{WRITER_PATH.parent}/__pycache__/{name}",
                    "the interpreter's cache of the writer, removed before the commit",
                )
        empty = not os.listdir(fd)
    finally:
        os.close(fd)
    if empty:
        parent = _open_chain(base, lib)
        try:
            os.rmdir("__pycache__", dir_fd=parent)
        finally:
            os.close(parent)


def blob_id(data: bytes, object_format: str) -> str:
    """The id git gives ``data`` as a file's content, in the repository's object format."""
    header = f"blob {len(data)}\0".encode()
    digest = hashlib.sha256 if object_format == "sha256" else hashlib.sha1
    return digest(header + data).hexdigest()


def _code_bytes(base: Path, relative: PurePosixPath) -> bytes:
    """A file of code's bytes, reached from the worktree without following any link."""
    try:
        directory = _open_chain(base, relative.parent.parts)
    except OSError as exc:
        reason = "is reached through a link" if exc.errno in _NOT_A_DIRECTORY else "is missing"
        msg = f"the code file {relative} {reason}"
        raise _RefusedError(msg) from None
    try:
        fd = os.open(relative.name, _NOFOLLOW_READ, dir_fd=directory)
    except OSError as exc:
        msg = f"the code file {relative} cannot be read ({exc.strerror})"
        raise _RefusedError(msg) from None
    finally:
        os.close(directory)
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_size > MAX_CODE_BYTES:
            msg = f"the code file {relative} is not a regular file of at most {MAX_CODE_BYTES}"
            raise _RefusedError(msg)
        return _read_all(fd, MAX_CODE_BYTES)
    finally:
        os.close(fd)


def _read_all(fd: int, bound: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= bound:
        chunk = os.read(fd, min(1 << 20, bound + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Installation:
    """Where the harness's own interpreter is installed.

    It is the only code outside a worktree a record may name.
    """

    prefixes: tuple[Path, ...]
    #: The distribution's own ``sitecustomize`` files, by exact path.
    system_customize: tuple[Path, ...]


def trusted_installation() -> Installation:
    """The harness's own interpreter's installation, from this process alone."""
    major, minor = sys.version_info[:2]
    prefixes = {sys.base_prefix, sys.base_exec_prefix}
    return Installation(
        prefixes=tuple(sorted({Path(os.path.realpath(p)) for p in prefixes if p})),
        system_customize=(Path(f"/etc/python{major}.{minor}/sitecustomize.py"),),
    )


def temporary_roots() -> tuple[Path, ...]:
    """The machine's temporary directories, which every session can write."""
    found = {tempfile.gettempdir(), "/tmp", "/var/tmp", "/dev/shm"}  # noqa: S108 - named to refuse
    return tuple(sorted({Path(os.path.realpath(p)) for p in found if os.path.isdir(p)}))


def _writable_by_the_session(path: str) -> bool:
    """Whether this process's user (the session's) can write ``path`` or replace it.

    A file can be replaced through any directory above it the user can write, so each of
    those is asked too, up to the root.
    """
    if os.access(path, os.W_OK):
        return True
    directory = os.path.dirname(path)
    while True:
        if os.access(directory, os.W_OK):
            return True
        parent = os.path.dirname(directory)
        if parent == directory:
            return False
        directory = parent


#: Files that run in every process of the interpreter: admitted only as the distribution's own.
_CUSTOMISATION_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})


def _identity(path: str | Path) -> tuple[int, int] | None:
    """The file system's own name for ``path`` (device and inode), or ``None`` if it is not."""
    try:
        found = os.stat(path)
    except OSError:
        return None
    return found.st_dev, found.st_ino


def _chain(path: str) -> set[tuple[int, int]]:
    """The identity of ``path`` and of every directory above it, up to the root.

    Compared by identity, not by spelling: a root reached through a link, another case on a
    case-insensitive volume, or ``..`` is the same directory here.
    """
    found: set[tuple[int, int]] = set()
    current = path
    while True:
        identity = _identity(current)
        if identity is not None:
            found.add(identity)
        parent = os.path.dirname(current)
        if parent == current:
            return found
        current = parent


def _environment_code(named: CodeFile, roots: tuple[Path, ...]) -> CodeDigest:
    """``named``, a file of code from outside the worktree, if it is the interpreter's own.

    The harness's own interpreter says where its installation is (:func:`trusted_installation`);
    nothing a record or a session supplies does. A file is admitted only when all of these
    hold, and is then recorded with the record by path and digest, never left out:

    - its path is plain (absolute, normalised, through no link);
    - it lies under none of ``roots`` (the worktree, the session's own directory with its home,
      and the machine's temporary directories), judged by file identity, not by spelling;
    - it lies in the installation: under one of its prefixes, or exactly the distribution's
      ``sitecustomize``; a customisation hook (``sitecustomize``, ``usercustomize``, a ``.pth``
      file) is admitted only as that exact file;
    - neither it nor any directory above it is writable by the session's user, who could
      otherwise replace it;
    - it is a regular file, read through no link, with the digest the writer recorded.

    Raises:
        _RefusedError: any of these does not hold.
    """
    path = named.path
    if os.path.normpath(path) != path or os.path.realpath(path) != path:
        msg = f"code from outside the worktree ran from a path that is not plain: {path}"
        raise _RefusedError(msg)
    chain = _chain(path)
    if any(_identity(root) in chain for root in roots):
        msg = f"code from outside the worktree ran from a place the session can write: {path}"
        raise _RefusedError(msg)
    installed = trusted_installation()
    is_system = any(
        Path(path) == own and _identity(own) is not None and _identity(own) == _identity(path)
        for own in installed.system_customize
    )
    hook = PurePosixPath(path).name in _CUSTOMISATION_NAMES or path.endswith(".pth")
    if hook and not is_system:
        shown = ", ".join(str(own) for own in installed.system_customize)
        msg = (
            f"a customisation hook ran from {path}; only the distribution's own ({shown}) "
            "is admitted"
        )
        raise _RefusedError(msg)
    inside = any(_identity(prefix) in chain for prefix in installed.prefixes)
    if not (inside or is_system):
        msg = (
            "code from outside the worktree ran that is not the interpreter's own "
            f"installation: {path}"
        )
        raise _RefusedError(msg)
    if _writable_by_the_session(path):
        msg = f"code from outside the worktree ran from a file the session's user can write: {path}"
        raise _RefusedError(msg)
    try:
        fd = os.open(path, _NOFOLLOW_READ)
    except OSError as exc:
        msg = f"the code file {path} cannot be read ({exc.strerror})"
        raise _RefusedError(msg) from None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_size > MAX_CODE_BYTES:
            msg = f"the code file {path} is not a regular file of at most {MAX_CODE_BYTES}"
            raise _RefusedError(msg)
        if (found.st_dev, found.st_ino) != _identity(path):
            msg = f"the code file {path} changed while it was read"
            raise _RefusedError(msg)
        data = _read_all(fd, MAX_CODE_BYTES)
    finally:
        os.close(fd)
    digest = hashlib.sha256(data).hexdigest()
    if digest != named.sha256:
        msg = f"{path} changed after the record was written; run the script again"
        raise _RefusedError(msg)
    return CodeDigest(path=path, sha256=digest)


def _in_the_module(path: str, module: PurePosixPath) -> PurePosixPath:
    named = PurePosixPath(path)
    if named.is_absolute() or ".." in named.parts:
        msg = f"code from outside the worktree ran: {path}"
        raise _RefusedError(msg)
    if named != WRITER_PATH and not named.is_relative_to(module):
        msg = f"code from outside the module ran: {path}"
        raise _RefusedError(msg)
    return named


@dataclass(frozen=True)
class _Provenance:
    """What a record's code comes to: the script's bytes, the module code, the environment."""

    script: bytes
    loaded: tuple[CodeBlob, ...]
    environment: tuple[CodeDigest, ...]


def _provenance(
    record: Record,
    base: Path,
    module: PurePosixPath,
    object_format: str,
    roots: tuple[Path, ...],
) -> _Provenance:
    """The script's bytes, the blob of every other module file, and the environment code.

    The script and every file of code the record names in the worktree must be the module's
    (the writer excepted) and unchanged since the record was written. Their blobs are what the
    change check holds the attempt commit to: code the attempt does not commit with these
    bytes cannot stand behind the curve. A file outside the worktree is admitted only as the
    interpreter's own (:func:`_environment_code`), and is recorded.

    Raises:
        _RefusedError: a file lies outside the module and is not admissible as the interpreter's
            own, cannot be read, or changed since the record was written.
    """
    script = _in_the_module(record.producer.script.path, module)
    if script == WRITER_PATH:
        msg = "a record names the writer as its script"
        raise _RefusedError(msg)
    script_bytes = b""
    loaded: dict[str, CodeBlob] = {}
    environment: dict[str, CodeDigest] = {}
    for named in (record.producer.script, *record.producer.loaded):
        if named is not record.producer.script and PurePosixPath(named.path).is_absolute():
            environment[named.path] = _environment_code(named, roots)
            continue
        relative = _in_the_module(named.path, module)
        data = _code_bytes(base, relative)
        if hashlib.sha256(data).hexdigest() != named.sha256:
            msg = f"{relative} changed after the record was written; run the script again"
            raise _RefusedError(msg)
        if relative == script:
            script_bytes = data
        else:
            loaded[str(relative)] = CodeBlob(path=str(relative), blob=blob_id(data, object_format))
    return _Provenance(
        script=script_bytes,
        loaded=tuple(loaded[path] for path in sorted(loaded)),
        environment=tuple(environment[path] for path in sorted(environment)),
    )


def _read_entry(fd: int, name: str) -> bytes:
    found = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(found.st_mode):
        msg = "not a regular file"
        raise _RefusedError(msg)
    try:
        entry = os.open(name, _NOFOLLOW_READ, dir_fd=fd)
    except OSError as exc:
        msg = f"cannot be opened ({exc.strerror})"
        raise _RefusedError(msg) from None
    try:
        held = os.fstat(entry)
        if not stat.S_ISREG(held.st_mode):
            msg = "not a regular file"
            raise _RefusedError(msg)
        if held.st_nlink != 1:
            msg = "has another name, through which it could be changed after it is sealed"
            raise _RefusedError(msg)
        if held.st_size > MAX_FILE_BYTES:
            msg = f"holds more than {MAX_FILE_BYTES} bytes"
            raise _RefusedError(msg)
        return _read_all(entry, MAX_FILE_BYTES)
    finally:
        os.close(entry)


def _write_sealed(into: _Place, name: str, data: bytes) -> None:
    """A new file ``name`` holding ``data`` in ``into``, synced, and its directory synced."""
    directory = into.open()
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(name, flags, 0o644, dir_fd=directory)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


def collect(
    worktree: Path,
    *,
    module_dir: str,
    run_dir: Path,
    subtask_id: str,
    attempt: int,
    session_id: str,
    object_format: str,
    discarded_before: tuple[SetAside, ...] = (),
    writable_roots: tuple[Path, ...] | None = None,
) -> SessionSeries:
    """Take every entry out of the outbox: seal what holds, set the rest aside, list both.

    ``discarded_before`` is what was moved aside before the session began; it heads the
    discarded list, under the same bound. ``writable_roots`` are the places the session can
    write besides its worktree (its home and temporary directories); by default the
    machine's temporary directories. Code a record names from outside the worktree is
    admitted only from outside all of them.

    Raises:
        RecordRefusedError: an identifier is not one the run could have written.
    """
    module = PurePosixPath(module_dir)
    if module.is_absolute() or ".." in module.parts or not module.parts:
        msg = "a module directory is a relative path inside the worktree"
        raise RecordRefusedError(msg, module_dir=module_dir)
    base = Path(os.path.realpath(worktree))
    chosen = temporary_roots() if writable_roots is None else tuple(writable_roots)
    roots = (base, *(Path(os.path.realpath(r)) for r in chosen))
    record_path(run_dir, subtask_id, attempt, session_id, "x")  # every id held to its pattern
    run_base = Path(os.path.realpath(run_dir))
    sealed_at = _Place(run_base, (SERIES_DIR, subtask_id, str(attempt), session_id))
    refused_at = _Place(run_base, (SERIES_DIR, REFUSED_DIR, subtask_id, str(attempt), session_id))
    discarded_at = _Place(run_base, (SERIES_DIR, DISCARDED_DIR, session_id))
    refused, discarded = _Listing(), _Listing()
    for earlier in discarded_before:
        discarded.add(earlier.name, earlier.reason)
    _clear_writer_cache(base, discarded)
    try:
        fd = _open_outbox(worktree)
    except _RefusedError as exc:
        done = _move_outbox_aside(worktree, refused_at)
        refused.add(str(OUTBOX), f"{exc}; {done}")
        return SessionSeries(refused=refused.done(), discarded=discarded.done())
    if fd is None:
        return SessionSeries(discarded=discarded.done())
    records: list[SealedRecord] = []
    total = 0
    try:
        for name in sorted(os.listdir(fd)):
            if name.startswith(".") and name.endswith(".tmp"):
                _move_aside(fd, name, discarded_at)
                discarded.add(name, "a writer's temporary file, never renamed into place")
                continue
            try:
                if not _RECORD_FILE.fullmatch(name):
                    msg = "not a record's name (<id>.json, the id in lower case)"
                    raise _RefusedError(msg)
                data = _read_entry(fd, name)
                if len(records) >= MAX_RECORDS_PER_SESSION:
                    msg = f"over the session's bound of {MAX_RECORDS_PER_SESSION} records"
                    raise _RefusedError(msg)
                if total + len(data) > MAX_SESSION_BYTES:
                    msg = f"over the session's bound of {MAX_SESSION_BYTES} bytes of records"
                    raise _RefusedError(msg)
                try:
                    record = parse_record(data)
                except RecordRefusedError as exc:
                    raise _RefusedError(str(exc)) from None
                if f"{record.id}.json" != name:
                    msg = (
                        f"the file is named for another record than the one it holds ({record.id})"
                    )
                    raise _RefusedError(msg)
                found = _provenance(record, base, module, object_format, roots)
            except _RefusedError as exc:
                _move_aside(fd, name, refused_at)
                refused.add(name, str(exc))
                continue
            _write_sealed(sealed_at, name, data)
            os.unlink(name, dir_fd=fd)
            total += len(data)
            sealed = seal(data)
            records.append(
                SealedRecord(
                    record_id=record.id,
                    sha256=sealed.sha256,
                    length=sealed.length,
                    script=str(PurePosixPath(record.producer.script.path)),
                    script_sha256=hashlib.sha256(found.script).hexdigest(),
                    script_blob=blob_id(found.script, object_format),
                    loaded=found.loaded,
                    environment=found.environment,
                )
            )
    finally:
        os.close(fd)
    return SessionSeries(records=tuple(records), refused=refused.done(), discarded=discarded.done())
