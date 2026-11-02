"""Whether the run's held records are what orchestrators wrote, as their write account names it.

A role session's sentinel records the run's held records when the session starts (its event log,
task ledger, approval queue and write account) and never writes them. A resume that finds the
session left by a killed orchestrator holds each record, before it acts on anything it says:

- to its own writer: the file is the one it holds, and after what it found there it holds
  exactly what it has written since;
- to the session's start: the same file, beginning with the bytes it held then, in the same mode;
- to its one name: a second name for the file, anywhere, is a change (a session's worktree can
  hold it, and an attempt's commit then would);
- and, from its first byte to where this process opened it, to the run's write account: every
  byte there is one an earlier orchestrator process named in the account before it wrote it, in
  order (:func:`unaccounted`). No line is taken as an orchestrator's for what it says, so a line
  forged in the record's form after the session started, whatever it names, is no orchestrator's.

Named limit (the same-user limit): a process of the session's user that appends to a held record
and to the write account a line naming those bytes, with the record's identity, offset, length
and digest, writes as an orchestrator does. Under the OS layer the run directory is outside every
session's writable set, which rules that out.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path

from physgate.orchestrator.ports import RecordAtStart
from physgate.state.held_file import HeldFile, identity_of
from physgate.state.write_account import Entry, Intent


def _begins_with(path: Path, size: int, sha256: str) -> bool:
    """Whether the regular file at ``path`` begins with ``size`` bytes of digest ``sha256``."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        digest = hashlib.sha256()
        left = size
        while left > 0 and (chunk := os.read(fd, min(left, 1 << 20))):
            digest.update(chunk)
            left -= len(chunk)
        return left == 0 and digest.hexdigest() == sha256
    finally:
        os.close(fd)


def unaccounted(held: HeldFile, entries: Sequence[Entry], problem: str | None) -> str | None:
    """Why the record's bytes before this process opened it are not all an orchestrator's.

    ``entries`` are the account's lines as this process found them, before it wrote any;
    ``problem`` is what of the account is of no form, if anything. The record's lines there are
    walked in order from byte 0: a line at the walk's place whose bytes are there with its digest
    moves it on; a line there whose bytes are not is a write its writer died in, and covers
    nothing; a line anywhere else, or on another file, refuses. The walk must end where this
    process opened the record.
    """
    if problem is not None:
        return problem
    try:
        fd = os.open(held.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        return f"it cannot be read: {exc!r}"
    try:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) != held.identity:
            return "the path no longer names the file this process writes"
        at = 0
        for line in (e for e in entries if isinstance(e, Intent) and e.record == held.path.name):
            if line.identity != held.identity:
                return (
                    f"the write account names an orchestrator's write at byte {line.offset} to "
                    "another file"
                )
            if line.offset != at:
                return (
                    f"the write account names a write at byte {line.offset} where the "
                    f"orchestrators' writes had reached byte {at}"
                )
            end = at + line.length
            if end <= held.opened:
                found = hashlib.sha256(os.pread(fd, line.length, at)).hexdigest()
                if found == line.sha256:
                    at = end
        if at != held.opened:
            return (
                f"{held.opened - at} bytes from byte {at} on, before this process opened it, are "
                "no write the write account names"
            )
    finally:
        os.close(fd)
    return None


def second_names(identities: Iterable[tuple[int, int]], roots: Iterable[Path]) -> list[str]:
    """Every path under ``roots`` that names one of the files ``identities`` gives, unfollowed."""
    wanted = set(identities)
    found: list[str] = []
    for root in roots:
        for top, dirs, files in os.walk(root):
            for name in (*dirs, *files):
                path = os.path.join(top, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) in wanted:
                    found.append(path)
    return sorted(found)


def record_change(
    start: RecordAtStart, held: HeldFile | None, *, unaccounted_why: str | None
) -> str | None:
    """Why the record is not what the session's start, this process and the account explain.

    ``held`` is this process's writer of the record, ``None`` if it has none; ``unaccounted_why``
    is :func:`unaccounted` for it (``None`` for the account itself, which no account names).
    """
    if held is None:
        return "this process holds no writer of it"
    if start.size < 0:
        return "it was not a regular file when the session started"
    if start.identity is not None and start.identity != held.identity:
        return "it is not the file the session started with"
    if identity_of(held.path) != held.identity:
        return "the path no longer names the file this process writes"
    now = os.lstat(held.path)
    if now.st_nlink != 1:
        return f"the file has {now.st_nlink} names"
    if start.mode is not None and stat.S_IMODE(now.st_mode) != start.mode:
        return (
            f"its mode is {stat.S_IMODE(now.st_mode):o} where it was {start.mode:o} when the "
            "session started"
        )
    if not held.own_tail_holds():
        return "it does not hold, after what this process found, exactly what this process wrote"
    if start.identity is not None and not _begins_with(held.path, start.size, start.sha256):
        return "the bytes it held when the session started are not all there as they were"
    if held.opened < start.size:
        return "it is shorter than it was when the session started"
    return unaccounted_why
