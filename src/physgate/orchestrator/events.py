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

import io
import os
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TypedDict, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)

from physgate.contracts.clause import ContractResult
from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.arbitration import (
    ContractConflict,
    DisputeConflict,
    Held,
    Level,
    Standing,
)
from physgate.orchestrator.budget import ATTEMPT_LIMIT, InfraCause
from physgate.orchestrator.common import (
    GateMode,
    NonEmptyStr,
    Timestamp,
    first_problem,
    utc_now,
    utc_stamp,
)
from physgate.orchestrator.dispute import plain
from physgate.orchestrator.escalation import BackendName, Decision
from physgate.orchestrator.escalation_state import EscalationState
from physgate.orchestrator.exceptions import (
    CorruptEventLogError,
    DutyUnownedError,
    RoleRegisterError,
    RunConfigError,
)
from physgate.orchestrator.followed import FollowedInterface
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.managed import (
    FlagCache,
    ObservedTraffic,
    PolicyEntry,
    SessionManaged,
    stricter_only,
)
from physgate.orchestrator.plan import (
    CriterionWords,
    InterfaceConsumers,
    SystemRequirements,
    list_problems,
    words_problems,
)
from physgate.orchestrator.protocols import (
    GateResult,
    QuantityRef,
    RecordedUnavailableCause,
    ReviewResult,
    SpecDefect,
    UnavailableCause,
    Usage,
)
from physgate.orchestrator.repair import Finding
from physgate.orchestrator.trajectory import Seal
from physgate.orchestrator.usage_limit import AccountWindow, UsageLimit
from physgate.oslayer.probe import OsLayerState
from physgate.reviewers.scan import ScanHit
from physgate.roles import owner_of, owners_of
from physgate.series.seal import SeriesCheck, SessionSeries
from physgate.state.held_file import HeldFile
from physgate.state.schema import NodeIdKey
from physgate.state.write_account import WriteAccount

#: The eight stages of the per-subtask loop, in the architecture's order (ARCH-030).
Stage = Literal[
    "resolve", "spawn", "verify_reading", "implement", "gate", "review", "decide", "diff"
]

#: An attempt number: the repair budget bounds it in the record itself, so a fourth
#: attempt cannot even be written down.
Attempt = Annotated[int, Field(ge=1, le=ATTEMPT_LIMIT)]
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

#: What an incident is about. Each halts the run; none spends from the repair budget.
#: ``cross_role_write`` is a node changed by a role that does not own it, a write the store's
#: own guard refuses; ``duty_breach`` is a write the store accepts and a cross-cutting duty
#: forbids (ARCH-051). A run recorded before ``duty_breach`` existed keeps the cause it was
#: recorded with. ``interface_mismatch`` is an interface node the store holds otherwise than the
#: plan's contract pairs say: missing, not an interface, or owned by another role than the pair's
#: producer, so no contract can be tested against it. ``issued_state_mismatch`` is integration's
#: issued state that the run's record, read again, no longer gives: a line it was built from was
#: rewritten after the state was issued. ``declaration_mismatch`` is integration's declaration line
#: that its merged commit, read again with the change check's parser, no longer gives.
#: ``decisions_unreadable`` is a line of the decisions file the queue's reader refuses: the run
#: halts on it, named by file and line, until a person mends the file.
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
    "review_material_read",
    "held_out_read",
    "placeholder_refused",
    "withheld_file_unsure",
    "os_layer_misplaced",
    "os_layer_aborted",
    "reaper_unverified",
    "stream_quarantined",
    "queue_item_mismatch",
    "decisions_rewritten",
    "duty_breach",
    "interface_mismatch",
    "issued_state_mismatch",
    "declaration_mismatch",
    "decisions_unreadable",
    "run_records_changed",
]

#: Why a run stopped short of the end of its plan.
HaltReason = Literal[
    "incident",
    "infrastructure_exhausted",
    "credential_refused",
    "decomposition_failed",
    "os_layer_unavailable",
    "disk_full",
    "role_not_built",
    "usage_limit",
]

