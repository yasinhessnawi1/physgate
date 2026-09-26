"""The run-event log: one append-only line for everything the loop did.

The loop's position is derived from this file and from nothing held in memory,
so a killed orchestrator loses nothing it had not yet written, and a fresh
process reading the file sees exactly what the loop saw. Every line carries a
sequence number, a UTC timestamp, the run id and the run's gate mode.

The task ledger is a projection of this log, not the other way round: the
ledger's line shape is fixed by the architecture and cannot hold a stage, a
cause or a timestamp, and this log exists to hold them.

Append-only is structural. There is no update and no delete, and every append
is flushed and synced before it returns, because some of these lines are
write-ahead records that a restart has to be able to trust.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from physgate.orchestrator.exceptions import CorruptEventLogError, RunConfigError

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

#: The architecture's physics-gate flag (ARCH-140): blocking, not run, or run and logged
#: without blocking. Required for every run; there is no default.
GateMode = Literal["on", "off", "observe"]

#: The eight stages of the per-subtask loop, in the architecture's order (ARCH-030).
Stage = Literal[
    "resolve", "spawn", "verify_reading", "implement", "gate", "review", "decide", "diff"
]

#: Why a run stopped short of the end of its plan.
HaltReason = Literal["incident", "infrastructure_exhausted", "decomposition_failed"]

_TIMESTAMP = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$"


class _Event(BaseModel):
    """What every line carries."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    seq: Annotated[int, Field(ge=0)]
    ts: Annotated[str, StringConstraints(pattern=_TIMESTAMP)]
    run_id: NonEmptyStr
    gate_mode: GateMode


class RunStarted(_Event):
    """The first line of every log: the run and the digest of its recorded config."""

    kind: Literal["run_started"] = "run_started"
    config_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SubtaskPlanned(_Event):
    """A subtask the decomposition produced."""

    kind: Literal["subtask_planned"] = "subtask_planned"
    subtask_id: NonEmptyStr
    spec_path: NonEmptyStr
    assigned_role: NonEmptyStr
    module_dir: NonEmptyStr


class SubtaskRemoved(_Event):
    """A planned subtask taken out of the plan before it was dispatched."""

    kind: Literal["subtask_removed"] = "subtask_removed"
    subtask_id: NonEmptyStr
    reason: NonEmptyStr


class StageEntered(_Event):
    """The loop entered one of the eight stages for a subtask's attempt."""

    kind: Literal["stage_entered"] = "stage_entered"
    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1)]
    stage: Stage


class Halted(_Event):
    """The run stopped, and why. Resuming reads this line."""

    kind: Literal["halted"] = "halted"
    reason: HaltReason
    detail: NonEmptyStr


Event = Annotated[
    RunStarted | SubtaskPlanned | SubtaskRemoved | StageEntered | Halted,
    Field(discriminator="kind"),
]
_EVENT: TypeAdapter[Event] = TypeAdapter(Event)

E = TypeVar("E", bound=_Event)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    if moment.utcoffset() != timedelta(0):
        msg = "event timestamps are UTC"
        raise ValueError(msg)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def first_problem(exc: ValidationError) -> str:
    """The first thing wrong with a record, as a sentence rather than a report."""
    problems = exc.errors()
    if not problems:
        return "the line is not a valid record"
    where = ".".join(str(part) for part in problems[0]["loc"]) or "the record"
    return f"{where}: {problems[0]['msg']}"


def read_jsonl[T](
    path: Path, parse: Callable[[bytes], T]
) -> tuple[list[T], int, tuple[int, str] | None]:
    """Parse every complete line of ``path``.

    Returns the parsed records, the byte offset where the good records end, and
    the offset and reason of the first complete line that did not parse, if any.
    A final line without its terminator is not parsed and not an error: it is a
    write that was still in progress. Reading stops at the first bad line, since
    whatever follows a record no writer of this package produced is not trusted.
    ``parse`` raises ``ValueError`` (``ValidationError`` is one) to refuse a line.
    """
    records: list[T] = []
    good_end = 0
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            try:
                records.append(parse(raw))
            except ValidationError as exc:
                return records, good_end, (good_end, first_problem(exc))
            except ValueError as exc:
                return records, good_end, (good_end, str(exc) or "the line is not a record")
            good_end += len(raw)
    return records, good_end, None


