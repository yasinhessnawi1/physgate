"""A design review's session, recorded beside the decomposition's rounds while it runs.

``decompose`` writes no event log before its opening, so a review session's spawn is on no run
record, and a resume's stop never finds it. While the review runs, its session's id, pid and start
time stand in a file of the run directory's, beneath the decomposition: written at the spawn, before
the session runs anything, and removed once the review is over, so a decomposition that ends as it
should leaves nothing new. A ``decompose`` killed during the review leaves the file. The next
command on that directory (``decompose``, which then refuses it as before, or ``run``) stops the
session and says so. It signals the pid only while it is that session's: the start time recorded
and its own command line, which carries the session id. The file is the orchestrator's: a review
session reads only its packet, beneath the review root.

The file stays until the round's end line is journalled, so a kill between the review's end and that
line leaves it too. The next command then scans every stream the review's spawns wrote for the
held-out canaries the file names: what the review showed is otherwise on no record. An exposure is
written to a file of its own beside it, synced, and every later command on the directory names it
and refuses.

Not synced: the file guards against this process being killed, and a machine that goes down takes
the session with it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.credentials import remove_secrets
from physgate.orchestrator.dispatch import read_stream_file, redact, review_streams
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.ports import SpawnHook
from physgate.orchestrator.processes import is_session, stop_tree
from physgate.reviewers.places import SESSION_DIRNAME

#: Where a design review's session is recorded while it runs, beneath the run directory.
REVIEW_SESSION = PurePosixPath("decomposition", "review_session.json")
#: Where a held-out exposure a killed ``decompose``'s review showed is recorded, once found.
REVIEW_EXPOSED = PurePosixPath("decomposition", "review_exposed.json")


def review_spawned(
    run_dir: Path, *, review_root: Path | None = None, canaries: Iterable[str] = ()
) -> SpawnHook:
    """The hook that records a review session at its spawn, while it is held before it runs.

    The record holds what a later command needs to scan the session's streams without the run's
    configuration, which a decomposition killed before its opening never wrote: where the review's
    session directory is, how many times it was spawned, and the held-out canaries. It is the
    orchestrator's file, removed once the round's end is journalled.
    """
    held_out = sorted(set(canaries))

    def spawned(session_id: str, pid: int, started: str) -> None:
        path = run_dir / REVIEW_SESSION
        path.parent.mkdir(parents=True, exist_ok=True)
        spawns = 1
        try:
            earlier = json.loads(path.read_text())
            if earlier.get("session_id") == session_id:
                spawns = int(earlier["spawns"]) + 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        # Named as the reviewer named it (``places.review_dir``), from the id it spawned.
        where = str(review_root / session_id / SESSION_DIRNAME) if review_root is not None else None
        record = {
            "session_id": session_id,
            "pid": pid,
            "started": started,
            "spawns": spawns,
            "session_dir": where,
            "held_out_canaries": held_out,
        }
        written = path.with_name(f".{path.name}.part")
        written.write_text(json.dumps(record))
        # A repair resume of the same review is spawned again: its record replaces the first.
        os.replace(written, path)

    return spawned


def review_over(run_dir: Path) -> None:
    """Remove the review session's record: its round's end is journalled, and nothing of it runs."""
    (run_dir / REVIEW_SESSION).unlink(missing_ok=True)


@dataclass(frozen=True)
class LeftReview:
    """What the next command found of a review session a killed ``decompose`` left."""

    #: What was done, for the operator; ``None`` if nothing was left.
    said: str | None
    #: The review's streams showed held-out material, now or at an earlier command.
    exposed: bool


def stop_left_review(run_dir: Path, secrets: Iterable[str] = ()) -> LeftReview:
    """Stop the review session a killed ``decompose`` left, scan its streams, and say so.

    The record is removed once the session is stopped, or once its pid is not that session's, and
    its streams are scanned for the held-out canaries the record names. An exposure is written to
    its own file first, synced, so every later command names it again. An unreadable record, a
    process table that cannot be read, or a stream that cannot be read keeps the record. Once
    nothing of it runs, its credential files are removed and its streams redacted of ``secrets``,
    as a resume does for its own leftovers, before they are read.
    """
    found = _stop_and_scan(run_dir, tuple(secrets))
    # Read once the scan is done: an exposure this command found, or an earlier one recorded.
    exposed = (run_dir / REVIEW_EXPOSED).is_file()
    if exposed:
        named = _exposed_session(run_dir)
        told = (
            f"the design review session {named} a killed decompose left showed held-out "
            "material: the held-out tier counts as exposed, and nothing more runs in this directory"
        )
        found = f"{found}; {told}" if found else told
    return LeftReview(found, exposed)


def _exposed_session(run_dir: Path) -> str:
    try:
        return str(json.loads((run_dir / REVIEW_EXPOSED).read_text())["session_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return "(its record cannot be read)"


def _stop_and_scan(run_dir: Path, secrets: tuple[str, ...]) -> str | None:
    path = run_dir / REVIEW_SESSION
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
        session_id = str(record["session_id"])
        pid = int(record["pid"])
        started = str(record["started"])
        spawns = int(record["spawns"])
        where = record["session_dir"]
        canaries = frozenset(str(c) for c in record["held_out_canaries"])
        if not isinstance(where, str) or spawns < 1:
            raise TypeError(type(where).__name__)
    except (OSError, ValueError, KeyError, TypeError):
        return (
            f"the record {path} of a design review session a killed decompose left cannot be "
            "read; nothing was signalled, and its streams are not scanned"
        )
    try:
        if is_session(pid, started, session_id):
            killed = stop_tree(pid, started)
            said = (
                f"stopped the design review session {session_id} (pid {pid}) a killed decompose "
                f"left running; {killed} process(es) needed SIGKILL"
            )
        else:
            said = (
                f"the design review session {session_id} (pid {pid}) a killed decompose left is "
                "not running; nothing was signalled"
            )
    except OSError as exc:
        return (
            f"the design review session {session_id} (pid {pid}) a killed decompose left could "
            f"not be checked: {exc!r}; nothing was signalled"
        )
    # Nothing of it runs now, so it needs no credential: a killed decompose never removed it, and
    # its streams were never redacted. Every stream its spawns wrote is final, and scanned once.
    session = Path(where)
    try:
        remove_secrets(session / "state", session / "config")
        for name in review_streams(spawns):
            for secret in secrets:
                redact(session / name, secret)
        shown = any(
            canary_seen(read_stream_file(Path(where) / name), canaries) is not None
            for name in review_streams(spawns)
        )
    except InvocationError as exc:
        return f"{said}; its directory cannot be read ({exc}), so the record is kept"
    if shown:
        _synced(run_dir / REVIEW_EXPOSED, json.dumps({"session_id": session_id}).encode())
    path.unlink(missing_ok=True)
    return said


def _synced(path: Path, data: bytes) -> None:
    """Write ``path`` whole and sync it before returning: a kill after keeps it."""
    written = path.with_name(f".{path.name}.part")
    with written.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(written, path)
