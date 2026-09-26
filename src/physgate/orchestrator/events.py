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
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TypedDict, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from physgate.orchestrator.budget import REPAIR_BUDGET, InfraCause
from physgate.orchestrator.common import (
    GateMode,
    NonEmptyStr,
    Timestamp,
    first_problem,
    utc_now,
    utc_stamp,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, RunConfigError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.protocols import GateResult, ReviewResult, Usage
from physgate.orchestrator.repair import Finding
from physgate.orchestrator.trajectory import Seal

#: The eight stages of the per-subtask loop, in the architecture's order (ARCH-030).
Stage = Literal[
    "resolve", "spawn", "verify_reading", "implement", "gate", "review", "decide", "diff"
]

#: An attempt number: the repair budget bounds it in the record itself, so a fourth
#: attempt cannot even be written down.
Attempt = Annotated[int, Field(ge=1, le=REPAIR_BUDGET)]
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]

#: What an incident is about. Each halts the run; none spends from the repair budget.
IncidentCause = Literal[
    "cross_role_write",
    "merge_conflict",
    "merge_refused",
    "foreign_journal_line",
    "store_refusal",
    "node_files_unrecoverable",
    "managed_settings_changed",
    "run_branch_moved",
    "trajectory_tampered",
]

#: Why a run stopped short of the end of its plan.
HaltReason = Literal[
    "incident", "infrastructure_exhausted", "credential_refused", "decomposition_failed"
]

#: Halts a resume continues from, the same attempt with a fresh schedule: the
#: infrastructure schedule ran out, or the credential was refused and has since
#: been replaced. Any other halt is resolved by a person first.
RESUMABLE_HALTS: frozenset[str] = frozenset({"infrastructure_exhausted", "credential_refused"})

#: Who spent a token: ``<what>:<invocation id>``. The invocation id is the Claude Code
#: session id of the one call, so decomposition invocations can be counted.
ATTRIBUTION = r"^(decomposition|session|reviewer|routing):[A-Za-z0-9_-]{1,128}$"


class Envelope(TypedDict):
    """What every line carries, filled in by the log: spread into an event at the call site.

    Building each event where it is emitted, with this spread in, lets the type
    checker see every field of every line the loop writes. A field name or a
    type that does not match the event is a type error, not a line the log
    refuses at run time.
    """

    seq: int
    ts: str
    run_id: str
    gate_mode: GateMode


class _Event(BaseModel):
    """What every line carries."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    seq: Annotated[int, Field(ge=0)]
    ts: Timestamp
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
    attempt: Attempt
    stage: Stage


class Halted(_Event):
    """The run stopped, and why. Resuming reads this line."""

    kind: Literal["halted"] = "halted"
    reason: HaltReason
    detail: NonEmptyStr


class GateRan(_Event):
    """The gate ran on an attempt, in the run's mode, and this is what it said."""

    kind: Literal["gate_ran"] = "gate_ran"
    subtask_id: NonEmptyStr
    attempt: Attempt
    result: GateResult


class GateSkipped(_Event):
    """The gate did not run, because the run's gate mode is ``off``.

    A recorded ablation, not a result: no verdict exists, so none is written.
    """

    kind: Literal["gate_skipped"] = "gate_skipped"
    subtask_id: NonEmptyStr
    attempt: Attempt
    reason: Literal["gate_mode=off"]


class ReviewRan(_Event):
    """The reviewer ran on an attempt, and this is what it said."""

    kind: Literal["review_ran"] = "review_ran"
    subtask_id: NonEmptyStr
    attempt: Attempt
    result: ReviewResult


class TokensUsed(_Event):
    """One model message's usage, attributed to the one thing that spent it.

    The attribution is a closed set: decomposition, a role session, a reviewer,
    or routing. Routing exists only so the account can prove it is zero.
    """

    kind: Literal["tokens_used"] = "tokens_used"
    attribution: Annotated[str, StringConstraints(pattern=ATTRIBUTION)]
    message_id: NonEmptyStr
    usage: Usage
    #: Read from a session a killed orchestrator left behind, whose stream has no
    #: result: its last message may be cut off, and nothing checks the sum.
    partial: bool = False


