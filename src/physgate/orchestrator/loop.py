"""The eight-stage loop, as code (ARCH-001, ARCH-030, ARCH-031).

For each planned subtask, one at a time: resolve, spawn a fresh session, verify
its reading, check what it implemented, run the gate, run the reviewer only if
the gate result allows it, merge or reject with a templated repair instruction,
then diff the graph. After three rejections the subtask goes to the approval
queue. An infrastructure failure retries the same attempt on the run's schedule
and never spends from the repair budget.

Nothing here asks a model anything. Every decision is read off ``RunState``,
which is rebuilt from the event log, so a killed loop resumes where its file
says it was. The gate and the reviewer are called through Protocols, and the
loop refuses to start in a gate mode that needs a gate when none is registered.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from physgate.contracts.clause import check_pair
from physgate.contracts.graph import nodes_at
from physgate.contracts.pairs import ContractError
from physgate.orchestrator.apply import ProposalRefusedError
from physgate.orchestrator.budget import infra_retry_delay
from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.common import utc_now
from physgate.orchestrator.credentials import SECRET_VARIABLE
from physgate.orchestrator.decisions import (
    SCANNED_SOURCES,
    decision_effect,
    item_consequence,
    person_order,
    scan_hits_of,
    source_of,
)
from physgate.orchestrator.escalation import TO_THE_QUEUE, EscalationInterface, bind
from physgate.orchestrator.escalation_state import escalation_state
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    AttemptRejected,
    ContractTested,
    DecisionsSealed,
    DecisionTaken,
    Decomposed,
    DiffChecked,
    Envelope,
    EnvironmentRecorded,
    Escalated,
    EscalationDecided,
    Event,
    GateRan,
    GateSkipped,
    Halted,
    Incident,
    IncidentCause,
    InfraRetryScheduled,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
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
    SessionEnded,
    SessionSpawned,
    Stage,
    StageEntered,
    SubtaskRejected,
    TokensUsed,
    WorktreeRemoved,
    WriteDone,
    WriteIntended,
    completion_mark_problem,
    completion_owner_problem,
)
from physgate.orchestrator.exceptions import (
    EscalationBackendError,
    GateNotRegisteredError,
    HeldOutExposedError,
    MergeConflictError,
    MergeRefusedError,
    QueueItemMismatchError,
    ReviewerNotRegisteredError,
    ReviewUnavailableError,
    RunStateError,
    StoreRefusalError,
    TrajectoryTamperedError,
    WorktreeMisplacedError,
)
from physgate.orchestrator.managed import policy_limits_change
from physgate.orchestrator.merge import merge_message
from physgate.orchestrator.ports import (
    ChangeChecker,
    Dispatcher,
    GraphPort,
    MaterialCheck,
    Merger,
    RecordsSpawns,
    SessionReport,
    SessionRequest,
)
from physgate.orchestrator.protocols import (
    Artefact,
    AttemptScope,
    Gate,
    IntegrationArtefact,
    IssuedSpec,
    PersonOrder,
    Reviewer,
    ReviewResult,
    SessionTrajectory,
    require_mode,
    require_separate_models,
)
from physgate.orchestrator.queue import (
    INTEGRATION,
    ItemConsequence,
    QueueItem,
    QueueResolution,
    QueueSource,
    QueueView,
    decided_item,
    decisions_file_bytes,
    escalation_item,
    held_windows_of,
    integration_item,
    item_id_for,
    read_queue,
    unavailable_item,
    whole_lines,
    within,
)
from physgate.orchestrator.record import PlanEntry, RunRecord
from physgate.orchestrator.repair import (
    Finding,
    repair_instruction,
)
from physgate.orchestrator.replay import (
    AttemptState,
    Step,
    SubtaskState,
    at_a_boundary,
    recorded_implementer,
    require_mergeable,
)
from physgate.orchestrator.run_config import RunConfig, os_layer_refusal
from physgate.orchestrator.trajectory import read_sealed
from physgate.reviewers.scan import ScanHit, ScanUnreadableError
from physgate.roles import require_registered
from physgate.series.reader import attempt_records
from physgate.series.seal import AttemptRecord, AttemptSeries, SeriesCheck
from physgate.state.exceptions import DesignStateError, StoreStaleError
from physgate.state.protocol import REJECT_CROSS_ROLE
from physgate.state.store import payload_digest

UNREAD = (
    "The session ended without completing its required reading, so nothing it "
    "produced is considered."
)


def run_head_of(events: Sequence[Event]) -> str | None:
    """The run branch's head as the log records it: its last merge, or its start."""
    head: str | None = None
    for event in events:
        if isinstance(event, Decomposed):
            head = event.spec_commit
        elif isinstance(event, Merged):
            head = event.merge_commit
    return head


def require_gate(config: RunConfig, gate: Gate | None) -> None:
    """Refuse a run whose gate mode needs a gate, with none registered.

    Raises:
        GateNotRegisteredError: the gate mode is ``on`` or ``observe`` and no gate
            is registered. There is no pass-through gate to fall back on.
    """
    if config.gate_mode != "off" and gate is None:
        msg = (
            f"the gate stage cannot pass: gate mode is {config.gate_mode!r} and no gate is "
            "registered"
        )
        raise GateNotRegisteredError(msg, gate_mode=config.gate_mode)


def escalation_for(config: RunConfig) -> EscalationInterface:
    """The escalation interface over the backend the run names, through the register.

    Raises:
        EscalationBackendError: the run names no backend, or the register will not bind it.
    """
    if config.escalation_backend is None:
        msg = "the run names no escalation backend; a run recorded without one is not driven"
        raise EscalationBackendError(msg, run_id=config.run_id)
    return bind(config.escalation_backend)


def require_binding(config: RunConfig, escalation: EscalationInterface) -> None:
    """Refuse a run asked through any interface but the one over the backend it names.

    One check covers a run that names none (recorded before the interface existed): an
    interface always asks a backend with a name, so it never matches none.

    Raises:
        EscalationBackendError: the interface asks a backend other than the one the run
            names, or the run names none.
    """
    if escalation.backend_id != config.escalation_backend:
        msg = "the escalation interface asks another backend than the one the run names"
        raise EscalationBackendError(
            msg, named=str(config.escalation_backend), asked=escalation.backend_id
        )


def refuse_unregistered(
    config: RunConfig, gate: Gate | None, reviewers: Mapping[str, Reviewer]
) -> None:
    """Refuse a run that could not dispatch, gate or review as configured.

    Raises:
        RoleNotRegisteredError: the run names a role the role register does not hold.
        GateNotRegisteredError: the gate mode is ``on`` or ``observe`` and no gate
            is registered. There is no pass-through gate to fall back on.
        ReviewerNotRegisteredError: a role has no reviewer, or its reviewer is not on
            the model string the run pinned for it.
    """
    require_registered(config.models.roles)
    require_gate(config, gate)
    for role, implementer in config.models.roles.items():
        reviewer = reviewers.get(role)
        pinned = config.models.reviewers.get(role)
        if reviewer is None or pinned is None or reviewer.model != pinned:
            msg = "every role needs a registered reviewer on its pinned model string"
            raise ReviewerNotRegisteredError(msg, role=role, pinned=str(pinned))
        require_separate_models(implementer=implementer, reviewer=reviewer.model)


