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

import contextlib
import hashlib
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from physgate.contracts.clause import check_pair
from physgate.contracts.graph import nodes_at
from physgate.contracts.pairs import ContractError
from physgate.gate.exceptions import GateError
from physgate.orchestrator import integration_state as render
from physgate.orchestrator.apply import ProposalRefusedError
from physgate.orchestrator.arbitration import (
    ContractConflict,
    DisputeConflict,
    Held,
    Level,
    arbitrate,
    dispute_standing,
)
from physgate.orchestrator.budget import infra_retry_delay
from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.common import PLANNED_ID_MAX_LENGTH, SUBTASK_PATTERN, utc_now
from physgate.orchestrator.credentials import SECRET_VARIABLE
from physgate.orchestrator.decisions import (
    SCANNED_SOURCES,
    closing_order,
    conform_order,
    contract_choices,
    contract_consequence,
    decision_effect,
    item_consequence,
    person_order,
    scan_hits_of,
    source_of,
)
from physgate.orchestrator.declaration import DeclarationError
from physgate.orchestrator.decompose import contracts_of
from physgate.orchestrator.dispute import DISPUTES_DIR, UNRECORDABLE, disputer_problem
from physgate.orchestrator.escalation import TO_THE_QUEUE, EscalationInterface, bind
from physgate.orchestrator.escalation_state import RUBRIC_ITEM, escalation_state
from physgate.orchestrator.events import (
    RULE,
    RULE_REASON,
    ArbitrationDecided,
    AttemptRejected,
    AttemptReturned,
    CompletionDeclared,
    ContractItemRaised,
    ContractRuled,
    ContractTested,
    ContractValue,
    DecisionsSealed,
    DecisionTaken,
    Decomposed,
    DiffChecked,
    DisputeRecorded,
    Envelope,
    EnvironmentRecorded,
    Escalated,
    EscalationDecided,
    Event,
    FindingsRecorded,
    FollowUpEnded,
    GateRan,
    GateSkipped,
    Halted,
    Incident,
    IncidentCause,
    IncidentResolved,
    InfraRetryScheduled,
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
    OwedEdge,
    PartsReleased,
    PartsWriteDone,
    PartsWriteIntended,
    PlanRejected,
    ProposalsChecked,
    ReleasedPart,
    Resumed,
    ReviewRan,
    ReviewUnavailable,
    SessionEnded,
    SessionFinding,
    SessionSpawned,
    Stage,
    StageEntered,
    StatedPart,
    SubtaskRejected,
    SubtaskReopened,
    TokensUsed,
    WorktreeRemoved,
    WriteDone,
    WriteIntended,
    completion_mark_problem,
    completion_owner_problem,
)
from physgate.orchestrator.exceptions import (
    CorruptEventLogError,
    EscalationBackendError,
    GateNotRegisteredError,
    GitError,
    HeldOutExposedError,
    MergeConflictError,
    MergeRefusedError,
    QueueError,
    QueueItemMismatchError,
    ReviewerNotRegisteredError,
    ReviewUnavailableError,
    RunStateError,
    StoreRefusalError,
    TrajectoryTamperedError,
    WorktreeMisplacedError,
)
from physgate.orchestrator.follow_up import follow_up_order, owed
from physgate.orchestrator.followed import FollowedInterface
from physgate.orchestrator.held_records import record_change, second_names, unaccounted
from physgate.orchestrator.integration_state import issued_state
from physgate.orchestrator.invocation import TRAFFIC_ALLOWED_VERSIONS
from physgate.orchestrator.managed import (
    ObservedTraffic,
    SessionManaged,
    UnshowableKeyError,
    limits_with,
    policy_diff,
    policy_limits_change,
    policy_limits_unjudged,
    read_limits,
    session_limits,
    stricter_only,
    traffic_change,
)
from physgate.orchestrator.merge import merge_message
from physgate.orchestrator.parts_write import (
    TakenPart,
    parts_record,
    parts_writes,
    unlanded_declared,
)
from physgate.orchestrator.ports import (
    HOOK_LOG_UNREAD,
    ChangeCheck,
    ChangeChecker,
    Dispatcher,
    GraphPort,
    Leftover,
    MaterialCheck,
    Merger,
    RecordsSpawns,
    SessionReport,
    SessionRequest,
)
from physgate.orchestrator.protocols import (
    REJECTING_RESULTS,
    Artefact,
    AttemptScope,
    Gate,
    GateResult,
    IntegrationArtefact,
    IssuedSpec,
    IssuedState,
    PersonOrder,
    QuantityRef,
    Reviewer,
    ReviewResult,
    SessionTrajectory,
    require_mode,
    require_separate_models,
)
from physgate.orchestrator.queue import (
    INTEGRATION,
    ItemConsequence,
    PartsBody,
    QueueItem,
    QueueResolution,
    QueueSource,
    QueueView,
    arbitration_item,
    contract_item,
    decided_item,
    decisions_file_bytes,
    escalation_item,
    held_windows_of,
    integration_item,
    item_id_for,
    parts_sha256,
    read_queue,
    round_stream,
    stream_parts,
    unavailable_item,
    whole_lines,
    within,
)
from physgate.orchestrator.record import PlanEntry, RunRecord
from physgate.orchestrator.repair import (
    Finding,
    arbitration_value_instruction,
    repair_instruction,
)
from physgate.orchestrator.replay import (
    AttemptState,
    Step,
    SubtaskState,
    at_a_boundary,
    following_up,
    recorded_implementer,
    replay,
    require_mergeable,
    why_not_merged,
)
from physgate.orchestrator.run_config import RunConfig, os_layer_refusal
from physgate.orchestrator.trajectory import read_sealed
from physgate.reviewers.packet import fits_one_read, person_order_text
from physgate.reviewers.scan import ScanHit, ScanUnreadableError
from physgate.roles import dispatchable, owners_of, require_registered
from physgate.series.reader import attempt_records
from physgate.series.seal import AttemptRecord, AttemptSeries, SeriesCheck
from physgate.state.exceptions import DesignStateError, StoreStaleError
from physgate.state.held_file import HeldFile
from physgate.state.protocol import REJECT_CROSS_ROLE
from physgate.state.schema import REJECT_DECLARED_FIXED, REJECT_DECLARED_FORGED, Node, validate_node
from physgate.state.store import JournalLine, payload_digest

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


#: Which of a resume's leftover findings names its one halt, first found first: a stream something
#: else wrote, then an exposure, then reviewer material, then a stream set aside; then, last, what a
#: session taken up after its own end showed beside its stream: a refused placeholder, other policy
#: limits, a possible abort, an unverified reaping.
LEFTOVER_HALTS: tuple[IncidentCause, ...] = (
    "trajectory_tampered",
    "held_out_read",
    "review_material_read",
    "stream_quarantined",
    "placeholder_refused",
    "managed_settings_changed",
    "os_layer_aborted",
    "reaper_unverified",
    "run_records_changed",
)


def _unjudged(report: SessionReport) -> str | None:
    """Why a session's missing policy limits are recorded and not judged, if they are."""
    return policy_limits_unjudged(
        report.end, answered=report.model_answered, now=report.policy_limits_sha256
    )


def _possible_abort(session_id: str, tool_uses: tuple[str, ...]) -> str:
    """The detail of a possible abort: the results of a session that carry bubblewrap's line."""
    return (
        f"possible abort: {len(tool_uses)} result(s) of session {session_id} carry bubblewrap's "
        f"own line, which the command may have printed itself: {', '.join(tool_uses)}"
    )


def _unverified_reaping(session_id: str, commands: tuple[str, ...]) -> str:
    """The detail of an unverified reaping: the commands whose reaper's done line was cut off.

    Where the hook layer's log could not be read, that is said on its own: no command of the
    session's is then taken as heard from.
    """
    unread = [why for why in commands if why.startswith(HOOK_LOG_UNREAD)]
    cut = [command for command in commands if not command.startswith(HOOK_LOG_UNREAD)]
    said = (
        [
            f"{len(cut)} shell command(s) of session {session_id} gave output longer than Claude "
            f"Code keeps, so the survivor reaper's done line could not be read: {'; '.join(cut)}"
        ]
        if cut
        else []
    )
    said += (
        [
            f"for session {session_id}, {'; '.join(unread)}, so no shell command's survivor reaper "
            "is taken as heard from"
        ]
        if unread
        else []
    )
    return "; ".join(said)


#: What the integration item names of a review is a reviewer's output, read back from the log: each
#: value is held to the pattern it has where it is written, or a placeholder stands in its place.
_ITEM = re.compile(RUBRIC_ITEM)
_CRITERION = re.compile(r"[0-9]{1,6}")
_CHECK = re.compile(r"[a-z][a-z0-9_]{0,63}")
REFUSED_RUBRIC_ITEM = "(a rubric item id the rubric's id pattern refuses)"
REFUSED_CRITERION = "(a criterion the specification's numbering refuses)"
REFUSED_CHECK = "(a check name the gate's names refuse)"
#: How many of one list the item names before it counts the rest, and its longest account.
LISTED_AT_MOST = 8
TOLD_AT_MOST = 4_000


def _listed(values: list[str]) -> str:
    left = len(values) - LISTED_AT_MOST
    return ", ".join(values[:LISTED_AT_MOST]) + (f", and {left} more left out" if left > 0 else "")


def _account(told: list[str]) -> str:
    """Each module's account, in order, as long as the whole stays within its cap; then a count."""
    kept = [one for k, one in enumerate(told) if len("; ".join(told[: k + 1])) <= TOLD_AT_MOST]
    left = len(told) - len(kept)
    return (
        "Sizing's closing pass changed values nodes of these modules depend on: "
        f"{'; '.join(kept)}{f'; and {left} more modules left out' if left else ''}."
    )


