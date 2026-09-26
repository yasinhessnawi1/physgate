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
from typing import Any

from physgate.orchestrator.budget import infra_retry_delay
from physgate.orchestrator.common import utc_now
from physgate.orchestrator.events import (
    AttemptRejected,
    DiffChecked,
    Escalated,
    GateRan,
    GateSkipped,
    Halted,
    Incident,
    InfraRetryScheduled,
    Merged,
    ProposalsChecked,
    Resumed,
    ReviewRan,
    SessionEnded,
    StageEntered,
    TokensUsed,
)
from physgate.orchestrator.exceptions import (
    GateNotRegisteredError,
    MergeConflictError,
    MergeRefusedError,
    ReviewerNotRegisteredError,
    RunStateError,
)
from physgate.orchestrator.merge import merge_message
from physgate.orchestrator.ports import ChangeChecker, Dispatcher, GraphDiff, Merger, SessionRequest
from physgate.orchestrator.protocols import (
    Artefact,
    Gate,
    Reviewer,
    require_mode,
    require_separate_models,
)
from physgate.orchestrator.queue import escalation_item
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.repair import Finding, repair_instruction
from physgate.orchestrator.replay import Step, require_mergeable
from physgate.orchestrator.run_config import RunConfig

UNREAD = (
    "The session ended without completing its required reading, so nothing it "
    "produced is considered."
)


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
    if config.gate_mode != "off" and gate is None:
        msg = (
            f"the gate stage cannot pass: gate mode is {config.gate_mode!r} and no gate is "
            "registered"
        )
        raise GateNotRegisteredError(msg, gate_mode=config.gate_mode)
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
        graph_diff: GraphDiff,
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
        self._graph_diff = graph_diff
        self._sleep = sleep
        self.record = RunRecord(config, self.run_dir, clock=clock)
        self.state = self.record.state
        self.log = self.record.log
        self.ledger = self.record.ledger
        self.queue = self.record.queue

    def close(self) -> None:
        """Release every file handle."""
        self.record.close()

    def _emit(self, kind: Any, **fields: Any) -> Any:  # noqa: ANN401 - forwards to the log
        return self.record.emit(kind, **fields)

    # -- the run's life -------------------------------------------------------------

    def start(self, plan: Sequence[Mapping[str, str]]) -> None:
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
        if self.state.halted is None and self.state.interrupted() is not None:
            msg = "the run was interrupted mid-attempt; resume it instead"
            raise RunStateError(msg, run_dir=str(self.run_dir))
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
        halted = self.state.halted
        if halted is not None and halted.reason != "infrastructure_exhausted":
            msg = f"the run halted for {halted.reason}; a person resolves that before any resume"
            raise RunStateError(msg, run_dir=str(self.run_dir), detail=halted.detail)
        sub = self.state.interrupted()
        if sub is not None:
            now = sub.attempts[-1]
            self._emit(
                Resumed,
                subtask_id=sub.plan.subtask_id,
                attempt=now.number,
                point=self.state.resume_point(now),
            )
        return self._drive()

    def _drive(self) -> Step:
        while True:
            step = self.state.next_step()
            if step.kind in ("done", "halted"):
                return step
            if step.subtask_id is None or step.attempt is None:
                msg = "a step with no subtask or attempt"
                raise RunStateError(msg, step=step.kind)
            if step.kind == "escalate":
                self._escalate(step.subtask_id)
            elif step.kind == "infra_failed":
                self._infra_failed(step.subtask_id, step.attempt)
            else:
                self._attempt(step.subtask_id, step.attempt, step.point or "resolve")

    # -- one attempt ------------------------------------------------------------------

    def _stage(self, subtask_id: str, attempt: int, stage: str) -> None:
        self._emit(StageEntered, subtask_id=subtask_id, attempt=attempt, stage=stage)

    def _reject(self, subtask_id: str, attempt: int, finding: Finding) -> None:
        self._stage(subtask_id, attempt, "decide")
        self._emit(AttemptRejected, subtask_id=subtask_id, attempt=attempt, finding=finding)

    def _attempt(self, subtask_id: str, attempt: int, point: str) -> None:
        if point == "resolve" and not self._session(subtask_id, attempt):
            return
        if point in ("resolve", "verify_reading") and not self._judge(subtask_id, attempt):
            return
        self._diff(subtask_id, attempt)

    def _session(self, subtask_id: str, attempt: int) -> bool:
        sub = self.state.subtasks[subtask_id]
        self._stage(subtask_id, attempt, "resolve")
        self._stage(subtask_id, attempt, "spawn")
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
        )
        report = self._dispatcher.run(request)
        for message in report.usage:
            self._emit(
                TokensUsed,
                attribution=f"session:{report.session_id}",
                message_id=message.message_id,
                usage=message.usage,
            )
        self._emit(
            SessionEnded,
            subtask_id=subtask_id,
            attempt=attempt,
            session_id=report.session_id,
            outcome=report.end.outcome,
            cause=report.end.cause,
            attempt_commit=report.attempt_commit,
            trajectory=report.trajectory,
            worktree=report.worktree,
            reading_verified=report.reading_verified,
        )
        return report.end.outcome == "completed"

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
            ProposalsChecked,
            subtask_id=subtask_id,
            attempt=attempt,
            checked_commit=session.attempt_commit,
            **check.model_dump(),
        )
        if check.refused_by is not None and check.reason is not None:
            self._reject(subtask_id, attempt, Finding(source=check.refused_by, text=check.reason))
            return False
        artefact = Artefact(
            subtask_id=subtask_id,
            attempt=attempt,
            assigned_role=role,
            attempt_commit=session.attempt_commit,
            worktree=session.worktree,
            graph_root=check.graph_root,
            trajectory=session.trajectory,
        )
        self._stage(subtask_id, attempt, "gate")
        mode = self.config.gate_mode
        if mode == "off":
            self._emit(GateSkipped, subtask_id=subtask_id, attempt=attempt, reason="gate_mode=off")
        else:
            if self._gate is None:
                msg = f"the gate stage cannot pass: gate mode is {mode!r} and no gate is registered"
                raise GateNotRegisteredError(msg, gate_mode=mode)
            result = require_mode(self._gate.check(artefact, mode=mode), mode)
            self._emit(GateRan, subtask_id=subtask_id, attempt=attempt, result=result)
            if result.verdict == "fail" and mode == "on":
                self._reject(subtask_id, attempt, Finding.from_gate(result))
                return False
        self._stage(subtask_id, attempt, "review")
        reviewer = self._reviewers[role]
        require_separate_models(implementer=self.config.models.roles[role], reviewer=reviewer.model)
        review = reviewer.review(artefact)
        if review.reviewer_model != reviewer.model:
            msg = "a reviewer reported a model other than the one it is pinned to"
            raise ReviewerNotRegisteredError(msg, role=role, reported=review.reviewer_model)
        for message in review.usage:
            self._emit(
                TokensUsed,
                attribution=f"reviewer:{review.session_id}",
                message_id=message.message_id,
                usage=message.usage,
            )
        self._emit(ReviewRan, subtask_id=subtask_id, attempt=attempt, result=review)
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
        try:
            merge_commit = self._merger.merge(subtask_id, attempt, checked, merge_text)
        except (MergeConflictError, MergeRefusedError) as exc:
            cause = "merge_conflict" if isinstance(exc, MergeConflictError) else "merge_refused"
            self._emit(Incident, subtask_id=subtask_id, cause=cause, detail=str(exc))
            self._emit(Halted, reason="incident", detail=f"{cause} in {subtask_id}")
            return False
        self._emit(
            Merged,
            subtask_id=subtask_id,
            attempt=attempt,
            attempt_commit=checked,
            merge_commit=merge_commit,
        )
        return True

    def _diff(self, subtask_id: str, attempt: int) -> None:
        self._stage(subtask_id, attempt, "diff")
        found = self._graph_diff.divergences(subtask_id)
        self._emit(DiffChecked, subtask_id=subtask_id, attempt=attempt, divergences=found)
        if found:
            detail = "; ".join(found)
            self._emit(Incident, subtask_id=subtask_id, cause="cross_role_write", detail=detail)
            self._emit(Halted, reason="incident", detail=f"cross-role write in {subtask_id}")

    # -- what is not an attempt ---------------------------------------------------------

    def _infra_failed(self, subtask_id: str, attempt: int) -> None:
        now = self.state.subtasks[subtask_id].attempts[-1]
        delay = infra_retry_delay(self.config.bounds.infra_retry_delays_s, now.retries_done)
        cause = now.session.cause if now.session else "unknown"
        if delay is None:
            detail = (
                f"subtask {subtask_id} attempt {attempt}: {cause} after "
                f"{now.retries_done} infrastructure retries"
            )
            self._emit(Halted, reason="infrastructure_exhausted", detail=detail)
            return
        self._emit(
            InfraRetryScheduled,
            subtask_id=subtask_id,
            attempt=attempt,
            retries_done=now.retries_done,
            delay_s=delay,
        )
        self._sleep(delay)

    def _escalate(self, subtask_id: str) -> None:
        attempts = self.state.subtasks[subtask_id].attempts
        findings = tuple(a.rejected.finding for a in attempts if a.rejected is not None)
        sessions = [a.session for a in attempts if a.session is not None]
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
        self._emit(Escalated, subtask_id=subtask_id, item_id=item_id)
