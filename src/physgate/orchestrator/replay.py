"""Where a run stands, derived from its event log and from nothing else.

``RunState`` follows the log line by line. It is handed to the log as its
record state, so it refuses a line that cannot come next at write time and at
replay alike: the stages of an attempt in the architecture's order (ARCH-030),
no review before a gate result that allows one, no merge without a passing
review, no attempt past the budget, nothing after a halt. A killed orchestrator
therefore resumes from exactly where its file says it was, and a file that
could not have been written by this loop does not open.

The task ledger is projected from the same state: one line per change of a
subtask's state, with the fields ARCH-012 names. The merge precondition reads
that ledger back from disk, not from memory.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn

from pydantic import ValidationError

from physgate.contracts.pairs import ContractPair, recorded_pairs_problem
from physgate.orchestrator.arbitration import Held, arbitrate, dispute_standing
from physgate.orchestrator.budget import REPAIR_BUDGET, after_rejection
from physgate.orchestrator.common import GateMode
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.decisions import require_taken, values_chosen
from physgate.orchestrator.escalation import (
    REGISTER,
    TO_THE_QUEUE,
    BackendAnswer,
    RulesBackend,
    forced,
    route,
)
from physgate.orchestrator.escalation_state import EscalationState, escalation_state
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    ArbitrationDecided,
    AttemptRejected,
    AttemptReturned,
    CompletionDeclared,
    ContractPairsPlanned,
    ContractTested,
    DecisionsSealed,
    DecisionTaken,
    Decomposed,
    DiffChecked,
    DisputeRecorded,
    EnvironmentRecorded,
    Escalated,
    EscalationDecided,
    Event,
    GateRan,
    GateSkipped,
    Halted,
    Incident,
    InfraRetryScheduled,
    InstallChecked,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    IntegrationStateIssued,
    LeftoverRead,
    LeftoverStopped,
    Merged,
    ModuleCompleted,
    NodeFilesRepaired,
    OsLayerChecked,
    ProposalsChecked,
    Resumed,
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SessionEnded,
    SessionSpawned,
    Stage,
    StageEntered,
    SubtaskPlanned,
    SubtaskRejected,
    SubtaskRemoved,
    TokensUsed,
    WorktreeRemoved,
    WriteDone,
    WriteIntended,
    read_events,
)
from physgate.orchestrator.exceptions import (
    CorruptEventLogError,
    EscalationBackendError,
    MergePreconditionError,
    QueueError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.plan import INTEGRATION_MODULE_DIR, CriterionWords, SystemRequirement
from physgate.orchestrator.protocols import ChosenValue, QuantityRef
from physgate.orchestrator.queue import item_id_for
from physgate.orchestrator.repair import FindingSource
from physgate.orchestrator.run_config import load_run_config
from physgate.state.task_ledger import TaskLedger, TaskLine, read_ledger


@dataclass
class AttemptState:
    """One implementation attempt of one subtask."""

    number: int
    cursor: Stage | None = None
    session: SessionEnded | None = None
    #: Every session this attempt ran, in order, as each ended. Never forgotten by a
    #: restart: an infrastructure retry's earlier sessions are part of the attempt.
    ended: list[SessionEnded] = field(default_factory=list)
    retries_done: int = 0
    changes: ProposalsChecked | None = None
    #: What the attempt declared complete, for integration's subtask: read after its change check.
    declaration: CompletionDeclared | None = None
    #: The disputes the attempt holds, in the order recorded: read after its change check.
    disputes: list[DisputeRecorded] = field(default_factory=list)
    gate: GateRan | GateSkipped | None = None
    #: Each dispute's ruling, in the disputes' order: written after the gate line.
    arbitrations: list[ArbitrationDecided] = field(default_factory=list)
    #: The journal head each ruling was made at, in the same order.
    ruled_at: list[int] = field(default_factory=list)
    review: ReviewRan | None = None
    #: A review that was not a verdict: retried once for infrastructure, otherwise final.
    unavailable: list[ReviewUnavailable] = field(default_factory=list)
    rejected: AttemptRejected | None = None
    merged: Merged | None = None
    diff: DiffChecked | None = None
    #: Nodes this attempt wrote into the canonical store, by revision. Kept across
    #: a resume: they are in the store, and a resumed apply must not write them twice.
    applied: dict[str, int] = field(default_factory=dict)
    pending: WriteIntended | None = None
    #: Whether the attempt's end goes to the approval queue: the recorded decision's
    #: route, or on a log written before the escalation interface, the route the rules
    #: give. ``None`` until the attempt has ended without a merge and been decided.
    routed: bool | None = None
    decided: EscalationDecided | None = None
    #: Whether this attempt is the one fix a person ordered after a blocked review (ARCH-133).
    fix: bool = False
    #: A person's approve that is merging this attempt.
    approved: DecisionTaken | None = None
    #: A person's reject that spent this attempt: the next attempt, the fix, or the end follows.
    person_rejected: DecisionTaken | None = None
    #: Integration's issued state, recorded in this window before its session was spawned.
    issued: IntegrationStateIssued | None = None
    #: A person's choice of the domain's value that resized this attempt; never forgotten by a
    #: restart.
    resized: DecisionTaken | None = None

    def restart(self, cursor: Stage | None) -> None:
        """Forget everything the attempt did after ``cursor``."""
        order: list[Stage | None] = [None, "resolve", "spawn", "verify_reading", "implement"]
        if order.index(cursor) < order.index("spawn"):
            self.session = None
            self.issued = None
        self.changes = self.gate = self.review = None
        self.declaration = None
        self.disputes = []
        self.arbitrations = []
        self.ruled_at = []
        self.unavailable = []
        self.cursor = cursor

    @property
    def blocked(self) -> ReviewRan | None:
        """The review that blocked the attempt, if one did: a person decides, no attempt spent."""
        review = self.review
        return review if review is not None and review.result.verdict == "blocked" else None

    @property
    def queued(self) -> bool:
        """Every dispute ruled, one of them for a person: the attempt ends there (level 3)."""
        ruled = len(self.arbitrations) == len(self.disputes)
        return ruled and any(line.level == "queue" for line in self.arbitrations)

    @property
    def unavailable_final(self) -> ReviewUnavailable | None:
        """The review outcome that sends the attempt to a person, if there is one."""
        last = self.unavailable[-1] if self.unavailable else None
        return last if last is not None and not last.retry else None


@dataclass
class SubtaskState:
    """One planned subtask and every attempt made at it."""

    plan: SubtaskPlanned
    status: Literal["planned", "removed", "active", "waiting", "done", "escalated", "rejected"] = (
        "planned"
    )
    attempts: list[AttemptState] = field(default_factory=list)
    #: The attempt number a ``resolve`` may start or restart now, if any.
    next_resolve: int | None = 1
    #: The approval-queue item an escalated subtask waits on.
    queue_item: str | None = None
    #: How many times the subtask has gone to the queue: its next item's round is one more.
    rounds: int = 0
    #: Whether the next attempt is the fix a person ordered.
    fix_next: bool = False
    #: Every review line of the subtask, in order, never forgotten: the history the
    #: reward-hacking indicator rule reads, which a resumed attempt's restart must not reset.
    reviews: list[ReviewRan] = field(default_factory=list)
    #: Why the subtask is ending without a merge, until its ``subtask_rejected`` line is written.
    ending: Literal["person", "fix_not_accepted"] | None = None
    #: The domain's values a person chose on the subtask's items, for sizing's closing pass to
    #: write: what the attempt's rulings are held to when it returns.
    chosen: list[ChosenValue] = field(default_factory=list)


@dataclass(frozen=True)
class Step:
    """What the loop does next."""

    kind: Literal[
        "attempt",
        "infra_failed",
        "decide",
        "escalate",
        "end_subtask",
        "integrate",
        "complete",
        "contract",
        "halt",
        "halted",
        "escalated",
        "wait",
        "return",
        "done",
    ]
    subtask_id: str | None = None
    attempt: int | None = None
    point: Literal["resolve", "verify_reading", "merge", "diff"] | None = None


def at_a_boundary(step: Step) -> bool:
    """Where a person's decision may be taken: no attempt in progress, none half judged.

    Between subtasks, at the integration call, or at the end of the run (ARCH-133). The loop
    takes decisions only where this holds, and the replay refuses one taken anywhere else.
    """
    if step.kind in ("integrate", "done", "escalated", "wait"):
        return True
    return step.kind == "attempt" and step.point == "resolve"


def _refuse(message: str) -> NoReturn:
    raise ValueError(message)


def _same(a: QuantityRef, b: QuantityRef) -> bool:
    """The same value exactly, in a unit the gate's parser reads as the same items."""
    from physgate.gate.units import UnitRefusedError, parse

    try:
        return a.value == b.value and parse(1, a.unit).unit_items() == parse(1, b.unit).unit_items()
    except UnitRefusedError:
        return False


