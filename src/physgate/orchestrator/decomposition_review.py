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

The exposure register reads what a killed ``decompose`` left without a command on the directory:
the exposure file, and a review record no command has scanned yet, whose streams it scans as the
next command does (:func:`review_record`, :func:`streams_show`), writing and signalling nothing.
Which tier versions that exposure marks is read from the held-out tiers' digests the
decomposition recorded, synced, before any review session was spawned (:func:`record_held_out`):
a decomposition writes no run configuration before its opening.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from physgate.orchestrator import dispatch
from physgate.orchestrator.canaries import canary_seen
from physgate.orchestrator.credentials import remove_secrets
from physgate.orchestrator.dispatch import redact, review_streams
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.ports import SpawnHook
from physgate.orchestrator.processes import is_session, stop_tree
from physgate.orchestrator.session_ends import PLAN_REVIEW_SPAWN
from physgate.orchestrator.session_files import FileRefused, read_beneath
from physgate.reviewers.places import SESSION_DIRNAME, review_root_path

#: Where a design review's session is recorded while it runs, beneath the run directory: the
#: record every reader of the run takes as the review still open (``session_ends``).
REVIEW_SESSION = PLAN_REVIEW_SPAWN
#: Where a held-out exposure a killed ``decompose``'s review showed is recorded, once found.
REVIEW_EXPOSED = PurePosixPath("decomposition", "review_exposed.json")
#: The digests of the held-out tiers a reviewed decomposition was given, recorded before its review.
HELD_OUT_TIERS = PurePosixPath("decomposition", "held_out_tiers.json")


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
        where = (
            str(review_root_path(review_root) / session_id / SESSION_DIRNAME)
            if review_root is not None
            else None
        )
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


def review_over(run_dir: Path, *, scanned: bool = True) -> None:
    """Remove the review session's record: its round's end is journalled, and nothing of it runs.

    ``scanned`` false: the review ended by raising, or the round went void, so nothing scanned its
    streams. They are scanned now, from the record, before it goes, as the next command would
    scan them: one that showed a canary is written to the exposure file first, synced; one that
    cannot be read keeps the record, for the exposure register and the next command to read.
    """
    path = run_dir / REVIEW_SESSION
    if not scanned:
        try:
            record = review_record(run_dir)
        except ReviewRecordError:
            return  # kept: whoever reads it next refuses it as it is
        if record is not None:
            try:
                shown = streams_show(record)
            except InvocationError:
                return  # kept: a stream that cannot be read is never read as clean
            if shown:
                _synced(
                    run_dir / REVIEW_EXPOSED, json.dumps({"session_id": record.session_id}).encode()
                )
    path.unlink(missing_ok=True)


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
    return exposed_review(run_dir) or "(its record cannot be read)"


@dataclass(frozen=True)
class ReviewRecord:
    """A review session's record, as its spawn wrote it beside the decomposition's rounds."""

    session_id: str
    pid: int
    started: str
    spawns: int
    #: The review's session directory, beneath the review root.
    session_dir: Path
    canaries: frozenset[str]


class ReviewRecordError(ValueError):
    """A review session's record is there and cannot be read."""


def review_record(run_dir: Path) -> ReviewRecord | None:
    """The record of the review session running, or left by a killed ``decompose``; ``None``.

    Raises:
        ReviewRecordError: the record is there and cannot be read.
    """
    path = run_dir / REVIEW_SESSION
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
        where = record["session_dir"]
        found = ReviewRecord(
            session_id=str(record["session_id"]),
            pid=int(record["pid"]),
            started=str(record["started"]),
            spawns=int(record["spawns"]),
            session_dir=Path(where) if isinstance(where, str) else Path(),
            canaries=frozenset(str(c) for c in record["held_out_canaries"]),
        )
        if not isinstance(where, str) or found.spawns < 1:
            raise TypeError(type(where).__name__)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReviewRecordError(str(path)) from exc
    return found


#: Why a review stream that is there cannot be read, by kind; never what or where it is.
STREAM_REFUSALS: dict[str, str] = {
    "absent": "gone",
    "file": "a link or not a plain file",
    "directory": "on a directory on its way that is a link or not a directory",
    "too_large": "over the size bound",
}


@dataclass(frozen=True)
class StreamRead:
    """One stream a review's spawn wrote, read once without following a link: its bytes, or why not.

    ``refused`` is a key of :data:`STREAM_REFUSALS`: ``absent`` where it is gone (it, or a
    directory on its way, is not there), otherwise why a stream that is there is not read.
    """

    name: str
    data: bytes | None
    refused: str | None = None


