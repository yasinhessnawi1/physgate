"""Whether the run's held records are what a leftover's start and the resume's own writes explain.

A role session's sentinel records the run's held records when the session starts (its event log,
task ledger and approval queue) and never writes them. A resume that finds the session left by a
killed orchestrator holds each record to that start and to its own writer before it acts on
anything the record says:

- the file is the one the session started with, and the one the resume's writer holds;
- it still begins with exactly the bytes it held then;
- what follows them is what the resume's writer read when it opened the file and has written
  since, and nothing else: the writer holds the path to its size and identity at every write, and
  its own bytes to their digest here;
- and when no orchestrator outlived the session (the record names no end of it, no finding and
  no incident after its spawn, and no later process's start, and the session is not one its run
  ended and died after), nothing at all came between the session's start and the resume's open:
  its run wrote nothing while it ran, so whatever is there was written by something else. An
  earlier resume that wrote its first lines and stopped short of ending the session (killed, or
  refused at the session's check) is such a later process: its lines start with its installation's
  check, which a run writes only when its command starts.

Named limit (the same-user limit): a session's user can write the record as the orchestrator does.
A line forged in the record's form after the session started, which names the session's end, a
finding, an incident or a process's start, makes its run look as though an orchestrator outlived
the session, and the lines between its start and the resume's open are then taken as that
orchestrator's. Only the OS layer, which confines what a session's processes can write, rules that
out.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path

from physgate.orchestrator.events import (
    Event,
    FindingsRecorded,
    Incident,
    InstallChecked,
    LeftoverRead,
    SessionEnded,
    SessionSpawned,
)
from physgate.orchestrator.ports import RecordAtStart
from physgate.state.held_file import HeldFile, identity_of


def outlived(session_id: str, events: Sequence[Event]) -> bool:
    """Whether the record shows an orchestrator went on after the session's spawn.

    ``events`` are the lines the record held before this process wrote any: an end or a read of
    the session, or an incident, a finding or a later process's start (its installation's check)
    after its spawn.
    """
    spawn = next(
        (e.seq for e in events if isinstance(e, SessionSpawned) and e.session_id == session_id),
        None,
    )
    return spawn is not None and any(
        (isinstance(e, SessionEnded | LeftoverRead) and e.session_id == session_id)
        or (isinstance(e, Incident | FindingsRecorded | InstallChecked) and e.seq > spawn)
        for e in events
    )


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


def record_change(
    start: RecordAtStart, held: HeldFile | None, *, outlived_by_run: bool
) -> str | None:
    """Why the record is not what the session's start and this process's writes explain, if not.

    ``held`` is this process's writer of the record, ``None`` if it has none; ``outlived_by_run``
    is :func:`outlived`, or that the session is one its own run ended and died after.
    """
    if held is None:
        return "this process holds no writer of it"
    if start.size < 0:
        return "it was not a regular file when the session started"
    if start.identity is not None and start.identity != held.identity:
        return "it is not the file the session started with"
    if identity_of(held.path) != held.identity:
        return "the path no longer names the file this process writes"
    if not held.own_tail_holds():
        return "it does not hold, after what this process found, exactly what this process wrote"
    if start.identity is not None and not _begins_with(held.path, start.size, start.sha256):
        return "the bytes it held when the session started are not all there as they were"
    if held.opened < start.size:
        return "it is shorter than it was when the session started"
    if not outlived_by_run and held.opened != start.size:
        added = held.opened - start.size
        return (
            f"{added} bytes were added after the session started and before this process opened "
            "it, and the session's own run wrote nothing while the session ran"
        )
    return None