def _item_id(run_id: str, subtask_id: str, round_: int) -> str:
    try:
        return item_id_for(run_id, subtask_id, round_)
    except QueueError as exc:
        _refuse(str(exc))


class RunState:
    """A run's position, rebuilt by following its event log."""

    def __init__(self) -> None:
        """An empty run: nothing started."""
        self.gate_mode: GateMode | None = None
        #: The escalation backend the run's first line names; ``None`` on a log written
        #: before the escalation interface existed.
        self.escalation_backend: str | None = None
        #: Whether the run acts on a person's decisions, as its first line says.
        self.acts = False
        self.order: list[str] = []
        self.subtasks: dict[str, SubtaskState] = {}
        self.halted: Halted | None = None
        #: The last halt on the record, kept when a resume takes the run up again.
        self.last_halt: Halted | None = None
        self.incident: Incident | None = None
        self.ledger: list[TaskLine] = []
        #: The newest canonical journal revision the orchestrator accounts for: the
        #: decomposition's head, then each recorded write. Anything after it that no
        #: pending intent names is a foreign write.
        self.journal_head = 0
        #: The decomposition's journal head, and each node's latest recorded write: what a ruling's
        #: held revision is held to; and each recorded write by the revision it put.
        self.base_revision = 0
        self.written: dict[str, WriteDone] = {}
        self.by_revision: dict[int, WriteDone] = {}
        #: Subtasks whose worktree removal was tried, whatever came of it: a refused
        #: removal is left, not retried or forced.
        self.worktrees_handled: set[str] = set()
        #: The integration call's line, once every planned subtask but integration's own is
        #: resolved, and the escalation a blocking failure there led to.
        self.integration: IntegrationGateRan | IntegrationGateSkipped | None = None
        self.integration_escalated: IntegrationEscalated | None = None
        #: Integration's subtask, if the plan has one: the one subtask whose planning line marks
        #: it as the completion owner's, read from that line and never from the role register or
        #: a role's name. It reads the system-scope result, so it runs after the integration
        #: call, and its lines are the only lines about a subtask that may follow that call.
        self.completion_subtask: str | None = None
        #: Every person's decision the run took, by item, and the held ones since confirmed.
        self.taken: dict[str, DecisionTaken] = {}
        self.confirmed: set[str] = set()
        #: Each interface node's consumers, as the decomposition's line records them; ``None`` in
        #: a run whose plan names none, which then records no contract pairs.
        self.consumers: dict[str, tuple[str, ...]] | None = None
        self.interfaces: tuple[str, ...] = ()
        #: The module pairs whose contract the run tests, once their line is on the record.
        self.contract_pairs: tuple[ContractPair, ...] | None = None
        #: The modules recorded complete, by the subtask that planned each. Merged is not
        #: complete: a module's subtask is ``done`` once it merged, whether or not it is here.
        self.completed: dict[str, ModuleCompleted] = {}
        #: Every contract result on the record, in order.
        self.contracts: list[ContractTested] = []
        #: The run branch's head as the log records it: the decomposition's commit, then each merge.
        self.run_head: str | None = None
        #: Where each module directory's last merge with a clean diff is on the record, by line.
        self.merged_at: dict[str, int] = {}
        #: The system requirements the plan allocates to integration, and the brief's own words for
        #: each one given by number, as the decomposition's line records them.
        self.system_requirements: tuple[SystemRequirement, ...] | None = None
        self.brief_words: tuple[CriterionWords, ...] = ()

    # -- following the log -------------------------------------------------------

    def check(self, event: Event) -> None:
        """Raise ``ValueError`` unless ``event`` may be the next line."""
        copy.deepcopy(self).record(event)

    def record(self, event: Event) -> None:
        """Take ``event`` as the next line, or raise ``ValueError`` if it cannot be.

        Once the integration call is on the record the plan is closed: no line about
        a subtask may follow, except a worktree removal, a person's decision, or a module's
        completion, which follows integration's accepted attempt (:meth:`_complete`). The rule is
        applied after the line's own rules, so a line that breaks one of those is refused for
        it. A decision that acts on a design the call skipped as incomplete reopens it, and so
        does one under ``off`` while a subtask but integration's has not merged.

        One subtask is exempt: integration's own, marked on its planning line, whose lines
        follow the call wherever the call lets it run (:meth:`integration_may_run`). Every other
        subtask's line is refused as before, whatever its role is named.
        """
        subtask_id = getattr(event, "subtask_id", None)
        closed = (
            self.integration is not None
            and subtask_id is not None
            and not isinstance(event, WorktreeRemoved | DecisionTaken | ModuleCompleted)
            and not (subtask_id == self.completion_subtask and self.integration_may_run())
        )
        self._record(event)
        if closed:
            _refuse("nothing about a subtask follows the integration call")

    def _record(self, event: Event) -> None:
        if isinstance(event, RunStarted):
            self.gate_mode = event.gate_mode
            self.escalation_backend = event.escalation_backend
            self.acts = event.queue_decisions == "act"
            return
        if isinstance(event, Halted):
            self.halted = self.last_halt = event
            return
        if isinstance(
            event,
            LeftoverStopped
            | LeftoverRead
            | TokensUsed
            | InstallChecked
            | SessionSpawned
            | OsLayerChecked
            | DecisionsSealed,
        ):
            return  # recorded at any time, a halted run's resume included
        if isinstance(event, WorktreeRemoved):
            if event.subtask_id not in self.subtasks or event.subtask_id in self.worktrees_handled:
                _refuse("a worktree removal for no subtask, or for one already handled")
            sub = self.subtasks[event.subtask_id]
            allowed = {
                "done": sub.status == "done",
                "queue_resolved": sub.status in ("escalated", "rejected"),
            }
            self._expect(allowed[event.reason], "a worktree removal")
            self.worktrees_handled.add(event.subtask_id)
            return
        if isinstance(event, Incident) and event.subtask_id is None:
            self.incident = event
            return
        if self.halted is not None and not isinstance(event, Resumed | Incident):
            _refuse("the run is halted; only a resume, or an incident found at one, may follow")
        if isinstance(event, SubtaskPlanned):
            if self.contract_pairs is not None:
                _refuse("nothing is planned after the run's contract pairs")
            self._plan(event)
            return
        if isinstance(event, Decomposed):
            self.journal_head = self.base_revision = event.head_revision
            self.run_head = event.spec_commit
            if event.interface_consumers is not None:
                self.consumers = {e.interface: e.consumers for e in event.interface_consumers}
                self.interfaces = event.interface_nodes
            self.system_requirements = event.system_requirements
            self.brief_words = event.brief_words or ()
            return
        if isinstance(event, ContractPairsPlanned):
            self._pairs(event)
            return
        if isinstance(event, ContractTested):
            self._tested(event)
            return
        if (
            self.consumers is not None
            and self.contract_pairs is None
            and isinstance(
                event,
                StageEntered | IntegrationGateRan | IntegrationGateSkipped | IntegrationEscalated,
            )
        ):
            _refuse("nothing is dispatched before the run's contract pairs are recorded")
        if (
            isinstance(
                event,
                StageEntered
                | IntegrationGateRan
                | IntegrationGateSkipped
                | IntegrationEscalated
                | CompletionDeclared
                | ModuleCompleted,
            )
            and self.owed_contract() is not None
        ):
            _refuse("nothing is dispatched or completed while a pair's contract result is owed")
        if isinstance(event, TokensUsed | EnvironmentRecorded):
            return  # attributed or recorded, never a transition
        if isinstance(event, IntegrationGateRan | IntegrationGateSkipped | IntegrationEscalated):
            self._integrate(event)
            return
        if isinstance(event, DecisionTaken):
            self._take(event)
            return
        if isinstance(event, ModuleCompleted):
            self._complete(event)
            return
        if event.subtask_id is None:
            return  # an incident with no subtask, taken above; for the type checker
        sub = self.subtasks[event.subtask_id]
        if isinstance(event, SubtaskRemoved):
            if sub.status != "planned":
                _refuse("only a subtask not yet dispatched can be removed from the plan")
            sub.status = "removed"
            return
        if isinstance(event, StageEntered) and event.stage == "resolve":
            self._resolve(sub, event.attempt)
            return
        if isinstance(event, AttemptReturned) or (
            isinstance(event, SubtaskRejected)
            and (sub.status == "waiting" or event.by == "closing_pass")
        ):
            self._back(sub, event)
            return
        if sub.status != "active" or not sub.attempts:
            _refuse(f"subtask {event.subtask_id!r} has no attempt in progress")
        now = sub.attempts[-1]
        if getattr(event, "attempt", now.number) != now.number:
            _refuse(f"attempt {getattr(event, 'attempt', '?')} is not the one in progress")
        if isinstance(event, StageEntered):
            if event.stage == "spawn" and sub.plan.subtask_id == self.completion_subtask:
                self._expect_issued(now)
            self._enter(now, event.stage)
        elif isinstance(event, IntegrationStateIssued):
            self._issued(sub, now, event)
        elif isinstance(event, SessionEnded):
            self._expect(now.cursor == "spawn" and now.session is None, "a session end")
            now.session = event
            now.ended.append(event)
        elif isinstance(event, InfraRetryScheduled):
            failed = now.session is not None and now.session.outcome == "infrastructure"
            self._expect(failed and event.retries_done == now.retries_done, "a retry")
            now.retries_done += 1
            sub.next_resolve = now.number
        elif isinstance(event, ProposalsChecked):
            self._expect(now.cursor == "implement" and now.changes is None, "a change check")
            now.changes = event
        elif isinstance(event, CompletionDeclared):
            self._declared(sub, now, event)
        elif isinstance(event, DisputeRecorded):
            self._disputed(sub, now, event)
        elif isinstance(event, ArbitrationDecided):
            self._arbitrated(sub, now, event)
        elif isinstance(event, GateRan | GateSkipped):
            self._expect(now.cursor == "gate" and now.gate is None, "a gate line")
            now.gate = event
            verdict = event.result.verdict if isinstance(event, GateRan) else "skipped"
            self._ledger(sub.plan.subtask_id, gate_result=verdict)
        elif isinstance(event, ReviewRan):
            done = now.cursor == "review" and now.review is None
            self._expect(done and now.unavailable_final is None, "a review line")
            now.review = event
            sub.reviews.append(event)
            self._ledger(sub.plan.subtask_id, review_result=event.result.verdict)
            if now.blocked is not None:
                self._ended(sub, now)
        elif isinstance(event, ReviewUnavailable):
            open_ = now.cursor == "review" and now.review is None
            self._expect(open_ and now.unavailable_final is None, "an unavailable review")
            retried = any(u.retry for u in now.unavailable)
            self._expect(not (event.retry and retried), "a second retry of a review")
            now.unavailable.append(event)
            if now.unavailable_final is not None:
                self._ended(sub, now)
        elif isinstance(event, AttemptRejected):
            basis = self.rejection_basis(now)
            self._expect(now.cursor == "decide" and basis == event.finding.source, "a rejection")
            if basis == "arbitration" and event.finding.subject != ",".join(self.sized(now)):
                _refuse("a rejection whose subject is not the nodes ruled for sizing")
            before = sub.attempts[-2].rejected if len(sub.attempts) > 1 else None
            repeats = before is not None and before.finding_key == event.finding_key
            keyed = event.finding_key == event.finding.key()
            self._expect(keyed and event.repeats_previous == repeats, "a rejection's key")
            now.rejected = event
            self._ended(sub, now)
        elif isinstance(event, WriteIntended):
            ready = now.cursor == "decide" and self.mergeable(now) and now.pending is None
            fresh = event.node_id not in now.applied
            next_rev = event.expected_revision == self.journal_head + 1
            own = event.actor_role == sub.plan.assigned_role
            self._expect(ready and fresh and next_rev and own, "a write intent")
            now.pending = event
        elif isinstance(event, WriteDone):
            pending = now.pending
            landed = (
                pending is not None
                and pending.node_id == event.node_id
                and pending.expected_revision == event.revision
            )
            self._expect(landed, "a write")
            now.applied[event.node_id] = event.revision
            self.written[event.node_id] = self.by_revision[event.revision] = event
            self.journal_head = event.revision
            now.pending = None
        elif isinstance(event, NodeFilesRepaired):
            done = now.session is not None and now.session.outcome == "completed"
            self._expect(now.cursor == "spawn" and done, "a node-file repair")
        elif isinstance(event, Merged):
            checked = now.changes.checked_commit if now.changes is not None else None
            self._expect(now.cursor == "decide" and self.mergeable(now), "a merge")
            if now.pending is not None:
                _refuse("a merge with a store write still unaccounted for")
            if event.attempt_commit != checked:
                _refuse("a merge of a commit other than the one that was checked")
            now.merged = event
            self.run_head = event.merge_commit
            self._ledger(sub.plan.subtask_id, merge_commit=event.merge_commit)
        elif isinstance(event, DiffChecked):
            self._expect(now.cursor == "diff" and now.diff is None, "a diff line")
            now.diff = event
            if not event.divergences:
                sub.status = "done"
                self.merged_at[sub.plan.module_dir] = event.seq
        elif isinstance(event, EscalationDecided):
            self._decided(sub, now, event)
        elif isinstance(event, Escalated):
            self._expect(now.routed is True and sub.ending is None, "an escalation")
            if event.item_id != _item_id(event.run_id, sub.plan.subtask_id, sub.rounds + 1):
                _refuse("an escalation names another item than its subtask's next round")
            sub.status = "escalated"
            sub.queue_item = event.item_id
            sub.rounds += 1
        elif isinstance(event, SubtaskRejected):
            self._expect(sub.ending == event.by, "a subtask's end")
            spent = now.person_rejected
            named = spent.item_id if spent is not None and event.by == "person" else None
            if event.item_id != named:
                _refuse("a subtask's end names another item than the decision that ended it")
            sub.status = "rejected"
            sub.ending = None
        elif isinstance(event, Incident):
            self.incident = event
        elif isinstance(event, Resumed):
            self._resume(sub, now, event.point)

    def _plan(self, event: SubtaskPlanned) -> None:
        """Take a planned subtask, and note it if its line marks it as integration's.

        The mark is read from the line, never from the role register: the writer held it to the
        register when the line was written, and a register changed since cannot move it. The
        marked subtask is planned last, in the integration module directory, as the one subtask
        of its role. A second marked line, a line after it, or a second subtask of its role
        would run before the call as an ordinary subtask or after it as a second exception.
        """
        marked = self.completion_subtask
        if event.owns_completion and marked is not None:
            _refuse(
                "two subtasks are marked as the completion owner's: "
                f"{marked!r} and {event.subtask_id!r}"
            )
        if marked is not None:
            _refuse(
                f"nothing is planned after {marked!r}, the subtask of the role that owns "
                "completion: it is planned last"
            )
        # Compared as the plan check compares them: where case is ignored, as on the machine runs
        # are made on, two directories written differently can be one, and two modules share it.
        folded = PurePosixPath(event.module_dir.casefold())
        for planned in self.order:
            other = self.subtasks[planned].plan.module_dir
            if other != event.module_dir and PurePosixPath(other.casefold()) == folded:
                _refuse(f"module directories {other} and {event.module_dir} are one directory")
        if event.owns_completion:
            if event.module_dir != INTEGRATION_MODULE_DIR:
                _refuse(
                    "the completion owner's subtask is planned in the integration module "
                    f"directory, {INTEGRATION_MODULE_DIR}, not {event.module_dir}"
                )
            same = [
                s for s in self.order if self.subtasks[s].plan.assigned_role == event.assigned_role
            ]
            if same:
                _refuse(
                    f"a second subtask of the marked role {event.assigned_role!r}: {same[0]!r} "
                    "is planned already, and one subtask at most is the completion owner's"
                )
            self.completion_subtask = event.subtask_id
        self.order.append(event.subtask_id)
        self.subtasks[event.subtask_id] = SubtaskState(plan=event)
        self._ledger(event.subtask_id, attempt_count=0)

    def _pairs(self, event: ContractPairsPlanned) -> None:
        """Take the run's contract pairs, once, if they are the ones its recorded plan gives."""
        if self.consumers is None:
            _refuse(
                "contract pairs are recorded only in a run whose plan names its interfaces' "
                "consumers"
            )
        if self.contract_pairs is not None:
            _refuse("the run's contract pairs are recorded once")
        why = recorded_pairs_problem(
            event.pairs,
            interfaces=self.interfaces,
            consumers=self.consumers,
            planned={s: sub.plan.assigned_role for s, sub in self.subtasks.items()},
            completion=self.completion_subtask,
        )
        if why is not None:
            _refuse(f"the run's contract pairs are not its plan's: {why}")
        self.contract_pairs = event.pairs

    def integrated(self) -> list[str]:
        """The planned subtasks the integration call waits for and judges: all but integration's."""
        return [s for s in self.order if s != self.completion_subtask]

    def integration_may_run(self) -> bool:
        """Whether the integration call on the record lets integration's subtask be dispatched.

        Integration's session reads the system-scope result, so its subtask runs only after a
        result that passed, or one that failed where the gate only observes; or after the call
        was skipped because the gate is off, once every other subtask merged. Under ``off`` the
        call is skipped as off whether or not they did, so the subtasks' own states say whether
        the design is complete. Never before the call, after a blocking failure, after a design
        found incomplete, or with nothing else planned.
        """
        ran = self.integration
        if isinstance(ran, IntegrationGateRan):
            return ran.result.verdict == "pass" or ran.result.mode == "observe"
        if isinstance(ran, IntegrationGateSkipped) and ran.reason == "gate_mode=off":
            others = self.integrated()
            return bool(others) and all(self.subtasks[s].status == "done" for s in others)
        return False

    def modules(self) -> list[str]:
        """The plan's modules in plan order, each named by the first subtask of its directory.

        A later subtask planned in the same directory, as sizing's closing pass is, is a pass
        over that module and no module of its own; integration's subtask is no module.
        """
        seen: set[str] = set()
        found: list[str] = []
        for subtask_id in self.order:
            directory = self.subtasks[subtask_id].plan.module_dir
            if directory not in seen and subtask_id != self.completion_subtask:
                found.append(subtask_id)
            seen.add(directory)
        return found

    def _declared(self, sub: SubtaskState, now: AttemptState, event: CompletionDeclared) -> None:
        """Take integration's declaration: after the attempt's accepted change check, once.

        It is read from the commit that check held, so it comes before the attempt's gate, and it
        names modules of the plan, each once, in plan order.
        """
        if sub.plan.subtask_id != self.completion_subtask:
            _refuse(
                "a completion declaration comes only from the subtask marked as the completion "
                "owner's"
            )
        accepted = now.changes is not None and now.changes.refused_by is None
        self._expect(
            now.cursor == "implement" and accepted and now.declaration is None,
            "a completion declaration",
        )
        modules = self.modules()
        for module in event.modules:
            if module not in modules:
                _refuse(
                    f"a completion declaration names {module!r}, which is no module of the plan"
                )
        places = [modules.index(module) for module in event.modules]
        if places != sorted(set(places)):
            _refuse("a completion declaration names each module once, in plan order")
        now.declaration = event

    def _disputed(self, sub: SubtaskState, now: AttemptState, event: DisputeRecorded) -> None:
        """Take a dispute: after the attempt's accepted change check, each quantity once, sorted."""
        if sub.plan.subtask_id == self.completion_subtask:
            _refuse("a dispute never comes from the subtask marked as the completion owner's")
        accepted = now.changes is not None and now.changes.refused_by is None
        self._expect(now.cursor == "implement" and accepted, "a dispute")
        last = now.disputes[-1].position if now.disputes else None
        here = event.position
        if last is not None and (here.node_id, here.name) <= (last.node_id, last.name):
            _refuse("an attempt disputes each quantity once, in order")
        now.disputes.append(event)

    def _arbitrated(self, sub: SubtaskState, now: AttemptState, event: ArbitrationDecided) -> None:
        """Take a ruling: after the gate line, the next dispute's, ruled again from the record.

        The standing is built from the lines before it (the attempt's gate line, the rulings of
        the subtask's earlier attempts, the attempt's place in the budget) and must be the one
        recorded, and the table must give the level recorded. ``held`` names the disputed
        quantity; its value and revision are the loop's to hold against the journal, which no
        line carries.
        """
        due = now.cursor == "gate" and now.gate is not None
        self._expect(due and len(now.arbitrations) < len(now.disputes), "an arbitration")
        disputed = now.disputes[len(now.arbitrations)].position
        conflict = event.conflict
        if (conflict.node_id, conflict.quantity) != (disputed.node_id, disputed.name):
            _refuse("an arbitration answers the next dispute of its attempt, in order")
        held = event.held.position
        if (held.node_id, held.name) != (disputed.node_id, disputed.name):
            _refuse("an arbitration's held value is of the quantity disputed")
        self._held_by_the_log(event.held, disputed.unit)
        earlier = [
            (line.conflict, line.level) for a in sub.attempts[:-1] for line in a.arbitrations
        ]
        gate = now.gate.result if isinstance(now.gate, GateRan) else None
        chosen = self.chosen_holds(sub.plan.subtask_id, disputed, event.held)
        standing = dispute_standing(
            conflict, gate=gate, earlier=earlier, attempt=now.number, fix=now.fix, chosen=chosen
        )
        if event.standing != standing:
            _refuse("an arbitration about a standing the lines before it do not give")
        if event.level != arbitrate(conflict, standing).level:
            _refuse("an arbitration whose level is not the one the precedence table gives")
        now.arbitrations.append(event)
        now.ruled_at.append(self.journal_head)
        if now.queued:
            self._ended(sub, now)

    def _held_by_the_log(self, held: Held, disputed_unit: str) -> None:
        """Refuse a held value the log does not give: its revision, or its unit's kind.

        The revision is the node's latest recorded write, or for a node no line wrote, at most the
        decomposition's head; the unit is of the disputed quantity's kind. The registry is loaded
        here, where a ruling is replayed, and never by the hook.
        """
        from physgate.series.consistency import unit_kind_problem

        done = self.written.get(held.position.node_id)
        revision_held = (
            held.revision == done.revision
            if done is not None
            else held.revision <= self.base_revision
        )
        if not revision_held:
            _refuse("an arbitration's held value at a revision no write of its node puts there")
        if unit_kind_problem(held.position.unit, disputed_unit) is not None:
            _refuse("an arbitration's held value in a unit of another kind than the dispute's")

    def write_of(self, held: Held) -> WriteDone | None:
        """The recorded write that put ``held``'s revision; ``None`` for one before the run.

        It is that write however often the node was written since.
        """
        done = self.by_revision.get(held.revision)
        return done if done is not None and done.node_id == held.position.node_id else None

    def writer_of(self, held: Held) -> tuple[str, str] | None:
        """Who wrote ``held``'s revision, by subtask and role; ``None`` before the run."""
        done = self.write_of(held)
        if done is None:
            return None
        return done.subtask_id, self.subtasks[done.subtask_id].plan.assigned_role

    def _arbitrated_basis(self, now: AttemptState) -> FindingSource | None:
        """Sizing's value stands where a ruling says so and none sends the attempt to a person."""
        return "arbitration" if self.sized(now) and not now.queued else None

    @staticmethod
    def sized(now: AttemptState) -> list[str]:
        """The nodes the attempt's rulings leave sizing's value standing on, sorted, each once."""
        return sorted(
            {line.conflict.node_id for line in now.arbitrations if line.level == "sizing"}
        )

    def _issued(self, sub: SubtaskState, now: AttemptState, event: IntegrationStateIssued) -> None:
        """Take integration's issued state: in its window, after ``resolve``, once.

        Held to its place and its form alone. Its bytes are the loop's to hold: a rebuild here
        would make every recorded log unreadable after any change to the document's wording.
        """
        if sub.plan.subtask_id != self.completion_subtask:
            _refuse(
                "an issued state is integration's subtask's alone, the subtask marked as the "
                "completion owner's"
            )
        self._expect(now.cursor == "resolve" and now.issued is None, "integration's issued state")
        now.issued = event

    @staticmethod
    def _expect_issued(now: AttemptState) -> None:
        if now.issued is None:
            _refuse(
                "integration's session is spawned only after its issued state is recorded in "
                "the same window"
            )

    def owed_contract(self) -> ContractPair | None:
        """The pair whose contract result the record owes next, if any (ARCH-051).

        A pair is owed its first result once the subtasks its two sides name are both done (merged,
        their diffs clean), and a retest after every later clean merge in either side's module
        directory, as sizing's closing pass is one: the first such pair, in the recorded order.
        """
        for pair in self.contract_pairs or ():
            sides = [self.subtasks[side.subtask_id] for side in (pair.producer, pair.consumer)]
            if any(sub.status != "done" for sub in sides):
                continue
            latest = self.latest_contract(pair)
            merged = max(self.merged_at[sub.plan.module_dir] for sub in sides)
            if latest is None or latest.seq < merged:
                return pair
        return None

    def latest_contract(self, pair: ContractPair) -> ContractTested | None:
        """The pair's latest contract result on the record, if it has one."""
        return next((line for line in reversed(self.contracts) if line.result.pair == pair), None)

    def _tested(self, event: ContractTested) -> None:
        """Take a pair's contract result: the one the record owes next, at the recorded head.

        Its clauses cannot be recomputed here, where there is no graph: the result is held to
        itself as it is read, and its definition's digest to the form of one, never to the code's
        digest now, which a later change to that code would move.
        """
        if self.contract_pairs is None:
            _refuse("a contract result in a run that records no contract pairs")
        owed = self.owed_contract()
        if owed is None:
            _refuse("a contract result where none is owed")
        if event.result.pair != owed:
            _refuse(
                f"the contract result owed next is {owed.producer.module} to {owed.consumer.module}"
            )
        if event.first != (self.latest_contract(owed) is None):
            _refuse("a pair's first result is marked first, and no other is")
        if (event.commit, event.revision) != (self.run_head, self.journal_head):
            _refuse("a contract result is taken at the run's recorded head and journal revision")
        self.contracts.append(event)

    def owed_completion(self) -> str | None:
        """The module whose completion line the record owes next, if any.

        Once integration's attempt merged and its diff found nothing: the first module, in plan
        order, that the attempt's declaration names, that has no completion line yet, and for
        which every registered precondition holds. A declared module with a precondition open is
        withheld: it is never owed, and the run ends without its line.
        """
        integration = self.completion_subtask
        if integration is None or self.subtasks[integration].status != "done":
            return None
        declared = self.subtasks[integration].attempts[-1].declaration
        if declared is None:
            return None
        return next(
            (
                module
                for module in declared.modules
                if module not in self.completed and not open_preconditions(self, module)
            ),
            None,
        )

    def _complete(self, event: ModuleCompleted) -> None:
        """Take a module's completion line: the one the record owes next, and no other (ARCH-051).

        Integration's attempt that merged, with its diff clean, explains it: that attempt's
        declaration names the module, the module is not complete already, and every registered
        precondition holds for it, asked here as the writer asked it.
        """
        integration = self.completion_subtask
        if integration is None or event.declared_by != integration:
            _refuse("a completion is declared only by the subtask marked as the completion owner's")
        sub = self.subtasks[integration]
        if sub.status != "done":
            _refuse(
                "a completion follows integration's accepted attempt: merged, and its diff clean"
            )
        merged = sub.attempts[-1]
        if event.attempt != merged.number:
            _refuse("a completion names the attempt of integration that merged")
        declared = merged.declaration
        if declared is None or event.subtask_id not in declared.modules:
            _refuse(f"{event.subtask_id!r} is not a module the merged attempt declared complete")
        if event.subtask_id in self.completed:
            _refuse(f"{event.subtask_id!r} is recorded complete once")
        still_open = open_preconditions(self, event.subtask_id)
        if still_open:
            named = "; ".join(f"{name}: {why}" for name, why in still_open)
            _refuse(f"a precondition of completion is open for {event.subtask_id!r}: {named}")
        owed = self.owed_completion()
        if event.subtask_id != owed:
            _refuse(f"{owed!r} is owed its completion line first, in plan order")
        self.completed[event.subtask_id] = event

    @staticmethod
    def _ended_without_merge(now: AttemptState) -> bool:
        return (
            now.rejected is not None
            or now.blocked is not None
            or now.unavailable_final is not None
            or now.queued
        )

    def _ended(self, sub: SubtaskState, now: AttemptState) -> None:
        """The attempt ended without a merge: the escalation question is due.

        A log that names an escalation backend carries the answer on a line of its own,
        which comes next. A log written before the interface existed has no such line; its
        loop sent to a person exactly where the rules do, so the rules' route is taken as
        the answer it would have recorded.
        """
        if now.fix:
            # The fix a person ordered is routed by rule, never asked about: not accepted, the
            # subtask ends; a review that reached no verdict, or a dispute ruled for a person
            # (ARCH-040), goes to the person once more.
            if now.unavailable_final is not None or now.queued:
                now.routed = True
            else:
                sub.ending = "fix_not_accepted"
            return
        if self.escalation_backend is not None:
            return
        state = self._state_of(sub.plan.subtask_id)
        answered = RulesBackend().decide(TO_THE_QUEUE, state)
        basis = route(forced=forced(state), answer=answered.answer, confidence=answered.confidence)
        self._route(sub, now, routed=basis is not None)

    def _state_of(self, subtask_id: str) -> EscalationState:
        try:
            return escalation_state(self, subtask_id)
        except RunStateError as exc:
            _refuse(f"no escalation state can be built here: {exc}")

    def _decided(self, sub: SubtaskState, now: AttemptState, event: EscalationDecided) -> None:
        """Take a decision line: due, about the state the log implies, routed by the rule."""
        if self.escalation_backend is None:
            _refuse("a decision line in a log whose run names no escalation backend")
        due = self._ended_without_merge(now) and now.decided is None and not now.fix
        self._expect(due and now.cursor in ("decide", "review", "gate"), "an escalation decision")
        decision = event.decision
        if decision.backend_id != self.escalation_backend:
            _refuse("a decision by another backend than the one the run names")
        try:
            row = REGISTER.row(decision.backend_id)
        except EscalationBackendError:
            _refuse("a decision by a backend the register does not name")
        if decision.backend_version != row.version or decision.question != TO_THE_QUEUE:
            _refuse("a decision under another backend version or question")
        if event.state != self._state_of(sub.plan.subtask_id):
            _refuse("a decision about a state the lines before it do not imply")
        if decision.forced != forced(event.state):
            _refuse("a decision whose forced route is not the state's")
        if decision.backend_id == "rules":
            answered = RulesBackend().decide(TO_THE_QUEUE, event.state)
            recorded = BackendAnswer(answer=decision.answer, confidence=decision.confidence)
            if recorded != answered:
                _refuse("a rules decision whose answer is not the rules' own")
        now.decided = event
        self._route(sub, now, routed=decision.routed)

    @staticmethod
    def _route(sub: SubtaskState, now: AttemptState, *, routed: bool) -> None:
        now.routed = routed
        if not routed:
            # Only a rejection with budget left can go on; the forced routes always route.
            sub.next_resolve = after_rejection(now.number)

    def _take(self, event: DecisionTaken) -> None:
        """Take a person's decision: held to what the lines before it allow, then acted on."""
        if not at_a_boundary(self.next_step()):
            _refuse("a decision is taken only where no attempt is in progress")
        try:
            require_taken(self, event)
        except ValueError as exc:
            _refuse(str(exc))
        if event.confirmed_by is not None:
            self.confirmed.add(event.item_id)
        else:
            self.taken[event.item_id] = event
        if not event.acts or event.subtask_id is None:
            return
        sub = self.subtasks[event.subtask_id]
        now = sub.attempts[-1]
        if self._design_incomplete():
            # The design changes again: integration is judged once more when it is complete.
            self.integration = None
        sub.status = "active"
        self._ledger(sub.plan.subtask_id, person_decision=event.verb, queue_item=event.item_id)
        if event.effect == "merge":
            now.approved = event
            now.cursor = "decide"
            return
        if event.effect == "resize":
            sub.status = "waiting"
            now.resized = event
            sub.chosen += values_chosen(sub, event.item_id)
            return
        now.person_rejected = event
        if event.effect == "retry":
            sub.next_resolve = after_rejection(now.number)
        elif event.effect == "fix":
            sub.next_resolve = now.number + 1
            sub.fix_next = True
        else:
            sub.ending = "person"

    def _design_incomplete(self) -> bool:
        """Whether the call on the record skipped a design a decision can still complete.

        A design found incomplete; or, under ``off``, where the skip line is written whether or
        not every subtask merged, a design with a subtask but integration's that did not. Never
        a design every other subtask merged: a decision then acts on integration's own subtask,
        and the design it reads is the one the call already let it run on.
        """
        skipped = self.integration
        if not isinstance(skipped, IntegrationGateSkipped):
            return False
        if skipped.reason == "not_all_merged":
            return True
        return skipped.reason == "gate_mode=off" and any(
            self.subtasks[s].status != "done" for s in self.integrated()
        )

    def _back(self, sub: SubtaskState, event: AttemptReturned | SubtaskRejected) -> None:
        """A waiting subtask's attempt returns once the closing pass merged, or ends once it ended.

        Once, for the attempt that waits and the item its resize was chosen on. The return takes
        the attempt back to its completed session: what it did after that is judged again.
        """
        if sub.status != "waiting":
            _refuse("only a waiting subtask returns to the gate, or ends with the closing pass")
        now = sub.attempts[-1]
        closing = self.subtasks[self.closing_pass() or sub.plan.subtask_id].status
        item = now.resized.item_id if now.resized is not None else None
        if isinstance(event, SubtaskRejected):
            ended = event.by == "closing_pass" and closing in ("rejected", "removed")
            if not ended or (event.attempt, event.item_id) != (now.number, item):
                _refuse("a waiting subtask ends only with the closing pass, naming its item")
            sub.status = "rejected"
            return
        if closing != "done" or (event.attempt, event.item_id) != (now.number, item):
            _refuse("an attempt returns once the closing pass merged, for the item that resized it")
        sub.status = "active"
        now.restart("spawn")
        now.routed = now.decided = None
        sub.next_resolve = None
        self._ledger(sub.plan.subtask_id, gate_result=None, review_result=None)

    def closing_pass(self) -> str | None:
        """Sizing's closing pass: the subtask planned in a module directory an earlier one holds.

        ``None`` with none planned, or with more than one, where no one of them carries a choice.
        """
        seen: set[str] = set()
        found: list[str] = []
        for subtask_id in self.integrated():
            directory = self.subtasks[subtask_id].plan.module_dir
            if directory in seen:
                found.append(subtask_id)
            seen.add(directory)
        return found[0] if len(found) == 1 else None

    def _waits(self, subtask_id: str) -> bool:
        """The closing pass waits, in a run that acts, before its first attempt, for every item.

        Every arbitration item without a decision taken, or with one held for the operator's
        confirmation and not yet confirmed.
        """
        if not self.acts or subtask_id != self.closing_pass():
            return False
        for sub in self.subtasks.values():
            if sub.status != "escalated" or not sub.attempts or not sub.attempts[-1].queued:
                continue
            taken = self.taken.get(sub.queue_item or "")
            if taken is None or (
                taken.why_not == "held_os_layer_off" and taken.item_id not in self.confirmed
            ):
                return True
        return False

    def waiting_values(self) -> list[ChosenValue]:
        """The values every waiting subtask's resize carries to the closing pass, in plan order."""
        return [
            value
            for s in self.order
            if self.subtasks[s].status == "waiting"
            for value in self.subtasks[s].chosen
        ]

    def chosen_holds(self, subtask_id: str, disputed: QuantityRef, held: Held) -> bool:
        """A person's resize chose ``disputed``'s value, and the dispute and the graph hold it.

        The value exactly, the unit by the gate parser's items.
        """
        return any(
            (value.position.node_id, value.position.name) == (disputed.node_id, disputed.name)
            and _same(value.position, disputed)
            and _same(value.position, held.position)
            for value in self.subtasks[subtask_id].chosen
        )

    def _integrate(
        self, event: IntegrationGateRan | IntegrationGateSkipped | IntegrationEscalated
    ) -> None:
        """The integration call: once, after every planned subtask but integration's is resolved."""
        if isinstance(event, IntegrationEscalated):
            ran = self.integration
            blocked = (
                isinstance(ran, IntegrationGateRan)
                and ran.result.verdict == "fail"
                and ran.result.mode == "on"
            )
            if not blocked or self.integration_escalated is not None:
                _refuse("an integration escalation without a blocking integration failure")
            self.integration_escalated = event
            return
        if self.integration is not None:
            _refuse("the integration call is made once")
        order = self.integrated()
        unresolved = [s for s in order if self.subtasks[s].status in ("planned", "active")]
        if unresolved:
            _refuse(f"integration before every planned subtask is merged or queued: {unresolved}")
        not_merged = tuple(s for s in order if self.subtasks[s].status != "done")
        if isinstance(event, IntegrationGateRan) and not_merged:
            _refuse("the integration gate ran on a design with subtasks that did not merge")
        if isinstance(event, IntegrationGateRan) and not order:
            _refuse("the integration gate ran on a run that planned nothing")
        if isinstance(event, IntegrationGateSkipped):
            if event.reason == "not_all_merged" and event.subtasks != not_merged:
                _refuse("an incomplete design names exactly the subtasks that did not merge")
            if event.reason == "nothing_planned" and order:
                _refuse("integration skipped as nothing planned in a run that planned subtasks")
        self.integration = event

    def _expect(self, condition: bool, what: str) -> None:
        if not condition:
            _refuse(f"{what} cannot come at this point of the attempt")

    def _resolve(self, sub: SubtaskState, attempt: int) -> None:
        if sub.plan.subtask_id == self.completion_subtask and not self.integration_may_run():
            _refuse(
                "integration's subtask is dispatched only after the system gate passed or "
                "observed, or after the gate was off and every other subtask merged"
            )
        if sub.status not in ("planned", "active") or sub.next_resolve != attempt:
            _refuse(f"attempt {attempt} of {sub.plan.subtask_id!r} cannot start now")
        if sub.status == "planned" and self._waits(sub.plan.subtask_id):
            _refuse("sizing's closing pass waits while a dispute's item is undecided")
        if not sub.attempts or sub.attempts[-1].number != attempt:
            if any(a.fix for a in sub.attempts):
                _refuse("the fix a person ordered is a subtask's last attempt")
            if attempt > REPAIR_BUDGET and not sub.fix_next:
                _refuse("an attempt past the repair budget is only the fix a person ordered")
            sub.attempts.append(AttemptState(number=attempt, fix=sub.fix_next))
            sub.fix_next = False
            self._ledger(sub.plan.subtask_id, attempt_count=attempt, reset=True)
        sub.status = "active"
        sub.next_resolve = None
        sub.attempts[-1].restart("resolve")

    def _enter(self, now: AttemptState, stage: Stage) -> None:
        session_ok = now.session is not None and now.session.outcome == "completed"
        # Nothing past the gate line until every dispute of the attempt is ruled (ARCH-040).
        ruled = now.cursor != "gate" or len(now.arbitrations) == len(now.disputes)
        allowed = {
            "spawn": now.cursor == "resolve",
            "verify_reading": now.cursor == "spawn" and session_ok,
            "implement": now.cursor == "verify_reading"
            and now.session is not None
            and now.session.reading_verified,
            "gate": now.cursor == "implement"
            and now.changes is not None
            and now.changes.refused_by is None,
            "review": now.cursor == "gate"
            and self._gate_allows_review(now)
            and not any(line.level not in ("gate", "person") for line in now.arbitrations)
            and ruled,
            "decide": now.cursor != "decide"
            and (self.rejection_basis(now) is not None or self.mergeable(now))
            and ruled,
            "diff": now.cursor == "decide" and now.merged is not None,
        }
        if not allowed.get(stage, False) or (now.rejected is not None and now.approved is None):
            _refuse(f"stage {stage!r} cannot follow {now.cursor!r}")
        now.cursor = stage

    def _gate_allows_review(self, now: AttemptState) -> bool:
        if isinstance(now.gate, GateSkipped):
            return True
        if isinstance(now.gate, GateRan):
            return now.gate.result.verdict == "pass" or now.gate.result.mode == "observe"
        return False

    def rejection_basis(self, now: AttemptState) -> FindingSource | None:
        """What would reject the attempt at its current stage, if anything."""
        if now.merged is not None or now.cursor == "decide" and now.rejected is not None:
            return None
        cursor = now.cursor if now.cursor != "decide" else self._decided_from(now)
        if cursor == "verify_reading" and now.session and not now.session.reading_verified:
            return "reading"
        if cursor == "implement" and now.changes is not None and now.changes.refused_by:
            return now.changes.refused_by
        gate = now.gate
        if cursor == "gate":
            ran = isinstance(gate, GateRan) and gate.result.mode == "on"
            refused = ran and isinstance(gate, GateRan) and gate.result.verdict == "fail"
            return "gate" if refused else self._arbitrated_basis(now)
        if cursor == "review" and now.review and now.review.result.verdict == "fail":
            return "review"
        return None

    def _decided_from(self, now: AttemptState) -> Stage | None:
        """The last stage whose outcome the decision was taken on."""
        done: list[tuple[Stage, object]] = [
            ("review", now.review),
            ("gate", now.gate),
            ("implement", now.changes),
            ("verify_reading", now.session),
        ]
        return next((stage for stage, outcome in done if outcome is not None), None)

    def mergeable(self, now: AttemptState) -> bool:
        """The attempt passed review, or a person approved it, after a gate result that merges.

        A person's approve overrides the reviewer and nothing else (ARCH-133): the gate result
        must still be one the run's mode merges.
        """
        reviewed = now.review is not None and now.review.result.verdict == "pass"
        return (
            (reviewed or now.approved is not None)
            and now.merged is None
            and self._gate_allows_review(now)
        )

    def _resume(self, sub: SubtaskState, now: AttemptState, point: str) -> None:
        if self._ended_without_merge(now):
            # An attempt that ended without a merge is never taken over: what follows it is
            # its escalation decision and the route that decision gives. A resume there would
            # restart the attempt and drop a decision that is due, or one already recorded.
            _refuse("an attempt that ended without a merge is not resumed; it is decided")
        if self.halted is not None and self.halted.reason not in RESUMABLE_HALTS:
            _refuse(f"a run halted for {self.halted.reason} is not resumed by the loop")
        if self.halted is not None:
            self.halted = None
            now.retries_done = 0
        if point != self.resume_point(now):
            _refuse(f"the attempt resumes at {self.resume_point(now)!r}, not {point!r}")
        # A resume follows the journal check, which has recorded a pending write
        # that landed and found none that did not; what is still pending never ran.
        now.pending = None
        if point == "resolve":
            now.restart(None)
            sub.next_resolve = now.number
        elif point == "verify_reading":
            now.restart("spawn")
        else:
            now.cursor, now.diff = "decide", None

    def resume_point(self, now: AttemptState) -> Literal["resolve", "verify_reading", "diff"]:
        """The checkpoint an interrupted attempt restarts from."""
        if now.merged is not None:
            return "diff"
        if now.session is not None and now.session.outcome == "completed":
            return "verify_reading"
        return "resolve"

    def _ledger(self, subtask_id: str, *, reset: bool = False, **changes: object) -> None:
        last = next((line for line in reversed(self.ledger) if line.id == subtask_id), None)
        if last is None:
            plan = self.subtasks[subtask_id].plan
            base: dict[str, object] = {"id": subtask_id, "spec_path": plan.spec_path}
            base |= {"assigned_role": plan.assigned_role, "attempt_count": 0}
        else:
            base = last.model_dump()
        if reset:
            base |= {"gate_result": None, "review_result": None, "merge_commit": None}
            base |= {"person_decision": None, "queue_item": None}
        self.ledger.append(TaskLine.model_validate(base | changes))

    # -- deciding what happens next ------------------------------------------------

    def next_step(self) -> Step:
        """What the loop does next, from the state alone.

        Every planned subtask in order, then the integration call, then integration's own
        subtask where the call lets it run, then each completion its accepted attempt owes. A
        contract result the record owes comes before all of them, and the halt an incident owes
        before anything.
        """
        if self.owed_halt() is not None:
            return Step(kind="halt")
        if self.halted is not None:
            return Step(kind="halted")
        if self.owed_contract() is not None:
            return Step(kind="contract")
        for subtask_id in self.integrated():
            step = self._step_of(subtask_id)
            if step is not None:
                return step
        ran = self.integration
        if ran is None:
            return Step(kind="integrate")
        blocked = (
            isinstance(ran, IntegrationGateRan)
            and ran.result.verdict == "fail"
            and ran.result.mode == "on"
        )
        if blocked and self.integration_escalated is None:
            return Step(kind="integrate")
        if blocked:
            return Step(kind="escalated")
        if self.completion_subtask is not None and self.integration_may_run():
            step = self._step_of(self.completion_subtask)
            if step is not None:
                return step
            owed = self.owed_completion()
            if owed is not None:
                return Step(kind="complete", subtask_id=owed)
        return Step(kind="done")

    def owed_halt(self) -> Incident | None:
        """The incident on the record with no halt after it, whose halt comes next, if any.

        The process that finds an incident writes its halt straight after it. One killed between
        the two leaves the incident alone, and the next step is its halt, whatever else is due.
        """
        incident, halt = self.incident, self.last_halt
        if incident is None or (halt is not None and halt.seq > incident.seq):
            return None
        return incident

    def _step_of(self, subtask_id: str) -> Step | None:
        """What the loop does next for ``subtask_id``; ``None`` once the subtask is resolved."""
        sub = self.subtasks[subtask_id]
        if sub.status in ("removed", "done", "escalated", "rejected"):
            return None
        if sub.status == "planned":
            if self._waits(subtask_id):
                return Step("wait", subtask_id)
            return Step("attempt", subtask_id, 1, "resolve")
        now = sub.attempts[-1]
        if sub.status == "waiting":
            closing = self.subtasks[self.closing_pass() or subtask_id].status
            if closing == "done":
                return Step("return", subtask_id, now.number)
            if closing in ("rejected", "removed"):
                return Step("end_subtask", subtask_id, now.number)
            return None
        if sub.ending is not None:
            return Step("end_subtask", subtask_id, now.number)
        if now.approved is not None:
            # A person's approve: merge exactly the attempt it names, then diff.
            point: Literal["merge", "diff"] = "merge" if now.merged is None else "diff"
            return Step("attempt", subtask_id, now.number, point)
        if now.person_rejected is not None and sub.next_resolve is not None:
            return Step("attempt", subtask_id, sub.next_resolve, "resolve")
        if self._ended_without_merge(now):
            # Asked once at every attempt end that did not merge; then the queue, or
            # the next attempt.
            if now.routed is None:
                return Step("decide", subtask_id, now.number)
            if now.routed:
                return Step("escalate", subtask_id, now.number)
            return Step("attempt", subtask_id, sub.next_resolve, "resolve")
        failed = now.session is not None and now.session.outcome == "infrastructure"
        if failed and sub.next_resolve is None:
            return Step("infra_failed", subtask_id, now.number)
        return Step("attempt", subtask_id, now.number, self.resume_point(now))

    def interrupted(self) -> SubtaskState | None:
        """The subtask a previous process left mid-attempt, if any.

        Also the subtask whose infrastructure schedule ran out, since a resume
        continues that attempt with a fresh schedule.
        """
        for subtask_id in self.order:
            sub = self.subtasks[subtask_id]
            if sub.status != "active" or not sub.attempts:
                continue
            now = sub.attempts[-1]
            if self.halted is not None:
                return sub if self.halted.reason in RESUMABLE_HALTS else None
            clean = now.cursor is None or sub.next_resolve is not None
            failed = now.session is not None and now.session.outcome == "infrastructure"
            # An infrastructure failure not yet answered is answered by the retry
            # schedule, not by a resume, so a crash there cannot reset the count.
            final = now.unavailable_final is not None or now.blocked is not None or now.queued
            if not clean and not failed and not final and now.rejected is None and now.diff is None:
                return sub
        return None


