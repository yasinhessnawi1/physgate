"""The approval queue: what a person decides, with what they need to decide it.

Two append-only files per run. The items file is written only by the
orchestrator, between sessions. An item carries the five things ARCH-130
names: the decision required, the artefact diff, the finding that triggered it,
the most relevant quantities (at most three), and a link to every trajectory
involved.

A person's decision goes into its own file, because a person decides while a
session may be running. The items file is put back by the hook layer if it
changes during a session; the decisions file is only refused to the session's
tools, so a decision appended by ``physgate queue resolve`` meanwhile stands.
Each decision names an open item. Nothing is ever edited, so the two files say
what was asked, what was decided, and when. Every decision is written by one
function, :func:`record_decision`, under a lock on the decisions file, so two
people deciding at once cannot both find an item open.

The item's wording is a template filled by code. The queue is where a model
would be most tempting, since it is prose for a person, and there is none.

**Reading is not writing.** :class:`ApprovalQueue` is the one writer: opening it
creates the files it writes and cuts a torn final line. Anything that only reads
(``physgate queue list``, the operator UI) goes through :func:`read_queue` and
:func:`queue_listing`, which create nothing and cut nothing, and hold every line
to exactly the rules the writer holds it to, through the same parser.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.common import (
    NonEmptyStr,
    Timestamp,
    first_problem,
    utc_now,
    utc_stamp,
)
from physgate.orchestrator.events import (
    Event,
    LeftoverRead,
    SessionEnded,
    StageEntered,
    parse_events,
    read_events,
    read_jsonl,
)
from physgate.orchestrator.exceptions import QueueError, StaleViewError
from physgate.orchestrator.protocols import GateResult, QuantityRef, SpecDefect
from physgate.orchestrator.repair import Finding
from physgate.orchestrator.trajectory import Seal, seal

#: The queue's sources (ARCH-130); a blocked review and one with no verdict are kept apart.
QueueSource = Literal[
    "gate_escalation",
    "repair_budget_exhausted",
    "review_unavailable",
    "review_blocked",
    "arbitration",
]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_id: NonEmptyStr
    ts: Timestamp


class QueueItem(_Record):
    """One decision a person has to take."""

    kind: Literal["item"] = "item"
    run_id: NonEmptyStr
    subtask_id: NonEmptyStr
    source: QueueSource
    decision_required: NonEmptyStr
    artefact_diff: str
    triggering_finding: NonEmptyStr
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]
    trajectories: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class QueueResolution(_Record):
    """A person's decision on one item."""

    kind: Literal["resolution"] = "resolution"
    decision: NonEmptyStr
    resolved_by: NonEmptyStr


#: The items file, in the run directory.
QUEUE_NAME = "queue.jsonl"

#: The decisions file, beside the items file.
DECISIONS_NAME = "queue_decisions.jsonl"

_ITEM: TypeAdapter[QueueItem] = TypeAdapter(QueueItem)
_DECISION: TypeAdapter[QueueResolution] = TypeAdapter(QueueResolution)


def escalation_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    findings: tuple[Finding, ...],
    artefact_diff: str,
    trajectories: tuple[str, ...],
    ts: str,
) -> QueueItem:
    """The item for a subtask whose every attempt was rejected.

    The triggering finding is the last one. The quantities are the last
    finding's that has any, because the most recent evidence is the most
    relevant.

    Raises:
        QueueError: fewer findings or trajectories than attempts were given.
    """
    if len(findings) != REPAIR_BUDGET or len(trajectories) != REPAIR_BUDGET:
        msg = "an exhausted budget is escalated with every attempt's finding and trajectory"
        raise QueueError(msg, findings=str(len(findings)), trajectories=str(len(trajectories)))
    with_quantities = [f for f in findings if f.quantities]
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source="repair_budget_exhausted",
        decision_required=(
            f"Subtask {subtask_id} was rejected on all {REPAIR_BUDGET} attempts. Decide whether "
            "to accept the last attempt as it stands, rewrite the subtask's specification, or "
            "split the subtask."
        ),
        artefact_diff=artefact_diff,
        triggering_finding=findings[-1].text,
        quantities=with_quantities[-1].quantities if with_quantities else (),
        trajectories=trajectories,
    )


#: The subtask field of the item the integration call escalates: it is about the
#: whole design, not one subtask.
INTEGRATION = "integration"