def read_review_streams(record: ReviewRecord) -> list[StreamRead]:
    """Every stream the review's spawns wrote, each read once as the reviewer reads its own.

    Reached beneath the review root as :func:`~physgate.orchestrator.dispatch.read_stream_file`
    reaches one, and refused for the same kinds, each told apart.
    """
    found = []
    for name in review_streams(record.spawns):
        path = record.session_dir / name
        anchor = path.parent.parent.parent
        names = (path.parent.parent.name, path.parent.name, path.name)
        try:
            data = read_beneath(anchor, names, limit=dispatch.MAX_SESSION_FILE_BYTES)
        except FileRefused as refused:
            if refused.kind == "absent":
                kind = "absent"
            elif refused.kind == "too_large":
                kind = "too_large"
            else:
                kind = "directory" if refused.directory else "file"
            found.append(StreamRead(name, None, kind))
            continue
        except ValueError:
            found.append(StreamRead(name, None, "directory"))
            continue
        except OSError:
            found.append(StreamRead(name, None, "file"))
            continue
        found.append(StreamRead(name, data))
    return found


def shown_in(data: bytes, canaries: frozenset[str], *, running: bool = False) -> bool:
    """Whether ``data``, one review stream's bytes as written, shows one of ``canaries``.

    The one scan of a review's stream, over its bytes unredacted: the live review's, the next
    command's, and the exposure register's. While the session runs (``running``), the bytes after
    the last line's end are a line still being written, read once it is whole: cut inside a
    character it would read as one that cannot be read, so as the canary. Leaving them out can
    only miss what a later read finds, never find what is not there.
    """
    if running:
        data = data[: data.rfind(b"\n") + 1]
    return canary_seen(data, canaries) is not None


def streams_show(record: ReviewRecord, *, running: bool = False) -> bool:
    """Whether a stream the review's spawns wrote shows a held-out canary its record names.

    Raises:
        InvocationError: a stream is gone, a link, not a regular file, on a linked directory or
            over the size bound: never read as clean.
    """
    for read in read_review_streams(record):
        if read.data is None:
            kind = STREAM_REFUSALS[read.refused or "file"]
            msg = f"a stream of the design review is {kind}; nothing is read from it"
            raise InvocationError(msg, session_id=record.session_id, stream=read.name)
        if shown_in(read.data, record.canaries, running=running):
            return True
    return False


def exposed_review(run_dir: Path) -> str | None:
    """The review session the exposure file names; ``None`` when there is no exposure file.

    An exposure file whose session cannot be read is still an exposure: an empty name is given.
    """
    if not (run_dir / REVIEW_EXPOSED).is_file():
        return None
    try:
        return str(json.loads((run_dir / REVIEW_EXPOSED).read_text())["session_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def record_held_out(run_dir: Path, digests: Iterable[str]) -> None:
    """Record the digests of the held-out tiers the decomposition was given, synced.

    Written before any review session is spawned: a decomposition killed in its review has no run
    configuration, and the register reads from this file which tier versions it may have exposed.
    """
    path = run_dir / HELD_OUT_TIERS
    path.parent.mkdir(parents=True, exist_ok=True)
    _synced(path, json.dumps({"held_out_sha256": list(digests)}).encode())


def recorded_held_out(run_dir: Path) -> tuple[str, ...] | None:
    """The held-out tiers' digests the decomposition recorded; ``None`` if it recorded none.

    Raises:
        ReviewRecordError: the record is there and cannot be read.
    """
    path = run_dir / HELD_OUT_TIERS
    if not path.is_file():
        return None
    try:
        named = json.loads(path.read_text())["held_out_sha256"]
        if not isinstance(named, list) or not all(isinstance(d, str) for d in named):
            raise TypeError(type(named).__name__)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReviewRecordError(str(path)) from exc
    return tuple(named)


def _stop_and_scan(run_dir: Path, secrets: tuple[str, ...]) -> str | None:
    path = run_dir / REVIEW_SESSION
    try:
        record = review_record(run_dir)
    except ReviewRecordError:
        return (
            f"the record {path} of a design review session a killed decompose left cannot be "
            "read; nothing was signalled, and its streams are not scanned"
        )
    if record is None:
        return None
    session_id, pid, started = record.session_id, record.pid, record.started
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
    # Nothing of it runs now. Every stream its spawns wrote is final, and scanned once, as it was
    # written: before the redaction, which replaces whole a line it cannot read, a line the scan
    # counts as the canary. So this command counts what the exposure register counts.
    session = record.session_dir
    try:
        shown = streams_show(record)
    except InvocationError as exc:
        return f"{said}; its directory cannot be read ({exc}), so the record is kept"
    if shown:
        _synced(run_dir / REVIEW_EXPOSED, json.dumps({"session_id": session_id}).encode())
    # It needs no credential now: a killed decompose never removed it, and its streams were never
    # redacted.
    try:
        remove_secrets(session / "state", session / "config")
        for name in review_streams(record.spawns):
            for secret in secrets:
                redact(session / name, secret)
    except InvocationError as exc:
        return f"{said}; its directory cannot be redacted ({exc}), so the record is kept"
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