def project_ledger(state: RunState, ledger: TaskLedger) -> int:
    """Append the ledger lines the state implies and the ledger lacks; return how many.

    Raises:
        MergePreconditionError: the ledger holds lines the event log does not imply,
            so the two records disagree and neither can be trusted to merge from.
    """
    held = ledger.read_all()
    require_projection(held, state, ledger.path)
    for line in state.ledger[len(held) :]:
        ledger.append(line)
    return len(state.ledger) - len(held)


def require_projection(held: list[TaskLine], state: RunState, ledger: Path) -> None:
    """Refuse a ledger whose lines are not the start of what the event log implies.

    The ledger is projected from the event log, and appended to only by
    ``project_ledger``, so what it holds must be a prefix of the projection: equal
    to it, or behind it by the lines a killed process had not yet appended.

    Raises:
        MergePreconditionError: the two records disagree, so neither can be
            trusted to merge from or to show.
    """
    if held != state.ledger[: len(held)]:
        msg = "the task ledger disagrees with the run-event log"
        raise MergePreconditionError(msg, ledger=str(ledger))


def replay(events: Iterable[Event]) -> RunState:
    """The run's state, followed line by line from its events, with nothing written.

    Raises:
        CorruptEventLogError: a line cannot come next in the run, so the log could
            not have been written by this loop.
    """
    state = RunState()
    for event in events:
        try:
            state.record(event)
        except ValueError as exc:
            msg = "the run-event log does not replay as a run"
            raise CorruptEventLogError(msg, seq=str(event.seq), reason=str(exc)) from None
    return state