def unavailable_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    attempt: int,
    source: Literal["review_unavailable", "review_blocked"],
    cause: str,
    detail: str,
    spec_defects: tuple[SpecDefect, ...],
    artefact_diff: str,
    trajectory: str,
    ts: str,
) -> QueueItem:
    """The item for a subtask whose review blocked it or reached no verdict; no attempt spent.

    A blocked review names what the issued specification lacks, which only the
    decomposition can supply; any other cause names why no verdict was reached. The
    source is the caller's, from the line it escalates, so a no-verdict line a log
    recorded with the legacy blocked cause stays a ``review_unavailable`` item.
    """
    if cause == "blocking_spec_defect":
        lacking = "; ".join(d.finding for d in spec_defects if d.blocking) or detail
        decision = (
            f"The review of subtask {subtask_id}, attempt {attempt}, was blocked: it could "
            f"not decide a safety-critical check because the issued specification lacks its input: "
            f"{lacking}. Decide whether to revise the specification and dispatch again, or "
            "to decide the check yourself. No repair attempt was spent."
        )
    else:
        decision = (
            f"The review of subtask {subtask_id}, attempt {attempt}, reached no verdict "
            f"({cause}: {detail}). Decide whether to review it again, review it yourself, or "
            "set the attempt aside. No repair attempt was spent."
        )
    notes = [f"specification defect: {d.finding}" for d in spec_defects if not d.blocking]
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source=source,
        decision_required=decision if not notes else decision + " Notes: " + "; ".join(notes),
        artefact_diff=artefact_diff,
        triggering_finding=detail,
        quantities=(),
        trajectories=(trajectory,),
    )


def integration_item(
    *,
    item_id: str,
    run_id: str,
    result: GateResult,
    run_span: tuple[str, str],
    trajectories: tuple[str, ...],
    ts: str,
) -> QueueItem:
    """The item for an integrated design the gate refused (a physics-gate escalation).

    No subtask owns a whole-system failure, so it goes to a person rather than to
    a repair session. ``run_span`` is the run branch's start and head, the design
    that was judged.

    Raises:
        QueueError: the refusal did not block, or no attempt left a trajectory.
    """
    if result.verdict != "fail" or result.mode != "on":
        msg = "only a blocking integration failure is escalated"
        raise QueueError(msg, verdict=result.verdict, mode=result.mode)
    if not trajectories:
        msg = "an integration item links every merged attempt's trajectory"
        raise QueueError(msg)
    start, head = run_span
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=INTEGRATION,
        source="gate_escalation",
        decision_required=(
            f"The integrated design failed the physics gate's {result.failing_check} check at "
            "system scope, after every subtask had merged. No one subtask owns this. Decide "
            "which module changes, or whether to accept the design as it stands."
        ),
        artefact_diff=(
            f"The run branch from {start} to {head}: see `git diff {start} {head}` in the "
            "target repository."
        ),
        triggering_finding=result.finding,
        quantities=result.quantities,
        trajectories=trajectories,
    )


class _Records:
    """The queue's lines read so far, and what they make legal next.

    Shared by the writer and every reader, so a line one accepts the other accepts.
    """

    def __init__(self) -> None:
        self.items: dict[str, QueueItem] = {}
        self.resolved: dict[str, QueueResolution] = {}
        #: Each item's line as recorded, without its terminator: what a view shows is held
        #: to these bytes, not to a re-serialisation of them.
        self.lines: dict[str, bytes] = {}

    def check(self, record: QueueItem | QueueResolution) -> None:
        """Raise ``ValueError`` unless ``record`` may be the next line."""
        if isinstance(record, QueueItem):
            if record.item_id in self.items:
                msg = f"item {record.item_id!r} listed twice"
                raise ValueError(msg)
        elif record.item_id not in self.items or record.item_id in self.resolved:
            msg = f"a decision on {record.item_id!r}, which is not an open item"
            raise ValueError(msg)

    def record(self, record: QueueItem | QueueResolution) -> None:
        """Take ``record`` as read; :meth:`check` has passed it."""
        if isinstance(record, QueueItem):
            self.items[record.item_id] = record
        else:
            self.resolved[record.item_id] = record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return [i for k, i in self.items.items() if k not in self.resolved]


