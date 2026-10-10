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
what was asked, what was decided, and when.

The item's wording is a template filled by code. The queue is where a model
would be most tempting, since it is prose for a person, and there is none.

**Reading is not writing.** :class:`ApprovalQueue` is the one writer: opening it
creates the files it writes and cuts a torn final line. Anything that only reads
(``physgate queue list``, the operator UI) goes through :func:`read_queue` and
:func:`queue_listing`, which create nothing and cut nothing, and hold every line
to exactly the rules the writer holds it to, through the same parser.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.common import NonEmptyStr, Timestamp, utc_now, utc_stamp
from physgate.orchestrator.events import (
    LeftoverRead,
    SessionEnded,
    StageEntered,
    read_events,
    read_jsonl,
)
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.protocols import GateResult, QuantityRef, SpecDefect
from physgate.orchestrator.repair import Finding

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
    path: Path,
    adapter: TypeAdapter[QueueItem] | TypeAdapter[QueueResolution],
    records: _Records,
    at: list[tuple[int, QueueResolution]] | None = None,
) -> int:
    """Admit every complete line of ``path`` into ``records``; the offset the good lines end at.

    A final line without its terminator is a write still in progress and is not read. With
    ``at``, each decision is also listed with the byte offset its line starts at.

    Raises:
        QueueError: a complete line is not a record of the file's kind, or does not follow
            from the lines before it.
        FileNotFoundError: there is no file at ``path``.
    """
    offset = 0

    def admit(raw: bytes) -> QueueItem | QueueResolution:
        nonlocal offset
        record = adapter.validate_json(raw)
        records.check(record)
        records.record(record)
        if at is not None and isinstance(record, QueueResolution):
            at.append((offset, record))
        offset += len(raw)
        return record

    _, good_end, corrupt = read_jsonl(path, admit)
    if corrupt is not None:
        bad_at, reason = corrupt
        msg = "the approval queue holds a line this package could not have written"
        raise QueueError(msg, queue=str(path), offset=str(bad_at), reason=reason)
    return good_end


@dataclass(frozen=True)
class QueueView:
    """A run's queue as read from disk: every item, and every decision with its line's offset."""

    items: tuple[QueueItem, ...]
    decisions: tuple[tuple[int, QueueResolution], ...]

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
    return QueueView(items=tuple(records.items.values()), decisions=tuple(at))


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
        self._load(self.path, _ITEM)
        self._load(self.decisions_path, _DECISION)

    def _load(
        self, path: Path, adapter: TypeAdapter[QueueItem] | TypeAdapter[QueueResolution]
    ) -> None:
        good_end = _parse(path, adapter, self._records)
        if path.stat().st_size != good_end:
            with path.open("r+b") as handle:
                handle.truncate(good_end)

    def _append(self, record: QueueItem | QueueResolution) -> None:
        try:
            self._records.check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(self.path)) from None
        target = self.path if isinstance(record, QueueItem) else self.decisions_path
        with target.open("ab") as handle:
            handle.write(record.model_dump_json().encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records.record(record)

    def add(self, item: QueueItem) -> None:
        """List ``item``, synced before returning."""
        self._append(item)

    def resolve(self, item_id: str, *, decision: str, resolved_by: str) -> QueueResolution:
        """Record a person's decision on an open item."""
        record = QueueResolution(
            item_id=item_id,
            ts=utc_stamp(self._clock()),
            decision=decision,
            resolved_by=resolved_by,
        )
        self._append(record)
        return record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return self._records.open_items()

    def items(self) -> list[QueueItem]:
        """Every item, oldest first."""
        return list(self._records.items.values())
