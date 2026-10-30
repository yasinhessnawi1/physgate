"""What an escalation backend is shown about an attempt: the ``state`` of ARCH-131.

ARCH-131 defines the state as the structured subtask record at the end of an attempt:
the task-ledger line, the gate result, the reviewer verdict and the changed-node
summary, with no free text. Each part below is copied from one record the run already
writes, and says which. Nothing is derived beyond counting, and nothing a person or a
model phrased is carried: no finding, message, evidence, reason, path or model string.
That is held by the types, not only by what the builder copies: every string field is an
identifier, and a failing item the reviewer named in words (an issued specification that
does not number its criteria) is not carried, only the fact that it was so named.

The state is built from the run as its event log replays (``RunState``), never from
an open ledger or store, so building it writes nothing and reads only what the log
says happened.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.common import GateMode
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.protocols import (
    CheckName,
    CriterionResult,
    IndicatorDisposition,
    IndicatorKind,
    ItemResult,
    RecordedUnavailableCause,
    ReviewVerdict,
    RubricSection,
    Scope,
    Verdict,
)
from physgate.orchestrator.protocols import Outcome as CheckOutcome
from physgate.orchestrator.repair import FindingSource

if TYPE_CHECKING:
    from physgate.orchestrator.replay import RunState

#: How an attempt that did not merge ended.
AttemptEnd = Literal["rejected", "review_blocked", "review_unavailable"]
#: What a task-ledger line records for a gate or a review (the ledger's own vocabulary).
LedgerOutcome = Literal["pass", "fail", "skipped", "blocked"]
Count = Annotated[int, Field(ge=0)]
#: A name the run gave something: a subtask, a role, a node. One token, no spaces, so no
#: sentence fits.
IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER)]
#: A rubric item's id, as a promoted rubric numbers its items (``DS-4``, ``AC-1``).
RUBRIC_ITEM = r"^[A-Z]{1,2}-?[0-9]+$"
#: What a failing item may be in the state: a rubric item's id, or an acceptance criterion's
#: number in the issued specification.
FAILING_ITEM = r"^(?:[A-Z]{1,2}-?[0-9]+|[0-9]+)$"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class LedgerPart(_Frozen):
    """From the task-ledger line (ARCH-012), as projected when the attempt ended.

    The specification path is left out (a path, not a fact about the attempt), and so is
    the merge commit, which is always empty where the question is asked.
    """

    subtask_id: Identifier
    assigned_role: Identifier
    attempt_count: Annotated[int, Field(ge=1)]
    gate_result: LedgerOutcome | None
    review_result: LedgerOutcome | None


class EndPart(_Frozen):
    """From the line that ended the attempt.

    A rejection, a blocked review, or the final line of a review that reached no verdict.
    """

    kind: AttemptEnd
    #: The rejection's finding source; only for a rejection.
    rejected_by: FindingSource | None
    #: Whether the previous attempt was rejected for the same finding; only for a rejection.
    repeats_previous: bool | None
    #: Why no verdict was reached; only for a review with none.
    unavailable_cause: RecordedUnavailableCause | None
    #: Whether a review of this attempt was retried for an infrastructure failure first.
    review_retried: bool

    @model_validator(mode="after")
    def _each_kind_carries_its_own_fields(self) -> EndPart:
        rejection = self.kind == "rejected"
        if rejection != (self.rejected_by is not None and self.repeats_previous is not None):
            msg = "a rejection, and only a rejection, carries its source and repeat flag"
            raise ValueError(msg)
        if (self.kind == "review_unavailable") != (self.unavailable_cause is not None):
            msg = "a review with no verdict, and only one, carries its cause"
            raise ValueError(msg)
        return self


class ChangesPart(_Frozen):
    """From the change check (``ProposalsChecked``): the changed-node summary."""

    refused_by: Literal["proposal", "write_scope", "series", "declaration", "dispute"] | None
    proposed: tuple[Identifier, ...]


class GateCheck(_Frozen):
    """One gate record's structured fields: no node, message, value or details."""

    check: CheckName
    scope: Scope
    outcome: CheckOutcome
    blocking: bool