def _parse(
    source: Path | bytes,
    adapter: TypeAdapter[QueueItem] | TypeAdapter[QueueResolution],
    records: _Records,
    at: list[tuple[int, QueueResolution]] | None = None,
    *,
    name: str | None = None,
) -> int:
    """Admit every complete line into ``records``; the offset the good lines end at.

    ``source`` is the file, or its bytes as a caller read them through its own descriptor
    (``name`` then names it in a refusal). A final line without its terminator is a write
    still in progress and is not read. With ``at``, each decision is also listed with the
    byte offset its line starts at.

    Raises:
        QueueError: a complete line is not a record of the file's kind, or does not follow
            from the lines before it.
        FileNotFoundError: there is no file at ``source``.
    """
    offset = 0

    def admit(raw: bytes) -> QueueItem | QueueResolution:
        nonlocal offset
        record = adapter.validate_json(raw)
        records.check(record)
        records.record(record)
        if isinstance(record, QueueItem):
            records.lines[record.item_id] = raw.removesuffix(b"\n")
        elif at is not None:
            at.append((offset, record))
        offset += len(raw)
        return record

    _, good_end, corrupt = read_jsonl(source, admit)
    if corrupt is not None:
        bad_at, reason = corrupt
        msg = "the approval queue holds a line this package could not have written"
        where = name if name is not None else str(source)
        raise QueueError(msg, queue=where, offset=str(bad_at), reason=reason)
    return good_end


@dataclass(frozen=True)
class QueueView:
    """A run's queue as read from disk: every item, and every decision with its line's offset."""

    items: tuple[QueueItem, ...]
    decisions: tuple[tuple[int, QueueResolution], ...]
    #: Each item's digest: the sha256 of its line as recorded (see :func:`item_sha256`).
    digests: Mapping[str, str] = field(default_factory=dict)

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        decided = {decision.item_id for _, decision in self.decisions}
        return [item for item in self.items if item.item_id not in decided]


def read_queue(run_dir: Path) -> QueueView:
    """The queue of the run at ``run_dir``, read without writing anything.

    Nothing is created: a run directory, or either file, that is missing reads as empty. A
    torn final line is left where it is and not read, since its writer may still be completing
    it; only the writer, which knows no write of its own is in progress, may cut one.

    Raises:
        QueueError: a complete line is not a record, or does not follow from the lines
            before it (an item listed twice, a decision on no open item).
    """
    records = _Records()
    at: list[tuple[int, QueueResolution]] = []
    for name, adapter in ((QUEUE_NAME, _ITEM), (DECISIONS_NAME, _DECISION)):
        try:
            _parse(Path(run_dir) / name, adapter, records, at)
        except FileNotFoundError:
            continue
    return QueueView(
        items=tuple(records.items.values()),
        decisions=tuple(at),
        digests={k: item_sha256(line) for k, line in records.lines.items()},
    )


def session_windows(run_dir: Path) -> list[tuple[int, int | None, str]]:
    """The decisions file's byte ranges written while each session ran: (start, end, session).

    From the event log: a session's window opens at its spawn stage and closes at
    its end, or at the resume that found it left over; a window still open has no
    end. No event log, no windows.
    """
    events_path = Path(run_dir) / "events.jsonl"
    if not events_path.exists():
        return []
    windows: list[tuple[int, int | None, str]] = []
    open_at: int | None = None
    for event in read_events(events_path):
        if isinstance(event, StageEntered) and event.decisions_bytes is not None:
            open_at = event.decisions_bytes
        elif (
            isinstance(event, SessionEnded | LeftoverRead)
            and open_at is not None
            and event.decisions_bytes is not None
        ):
            windows.append((open_at, event.decisions_bytes, event.session_id))
            open_at = None
    if open_at is not None:
        windows.append((open_at, None, "still running or not yet resumed"))
    return windows


def queue_listing(run_dir: Path) -> dict[str, object]:
    """What ``physgate queue list`` prints: the open items, and every decision with its mark.

    A decision is not refused for being made while a session ran, since a person may decide
    then; but a session's hidden write could add one too, so a decision whose line starts
    inside a session's window is marked for a person to confirm. Read without writing.

    Raises:
        QueueError: the queue holds a line the writer could not have written.
        CorruptEventLogError: the event log does.
    """
    view = read_queue(run_dir)
    windows = session_windows(run_dir)
    decided = []
    for offset, decision in view.decisions:
        during = [
            sid for start, end, sid in windows if start <= offset and (end is None or offset < end)
        ]
        flag = f"made while session {during[0]} ran; confirm" if during else None
        decided.append({**decision.model_dump(), "flag": flag})
    return {"open": [item.model_dump() for item in view.open_items()], "decided": decided}