class _Context:
    """What the lines so far make legal: the check shared by the writer and replay."""

    def __init__(self) -> None:
        self.count = 0
        self.run: tuple[str, str] | None = None
        self.planned: set[str] = set()

    def check(self, event: _Event) -> None:
        """Raise ``ValueError`` unless ``event`` may be the next line."""
        if event.seq != self.count:
            msg = f"sequence number {event.seq} where {self.count} comes next"
            raise ValueError(msg)
        if self.run is None:
            if not isinstance(event, RunStarted):
                msg = "the first line of a run is not its start"
                raise ValueError(msg)
        elif isinstance(event, RunStarted):
            msg = "a second start line in one run"
            raise ValueError(msg)
        elif (event.run_id, event.gate_mode) != self.run:
            msg = "the run id or the gate mode changed within one run"
            raise ValueError(msg)
        subtask = getattr(event, "subtask_id", None)
        if isinstance(event, SubtaskPlanned):
            if event.subtask_id in self.planned:
                msg = f"subtask {event.subtask_id!r} planned twice"
                raise ValueError(msg)
        elif subtask is not None and subtask not in self.planned:
            msg = f"subtask {subtask!r} was never planned"
            raise ValueError(msg)

    def record(self, event: _Event) -> None:
        """Take ``event`` as the next line. Call only after :meth:`check` passed."""
        if self.run is None:
            self.run = (event.run_id, event.gate_mode)
        if isinstance(event, SubtaskPlanned):
            self.planned.add(event.subtask_id)
        self.count += 1


def _parse_in(context: _Context) -> Callable[[bytes], Event]:
    def parse(raw: bytes) -> Event:
        event = _EVENT.validate_json(raw)
        context.check(event)
        context.record(event)
        return event

    return parse


def read_events(path: Path) -> list[Event]:
    """Every event in the log at ``path``, read fresh from disk by any process.

    Raises:
        CorruptEventLogError: a complete line is not a record, or does not follow
            from the lines before it.
    """
    events, _, corrupt = read_jsonl(Path(path), _parse_in(_Context()))
    if corrupt is not None:
        offset, reason = corrupt
        msg = "the run-event log holds a line this package could not have written"
        raise CorruptEventLogError(msg, log=str(path), offset=str(offset), reason=reason)
    return events


class EventLog:
    """The one writer of a run's event log.

    Opening reads the log back through the same checks the writer applies, drops
    an unterminated final line, and refuses a log whose complete lines do not
    follow from each other. Like the task ledger, a handle answers from what it
    has read and written: the orchestrator is the only writer.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        gate_mode: GateMode,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Open or create the log at ``path`` for ``run_id``.

        Raises:
            CorruptEventLogError: as :func:`read_events`.
            RunConfigError: the log belongs to another run or another gate mode.
        """
        self.path = Path(path)
        self._run = (run_id, gate_mode)
        self._clock = clock
        self._context = _Context()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        events, good_end, corrupt = read_jsonl(self.path, _parse_in(self._context))
        if corrupt is not None:
            offset, reason = corrupt
            msg = "the run-event log holds a line this package could not have written"
            raise CorruptEventLogError(msg, log=str(self.path), offset=str(offset), reason=reason)
        if self._context.run not in (None, self._run):
            msg = "the run-event log belongs to another run or gate mode"
            raise RunConfigError(msg, log=str(self.path), run_id=run_id, gate_mode=gate_mode)
        self.torn_tail_bytes = self.path.stat().st_size - good_end
        if self.torn_tail_bytes:
            with self.path.open("r+b") as handle:
                handle.truncate(good_end)
        self._events: list[Event] = events
        self._handle = self.path.open("ab")

    @property
    def events(self) -> tuple[Event, ...]:
        """Every event this handle has read or written, oldest first."""
        return tuple(self._events)

    def emit(self, kind: type[E], **fields: Any) -> E:
        """Append one event of ``kind``, synced to disk before returning.

        The sequence number, timestamp, run id and gate mode are filled in here.
        A line the replay would refuse is refused before it is written.

        Raises:
            ValueError: the event does not follow from the log (``ValidationError``
                for a malformed field).
        """
        run_id, gate_mode = self._run
        event = kind(
            seq=len(self._events),
            ts=_stamp(self._clock()),
            run_id=run_id,
            gate_mode=gate_mode,
            **fields,
        )
        self._context.check(event)
        self._handle.write(event.model_dump_json().encode() + b"\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        # Recorded only once the line is on disk, so a failed write leaves the
        # handle agreeing with the file.
        self._context.record(event)
        self._events.append(cast("Event", event))
        return event

    def close(self) -> None:
        """Release the file handle. Idempotent."""
        if not self._handle.closed:
            self._handle.close()
