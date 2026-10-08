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

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from physgate.orchestrator.apply import ProposalRefusedError
from physgate.orchestrator.budget import infra_retry_delay
from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.common import utc_now
from physgate.orchestrator.credentials import SECRET_VARIABLE
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    AttemptRejected,
    Decomposed,
    DiffChecked,
    Envelope,
    EnvironmentRecorded,
    Escalated,
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
    NodeFilesRepaired,
    ProposalsChecked,
    Resumed,
    ReviewRan,
    ReviewUnavailable,
    SessionEnded,
    Stage,
    StageEntered,
    TokensUsed,
    WorktreeRemoved,
    WriteDone,
    WriteIntended,
)
from physgate.orchestrator.exceptions import (
    GateNotRegisteredError,
    MergeConflictError,
    MergeRefusedError,
    ReviewerNotRegisteredError,
    ReviewUnavailableError,
    RunStateError,
    StoreRefusalError,
    TrajectoryTamperedError,
)
from physgate.orchestrator.managed import policy_limits_change
from physgate.orchestrator.merge import merge_message
from physgate.orchestrator.ports import (
    ChangeChecker,
    Dispatcher,
    GraphPort,
    Merger,
    SessionRequest,
)
from physgate.orchestrator.protocols import (
    Artefact,
    AttemptScope,
    Gate,
    IntegrationArtefact,
    IssuedSpec,
    Reviewer,
    ReviewResult,
    SpecDefect,
    require_mode,
    require_separate_models,
)
from physgate.orchestrator.queue import (
    INTEGRATION,
    escalation_item,
    integration_item,
    unavailable_item,
)
from physgate.orchestrator.record import PlanEntry, RunRecord
from physgate.orchestrator.repair import Finding, repair_instruction
from physgate.orchestrator.replay import (
    AttemptState,
    Step,
    recorded_implementer,
    require_mergeable,
)
from physgate.orchestrator.run_config import RunConfig
from physgate.orchestrator.trajectory import read_sealed
from physgate.state.exceptions import DesignStateError, StoreStaleError
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