def item_sha256(line: bytes) -> str:
    """The digest a view of an item carries: of its line as recorded, without the terminator."""
    return hashlib.sha256(line).hexdigest()


# -- what a person saw of an item's trajectories ----------------------------------------

#: The run directory's sessions, each in a directory named by its id, its captured stream in it.
SESSIONS_NAME = "sessions"
STREAM_NAME = "stdout.jsonl"
EVENTS_NAME = "events.jsonl"

#: A session id as the event log's own model accepts it.
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

#: What an item's trajectory link is found to be, when its view is built and again when a
#: decision is recorded on that view.
TrajectoryStatus = Literal["holds", "tampered", "missing", "no_seal", "not_in_this_run"]


def trajectory_session(link: str) -> str | None:
    """The session id an item's trajectory link names, or ``None`` if it names none.

    A link is the path the session's stream had on the machine that ran it. It is never
    opened as written: only its last three components are read, and they must be the
    sessions directory, a session id, and the stream's name.
    """
    parts = Path(link).parts
    if len(parts) < 3 or parts[-3] != SESSIONS_NAME or parts[-1] != STREAM_NAME:
        return None
    return parts[-2] if _SESSION_ID.fullmatch(parts[-2]) else None


def recorded_seal(events: list[Event], session_id: str) -> Seal | None:
    """The seal recorded for a session's stream: at its end, or when a resume read it left over."""
    for event in events:
        if (
            isinstance(event, SessionEnded | LeftoverRead)
            and event.session_id == session_id
            and event.trajectory_seal is not None
        ):
            return event.trajectory_seal
    return None


def trajectory_statuses(
    item: QueueItem, events: list[Event], read: Callable[[str], bytes | None]
) -> tuple[TrajectoryStatus, ...]:
    """Each of ``item``'s trajectory links, held to its seal, in the item's order.

    ``read`` returns a session's stream bytes, or ``None`` if there is none; it raises
    ``OSError`` for a stream it refused to open (a link, a second name), which counts as
    tampered, since the runtime writes neither.
    """
    found: list[TrajectoryStatus] = []
    for link in item.trajectories:
        session_id = trajectory_session(link)
        if session_id is None:
            found.append("not_in_this_run")
            continue
        expected = recorded_seal(events, session_id)
        if expected is None:
            found.append("no_seal")
            continue
        try:
            data = read(session_id)
        except OSError:
            found.append("tampered")
            continue
        if data is None:
            found.append("missing")
        else:
            found.append("holds" if seal(data) == expected else "tampered")
    return tuple(found)


class ShownItem(BaseModel):
    """What a person was shown of an item: its line's digest and its trajectories' statuses."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    trajectories: tuple[TrajectoryStatus, ...]


# -- the one decision function ------------------------------------------------------------

#: The words a person decides with in the operator UI, mapped onto the free-text decision.
Verb = Literal["approve", "reject"]


def decision_text(verb: Verb, note: str) -> str:
    """The decision as recorded: the verb, and the note after a colon when there is one.

    A rejection must say why.

    Raises:
        QueueError: a rejection without a note, or a verb that is not one of the two.
    """
    if verb not in ("approve", "reject"):
        msg = "a decision is to approve or to reject"
        raise QueueError(msg, verb=str(verb))
    if not note.strip():
        if verb == "reject":
            msg = "a rejection says why: its note is required"
            raise QueueError(msg)
        return verb
    return f"{verb}: {note}"


#: How the decision function opens what it reads and writes: relative to the run directory's
#: descriptor, never through a link, never creating anything.
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_in(dir_fd: int, name: str, flags: int) -> int:
    """Open ``name`` beneath ``dir_fd``. Its own function so a test can act just before it."""
    return os.open(name, flags, dir_fd=dir_fd)


def _plain(fd: int) -> os.stat_result:
    """``fd``'s status if it is a regular file with one name; otherwise ``OSError``."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise OSError(errno.EPERM, "not a regular file with one name")
    return st


def _read_fd(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, 1 << 20):
        chunks.append(chunk)
    return b"".join(chunks)