class GatePart(_Frozen):
    """From the gate line: the gate result (``GateRan``), or the stage skipped (``GateSkipped``)."""

    ran: bool
    mode: GateMode
    verdict: Verdict | None
    failing_check: CheckName | None
    checks: tuple[GateCheck, ...]

    @model_validator(mode="after")
    def _a_skipped_gate_has_no_result(self) -> GatePart:
        if not self.ran and (self.verdict is not None or self.checks or self.mode != "off"):
            msg = "a skipped gate stage has no verdict and no checks, and only under off"
            raise ValueError(msg)
        if self.ran and self.verdict is None:
            msg = "a gate that ran has a verdict"
            raise ValueError(msg)
        return self


class ReviewItem(_Frozen):
    """One rubric item's verdict: its id, section and result, without the evidence."""

    item: Annotated[str, StringConstraints(pattern=RUBRIC_ITEM)]
    section: RubricSection
    result: ItemResult


class Indicator(_Frozen):
    """One reward-hacking indicator: its kind and how it was dispositioned."""

    kind: IndicatorKind
    disposition: IndicatorDisposition


class CriteriaCount(_Frozen):
    """How many of the issued specification's acceptance criteria came out each way."""

    met: Count
    unmet: Count
    not_evaluable: Count


class ReviewPart(_Frozen):
    """From the review line (``ReviewRan``): the verdict's structured fields."""

    verdict: ReviewVerdict
    rubric_kind: Literal["paired", "generalist"] | None
    reading_verified: bool | None
    #: The failing item when it is an identifier the review answered: a rubric item's id, or
    #: a numbered acceptance criterion. Otherwise ``None``.
    failing_item: Annotated[str, StringConstraints(pattern=FAILING_ITEM)] | None
    #: The reviewer named a failing item in its own words (the issued specification did not
    #: number its criteria): those words are not carried, only that they were written.
    failing_item_in_words: bool
    items: tuple[ReviewItem, ...]
    criteria: CriteriaCount
    indicators: tuple[Indicator, ...]
    spec_defects: Count
    blocking_spec_defects: Count

    @model_validator(mode="after")
    def _a_failing_item_is_carried_or_said_to_be_in_words(self) -> ReviewPart:
        if self.failing_item_in_words and self.failing_item is not None:
            msg = "a failing item named in words is not carried"
            raise ValueError(msg)
        return self


class EscalationState(_Frozen):
    """The state an escalation backend decides from, one part per source record."""

    ledger: LedgerPart
    ended: EndPart
    #: ``None`` when the attempt ended before its changes were checked (unread).
    changes: ChangesPart | None
    #: ``None`` when the attempt ended before the gate stage.
    gate: GatePart | None
    #: ``None`` when no review verdict exists for the attempt.
    review: ReviewPart | None

    @property
    def attempt_end(self) -> AttemptEnd:
        """How the attempt ended (what the interface's forced routes read)."""
        return self.ended.kind

    @property
    def attempt_count(self) -> int:
        """Which attempt it was, from the ledger line."""
        return self.ledger.attempt_count


#: Each part of the state and the record it is copied from.
SOURCES: Final[dict[str, str]] = {
    "ledger": "the task-ledger line (TaskLine)",
    "ended": "attempt_rejected, a review_ran with verdict blocked, or a final review_unavailable",
    "changes": "proposals_checked",
    "gate": "gate_ran or gate_skipped",
    "review": "review_ran",
}