class SessionEnded(_Event):
    """A role session ended, and how. A completed one names its commit and trajectory."""

    kind: Literal["session_ended"] = "session_ended"
    subtask_id: NonEmptyStr
    attempt: Attempt
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    outcome: Literal["completed", "infrastructure"]
    cause: InfraCause | None
    attempt_commit: Sha | None
    trajectory: NonEmptyStr | None
    #: The trajectory's digest and length when the session ended; every later reader
    #: holds the file to it. None for a session with no captured stream.
    trajectory_seal: Seal | None = None
    worktree: NonEmptyStr | None
    reading_verified: bool

    @model_validator(mode="after")
    def _completed_names_its_work(self) -> SessionEnded:
        completed = self.outcome == "completed"
        if completed != (self.cause is None):
            msg = "an infrastructure outcome carries its cause, and a completed one none"
            raise ValueError(msg)
        if completed and None in (self.attempt_commit, self.trajectory, self.worktree):
            msg = "a completed session names its attempt commit, trajectory and worktree"
            raise ValueError(msg)
        return self


class InfraRetryScheduled(_Event):
    """The same attempt will run again with a fresh session, after a delay.

    Spends nothing from the repair budget.
    """

    kind: Literal["infra_retry_scheduled"] = "infra_retry_scheduled"
    subtask_id: NonEmptyStr
    attempt: Attempt
    retries_done: Annotated[int, Field(ge=0)]
    delay_s: Annotated[float, Field(ge=0)]


class ProposalsChecked(_Event):
    """The attempt's changes were checked before the gate.

    First its write scope, then its node proposals against the store's own
    guards on a scratch copy of the graph. The commit that was checked is
    recorded, and only that commit may be merged.
    """

    kind: Literal["proposals_checked"] = "proposals_checked"
    subtask_id: NonEmptyStr
    attempt: Attempt
    checked_commit: Sha
    refused_by: Literal["proposal", "write_scope"] | None
    reason: NonEmptyStr | None
    subject: NonEmptyStr | None
    graph_root: NonEmptyStr

    @model_validator(mode="after")
    def _a_refusal_says_why(self) -> ProposalsChecked:
        if (self.refused_by is None) != (self.reason is None):
            msg = "a refusal names what refused and why, and an acceptance names neither"
            raise ValueError(msg)
        return self


class AttemptRejected(_Event):
    """The attempt was rejected; this spends one attempt of the repair budget."""

    kind: Literal["attempt_rejected"] = "attempt_rejected"
    subtask_id: NonEmptyStr
    attempt: Attempt
    finding: Finding
    #: The finding's stable key, and whether the previous attempt was rejected for
    #: the same key: an agent that never fixes a finding spends its budget on it.
    finding_key: NonEmptyStr
    repeats_previous: bool


class Merged(_Event):
    """The attempt was merged into the run branch."""

    kind: Literal["merged"] = "merged"
    subtask_id: NonEmptyStr
    attempt: Attempt
    attempt_commit: Sha
    merge_commit: Sha


class DiffChecked(_Event):
    """The graph was diffed off the durable record after the subtask's step.

    Any divergence (a node written by a role that does not own it) is a blocking
    failure caught before the next dispatch (ARCH-013).
    """

    kind: Literal["diff_checked"] = "diff_checked"
    subtask_id: NonEmptyStr
    attempt: Attempt
    divergences: tuple[NonEmptyStr, ...]


class Escalated(_Event):
    """The subtask exhausted its repair budget and is in the approval queue."""

    kind: Literal["escalated"] = "escalated"
    subtask_id: NonEmptyStr
    item_id: NonEmptyStr


class Incident(_Event):
    """Something the loop cannot answer by itself happened. The run halts after it."""

    kind: Literal["incident"] = "incident"
    #: None when no subtask was active, as for a foreign line found when a run opens.
    subtask_id: NonEmptyStr | None
    cause: IncidentCause
    detail: NonEmptyStr


class Decomposed(_Event):
    """The run's one model call produced a plan, and what it wrote."""

    kind: Literal["decomposed"] = "decomposed"
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    model: NonEmptyStr
    num_turns: Annotated[int, Field(ge=0)]
    subtasks: Annotated[int, Field(ge=1)]
    interface_nodes: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    spec_commit: Sha
    head_revision: Annotated[int, Field(ge=1)]