def _read_in(dir_fd: int, *parts: str) -> bytes | None:
    """The bytes of the file ``parts`` names beneath ``dir_fd``, or ``None`` if it is not there.

    Every directory on the way and the file itself are opened without following a link, and
    the file must be regular with one name.

    Raises:
        OSError: a link, a second name, or anything else that is not a plain file.
    """
    opened: list[int] = []
    try:
        current = dir_fd
        for name in parts[:-1]:
            current = _open_in(current, name, _DIR_FLAGS)
            opened.append(current)
        fd = _open_in(current, parts[-1], _READ_FLAGS)
        opened.append(fd)
        _plain(fd)
        return _read_fd(fd)
    except FileNotFoundError:
        return None
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def record_decision(
    run_dir: Path,
    item_id: str,
    *,
    decision: str,
    resolved_by: str,
    clock: Callable[[], datetime] | None = None,
    shown: ShownItem | None = None,
    dir_fd: int | None = None,
) -> QueueResolution:
    """Record a person's decision on an open item: the one function that writes a decision.

    ``physgate queue resolve`` and the operator UI both call it, and so does
    :meth:`ApprovalQueue.resolve`. The run directory is ``dir_fd`` when the caller opened it
    (the UI reaches it by a walk no swap can redirect), or ``run_dir`` opened here. In order:

    1. the decisions file is opened for appending beneath the run directory, never through a
       link and never created, and must be a regular file with one name;
    2. an exclusive lock is taken on it, so two deciders cannot both find an item open;
    3. both files are read beneath the run directory the same way (the decisions file must be
       the one locked) and every line held to the writer's rules;
    4. the item must be listed and open, and, when ``shown`` is given, still exactly as it was
       shown: its line's digest and every trajectory's status, read again under the lock;
    5. a torn final line, which only a decider that died mid-write can leave while the lock is
       free, is cut; the decision is appended as one line and synced.

    A refusal writes nothing. ``run_dir`` also names the files in a refusal.

    Raises:
        QueueError: the item is not open (unknown, decided, or no queue at all), a file is not
            a plain file, a line is not one the writer could have written, or the decision is
            not a record.
        StaleViewError: the item is no longer as ``shown``.
    """
    queue_path = Path(run_dir) / QUEUE_NAME
    try:
        record = QueueResolution(
            item_id=item_id,
            ts=utc_stamp((clock or utc_now)()),
            decision=decision,
            resolved_by=resolved_by,
        )
    except ValidationError as exc:
        msg = "the decision is not one the queue can record"
        raise QueueError(msg, reason=first_problem(exc)) from None
    owned = dir_fd is None
    if dir_fd is None:
        try:
            dir_fd = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_open(item_id, queue_path) from None
    try:
        _decide(dir_fd, Path(run_dir), record, shown)
    finally:
        if owned:
            os.close(dir_fd)
    return record


def _not_open(item_id: str, queue_path: Path) -> QueueError:
    msg = f"a decision on {item_id!r}, which is not an open item"
    return QueueError(msg, queue=str(queue_path))


def _not_plain(name: Path, exc: OSError) -> QueueError:
    msg = "an approval-queue file is not a plain file with one name, so nothing is written"
    return QueueError(msg, file=str(name), reason=os.strerror(exc.errno or 0))


def _decide(dir_fd: int, run_dir: Path, record: QueueResolution, shown: ShownItem | None) -> None:
    queue_path, decisions_path = run_dir / QUEUE_NAME, run_dir / DECISIONS_NAME
    try:
        append = _open_in(dir_fd, DECISIONS_NAME, _APPEND_FLAGS)
    except FileNotFoundError:
        raise _not_open(record.item_id, queue_path) from None
    except OSError as exc:
        raise _not_plain(decisions_path, exc) from None
    try:
        try:
            locked = _plain(append)
        except OSError as exc:
            raise _not_plain(decisions_path, exc) from None
        fcntl.flock(append, fcntl.LOCK_EX)
        _checked(record.item_id)
        try:
            items = _read_in(dir_fd, QUEUE_NAME)
        except OSError as exc:
            raise _not_plain(queue_path, exc) from None
        if items is None:
            raise _not_open(record.item_id, queue_path)
        try:
            reading = _open_in(dir_fd, DECISIONS_NAME, _READ_FLAGS)
        except OSError as exc:
            raise _not_plain(decisions_path, exc) from None
        try:
            read = _plain(reading)
            decided = _read_fd(reading)
        except OSError as exc:
            raise _not_plain(decisions_path, exc) from None
        finally:
            os.close(reading)
        if (read.st_dev, read.st_ino) != (locked.st_dev, locked.st_ino):
            msg = "the decisions file was replaced while the decision was being made"
            raise QueueError(msg, file=str(decisions_path))
        records = _Records()
        _parse(items, _ITEM, records, name=str(queue_path))
        good_end = _parse(decided, _DECISION, records, name=str(decisions_path))
        try:
            records.check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(queue_path)) from None
        if shown is not None:
            _require_as_shown(dir_fd, run_dir, records, record.item_id, shown)
        if good_end != len(decided):
            os.ftruncate(append, good_end)
        _write_all(append, record.model_dump_json().encode() + b"\n")
        os.fsync(append)
    finally:
        os.close(append)


