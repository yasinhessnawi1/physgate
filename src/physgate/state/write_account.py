"""The run's write account: what each orchestrator process wrote to the run's held records.

A held record (the event log, the task ledger, the approval queue) is written in a form anyone
can write: a line names what it says, and a line forged in that form says anything. So no line
is taken as an orchestrator's for what it says. Before every append, the record's writer appends
one line here and syncs it: the record's name, the file's identity, the offset it writes at, the
number of bytes and their digest. Only then does it write the record. A resume holds each record,
from its first byte to where it opened it, to these lines (``held_records.unaccounted``): bytes no
line names are no orchestrator's.

A line here whose bytes never followed is a write its writer died in: written first, it names
bytes the record does not hold, and covers nothing. The account also names each role session
whose end its run settled (stopped, and checked after the stop) before any git call on its
attempt: a resume never runs that session's end check again, which would put back the run's own
writes after it.

The account is itself a held record, compared by every session's sentinel and never written by
one, held by its writer as the others are. Its own lines are written by no account.

Named limit (the same-user limit): a process of the session's user that appends to a held record
and here a line naming those bytes, or a settle line, writes as an orchestrator does. Under the OS
layer the run directory is outside every session's writable set, which rules that out.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from physgate.state.held_file import HeldFile

#: The account's name in its run directory, beside the records it names.
ACCOUNT_NAME = "writes.jsonl"
_SHA256 = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class Intent:
    """One append its writer was about to make: which record, where, how much, and its digest."""

    record: str
    identity: tuple[int, int]
    offset: int
    length: int
    sha256: str


@dataclass(frozen=True)
class Settled:
    """A role session whose end its run settled before any git call on its attempt."""

    session_id: str
    subtask_id: str
    attempt: int


Entry = Intent | Settled


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(repr(value))
    return value


def _entry(raw: object) -> Entry:
    """One line of the account, or ``ValueError`` if it is of no form the account writes."""
    if not isinstance(raw, dict):
        raise ValueError(type(raw).__name__)
    if set(raw) == {"settled", "subtask_id", "attempt"}:
        sid, subtask = raw["settled"], raw["subtask_id"]
        if not (isinstance(sid, str) and sid and isinstance(subtask, str) and subtask):
            raise ValueError("a settle line names no session")
        return Settled(sid, subtask, _count(raw["attempt"]))
    if set(raw) != {"record", "identity", "offset", "length", "sha256"}:
        raise ValueError(sorted(raw))
    record, identity, digest = raw["record"], raw["identity"], raw["sha256"]
    if not (isinstance(record, str) and record and "/" not in record):
        raise ValueError(repr(record))
    if not (isinstance(identity, list) and len(identity) == 2):
        raise ValueError(repr(identity))
    if not (isinstance(digest, str) and len(digest) == 64 and set(digest) <= _SHA256):
        raise ValueError(repr(digest))
    return Intent(
        record,
        (_count(identity[0]), _count(identity[1])),
        _count(raw["offset"]),
        _count(raw["length"]),
        digest,
    )


def _read(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, 1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def parse_account(data: bytes) -> tuple[tuple[Entry, ...], int, str | None]:
    """The account's complete lines, where they end, and what of it is of no form, if any.

    A final line with no terminator is a write its writer died in, and is not read.
    """
    entries: list[Entry] = []
    end = 0
    while (newline := data.find(b"\n", end)) >= 0:
        line = data[end:newline]
        try:
            entries.append(_entry(json.loads(line)))
        except (ValueError, TypeError) as exc:
            return tuple(entries), end, f"the line at byte {end} is of no form it writes: {exc}"
        end = newline + 1
    return tuple(entries), end, None


def read_account(path: Path) -> tuple[tuple[Entry, ...], str | None]:
    """The account's lines as they are now, read without following a link; and why not, if not."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return (), "the run keeps no write account"
    except OSError as exc:
        return (), f"the write account cannot be read: {exc!r}"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return (), "the write account is not a regular file"
        entries, _end, problem = parse_account(_read(fd))
    finally:
        os.close(fd)
    return entries, problem


#: The account each run directory's open record writes through, in this process.
_OPEN: dict[str, WriteAccount] = {}


def account_of(run_dir: Path) -> WriteAccount | None:
    """The account this process's open record of ``run_dir`` writes through, if one is open."""
    return _OPEN.get(os.path.realpath(run_dir))


class WriteAccount:
    """One orchestrator process's writer of its run's write account."""

    def __init__(self, path: Path) -> None:
        """Open the account, cutting a torn final line, and read what earlier processes wrote.

        The account is opened before any record it names, so its lines then are every earlier
        process's and none of this one's.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        try:
            data = _read(fd)
            earlier, end, problem = parse_account(data)
            if problem is None and end != len(data):
                os.ftruncate(fd, end)
            self.held = HeldFile(self.path, fd)
        except BaseException:
            os.close(fd)
            raise
        self._fd: int | None = fd
        #: What earlier processes wrote here, before this one opened it.
        self.earlier: tuple[Entry, ...] = earlier
        #: What of the account as found is of no form it writes, if any: nothing it names counts.
        self.problem: str | None = problem
        _OPEN[os.path.realpath(self.path.parent)] = self

    def _write(self, line: dict[str, object]) -> None:
        if self._fd is None:
            msg = "the write account is closed"
            raise ValueError(msg)
        payload = json.dumps(line, separators=(",", ":")).encode() + b"\n"
        self.held.require_current()
        os.write(self._fd, payload)
        os.fsync(self._fd)
        self.held.wrote(payload)

    def intend(self, record: Path, identity: tuple[int, int], offset: int, payload: bytes) -> None:
        """Name ``payload``, about to be appended to ``record`` at ``offset``, before it is.

        Raises:
            RecordMovedError: the account is no longer the file this writer holds; nothing is
                written, here or to the record.
        """
        self._write(
            {
                "record": record.name,
                "identity": list(identity),
                "offset": offset,
                "length": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    def settle(self, session_id: str, subtask_id: str, attempt: int) -> None:
        """Name a role session whose end its run settled, before any git call on its attempt."""
        self._write({"settled": session_id, "subtask_id": subtask_id, "attempt": attempt})

    def close(self) -> None:
        """Release the account. Idempotent."""
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            key = os.path.realpath(self.path.parent)
            if _OPEN.get(key) is self:
                del _OPEN[key]