def recorded_ledger(events: Path, ledger: Path) -> list[TaskLine]:
    """The task ledger as recorded, read without writing, held to the event log's projection.

    What ``physgate ledger`` prints and the operator UI serves.

    Raises:
        CorruptEventLogError: the event log does not read or does not replay.
        CorruptRecordError: a ledger line is not a record this package could write.
        MergePreconditionError: the ledger is not a prefix of the log's projection.
    """
    state = replay(read_events(events))
    held = read_ledger(ledger)
    require_projection(held, state, ledger)
    return held


def require_mergeable(ledger_path: Path, subtask_id: str, gate_mode: GateMode) -> TaskLine:
    """The subtask's ledger line, read back from disk, if it permits a merge (ARCH-001).

    A merge needs a gate result and a review result on the ledger line. The review
    must have passed, or a person's approve bound to the attempt must have overridden its
    verdict (ARCH-133). The gate result must be one the run's gate mode allows:
    a pass when the gate blocks, a pass or a logged failure when it observes, and
    ``skipped`` when it is off.

    Raises:
        MergePreconditionError: the line is missing, or lacks either result, or
            carries one the mode does not allow.
    """
    ledger = TaskLedger(ledger_path)
    try:
        line = ledger.find(subtask_id)
    finally:
        ledger.close()
    allowed = {"on": {"pass"}, "observe": {"pass", "fail"}, "off": {"skipped"}}[gate_mode]
    approved = line is not None and line.person_decision == "approve"
    if line is None or line.gate_result is None or (line.review_result is None and not approved):
        msg = "a merge needs a gate result and a review result on the ledger line"
        raise MergePreconditionError(msg, subtask=subtask_id)
    reviewed = line.review_result == "pass" or (
        line.person_decision == "approve" and line.review_result in ("fail", "blocked", None)
    )
    if not reviewed or line.gate_result not in allowed:
        msg = "the ledger line does not permit a merge"
        raise MergePreconditionError(
            msg,
            subtask=subtask_id,
            gate_result=line.gate_result,
            review_result=str(line.review_result),
            gate_mode=gate_mode,
        )
    return line