class Loop:
    """One run's loop, over the run directory's event log, ledger and queue."""

    def __init__(
        self,
        *,
        config: RunConfig,
        run_dir: Path,
        gate: Gate | None,
        reviewers: Mapping[str, Reviewer],
        dispatcher: Dispatcher,
        changes: ChangeChecker,
        merger: Merger,
        graph: GraphPort,
        escalation: EscalationInterface,
        material: MaterialCheck,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Open the run in ``run_dir``, replaying whatever its log already holds.

        Raises:
            GateNotRegisteredError, ReviewerNotRegisteredError: see
                :func:`refuse_unregistered`.
            RunConfigError: the run directory holds another configuration, or a log
                with no configuration.
            EscalationBackendError: see :func:`require_binding`.

        ``material`` holds the text a person's decision sends to a role session to the canaries
        of material no session may read, before the session is spawned (ARCH-133).
        """
        refuse_unregistered(config, gate, reviewers)
        require_binding(config, escalation)
        self.config = config
        self.run_dir = Path(run_dir)
        self._gate = gate
        self._reviewers = reviewers
        # A review session's spawn goes on the record as a role session's does: a resume holds
        # a review's process record to it too.
        for reviewer in reviewers.values():
            if isinstance(reviewer, RecordsSpawns):
                reviewer.record_spawns(self._spawned)
        self._dispatcher = dispatcher
        self._changes = changes
        self._merger = merger
        self._graph = graph
        self._escalation = escalation
        self._material = material
        self._sleep = sleep
        self._appends: tuple[str, ...] = ()
        #: The items the operator confirms on this resume, and who; none on a plain run.
        self._confirm: tuple[frozenset[str], str | None] = (frozenset(), None)
        #: Whether this process has recorded the environment its sessions run in.
        self._environment_recorded = False
        self.record = RunRecord(config, self.run_dir, clock=clock)
        self.state = self.record.state
        self.log = self.record.log
        self.ledger = self.record.ledger
        self.queue = self.record.queue

    def close(self) -> None:
        """Release every file handle."""
        self.record.close()

    def _emit(self, event: Event) -> None:
        self.record.emit(event)

    def _env(self) -> Envelope:
        return self.record.log.envelope()

    # -- the run's life -------------------------------------------------------------

    def start(self, plan: Sequence[PlanEntry]) -> None:
        """Record the configuration and the plan, with no decomposition call.

        What the decomposition step does is :meth:`RunRecord.start` with the call;
        this is the same without one, for a plan given directly.
        """
        self.record.start(plan)

    def remove(self, subtask_id: str, reason: str) -> None:
        """Take a subtask not yet dispatched out of the plan; its id stays visible."""
        self.record.remove(subtask_id, reason)

    def run(self) -> Step:
        """Drive the plan until it is done or the run halts.

        Raises:
            RunStateError: a previous process left the run mid-attempt; resume it; or this
                process recorded no OS layer, and the run acts on queue decisions or does not
                allow the layer's absence.
        """
        self._require_os_layer()
        self._stop_leftovers()
        if self.state.halted is None and self.state.interrupted() is not None:
            msg = "the run was interrupted mid-attempt; resume it instead"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if self.state.halted is None and not self._journal_clean():
            return self.state.next_step()
        return self._drive()

    def resume(self, *, confirm: Sequence[str] = (), confirmed_by: str | None = None) -> Step:
        """Take over a run a previous process left, then drive it.

        The interrupted attempt restarts at its checkpoint with a fresh session,
        never the binary's own resume, and keeps its attempt number. A run halted
        because its infrastructure retries ran out continues the same attempt with
        a fresh schedule.

        Every leftover session is stopped and its stream read before anything else, so no
        decision is taken before every stream a previous process left has been read. ``confirm``
        names items whose decision is held because it was written while a session ran without
        the OS layer; ``confirmed_by`` is the operator who confirms them on the command line
        (ARCH-133). Only then does such a decision act.

        Raises:
            RunStateError: the run halted for an incident, which a person resolves; or an item
                to confirm has no held decision, or the run acts on no decision at all; or this
                process recorded no OS layer, and the run acts on queue decisions or does not
                allow the layer's absence.
        """
        self._require_os_layer()
        self._stop_leftovers()
        halted = self.state.halted
        if halted is not None and halted.reason not in RESUMABLE_HALTS:
            msg = f"the run halted for {halted.reason}; a person resolves that before any resume"
            raise RunStateError(msg, run_dir=str(self.run_dir), detail=halted.detail)
        self._require_confirmable(confirm, confirmed_by)
        self._confirm = (frozenset(confirm), confirmed_by)
        if not self._journal_clean():
            return self.state.next_step()
        sub = self.state.interrupted()
        now_changes = sub.attempts[-1].changes if sub is not None and sub.attempts else None
        pending = (
            now_changes.checked_commit
            if sub is not None and now_changes is not None and sub.attempts[-1].merged is None
            else None
        )
        approving = self._approved_unmerged()
        if sub is None and approving is not None:
            # A person's approve taken and not yet recorded as merged: a merge of exactly its
            # commit may have landed before the process died, and is where the run left the branch.
            sub, pending = approving
        if not self._run_branch_holds(sub.plan.subtask_id if sub else None, pending):
            return self.state.next_step()
        if sub is not None and self.state.interrupted() is None:
            sub = None
        if sub is not None:
            now = sub.attempts[-1]
            self._emit(
                Resumed(
                    **self._env(),
                    subtask_id=sub.plan.subtask_id,
                    attempt=now.number,
                    point=self.state.resume_point(now),
                )
            )
        return self._drive()

    def _require_os_layer(self) -> None:
        """Refuse to drive a run whose role sessions would run without the OS layer here.

        Without the layer a role session's shell is bounded by the text hooks alone, so a run
        runs nothing where it is absent unless its parameters allow that, for development, and a
        run that acts on decisions never does (ARCH-091, ARCH-133); the check is
        :func:`os_layer_refusal`, the one a new run's configuration was held to. Read from the
        layer's record this process wrote before driving; none recorded is refused like one
        absent, so a missing check never reads as a present layer. Checked before anything is
        stopped, read or taken.

        Raises:
            RunStateError: as above.
        """
        checked = [e for e in self.log.events if isinstance(e, OsLayerChecked)]
        why = os_layer_refusal(self.config, checked[-1].state if checked else None)
        if why is not None:
            raise RunStateError(why, run_dir=str(self.run_dir))

    def _approved_unmerged(self) -> tuple[SubtaskState, str] | None:
        """The subtask an approve is merging and the commit it merges, if one is not merged yet."""
        for subtask_id in self.state.order:
            sub = self.state.subtasks[subtask_id]
            now = sub.attempts[-1] if sub.attempts else None
            if now is not None and now.approved is not None and now.merged is None:
                commit = now.approved.attempt_commit
                if commit is not None:
                    return sub, commit
        return None

    def _require_confirmable(self, confirm: Sequence[str], confirmed_by: str | None) -> None:
        """Refuse a confirmation the run cannot take: of nothing held, or in a run that records.

        Checked before anything is taken, so a refusal leaves the run as it was.

        Raises:
            RunStateError: as above, or a confirmation with no operator named.
        """
        if not confirm:
            return
        if self.config.queue_decisions != "act":
            msg = "the run only records decisions; nothing is confirmed in it"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if not confirmed_by:
            msg = "a confirmation names the operator who makes it"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        self.queue.refresh()
        # Judged on the file as every take reads it: one read, its seals held first.
        data = decisions_file_bytes(self.run_dir)
        if not self._decisions_as_sealed(data):
            msg = "the decisions file was rewritten beneath a session; the run halts on it"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        view = read_queue(self.run_dir, decisions=data)
        held = self._held_windows()
        offsets = {decision.item_id: offset for offset, decision in view.decisions}
        for item_id in confirm:
            earlier = self.state.taken.get(item_id)
            if earlier is not None:
                ok = earlier.why_not == "held_os_layer_off" and item_id not in self.state.confirmed
            else:
                offset = offsets.get(item_id)
                ok = offset is not None and within(offset, held)
            if not ok:
                msg = "a confirmation is of a held decision, and this item's decision is not held"
                raise RunStateError(msg, item=item_id)

    def _expected_run_head(self) -> str | None:
        """Where the run last left its branch: its last recorded merge, or its start."""
        return run_head_of(self.log.events)

    def _run_branch_holds(self, subtask_id: str | None, pending: str | None) -> bool:
        """The run branch is where the run left it; otherwise an incident.

        Checked before every merge and at every resume. A session's user can move
        the ref as the same user; the hook layer refuses and puts back what it can
        see, and this sees the rest, ``packed-refs`` included.
        """
        expected = self._expected_run_head()
        if expected is None:
            return True
        moved = self._merger.run_branch_moved(expected, pending)
        if moved is None:
            return True
        self._incident(subtask_id, "run_branch_moved", moved)
        return False

    def _decisions_bytes(self) -> int:
        path = self.queue.decisions_path
        return path.stat().st_size if path.exists() else 0

    def _spawned(self, session_id: str, pid: int, started: str) -> None:
        """Record a role session's process before it runs anything: what a resume holds it to."""
        self._emit(SessionSpawned(**self._env(), session_id=session_id, pid=pid, started=started))

    def _stop_leftovers(self) -> None:
        """Stop what a previous process left running, before anything reads or writes."""
        if not self.log.events:
            return
        tampered: list[tuple[str, str]] = []
        exposed = material = quarantined = False
        for left in self._dispatcher.stop_leftovers():
            if left.stopped:
                self._emit(
                    LeftoverStopped(
                        **self._env(), session_id=left.session_id, pid=left.pid, killed=left.killed
                    )
                )
            self._emit(
                LeftoverRead(
                    **self._env(),
                    session_id=left.session_id,
                    stopped=left.stopped,
                    complete=left.complete,
                    trajectory_seal=left.seal,
                    decisions_bytes=self._decisions_bytes(),
                    quarantine=left.quarantine,
                    scan=left.scan,
                )
            )
            if left.held_out_seen is not None:
                # As at a normal session end: the tier counts as exposed (ARCH-141), and
                # the exposure is recorded whatever else the resume finds. The canary is not.
                exposed = True
                detail = f"held-out material in the stream of leftover session {left.session_id}"
                self._emit(
                    Incident(**self._env(), subtask_id=None, cause="held_out_read", detail=detail)
                )
            if left.review_material_seen is not None:
                # A role session that read what only its reviewer reads, found at the
                # resume as at a normal session end. The canary is not recorded.
                material = True
                detail = f"reviewer material in the stream of leftover session {left.session_id}"
                self._emit(
                    Incident(
                        **self._env(), subtask_id=None, cause="review_material_read", detail=detail
                    )
                )
            if left.quarantine is not None:
                # The operator set a gone stream aside: nothing was scanned, so the session's
                # work is never counted as clean. The run halts as an incident, once.
                quarantined = True
                self._emit(
                    Incident(
                        **self._env(),
                        subtask_id=None,
                        cause="stream_quarantined",
                        detail=(
                            f"leftover session {left.session_id}: {left.scan}; "
                            f"set aside by {left.quarantine}"
                        ),
                    )
                )
            if left.tampered is not None:
                tampered.append((left.session_id, left.tampered))
            # Spent, and never recorded: its orchestrator died first. Up to the
            # runtime's own result only, when something wrote after it.
            for message in left.usage:
                self._emit(
                    TokensUsed(
                        **self._env(),
                        attribution=f"{left.kind}:{left.session_id}",
                        message_id=message.message_id,
                        usage=message.usage,
                        partial=not left.complete,
                    )
                )
        for session_id, why in tampered:
            self._incident(None, "trajectory_tampered", f"leftover session {session_id}: {why}")
        if exposed and not tampered:
            # No other incident: the exposure alone stops the run, once.
            self._halt_for(None, "held_out_read")
        elif material and not tampered:
            self._halt_for(None, "review_material_read")
        elif quarantined and not tampered:
            self._halt_for(None, "stream_quarantined")

    def _clean_up_worktrees(self) -> None:
        """Remove the worktrees the rules allow, recording each; never stall or fail the run.

        A done subtask's (merged, diff clean), and an escalated subtask's once its
        queue item has a decision. Nothing else, and never forced.
        """
        self.queue.refresh()  # a person may have decided while a session ran
        resolved = {item.item_id for item in self.queue.items()} - {
            item.item_id for item in self.queue.open_items()
        }
        for subtask_id in self.state.order:
            sub = self.state.subtasks[subtask_id]
            if subtask_id in self.state.worktrees_handled:
                continue
            if sub.status == "done":
                reason: Literal["done", "queue_resolved"] = "done"
            elif sub.status == "escalated" and sub.queue_item in resolved:
                # In a run that acts, only once the decision is taken: an attempt may still run
                # in this worktree because of it. Taken and still waiting, nothing will; held
                # for the operator's confirmation, it still may.
                taken = self.state.taken.get(sub.queue_item)
                if self._acts() and (
                    taken is None
                    or (
                        taken.why_not == "held_os_layer_off"
                        and sub.queue_item not in self.state.confirmed
                    )
                ):
                    continue
                reason = "queue_resolved"
            elif sub.status == "rejected":
                reason = "queue_resolved"
            else:
                continue
            removal = self._merger.remove_worktree(subtask_id)
            self._emit(
                WorktreeRemoved(
                    **self._env(),
                    subtask_id=subtask_id,
                    path=removal.path,
                    reason=reason,
                    outcome=removal.outcome,
                    seconds=removal.seconds,
                    detail=removal.detail,
                )
            )

    def _drive(self) -> Step:
        # The environment is recorded for a step that spawns a session; the integration
        # call, a contract result, a completion line and a finished run spawn none. A process
        # whose first step is one of those may still spawn one, after a decision it takes or the
        # call it makes: that session's line is recorded before it, once (:meth:`_session`).
        first = self.state.next_step().kind
        if first not in ("done", "halted", "escalated", "integrate", "contract", "complete"):
            self._record_environment()
        while True:
            step = self.state.next_step()
            if self._at_a_boundary(step) and self._take_decisions():
                continue  # what a decision did changes what comes next
            if step.kind in ("done", "halted", "escalated"):
                self._clean_up_worktrees()
                return step
            if step.kind == "integrate":
                self._integrate()
                continue
            if step.kind == "contract":
                self._contract()
                continue
            if step.kind == "complete":
                self._complete(step)
                continue
            if step.subtask_id is None or step.attempt is None:
                msg = "a step with no subtask or attempt"
                raise RunStateError(msg, step=step.kind)
            if step.kind == "end_subtask":
                self._end_subtask(step.subtask_id, step.attempt)
            elif step.kind == "decide":
                self._decide(step.subtask_id, step.attempt)
            elif step.kind == "escalate":
                now = self.state.subtasks[step.subtask_id].attempts[-1]
                if now.unavailable_final is not None or now.blocked is not None:
                    self._to_a_person(step.subtask_id)
                else:
                    self._escalate(step.subtask_id)
            elif step.kind == "infra_failed":
                self._infra_failed(step.subtask_id, step.attempt)
            else:
                self._attempt(step.subtask_id, step.attempt, step.point or "resolve")

    # -- a person's decisions -------------------------------------------------------------

    def _acts(self) -> bool:
        return self.config.queue_decisions == "act"

    def _at_a_boundary(self, step: Step) -> bool:
        """Where a decision may be taken, in a run that acts on them (ARCH-133)."""
        return self._acts() and at_a_boundary(step)

    def _held_windows(self) -> list[tuple[int, int | None]]:
        """The decisions file's ranges written while a session ran without the OS layer."""
        return held_windows_of(list(self.log.events))

    def _take_decisions(self) -> bool:
        """Take every decision not yet taken, in the decisions file's order; True if any was.

        Each becomes one ``decision_taken`` line computed by code from the item and the log;
        a held one the operator confirmed on the command line is taken again, acting.
        """
        self.queue.refresh()
        # One read of the file: the seals are checked on these bytes and the decisions parsed
        # from them, so nothing written between the two is taken.
        data = decisions_file_bytes(self.run_dir)
        if not self._decisions_as_sealed(data):
            return True  # halted: the next step says so
        view = read_queue(self.run_dir, decisions=data)
        items = {item.item_id: item for item in view.items}
        held = self._held_windows()
        confirm, confirmed_by = self._confirm
        took = False
        for offset, resolution in view.decisions:
            item = items[resolution.item_id]
            if resolution.item_id not in self.state.taken:
                if not self._take(item, resolution, offset, view, held=within(offset, held)):
                    return True
                took = True
            earlier = self.state.taken[resolution.item_id]
            if (
                resolution.item_id in confirm
                and earlier.why_not == "held_os_layer_off"
                and resolution.item_id not in self.state.confirmed
            ):
                if not self._take(
                    item, resolution, offset, view, held=False, confirmed_by=confirmed_by
                ):
                    return True
                took = True
            if took and not at_a_boundary(self.state.next_step()):
                # What it did starts an attempt's work (a merge, an end): that is driven first,
                # and the next decision waits for the next boundary.
                return True
        return took

    def _decisions_as_sealed(self, data: bytes) -> bool:
        """Every prefix of the decisions file a session started beside is still its first bytes.

        The file only grows: a person's decision is a line appended at its end. A prefix that
        changed was rewritten beneath a session that may have written it, and a decision read from
        it could be one no person made, so the run halts and nothing is taken (ARCH-133).
        """
        for seal in (e for e in self.log.events if isinstance(e, DecisionsSealed)):
            prefix = data[: seal.length]
            if len(prefix) < seal.length or hashlib.sha256(prefix).hexdigest() != seal.sha256:
                detail = (
                    f"the decisions file's first {seal.length} bytes, as subtask "
                    f"{seal.subtask_id} attempt {seal.attempt} started beside them, changed"
                )
                self._incident(None, "decisions_rewritten", detail)
                return False
        return True

    def _take(
        self,
        item: QueueItem,
        resolution: QueueResolution,
        offset: int,
        view: QueueView,
        *,
        held: bool,
        confirmed_by: str | None = None,
    ) -> bool:
        """Take one decision into the log; False if the run halted instead.

        No attempt is in progress here, so an incident names no subtask; its detail does.
        """
        subtask_id = None if item.subtask_id == INTEGRATION else item.subtask_id
        digest = view.digests.get(item.item_id)
        if digest is None:
            self._incident(None, "queue_item_mismatch", f"item {item.item_id} has no line")
            return False
        attempt: int | None = None
        commit: str | None = None
        scan: tuple[ScanHit, ...] = ()
        if subtask_id is not None:
            sub = self.state.subtasks.get(subtask_id)
            if sub is None or not sub.attempts:
                self._incident(None, "queue_item_mismatch", f"item {item.item_id} names no attempt")
                return False
            attempt = sub.attempts[-1].number
            if item.source in SCANNED_SOURCES:
                found = self._scan_hits(subtask_id, where=None)
                if found is None:
                    return False
                scan = found
            if sub.status == "escalated" and sub.queue_item == item.item_id:
                commit = item_consequence(
                    self.state, subtask_id, source=source_of(sub), scan_hits=()
                ).attempt_commit
        try:
            taken = decision_effect(
                self.state, item, resolution, line_sha256=digest, scan_hits=scan, held=held
            )
        except QueueItemMismatchError as exc:
            self._incident(None, "queue_item_mismatch", f"{exc}: {exc.context}")
            return False
        # Held to the record whole, not field by field: the item as listed must be the item the
        # loop builds from the log now, its links, finding, diff and consequence alike. Otherwise
        # the person decided on something the run did not write.
        if (
            resolution.verb is not None
            and subtask_id is not None
            and self._item_for(subtask_id, item_id=item.item_id, ts=item.ts, scan=scan) != item
        ):
            detail = f"item {item.item_id} is not the item the run's record builds"
            self._incident(None, "queue_item_mismatch", detail)
            return False
        if taken.acts and taken.effect == "merge":
            if subtask_id is None or commit is None:
                detail = f"item {item.item_id}: an approve that merges names no attempt's commit"
                self._incident(None, "queue_item_mismatch", detail)
                return False
            # Every trajectory of every attempt, each held to its seal: a stream named and not
            # sealed is one nothing can vouch for, and refuses the merge.
            sessions = [s for a in self.state.subtasks[subtask_id].attempts for s in a.ended]
            if not self._sealed_hold(sessions):
                return False
        self._emit(
            DecisionTaken(
                **self._env(),
                subtask_id=subtask_id,
                item_id=item.item_id,
                verb=resolution.verb,
                note=resolution.note,
                resolved_by=resolution.resolved_by,
                decided_ts=resolution.ts,
                decision_offset=offset,
                shown_sha256=resolution.shown_sha256,
                attempt=attempt,
                attempt_commit=commit,
                effect=taken.effect,
                acts=taken.acts,
                why_not=taken.why_not,
                confirmed_by=confirmed_by,
                order_too_long=taken.order_too_long,
            )
        )
        return True

    def _scan_hits(self, subtask_id: str, *, where: str | None) -> tuple[ScanHit, ...] | None:
        """What the scan before review finds in the unjudged attempts' streams; None if it halted.

        Each stream is held to its seal first. A stream that is not what was sealed, or that
        the scan cannot read, is an incident: it is never a stream that showed nothing.
        """
        # Every attempt no review judged, not only the last: an earlier attempt's work is in the
        # commit an approve would merge, and no reviewer weighed what its streams show.
        sub = self.state.subtasks[subtask_id]
        judged = {review.attempt for review in sub.reviews}
        sessions = [s for a in sub.attempts if a.number not in judged for s in a.ended]
        streams: list[bytes] = []
        for session in sessions:
            if session.trajectory is None:
                continue  # nothing was captured: no stream, and none a reviewer was shown
            if session.trajectory_seal is None:
                # A stream named and never sealed: the scan cannot say what it held, and an
                # unscanned stream is never one that showed nothing.
                detail = f"subtask {subtask_id}: session {session.session_id}'s stream has no seal"
                self._incident(where, "trajectory_tampered", detail)
                return None
            try:
                streams.append(read_sealed(Path(session.trajectory), session.trajectory_seal))
            except TrajectoryTamperedError as exc:
                self._incident(where, "trajectory_tampered", f"{exc}: {exc.context}")
                return None
        try:
            return scan_hits_of(streams)
        except ScanUnreadableError as exc:
            detail = f"subtask {subtask_id}: the scan cannot read its stream: {exc}"
            self._incident(where, "trajectory_tampered", detail)
            return None

    def _consequence(
        self, subtask_id: str, source: QueueSource, scan_hits: tuple[ScanHit, ...] = ()
    ) -> ItemConsequence | None:
        """What each verb will do to the item, in a run that acts; none in one that records."""
        if not self._acts():
            return None
        return item_consequence(self.state, subtask_id, source=source, scan_hits=scan_hits)

    def _end_subtask(self, subtask_id: str, attempt: int) -> None:
        """The subtask ends rejected: a person's reject with no attempt left, or a failed fix."""
        sub = self.state.subtasks[subtask_id]
        by = sub.ending
        if by is None:
            msg = "a subtask ended with no reason to"
            raise RunStateError(msg, subtask=subtask_id)
        spent = sub.attempts[-1].person_rejected
        self._emit(
            SubtaskRejected(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                by=by,
                item_id=spent.item_id if by == "person" and spent is not None else None,
            )
        )

    def _decide(self, subtask_id: str, attempt: int) -> None:
        """Ask the escalation question about the attempt that just ended, and record the answer.

        The state is built from the run as its log replays, and recorded with the answer,
        so the line says what the backend was shown as well as what it said.
        """
        state = escalation_state(self.state, subtask_id)
        decision = self._escalation.decide(TO_THE_QUEUE, state)
        self._emit(
            EscalationDecided(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                decision=decision,
                state=state,
            )
        )

    # -- one attempt ------------------------------------------------------------------

    def _stage(self, subtask_id: str, attempt: int, stage: Stage) -> None:
        self._emit(StageEntered(**self._env(), subtask_id=subtask_id, attempt=attempt, stage=stage))

    def _reject(self, subtask_id: str, attempt: int, finding: Finding) -> None:
        self._stage(subtask_id, attempt, "decide")
        attempts = self.state.subtasks[subtask_id].attempts
        before = attempts[-2].rejected if len(attempts) > 1 else None
        self._emit(
            AttemptRejected(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                finding=finding,
                finding_key=finding.key(),
                repeats_previous=before is not None and before.finding_key == finding.key(),
            )
        )

    def _attempt(self, subtask_id: str, attempt: int, point: str) -> None:
        if point == "merge":
            # A person's approve, taken: merge exactly the attempt it names, then diff.
            if self._merge_attempt(subtask_id, attempt):
                self._diff(subtask_id, attempt)
            return
        if point == "resolve" and not self._session(subtask_id, attempt):
            return
        if point in ("resolve", "verify_reading") and not self._judge(subtask_id, attempt):
            return
        self._diff(subtask_id, attempt)

    def _instruction(self, subtask_id: str, attempt: int) -> tuple[str | None, PersonOrder | None]:
        """What ``attempt`` starts from, and the person's order behind it if a person gave one.

        Rebuilt from the log on every call, by code: a session restarted after a kill, and the
        attempt's reviewer, are told exactly what the first session was.

        Raises:
            RunStateError: a fix ordered after a review that did not block, or with no note.
        """
        sub = self.state.subtasks[subtask_id]
        previous = sub.attempts[-2] if attempt > 1 and len(sub.attempts) > 1 else None
        if previous is None:
            return None, None
        before = previous.rejected
        ordered = previous.person_rejected
        if ordered is not None and ordered.effect in ("fix", "retry"):
            if ordered.note is None:
                msg = "a session a person ordered is ordered with the person's note"
                raise RunStateError(msg, subtask=subtask_id, attempt=str(attempt))
            try:
                order = person_order(
                    previous, effect=ordered.effect, item_id=ordered.item_id, note=ordered.note
                )
            except ValueError as exc:
                raise RunStateError(str(exc), subtask=subtask_id, attempt=str(attempt)) from None
            if order is not None:
                return order.instruction, order
        return (repair_instruction(previous.number, before.finding) if before else None), None

    def _screened(self, subtask_id: str, order: PersonOrder) -> str:
        """What a person's order is held to the canaries by, before its session is spawned.

        A fix's whole instruction, the quoted verdict with the note; a retry's note, the one text
        in it no check before it saw (ARCH-133). The reviewer's finding a retry also quotes is
        what every automated repair quotes, and is held to nothing more here than there.
        """
        if order.kind == "fix_after_block":
            return order.instruction
        attempts = self.state.subtasks[subtask_id].attempts
        spent = next((a.person_rejected for a in attempts if a.number == order.of_attempt), None)
        if spent is None or spent.note is None:
            msg = "a retry a person ordered has no note on the record"
            raise RunStateError(msg, subtask=subtask_id, item=order.item_id)
        return spent.note

    def _material_clean(self, subtask_id: str, text: str) -> bool:
        """``text`` shows no material a role session may not read; otherwise the run halts.

        Held-out material counts the tier as exposed (ARCH-141). The canary is never recorded.
        """
        seen = self._material.seen(text)
        if seen is None:
            return True
        cause: IncidentCause = "held_out_read" if seen == "held_out" else "review_material_read"
        what = "held-out" if seen == "held_out" else "reviewer"
        detail = f"{what} material in the instruction a person's decision gives {subtask_id}"
        self._incident(subtask_id, cause, detail)
        return False

    def _record_environment(self) -> None:
        facts = self._dispatcher.environment()
        if facts is not None:
            self._emit(EnvironmentRecorded(**self._env(), facts=facts))
            self._environment_recorded = True

    def _environment_before_a_spawn(self) -> None:
        """Record this process's environment once, before the first session it spawns.

        A role's session and a reviewer's run alike under the installation of the process that
        spawns them, so each follows that process's environment line, whatever led to it.
        """
        if not self._environment_recorded:
            self._record_environment()

    def _mark_borne_out(self, subtask_id: str) -> bool:
        """The subtask's completion mark is what the role register says; otherwise the run halts.

        Replay reads the mark from the planning line and never asks the register, so a recorded
        run replays under any later register. The writer held the line to the register, but a
        line written past it (appended to the file, or through a handle that follows no run
        state) replays as well, and a mark it put on another role's subtask would move that
        subtask past the system gate. So the process that dispatches asks the register again,
        before the subtask's first line of the attempt. The harness checkout, and with it the
        register, is held across a run and its resume, so an honest run always passes.
        """
        role = self.state.subtasks[subtask_id].plan.assigned_role
        why = completion_mark_problem(role, marked=subtask_id == self.state.completion_subtask)
        if why is None:
            return True
        # No attempt is in progress yet, so the incident names no subtask; its detail does.
        self._incident(None, "duty_breach", f"subtask {subtask_id}: {why}")
        return False

    def _session(self, subtask_id: str, attempt: int) -> bool:
        if not self._mark_borne_out(subtask_id):
            return False
        self._environment_before_a_spawn()
        sub = self.state.subtasks[subtask_id]
        self._stage(subtask_id, attempt, "resolve")
        instruction, order = self._instruction(subtask_id, attempt)
        if order is not None and not self._material_clean(
            subtask_id, self._screened(subtask_id, order)
        ):
            return False
        # The decisions file's length now and when the session ends: the window a
        # decision written meanwhile falls in, which the queue listing marks.
        self._emit(
            StageEntered(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                stage="spawn",
                decisions_bytes=self._decisions_bytes(),
            )
        )
        if self._acts():
            # The decisions file as this session starts: no later decision is taken unless
            # these bytes are still the file's first (ARCH-133). Whole lines only: a torn final
            # line is no decision, and the writer may lawfully cut it.
            beside = whole_lines(decisions_file_bytes(self.run_dir))
            self._emit(
                DecisionsSealed(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    length=len(beside),
                    sha256=hashlib.sha256(beside).hexdigest(),
                )
            )
        request = SessionRequest(
            subtask_id=subtask_id,
            attempt=attempt,
            assigned_role=sub.plan.assigned_role,
            spec_path=sub.plan.spec_path,
            module_dir=sub.plan.module_dir,
            model=self.config.models.roles[sub.plan.assigned_role],
            repair_instruction=instruction,
            bounds=self.config.bounds,
            spec_commit=self._spec_commit(),
            kind="fix" if order is not None and order.kind == "fix_after_block" else "attempt",
        )
        try:
            report = self._dispatcher.run(request, on_spawn=self._spawned)
        except WorktreeMisplacedError as exc:
            # No session was started: the run is where sandboxed sessions abort each
            # other's commands, and a person moves it.
            self._incident(subtask_id, "os_layer_misplaced", str(exc))
            return False
        for message in report.usage:
            self._emit(
                TokensUsed(
                    **self._env(),
                    attribution=f"session:{report.session_id}",
                    message_id=message.message_id,
                    usage=message.usage,
                )
            )
        self._emit(
            SessionEnded(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                session_id=report.session_id,
                outcome=report.end.outcome,
                cause=report.end.cause,
                attempt_commit=report.attempt_commit,
                trajectory=report.trajectory,
                worktree=report.worktree,
                reading_verified=report.reading_verified,
                trajectory_seal=report.trajectory_seal,
                decisions_bytes=self._decisions_bytes(),
                policy_limits_sha256=report.policy_limits_sha256,
                issued_spec_sha256=report.issued_spec_sha256,
                series=report.series,
            )
        )
        exposed = report.held_out_seen is not None
        if exposed:
            # The session displayed held-out material: the tier counts as exposed (ARCH-141).
            # Recorded first and whatever else is found below, so no other incident can
            # leave an exposure unlogged; the run halts once, after every incident found.
            # The canary is not recorded.
            detail = f"held-out material in the stream of session {report.session_id}"
            self._emit(
                Incident(**self._env(), subtask_id=subtask_id, cause="held_out_read", detail=detail)
            )
        # Every other incident first, then the possible abort beside it, then one halt.
        # ``bwrap:`` in a result is the session's own output, which any command can print:
        # no harness-side signal tells a real abort from a printed one, so it is recorded
        # alongside, never in place of, anything else the session's end shows.
        other = self._other_incident(report)
        if other is not None:
            cause, detail = other
            self._emit(Incident(**self._env(), subtask_id=subtask_id, cause=cause, detail=detail))
            self._possible_abort(subtask_id, report)
            self._unverified_reaping(subtask_id, report)
            self._halt_for(subtask_id, cause)
            return False
        if exposed:
            # No other incident: the exposure alone stops the run, and nothing is taken.
            self._possible_abort(subtask_id, report)
            self._unverified_reaping(subtask_id, report)
            self._halt_for(subtask_id, "held_out_read")
            return False
        if report.os_layer_aborted:
            # Nothing else: the session was told of failures no layer judged, if its words
            # are bubblewrap's. Its work is not taken, and a person looks first.
            self._possible_abort(subtask_id, report)
            self._unverified_reaping(subtask_id, report)
            self._halt_for(subtask_id, "os_layer_aborted")
            return False
        if report.reaper_unverified:
            # A command's output was cut where its survivor reaper's last word stands: what
            # it started may have lived on. Its work is not taken, and a person looks first.
            self._unverified_reaping(subtask_id, report)
            self._halt_for(subtask_id, "reaper_unverified")
            return False
        if report.end.outcome != "completed":
            return False
        self._appends = report.hook_journal_appends
        if not self._journal_clean():
            return False
        return not report.node_files_halted or self._repair_node_files(subtask_id, attempt)

    def _other_incident(self, report: SessionReport) -> tuple[IncidentCause, str] | None:
        """The incident a session's end shows besides an exposure or an abort, if any.

        In the order a person reads them; the first found stops the run.
        """
        if report.trajectory_tampered is not None:
            # Something other than the runtime wrote the stream after its result:
            # nothing the session did is taken, and a person looks first.
            return "trajectory_tampered", report.trajectory_tampered
        if report.review_material_seen is not None:
            # The session read what only its reviewer reads, by a path no hook could
            # judge: its work is not taken, and a person looks first.
            # The canary itself is not written into the record a later session can read.
            return (
                "review_material_read",
                f"reviewer material in the stream of session {report.session_id}",
            )
        if report.withheld_problems is not None:
            # A file no session reads had a second name, changed, or could not be checked
            # when the attempt was committed: its work is not taken, and a person looks first.
            return "withheld_file_unsure", report.withheld_problems
        if report.placeholders_refused is not None:
            # Something stood at a path only the sandbox holds that is not its placeholder:
            # its work is not taken, and a person looks first.
            return "placeholder_refused", report.placeholders_refused
        if report.managed_drift is not None:
            # Settings above every source the hooks were installed in changed under the
            # session: nothing it did is taken, and a person looks first.
            return "managed_settings_changed", report.managed_drift
        changed = policy_limits_change(self._policy_baseline(), report.policy_limits_sha256)
        if changed is not None:
            # The account's policy limits are applied without a trace the hooks see: the
            # session ran under other limits than the run began with.
            return "managed_settings_changed", changed
        return None

    def _unverified_reaping(self, subtask_id: str, report: SessionReport) -> None:
        """Record the commands whose reaper could not be heard from, if any."""
        if not report.reaper_unverified:
            return
        detail = (
            f"{len(report.reaper_unverified)} shell command(s) of session {report.session_id} "
            "gave output longer than Claude Code keeps, so the survivor reaper's done line "
            f"could not be read: {'; '.join(report.reaper_unverified)}"
        )
        self._emit(
            Incident(**self._env(), subtask_id=subtask_id, cause="reaper_unverified", detail=detail)
        )

    def _possible_abort(self, subtask_id: str, report: SessionReport) -> None:
        """Record the results that carry bubblewrap's own line, if any: a possible abort.

        Neither a denial nor a reach, and never a judgement on the session's word: the
        record says what the results showed, beside whatever else was found.
        """
        if not report.os_layer_aborted:
            return
        detail = (
            f"possible abort: {len(report.os_layer_aborted)} result(s) of session "
            f"{report.session_id} carry bubblewrap's own line, which the command may have "
            f"printed itself: {', '.join(report.os_layer_aborted)}"
        )
        self._emit(
            Incident(**self._env(), subtask_id=subtask_id, cause="os_layer_aborted", detail=detail)
        )

    def _spec_commit(self) -> str | None:
        """The commit that issued every subtask's specification: the decomposition's."""
        return next((e.spec_commit for e in self.log.events if isinstance(e, Decomposed)), None)

    def _policy_baseline(self) -> str | None:
        """The policy limits the decomposition call received: what every session is held to."""
        for event in self.log.events:
            if isinstance(event, Decomposed):
                return event.policy_limits_sha256
        return None

    def _repair_node_files(self, subtask_id: str, attempt: int) -> bool:
        """Reopen the store so recovery rebuilds node files from the journal, before any read."""
        try:
            repaired, quarantined = self._graph.reopen()
        except DesignStateError as exc:
            self._incident(subtask_id, "node_files_unrecoverable", str(exc))
            return False
        self._emit(
            NodeFilesRepaired(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                repaired=repaired,
                quarantined=quarantined,
            )
        )
        return True

    def _incident(self, subtask_id: str | None, cause: IncidentCause, detail: str) -> None:
        self._emit(Incident(**self._env(), subtask_id=subtask_id, cause=cause, detail=detail))
        self._halt_for(subtask_id, cause)

    def _halt_for(self, subtask_id: str | None, cause: IncidentCause) -> None:
        where = f" in {subtask_id}" if subtask_id else ""
        self._emit(Halted(**self._env(), reason="incident", detail=f"{cause}{where}"))

    def _active(self) -> tuple[str | None, AttemptState | None]:
        for subtask_id in self.state.order:
            sub = self.state.subtasks[subtask_id]
            if sub.status == "active" and sub.attempts:
                return subtask_id, sub.attempts[-1]
        return None, None

    def _journal_clean(self) -> bool:
        """Account for every canonical journal line after the recorded head.

        A line that is the pending intended write is the orchestrator's own and is
        recorded as done. Any other line is foreign: the run halts as an incident,
        and the store is not reopened, because recovery would replay the line as
        genuine.
        """
        subtask_id, now = self._active()
        try:
            tail = self._graph.records_after(self.state.journal_head)
        except DesignStateError as exc:
            self._incident(subtask_id, "foreign_journal_line", str(exc))
            return False
        for line in tail:
            pending = now.pending if now is not None else None
            own = (
                pending is not None
                and line.rev == pending.expected_revision
                and line.node_id == pending.node_id
                and payload_digest(line.payload) == pending.payload_sha256
            )
            if own and pending is not None and subtask_id is not None:
                self._emit(
                    WriteDone(
                        **self._env(),
                        subtask_id=subtask_id,
                        attempt=pending.attempt,
                        node_id=line.node_id,
                        revision=line.rev,
                    )
                )
                continue
            detail = (
                f"journal revision {line.rev}, a {line.op} of {line.node_id}, was not written "
                "by the orchestrator"
            )
            if self._appends:
                detail += "; the hook log recorded: " + " | ".join(self._appends)
            self._incident(subtask_id, "foreign_journal_line", detail)
            return False
        self._graph.hold()
        return True

    def _apply(self, subtask_id: str, attempt: int, commit: str, role: str) -> bool:
        """Write the attempt's proposals into the canonical store, each behind an intent."""
        now = self.state.subtasks[subtask_id].attempts[-1]
        try:
            proposals = self._graph.proposals(subtask_id, commit, role)
        except ProposalRefusedError as exc:
            self._incident(subtask_id, "store_refusal", f"after a clean pre-check: {exc}")
            return False
        for payload in proposals:
            node_id = str(payload["id"])
            if node_id in now.applied:
                continue
            expected = self.state.journal_head + 1
            self._emit(
                WriteIntended(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    node_id=node_id,
                    payload_sha256=payload_digest(payload),
                    actor_role=role,
                    expected_revision=expected,
                )
            )
            try:
                revision = self._graph.write(payload, role)
            except StoreStaleError:
                # The journal moved underneath the handle: something appended that
                # the orchestrator did not. Never reopen and continue.
                if self._journal_clean():
                    self._incident(
                        subtask_id, "foreign_journal_line", "the store handle went stale"
                    )
                return False
            except StoreRefusalError as exc:
                self._incident(subtask_id, "store_refusal", f"{exc} ({exc.context.get('reason')})")
                return False
            if revision != expected:
                self._incident(
                    subtask_id, "foreign_journal_line", f"revision {revision}, not {expected}"
                )
                return False
            self._emit(
                WriteDone(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    node_id=node_id,
                    revision=revision,
                )
            )
        if proposals:
            self._graph.commit(f"Nodes of subtask {subtask_id}, attempt {attempt}\n")
        return True

    def _judge(self, subtask_id: str, attempt: int) -> bool:
        """Reading, changes, gate, review, decision. True if the attempt was merged."""
        sub = self.state.subtasks[subtask_id]
        role = sub.plan.assigned_role
        session = sub.attempts[-1].session
        if session is None or not (
            session.attempt_commit and session.trajectory and session.worktree
        ):
            msg = "an attempt judged without a completed session"
            raise RunStateError(msg, subtask=subtask_id, attempt=str(attempt))
        self._stage(subtask_id, attempt, "verify_reading")
        if not session.reading_verified:
            self._reject(subtask_id, attempt, Finding(source="reading", text=UNREAD))
            return False
        self._stage(subtask_id, attempt, "implement")
        check = self._changes.check(subtask_id, session.attempt_commit, role, series=session.series)
        self._emit(
            ProposalsChecked(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                checked_commit=session.attempt_commit,
                **check.model_dump(),
            )
        )
        if check.refused_by is not None and check.reason is not None:
            finding = Finding(source=check.refused_by, text=check.reason, subject=check.subject)
            self._reject(subtask_id, attempt, finding)
            return False
        artefact = Artefact(
            subtask_id=subtask_id,
            attempt=attempt,
            assigned_role=role,
            attempt_commit=session.attempt_commit,
            worktree=session.worktree,
            graph_root=check.graph_root,
            trajectory=session.trajectory,
            trajectory_sha256=session.trajectory_seal.sha256 if session.trajectory_seal else None,
            trajectory_length=session.trajectory_seal.length if session.trajectory_seal else None,
            scopes=self._scopes(subtask_id),
            base_revision=self.state.journal_head,
            base_commit=self._merger.review_base(session.attempt_commit),
            issued_spec=self._issued_spec(sub.plan.spec_path, session),
            earlier_sessions=self._earlier_sessions(subtask_id, attempt),
            series=self._attempt_series(subtask_id, attempt, check.series_checks),
            ordered_by_person=self._instruction(subtask_id, attempt)[1],
        )
        self._stage(subtask_id, attempt, "gate")
        mode = self.config.gate_mode
        if mode == "off":
            self._emit(
                GateSkipped(
                    **self._env(), subtask_id=subtask_id, attempt=attempt, reason="gate_mode=off"
                )
            )
        else:
            if self._gate is None:
                msg = f"the gate stage cannot pass: gate mode is {mode!r} and no gate is registered"
                raise GateNotRegisteredError(msg, gate_mode=mode)
            result = require_mode(self._gate.check(artefact, mode=mode), mode)
            self._emit(
                GateRan(**self._env(), subtask_id=subtask_id, attempt=attempt, result=result)
            )
            if result.verdict == "fail" and mode == "on":
                self._reject(subtask_id, attempt, Finding.from_gate(result))
                return False
        # The reviewer reads the trajectory: it must still be what was sealed.
        if not self._trajectories_hold(subtask_id, [session]):
            return False
        self._environment_before_a_spawn()
        self._stage(subtask_id, attempt, "review")
        reviewer = self._reviewers[role]
        # The implementer's model is read from the run's record on disk, never from the
        # configuration object this loop was handed: what the check compares must be
        # what the run recorded, whatever a caller holds.
        require_separate_models(
            implementer=recorded_implementer(self.run_dir, subtask_id), reviewer=reviewer.model
        )
        review = self._review(reviewer, artefact)
        if review is None:
            return False  # no verdict: the subtask goes to a person, no attempt spent
        if review.reviewer_model != reviewer.model:
            msg = "a reviewer reported a model other than the one it is pinned to"
            raise ReviewerNotRegisteredError(msg, role=role, reported=review.reviewer_model)
        for message in review.usage:
            self._emit(
                TokensUsed(
                    **self._env(),
                    attribution=f"reviewer:{review.session_id}",
                    message_id=message.message_id,
                    usage=message.usage,
                )
            )
        self._emit(ReviewRan(**self._env(), subtask_id=subtask_id, attempt=attempt, result=review))
        if review.verdict == "blocked":
            return False  # a person decides; the issued specification lacks an input
        if review.verdict == "fail":
            self._reject(subtask_id, attempt, Finding.from_review(review))
            return False
        self._stage(subtask_id, attempt, "decide")
        return self._merge_attempt(subtask_id, attempt)

    def _merge_attempt(self, subtask_id: str, attempt: int) -> bool:
        """Merge the attempt's checked commit; True if it was merged.

        The one merge a review's pass and a person's approve both go through. The ledger line
        read back from disk must permit it (ARCH-001): a passing review, or a person's approve
        bound to this attempt, beside a gate result the mode merges. The proposals are applied
        under the store's own refusals, the run branch checked, exactly the checked commit merged.
        """
        sub = self.state.subtasks[subtask_id]
        now = sub.attempts[-1]
        line = require_mergeable(self.ledger.path, subtask_id, self.config.gate_mode)
        changes = now.changes
        if changes is None:
            msg = "a merge with no recorded change check"
            raise RunStateError(msg, subtask=subtask_id)
        checked = changes.checked_commit
        approved = now.approved
        merge_text = merge_message(
            subtask_id,
            attempt,
            checked,
            str(line.gate_result),
            str(line.review_result),
            approved_by=(
                (approved.resolved_by, approved.item_id, str(approved.shown_sha256))
                if approved is not None
                else None
            ),
        )
        if not self._apply(subtask_id, attempt, checked, sub.plan.assigned_role):
            return False
        if not self._run_branch_holds(subtask_id, checked):
            return False
        try:
            merge_commit = self._merger.merge(subtask_id, attempt, checked, merge_text)
        except (MergeConflictError, MergeRefusedError) as exc:
            cause: IncidentCause = (
                "merge_conflict" if isinstance(exc, MergeConflictError) else "merge_refused"
            )
            self._incident(subtask_id, cause, str(exc))
            return False
        self._emit(
            Merged(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                attempt_commit=checked,
                merge_commit=merge_commit,
            )
        )
        return True

    def _issued_spec(self, spec_path: str, session: SessionEnded) -> IssuedSpec | None:
        """The attempt's specification as issued, with the digest its dispatch recorded."""
        commit = self._spec_commit()
        if commit is None or session.issued_spec_sha256 is None:
            return None
        return IssuedSpec(commit=commit, path=spec_path, sha256=session.issued_spec_sha256)

    def _review(self, reviewer: Reviewer, artefact: Artefact) -> ReviewResult | None:
        """The review's verdict, or ``None`` when there is none and the attempt escalates.

        An infrastructure failure is retried once; any other cause, or a second
        failure, is final. What every try spent is attributed to the reviewer.
        """
        subtask_id, attempt = artefact.subtask_id, artefact.attempt
        retried = False
        while True:
            try:
                return reviewer.review(artefact)
            except HeldOutExposedError as exc:
                # The review session showed held-out material: the tier counts as exposed
                # (ARCH-141). What it spent is recorded, then the exposure, then one halt;
                # no verdict is taken and nothing is retried. The canary is not recorded.
                for message in exc.usage:
                    self._emit(
                        TokensUsed(
                            **self._env(),
                            attribution=f"reviewer:{exc.session_id}",
                            message_id=message.message_id,
                            usage=message.usage,
                        )
                    )
                detail = f"held-out material in the stream of review session {exc.session_id}"
                self._emit(
                    Incident(
                        **self._env(), subtask_id=subtask_id, cause="held_out_read", detail=detail
                    )
                )
                self._halt_for(subtask_id, "held_out_read")
                return None
            except ReviewUnavailableError as exc:
                for message in exc.usage:
                    self._emit(
                        TokensUsed(
                            **self._env(),
                            attribution=f"reviewer:{exc.session_id or 'none'}",
                            message_id=message.message_id,
                            usage=message.usage,
                        )
                    )
                retry = exc.cause == "infrastructure" and not retried
                self._emit(
                    ReviewUnavailable(
                        **self._env(),
                        subtask_id=subtask_id,
                        attempt=attempt,
                        cause=exc.cause,
                        detail=str(exc) or exc.cause,
                        retry=retry,
                        session_id=exc.session_id,
                        reviewer_model=exc.reviewer_model,
                        spec_defects=exc.spec_defects,
                    )
                )
                if not retry:
                    return None
                retried = True

    def _scopes(self, subtask_id: str) -> tuple[AttemptScope, ...]:
        """Subtask scope always; module scope when this completes its module.

        A module is complete when the last planned subtask for its directory is
        judged; a subtask taken out of the plan does not count.
        """
        module_dir = self.state.subtasks[subtask_id].plan.module_dir
        same = [
            s
            for s in self.state.order
            if self.state.subtasks[s].plan.module_dir == module_dir
            and self.state.subtasks[s].status != "removed"
        ]
        return ("subtask", "module") if same and same[-1] == subtask_id else ("subtask",)

    def _integrate(self) -> None:
        """The integration call, once every planned subtask is merged or queued.

        Every subtask merged: the gate checks the whole design at system scope. In
        ``on`` a failure becomes an approval-queue item and the run ends escalated;
        in ``observe`` it is recorded and nothing blocks. Under ``off``, or with a
        subtask that never merged, the log says integration was not gated, and why.
        A killed process that recorded a blocking failure but not its escalation
        escalates on its next pass, and adds the queue item at most once.

        Integration's own subtask is neither waited for nor judged here: it runs after this
        call, whose result its session reads, wherever the call lets it run.
        """
        if self.state.integration is None:
            mode = self.config.gate_mode
            order = self.state.integrated()
            not_merged = tuple(s for s in order if self.state.subtasks[s].status != "done")
            if mode == "off" or not_merged or not order:
                reason: Literal["gate_mode=off", "not_all_merged", "nothing_planned"] = (
                    "gate_mode=off"
                    if mode == "off"
                    else "not_all_merged"
                    if not_merged
                    else "nothing_planned"
                )
                self._emit(
                    IntegrationGateSkipped(
                        **self._env(),
                        reason=reason,
                        subtasks=not_merged if reason == "not_all_merged" else (),
                    )
                )
                return
            if self._gate is None:
                msg = f"the integration call cannot pass: gate mode is {mode!r} and no gate"
                raise GateNotRegisteredError(msg, gate_mode=mode)
            head = self._expected_run_head()
            if head is None:
                msg = "an integration call with no run branch head recorded"
                raise RunStateError(msg, run_dir=str(self.run_dir))
            baseline, change_sets = change_history(self.log.events)
            artefact = IntegrationArtefact(
                run_id=self.config.run_id,
                graph_root=str(self._graph.root),
                run_head=head,
                baseline_revision=baseline,
                change_sets=change_sets,
            )
            result = require_mode(self._gate.check_integration(artefact, mode=mode), mode)
            self._emit(IntegrationGateRan(**self._env(), result=result))
            if result.verdict == "pass" or result.mode == "observe":
                return
        ran = self.state.integration
        if not isinstance(ran, IntegrationGateRan) or self.state.integration_escalated:
            return
        item_id = f"{self.config.run_id}-{INTEGRATION}"
        if item_id not in {item.item_id for item in self.queue.items()}:
            head = run_head_of(self.log.events) or ""
            # A plan started without a decomposition has no recorded start; its span
            # is then the head alone.
            start = next(
                (e.spec_commit for e in self.log.events if isinstance(e, Decomposed)), head
            )
            sessions = [
                a.session
                for sub in self.state.subtasks.values()
                for a in sub.attempts
                if a.merged is not None and a.session is not None
            ]
            self.queue.add(
                integration_item(
                    item_id=item_id,
                    run_id=self.config.run_id,
                    result=ran.result,
                    run_span=(start, head),
                    trajectories=tuple(s.trajectory for s in sessions if s.trajectory),
                    ts=self.log.events[-1].ts,
                    consequence=self._consequence(INTEGRATION, "gate_escalation"),
                )
            )
        self._emit(IntegrationEscalated(**self._env(), item_id=item_id))

    def _contract(self) -> None:
        """Hold the pair the record owes a result to the clause, and record it (ARCH-051).

        The graph is read at the journal revision the log records. The result blocks nothing: the
        merge that owed it stands, and a failed contract withholds completion alone. An interface
        node the pair cannot be held to, or a journal that ends before the recorded revision, halts
        the run, and no result is recorded; a process killed between that incident and its halt
        writes the halt alone.
        """
        incident = self.state.incident
        if incident is not None:
            self._halt_for(None, incident.cause)
            return
        pair, head = self.state.owed_contract(), self.state.run_head
        if pair is None or head is None:
            msg = "a contract step with no pair owed a result, or no run head on the record"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        revision = self.state.journal_head
        what = f"the contract of {pair.producer.module} to {pair.consumer.module}"
        try:
            result = check_pair(pair, nodes_at(self._graph.root, revision))
        except DesignStateError as exc:
            detail = f"{what} reads the graph at journal revision {revision}: {exc}"
            self._incident(None, "foreign_journal_line", detail)
            return
        except ContractError as exc:
            held = ", ".join(f"{key} {value}" for key, value in sorted(exc.context.items()))
            self._incident(None, "interface_mismatch", f"{what}: {exc} ({held})")
            return
        first = self.state.latest_contract(pair) is None
        self._emit(
            ContractTested(
                **self._env(), result=result, first=first, commit=head, revision=revision
            )
        )

    def _complete(self, step: Step) -> None:
        """Record the completion the record owes next (ARCH-051).

        Integration's attempt merged with its diff clean, its declaration names the module, and
        every precondition holds for it: the run state owes the line only then, in plan order.
        """
        integration = self.state.completion_subtask
        if step.subtask_id is None or integration is None:
            msg = "a completion step with no module, or in a run with no subtask that declares one"
            raise RunStateError(msg, step=step.kind)
        # The writer refuses the line unless the register names the declaring role as the one
        # owner of completion, and a refusal there records nothing, in this process or any after
        # it. So the register is asked first, as a dispatch asks it (:meth:`_mark_borne_out`),
        # and the run halts with the cause on the record.
        why = completion_owner_problem(self.state.subtasks[integration].plan.assigned_role)
        if why is not None:
            self._incident(None, "duty_breach", f"subtask {integration}: {why}")
            return
        attempt = self.state.subtasks[integration].attempts[-1].number
        self._emit(
            ModuleCompleted(
                **self._env(), subtask_id=step.subtask_id, declared_by=integration, attempt=attempt
            )
        )

    def _diff(self, subtask_id: str, attempt: int) -> None:
        # A person's approve is carried on from the record, never resumed: its attempt ended
        # without a merge, so no resume line takes the cursor back. A process killed after the
        # stage line and before the check leaves the stage entered, and the check is made under
        # it, so the stage is never entered twice and the check never left out.
        if self.state.subtasks[subtask_id].attempts[-1].cursor != "diff":
            self._stage(subtask_id, attempt, "diff")
        now = self.state.subtasks[subtask_id].attempts[-1]
        # A check on the record here named divergences, since a clean one makes the subtask done:
        # a process was killed before the incident it owed, or before the halt after it. What
        # that process would have written next is written now, and nothing twice.
        checked, written = now.diff, self.state.incident
        if (
            checked is not None
            and written is not None
            and written.subtask_id == subtask_id
            and written.seq > checked.seq
        ):
            self._halt_for(subtask_id, written.cause)
            return
        since = min(now.applied.values()) - 1 if now.applied else self.state.journal_head
        role = self.state.subtasks[subtask_id].plan.assigned_role
        found = self._graph.divergences(since, role)
        named = tuple(str(d) for d in found)
        if checked is None:
            self._emit(
                DiffChecked(
                    **self._env(), subtask_id=subtask_id, attempt=attempt, divergences=named
                )
            )
        else:
            # The graph still holds those writes, so it gives the cause; the check's own line,
            # the detail.
            named = checked.divergences
        if named:
            # A write past the store's own guard is the graver of the two, and the cause a
            # step that made one was always recorded under; duty breaches alone are a breach.
            foreign = any(d.reason == REJECT_CROSS_ROLE for d in found)
            cause: IncidentCause = "cross_role_write" if foreign else "duty_breach"
            self._incident(subtask_id, cause, "; ".join(named))

    # -- what is not an attempt ---------------------------------------------------------

    def _infra_failed(self, subtask_id: str, attempt: int) -> None:
        now = self.state.subtasks[subtask_id].attempts[-1]
        delay = infra_retry_delay(self.config.bounds.infra_retry_delays_s, now.retries_done)
        cause = now.session.cause if now.session else "unknown"
        if cause == "credential_refused":
            variable = SECRET_VARIABLE[self.config.auth]
            detail = (
                f"subtask {subtask_id} attempt {attempt}: the API refused the "
                f"{self.config.auth} credential; replace {variable} and resume"
            )
            self._emit(Halted(**self._env(), reason="credential_refused", detail=detail))
            return
        if cause == "sandbox_unavailable":
            detail = (
                f"subtask {subtask_id} attempt {attempt}: the session's OS layer would not "
                "start, so the session refused to run without it; repair the sandbox's "
                "dependencies and resume (the binary's message is in the session's stream)"
            )
            self._emit(Halted(**self._env(), reason="os_layer_unavailable", detail=detail))
            return
        if delay is None:
            detail = (
                f"subtask {subtask_id} attempt {attempt}: {cause} after "
                f"{now.retries_done} infrastructure retries"
            )
            self._emit(Halted(**self._env(), reason="infrastructure_exhausted", detail=detail))
            return
        self._emit(
            InfraRetryScheduled(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                retries_done=now.retries_done,
                delay_s=delay,
            )
        )
        self._sleep(delay)

    def _earlier_sessions(self, subtask_id: str, attempt: int) -> tuple[SessionTrajectory, ...]:
        """The attempt's sessions before the one that completed it, each with its stream.

        Raises:
            RunStateError: an earlier session left a sealed stream the log does not name,
                so the attempt's whole trajectory cannot be shown.
        """
        now = self.state.subtasks[subtask_id].attempts[-1]
        found = []
        for session in now.ended[:-1]:
            if session.trajectory_seal is None:
                continue  # it left no stream: nothing it did is on record to show
            if session.trajectory is None:
                msg = "an earlier session of the attempt has a sealed stream the log does not name"
                raise RunStateError(msg, subtask=subtask_id, attempt=str(attempt))
            found.append(
                SessionTrajectory(
                    session_id=session.session_id,
                    trajectory=session.trajectory,
                    trajectory_sha256=session.trajectory_seal.sha256,
                    trajectory_length=session.trajectory_seal.length,
                )
            )
        return tuple(found)

    def _attempt_series(
        self, subtask_id: str, attempt: int, checks: tuple[SeriesCheck, ...]
    ) -> AttemptSeries | None:
        """The records the attempt's sessions sealed and its quantities' checks, if any.

        Read from the attempt's own session-end lines, a later session's record superseding
        an earlier one's of the same id, as the change check read them.
        """
        ended = self.state.subtasks[subtask_id].attempts[-1].ended
        entries = attempt_records(ended, subtask_id, attempt)
        if not entries and not checks:
            return None
        return AttemptSeries(
            run_dir=str(self.run_dir),
            subtask_id=subtask_id,
            attempt=attempt,
            records=tuple(AttemptRecord(session_id=e.session_id, record=e.record) for e in entries),
            checks=checks,
        )

    def _sealed_hold(self, sessions: list[SessionEnded]) -> bool:
        """Every stream the sessions name is sealed and still what was sealed; else an incident."""
        for session in sessions:
            if session.trajectory is not None and session.trajectory_seal is None:
                detail = f"session {session.session_id}'s stream is named and has no seal"
                self._incident(None, "trajectory_tampered", detail)
                return False
        return self._trajectories_hold(None, sessions)

    def _trajectories_hold(self, subtask_id: str | None, sessions: list[SessionEnded]) -> bool:
        """Every sealed trajectory is still what it was; otherwise an incident."""
        for session in sessions:
            if session.trajectory is None or session.trajectory_seal is None:
                continue
            try:
                read_sealed(Path(session.trajectory), session.trajectory_seal)
            except TrajectoryTamperedError as exc:
                self._incident(subtask_id, "trajectory_tampered", f"{exc}: {exc.context}")
                return False
        return True

    def _to_a_person(self, subtask_id: str) -> None:
        """Send a subtask whose review blocked it or reached no verdict to a person.

        No attempt is spent. A blocked review is on the record as a review; only the routing is
        shared with a review that reached no verdict.
        """
        session = self.state.subtasks[subtask_id].attempts[-1].session
        if session is None:
            msg = "a review sent to a person with no completed session behind it"
            raise RunStateError(msg, subtask=subtask_id)
        if not self._trajectories_hold(subtask_id, [session]):
            return
        scan: tuple[ScanHit, ...] = ()
        if source_of(self.state.subtasks[subtask_id]) in SCANNED_SOURCES and self._acts():
            found = self._scan_hits(subtask_id, where=subtask_id)
            if found is None:
                return
            scan = found
        item_id = self._next_item_id(subtask_id)
        if item_id not in {item.item_id for item in self.queue.items()}:
            self.queue.add(
                self._item_for(subtask_id, item_id=item_id, ts=self.log.events[-1].ts, scan=scan)
            )
        self._emit(Escalated(**self._env(), subtask_id=subtask_id, item_id=item_id))

    def _item_for(
        self, subtask_id: str, *, item_id: str, ts: str, scan: tuple[ScanHit, ...]
    ) -> QueueItem:
        """The item the loop lists for a subtask it sends to a person, from the record alone.

        The one builder: what a person is shown, and what a decision on it is held to when the
        loop takes it, are the same function of the event log, so an item listed otherwise than
        this rebuilds it is not one the loop wrote (ARCH-133). ``ts`` is the item's own time;
        ``scan`` what the scan before review found, for an item whose review never judged it.

        Raises:
            RunStateError: the subtask did not end in a way that reaches the queue, or its last
                attempt has no completed session behind it.
        """
        sub = self.state.subtasks[subtask_id]
        try:
            source = source_of(sub)
        except ValueError as exc:
            raise RunStateError(str(exc), subtask=subtask_id) from None
        attempts = sub.attempts
        now = attempts[-1]
        if source in ("review_unavailable", "review_blocked"):
            session = now.session
            if session is None or session.trajectory is None or session.attempt_commit is None:
                msg = "a review sent to a person with no completed session behind it"
                raise RunStateError(msg, subtask=subtask_id)
            blocked, unavailable = now.blocked, now.unavailable_final
            if blocked is not None:
                attempt, cause = blocked.attempt, "blocking_spec_defect"
                detail, defects = blocked.result.finding, blocked.result.spec_defects
            elif unavailable is not None:
                attempt, cause = unavailable.attempt, unavailable.cause
                detail, defects = unavailable.detail, unavailable.spec_defects
            else:  # source_of names one of the two only when the attempt carries it
                msg = "a review sent to a person that neither blocked nor reached no verdict"
                raise RunStateError(msg, subtask=subtask_id)
            return unavailable_item(
                item_id=item_id,
                run_id=self.config.run_id,
                subtask_id=subtask_id,
                attempt=attempt,
                source="review_blocked" if blocked is not None else "review_unavailable",
                cause=cause,
                detail=detail,
                spec_defects=defects,
                artefact_diff=self._merger.artefact_diff(session.attempt_commit),
                trajectory=session.trajectory,
                ts=ts,
                consequence=self._consequence(subtask_id, source, scan),
            )
        findings = tuple(a.rejected.finding for a in attempts if a.rejected is not None)
        sessions = [a.session for a in attempts if a.session is not None]
        trajectories = tuple(s.trajectory for s in sessions if s.trajectory is not None)
        commits = [s.attempt_commit for s in sessions if s.attempt_commit is not None]
        decided = now.decided
        if source == "escalation_decision" and decided is not None:
            # Sent to a person with attempts left, by the backend's answer or the confidence
            # floor: an item of its own, with the attempts made so far.
            return decided_item(
                item_id=item_id,
                run_id=self.config.run_id,
                subtask_id=subtask_id,
                decision=decided.decision,
                findings=findings,
                artefact_diff=self._merger.artefact_diff(commits[-1]),
                trajectories=trajectories,
                ts=ts,
                attempt=now.number,
                consequence=self._consequence(subtask_id, "escalation_decision", scan),
            )
        return escalation_item(
            item_id=item_id,
            run_id=self.config.run_id,
            subtask_id=subtask_id,
            findings=findings,
            artefact_diff=self._merger.artefact_diff(commits[-1]),
            trajectories=trajectories,
            ts=ts,
            spent_by_person=sum(
                1 for a in attempts if a.person_rejected is not None and a.rejected is None
            ),
            consequence=self._consequence(subtask_id, "repair_budget_exhausted", scan),
        )

    def _next_item_id(self, subtask_id: str) -> str:
        """The id of the subtask's next queue item: a new round each time it comes back."""
        return item_id_for(
            self.config.run_id, subtask_id, self.state.subtasks[subtask_id].rounds + 1
        )

    def _escalate(self, subtask_id: str) -> None:
        attempts = self.state.subtasks[subtask_id].attempts
        sessions = [a.session for a in attempts if a.session is not None]
        if not self._trajectories_hold(subtask_id, sessions):
            return  # the queue item would link a trajectory that is not what was sealed
        scan: tuple[ScanHit, ...] = ()
        if self._acts():
            # An attempt that ended at the gate or the change check was never reviewed, and its
            # work is in the commit an approve would merge: its streams are scanned as well.
            found = self._scan_hits(subtask_id, where=subtask_id)
            if found is None:
                return
            scan = found
        item_id = self._next_item_id(subtask_id)
        if item_id not in {item.item_id for item in self.queue.items()}:
            self.queue.add(
                self._item_for(subtask_id, item_id=item_id, ts=self.log.events[-1].ts, scan=scan)
            )
        self._emit(Escalated(**self._env(), subtask_id=subtask_id, item_id=item_id))