#: Halts a resume continues from, the same attempt with a fresh schedule: the
#: infrastructure schedule ran out, the credential was refused and has since been
#: replaced, the OS layer would not start and has since been repaired, or the account's
#: usage limit was reached (a resume goes on only after its reset: the loop's to hold).
#: Any other halt is resolved by a person first; ``disk_full`` is one of those, since a
#: session whose records a full disk lost is looked at before the run goes on.
RESUMABLE_HALTS: frozenset[str] = frozenset(
    {"infrastructure_exhausted", "credential_refused", "os_layer_unavailable", "usage_limit"}
)

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
    #: The escalation backend the run is bound to, as its configuration names it; ``None``
    #: on a log written before the escalation interface existed, whose loop asked none.
    escalation_backend: BackendName | None = None
    #: ``act`` in a run that acts on a person's decisions, which replay reads to hold the closing
    #: pass's wait; left out of a run that records only, so its line keeps its bytes.
    queue_decisions: Literal["act"] | None = None
    #: ``observe``, ``on`` or ``repair:N`` in a run that reviews its plan, which replay reads to
    #: hold every dispatch to the review's line, and but under ``observe`` to the person's decision
    #: on a plan it did not pass; left out of a run that does not, so its line keeps its bytes.
    design_review: Literal["observe", "on", "repair:1", "repair:2", "repair:3"] | None = None
    #: ``generalist`` or ``off`` in a run whose role work is not reviewed by the paired
    #: specialists; left out of a run reviewed by them, so its line keeps its bytes.
    reviewers: Literal["generalist", "off"] | None = None
    #: ``off`` in a run whose role sessions are not given their skill file; left out otherwise.
    skills: Literal["off"] | None = None
    #: ``off`` in a run whose role sessions run without the design discipline; left out otherwise.
    hooks: Literal["off"] | None = None
    #: ``True`` in an ablation run, which is never reportable; left out of every other run.
    ablation: Literal[True] | None = None
    #: ``hold`` in a run that acts on decisions and was started under the rule that every
    #: dispatch of a subtask waits while a subtask it reads from waits on a person; replay refuses
    #: such a dispatch with no hold or release line before it. Left out of every other run, so a
    #: line written before the rule keeps its bytes and replays as it did.
    producer_wait: Literal["hold"] | None = None

    @model_serializer(mode="wrap")
    def _omit_record(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for absent in (
            "queue_decisions",
            "design_review",
            "reviewers",
            "skills",
            "hooks",
            "ablation",
            "producer_wait",
        ):
            if getattr(self, absent) is None:
                data.pop(absent, None)
        return data


class SubtaskPlanned(_Event):
    """A subtask the decomposition produced."""

    kind: Literal["subtask_planned"] = "subtask_planned"
    subtask_id: NonEmptyStr
    spec_path: NonEmptyStr
    assigned_role: NonEmptyStr
    module_dir: NonEmptyStr
    #: Set on the one subtask of the role that owns completion, integration's, which runs after
    #: the integration call; left out of every other line, so those keep their bytes. The writer
    #: holds the mark to the role register when the line is written
    #: (:func:`completion_mark_problem`). Replay reads the mark and never the register, so a
    #: register changed later, a role renamed or an owner moved, cannot change how a recorded
    #: run replays.
    owns_completion: Literal[True] | None = None

    @field_validator("owns_completion", mode="before")
    @classmethod
    def _a_boolean_when_present(cls, value: object) -> object:
        # Present, the mark is a JSON boolean, and the type then takes true alone. A literal
        # compares by equality, so 1 and 1.0 would read as the mark, and an explicit null as
        # none: each re-serialises to bytes no writer here wrote, on the one field that decides
        # which subtask runs after the system gate. Absent, nothing is validated.
        if not isinstance(value, bool):
            msg = "the completion mark is true when present, never a number or null"
            raise ValueError(msg)
        return value

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if data.get("owns_completion") is None:
            data.pop("owns_completion", None)
        return data


def completion_mark_problem(assigned_role: str, *, marked: bool) -> str | None:
    """Why the role register, asked now, does not bear out a planning line's mark; or ``None``.

    Asked when a line is written, never when one is read: the register says which role owns
    completion today, and a recorded line keeps what it said then. A subtask of the owner
    carries the mark and no other does; and with no owner, or two, no subtask is marked, nor
    any subtask of either owner planned, since which of them runs after the call cannot be told.
    """
    owners = owners_of("completion")
    if (marked or assigned_role in owners) and len(owners) > 1:
        return (
            "more than one role owns completion, so no subtask of either is planned: "
            + ", ".join(owners)
        )
    if marked and not owners:
        return "no role owns completion, so no subtask is marked as its owner's"
    if marked and assigned_role not in owners:
        return "only a subtask of the role that owns completion is marked as its owner's"
    if not marked and assigned_role in owners:
        return "a subtask of the role that owns completion carries the completion mark"
    return None


def completion_owner_problem(declaring_role: str | None) -> str | None:
    """Why the role register, asked now, does not let ``declaring_role`` declare completion.

    Asked when a declaration or a completion line is written, never when one is read: replay
    reads the planning line's mark. The register must name exactly one owner of completion, and
    the declaring subtask must be of that role; with none or two, nothing is declared complete.
    ``None`` if the line may be written.
    """
    try:
        owner = owner_of("completion")
    except DutyUnownedError:
        return "no role owns completion, so no module is declared or recorded complete"
    except RoleRegisterError as exc:
        return (
            "more than one role owns completion, so no module is declared or recorded complete: "
            + exc.context.get("owners", "")
        )
    if declaring_role != owner:
        return f"only a subtask of the {owner} role, which owns completion, declares completion"
    return None


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
    #: At the spawn stage: the queue decisions file's length as the session starts.
    decisions_bytes: Annotated[int, Field(ge=0)] | None = None


class DecisionsSealed(_Event):
    """The decisions file as a session starts, in a run that acts on queue decisions (ARCH-133).

    The file is append-only: every decision a person writes is a line added at its end. So the
    bytes a session started beside are still the file's first bytes at every later point, and a
    decision is taken only while each such prefix is what it was. A prefix that changed was
    rewritten beneath a session, by a hand no person's decision accounts for, and the run halts.
    Written only by a run that acts, so a run that records keeps its log byte for byte.
    """

    kind: Literal["decisions_sealed"] = "decisions_sealed"
    subtask_id: NonEmptyStr
    attempt: Attempt
    #: The file's length as the session starts, in bytes, and the digest of those bytes.
    length: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Halted(_Event):
    """The run stopped, and why. Resuming reads this line."""

    kind: Literal["halted"] = "halted"
    reason: HaltReason
    detail: NonEmptyStr
    #: For a halt on the account's usage limit: the reset as the stream gave it, and as an
    #: instant where it parses.
    usage_limit: UsageLimit | None = None

    @model_validator(mode="after")
    def _a_limit_halt_names_its_reset(self) -> Halted:
        if (self.reason == "usage_limit") != (self.usage_limit is not None):
            msg = "a halt on the usage limit carries the limit, and no other halt does"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_no_limit(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # A halt of any other reason is written byte for byte as before the limit was a cause.
        data: dict[str, Any] = handler(self)
        if self.usage_limit is None:
            data.pop("usage_limit", None)
        return data


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


class IntegrationGateRan(_Event):
    """The gate ran once on the whole design, after every planned subtask merged.

    System scope: the checks the architecture runs per run (ARCH-080), over the
    canonical graph. It belongs to no subtask and no attempt.
    """

    kind: Literal["integration_gate_ran"] = "integration_gate_ran"
    result: GateResult


class IntegrationGateSkipped(_Event):
    """Integration was not gated, and why.

    The gate is off, the design is incomplete, nothing was planned, or a person rejected the plan.
    ``subtasks`` names the planned subtasks that were not merged, or for a rejected plan every
    planned subtask; for the other two reasons it is empty.
    """

    kind: Literal["integration_gate_skipped"] = "integration_gate_skipped"
    reason: Literal["gate_mode=off", "not_all_merged", "nothing_planned", "plan_rejected"]
    subtasks: tuple[NonEmptyStr, ...]


class IntegrationEscalated(_Event):
    """The integrated design failed the gate where a failure blocks; a person decides.

    The run ends here, with the approval-queue item this line names.
    """

    kind: Literal["integration_escalated"] = "integration_escalated"
    item_id: NonEmptyStr


class ReviewRan(_Event):
    """The reviewer ran on an attempt, and this is what it said."""

    kind: Literal["review_ran"] = "review_ran"
    subtask_id: NonEmptyStr
    attempt: Attempt
    result: ReviewResult
    #: The earlier attempts of the subtask no review had judged whose scan hits this review was
    #: given and answered, every one (ARCH-133), in order. A line without it judged its own
    #: attempt's streams alone, as every line written before did; it is left out when empty, so
    #: those lines keep their bytes, and a line that holds it holds at least one attempt.
    judged_earlier: tuple[Attempt, ...] = ()
    #: The hits of those earlier attempts this review was given to judge, each marked with its
    #: attempt, as the scan found them: what :attr:`judged_earlier` is held to, with the answers
    #: in :attr:`result`. Left out when empty, as :attr:`judged_earlier` is.
    earlier_hits: tuple[ScanHit, ...] = ()

    @field_validator("judged_earlier", "earlier_hits", mode="before")
    @classmethod
    def _some_when_present(cls, value: object) -> object:
        # Present on a line, the list names an attempt: an empty one re-serialises to bytes no
        # writer wrote. The writer's own empty tuple is the field left out.
        if isinstance(value, list):
            if not value:
                msg = "a review line names the earlier attempts it judged, or leaves the field out"
                raise ValueError(msg)
            return tuple(value)
        return value

    @model_serializer(mode="wrap")
    def _omit_none_judged(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.judged_earlier:
            data.pop("judged_earlier", None)
        if not self.earlier_hits:
            data.pop("earlier_hits", None)
        return data

    @model_validator(mode="after")
    def _earlier_hits_marked(self) -> ReviewRan:
        if any(hit.attempt is None or hit.attempt >= self.attempt for hit in self.earlier_hits):
            msg = "a review line's earlier hits are each marked with an attempt before its own"
            raise ValueError(msg)
        return self


class ReviewUnavailable(_Event):
    """A review that is not a verdict, and why.

    ``retry`` is true once per attempt, for an infrastructure cause only: the review
    runs again. Otherwise the subtask goes to the approval queue with no repair
    attempt spent, and no gate event is stamped from it: catch accounting records
    no reviewer verdict for the attempt, never a pass or a fail.
    """

    kind: Literal["review_unavailable"] = "review_unavailable"
    subtask_id: NonEmptyStr
    attempt: Attempt
    #: A cause from :data:`UnavailableCause`. A log written before a blocked review was
    #: a review line may also hold ``blocking_spec_defect``; it is read as written, and
    #: :meth:`EventLog.append` refuses to write it.
    cause: RecordedUnavailableCause
    detail: NonEmptyStr
    retry: bool
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")] | None
    reviewer_model: NonEmptyStr | None
    #: The specification defects the reviewer recorded, carried to the queue item.
    spec_defects: tuple[SpecDefect, ...] = ()
    #: Per invocation of the review's session, on a pin whose sessions carry the catalog
    #: and flag traffic, the conditions it ran under; empty, and not written, otherwise.
    managed: tuple[SessionManaged, ...] = Field(default=(), exclude_if=lambda v: not v)

    @model_validator(mode="after")
    def _only_infrastructure_is_retried(self) -> ReviewUnavailable:
        if self.retry and self.cause != "infrastructure":
            msg = "only an infrastructure failure of a review is retried"
            raise ValueError(msg)
        return self


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
    #: The queue decisions file's length as the session ended: with the spawn
    #: stage's, the window a decision may have been written in while it ran.
    decisions_bytes: Annotated[int, Field(ge=0)] | None = None
    worktree: NonEmptyStr | None
    reading_verified: bool
    #: The digest of the policy limits the session's invocation received, ``None`` if
    #: none: held to the decomposition call's.
    policy_limits_sha256: Sha256 | None = None
    #: The served catalog and feature flags the session's debug log showed, on a pin whose
    #: sessions carry that traffic: held to the run's first observation. ``None`` otherwise,
    #: and then not written at all, so a session on an earlier pin is recorded byte for byte
    #: as it was before the field existed.
    observed_traffic: ObservedTraffic | None = Field(default=None, exclude_if=lambda v: v is None)
    #: The remote feature flags the session's binary held when it ended, counted and
    #: digested: a record only, since they differ between sessions minutes apart with nothing
    #: of the run's changed. Not written where there is none, as above.
    flag_cache: FlagCache | None = Field(default=None, exclude_if=lambda v: v is None)
    #: Why the session's missing policy limits were recorded and not held to the decomposition
    #: call's: it ended for infrastructure before any model answered it. ``None`` where they were
    #: judged, and on a line written before this was recorded.
    policy_limits_unjudged: NonEmptyStr | None = None
    #: The digest of the session's specification as the decomposition issued it,
    #: taken before the session was spawned; ``None`` for a plan given directly.
    issued_spec_sha256: Sha256 | None = None
    #: The series records the session left, each sealed by digest and length, and what was
    #: refused or discarded instead. Every later reader holds a record to its seal here.
    series: SessionSeries = SessionSeries()
    #: For an end on the account's usage limit: the reset as the stream gave it, and as an
    #: instant where it parses.
    usage_limit: UsageLimit | None = None
    #: How full the account's usage windows were at the last rate-limit event the session's
    #: stream gave, so a run's analysis can say how near the limit each session ended.
    account_windows: tuple[AccountWindow, ...] = ()

    @model_validator(mode="after")
    def _completed_names_its_work(self) -> SessionEnded:
        completed = self.outcome == "completed"
        if completed != (self.cause is None):
            msg = "an infrastructure outcome carries its cause, and a completed one none"
            raise ValueError(msg)
        if completed and None in (self.attempt_commit, self.trajectory, self.worktree):
            msg = "a completed session names its attempt commit, trajectory and worktree"
            raise ValueError(msg)
        if self.policy_limits_unjudged is not None and (
            completed or self.policy_limits_sha256 is not None
        ):
            msg = "only an infrastructure end that left no policy limits has them unjudged"
            raise ValueError(msg)
        if (self.cause == "usage_limit") != (self.usage_limit is not None):
            msg = "an end on the usage limit carries the limit, and no other end does"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_no_limit(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Every other end is written byte for byte as before the limit was a cause.
        data: dict[str, Any] = handler(self)
        if self.usage_limit is None:
            data.pop("usage_limit", None)
        # And an end whose stream gave no rate-limit state, as before the windows were read.
        if not self.account_windows:
            data.pop("account_windows", None)
        return data


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
    refused_by: (
        Literal[
            "proposal", "write_scope", "series", "declaration", "dispute", "interface", "long_line"
        ]
        | None
    )
    reason: NonEmptyStr | None
    subject: NonEmptyStr | None
    graph_root: NonEmptyStr
    #: The node ids the attempt proposed; empty when it was refused before they were
    #: read, and on every line written before the field existed.
    proposed: tuple[NonEmptyStr, ...] = ()
    #: Every proposed quantity that names a simulation record, held to it, passes included;
    #: empty on every line written before the field existed.
    series_checks: tuple[SeriesCheck, ...] = ()
    #: Each interface the attempt's nodes revise, derived at the check: the interface
    #: as it stood, every joined node's payload and the derived revision, so replay derives it
    #: again. Left out of the line when empty, so every other line keeps its bytes.
    followed: tuple[FollowedInterface, ...] = ()

    @model_validator(mode="after")
    def _a_refusal_says_why(self) -> ProposalsChecked:
        if (self.refused_by is None) != (self.reason is None):
            msg = "a refusal names what refused and why, and an acceptance names neither"
            raise ValueError(msg)
        if self.followed and self.refused_by is not None:
            msg = "only an accepted change check follows an interface"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_none_followed(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.followed:
            data.pop("followed", None)
        return data


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

    Any divergence (a node written by a role that does not own it, or a write that
    breaks a cross-cutting duty: a cross node by another role than their owner, a domain
    node by that owner, a new interface node, a node by the owner of completion) is a
    blocking failure caught before the next dispatch (ARCH-013, ARCH-051).
    """

    kind: Literal["diff_checked"] = "diff_checked"
    subtask_id: NonEmptyStr
    attempt: Attempt
    divergences: tuple[NonEmptyStr, ...]


class EscalationDecided(_Event):
    """The escalation question, asked at an attempt end that did not merge (ARCH-131).

    Carries the decision (the answer, confidence, backend id and latency, and the route)
    and the state it was asked about, so the decision can be audited after the fact. The
    replay holds the state to the one the lines before it imply, the route to the rule,
    and, for the deterministic rules, the answer to the rules' own.
    """

    kind: Literal["escalation_decided"] = "escalation_decided"
    subtask_id: NonEmptyStr
    attempt: Attempt
    decision: Decision
    state: EscalationState


class Escalated(_Event):
    """The subtask is in the approval queue: its attempt end was routed there."""

    kind: Literal["escalated"] = "escalated"
    subtask_id: NonEmptyStr
    item_id: NonEmptyStr


#: A position a person may choose on an item whose kind offers two (``choose``): an arbitration's
#: sizing (the graph's value stands) or domain (the disputing subtask's); a failed contract's
#: producer or consumer (whose merged work stands).
Position = Literal["sizing", "domain", "producer", "consumer"]
#: What a person's decision did when the loop took it (ARCH-133). ``resize``: the subtask waits
#: for sizing's closing pass, ordered to write the domain's value, then returns to the gate.
#: ``reopen``: a merged module's planning subtask takes one more attempt, to conform to the
#: interface of a failed contract.
#: ``release`` and ``end_run``: an approve of the plan's item lets the held run dispatch, a reject
#: ends it with nothing dispatched.
DecisionEffect = Literal[
    "merge", "retry", "fix", "end_subtask", "resize", "reopen", "release", "end_run", "none"
]
#: Why a decision taken did not act. ``record_only_source``: approve or reject on an item whose
#: source neither verb acts on. ``last_rejection_automated``: approve where an automated check,
#: not the reviewer, refused the attempt. ``indicator_in_history``: approve where a review of
#: some attempt of the subtask confirmed a reward-hacking indicator. ``scan_hit``: approve where
#: the scan before review found one no review judged. ``not_bound``: a decision that names no
#: verb, or no view. ``legacy_item``: an item that says nothing of what a verb does.
#: ``held_os_layer_off``: written while a session ran without the OS layer, so its own shell
#: could have written it; it acts once the operator confirms it. ``order_too_long``: a choice that
#: would reopen a module whose order its reviewer could not read whole. ``superseded``: a
#: decision on a contract item another item's reopen superseded, since what it said is no longer
#: true.
WhyNot = Literal[
    "record_only_source",
    "last_rejection_automated",
    "indicator_in_history",
    "scan_hit",
    "not_bound",
    "legacy_item",
    "held_os_layer_off",
    "order_too_long",
    "superseded",
]


class DecisionTaken(_Event):
    """A person's decision on a queue item, taken into the run where no attempt is in progress.

    What it did is computed by code from the item and from the lines before this one
    (``decisions.decision_effect``), never from the decision's words, and replay holds the line
    to what those lines allow. ``decision_offset`` is where the decision's line starts in the
    decisions file, which is what tells a decision written in a session's window from one that
    was not. A held decision is taken twice: once not acting, then once more, confirmed by the
    operator on the command line, naming who.
    """

    kind: Literal["decision_taken"] = "decision_taken"
    #: ``None`` for the integration item, which no subtask owns.
    subtask_id: NonEmptyStr | None
    item_id: NonEmptyStr
    verb: Literal["approve", "reject", "choose"] | None
    #: The position a choice names; left out of every other decision's line, so it keeps its bytes.
    position: Position | None = None
    #: The person's note, verbatim, as the decisions file holds it.
    note: NonEmptyStr | None
    resolved_by: NonEmptyStr
    decided_ts: Timestamp
    decision_offset: Annotated[int, Field(ge=0)]
    shown_sha256: Sha256 | None
    attempt: Annotated[int, Field(ge=1)] | None
    attempt_commit: Sha | None
    effect: DecisionEffect
    acts: bool
    why_not: WhyNot | None
    #: The operator who confirmed a held decision on the command line, by OS user name.
    confirmed_by: NonEmptyStr | None = None
    #: A reject or a choice that would have ordered the one fix, or the next attempt, ends the
    #: subtask instead: what that session's reviewer would be told of the order is longer than one
    #: read shows whole, so its review could not be prepared. Nothing is spawned.
    order_too_long: bool = False
    #: The planning subtask a choice on a failed contract's item reopens, with that effect alone.
    reopens: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _an_act_needs_no_excuse_and_a_non_act_has_one(self) -> DecisionTaken:
        if self.acts == (self.why_not is not None):
            msg = "a decision that acts says no reason it would not, and one that does not says why"
            raise ValueError(msg)
        if self.acts and self.effect == "none":
            msg = "a decision that acts has an effect"
            raise ValueError(msg)
        if self.confirmed_by is not None and not self.acts and self.subtask_id is not None:
            # A held decision on a contract item records only, and its confirmation does too:
            # what it closes is the item, on which a completion waits.
            msg = "a confirmed decision is the one that acts"
            raise ValueError(msg)
        # A choice on a contract item that would reopen a module records only instead.
        ends = self.verb in ("reject", "choose") and self.effect == "end_subtask"
        records = self.verb == "choose" and self.effect == "none" and self.subtask_id is None
        if self.order_too_long and not (ends or records):
            msg = (
                "only a reject or a choice ends a subtask, and a choice on a contract item records "
                "only, for an order its reviewer could not read whole"
            )
            raise ValueError(msg)
        if (self.verb == "choose") != (self.position is not None):
            msg = "a position is chosen with choose, and only with it"
            raise ValueError(msg)
        if (self.effect == "reopen") != (self.reopens is not None):
            msg = "a decision names the subtask it reopens, and only one that reopens does"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_position(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for absent in ("position", "reopens"):
            if getattr(self, absent) is None:
                data.pop(absent, None)
        return data


class SubtaskRejected(_Event):
    """The subtask ends without a merge, and no attempt of it runs again.

    A person rejected it with no attempt left, or the one fix a person ordered after a blocked
    review was not accepted, or sizing's closing pass a person's choice waited on ended without a
    merge (``closing_pass``, naming the item the choice was made on).
    """

    kind: Literal["subtask_rejected"] = "subtask_rejected"
    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1)]
    by: Literal["person", "fix_not_accepted", "closing_pass"]
    item_id: NonEmptyStr | None


#: The fields one kind of reopen carries and the other leaves out: a decision's, then code's.
_REOPEN_EITHER = ("item_id", "shown_sha256", "cause", "owed")


class OwedEdge(BaseModel):
    """An edge a follow-up owes: a node sizing's closing pass changed, and one it constrains."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: NodeIdKey
    target: NodeIdKey


class SubtaskReopened(_Event):
    """A merged module's planning subtask reopens, as a taken decision or the closing pass owes.

    The decision's reopen is the next line about any subtask after the decision on ``item_id``:
    it names that item and the digest of the item line it was taken on. A follow-up is code's
    (``cause``), owed because sizing's closing pass changed a value whose edges reach a node of
    the module that no session wrote after it; it names those edges, sorted, and no decision.
    Either names the subtask's last merge and the attempt it reopens at, its next one or its one
    fix. The earlier merge stays on the record. Each field one kind leaves out is left out of its
    line, so a decision's keeps its bytes.
    """

    kind: Literal["subtask_reopened"] = "subtask_reopened"
    subtask_id: NonEmptyStr
    item_id: NonEmptyStr | None = None
    shown_sha256: Sha256 | None = None
    merge_commit: Sha
    attempt: Attempt
    cause: Literal["follow_up"] | None = None
    owed: tuple[OwedEdge, ...] | None = None

    @model_validator(mode="after")
    def _a_decision_s_or_a_follow_up_s(self) -> SubtaskReopened:
        if any(getattr(self, k) is None for k in self.model_fields_set & set(_REOPEN_EITHER)):
            msg = "a field a reopen does not carry is left out of its line, never null"
            raise ValueError(msg)
        decided = (self.item_id, self.shown_sha256, self.cause, self.owed)
        if None not in decided[:2] and decided[2:] == (None, None):
            return self
        owed = self.owed or ()
        keys = [(e.source, e.target) for e in owed]
        if decided[:2] == (None, None) and self.cause and keys and keys == sorted(set(keys)):
            return self
        msg = "a reopen is a decision's, with its item, or a follow-up's, with its edges sorted"
        raise ValueError(msg)

    @model_serializer(mode="wrap")
    def _omit_record(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for absent in _REOPEN_EITHER:
            if getattr(self, absent) is None:
                data.pop(absent, None)
        return data


class AttemptReturned(_Event):
    """A waiting subtask's disputed attempt returns to the gate once sizing's closing pass merged.

    Its reading, change check, rulings and review run again from its completed session: no new
    session, and no attempt spent, as the attempt was never reviewed. ``item_id`` is the item on
    which a person chose the domain's value.
    """

    kind: Literal["attempt_returned"] = "attempt_returned"
    subtask_id: NonEmptyStr
    attempt: Attempt
    item_id: NonEmptyStr


#: What ended a follow-up's one attempt without a merge.
FollowUpWhy = Literal["rejected", "blocked", "no_verdict", "for_a_person"]


class FollowUpEnded(_Event):
    """A follow-up's one attempt ended without a merge: no retry, and no fix or item follows.

    The module's earlier merge stands, so the subtask is done again, and the integration call
    judges the edges it still owes (ARCH-051). ``why`` is what ended the attempt.
    """

    kind: Literal["follow_up_ended"] = "follow_up_ended"
    subtask_id: NonEmptyStr
    attempt: Attempt
    why: FollowUpWhy


class DispatchHeld(_Event):
    """A subtask's dispatch is held: a subtask it reads from waits on a person, unmerged.

    "Reads from" is the run's recorded contract pairs: ``producer`` is a pair's producing subtask
    whose consumer is ``subtask_id``, over ``interfaces``. The producer is escalated with its item
    ``item_id`` undecided, or is held itself through a chain whose root waits on ``item_id``.
    Written once per held producer, in a run that acts on decisions; the run goes on with what
    does not read from it, and otherwise waits on the queue.
    """

    kind: Literal["dispatch_held"] = "dispatch_held"
    subtask_id: NonEmptyStr
    producer: NonEmptyStr
    item_id: NonEmptyStr
    interfaces: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


#: How a held dispatch was let go, or why one was never held.
#:
#: ``merged``: the producer merged. ``ended_unmerged``: it ended without a merge (rejected,
#: removed, or a decision that acted on nothing), so the subtask runs without its work.
#: ``waits_for_closing_pass``: a person chose the producer's value in a dispute, and its attempt
#: waits for sizing's closing pass, which comes after the subtask. ``mutual_readers``: the two
#: read from each other, so the subtask is dispatched with the producer waiting, and never held.
ReleasedHow = Literal["merged", "ended_unmerged", "waits_for_closing_pass", "mutual_readers"]


class DispatchReleased(_Event):
    """A held dispatch let go, or a dispatch not held although its producer waits on a person.

    ``item_id`` is the item the hold named, or for ``mutual_readers`` the item the producer waits
    on. Every outcome but ``mutual_readers`` closes the one hold of ``subtask_id`` on ``producer``.
    """

    kind: Literal["dispatch_released"] = "dispatch_released"
    subtask_id: NonEmptyStr
    producer: NonEmptyStr
    item_id: NonEmptyStr
    outcome: ReleasedHow


class Incident(_Event):
    """Something the loop cannot answer by itself happened. The run halts after it."""

    kind: Literal["incident"] = "incident"
    #: None when no subtask was active, as for a foreign line found when a run opens.
    subtask_id: NonEmptyStr | None
    cause: IncidentCause
    detail: NonEmptyStr


#: Who resolves an incident by the owner's rule rather than by a person: never a person's name.
RULE = "rule"
#: Why the rule resolves a change: what the change is, in the owner's words.
RULE_REASON = (
    "the change only adds restrictions, each set to allowed: false, which the owner's rule "
    "resolves on the record"
)


class IncidentResolved(_Event):
    """A change of the run's policy limits, resolved on the record, and the new baseline.

    A person resolves a ``managed_settings_changed`` halt at a terminal, naming who and why, and
    the run's resume then accepts it; or the owner's rule resolves a change that only adds
    restrictions set to ``allowed: false`` as the session ends, and the run goes on. Either way
    the line carries both digests and the change by key and value: every later session is held to
    the new limits, and the baseline moves by this line alone.
    """

    kind: Literal["incident_resolved"] = "incident_resolved"
    subtask_id: NonEmptyStr | None
    #: The session whose end showed the change.
    session_id: NonEmptyStr
    cause: Literal["managed_settings_changed"] = "managed_settings_changed"
    by: NonEmptyStr
    reason: NonEmptyStr
    #: Whether the owner's rule resolved it, with no person.
    rule: bool
    old_sha256: Sha256 | None
    new_sha256: Sha256 | None
    changes: tuple[PolicyEntry, ...]
    #: How many more keys differ than :attr:`changes` lists.
    omitted: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def _as_resolved(self) -> IncidentResolved:
        if self.rule != (self.by == RULE):
            msg = f"the rule, and only the rule, resolves as {RULE!r}"
            raise ValueError(msg)
        if self.old_sha256 == self.new_sha256:
            msg = "a resolution moves the policy limits to other ones"
            raise ValueError(msg)
        if self.rule and (
            None in (self.old_sha256, self.new_sha256)
            or not stricter_only(self.changes, self.omitted)
        ):
            msg = "the rule resolves only a change that adds restrictions set to allowed: false"
            raise ValueError(msg)
        return self


class SessionFinding(BaseModel):
    """One thing a session's end showed that a person must look at, as its incident says it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    cause: IncidentCause
    detail: NonEmptyStr


class FindingsRecorded(_Event):
    """Every finding of one session's end, or of a resume's leftovers, before any incident of them.

    Written where there are two or more, so a process killed between their incidents, or before
    their one halt, leaves the rest on the record: the next process writes the incidents still
    missing, in this order, and then the halt under ``halt``, the cause the site's own rule picks.
    Left out where there is one, so such a log keeps its bytes; a log written before the line
    existed has none and replays as it did.
    """

    kind: Literal["findings_recorded"] = "findings_recorded"
    #: None for the leftovers a resume found, which belong to no subtask.
    subtask_id: NonEmptyStr | None
    findings: Annotated[tuple[SessionFinding, ...], Field(min_length=2, max_length=64)]
    halt: IncidentCause


class Followable(BaseModel):
    """The interfaces the role that owns the cross nodes produces, as the decomposition wrote them.

    Only these follow that role's opening pass, and only that role's change check follows them:
    replay holds each followed line to ``role`` and the interface it revises to the digest of the
    payload the store held for it here. The role is the register's when the line is written,
    never when it is read, as a planning line's completion mark is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role: NonEmptyStr
    payload_sha256: Annotated[dict[NodeIdKey, Sha256], Field(min_length=1)]


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
    #: The digest of the policy limits the call received, ``None`` if none: the
    #: baseline every session of the run is held to.
    policy_limits_sha256: Sha256 | None = None
    #: The binary's served catalog and remote feature flags as the call's debug log
    #: showed them; ``None`` for a run started with no call.
    observed_traffic: ObservedTraffic | None = None
    #: The flag cache the call left, the run's first reading; not written where none.
    flag_cache: FlagCache | None = Field(default=None, exclude_if=lambda v: v is None)
    #: sha256 of the plan's canonical JSON, every field of its own form in it, taken from
    #: the plan itself. ``None`` on a line written before the digest was recorded.
    plan_sha256: Sha256 | None = None
    #: The consumers of each interface node and the system requirements, as the plan of a
    #: run with the integration role gives them; ``None`` in a run without that role. Typed
    #: with the plan's own models, so a line read back is held to every bound the plan was,
    #: and to the plan's rules across the two lists and the line's own interface nodes.
    interface_consumers: tuple[InterfaceConsumers, ...] | None = None
    system_requirements: SystemRequirements | None = None
    #: The brief's own words for each system requirement the plan gives by the brief's criterion
    #: number, in the list's order; left out when there are none. Taken from the brief the call
    #: was given, which the record holds by its digest alone.
    brief_words: tuple[CriterionWords, ...] | None = None
    #: The interfaces the role that owns the cross nodes produces, each by the digest of its
    #: payload as the store held it; left out where that role produces none, or no one role owns
    #: the cross nodes, and then no interface follows.
    followable: Followable | None = None

    @model_validator(mode="after")
    def _the_followable_interfaces_are_its_own(self) -> Decomposed:
        if self.followable is not None and not set(self.followable.payload_sha256) <= set(
            self.interface_nodes
        ):
            msg = "a followable interface is an interface node of the plan"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _both_lists_or_neither(self) -> Decomposed:
        if (self.interface_consumers is None) != (self.system_requirements is None):
            msg = "a plan gives integration both of its lists, or neither"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _the_lists_hold_the_plan_s_rules(self) -> Decomposed:
        # The rules the plan check held the lists to that need no module and no brief: the
        # line carries neither, but it carries the interface nodes the entries are for.
        if self.interface_consumers is not None and self.system_requirements is not None:
            problems = list_problems(
                self.interface_nodes, self.interface_consumers, self.system_requirements
            )
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _the_words_are_the_requirements(self) -> Decomposed:
        if self.brief_words is not None:
            problems = words_problems(self.system_requirements or (), self.brief_words)
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Left out when absent, so a line without them is written exactly as before they existed.
        data: dict[str, Any] = handler(self)
        for name in (
            "plan_sha256",
            "interface_consumers",
            "system_requirements",
            "brief_words",
            "followable",
            "flag_cache",
        ):
            if data.get(name) is None:
                data.pop(name, None)
        return data


class PlanProposed(_Event):
    """One round's call, written in the run's opening after the tokens it spent (ARCH-060).

    A run that reviews its plan writes one per round, the last included: the round, the call's own
    session, the model that answered and its turns, and the plan's digest or why the round has no
    plan it could start. ``started`` and ``ended`` are the call's, measured as it ran, because every
    line of the opening is written together when the rounds have ended. Replay ties the round's
    call tokens to its session, and the round's review to its digest.
    """

    kind: Literal["plan_proposed"] = "plan_proposed"
    round: Annotated[int, Field(ge=1)]
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    model: NonEmptyStr | None
    num_turns: Annotated[int, Field(ge=0)]
    plan_sha256: Sha256 | None = None
    #: Why the round has no plan it could start; ``None`` exactly when it has one.
    cause: NonEmptyStr | None = None
    started: Timestamp
    ended: Timestamp
    #: The round's first call, or its second: made once, when the first's output was refused
    #: by its schema. Left out of the line for a first call.
    call: Literal[1, 2] = 1

    @model_validator(mode="after")
    def _a_plan_or_why_not(self) -> PlanProposed:
        if (self.plan_sha256 is None) == (self.cause is None):
            msg = "a round proposes a plan by its digest, or says why it has none, and never both"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for absent in ("plan_sha256", "cause"):
            if data.get(absent) is None:
                data.pop(absent, None)
        if data.get("call") == 1:
            data.pop("call", None)
        return data


#: The one cause a decomposition call is made again for: its output refused by its schema.
RETRIED_CAUSE: Literal["schema_refused"] = "schema_refused"


class DecompositionRetried(_Event):
    """A run that does not review its plan made its call again, once: the first was refused.

    Written in the opening after the refused call's tokens and before the second call's: the
    refused call's session and why. A second refusal fails the decomposition; nothing else is
    retried, and no call a third time.
    """

    kind: Literal["decomposition_retried"] = "decomposition_retried"
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    cause: Literal["schema_refused"]
    detail: NonEmptyStr


class DesignUnavailable(BaseModel):
    """Why the plan's review is not a verdict: its cause, and the session that spent on it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    cause: UnavailableCause
    detail: NonEmptyStr
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")] | None
    reviewer_model: NonEmptyStr | None
    #: What the review found the specification lacks, as an attempt's no-verdict line keeps it;
    #: left out when it found nothing, so such a line keeps its bytes.
    spec_defects: tuple[SpecDefect, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_none_found(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if not self.spec_defects:
            data.pop("spec_defects", None)
        return data


class DesignReviewRan(_Event):
    """What the design reviewer came to on the plan, written in the run's opening (ARCH-060).

    The review runs after the one call and before anything of the run is written, so its line is
    the opening's last: after the plan it judged, before any dispatch. It names the plan by the
    digest the decomposition's line carries and the call's stream by the seal the review held it
    to, and gives either the verdict or why there is none. What the review spent is attributed to
    its own session on the lines before it.
    """

    kind: Literal["design_review_ran"] = "design_review_ran"
    plan_sha256: Sha256
    stream_seal: Seal
    result: ReviewResult | None = None
    unavailable: DesignUnavailable | None = None
    #: The plan's item every dispatch is held on, under ``on`` where the review did not pass.
    held_item: NonEmptyStr | None = None
    #: The round reviewed, and the review's own start and end, measured as it ran; replay requires
    #: them, and reads the round's proposal by its number.
    round: Annotated[int, Field(ge=1)] | None = None
    started: Timestamp | None = None
    ended: Timestamp | None = None

    @model_validator(mode="after")
    def _a_verdict_or_why_there_is_none(self) -> DesignReviewRan:
        if (self.result is None) == (self.unavailable is None):
            msg = "a plan's review gives a verdict or why there is none, and never both"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for absent in ("result", "unavailable", "held_item", "round", "started", "ended"):
            if data.get(absent) is None:
                data.pop(absent, None)
        return data


class PlanRejected(_Event):
    """A person rejected the plan its review held the run on: nothing of it is dispatched."""

    kind: Literal["plan_rejected"] = "plan_rejected"
    item_id: NonEmptyStr


class ContractPairsPlanned(_Event):
    """The module pairs whose interface contract the run tests, read from its plan.

    Written once, in the run's opening after the planning lines, and only in a run whose plan
    names the consumers of its interfaces (one with the integration role), so the set is on the
    record before any module runs and nothing a module writes can shape it. Replay holds it to
    the plan's recorded lines and refuses a dispatch before it.
    """

    kind: Literal["contract_pairs_planned"] = "contract_pairs_planned"
    pairs: Annotated[tuple[ContractPair, ...], Field(min_length=1)]


class ContractTested(_Event):
    """A pair's interface contract, held to the clause after a merge in one of its modules.

    Owed once both subtasks the pair names have merged with a clean diff, and again after every
    later clean merge in either module's directory, as sizing's closing pass is one; the pair's
    first line is marked ``first`` and no later one is (ARCH-051). A record, never a block: the
    merge that owed it stands whatever the outcome, and a failed contract withholds completion
    alone. ``commit`` is the run branch's head and ``revision`` the canonical journal's, at which
    the graph was read.
    """

    kind: Literal["contract_tested"] = "contract_tested"
    result: ContractResult
    first: bool
    commit: Sha
    revision: Annotated[int, Field(ge=1)]


class IntegrationStateIssued(_Event):
    """Integration's issued state, by digest and length, before its session is spawned.

    The document is built by code from the run's record alone (the gate mode, the system-scope
    result, each planned pair's contract results, the system requirements with the brief's words)
    and handed to the session as required reading and to its reviewer in the packet. One line in
    each window between the attempt's ``resolve`` and its ``spawn``: a restarted window records
    its own. Replay holds the line to its place and its form; the loop holds the bytes, rebuilding
    them from the record before the spawn and before the review.
    """

    kind: Literal["integration_state_issued"] = "integration_state_issued"
    subtask_id: NonEmptyStr
    attempt: Attempt
    sha256: Sha256
    length: Annotated[int, Field(ge=1)]


class CompletionDeclared(_Event):
    """What an attempt of integration's subtask declares complete, read from its checked commit.

    One line per attempt of the subtask marked as the completion owner's, straight after that
    attempt's accepted change check and before its gate: the plan modules the declaration names
    complete, each by the subtask that planned it, in plan order, and the digest of the
    declaration as that commit holds it. A module it leaves out is one integration did not
    declare complete. No module is recorded complete that the merged attempt's line does not
    name (ARCH-051).
    """

    kind: Literal["completion_declared"] = "completion_declared"
    subtask_id: NonEmptyStr
    attempt: Attempt
    modules: tuple[NonEmptyStr, ...]
    declaration_sha256: Sha256


class DisputeRecorded(_Event):
    """A dispute an attempt holds, read from its checked commit: a position, and its reason.

    One line per dispute, straight after the attempt's accepted change check and before its
    gate, sorted by node and quantity. The position is a quantity of a cross node, in the
    disputing role's own value and unit. The reason is the session's text, kept for a person.
    The run keeps it here: the file stays on its attempt's branch, left out of the merge and of
    the reviewer's packet.
    """

    kind: Literal["dispute_recorded"] = "dispute_recorded"
    subtask_id: NonEmptyStr
    attempt: Attempt
    position: QuantityRef
    reason: NonEmptyStr

    @model_validator(mode="after")
    def _as_the_parser_reads_one(self) -> DisputeRecorded:
        # The parser refuses these characters in a dispute's unit and reason, so no line the
        # loop writes holds one, and a line that does was written by something else.
        if not (plain(self.position.unit) and plain(self.reason)):
            msg = "a dispute's unit and reason hold only characters the dispute parser takes"
            raise ValueError(msg)
        return self


class ArbitrationDecided(_Event):
    """A dispute ruled by the precedence table, after the attempt's gate line (ARCH-040).

    One line per dispute of the attempt, in the order the disputes were recorded. ``standing`` is
    what the record gave when it was ruled, and ``level`` the row of the table that decided; the
    replay builds the standing again from the lines before this one and rules it again. ``held``
    is sizing's position, the quantity as the graph held it, so the record alone states both
    positions; the dispute's reason is on its own line and never on this one.
    """

    kind: Literal["arbitration_decided"] = "arbitration_decided"
    subtask_id: NonEmptyStr
    attempt: Attempt
    conflict: DisputeConflict
    standing: Standing
    level: Level
    held: Held


class ContractValue(BaseModel):
    """A quantity of a node as the canonical journal held it, and the revision of its line."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    position: QuantityRef
    revision: Annotated[int, Field(ge=1)]


class ContractRuled(_Event):
    """A failed clause of a pair's contract, ruled by the precedence table (ARCH-040).

    One line per failed clause of the latest contract result, which failed, in the result's
    order, straight after it. ``wanted`` is the interface's quantity and ``found`` each joined node
    that fails the clause and carries the quantity, as the journal held them at the result's
    revision: the record alone states both positions, and never a node's free-text provenance. A
    clause the gate refused is the gate's; any other goes to a person. Sizing's level never rules
    an interface quantity, which is no sizing quantity.
    """

    kind: Literal["contract_ruled"] = "contract_ruled"
    conflict: ContractConflict
    standing: Standing
    level: Level
    wanted: ContractValue | None
    found: tuple[ContractValue, ...]

    @model_validator(mode="after")
    def _the_values_are_the_clause_s(self) -> ContractRuled:
        quantity = self.conflict.quantity
        if (self.wanted is None) != (quantity is None) or (
            self.wanted is not None
            and (self.wanted.position.node_id, self.wanted.position.name)
            != (self.conflict.interface, quantity)
        ):
            msg = "a ruled clause holds the interface's own quantity, and only a clause holds one"
            raise ValueError(msg)
        if any(value.position.name != quantity for value in self.found):
            msg = "a ruled clause holds its nodes' values of its own quantity"
            raise ValueError(msg)
        return self


class ContractItemRaised(_Event):
    """A failed contract sent to a person: the item listed for the latest result, which failed.

    Written once the result's clauses are ruled and one of them went to a person, after the item
    is in the queue, while the pair has no item a decision has not yet been taken on.
    """

    kind: Literal["contract_item_raised"] = "contract_item_raised"
    item_id: NonEmptyStr


class ModuleCompleted(_Event):
    """A module of the plan recorded complete, which merged alone never says (ARCH-051).

    ``subtask_id`` is the subtask that planned the module; ``declared_by`` and ``attempt`` are
    integration's subtask and its attempt that merged, whose declaration names the module.
    Written only once that attempt merged and its diff found nothing, one line per module in
    plan order, and only while every precondition of completion holds for the module.
    """

    kind: Literal["module_completed"] = "module_completed"
    subtask_id: NonEmptyStr
    declared_by: NonEmptyStr
    attempt: Attempt


def flag_cache_readings(events: Iterable[_Event]) -> tuple[FlagCache, ...]:
    """Every flag cache a run's sessions left, in the order the log holds them.

    The decomposition call's, each role session's, and each invocation of each review's
    session, whether or not the review gave a verdict.
    """
    found: list[FlagCache | None] = []
    for event in events:
        if isinstance(event, (Decomposed, SessionEnded)):
            found.append(event.flag_cache)
        elif isinstance(event, ReviewRan):
            found.extend(m.flag_cache for m in event.result.managed)
        elif isinstance(event, ReviewUnavailable):
            found.extend(m.flag_cache for m in event.managed)
    return tuple(r for r in found if r is not None)


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


class InstallChecked(_Event):
    """The hooks' installation was checked against its build, or built, and how long it took.

    Checked at every run and resume before anything is spawned; the time is the
    run's, not a session's. ``entries`` is the size of the manifest it was held to.
    """

    kind: Literal["install_checked"] = "install_checked"
    path: NonEmptyStr
    action: Literal["checked", "built"]
    seconds: Annotated[float, Field(ge=0)]
    entries: Annotated[int, Field(ge=0)]


class OsLayerChecked(_Event):
    """Where this process runs the run's sessions, whether the OS layer runs, and if not why.

    Recorded at every run and resume before anything is spawned. ``as_recorded`` says
    whether the state is the one the run's configuration recorded when it was set up
    (``None`` for a run recorded before that was measured); a run that moves between
    machines says so here rather than silently.
    """

    kind: Literal["os_layer_checked"] = "os_layer_checked"
    state: OsLayerState
    as_recorded: bool | None
    #: For a run that asks for ``network: none``: whether the layer here enforces it.
    #: ``False`` records "network: none requested, not enforceable here", since only the
    #: OS layer refuses a shell remote hosts. ``None`` for ``open``, and on a line written before.
    network_enforced: bool | None = None
    #: For a run that asks for ``network: none``: the TCP ports listening where the
    #: machine's loopback reaches them, at this check. The layer keeps an offline session
    #: from them; this says what was there. ``None`` for ``open``, where it was not read,
    #: and on a line written before.
    loopback_listeners: tuple[int, ...] | None = None
    #: Whether that listing was read: ``False`` when it could not be, which is never
    #: taken for "nothing listens". ``None`` for ``open``, and on a line written before.
    loopback_listeners_read: bool | None = None
    #: Where the layer is absent: ``True`` when the run's parameters allow role sessions
    #: without it, for development (``os_layer_absent: allow``), and the run goes on;
    #: ``False`` when nothing allows it, and the run is refused before any session. ``None``
    #: where the layer runs, and on a line written before.
    absent_allowed: bool | None = None


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


class SessionSpawned(_Event):
    """A role session's process, recorded before it runs anything: its pid and start time.

    Written while the spawned process still waits to start the binary, so no session has run
    before the line is on disk. A resume honours a session's process record only if it
    agrees with this line; the record is a file the session's own user can write.
    """

    kind: Literal["session_spawned"] = "session_spawned"
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    pid: Annotated[int, Field(ge=1)]
    started: NonEmptyStr


class LeftoverRead(_Event):
    """What a resume read of a session a previous orchestrator left without an end.

    Its stream was sealed as read, and its usage recorded from the same bytes,
    partial if the stream holds no result. The decisions file's length closes the
    session's window.
    """

    kind: Literal["leftover_read"] = "leftover_read"
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    stopped: bool
    complete: bool
    trajectory_seal: Seal | None
    decisions_bytes: Annotated[int, Field(ge=0)] | None = None
    #: A stream that was gone is quarantined only by a person's marker: who and why. Its
    #: scan is then recorded as not made, never as one that found nothing.
    quarantine: NonEmptyStr | None = None
    scan: Literal["scanned", "unscanned (stream gone)"] = "scanned"


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
    #: The operator who said on the command line that the account's usage limit has reset, for a
    #: resume of a run waiting on a limit whose reset could not be read.
    limit_reset_by: NonEmptyStr | None = None

    @model_serializer(mode="wrap")
    def _omit_no_word(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Every other resume is written byte for byte as before.
        data: dict[str, Any] = handler(self)
        if self.limit_reset_by is None:
            data.pop("limit_reset_by", None)
        return data


Event = Annotated[
    RunStarted
    | SubtaskPlanned
    | SubtaskRemoved
    | StageEntered
    | DecisionsSealed
    | GateRan
    | GateSkipped
    | IntegrationGateRan
    | IntegrationGateSkipped
    | IntegrationEscalated
    | ReviewRan
    | ReviewUnavailable
    | TokensUsed
    | SessionEnded
    | InfraRetryScheduled
    | ProposalsChecked
    | AttemptRejected
    | Merged
    | DiffChecked
    | EscalationDecided
    | Escalated
    | DecisionTaken
    | SubtaskRejected
    | SubtaskReopened
    | AttemptReturned
    | FollowUpEnded
    | DispatchHeld
    | DispatchReleased
    | FindingsRecorded
    | Incident
    | IncidentResolved
    | Resumed
    | Decomposed
    | DecompositionRetried
    | PlanProposed
    | DesignReviewRan
    | PlanRejected
    | ContractPairsPlanned
    | ContractTested
    | IntegrationStateIssued
    | CompletionDeclared
    | DisputeRecorded
    | ArbitrationDecided
    | ContractRuled
    | ContractItemRaised
    | ModuleCompleted
    | EnvironmentRecorded
    | InstallChecked
    | OsLayerChecked
    | LeftoverStopped
    | SessionSpawned
    | LeftoverRead
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
    path: Path | bytes, parse: Callable[[bytes], T]
) -> tuple[list[T], int, tuple[int, str] | None]:
    """Parse every complete line of ``path``, or of the bytes given in its place.

    Bytes are for a reader that opened the file itself, through a descriptor it checked,
    and must parse exactly what it read rather than reopen the file by name.

    Returns the parsed records, the byte offset where the good records end, and
    the offset and reason of the first complete line that did not parse, if any.
    A final line without its terminator is not parsed and not an error: it is a
    write that was still in progress. Reading stops at the first bad line, since
    whatever follows a record no writer of this package produced is not trusted.
    ``parse`` raises ``ValueError`` (``ValidationError`` is one) to refuse a line.
    """
    records: list[T] = []
    good_end = 0
    with path.open("rb") if isinstance(path, Path) else io.BytesIO(path) as handle:
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
        #: Each planned subtask's role, by subtask.
        self.planned: dict[str, str] = {}

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
        if isinstance(event, GateRan | IntegrationGateRan) and event.result.mode != mode:
            msg = (
                f"a gate result in mode {event.result.mode!r} in a run whose gate mode is {mode!r}"
            )
            raise ValueError(msg)
        if isinstance(event, GateSkipped) and mode != "off":
            msg = f"the gate was skipped in a run whose gate mode is {mode!r}"
            raise ValueError(msg)
        # A rejected plan is skipped in any mode, naming every subtask it planned (the run's rule).
        if isinstance(event, IntegrationGateSkipped) and event.reason != "plan_rejected":
            if (event.reason == "gate_mode=off") != (mode == "off"):
                msg = (
                    f"integration skipped as {event.reason!r} in a run whose gate mode is {mode!r}"
                )
                raise ValueError(msg)
            if (event.reason == "not_all_merged") != bool(event.subtasks):
                msg = "an incomplete design names the subtasks that did not merge, and only then"
                raise ValueError(msg)

    def record(self, event: _Event) -> None:
        """Take ``event`` as the next line. Call only after :meth:`check` passed."""
        if self.run is None:
            self.run = (event.run_id, event.gate_mode)
        if isinstance(event, SubtaskPlanned):
            self.planned[event.subtask_id] = event.assigned_role
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


def _admit(context: _Context, state: RecordState | None, event: _Event) -> Event:
    """``event``, if the writer may write it next; raise ``ValueError`` if not.

    What every line is held to before it is written: its place among the lines before it, and in
    a log that follows a run state, a planning line's mark and a completion's declaring subtask
    against the role register, and the line against the state. Nothing is recorded.
    """
    if isinstance(event, ReviewUnavailable) and event.cause == "blocking_spec_defect":
        msg = "a blocked review is written as a review line, never as one with no verdict"
        raise ValueError(msg)
    context.check(event)
    if state is not None and isinstance(event, SubtaskPlanned):
        # A run's plan, held to the register as it is written, and only then: replay reads
        # the mark. An instrument's own log (a generalist review, an injected corpus) follows
        # no run, and plans an artefact of any role; the mark is no part of it.
        why = completion_mark_problem(event.assigned_role, marked=event.owns_completion is not None)
        if why is not None:
            raise ValueError(why)
    if state is not None and isinstance(event, CompletionDeclared | ModuleCompleted):
        # So is a run's completion: the subtask that declares it is of the one role the register
        # names as owning completion now. Replay reads the planning line's mark instead.
        declaring = event.subtask_id if isinstance(event, CompletionDeclared) else event.declared_by
        why = completion_owner_problem(context.planned.get(declaring))
        if why is not None:
            raise ValueError(why)
    admitted = cast("Event", event)
    if state is not None:
        state.check(admitted)
    return admitted


def require_writable(lines: Iterable[Event], state: RecordState) -> None:
    """Raise ``ValueError`` unless ``lines``, in order, may open a log that ``state`` follows.

    Each line is held to every check the writer holds a line to, as if the lines before it had
    been written, so a run whose opening any of those checks would refuse part way is refused
    before its first line. Nothing is written; ``state``, fresh, follows the lines and is the
    caller's to discard.
    """
    context = _Context()
    for line in lines:
        admitted = _admit(context, state, line)
        context.record(line)
        state.record(admitted)


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
    return _events_of(Path(path), str(path))


def parse_events(data: bytes, *, log: str) -> list[Event]:
    """Every event in ``data``, an event log's bytes read by the caller; ``log`` names it.

    Raises:
        CorruptEventLogError: as :func:`read_events`.
    """
    return _events_of(data, log)


def _events_of(source: Path | bytes, log: str) -> list[Event]:
    events, _, corrupt = read_jsonl(source, _parse_in(_Context(), None))
    if corrupt is not None:
        offset, reason = corrupt
        msg = "the run-event log holds a line this package could not have written"
        raise CorruptEventLogError(msg, log=log, offset=str(offset), reason=reason)
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
        account: WriteAccount | None = None,
    ) -> None:
        """Open or create the log at ``path`` for ``run_id``.

        ``state``, if given, follows every line read at open and every line
        written after, and can refuse one; the loop passes its run state here.
        ``account`` is the run's write account, which names every line before it is written.

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
        #: How many lines the log held when this handle opened it: the rest are its own.
        self.read_at_open = len(events)
        self._handle = self.path.open("ab")
        #: What this handle knows of its file, held to the path before every append.
        self.held = HeldFile(self.path, self._handle.fileno(), account)

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
                sequence number that is not the next one; or it is a review with
                no verdict carrying the legacy blocked cause, which is only read.
            RecordMovedError: the log is no longer the file this handle holds, at the size it
                wrote; nothing is written.
        """
        admitted = _admit(self._context, self._state, event)
        # A log replaced beneath this handle, or written by another, is written no more: a line
        # here would land where no path names it, or after a line this writer never wrote.
        self.held.require_current()
        payload = event.model_dump_json().encode() + b"\n"
        self.held.intend(payload)
        self._handle.write(payload)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.held.wrote(payload)
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