def _follow_up_end(now: AttemptState | None) -> str:
    """How a module's follow-up ended, in the record's structured fields; ``now`` is its attempt."""
    if now is None:
        return "none owed (merged on its fix, or its order no read shows whole)"
    if now.merged is not None:
        return f"its follow-up merged at attempt {now.number}"
    said = [f"its follow-up ended {why_not_merged(now)}"]  # one of its enum's words, by code
    held = render.held
    if isinstance(now.gate, GateRan) and now.gate.result.verdict == "fail":
        check = now.gate.result.failing_check or ""
        said.append(f"gate check {held(check, _CHECK, 64, REFUSED_CHECK)}")
    review = now.review.result if now.review is not None else None
    if review is not None:
        failing = [
            f"{held(i.item, _ITEM, 16, REFUSED_RUBRIC_ITEM)} ({i.result})"
            for i in review.items
            if i.result in REJECTING_RESULTS
        ]
        blocking = [
            f"criterion {held(c.criterion, _CRITERION, 6, REFUSED_CRITERION)}"
            for c in review.criteria
            if c.defect and c.defect.blocking
        ]
        blocking += [
            f"item {held(d.item, _ITEM, 16, REFUSED_RUBRIC_ITEM)}"
            for d in review.spec_defects
            if d.blocking and d.item
        ]
        said += [f"failing items {_listed(failing)}"] if failing else []
        said += [f"blocking {_listed(blocking)}"] if blocking else []
    return "; ".join(said)


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
        self._follow_ups_checked = False  # held to the journal once in this process
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
        if self._took_an_owed_halt():
            return self._drive()
        if self.state.halted is None and self.state.interrupted() is not None:
            msg = "the run was interrupted mid-attempt; resume it instead"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if self.state.halted is None and not self._journal_clean():
            return self.state.next_step()
        return self._drive()

    def _took_an_owed_halt(self) -> bool:
        """Take the halt the record owes, then stop the leftovers; whether one was owed.

        First, before the leftovers' lines: replay takes nothing but its incidents and its halt
        while they are owed, and a check of this process's own would find again what the record
        already holds and write a second incident. The leftovers are stopped either way.
        """
        owed = self.state.halt_owed()
        if owed:
            self._owed_halt()
        self._stop_leftovers()
        return owed

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
        if self._took_an_owed_halt():
            return self._drive()
        halted = self.state.halted
        if halted is not None and not self.state.halt_resumable():
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
        if self.config.queue_decisions != "act" and not set(confirm) <= set(
            self.state.contract_items
        ):
            # A run that records only confirms nothing but a contract item's held decision, which
            # a completion waits on there too.
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
        """Stop what a previous process left running, before anything reads or writes.

        The dispatcher ends the leftovers once what they showed is on the record, before any of
        their own lines, so a process killed before that finds them again. Two
        or more findings are one findings line first, then each leftover's lines, then each
        incident and one halt; a lone finding is its incident first, then the lines and the halt.
        In order: every exposure, reviewer material and set-aside stream, leftover by leftover,
        then every tampered stream, then what each session taken up after its own end showed beside
        its stream. The halt is the first cause :data:`LEFTOVER_HALTS` names.
        """
        if not self.log.events:
            return
        leftovers = self._dispatcher.stop_leftovers()
        found: list[tuple[IncidentCause, str]] = []
        for left in leftovers:
            sid = left.session_id
            if left.held_out_seen is not None:
                # As at a normal session end: the tier counts as exposed (ARCH-141), and the
                # exposure is recorded whatever else the resume finds. The canary is not.
                found.append(("held_out_read", f"held-out material in the stream of leftover "
                              f"session {sid}"))  # fmt: skip
            if left.review_material_seen is not None:
                # A role session that read what only its reviewer reads, found at the resume as
                # at a normal session end. The canary is not recorded.
                found.append(("review_material_read", f"reviewer material in the stream of "
                              f"leftover session {sid}"))  # fmt: skip
            if left.quarantine is not None:
                # The operator set a gone stream aside: nothing was scanned, so the session's
                # work is never counted as clean. The run halts as an incident, once.
                found.append(("stream_quarantined", f"leftover session {sid}: {left.scan}; "
                              f"set aside by {left.quarantine}"))  # fmt: skip
        found += [
            ("trajectory_tampered", f"leftover session {left.session_id}: {why}")
            for left in leftovers
            if (why := left.tampered) is not None
        ]
        for left in leftovers:
            found += self._taken_up_findings(left)
        for left in leftovers:
            found += self._records_findings(left)
        # Whatever was left, or nothing: every held record is the orchestrators' as the write
        # account names it, after the run's end as before it.
        found += self._account_findings()
        causes = {cause for cause, _ in found}
        halt = next((c for c in LEFTOVER_HALTS if c in causes), None)
        if len(found) > 1 and halt is not None:
            listed = tuple(SessionFinding(cause=cause, detail=detail) for cause, detail in found)
            self._emit(FindingsRecorded(**self._env(), subtask_id=None, findings=listed, halt=halt))
        for cause, detail in found[:1] if len(found) == 1 else ():
            self._emit(Incident(**self._env(), subtask_id=None, cause=cause, detail=detail))
        # Only now, with what they showed on the record, are they ended: a process killed before
        # this finds them again.
        self._dispatcher.end_leftovers()
        for left in leftovers:
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
        for cause, detail in found if len(found) > 1 else ():
            self._emit(Incident(**self._env(), subtask_id=None, cause=cause, detail=detail))
        if halt is not None:
            self._halt_for(None, halt)

    def _records_findings(self, left: Leftover) -> list[tuple[IncidentCause, str]]:
        """Each held record the leftover's start, this process and the write account do not explain.

        Judged by :func:`held_records.record_change` against this process's writers, before any
        line of the leftovers is written, for every held record this process writes: one the
        session's start does not name is a change too, and so is a start that names none. Every
        byte of a record before this process opened it must be one the write account names
        (:func:`held_records.unaccounted`): what a line says makes it no orchestrator's. A change
        no orchestrator made is an incident, and the run halts on it. A record this process no
        longer holds refuses the first line written to it, so the incident is never written
        where no one will read it.
        """
        if left.kind != "session" or left.records_at_start == ():
            # No start was read for it: a dispatcher that installs no sentinel, as a test's.
            return []
        sid = left.session_id
        if left.records_at_start is None:
            none = "the sentinel's record of its start names none of the run's held records"
            return [("run_records_changed", f"leftover session {sid}: {none}")]
        writers = self._held_writers()
        starts = {os.path.realpath(s.path): s for s in left.records_at_start}
        found: list[tuple[IncidentCause, str]] = []
        for path, held in sorted(writers.items()):
            start = starts.get(os.path.realpath(path))
            if start is None:
                why: str | None = "the sentinel's record of the session's start does not name it"
            else:
                why = record_change(start, held, unaccounted_why=None)
            if why is not None:
                found.append(("run_records_changed", f"leftover session {sid}: {path}: {why}"))
        return found

    def _held_writers(self) -> dict[Path, HeldFile | None]:
        """This process's writer of each held record, by its path."""
        account = self.record.account
        return {
            self.log.path: self.log.held,
            self.ledger.path: self.ledger.held,
            self.queue.path: self.queue.held,
            account.path: account.held,
        }

    def _named_also(self, why: str, held: HeldFile, path: Path) -> str:
        """``why``, with every other name for the record's file under the run directory."""
        others = [p for p in second_names([held.identity], [self.run_dir]) if p != str(path)]
        return f"{why}: {', '.join(others)}" if others else why

    def _account_findings(self) -> list[tuple[IncidentCause, str]]:
        """Each held record the write account does not name as the orchestrators', or renamed.

        At every resume, whatever was left: :func:`held_records.unaccounted` walks each record
        along the account from its first byte; the account itself is held to its one name and
        its form.
        """
        account = self.record.account
        found: list[tuple[IncidentCause, str]] = []
        for path, held in sorted(self._held_writers().items()):
            if held is None:
                why: str | None = "this process holds no writer of it"
            elif held is account.held:
                why = account.problem
            else:
                why = unaccounted(held, account.earlier, None)
            if why is None and held is not None:
                links = os.lstat(path).st_nlink
                if links != 1:
                    why = self._named_also(f"the file has {links} names", held, path)
            if why is not None:
                found.append(("run_records_changed", f"{path}: {why}"))
        return found

    def _taken_up_findings(self, left: Leftover) -> list[tuple[IncidentCause, str]]:
        """What a session taken up after its own end showed beside its stream, as that end would.

        The dispatcher read them again only for such a session. The policy limits are held to the
        run's first only there: for a session left running nothing was read, and no digest is no
        finding of its own.
        """
        sid = left.session_id
        found: list[tuple[IncidentCause, str]] = []
        if left.placeholders_refused is not None:
            found.append(("placeholder_refused", f"leftover session {sid}: "
                          f"{left.placeholders_refused}"))  # fmt: skip
        changed = left.policy_limits_unsure or (
            policy_limits_change(self._policy_baseline(), left.policy_limits_sha256)
            if left.taken_up
            else None
        )
        if changed is not None:
            found.append(("managed_settings_changed", f"leftover session {sid}: {changed}"))
        if left.os_layer_aborted:
            found.append(("os_layer_aborted", _possible_abort(sid, left.os_layer_aborted)))
        if left.reaper_unverified:
            found.append(("reaper_unverified", _unverified_reaping(sid, left.reaper_unverified)))
        return found

    def _clean_up_worktrees(self) -> None:
        """Remove the worktrees the rules allow, recording each; never stall or fail the run.

        A done subtask's (merged, diff clean), and an escalated subtask's once its
        queue item has a decision. Nothing else, and never forced.
        """
        try:
            self.queue.refresh()  # a person may have decided while a session ran
        except QueueError as exc:
            # Recorded once: a run already halted, or halting, for it has its incident.
            if not self._decisions_unreadable(exc, write=not self.state.halted):
                raise
            return
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
            self._remove_worktree(subtask_id, reason)

    def _remove_worktree(self, subtask_id: str, reason: Literal["done", "queue_resolved"]) -> None:
        """Remove the subtask's present worktree, and record it; never stall or fail the run."""
        sub = self.state.subtasks[subtask_id]
        removal = self._merger.remove_worktree(subtask_id, reopen=sub.reopens)
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

    def _before_a_reopen(self, subtask_id: str) -> None:
        """The merged subtask's worktree, removed before its reopen unless a stop removed it.

        A reopened subtask works in a fresh worktree, and no stop need come between its merge and
        its reopen (a follow-up never has one), so the old one is removed here, once. A process
        killed after the removal and before its line finds it absent and records that.
        """
        if subtask_id not in self.state.worktrees_handled:
            self._remove_worktree(subtask_id, "done")

    def _drive(self) -> Step:
        # The environment is recorded for a step that spawns a session; the integration
        # call, a contract result, a completion line, an owed halt and a finished run spawn none.
        # A process whose first step is one of those may still spawn one, after a decision it
        # takes or the call it makes: that session's line is recorded before it, once
        # (:meth:`_session`).
        first = self.state.next_step().kind
        if first not in (
            "done",
            "halted",
            "escalated",
            "integrate",
            "contract",
            "complete",
            "halt",
            "wait",
            "parts",
            "reopen",
            "follow_up_ended",
        ):
            self._record_environment()
        while True:
            step = self.state.next_step()
            if (
                step.kind == "attempt"
                and not self._follow_ups_checked
                and following_up(self.state.subtasks[step.subtask_id or ""], step.attempt)
            ):
                # A process killed between two follow-up lines left a part: written here first.
                self._follow_ups(write=True)
                continue
            if self._at_a_boundary(step) and self._take_decisions():
                continue  # what a decision did changes what comes next
            if step.kind in ("done", "halted", "escalated", "wait"):
                if self._decisions_refused_at_the_end():
                    continue  # the run halts on it: that is the step it ends on
                self.record.hold_plan()  # a decompose killed before it listed the plan's item
                self.record.hold_parts()  # and before it listed each part, or the plan's hold left
                self._clean_up_worktrees()
                return step
            if step.kind == "halt":
                # A process killed between an incident and its halt: the halt, and nothing else.
                self._owed_halt()
                continue
            if step.kind == "parts":
                self._release_parts()
                continue
            if step.kind == "integrate":
                self._integrate()
                continue
            if step.kind == "contract":
                self._contract()
                continue
            if step.kind == "complete":
                self._complete(step)
                continue
            if step.kind == "reopen":
                self._reopen()
                continue
            if step.subtask_id is None or step.attempt is None:
                msg = "a step with no subtask or attempt"
                raise RunStateError(msg, step=step.kind)
            if step.kind == "end_subtask":
                self._end_subtask(step.subtask_id, step.attempt)
            elif step.kind == "decide":
                self._decide(step.subtask_id, step.attempt)
            elif step.kind == "follow_up_ended":
                why = why_not_merged(self.state.subtasks[step.subtask_id].attempts[-1])
                self._emit(
                    FollowUpEnded(
                        **self._env(), subtask_id=step.subtask_id, attempt=step.attempt, why=why
                    )
                )
            elif step.kind == "escalate":
                now = self.state.subtasks[step.subtask_id].attempts[-1]
                if now.unavailable_final is not None or now.blocked is not None or now.queued:
                    self._to_a_person(step.subtask_id)
                else:
                    self._escalate(step.subtask_id)
            elif step.kind == "infra_failed":
                self._infra_failed(step.subtask_id, step.attempt)
            elif step.kind == "return":
                resized = self.state.subtasks[step.subtask_id].attempts[-1].resized
                item_id = resized.item_id if resized is not None else ""
                self._emit(
                    AttemptReturned(
                        **self._env(),
                        subtask_id=step.subtask_id,
                        attempt=step.attempt,
                        item_id=item_id,
                    )
                )
            elif self._roles_built():
                self._attempt(step.subtask_id, step.attempt, step.point or "resolve")

    def _roles_built(self) -> bool:
        """Whether every role the plan still names can be dispatched; otherwise the run halts.

        Asked before every attempt, so a run whose plan names a role registered for planning only
        halts at its first dispatch, before any session of any role is spent: it could never
        finish. The halt is not resumed; the run is decomposed again once the role is built.
        """
        unbuilt = sorted(
            {
                f"{sub.plan.subtask_id} ({sub.plan.assigned_role})"
                for sub in self.state.subtasks.values()
                if sub.status != "removed" and not dispatchable(sub.plan.assigned_role)
            }
        )
        if unbuilt:
            detail = (
                f"the plan names a role registered for planning only, whose sessions are not "
                f"dispatched until it is built: {', '.join(unbuilt)}"
            )
            self._emit(Halted(**self._env(), reason="role_not_built", detail=detail))
        return not unbuilt

    # -- a person's decisions -------------------------------------------------------------

    def _acts(self) -> bool:
        return self.config.queue_decisions == "act"

    def _at_a_boundary(self, step: Step) -> bool:
        """Where a decision may be taken (ARCH-133), in a run that acts on them.

        In a run that records only, too, while a failed contract's item is undecided: a completion
        waits for a decision on it in either mode, and the decision is taken, recording only.
        """
        open_ = any(self.state.undecided(i) for i in self.state.contract_items)
        return (self._acts() or open_) and at_a_boundary(step)

    def _held_windows(self) -> list[tuple[int, int | None]]:
        """The decisions file's ranges written while a session ran without the OS layer."""
        return held_windows_of(list(self.log.events))

    def _take_decisions(self) -> bool:
        """Take every decision not yet taken, in the decisions file's order; True if any was.

        Each becomes one ``decision_taken`` line computed by code from the item and the log;
        a held one the operator confirmed on the command line is taken again, acting.
        """
        try:
            self.queue.refresh()
            # One read of the file: the seals are checked on these bytes and the decisions parsed
            # from them, so nothing written between the two is taken.
            data = decisions_file_bytes(self.run_dir)
            sealed = self._decisions_as_sealed(data)
            view = read_queue(self.run_dir, decisions=data) if sealed else None
        except QueueError as exc:
            if not self._decisions_unreadable(exc):
                raise
            return True  # halted: the next step says so
        if view is None:
            return True  # halted: the next step says so
        items = {item.item_id: item for item in view.items}
        held = self._held_windows()
        confirm, confirmed_by = self._confirm
        took = False
        for offset, resolution in view.decisions:
            item = items[resolution.item_id]
            if not self._acts() and item.source != "contract":
                continue  # a run that records only takes no other decision into its log
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

    def _decisions_refused_at_the_end(self) -> bool:
        """Whether the decisions file, read before the drive returns, holds a line it refuses.

        Read before the run is ended, so a run never ends on a step its log does not: a person's
        line that does not read is the incident and the halt (:meth:`_decisions_unreadable`), and
        the drive goes on to that halt. A run already halted has its incident, and is not read here.
        """
        if self.state.halted is not None:
            return False
        try:
            self.queue.refresh()
        except QueueError as exc:
            if not self._decisions_unreadable(exc):
                raise
            return True
        return False

    def _decisions_unreadable(self, exc: QueueError, *, write: bool = True) -> bool:
        """Whether ``exc`` is the decisions file's reader refusing it; then, with ``write``, halt.

        A person's line that does not read is never read past and never mended here: one incident
        names the file and the line, and the run halts until a person mends the file. Any other
        refusal of the queue is not this one.
        """
        path = self.queue.decisions_path
        named = exc.context.get("queue") or exc.context.get("file")
        if named is None or Path(named) != path:
            return False
        if write and not self.state.halt_owed():
            where = "the file"
            offset = exc.context.get("offset")
            if offset is not None and offset.isdigit():
                with contextlib.suppress(OSError):
                    where = f"line {path.read_bytes()[: int(offset)].count(b'\n') + 1}"
            reason = exc.context.get("reason", "")
            self._incident(None, "decisions_unreadable", f"{path}, {where}: {exc} ({reason})")
        return True

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
        contract = item.source == "contract"
        whole = item.subtask_id == INTEGRATION or item.source in ("plan_review", "parts")
        subtask_id = None if whole or contract else item.subtask_id
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
            if item.source == "arbitration" and not self._held_holds(subtask_id):
                return False
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
        # A superseded item records only: its consequence is no longer the record's to rebuild.
        superseded = item.item_id in self.state.superseded
        if (
            contract
            and resolution.verb is not None
            and not superseded
            and not self._contract_item_holds(item)
        ):
            return False
        # Held to the record whole, not field by field: the item as listed must be the item the
        # loop builds from the log now, its links, finding, diff and consequence alike. Otherwise
        # the person decided on something the run did not write.
        rebuilt = (
            self._item_for(subtask_id, item_id=item.item_id, ts=item.ts, scan=scan)
            if subtask_id is not None
            else self.record.plan_item()
            if item.source == "plan_review"
            else self.record.parts_item_of(item.item_id)
            if item.source == "parts"
            else item
        )
        if resolution.verb is not None and rebuilt != item:
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
        # A release dispatches the plan the person approved on a view of the decomposition's
        # stream: it is taken only while that stream still holds the seal the review recorded,
        # as a merge is taken only over sealed streams.
        if taken.acts and taken.effect == "release" and not self._decomposition_holds():
            return False
        # A choice of the domain's value carries a session's typed value into the graph: it binds
        # only where every stream its item links still holds its seal.
        if (
            taken.effect == "resize"
            and subtask_id is not None
            and not self._sealed_hold(self._arbitration_sessions(subtask_id))
        ):
            return False
        self._emit(
            DecisionTaken(
                **self._env(),
                subtask_id=subtask_id,
                item_id=item.item_id,
                verb=resolution.verb,
                position=resolution.position,
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
                reopens=taken.reopens,
                parts_sha256=(
                    parts_sha256(resolution.parts) if resolution.parts is not None else None
                ),
            )
        )
        return True

    def _reopen(self) -> None:
        """Write the reopen the taken decision ordered: the subtask's next attempt, or its fix."""
        taken = self.state.pending_reopen
        sub = self.state.subtasks.get(taken.reopens or "") if taken is not None else None
        merged = sub.attempts[-1].merged if sub is not None and sub.attempts else None
        if taken is None or taken.shown_sha256 is None or sub is None or merged is None:
            msg = "a reopen with no decision that orders it, or of a subtask with no merge"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        self._before_a_reopen(sub.plan.subtask_id)
        self._emit(
            SubtaskReopened(
                **self._env(),
                subtask_id=sub.plan.subtask_id,
                item_id=taken.item_id,
                shown_sha256=taken.shown_sha256,
                merge_commit=merged.merge_commit,
                attempt=sub.attempts[-1].number + 1,
            )
        )

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
        now = sub.attempts[-1]
        by = "closing_pass" if sub.status == "waiting" else sub.ending
        if by is None:
            msg = "a subtask ended with no reason to"
            raise RunStateError(msg, subtask=subtask_id)
        spent = now.resized if by == "closing_pass" else now.person_rejected
        self._emit(
            SubtaskRejected(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                by=by,
                item_id=spent.item_id if by != "fix_not_accepted" and spent is not None else None,
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
        attempt's reviewer, are told exactly what the first session was. Sizing's closing pass,
        while a person's choice of the domain's value waits, is told each value chosen, wrapping
        what it would otherwise be told.

        Raises:
            RunStateError: a fix ordered after a review that did not block, or with no note.
        """
        told, order = self._told(subtask_id, attempt)
        if subtask_id == self.state.closing_pass():
            values = closing_order(self.state, told)
            if values is not None:
                # The person's part is the values, and a person's own order it wraps. An automated
                # repair is no person's order: its reviewer is told the values alone, never the
                # previous finding, which no bound holds to one read.
                ordered = values if order is not None else closing_order(self.state, None)
                return values.instruction, ordered
        return told, order

    def _told(self, subtask_id: str, attempt: int) -> tuple[str | None, PersonOrder | None]:
        """What ``attempt`` would start from with no chosen value waiting, and the order behind."""
        sub = self.state.subtasks[subtask_id]
        previous = sub.attempts[-2] if attempt > 1 and len(sub.attempts) > 1 else None
        if previous is None:
            return None, None
        followed = sub.followed_up
        if previous.merged is not None and followed is not None and followed.attempt == attempt:
            told = self._follow_up_order(followed)  # the follow-up's one attempt
            return told.instruction, told
        reopened = sub.reopened
        if (
            previous.merged is not None
            and reopened is not None
            and reopened.item_id is not None
            and reopened.attempt == attempt
        ):
            # The reopened attempt alone: a later one follows the repair rules.
            note = self.state.taken[reopened.item_id].note
            conform = conform_order(self.state, reopened.item_id, subtask_id, previous.number, note)
            return conform.instruction, conform
        before = previous.rejected
        ordered = previous.person_rejected
        if ordered is not None and ordered.effect in ("fix", "retry"):
            if ordered.note is None and ordered.verb != "choose":
                msg = "a session a person ordered is ordered with the person's note"
                raise RunStateError(msg, subtask=subtask_id, attempt=str(attempt))
            try:
                order = person_order(
                    self.state,
                    previous,
                    effect=ordered.effect,
                    item_id=ordered.item_id,
                    note=ordered.note,
                )
            except ValueError as exc:
                raise RunStateError(str(exc), subtask=subtask_id, attempt=str(attempt)) from None
            if order is not None:
                return order.instruction, order
        # A level-2 finding is rebuilt from its rulings, never taken as written: a session reads it.
        sized = before is not None and before.finding.source == "arbitration"
        if sized and before is not None and before.finding != self._sized_finding(previous):
            msg = "the run-event log does not replay as a run"
            why = "a rejection whose finding is not the one its rulings give"
            raise CorruptEventLogError(msg, seq=str(before.seq), reason=why)
        return (repair_instruction(previous.number, before.finding) if before else None), None

    def _screened(self, subtask_id: str, order: PersonOrder) -> str:
        """What a person's order is held to the canaries by, before its session is spawned.

        A fix's whole instruction, the quoted verdict with the note; a retry's note, the one text
        in it no check before it saw (ARCH-133). The reviewer's finding a retry also quotes is
        what every automated repair quotes, and is held to nothing more here than there. An order
        given by choosing sizing's value is held whole: the graph's values it quotes and the note.
        """
        if order.kind == "arbitration_value":
            return arbitration_value_instruction(order.chosen, None)
        if order.kind in (
            "fix_after_block",
            "retry_after_arbitration",
            "fix_after_arbitration",
            "contract_conform",
            "follow_up",
        ):
            return order.instruction
        attempts = self.state.subtasks[subtask_id].attempts
        spent = next((a.person_rejected for a in attempts if a.number == order.of_attempt), None)
        if spent is None or spent.note is None:
            msg = "a retry a person ordered has no note on the record"
            raise RunStateError(msg, subtask=subtask_id, item=order.item_id or "")
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
        # Integration's state quotes the contract results and the system-scope result on the
        # record: each is taken again first, so one the stores do not give halts the run before
        # its window opens.
        if subtask_id == self.state.completion_subtask and not (
            self._record_holds() and (attempt > 1 or self._no_declaration_at_head(subtask_id))
        ):
            return False
        self._environment_before_a_spawn()
        sub = self.state.subtasks[subtask_id]
        self._stage(subtask_id, attempt, "resolve")
        reopened = sub.reopened
        if (
            reopened is not None
            and reopened.item_id is not None
            and reopened.attempt == attempt
            and not self._rulings_hold(self.state.contract_items[reopened.item_id])
        ):
            return False  # the rulings its order quotes are the journal's, or the run halts
        before = sub.attempts[-2] if attempt > 1 and len(sub.attempts) > 1 else None
        if before is not None and before.rejected is not None:
            # A ruling is used again here, in the finding the session is told: held first.
            sized = before.rejected.finding.source == "arbitration"
            if sized and not self._held_holds(subtask_id, before):
                return False
        if before is not None and before.queued and not self._held_holds(subtask_id, before):
            # So are the rulings a person's choice of sizing's value quotes to this session.
            return False
        instruction, order = self._instruction(subtask_id, attempt)
        inner = self._told(subtask_id, attempt)[1]
        for screened in dict.fromkeys(o for o in (order, inner) if o is not None):
            if not self._material_clean(subtask_id, self._screened(subtask_id, screened)):
                return False
        whole, record = self._parts_record_holds(subtask_id)
        if not whole:
            return False
        held: IssuedState | None = None
        if subtask_id == self.state.completion_subtask:
            # Integration's session reads the record's state: built from the log and recorded by
            # its digest before the spawn. The dispatcher holds the file it writes to that digest.
            data = issued_state(self.state)
            held = IssuedState(
                text=data.decode("utf-8"), sha256=hashlib.sha256(data).hexdigest(), length=len(data)
            )
            self._emit(
                IntegrationStateIssued(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    sha256=held.sha256,
                    length=held.length,
                )
            )
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
        if self._acts() or any(self.state.undecided(i) for i in self.state.contract_items):
            # The decisions file as this session starts: no later decision is taken unless
            # these bytes are still the file's first (ARCH-133). Whole lines only: a torn final
            # line is no decision, and the writer may lawfully cut it. A run that records only
            # takes decisions on contract items, which close them: it seals while one is open.
            # A session spawned before the first item, or once every item is decided, runs
            # unsealed. That is safe only because the queue's reader refuses a decision on an item
            # not listed or already decided, at every read: a line such a session plants can then
            # never close an item a person has not, and loosening that rule reopens the gap.
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
            kind="fix"
            if inner is not None
            and (
                inner.kind in ("fix_after_block", "fix_after_arbitration")
                or (inner.kind == "contract_conform" and sub.attempts[-1].fix)
            )
            else "attempt",
            issued_state=held,
            parts_record=record,
            disputes=disputer_problem(sub.plan.assigned_role) is None
            and any(
                s.plan.assigned_role in owners_of("cross_nodes")
                for s in self.state.subtasks.values()
            ),
            reopened=sub.reopens,
            interfaces=self._shared_interfaces(sub.plan.assigned_role),
        )
        try:
            report = self._dispatcher.run(request, on_spawn=self._spawned)
        except WorktreeMisplacedError as exc:
            # No session was started: the run is where sandboxed sessions abort each
            # other's commands, and a person moves it.
            self._incident(subtask_id, "os_layer_misplaced", str(exc))
            return False
        found = self._session_findings(report)
        ruled = self._by_the_rule(subtask_id, report, found)
        if ruled is not None:
            # The owner's rule: a change that only adds restrictions is no incident. Recorded
            # before the session's end line, and every later session is held to the new limits.
            self._emit(ruled)
            found = None
        if found is not None:
            # Before anything says the session ended: a process killed after this line owes the
            # halt, and one killed before it finds the session again (``stop_leftovers``).
            self._findings(subtask_id, *found, first=True)
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
                observed_traffic=report.observed_traffic,
                flag_cache=report.flag_cache,
                policy_limits_unjudged=_unjudged(report),
                issued_spec_sha256=report.issued_spec_sha256,
                series=report.series,
            )
        )
        if found is not None:
            self._findings(subtask_id, *found, first=False)
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
        changed = (
            policy_limits_change(self._policy_baseline(), report.policy_limits_sha256)
            if _unjudged(report) is None
            else None
        )
        if changed is not None:
            # The account's policy limits are applied without a trace the hooks see: the
            # session ran under other limits than the run began with.
            return "managed_settings_changed", changed
        changed = traffic_change(self._traffic_baseline(), report.observed_traffic)
        if changed is not None:
            # On a pin whose sessions fetch the flags and may be served a catalog, the run is
            # held to what it first saw: this session ran under other conditions.
            return "managed_settings_changed", changed
        return None

    def _session_findings(
        self, report: SessionReport
    ) -> tuple[list[tuple[IncidentCause, str]], IncidentCause] | None:
        """Every incident a session's end shows, in the order written, and the halt's cause.

        An exposure first, so no other incident can leave it unlogged; then any other incident,
        which names the halt; then the possible abort beside it, and the unverified reaping.
        ``bwrap:`` in a result is the session's own output, which any command can print: no
        harness-side signal tells a real abort from a printed one, so it is recorded alongside,
        never in place of, anything else the end shows. ``None`` when it shows none.
        """
        found: list[tuple[IncidentCause, str]] = []
        if report.held_out_seen is not None:
            # The session displayed held-out material: the tier counts as exposed (ARCH-141).
            # The canary is not recorded.
            found.append(("held_out_read", f"held-out material in the stream of session "
                          f"{report.session_id}"))  # fmt: skip
        other = self._other_incident(report)
        if other is not None:
            found.append(other)
        if report.os_layer_aborted:
            found.append(
                ("os_layer_aborted", _possible_abort(report.session_id, report.os_layer_aborted))
            )
        if report.reaper_unverified:
            # A command's output was cut where its survivor reaper's last word stands: what it
            # started may have lived on. Its work is not taken, and a person looks first.
            found.append(
                (
                    "reaper_unverified",
                    _unverified_reaping(report.session_id, report.reaper_unverified),
                )
            )
        if not found:
            return None
        # The halt: the other incident's cause, else the exposure's, else the first found.
        halt = other[0] if other is not None else found[0][0]
        return found, halt

    def _findings(
        self,
        subtask_id: str | None,
        found: list[tuple[IncidentCause, str]],
        halt: IncidentCause,
        *,
        first: bool,
    ) -> None:
        """A site's findings: with ``first`` the line that records them, else the rest and the halt.

        Two or more are recorded in one line first, which a process taking over after a kill
        writes the rest from: each incident, then the one halt. One is its own incident first;
        its halt is its own cause, which the record then owes.
        """
        if first:
            listed = tuple(SessionFinding(cause=cause, detail=detail) for cause, detail in found)
            self._emit(
                FindingsRecorded(**self._env(), subtask_id=subtask_id, findings=listed, halt=halt)
                if len(found) > 1
                else Incident(
                    **self._env(), subtask_id=subtask_id, cause=found[0][0], detail=found[0][1]
                )
            )
            return
        for cause, detail in found if len(found) > 1 else ():
            self._emit(Incident(**self._env(), subtask_id=subtask_id, cause=cause, detail=detail))
        self._halt_for(subtask_id, halt)

    def _owed_halt(self) -> None:
        """The halt the record owes, after the incidents a findings line names and none follows.

        A process killed between a site's incidents, or between them and the halt.
        """
        listed = self.state.findings
        if listed is not None:
            for found in listed.findings[self.state.findings_written :]:
                self._emit(
                    Incident(
                        **self._env(),
                        subtask_id=listed.subtask_id,
                        cause=found.cause,
                        detail=found.detail,
                    )
                )
            self._halt_for(listed.subtask_id, listed.halt)
            return
        owed = self.state.owed_halt()
        if owed is not None:
            self._halt_for(owed.subtask_id, owed.cause)

    def _parts_record_holds(self, subtask_id: str) -> tuple[bool, IssuedState | None]:
        """The parts record a session reads, built again and held to the line that released it.

        ``(True, None)`` for a run that issues none: it did not ask, or its plan names no part.
        ``(True, record)`` where the record the plan and the released decisions give now is the
        one the release line named, by its digest and length. ``(False, None)`` after an incident
        where it is not: a line the record was built from, or the code that builds it, has
        changed since the run was released, and nothing is handed to a session or a reviewer.
        """
        released = self.state.parts_released
        components = self.state.components or ()
        if released is None or not components:
            return True, None
        taken = []
        for named in released.components:
            decided = self.state.taken[named.item_id]
            body = (
                None if named.parts is None else PartsBody.model_validate(named.parts.model_dump())
            )
            taken.append(
                TakenPart(
                    item_id=named.item_id,
                    choice=named.choice,
                    body=body,
                    operator=decided.resolved_by,
                    decided_ts=decided.decided_ts,
                )
            )
        data = parts_record(components, taken)
        if (hashlib.sha256(data).hexdigest(), len(data)) != (
            released.record_sha256,
            released.record_length,
        ):
            detail = (
                f"the parts record the release at line {released.seq} named is not what the "
                "run's record gives now"
            )
            self._incident(subtask_id, "parts_record_mismatch", detail)
            return False, None
        return True, IssuedState(
            text=data.decode("utf-8"), sha256=released.record_sha256, length=released.record_length
        )

    def _state_holds(self, subtask_id: str) -> IssuedState | None:
        """Integration's issued state, built again from the record and held to its window's line.

        Replay holds the line to its place and form, never to the bytes, so a recorded log stays
        readable whatever the document's wording becomes. Before the review the bytes are held
        here: a record that no longer gives what was issued halts the run, and nothing is handed
        to the reviewer. Within one process this compares the record as this process read it, so
        it catches a rewrite of the log (a line the state was built from, or the state's own line)
        only across a takeover: a process that replayed the file after the state was issued. The
        file the session reads is held by the dispatcher, which reads it back before the session
        is installed and holds it to the line's digest and length.
        """
        line = self.state.subtasks[subtask_id].attempts[-1].issued
        data = issued_state(self.state)
        if line is None or (hashlib.sha256(data).hexdigest(), len(data)) != (
            line.sha256,
            line.length,
        ):
            where = f"at line {line.seq}" if line is not None else "in this window"
            detail = (
                f"integration's issued state recorded {where} is not what the run's record gives "
                "now"
            )
            self._incident(subtask_id, "issued_state_mismatch", detail)
            return None
        return IssuedState(text=data.decode("utf-8"), sha256=line.sha256, length=line.length)

    def _spec_commit(self) -> str | None:
        """The commit that issued every subtask's specification: the decomposition's."""
        return next((e.spec_commit for e in self.log.events if isinstance(e, Decomposed)), None)

    def _shared_interfaces(self, role: str) -> tuple[str, ...]:
        """The interfaces the recorded contract pairs hold ``role`` to, either side, in id order.

        By role, as a clause reads a module's nodes: so a closing pass, which no pair names by
        its subtask, is told the interfaces its role produces, as the opening pass is.
        """
        return tuple(
            sorted(
                {
                    interface
                    for pair in self.state.contract_pairs or ()
                    if role in (pair.producer.role, pair.consumer.role)
                    for interface in pair.interfaces
                }
            )
        )

    def _policy_baseline(self) -> str | None:
        """The policy limits every session is held to: the decomposition call's, as resolved since.

        Moved only by a resolution on the record (:class:`IncidentResolved`), as the replay does.
        """
        return self.state.policy_baseline

    def _by_the_rule(
        self, subtask_id: str, report: SessionReport, found: object
    ) -> IncidentResolved | None:
        """The owner's rule's resolution of the session's change of policy limits, if it applies.

        Only where that change is all the session's end shows (``found`` is its lone finding),
        both limits are files held to their digests, and the change only adds restrictions set to
        ``allowed: false``. Any other change is the incident it was, for a person to resolve.
        """
        baseline, now = self._policy_baseline(), report.policy_limits_sha256
        changed = policy_limits_change(baseline, now) if _unjudged(report) is None else None
        lone = ([("managed_settings_changed", changed)], "managed_settings_changed")
        if changed is None or baseline is None or now is None or found != lone:
            return None
        before = limits_with(self.run_dir, baseline)
        after = read_limits(session_limits(self.run_dir, report.session_id), now)
        if before is None or after is None:
            return None
        try:
            changes, omitted = policy_diff(before, after)
        except UnshowableKeyError:
            return None
        if not stricter_only(changes, omitted):
            return None
        return IncidentResolved(
            **self._env(),
            subtask_id=subtask_id,
            session_id=report.session_id,
            by=RULE,
            reason=RULE_REASON,
            rule=True,
            old_sha256=baseline,
            new_sha256=now,
            changes=changes,
            omitted=omitted,
        )

    def _traffic_baseline(self) -> ObservedTraffic | None:
        """The catalog and flags the run first saw: the decomposition call's, else a session's.

        A run given its plan directly has no decomposition call, so its first session that
        read a log, a role session's or a review's, sets what every later session is held to.
        """
        for event in self.log.events:
            if isinstance(event, Decomposed) and event.observed_traffic is not None:
                return event.observed_traffic
        for event in self.log.events:
            if isinstance(event, SessionEnded):
                seen: tuple[ObservedTraffic | None, ...] = (event.observed_traffic,)
            elif isinstance(event, ReviewRan):
                seen = tuple(m.observed_traffic for m in event.result.managed)
            elif isinstance(event, ReviewUnavailable):
                seen = tuple(m.observed_traffic for m in event.managed)
            else:
                continue
            first = next((s for s in seen if s is not None), None)
            if first is not None:
                return first
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

    def _recordable(self, subtask_id: str, attempt: int, check: ChangeCheck) -> ChangeCheck:
        """``check``, or the dispute's refusal if a dispute it read cannot be a line of the record.

        Tried before the check's own line: a session's file never stops the loop, and a line that
        could not be built or written would fail the same way on every resume.
        """
        for found in check.disputes:
            try:
                DisputeRecorded(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    position=found.position,
                    reason=found.reason,
                ).model_dump_json()
            except ValueError:
                path = f"{DISPUTES_DIR}/{found.position.node_id}.{found.position.name}.json"
                why = {"reason": f"{path}: {UNRECORDABLE}", "subject": path, "disputes": ()}
                return check.model_copy(update={"refused_by": "dispute", **why})
        return check

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
            owed = self.state.parts_pending
            if now is None and owed is not None and self._own_parts_line(line, owed):
                self._emit(PartsWriteDone(**self._env(), node_id=line.node_id, revision=line.rev))
                continue
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
        return self._declared_hold(subtask_id)

    def _declared_hold(self, subtask_id: str | None) -> bool:
        """Every declared quantity at the journal's head is one a landed parts write wrote.

        Only the parts writer declares, and the record names each write that landed with the
        digest of its whole payload. A declared quantity the landed writes do not account for,
        or a landed line the journal no longer holds as it landed, reached the journal past the
        store's guard: an integrity fault, an incident and a halt, never a repair. Taken after an
        attempt's journal step, after the parts writes, and whenever the journal is accounted for,
        so a process killed between a landed write and this check makes it when it next starts.
        Nothing is recorded when it holds.
        """
        try:
            lines = self._graph.records_after(0)
        except DesignStateError as exc:
            self._incident(subtask_id, "foreign_journal_line", str(exc))
            return False
        problem = unlanded_declared(lines, self.state.parts_landed)
        if problem is None:
            return True
        self._incident(subtask_id, "foreign_journal_line", problem)
        return False

    @staticmethod
    def _own_parts_line(line: JournalLine, owed: PartsWriteIntended) -> bool:
        """Whether a journal line is the parts write the run intended and did not see land."""
        return (
            line.rev == owed.expected_revision
            and line.node_id == owed.node_id
            and payload_digest(line.payload) == owed.payload_sha256
        )

    def _release_parts(self) -> None:
        """Write what the decisions owe, each node behind an intent, then release the run.

        The values are read from the decisions file, held to the digest each decision's line
        names, and written through the store's ``declare`` only. A process killed between an
        intent and its write finds the pending intent on the record, accounts for the journal
        line if it landed (:meth:`_journal_clean`), and otherwise intends the same write again.
        The release names every component with what it stated, and the record a role reads.
        """
        state = self.state
        components = state.components or ()
        try:
            resolutions = {d.item_id: d for _, d in read_queue(self.run_dir).decisions}
        except QueueError as exc:
            if not self._decisions_unreadable(exc):
                raise
            return
        taken: list[TakenPart] = []
        for item_id in state.parts_ids:
            decided = state.taken[item_id]
            said = resolutions.get(item_id)
            body = None if said is None or decided.position == "find" else said.parts
            digest = None if body is None else parts_sha256(body)
            if digest != decided.parts_sha256:
                detail = f"item {item_id}: the decisions file no longer states what was taken"
                self._incident(None, "queue_item_mismatch", detail)
                return
            taken.append(
                TakenPart(
                    item_id=item_id,
                    choice=decided.position,  # type: ignore[arg-type]  # have, make or find
                    body=body,
                    operator=decided.resolved_by,
                    decided_ts=decided.decided_ts,
                )
            )
        owners = owners_of("cross_nodes")
        owed = parts_writes(
            components,
            state.parts_ids,
            {part.item_id: part for part in taken},
            owners[0] if len(owners) == 1 else None,
        )
        landed = {node for node, _, _ in state.parts_landed}
        for write in owed:
            if write.node_id in landed:
                continue
            expected = state.journal_head + 1
            self._emit(
                PartsWriteIntended(
                    **self._env(),
                    node_id=write.node_id,
                    item_id=write.item_id,
                    parts=StatedPart.model_validate(write.body.model_dump()),
                    actor_role=write.owner_role,
                    payload_sha256=write.payload_sha256,
                    expected_revision=expected,
                )
            )
            try:
                revision = self._graph.declare(write.payload, (write.item_id,))
            except StoreStaleError:
                if self._journal_clean():
                    detail = "the store handle went stale"
                    self._incident(None, "foreign_journal_line", detail)
                return
            except StoreRefusalError as exc:
                self._incident(None, "store_refusal", f"{exc} ({exc.context.get('reason')})")
                return
            if revision != expected:
                self._incident(None, "foreign_journal_line", f"revision {revision}, not {expected}")
                return
            self._emit(PartsWriteDone(**self._env(), node_id=write.node_id, revision=revision))
        if not self._declared_hold(None):
            return
        if owed:
            self._graph.commit("Parts the person declared\n")
        record = parts_record(components, taken)
        self._emit(
            PartsReleased(
                **self._env(),
                components=tuple(
                    ReleasedPart(
                        item_id=part.item_id,
                        node=component.node,
                        choice=part.choice,
                        parts=None
                        if part.body is None
                        else StatedPart.model_validate(part.body.model_dump()),
                    )
                    for component, part in zip(components, taken, strict=True)
                ),
                record_sha256=hashlib.sha256(record).hexdigest(),
                record_length=len(record),
            )
        )

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
        followed = now.changes.followed if now.changes is not None else ()
        if not self._apply_followed(subtask_id, attempt, role, followed):
            return False
        if not self._declared_hold(subtask_id):
            return False
        if proposals or followed:
            self._graph.commit(f"Nodes of subtask {subtask_id}, attempt {attempt}\n")
        return True

    def _apply_followed(
        self,
        subtask_id: str,
        attempt: int,
        role: str,
        followed: tuple[FollowedInterface, ...],
    ) -> bool:
        """Write each interface the change check followed, after the proposals, behind an intent.

        The record holds both ends: the change check's line was taken only as the derivation of
        what it records, and an intent only as that line's revision, after the joined nodes were
        written as the payloads it records (``RunState``'s rules, applied as each line is
        written). The store's own method holds the revision to the interface and the joined
        nodes as the journal has them, and refuses anything else.
        """
        now = self.state.subtasks[subtask_id].attempts[-1]
        for entry in followed:
            if entry.interface in now.applied:
                continue
            expected = self.state.journal_head + 1
            self._emit(
                WriteIntended(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    node_id=entry.interface,
                    payload_sha256=entry.payload_sha256,
                    actor_role=role,
                    expected_revision=expected,
                )
            )
            try:
                revision = self._graph.follow(entry.after, role, entry.joined)
            except StoreStaleError:
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
                    node_id=entry.interface,
                    revision=revision,
                )
            )
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
        # Only the cross-nodes owner's opening pass follows its interfaces.
        follows = self.state.follows(subtask_id) if role in owners_of("cross_nodes") else None
        check = self._recordable(
            subtask_id,
            attempt,
            self._changes.check(
                subtask_id, session.attempt_commit, role, series=session.series, follows=follows
            ),
        )
        self._emit(
            ProposalsChecked(
                **self._env(),
                subtask_id=subtask_id,
                attempt=attempt,
                checked_commit=session.attempt_commit,
                **check.model_dump(exclude={"declaration", "disputes"}),
            )
        )
        if check.refused_by is not None and check.reason is not None:
            finding = Finding(source=check.refused_by, text=check.reason, subject=check.subject)
            self._reject(subtask_id, attempt, finding)
            return False
        if check.declaration is not None:
            # The writer refuses the line unless the register names this role as the one owner of
            # completion, and a refusal there records nothing: the register is asked first, as
            # before a completion line, and the run halts with the cause on the record.
            why = completion_owner_problem(role)
            if why is not None:
                self._incident(subtask_id, "duty_breach", f"subtask {subtask_id}: {why}")
                return False
            self._emit(
                CompletionDeclared(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    modules=check.declaration.modules,
                    declaration_sha256=check.declaration.sha256,
                )
            )
        for dispute in check.disputes:
            self._emit(
                DisputeRecorded(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    position=dispute.position,
                    reason=dispute.reason,
                )
            )
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
            followed=check.followed,
        )
        self._stage(subtask_id, attempt, "gate")
        mode = self.config.gate_mode
        result: GateResult | None = None
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
        if not self._arbitrate(subtask_id, attempt, result):
            return False
        now = sub.attempts[-1]
        if result is not None and result.verdict == "fail" and mode == "on":
            self._reject(subtask_id, attempt, Finding.from_gate(result))
            return False
        if now.queued:
            return False  # a person rules on the dispute: the escalation decision comes next
        if self.state.sized(now):
            self._reject(subtask_id, attempt, self._sized_finding(now))
            return False
        # The reviewer reads the trajectory: it must still be what was sealed.
        if not self._trajectories_hold(subtask_id, [session]):
            return False
        if subtask_id == self.state.completion_subtask:
            # And the issued state its session read: still what the record gives.
            held = self._state_holds(subtask_id)
            if held is None:
                return False
            artefact = artefact.model_copy(update={"integration_state": held})
        whole, record = self._parts_record_holds(subtask_id)
        if not whole:
            return False
        if record is not None:
            artefact = artefact.model_copy(update={"parts_record": record})
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

    def _arbitrate(self, subtask_id: str, attempt: int, gate: GateResult | None) -> bool:
        """Rule each dispute of the attempt by the precedence table, one line each (ARCH-040).

        Sizing's position is the node's last journal line at or before the recorded head, the
        standing is built as the replay builds it, and the table gives the level. A journal that
        holds no such quantity is not the one the record describes: the run halts, and False.
        """
        sub = self.state.subtasks[subtask_id]
        now = sub.attempts[-1]
        earlier = [(ln.conflict, ln.level) for a in sub.attempts[:-1] for ln in a.arbitrations]
        for dispute in list(now.disputes):
            node, name = dispute.position.node_id, dispute.position.name
            held = self._held_at(subtask_id, node, name, self.state.journal_head)
            if held is None:
                return False
            conflict = DisputeConflict(node_id=node, quantity=name)
            standing = dispute_standing(
                conflict,
                gate=gate,
                earlier=earlier,
                attempt=attempt,
                fix=now.fix,
                chosen=self.state.chosen_holds(subtask_id, dispute.position, held),
            )
            self._emit(
                ArbitrationDecided(
                    **self._env(),
                    subtask_id=subtask_id,
                    attempt=attempt,
                    conflict=conflict,
                    standing=standing,
                    level=cast("Level", arbitrate(conflict, standing).level),
                    held=held,
                )
            )
        return True

    def _held_at(self, subtask_id: str | None, node: str, name: str, head: int) -> Held | None:
        """Quantity ``name`` of ``node`` as journal revision ``head`` left it; ``None`` if halted.

        The journal is read as ``nodes_at`` reads it, through the graph port and with the revision
        of the node's line. A journal that cannot be read, that ends before ``head``, or that lacks
        the quantity halts. (``nodes_at`` itself is left as it is: its bytes are part of the
        contract definition every contract result carries.)
        """
        try:
            lines = [ln for ln in self._graph.records_after(0) if ln.rev <= head]
            if not lines or lines[-1].rev != head:
                msg = "the canonical journal ends before the revision the run records"
                raise StoreStaleError(msg, revision=str(head))
            line = {ln.node_id: ln for ln in lines}.get(node)
            found = validate_node(line.payload).quantities.get(name) if line is not None else None
            if line is not None and found is not None:
                position = QuantityRef(node_id=node, name=name, value=found.value, unit=found.unit)
                by = {"source": found.source, "written_by": found.written_by}
                return Held(position=position, revision=line.rev, **by)
            detail = f"the journal holds no {name} of {node} at revision {head}"
        except (DesignStateError, ValueError) as exc:
            detail = f"{node} at journal revision {head}: {exc}"
        self._incident(subtask_id, "foreign_journal_line", detail)
        return None

    def _held_holds(self, subtask_id: str, now: AttemptState | None = None) -> bool:
        """Each ruling's held value is what the journal gives at its ruling's head; False if halted.

        So a line of its node between the held revision and that head, which the loop could not
        have ruled on, halts too. The rulings are ``now``'s, by default the last attempt's.
        """
        now = now or self.state.subtasks[subtask_id].attempts[-1]
        for ruling, head in zip(now.arbitrations, now.ruled_at, strict=True):
            held = ruling.held
            again = self._held_at(None, held.position.node_id, held.position.name, head)
            if again is None:
                return False
            if again != held:
                detail = (
                    f"subtask {subtask_id}: journal revision {head} does not hold the value its "
                    "ruling holds"
                )
                self._incident(None, "foreign_journal_line", detail)
                return False
        return True

    def _sized_finding(self, now: AttemptState) -> Finding:
        """The level-2 finding, built from the attempt's rulings and the writes on the record."""
        sized = [
            (ln.held, self.state.writer_of(ln.held))
            for ln in now.arbitrations
            if ln.level == "sizing"
        ]
        return Finding.from_arbitration(sized)

    def _arbitration_sessions(self, subtask_id: str) -> list[SessionEnded]:
        """The domain's sessions, then each sizing session whose write put a held revision."""
        sub = self.state.subtasks[subtask_id]
        sessions = [a.session for a in sub.attempts if a.session is not None]
        for ruling in sub.attempts[-1].arbitrations:
            done = self.state.write_of(ruling.held)
            if done is None:
                continue
            wrote = self.state.subtasks[done.subtask_id].attempts
            session = next((a.session for a in wrote if a.number == done.attempt), None)
            if session is not None and session not in sessions:
                sessions.append(session)
        return sessions

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
            if changes.followed:
                # The merge commit rewrites each followed interface's contract file, so every
                # later session reads the revised values.
                contracts = contracts_of([Node.model_validate(e.after) for e in changes.followed])
                merge_commit = self._merger.merge(
                    subtask_id, attempt, checked, merge_text, reopen=sub.reopens,
                    contracts=contracts,
                )  # fmt: skip
            else:
                merge_commit = self._merger.merge(
                    subtask_id, attempt, checked, merge_text, reopen=sub.reopens
                )
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
                review = reviewer.review(artefact)
            except HeldOutExposedError as exc:
                # The review session showed held-out material: the tier counts as exposed
                # (ARCH-141). The exposure is recorded first, then what it spent, then one halt;
                # no verdict is taken and nothing is retried. The canary is not recorded. A
                # process killed before the exposure's line finds the review again at the resume
                # (its tokens are the loop's word that the review is back, so none come first).
                detail = f"held-out material in the stream of review session {exc.session_id}"
                self._emit(
                    Incident(
                        **self._env(), subtask_id=subtask_id, cause="held_out_read", detail=detail
                    )
                )
                for message in exc.usage:
                    self._emit(
                        TokensUsed(
                            **self._env(),
                            attribution=f"reviewer:{exc.session_id}",
                            message_id=message.message_id,
                            usage=message.usage,
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
                if self._review_held(subtask_id, exc.session_id, exc.managed):
                    return None  # it ran under other conditions: neither recorded nor retried
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
                        managed=exc.managed,
                    )
                )
                if not retry:
                    return None
                retried = True
                continue
            if self._review_held(subtask_id, review.session_id, review.managed, review):
                return None
            return review

    def _review_held(
        self,
        subtask_id: str,
        session_id: str | None,
        managed: tuple[SessionManaged, ...],
        review: ReviewResult | None = None,
    ) -> bool:
        """Whether a review ran under other conditions than its run began with; then it halts.

        Each invocation of the review's session is held as a role session is: no managed
        settings delivered or changed, the decomposition call's policy limits, and the run's
        first catalog and flags. On a pin whose sessions carry that traffic, an invocation
        whose catalog and flags went unread (its stop was not confirmed) is held too. What a
        held review with a verdict spent is recorded here, as its verdict is not taken.
        """
        changed = self._review_change(managed)
        if changed is None:
            return False
        if review is not None:
            for message in review.usage:
                self._emit(
                    TokensUsed(
                        **self._env(),
                        attribution=f"reviewer:{review.session_id}",
                        message_id=message.message_id,
                        usage=message.usage,
                    )
                )
        detail = f"review session {session_id or 'none'} {changed}"
        self._emit(
            Incident(
                **self._env(),
                subtask_id=subtask_id,
                cause="managed_settings_changed",
                detail=detail,
            )
        )
        self._halt_for(subtask_id, "managed_settings_changed")
        return True

    def _review_change(self, managed: tuple[SessionManaged, ...]) -> str | None:
        """How a review's invocations differ from what its run began with, or ``None``."""
        held = self.config.claude_version in TRAFFIC_ALLOWED_VERSIONS
        for n, seen in enumerate(managed, start=1):
            changed = (
                seen.managed_drift
                or policy_limits_change(self._policy_baseline(), seen.policy_limits_sha256)
                or (
                    "had its catalog and flags not read: its stop was not confirmed"
                    if held and seen.observed_traffic is None
                    else traffic_change(self._traffic_baseline(), seen.observed_traffic)
                )
            )
            if changed is not None:
                return f"(invocation {n}): {changed}"
        return None

    def _scopes(self, subtask_id: str) -> tuple[AttemptScope, ...]:
        """Subtask scope always; module scope when this completes its module, or is sizing's.

        A module is complete when the last planned subtask for its directory is
        judged; a subtask taken out of the plan does not count. Every subtask of the
        cross-nodes owner is also judged at module scope (ARCH-080): the domains
        read sizing's nodes as they stand after its opening pass, so the relations those
        nodes form are judged there. A domain's subtask keeps module scope only when it
        completes its module, since a half-written module would fail its mass sum falsely.
        """
        plan = self.state.subtasks[subtask_id].plan
        if plan.assigned_role in owners_of("cross_nodes"):
            return ("subtask", "module")
        module_dir = plan.module_dir
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
        if self.state.plan_ends():
            # A person rejected the plan: its rejection, then the call skipped, and nothing else.
            decided = self.state.plan_decision()
            if self.state.plan_rejected is None and decided is not None:
                self._emit(PlanRejected(**self._env(), item_id=decided.item_id))
            planned = self.state.planned()
            self._emit(
                IntegrationGateSkipped(**self._env(), reason="plan_rejected", subtasks=planned)
            )
            return
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
            if not self._follow_ups(write=True):
                return
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
                    follow_ups=self._follow_ups_told(),
                )
            )
        self._emit(IntegrationEscalated(**self._env(), item_id=item_id))

    def _contract(self) -> None:
        """Hold the pair the record owes a result to the clause, and record it (ARCH-051).

        The graph is read at the journal revision the log records. The result blocks nothing: the
        merge that owed it stands, and a failed contract withholds completion alone. An interface
        node the pair cannot be held to, or a journal that ends before the recorded revision, halts
        the run, and no result is recorded.
        """
        if self.state.owed_ruling() is not None:
            self._rule_contract()
            return
        if self.state.owed_item() is not None:
            self._raise_contract_item()
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

    def _rule_contract(self) -> None:
        """Rule the failed clause the record owes next by the precedence table (ARCH-040).

        Both positions are read from the canonical journal at the result's revision: the
        interface's value and each failing node's that carries the quantity, with the revision of
        its line. A journal that does not give them halts the run, and nothing is ruled.
        """
        clause, tested = self.state.owed_ruling(), self.state.failed_result()
        if clause is None or tested is None:
            msg = "a contract ruling with none owed"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        values = self._clause_values(tested, clause.conflict, clause.carrying)
        if values is None:
            return
        wanted, found = values
        standing = self.state.contract_standing_of(tested, clause)
        self._emit(
            ContractRuled(
                **self._env(),
                conflict=clause.conflict,
                standing=standing,
                level=cast("Level", arbitrate(clause.conflict, standing).level),
                wanted=wanted,
                found=found,
            )
        )

    def _clause_values(
        self, tested: ContractTested, conflict: ContractConflict, nodes: tuple[str, ...]
    ) -> tuple[ContractValue | None, tuple[ContractValue, ...]] | None:
        """The clause's quantity on the interface and on ``nodes`` at the result; None if halted."""
        name = conflict.quantity
        if name is None:
            return None, ()
        read: list[ContractValue] = []
        for node in (conflict.interface, *nodes):
            held = self._held_at(None, node, name, tested.revision)
            if held is None:
                return None
            read.append(ContractValue(position=held.position, revision=held.revision))
        return read[0], tuple(read[1:])

    def _rulings_hold(self, tested: ContractTested) -> bool:
        """Each ruling of ``tested`` holds what the journal gives at its revision; else halted.

        Replay holds a ruling's values to the revisions the log gives and to nothing more, so a
        value rewritten on the line would reach the item; it is read again here first.
        """
        for line in self.state.rulings_of(tested):
            nodes = tuple(value.position.node_id for value in line.found)
            again = self._clause_values(tested, line.conflict, nodes)
            if again is None:
                return False
            if again != (line.wanted, line.found):
                detail = (
                    f"the contract ruling recorded at line {line.seq} does not hold what the "
                    f"canonical journal gives at revision {tested.revision}"
                )
                self._incident(None, "foreign_journal_line", detail)
                return False
        return True

    def _raise_contract_item(self) -> None:
        """List the item a failed contract owes a person, once, then record it."""
        tested = self.state.owed_item()
        if tested is None:
            msg = "a contract item with none owed"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if not self._rulings_hold(tested):
            return
        item_id = self.state.next_contract_item(tested, self.config.run_id)
        if item_id not in {item.item_id for item in self.queue.items()}:
            self.queue.add(self._contract_item_for(tested, item_id, ts=self.log.events[-1].ts))
        self._emit(ContractItemRaised(**self._env(), item_id=item_id))

    def _contract_item_for(self, tested: ContractTested, item_id: str, *, ts: str) -> QueueItem:
        """The item a failed contract lists, from the record as it stood at the result.

        The one builder, so the item a decision is taken on is held to it whole. Its links are the
        sessions of every attempt merged in either module's directory before the result.
        """
        pair = tested.result.pair
        dirs = {
            self.state.subtasks[s.subtask_id].plan.module_dir
            for s in (pair.producer, pair.consumer)
        }
        trajectories = tuple(
            attempt.session.trajectory
            for subtask_id in self.state.order
            if self.state.subtasks[subtask_id].plan.module_dir in dirs
            for attempt in self.state.subtasks[subtask_id].attempts
            if attempt.merged is not None
            and attempt.merged.seq < tested.seq
            and attempt.session is not None
            and attempt.session.trajectory is not None
        )
        start = next((e.spec_commit for e in self.log.events if isinstance(e, Decomposed)), "")
        raised = len(self.state.items_of(pair))
        own = item_id in self.state.contract_items
        return contract_item(
            item_id=item_id,
            run_id=self.config.run_id,
            tested=tested,
            rulings=tuple(self.state.rulings_of(tested)),
            round_=raised if own else raised + 1,
            run_span=(start or tested.commit, tested.commit),
            trajectories=trajectories,
            ts=ts,
            consequence=contract_consequence(self.state, tested) if self._acts() else None,
            choices=contract_choices(self.state, tested) if self._acts() else None,
        )

    def _contract_item_holds(self, item: QueueItem) -> bool:
        """The contract item as listed is the one the record builds, its rulings the journal's."""
        tested = self.state.contract_items.get(item.item_id)
        if tested is None:
            self._incident(None, "queue_item_mismatch", f"the run raised no item {item.item_id}")
            return False
        if not self._rulings_hold(tested):
            return False
        if self._contract_item_for(tested, item.item_id, ts=item.ts) != item:
            detail = f"item {item.item_id} is not the item the run's record builds"
            self._incident(None, "queue_item_mismatch", detail)
            return False
        return True

    def _complete(self, step: Step) -> None:
        """Record the completion the record owes next (ARCH-051).

        Integration's attempt merged with its diff clean, its declaration names the module, and
        every precondition holds for it: the run state owes the line only then, in plan order.
        Before the line, the declaration, every recorded contract result and the system-scope result
        are taken again (:meth:`_record_holds`).
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
        if not self._record_holds(integration):
            return
        attempt = self.state.subtasks[integration].attempts[-1].number
        self._emit(
            ModuleCompleted(
                **self._env(), subtask_id=step.subtask_id, declared_by=integration, attempt=attempt
            )
        )

    def _record_holds(self, declaring: str | None = None) -> bool:
        """What a completion line, or integration's issued state, rests on is what the stores give.

        Taken again in this order, and the first that differs halts the run with nothing written:
        the merged attempt's declaration (before a completion line, ``declaring`` naming
        integration's subtask), every recorded contract result, and the system-scope result.
        """
        if declaring is not None and not self._declaration_holds(declaring):
            return False
        return self._results_hold() and self._follow_ups(write=False) and self._scope_holds()

    def _owed(
        self, events: Sequence[Event], *, every: bool = False
    ) -> Mapping[str, tuple[OwedEdge, ...]]:
        """What sizing's closing pass owed the domain modules on the record up to ``events``.

        Candidates are the domain modules that merged with an attempt left to reopen at: one
        that merged on its fix has none, and the propagation check judges its nodes as written.
        A module whose order its reviewer could not read whole is owed none either: the check
        judges its edges as they stand. With ``every``, each done domain module's edges, owed or
        not: what the integration item names.
        """
        state = replay(events)
        closing = state.closing_pass()
        if closing is None or state.subtasks[closing].status != "done":
            return {}
        directory = state.subtasks[closing].plan.module_dir
        candidates = {
            s
            for s in state.integrated()
            if (sub := state.subtasks[s]).status == "done"
            and sub.plan.module_dir != directory
            and (every or sub.attempts[-1].merged is not None)
            and (every or not any(a.fix for a in sub.attempts))
        }
        _, change_sets = change_history(events)
        head = max((r for c in change_sets for r in c.revisions), default=0)
        lines = [line for line in self._graph.records_after(0) if line.rev <= head]
        found = owed(lines, change_sets, closing, candidates)
        if every:
            return found
        return {
            s: edges
            for s, edges in found.items()
            if fits_one_read(
                person_order_text(
                    follow_up_order(
                        lines, change_sets, closing, edges, state.subtasks[s].attempts[-1].number
                    )
                )
            )
        }

    def _follow_ups_told(self) -> str | None:
        """Each module sizing's closing pass reached, its edges, and how its follow-up ended.

        From the record's structured fields alone: why it did not merge, the gate's failing
        check, the review's rejecting rubric items with their results, and its blocking criteria
        and items. Never the gate's, a reviewer's or a session's own words. ``None`` when no edge
        was reached, so the item keeps its words.
        """
        events = self.log.events
        taken = [e for e in events if isinstance(e, SubtaskReopened) and e.cause is not None]
        reached = self._owed(events[: taken[0].seq] if taken else events, every=True)
        if not reached:
            return None
        at = {e.subtask_id: e.attempt for e in taken}
        told = []
        for subtask_id, edges in reached.items():
            named = _listed([f"{render.held(e.source)} -> {render.held(e.target)}" for e in edges])
            sub = self.state.subtasks[subtask_id]
            now = next((a for a in sub.attempts if a.number == at.get(subtask_id)), None)
            who = render.held(
                subtask_id, SUBTASK_PATTERN, PLANNED_ID_MAX_LENGTH, render.REFUSED_SUBTASK
            )
            told.append(f"{who} (owed {named}): {_follow_up_end(now)}")
        return _account(told)

    def _follow_up_order(self, followed: SubtaskReopened) -> PersonOrder:
        """The follow-up's order, from the journal and the history where it was written."""
        _, change_sets = change_history(self.log.events[: followed.seq])
        closing = self.state.closing_pass() or ""
        lines = self._graph.records_after(0)
        edges = followed.owed or ()
        return follow_up_order(lines, change_sets, closing, edges, followed.attempt - 1)

    def _follow_ups(self, *, write: bool) -> bool:
        """The follow-ups on the record are what the journal owed where the first was written.

        With ``write``, the integration call's: the ones owed and not yet written are written, in
        plan order, each reopening its domain module at its next attempt, by code (ARCH-051), and
        whether the call may run now is returned. A process killed between two of them left a
        plan-order prefix, and the rest follows; once any of their attempts began, none does.
        Otherwise, whether what is recorded holds. A difference halts the run.
        """
        self._follow_ups_checked = True
        events = self.log.events
        taken = [e for e in events if isinstance(e, SubtaskReopened) and e.cause is not None]
        if not taken and not write:
            return True
        found = self._owed(events[: taken[0].seq] if taken else events)
        wanted = [(s, found[s]) for s in self.state.order if s in found]
        recorded = [(e.subtask_id, e.owed) for e in taken]
        subs = self.state.subtasks
        begun = any(subs[e.subtask_id].attempts[-1].number >= e.attempt for e in taken)
        if recorded != wanted[: len(recorded)] or ((begun or not write) and recorded != wanted):
            detail = "the follow-ups on the record are not what the journal owed where written"
            self._incident(None, "foreign_journal_line", detail)
            return False
        if begun or not write:
            return True
        for subtask_id, edges in wanted[len(recorded) :]:
            last = subs[subtask_id].attempts[-1]
            merge_commit = last.merged.merge_commit if last.merged is not None else ""
            self._before_a_reopen(subtask_id)
            self._emit(
                SubtaskReopened(
                    **self._env(),
                    subtask_id=subtask_id,
                    merge_commit=merge_commit,
                    attempt=last.number + 1,
                    cause="follow_up",
                    owed=edges,
                )
            )
        return not wanted

    def _no_declaration_at_head(self, declaring: str) -> bool:
        """The run head integration's window would start from holds no declaration; else halted.

        Only integration's own accepted attempt puts one on the run branch, and it is its last:
        one there before its window (in the run's start commit, say) is no attempt's of this run.
        Read before its first window: no line but integration's follows the integration call, so
        the run head does not move between its attempts, and a foreign move halts the run anyway.
        """
        head = self.state.run_head
        try:
            found = head is not None and self._changes.declaration_at(head, declaring) is not None
        except (DeclarationError, GitError):
            found = True
        if found:
            detail = (
                "a completion declaration was on the run branch before integration's window; no "
                "attempt of this run wrote it"
            )
            self._incident(None, "declaration_mismatch", detail)
        return not found

    def _declaration_holds(self, declaring: str) -> bool:
        """The merged attempt's declaration line is what its merged commit holds, read again.

        Replay holds the line to its place and its form, and its modules and its digest are fields
        of their own: a module list rewritten in place with the digest kept still replays. So the
        declaration is read again from the commit the attempt merged, with the change check's
        parser, and both are compared with the line. A difference, or a commit that no longer
        gives a declaration, halts the run, and no completion is written over it.
        """
        now = self.state.subtasks[declaring].attempts[-1]
        line, merged = now.declaration, now.merged
        try:
            again = (
                None
                if merged is None
                else self._changes.declaration_at(merged.merge_commit, declaring)
            )
        except (DeclarationError, GitError):
            again = None
        held = None if again is None else (again.modules, again.sha256)
        if line is not None and held == (line.modules, line.declaration_sha256):
            return True
        detail = (
            f"integration's declaration recorded at line {line.seq if line else 'none'} is not "
            "what the commit its attempt merged holds"
        )
        self._incident(None, "declaration_mismatch", detail)
        return False

    def _scope_holds(self) -> bool:
        """The system-scope result on the record is, whole, what the gate gives again at its place.

        The question is the call's own, read from the log up to the gate's line: the run head, and
        the change history over the canonical store, which the gate refuses unless the journal
        still ends where that history says. In this harness nothing writes the store after the
        call, so an honest run is asked the same question and gives the same answer; a rewritten
        line, a journal moved past the line's revision, or a gate that cannot answer halts the run.
        """
        ran = self.state.integration
        if not isinstance(ran, IntegrationGateRan):
            return True
        prefix = self.log.events[: ran.seq]
        head, mode = run_head_of(prefix), self.config.gate_mode
        again: GateResult | None = None
        if head is not None and mode != "off" and self._gate is not None:
            baseline, change_sets = change_history(prefix)
            artefact = IntegrationArtefact(
                run_id=self.config.run_id,
                graph_root=str(self._graph.root),
                run_head=head,
                baseline_revision=baseline,
                change_sets=change_sets,
            )
            try:
                again = self._gate.check_integration(artefact, mode=mode)
            except (GateError, DesignStateError):
                again = None
        if again == ran.result:
            return True
        detail = (
            f"the system-scope result recorded at line {ran.seq} is not what the gate gives again "
            "over the canonical store at its place"
        )
        self._incident(None, "foreign_journal_line", detail)
        return False

    def _results_hold(self) -> bool:
        """Every contract result on the record is, whole, what the journal gives at its revision.

        A completion reads each pair's latest result as the log holds it, and replay holds a
        result to its place, never to the graph. So before a completion line each recorded result
        is taken again over the canonical journal at the revision it records, as the contract step
        took it. One that differs, or that the journal can no longer give, is not what the store
        holds: the run halts, and no completion is written over it. Integration's issued state
        quotes the same results, so they are taken again before it is built, too.
        """
        for line in self.state.contracts:
            pair = line.result.pair
            try:
                again = check_pair(pair, nodes_at(self._graph.root, line.revision))
            except (DesignStateError, ContractError):
                again = None
            if again != line.result:
                detail = (
                    f"the contract result of {pair.producer.module} to {pair.consumer.module} "
                    f"recorded at line {line.seq} is not what the canonical journal gives at "
                    f"revision {line.revision}"
                )
                self._incident(None, "foreign_journal_line", detail)
                return False
        return True

    def _diff(self, subtask_id: str, attempt: int) -> None:
        # A person's approve is carried on from the record, never resumed: its attempt ended
        # without a merge, so no resume line takes the cursor back. A process killed after the
        # stage line and before the check leaves the stage entered, and the check is made under
        # it, so the stage is never entered twice and the check never left out.
        if self.state.subtasks[subtask_id].attempts[-1].cursor != "diff":
            self._stage(subtask_id, attempt, "diff")
        now = self.state.subtasks[subtask_id].attempts[-1]
        # A check on the record here named divergences, since a clean one makes the subtask done:
        # a process was killed before the incident it owed, which is written now, and nothing
        # twice. Killed after the incident, it owed the halt alone, the run's next step.
        checked = now.diff
        since = min(now.applied.values()) - 1 if now.applied else self.state.journal_head
        role = self.state.subtasks[subtask_id].plan.assigned_role
        followed = now.changes.followed if now.changes is not None else ()
        admitted = frozenset(
            now.applied[e.interface] for e in followed if e.interface in now.applied
        )
        found = (
            self._graph.divergences(since, role, admitted=admitted)
            if admitted
            else self._graph.divergences(since, role)
        )
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
            # A declared quantity touched past the store's guard is the journal's integrity, as
            # the head check names it, not a role's duty.
            foreign = any(d.reason == REJECT_CROSS_ROLE for d in found)
            declared = any(
                d.reason in (REJECT_DECLARED_FIXED, REJECT_DECLARED_FORGED) for d in found
            )
            cause: IncidentCause = (
                "cross_role_write"
                if foreign
                else "foreign_journal_line"
                if declared
                else "duty_breach"
            )
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
        if cause == "disk_full":
            # Never retried: the binary said a full disk lost the session's own records,
            # and the harness measured the volume as full. Nothing the session did is
            # taken, and a person looks before anything else runs.
            detail = (
                f"subtask {subtask_id} attempt {attempt}: the session's binary said a full "
                "disk lost the session's own records, and the volume holding them was "
                "measured full when it ended; free the space and look at the session "
                "before the run goes on"
            )
            self._emit(Halted(**self._env(), reason="disk_full", detail=detail))
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

    def _decomposition_holds(self) -> bool:
        """The held round's stream is still what its review sealed; else an incident."""
        review = self.state.design_review
        if review is None:
            self._incident(None, "trajectory_tampered", "the plan's review sealed no stream")
            return False
        held = round_stream(len(self.state.earlier_reviews) + 1)
        try:
            read_sealed(self.run_dir.joinpath(*stream_parts(held)), review.stream_seal)
        except TrajectoryTamperedError as exc:
            self._incident(None, "trajectory_tampered", f"{exc}: {exc.context}")
            return False
        return True

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
        now = self.state.subtasks[subtask_id].attempts[-1]
        session = now.session
        if session is None:
            msg = "a review sent to a person with no completed session behind it"
            raise RunStateError(msg, subtask=subtask_id)
        if now.queued and not self._held_holds(subtask_id):
            return
        linked = self._arbitration_sessions(subtask_id) if now.queued else [session]
        if not self._trajectories_hold(subtask_id, linked):
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
        if source == "arbitration" and now.changes is not None:
            positions = {(d.position.node_id, d.position.name): d.position for d in now.disputes}
            ruled = [ln for ln in now.arbitrations if ln.level != "gate"]
            linked = self._arbitration_sessions(subtask_id)
            return arbitration_item(
                item_id=item_id,
                run_id=self.config.run_id,
                subtask_id=subtask_id,
                attempt=now.number,
                fix=now.fix,
                rulings=tuple(
                    (
                        positions[(ln.conflict.node_id, ln.conflict.quantity)],
                        ln.held,
                        self.state.writer_of(ln.held),
                        ln.level,
                        ln.standing,
                    )
                    for ln in ruled
                ),
                artefact_diff=self._merger.artefact_diff(now.changes.checked_commit),
                trajectories=tuple(s.trajectory for s in linked if s.trajectory is not None),
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
            merged=sum(1 for a in attempts if a.merged is not None),
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
