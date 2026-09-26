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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from physgate.orchestrator.budget import REPAIR_BUDGET, after_rejection
from physgate.orchestrator.common import GateMode
from physgate.orchestrator.events import (
    AttemptRejected,
    DiffChecked,
    Escalated,
    Event,
    GateRan,
    GateSkipped,
    Halted,
    Incident,
    InfraRetryScheduled,
    Merged,
    ProposalsChecked,
    Resumed,
    ReviewRan,
    RunStarted,
    SessionEnded,
    Stage,
    StageEntered,
    SubtaskPlanned,
    SubtaskRemoved,
    TokensUsed,
)
from physgate.orchestrator.exceptions import MergePreconditionError
from physgate.orchestrator.repair import FindingSource
from physgate.state.task_ledger import TaskLedger, TaskLine


@dataclass
class AttemptState:
    """One implementation attempt of one subtask."""

    number: int
    cursor: Stage | None = None
    session: SessionEnded | None = None
    retries_done: int = 0
    changes: ProposalsChecked | None = None
    gate: GateRan | GateSkipped | None = None
    review: ReviewRan | None = None
    rejected: AttemptRejected | None = None
    merged: Merged | None = None
    diff: DiffChecked | None = None

    def restart(self, cursor: Stage | None) -> None:
        """Forget everything the attempt did after ``cursor``."""
        order: list[Stage | None] = [None, "resolve", "spawn", "verify_reading", "implement"]
        if order.index(cursor) < order.index("spawn"):
            self.session = None
        self.changes = self.gate = self.review = None
        self.cursor = cursor


@dataclass
class SubtaskState:
    """One planned subtask and every attempt made at it."""

    plan: SubtaskPlanned
    status: Literal["planned", "removed", "active", "done", "escalated"] = "planned"
    attempts: list[AttemptState] = field(default_factory=list)
    #: The attempt number a ``resolve`` may start or restart now, if any.
    next_resolve: int | None = 1


@dataclass(frozen=True)
class Step:
    """What the loop does next."""

    kind: Literal["attempt", "infra_failed", "escalate", "halted", "done"]
    subtask_id: str | None = None
    attempt: int | None = None
    point: Literal["resolve", "verify_reading", "diff"] | None = None


def _refuse(message: str) -> None:
    raise ValueError(message)