def _checked(item_id: str) -> None:
    """Called with the lock held, before anything is read. A seam for the lock's own tests."""


def _require_as_shown(
    dir_fd: int, run_dir: Path, records: _Records, item_id: str, shown: ShownItem
) -> None:
    """Refuse unless the item is still exactly as ``shown``, read again under the lock."""
    now = item_sha256(records.lines[item_id])
    if now != shown.item_sha256:
        msg = "the item is no longer the one that was shown, so the decision is refused"
        raise StaleViewError(msg, item=item_id, shown=shown.item_sha256, now=now)
    try:
        log = _read_in(dir_fd, EVENTS_NAME)
    except OSError as exc:
        raise _not_plain(run_dir / EVENTS_NAME, exc) from None
    events = parse_events(log, log=str(run_dir / EVENTS_NAME)) if log is not None else []
    statuses = trajectory_statuses(
        records.items[item_id],
        events,
        lambda session_id: _read_in(dir_fd, SESSIONS_NAME, session_id, STREAM_NAME),
    )
    if statuses != shown.trajectories:
        msg = "a trajectory of the item is no longer as it was shown, so the decision is refused"
        raise StaleViewError(
            msg, item=item_id, shown=",".join(shown.trajectories), now=",".join(statuses)
        )


class ApprovalQueue:
    """The one writer of a run's approval queue.

    Opening it creates the files and cuts a torn final line, which is right for the writer and
    wrong for anything that only reads: a reader goes through :func:`read_queue`.
    """

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Open or create the queue at ``path``.

        Raises:
            QueueError: a complete line is not a record, or does not follow from the
                lines before it (an item listed twice, a decision on no open item).
        """
        self.path = Path(path)
        if self.path.name != QUEUE_NAME:
            msg = "the approval queue's items file is always named the same in its run directory"
            raise QueueError(msg, queue=str(self.path), expected=QUEUE_NAME)
        self.decisions_path = self.path.with_name(DECISIONS_NAME)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.decisions_path.touch(exist_ok=True)
        self.refresh()

    def refresh(self) -> None:
        """Read both files again: a person may have decided since they were last read.

        Raises:
            QueueError: a complete line is not a record of its file's kind, or does not
                follow from the lines before it.
        """
        self._records = _Records()
        # The items file has one writer, this one, so a torn tail there is this writer's own
        # interrupted write and is cut. The decisions file is appended to by whoever decides,
        # whenever they decide, so a torn tail there may be a write still in progress: it is
        # left for the decision function to cut, under its lock.
        good_end = _parse(self.path, _ITEM, self._records)
        if self.path.stat().st_size != good_end:
            with self.path.open("r+b") as handle:
                handle.truncate(good_end)
        _parse(self.decisions_path, _DECISION, self._records)

    def _append(self, record: QueueItem) -> None:
        try:
            self._records.check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(self.path)) from None
        with self.path.open("ab") as handle:
            handle.write(record.model_dump_json().encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records.record(record)

    def add(self, item: QueueItem) -> None:
        """List ``item``, synced before returning."""
        self._append(item)

    def resolve(self, item_id: str, *, decision: str, resolved_by: str) -> QueueResolution:
        """Record a person's decision on an open item, through :func:`record_decision`."""
        record = record_decision(
            self.path.parent,
            item_id,
            decision=decision,
            resolved_by=resolved_by,
            clock=self._clock,
        )
        self.refresh()
        return record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return self._records.open_items()

    def items(self) -> list[QueueItem]:
        """Every item, oldest first."""
        return list(self._records.items.values())