class WriteIntended(_Event):
    """The orchestrator is about to write one node into the canonical store.

    Synced before the write, so a restart can tell its own write that landed
    without being recorded from a line it never intended, which is foreign.
    """

    kind: Literal["write_intended"] = "write_intended"
    subtask_id: NonEmptyStr
    attempt: Attempt
    node_id: NonEmptyStr
    payload_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    actor_role: NonEmptyStr
    expected_revision: Annotated[int, Field(ge=1)]


class WriteDone(_Event):
    """The intended write landed at this revision of the canonical journal."""

    kind: Literal["write_done"] = "write_done"
    subtask_id: NonEmptyStr
    attempt: Attempt
    node_id: NonEmptyStr
    revision: Annotated[int, Field(ge=1)]


class NodeFilesRepaired(_Event):
    """Node files changed behind the journal were repaired before anything read the graph.

    The session was halted for it; the store was reopened, and recovery rebuilt
    the files from the journal.
    """

    kind: Literal["node_files_repaired"] = "node_files_repaired"
    subtask_id: NonEmptyStr
    attempt: Attempt
    repaired: Annotated[int, Field(ge=0)]
    quarantined: tuple[NonEmptyStr, ...]


class EnvironmentRecorded(_Event):
    """The machine the process runs on, as the hooks depend on it: recorded, not assumed.

    Recorded by every process that drives the run, since a resume can happen on
    another machine. Where the machine cannot provide an installation the session's
    user cannot write, or a local disk for the hook state, this says so.
    """

    kind: Literal["environment_recorded"] = "environment_recorded"
    facts: InstallFacts


class LeftoverStopped(_Event):
    """A session a previous orchestrator left running was found and stopped.

    Killing the orchestrator does not stop its session (measured: it finished its
    whole attempt unobserved), so a new process stops it first, before anything
    else touches the worktree or the store.
    """

    kind: Literal["leftover_stopped"] = "leftover_stopped"
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    pid: Annotated[int, Field(ge=1)]
    killed: Annotated[int, Field(ge=0)]


class WorktreeRemoved(_Event):
    """A done subtask's worktree was removed, or git refused to, and how long it took.

    Only a done subtask's (merged, its diff clean), or an escalated one's once its
    queue item was resolved. Never its branch, a session directory, the run branch or
    the store, and never forced: a refusal is recorded and the worktree left.
    """

    kind: Literal["worktree_removed"] = "worktree_removed"
    subtask_id: NonEmptyStr
    path: NonEmptyStr
    reason: Literal["done", "queue_resolved"]
    outcome: Literal["removed", "refused", "timed_out", "absent"]
    seconds: Annotated[float, Field(ge=0)]
    detail: NonEmptyStr | None


class Resumed(_Event):
    """A process took the run over from one that stopped, at a checkpoint of the attempt.

    Whatever the previous process had started after that checkpoint is done again:
    a session is always a fresh one, never the binary's own resume.
    """

    kind: Literal["resumed"] = "resumed"
    subtask_id: NonEmptyStr
    attempt: Attempt
    point: Literal["resolve", "verify_reading", "diff"]


Event = Annotated[
    RunStarted
    | SubtaskPlanned
    | SubtaskRemoved
    | StageEntered
    | GateRan
    | GateSkipped
    | ReviewRan
    | TokensUsed
    | SessionEnded
    | InfraRetryScheduled
    | ProposalsChecked
    | AttemptRejected
    | Merged
    | DiffChecked
    | Escalated
    | Incident
    | Resumed
    | Decomposed
    | EnvironmentRecorded
    | LeftoverStopped
    | WorktreeRemoved
    | WriteIntended
    | WriteDone
    | NodeFilesRepaired
    | Halted,
    Field(discriminator="kind"),
]
_EVENT: TypeAdapter[Event] = TypeAdapter(Event)