class RunState:
    """A run's position, rebuilt by following its event log."""

    def __init__(self) -> None:
        """An empty run: nothing started."""
        self.gate_mode: GateMode | None = None
        self.order: list[str] = []
        self.subtasks: dict[str, SubtaskState] = {}
        self.halted: Halted | None = None
        self.incident: Incident | None = None
        self.ledger: list[TaskLine] = []

    # -- following the log -------------------------------------------------------

    def check(self, event: Event) -> None:
        """Raise ``ValueError`` unless ``event`` may be the next line."""
        copy.deepcopy(self).record(event)

    def record(self, event: Event) -> None:
        """Take ``event`` as the next line, or raise ``ValueError`` if it cannot be."""
        if isinstance(event, RunStarted):
            self.gate_mode = event.gate_mode
            return
        if isinstance(event, Halted):
            self.halted = event
            return
        if self.halted is not None and not isinstance(event, Resumed):
            _refuse("the run is halted; only a resume may follow")
        if isinstance(event, SubtaskPlanned):
            self.order.append(event.subtask_id)
            self.subtasks[event.subtask_id] = SubtaskState(plan=event)
            self._ledger(event.subtask_id, attempt_count=0)
            return
        if isinstance(event, TokensUsed):
            return  # attributed, never a transition
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
            self._expect(now.cursor == "review" and now.review is None, "a review line")
            now.review = event
            self._ledger(sub.plan.subtask_id, review_result=event.result.verdict)
        elif isinstance(event, AttemptRejected):
            basis = self.rejection_basis(now)
            self._expect(now.cursor == "decide" and basis == event.finding.source, "a rejection")
            now.rejected = event
            sub.next_resolve = after_rejection(now.number)
        elif isinstance(event, Merged):
            checked = now.changes.checked_commit if now.changes is not None else None
            self._expect(now.cursor == "decide" and self.mergeable(now), "a merge")
            if event.attempt_commit != checked:
                _refuse("a merge of a commit other than the one that was checked")
            now.merged = event
            self._ledger(sub.plan.subtask_id, merge_commit=event.merge_commit)
        elif isinstance(event, DiffChecked):
            self._expect(now.cursor == "diff" and now.diff is None, "a diff line")
            now.diff = event
            if not event.divergences:
                sub.status = "done"
        elif isinstance(event, Escalated):
            last = now.number == REPAIR_BUDGET and now.rejected is not None
            self._expect(last, "an escalation")
            sub.status = "escalated"
        elif isinstance(event, Incident):
            self.incident = event
        elif isinstance(event, Resumed):
            self._resume(sub, now, event.point)

    def _expect(self, condition: bool, what: str) -> None:
        if not condition:
            _refuse(f"{what} cannot come at this point of the attempt")

    def _resolve(self, sub: SubtaskState, attempt: int) -> None:
        if sub.status not in ("planned", "active") or sub.next_resolve != attempt:
            _refuse(f"attempt {attempt} of {sub.plan.subtask_id!r} cannot start now")
        if not sub.attempts or sub.attempts[-1].number != attempt:
            sub.attempts.append(AttemptState(number=attempt))
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
        if not allowed.get(stage, False) or now.rejected is not None:
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
        """The attempt passed review after a gate result that allows a merge."""
        reviewed = now.review is not None and now.review.result.verdict == "pass"
        return reviewed and now.merged is None and self._gate_allows_review(now)

    def _resume(self, sub: SubtaskState, now: AttemptState, point: str) -> None:
        if self.halted is not None and self.halted.reason != "infrastructure_exhausted":
            _refuse(f"a run halted for {self.halted.reason} is not resumed by the loop")
        if self.halted is not None:
            self.halted = None
            now.retries_done = 0
        if point != self.resume_point(now):
            _refuse(f"the attempt resumes at {self.resume_point(now)!r}, not {point!r}")
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
        self.ledger.append(TaskLine.model_validate(base | changes))

    # -- deciding what happens next ------------------------------------------------

    def next_step(self) -> Step:
        """What the loop does next, from the state alone."""
        if self.halted is not None:
            return Step(kind="halted")
        for subtask_id in self.order:
            sub = self.subtasks[subtask_id]
            if sub.status in ("removed", "done", "escalated"):
                continue
            if sub.status == "planned":
                return Step("attempt", subtask_id, 1, "resolve")
            now = sub.attempts[-1]
            if now.rejected is not None:
                if sub.next_resolve is None:
                    return Step("escalate", subtask_id, now.number)
                return Step("attempt", subtask_id, sub.next_resolve, "resolve")
            failed = now.session is not None and now.session.outcome == "infrastructure"
            if failed and sub.next_resolve is None:
                return Step("infra_failed", subtask_id, now.number)
            return Step("attempt", subtask_id, now.number, self.resume_point(now))
        return Step(kind="done")

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
                return sub if self.halted.reason == "infrastructure_exhausted" else None
            clean = now.cursor is None or sub.next_resolve is not None
            failed = now.session is not None and now.session.outcome == "infrastructure"
            # An infrastructure failure not yet answered is answered by the retry
            # schedule, not by a resume, so a crash there cannot reset the count.
            if not clean and not failed and now.rejected is None and now.diff is None:
                return sub
        return None


def project_ledger(state: RunState, ledger: TaskLedger) -> int:
    """Append the ledger lines the state implies and the ledger lacks; return how many.

    Raises:
        MergePreconditionError: the ledger holds lines the event log does not imply,
            so the two records disagree and neither can be trusted to merge from.
    """
    held = ledger.read_all()
    if held != state.ledger[: len(held)]:
        msg = "the task ledger disagrees with the run-event log"
        raise MergePreconditionError(msg, ledger=str(ledger.path))
    for line in state.ledger[len(held) :]:
        ledger.append(line)
    return len(state.ledger) - len(held)


def require_mergeable(ledger_path: Path, subtask_id: str, gate_mode: GateMode) -> TaskLine:
    """The subtask's ledger line, read back from disk, if it permits a merge (ARCH-001).

    A merge needs a gate result and a review result on the ledger line. The review
    must have passed. The gate result must be one the run's gate mode allows:
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
    if line is None or line.gate_result is None or line.review_result is None:
        msg = "a merge needs a gate result and a review result on the ledger line"
        raise MergePreconditionError(msg, subtask=subtask_id)
    if line.review_result != "pass" or line.gate_result not in allowed:
        msg = "the ledger line does not permit a merge"
        raise MergePreconditionError(
            msg,
            subtask=subtask_id,
            gate_result=line.gate_result,
            review_result=line.review_result,
            gate_mode=gate_mode,
        )
    return line
