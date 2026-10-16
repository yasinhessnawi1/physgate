"""Reading one sealed series record: bounded, read-only, and held to its seal.

A record lives at ``<run_dir>/series/<subtask>/<attempt>/<session>/<record id>.json``.
The path is always built here from validated identifiers, never taken from a record or
a log line, because a forged line could otherwise name any file in the run directory.
Every read is held to the seal the session's end recorded (its digest and length), so a
record changed after it was sealed is refused, not served. There is no way to read a
record without a seal: a file nothing sealed is never read.

**Bounded.** The file's size is taken from the open descriptor and compared with the seal
and with the format's byte bound before a byte is read, and at most one byte more than
the bound is ever read.

**Read-only, and judged by its path.** The reader opens one file, for reading, by its
absolute path. It never follows a link (the final name is opened without following one,
and the path must already be its own real path, so no directory on the way is a link),
refuses anything but a regular file with one name, writes nothing, starts no thread and
no process. That is what lets the operator UI call it inside its read guard, which judges
every open by the path it names, so the UI needs no parser of its own.

**What it cannot see.** The check that no directory on the way is a link and the open
that follows it are two steps; a process running as the same user that swaps a directory
for a link between them would have the open follow it. The seal still holds: whatever is
opened must be the sealed bytes.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from pathlib import Path

from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.trajectory import Seal
from physgate.series.exceptions import RecordRefusedError, RecordTamperedError
from physgate.series.record import MAX_FILE_BYTES, NAME_PATTERN, Record, parse_record

#: The directory beneath a run that holds its sealed records.
SERIES_DIR = "series"

_SUBTASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RECORD = re.compile(NAME_PATTERN)


def record_path(
    run_dir: Path, subtask_id: str, attempt: int, session_id: str, record_id: str
) -> Path:
    """Where the sealed record ``record_id`` of one session of one attempt lives.

    Raises:
        RecordRefusedError: an identifier is not one the run could have written.
    """
    for value, pattern, what in (
        (subtask_id, _SUBTASK, "subtask id"),
        (session_id, _SESSION, "session id"),
        (record_id, _RECORD, "record id"),
    ):
        if not pattern.match(value):
            msg = f"the {what} is not a plain identifier"
            raise RecordRefusedError(msg, value=value[:64])
    if isinstance(attempt, bool) or not 1 <= attempt <= REPAIR_BUDGET:
        msg = f"an attempt is a number from 1 to {REPAIR_BUDGET}"
        raise RecordRefusedError(msg, attempt=str(attempt))
    return Path(run_dir) / SERIES_DIR / subtask_id / str(attempt) / session_id / f"{record_id}.json"


def read_record(path: Path, seal: Seal) -> Record:
    """The record at ``path``, if its bytes are the ones ``seal`` names.

    Raises:
        RecordTamperedError: the file is gone, is not the sealed bytes, or is reached
            through a link, or is not a regular file with one name.
        RecordRefusedError: the sealed bytes are not a record this format admits.
    """
    if not Path(path).is_absolute():
        msg = "a record is read by its absolute path"
        raise RecordRefusedError(msg, path=str(path))
    spelt = os.path.normpath(path)
    if os.path.realpath(spelt) != spelt:
        msg = "a sealed record is reached through a link"
        raise RecordTamperedError(msg, path=spelt)
    try:
        fd = os.open(spelt, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        msg = "a sealed record is gone"
        raise RecordTamperedError(msg, path=spelt) from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = "a sealed record is a link"
            raise RecordTamperedError(msg, path=spelt) from None
        raise
    try:
        data = _read_bounded(fd, spelt, seal)
    finally:
        os.close(fd)
    found = hashlib.sha256(data).hexdigest()
    if found != seal.sha256:
        msg = "a record is not what it was when its session ended"
        raise RecordTamperedError(msg, path=spelt, sealed=seal.sha256, found=found)
    return parse_record(data)


def _read_bounded(fd: int, path: str, seal: Seal) -> bytes:
    """At most one byte more than the bound, after the descriptor is held to the seal."""
    found = os.fstat(fd)
    if not stat.S_ISREG(found.st_mode):
        msg = "a sealed record is not a regular file"
        raise RecordTamperedError(msg, path=path)
    if found.st_nlink != 1:
        msg = "a sealed record has another name, through which it could be changed"
        raise RecordTamperedError(msg, path=path, links=str(found.st_nlink))
    if found.st_size != seal.length:
        msg = "a record is not the length it was when its session ended"
        raise RecordTamperedError(msg, path=path, sealed=str(seal.length), found=str(found.st_size))
    if found.st_size > MAX_FILE_BYTES:
        msg = f"a record holds at most {MAX_FILE_BYTES} bytes"
        raise RecordRefusedError(msg, path=path, bytes=str(found.st_size))
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_FILE_BYTES:
        chunk = os.read(fd, min(1 << 20, MAX_FILE_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)