E = TypeVar("E", bound=_Event)


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
        mode = self.run[1] if self.run is not None else event.gate_mode
        # Under ``off`` no gate result may exist, and a gate that ran must have run in
        # the run's own mode: a pass recorded for a skipped gate is a fabricated one.
        if isinstance(event, GateRan) and event.result.mode != mode:
            msg = (
                f"a gate result in mode {event.result.mode!r} in a run whose gate mode is {mode!r}"
            )
            raise ValueError(msg)
        if isinstance(event, GateSkipped) and mode != "off":
            msg = f"the gate was skipped in a run whose gate mode is {mode!r}"
            raise ValueError(msg)

    def record(self, event: _Event) -> None:
        """Take ``event`` as the next line. Call only after :meth:`check` passed."""
        if self.run is None:
            self.run = (event.run_id, event.gate_mode)
        if isinstance(event, SubtaskPlanned):
            self.planned.add(event.subtask_id)
        self.count += 1


class RecordState(Protocol):
    """Something that follows a run's lines and refuses one that cannot come next.

    The writer calls ``check`` before a line is written and ``record`` after it
    is on disk; replay calls both for every line it reads. One object doing both
    is what makes "the writer refuses what the replay refuses" true by
    construction rather than by keeping two copies of a rule in step.
    """

    def check(self, event: Event) -> None:
        """Raise ``ValueError`` unless ``event`` may be the next line."""
        ...

    def record(self, event: Event) -> None:
        """Take ``event`` as the next line."""
        ...


def _parse_in(context: _Context, state: RecordState | None) -> Callable[[bytes], Event]:
    def parse(raw: bytes) -> Event:
        event = _EVENT.validate_json(raw)
        context.check(event)
        if state is not None:
            state.check(event)
        context.record(event)
        if state is not None:
            state.record(event)
        return event

    return parse


def read_events(path: Path) -> list[Event]:
    """Every event in the log at ``path``, read fresh from disk by any process.

    Raises:
        CorruptEventLogError: a complete line is not a record, or does not follow
            from the lines before it.
    """
    events, _, corrupt = read_jsonl(Path(path), _parse_in(_Context(), None))
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
        clock: Callable[[], datetime] = utc_now,
        state: RecordState | None = None,
    ) -> None:
        """Open or create the log at ``path`` for ``run_id``.

        ``state``, if given, follows every line read at open and every line
        written after, and can refuse one; the loop passes its run state here.

        Raises:
            CorruptEventLogError: as :func:`read_events`.
            RunConfigError: the log belongs to another run or another gate mode.
        """
        self.path = Path(path)
        self._run = (run_id, gate_mode)
        self._clock = clock
        self._context = _Context()
        self._state = state
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        events, good_end, corrupt = read_jsonl(self.path, _parse_in(self._context, state))
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

    def envelope(self) -> Envelope:
        """The fields the next line carries: its sequence number, timestamp, run and mode."""
        run_id, gate_mode = self._run
        return Envelope(
            seq=len(self._events), ts=utc_stamp(self._clock()), run_id=run_id, gate_mode=gate_mode
        )

    def emit(self, kind: type[E], **fields: Any) -> E:  # noqa: ANN401 - a test's own fields
        """Build and append one event from loose fields. For tests only.

        Tests use it to write lines the log must refuse, which a typed constructor
        would not let them build. The orchestrator's own code builds each event
        with :meth:`envelope` spread in and calls :meth:`append`, so the type
        checker sees every field; the routing fence refuses this method there.
        """
        return self.append(kind(**self.envelope(), **fields))

    def append(self, event: E) -> E:
        """Append ``event``, synced to disk before returning.

        A line the replay would refuse is refused before it is written.

        Raises:
            ValueError: the event does not follow from the log, including a
                sequence number that is not the next one.
        """
        self._context.check(event)
        admitted = cast("Event", event)
        if self._state is not None:
            self._state.check(admitted)
        self._handle.write(event.model_dump_json().encode() + b"\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        # Recorded only once the line is on disk, so a failed write leaves the
        # handle agreeing with the file.
        self._context.record(event)
        if self._state is not None:
            self._state.record(admitted)
        self._events.append(admitted)
        return event

    def close(self) -> None:
        """Release the file handle. Idempotent."""
        if not self._handle.closed:
            self._handle.close()