def recorded_implementer(run_dir: Path, subtask_id: str) -> str:
    """The model string the run recorded for the role that implements ``subtask_id``.

    Read from the durable record, never from a parameter: the subtask's role from its
    task-ledger line, read back from disk, and that role's model from the run's
    configuration file, held to the digest the run's first event line carries. A
    caller holding a configuration object that says something else changes nothing.
    The model that actually answered each session was already held to this string
    when the session ended, so the record is the implementer's model.

    Raises:
        MergePreconditionError: the subtask has no ledger line.
        RunConfigError: the configuration is not the one the run started with, or
            names no model for the line's role.
    """
    run_dir = Path(run_dir)
    ledger = TaskLedger(run_dir / "ledger.jsonl")
    try:
        line = ledger.find(subtask_id)
    finally:
        ledger.close()
    if line is None:
        msg = "a subtask with no ledger line has no recorded implementer"
        raise MergePreconditionError(msg, subtask=subtask_id)
    config = load_run_config(run_dir / "run.json")
    with (run_dir / "events.jsonl").open("rb") as log:
        first = log.readline()
    try:
        started = RunStarted.model_validate_json(first) if first.endswith(b"\n") else None
    except ValidationError:
        started = None
    if started is None or started.config_sha256 != config.sha256():
        msg = "the run's configuration is not the one its first event line recorded"
        raise RunConfigError(msg, run_dir=str(run_dir))
    model = config.models.roles.get(line.assigned_role)
    if model is None:
        msg = "the run recorded no model for the role on the ledger line"
        raise RunConfigError(msg, role=line.assigned_role)
    return model