def escalation_state(state: RunState, subtask_id: str) -> EscalationState:
    """The state of ``subtask_id``'s last attempt, which ended without a merge.

    Raises:
        RunStateError: the subtask has no attempt, its attempt did not end in one of the
            three ways the question is asked at, or its ledger line disagrees with the
            attempt.
    """
    sub = state.subtasks.get(subtask_id)
    if sub is None or not sub.attempts:
        msg = "an escalation state for a subtask with no attempt"
        raise RunStateError(msg, subtask=subtask_id)
    now = sub.attempts[-1]
    line = next((ln for ln in reversed(state.ledger) if ln.id == subtask_id), None)
    if line is None or line.attempt_count != now.number:
        msg = "the ledger line does not describe the attempt that ended"
        raise RunStateError(msg, subtask=subtask_id, attempt=str(now.number))
    return EscalationState(
        ledger=LedgerPart(
            subtask_id=line.id,
            assigned_role=line.assigned_role,
            attempt_count=line.attempt_count,
            gate_result=line.gate_result,
            review_result=line.review_result,
        ),
        ended=_ended(state, subtask_id),
        changes=None
        if now.changes is None
        else ChangesPart(refused_by=now.changes.refused_by, proposed=now.changes.proposed),
        gate=_gate(state, subtask_id),
        review=_review(state, subtask_id),
    )


def _ended(state: RunState, subtask_id: str) -> EndPart:
    now = state.subtasks[subtask_id].attempts[-1]
    retried = any(u.retry for u in now.unavailable)
    if now.rejected is not None:
        return EndPart(
            kind="rejected",
            rejected_by=now.rejected.finding.source,
            repeats_previous=now.rejected.repeats_previous,
            unavailable_cause=None,
            review_retried=retried,
        )
    if now.blocked is not None:
        return EndPart(
            kind="review_blocked",
            rejected_by=None,
            repeats_previous=None,
            unavailable_cause=None,
            review_retried=retried,
        )
    final = now.unavailable_final
    if final is not None:
        return EndPart(
            kind="review_unavailable",
            rejected_by=None,
            repeats_previous=None,
            unavailable_cause=final.cause,
            review_retried=retried,
        )
    msg = "the attempt did not end in a rejection, a blocked review or a review with no verdict"
    raise RunStateError(msg, subtask=subtask_id, attempt=str(now.number))


def _gate(state: RunState, subtask_id: str) -> GatePart | None:
    gate = state.subtasks[subtask_id].attempts[-1].gate
    if gate is None:
        return None
    if gate.kind == "gate_skipped":
        return GatePart(ran=False, mode=gate.gate_mode, verdict=None, failing_check=None, checks=())
    result = gate.result
    # The gate names its failing check by the check's name; validating the part holds the
    # field to that vocabulary, so a result carrying anything else is refused, not passed on.
    return GatePart.model_validate(
        {
            "ran": True,
            "mode": result.mode,
            "verdict": result.verdict,
            "failing_check": result.failing_check,
            "checks": tuple(
                GateCheck(check=r.name, scope=r.scope, outcome=r.outcome, blocking=r.blocking)
                for r in result.checks
            ),
        }
    )


def _review(state: RunState, subtask_id: str) -> ReviewPart | None:
    review = state.subtasks[subtask_id].attempts[-1].review
    if review is None:
        return None
    result = review.result
    results: list[CriterionResult] = [c.result for c in result.criteria]
    # Carried only as an identifier the review itself answered: a rubric item's id, or a
    # criterion the issued specification numbered. Anything else is the reviewer's words.
    named = result.failing_item
    answered = {i.item for i in result.items} | {c.criterion for c in result.criteria}
    carried = (
        named
        if named is not None and named in answered and re.fullmatch(FAILING_ITEM, named)
        else None
    )
    return ReviewPart(
        verdict=result.verdict,
        rubric_kind=result.rubric_kind,
        reading_verified=result.reading_verified,
        failing_item=carried,
        failing_item_in_words=named is not None and carried is None,
        items=tuple(
            ReviewItem(item=i.item, section=i.section, result=i.result) for i in result.items
        ),
        criteria=CriteriaCount(
            met=results.count("met"),
            unmet=results.count("unmet"),
            not_evaluable=results.count("not evaluable"),
        ),
        indicators=tuple(
            Indicator(kind=i.kind, disposition=i.disposition) for i in result.indicators
        ),
        spec_defects=len(result.spec_defects),
        blocking_spec_defects=sum(1 for d in result.spec_defects if d.blocking),
    )