def refuse_unregistered(
    config: RunConfig, gate: Gate | None, reviewers: Mapping[str, Reviewer]
) -> None:
    """Refuse a run that could not pass its gate or review stage as configured.

    Raises:
        GateNotRegisteredError: the gate mode is ``on`` or ``observe`` and no gate
            is registered. There is no pass-through gate to fall back on.
        ReviewerNotRegisteredError: a role has no reviewer, or its reviewer is not on
            the model string the run pinned for it.
    """
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
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Open the run in ``run_dir``, replaying whatever its log already holds.

        Raises:
            GateNotRegisteredError, ReviewerNotRegisteredError: see
                :func:`refuse_unregistered`.
            RunConfigError: the run directory holds another configuration, or a log
                with no configuration.
        """
        refuse_unregistered(config, gate, reviewers)
        self.config = config
        self.run_dir = Path(run_dir)
        self._gate = gate
        self._reviewers = reviewers
        self._dispatcher = dispatcher
        self._changes = changes
        self._merger = merger
        self._graph = graph
        self._sleep = sleep
        self._appends: tuple[str, ...] = ()
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
            RunStateError: a previous process left the run mid-attempt; resume it.
        """
        self._stop_leftovers()
        if self.state.halted is None and self.state.interrupted() is not None:
            msg = "the run was interrupted mid-attempt; resume it instead"
            raise RunStateError(msg, run_dir=str(self.run_dir))
        if self.state.halted is None and not self._journal_clean():
            return self.state.next_step()
        return self._drive()

    def resume(self) -> Step:
        """Take over a run a previous process left, then drive it.

        The interrupted attempt restarts at its checkpoint with a fresh session,
        never the binary's own resume, and keeps its attempt number. A run halted
        because its infrastructure retries ran out continues the same attempt with
        a fresh schedule.

        Raises:
            RunStateError: the run halted for an incident, which a person resolves.
        """
        self._stop_leftovers()
        halted = self.state.halted
        if halted is not None and halted.reason not in RESUMABLE_HALTS:
            msg = f"the run halted for {halted.reason}; a person resolves that before any resume"
            raise RunStateError(msg, run_dir=str(self.run_dir), detail=halted.detail)
        if not self._journal_clean():
            return self.state.next_step()
        sub = self.state.interrupted()
        now_changes = sub.attempts[-1].changes if sub is not None and sub.attempts else None
        pending = (
            now_changes.checked_commit
            if sub is not None and now_changes is not None and sub.attempts[-1].merged is None
            else None
        )
        if not self._run_branch_holds(sub.plan.subtask_id if sub else None, pending):
            return self.state.next_step()
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

    def _stop_leftovers(self) -> None:
        """Stop what a previous process left running, before anything reads or writes."""
        if not self.log.events:
            return
        tampered: list[tuple[str, str]] = []
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
        # The environment is recorded for a step that spawns a session; the
        # integration call and a finished run spawn none.
        if self.state.next_step().kind not in ("done", "halted", "escalated", "integrate"):
            facts = self._dispatcher.environment()
            if facts is not None:
                self._emit(EnvironmentRecorded(**self._env(), facts=facts))
        while True:
            step = self.state.next_step()
            if step.kind in ("done", "halted", "escalated"):
                self._clean_up_worktrees()
                return step
            if step.kind == "integrate":
                self._integrate()
                continue
            if step.subtask_id is None or step.attempt is None:
                msg = "a step with no subtask or attempt"
                raise RunStateError(msg, step=step.kind)
            if step.kind == "escalate":
                now = self.state.subtasks[step.subtask_id].attempts[-1]
                if now.unavailable_final is not None:
                    self._escalate_unavailable(step.subtask_id, now.unavailable_final)
                elif now.blocked is not None:
                    self._escalate_blocked(step.subtask_id, now.blocked)
                else:
                    self._escalate(step.subtask_id)
            elif step.kind == "infra_failed":
                self._infra_failed(step.subtask_id, step.attempt)
            else:
                self._attempt(step.subtask_id, step.attempt, step.point or "resolve")

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
        if point == "resolve" and not self._session(subtask_id, attempt):
            return
        if point in ("resolve", "verify_reading") and not self._judge(subtask_id, attempt):
            return
        self._diff(subtask_id, attempt)

    def _session(self, subtask_id: str, attempt: int) -> bool:
        sub = self.state.subtasks[subtask_id]
        self._stage(subtask_id, attempt, "resolve")
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
        before = sub.attempts[-2].rejected if attempt > 1 else None
        request = SessionRequest(
            subtask_id=subtask_id,
            attempt=attempt,
            assigned_role=sub.plan.assigned_role,
            spec_path=sub.plan.spec_path,
            module_dir=sub.plan.module_dir,
            model=self.config.models.roles[sub.plan.assigned_role],
            repair_instruction=repair_instruction(attempt - 1, before.finding) if before else None,
            bounds=self.config.bounds,
            spec_commit=self._spec_commit(),
        )
        report = self._dispatcher.run(request)
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
            )
        )
        if report.trajectory_tampered is not None:
            # Something other than the runtime wrote the stream after its result:
            # nothing the session did is taken, and a person looks first.
            self._incident(subtask_id, "trajectory_tampered", report.trajectory_tampered)
            return False
        if report.review_material_seen is not None:
            # The session read what only its reviewer reads, by a path no hook could
            # judge: its work is not taken, and a person looks first.
            # The canary itself is not written into the record a later session can read.
            detail = f"reviewer material in the stream of session {report.session_id}"
            self._incident(subtask_id, "review_material_read", detail)
            return False
        if report.managed_drift is not None:
            # Settings above every source the hooks were installed in changed under the
            # session: nothing it did is taken, and a person looks first.
            self._incident(subtask_id, "managed_settings_changed", report.managed_drift)
            return False
        changed = policy_limits_change(self._policy_baseline(), report.policy_limits_sha256)
        if changed is not None:
            # The account's policy limits are applied without a trace the hooks see: the
            # session ran under other limits than the run began with.
            self._incident(subtask_id, "managed_settings_changed", changed)
            return False
        if report.end.outcome != "completed":
            return False
        self._appends = report.hook_journal_appends
        if not self._journal_clean():
            return False
        return not report.node_files_halted or self._repair_node_files(subtask_id, attempt)

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
            proposals = self._graph.proposals(subtask_id, commit)
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
        check = self._changes.check(subtask_id, session.attempt_commit, role)
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
        line = require_mergeable(self.ledger.path, subtask_id, mode)
        changes = sub.attempts[-1].changes
        if changes is None:
            msg = "a merge with no recorded change check"
            raise RunStateError(msg, subtask=subtask_id)
        checked = changes.checked_commit
        merge_text = merge_message(
            subtask_id, attempt, checked, str(line.gate_result), str(line.review_result)
        )
        if not self._apply(subtask_id, attempt, checked, role):
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
        """
        if self.state.integration is None:
            mode = self.config.gate_mode
            order = self.state.order
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
                )
            )
        self._emit(IntegrationEscalated(**self._env(), item_id=item_id))

    def _diff(self, subtask_id: str, attempt: int) -> None:
        self._stage(subtask_id, attempt, "diff")
        now = self.state.subtasks[subtask_id].attempts[-1]
        since = min(now.applied.values()) - 1 if now.applied else self.state.journal_head
        role = self.state.subtasks[subtask_id].plan.assigned_role
        found = self._graph.divergences(since, role)
        self._emit(
            DiffChecked(**self._env(), subtask_id=subtask_id, attempt=attempt, divergences=found)
        )
        if found:
            self._incident(subtask_id, "cross_role_write", "; ".join(found))

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

    def _trajectories_hold(self, subtask_id: str, sessions: list[SessionEnded]) -> bool:
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

    def _escalate_unavailable(self, subtask_id: str, unavailable: ReviewUnavailable) -> None:
        """Send a subtask whose review reached no verdict to a person, spending no attempt."""
        self._to_a_person(
            subtask_id,
            attempt=unavailable.attempt,
            cause=unavailable.cause,
            detail=unavailable.detail,
            spec_defects=unavailable.spec_defects,
        )

    def _escalate_blocked(self, subtask_id: str, blocked: ReviewRan) -> None:
        """Send a subtask whose review blocked it to a person, spending no attempt.

        The review is on the record as a review; only the routing is shared with a
        review that reached no verdict.
        """
        self._to_a_person(
            subtask_id,
            attempt=blocked.attempt,
            cause="blocking_spec_defect",
            detail=blocked.result.finding,
            spec_defects=blocked.result.spec_defects,
        )

    def _to_a_person(
        self,
        subtask_id: str,
        *,
        attempt: int,
        cause: str,
        detail: str,
        spec_defects: tuple[SpecDefect, ...],
    ) -> None:
        session = self.state.subtasks[subtask_id].attempts[-1].session
        if session is None or session.trajectory is None or session.attempt_commit is None:
            msg = "a review sent to a person with no completed session behind it"
            raise RunStateError(msg, subtask=subtask_id)
        if not self._trajectories_hold(subtask_id, [session]):
            return
        item_id = f"{self.config.run_id}-{subtask_id}"
        if item_id not in {item.item_id for item in self.queue.items()}:
            self.queue.add(
                unavailable_item(
                    item_id=item_id,
                    run_id=self.config.run_id,
                    subtask_id=subtask_id,
                    attempt=attempt,
                    cause=cause,
                    detail=detail,
                    spec_defects=spec_defects,
                    artefact_diff=self._merger.artefact_diff(session.attempt_commit),
                    trajectory=session.trajectory,
                    ts=self.log.events[-1].ts,
                )
            )
        self._emit(Escalated(**self._env(), subtask_id=subtask_id, item_id=item_id))

    def _escalate(self, subtask_id: str) -> None:
        attempts = self.state.subtasks[subtask_id].attempts
        findings = tuple(a.rejected.finding for a in attempts if a.rejected is not None)
        sessions = [a.session for a in attempts if a.session is not None]
        if not self._trajectories_hold(subtask_id, sessions):
            return  # the queue item would link a trajectory that is not what was sealed
        trajectories = tuple(s.trajectory for s in sessions if s.trajectory is not None)
        commits = [s.attempt_commit for s in sessions if s.attempt_commit is not None]
        item_id = f"{self.config.run_id}-{subtask_id}"
        if item_id not in {item.item_id for item in self.queue.items()}:
            self.queue.add(
                escalation_item(
                    item_id=item_id,
                    run_id=self.config.run_id,
                    subtask_id=subtask_id,
                    findings=findings,
                    artefact_diff=self._merger.artefact_diff(commits[-1]),
                    trajectories=trajectories,
                    ts=self.log.events[-1].ts,
                )
            )
        self._emit(Escalated(**self._env(), subtask_id=subtask_id, item_id=item_id))
