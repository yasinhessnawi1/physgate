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
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import ValidationError

from physgate.orchestrator.budget import REPAIR_BUDGET, after_rejection
from physgate.orchestrator.common import GateMode
from physgate.orchestrator.decisions import require_taken
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
    AttemptRejected,
    DecisionsSealed,
    DecisionTaken,
    Decomposed,
    DiffChecked,
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
    LeftoverRead,
    LeftoverStopped,
    Merged,
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
from physgate.orchestrator.plan import INTEGRATION_MODULE_DIR
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
    gate: GateRan | GateSkipped | None = None
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

    def restart(self, cursor: Stage | None) -> None:
        """Forget everything the attempt did after ``cursor``."""
        order: list[Stage | None] = [None, "resolve", "spawn", "verify_reading", "implement"]
        if order.index(cursor) < order.index("spawn"):
            self.session = None
        self.changes = self.gate = self.review = None
        self.unavailable = []
        self.cursor = cursor

    @property
    def blocked(self) -> ReviewRan | None:
        """The review that blocked the attempt, if one did: a person decides, no attempt spent."""
        review = self.review
        return review if review is not None and review.result.verdict == "blocked" else None

    @property
    def unavailable_final(self) -> ReviewUnavailable | None:
        """The review outcome that sends the attempt to a person, if there is one."""
        last = self.unavailable[-1] if self.unavailable else None
        return last if last is not None and not last.retry else None


@dataclass
class SubtaskState:
    """One planned subtask and every attempt made at it."""

    plan: SubtaskPlanned
    status: Literal["planned", "removed", "active", "done", "escalated", "rejected"] = "planned"
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
        "halted",
        "escalated",
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
    if step.kind in ("integrate", "done", "escalated"):
        return True
    return step.kind == "attempt" and step.point == "resolve"


def _refuse(message: str) -> NoReturn:
    raise ValueError(message)


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
        self.order: list[str] = []
        self.subtasks: dict[str, SubtaskState] = {}
        self.halted: Halted | None = None
        self.incident: Incident | None = None
        self.ledger: list[TaskLine] = []
        #: The newest canonical journal revision the orchestrator accounts for: the
        #: decomposition's head, then each recorded write. Anything after it that no
        #: pending intent names is a foreign write.
        self.journal_head = 0
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

    # -- following the log -------------------------------------------------------

    def check(self, event: Event) -> None:
        """Raise ``ValueError`` unless ``event`` may be the next line."""
        copy.deepcopy(self).record(event)

    def record(self, event: Event) -> None:
        """Take ``event`` as the next line, or raise ``ValueError`` if it cannot be.

        Once the integration call is on the record the plan is closed: no line about
        a subtask may follow, except a worktree removal or a person's decision. The rule is
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
            and not isinstance(event, WorktreeRemoved | DecisionTaken)
            and not (subtask_id == self.completion_subtask and self.integration_may_run())
        )
        self._record(event)
        if closed:
            _refuse("nothing about a subtask follows the integration call")

    def _record(self, event: Event) -> None:
        if isinstance(event, RunStarted):
            self.gate_mode = event.gate_mode
            self.escalation_backend = event.escalation_backend
            return
        if isinstance(event, Halted):
            self.halted = event
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
            self._plan(event)
            return
        if isinstance(event, Decomposed):
            self.journal_head = event.head_revision
            return
        if isinstance(event, TokensUsed | EnvironmentRecorded):
            return  # attributed or recorded, never a transition
        if isinstance(event, IntegrationGateRan | IntegrationGateSkipped | IntegrationEscalated):
            self._integrate(event)
            return
        if isinstance(event, DecisionTaken):
            self._take(event)
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
        if sub.status != "active" or not sub.attempts:
            _refuse(f"subtask {event.subtask_id!r} has no attempt in progress")
        now = sub.attempts[-1]
        if getattr(event, "attempt", now.number) != now.number:
            _refuse(f"attempt {getattr(event, 'attempt', '?')} is not the one in progress")
        if isinstance(event, StageEntered):
            self._enter(now, event.stage)
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
            self._ledger(sub.plan.subtask_id, merge_commit=event.merge_commit)
        elif isinstance(event, DiffChecked):
            self._expect(now.cursor == "diff" and now.diff is None, "a diff line")
            now.diff = event
            if not event.divergences:
                sub.status = "done"
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

    @staticmethod
    def _ended_without_merge(now: AttemptState) -> bool:
        return (
            now.rejected is not None or now.blocked is not None or now.unavailable_final is not None
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
            # subtask ends; a review that reached no verdict goes to the person once more.
            if now.unavailable_final is not None:
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
        self._expect(due and now.cursor in ("decide", "review"), "an escalation decision")
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
        allowed = {
            "spawn": now.cursor == "resolve",
            "verify_reading": now.cursor == "spawn" and session_ok,
            "implement": now.cursor == "verify_reading"
            and now.session is not None
            and now.session.reading_verified,
            "gate": now.cursor == "implement"
            and now.changes is not None
            and now.changes.refused_by is None,
            "review": now.cursor == "gate" and self._gate_allows_review(now),
            "decide": now.cursor != "decide"
            and (self.rejection_basis(now) is not None or self.mergeable(now)),
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
        if cursor == "gate" and isinstance(gate, GateRan) and gate.result.verdict == "fail":
            return "gate" if gate.result.mode == "on" else None
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
        subtask where the call lets it run.
        """
        if self.halted is not None:
            return Step(kind="halted")
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
        return Step(kind="done")

    def _step_of(self, subtask_id: str) -> Step | None:
        """What the loop does next for ``subtask_id``; ``None`` once the subtask is resolved."""
        sub = self.subtasks[subtask_id]
        if sub.status in ("removed", "done", "escalated", "rejected"):
            return None
        if sub.status == "planned":
            return Step("attempt", subtask_id, 1, "resolve")
        now = sub.attempts[-1]
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
            final = now.unavailable_final is not None or now.blocked is not None
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
