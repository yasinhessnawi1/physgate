"""The verdict a reviewer answers with, and what code accepts as one.

The reviewer answers through the structured verdict tool, against a schema generated
from its rubric (``contract.verdict_schema``), which the binary enforces inside the
session. The answer is untrusted input all the same: it is validated here again,
field by field and as a whole, and only then becomes a review result. An answer
that is missing, malformed or inconsistent is not a verdict: it is recorded as
unavailable and escalated, never read as a pass or a fail.

**The three verdicts, and the only combinations that make one:**

- ``accept``: no rejecting finding and no blocking specification defect.
  Non-blocking defects may stand beside it; they never change it.
- ``reject``: at least one rejecting finding, named as the failing item. It may
  also carry blocking defects, and the repair instruction then names them too.
- ``blocked``: at least one blocking specification defect and no rejecting
  finding. A safety-critical check cannot be decided because the issued
  specification lacks its input; only the decomposition can fix that, so the
  subtask goes to a person and no repair attempt is spent. It is a verdict, recorded
  as a review like the other two; it is not a pass or a fail.

Every item of the rubric is answered, each under its own section, and nothing else
is: a verdict that leaves an item out, or answers one twice, is not a verdict.

A rejecting finding is an item ``unmet`` or ``confirmed``, an issued-specification
criterion ``unmet``, or an indicator ``confirmed``. Each section allows only its own
results (``SECTION_RESULTS``): ``n/a`` only for a domain standard or an antipattern,
with evidence that its trigger is absent; a reward-hacking item is ``not observed``,
``noted`` or ``confirmed``. Every acceptance criterion of the issued specification has
its own line, apart from the rubric's items: exactly the numbered ones when the
specification numbers them, at least one otherwise. Anything ``not evaluable`` is named
by a specification defect, blocking where the role's rubric requires it. Every check the
trajectory shows switched off (``scan.scan``) is answered by an indicator naming the same
tool call. A number
comes with its unit, never bare.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.protocols import (
    REJECTING_RESULTS,
    CriterionVerdict,
    IndicatorReport,
    ItemVerdict,
    MessageUsage,
    NumericOutput,
    ReviewResult,
    ReviewVerdict,
    SpecDefect,
    UnavailableCause,
)
from physgate.reviewers.contract import as_answer
from physgate.reviewers.rubric import NotEvaluableNeeds, RubricItem
from physgate.reviewers.scan import ScanHit

#: The model's words for its verdict. ``accept`` and ``reject`` become the review's
#: pass and fail; ``blocked`` stays blocked, a verdict that is neither.
ModelVerdictWord = Literal["accept", "reject", "blocked"]
#: What each of the model's words becomes on the review line.
REVIEW_VERDICT: dict[str, ReviewVerdict] = {
    "accept": "pass",
    "reject": "fail",
    "blocked": "blocked",
}


class ModelVerdict(BaseModel):
    """The model's answer, as validated: the boundary between its text and the record."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)

    verdict: ModelVerdictWord
    finding: NonEmptyStr
    failing_item: NonEmptyStr | None
    subject: NonEmptyStr | None
    numeric_output: NumericOutput | None
    items: tuple[ItemVerdict, ...]
    acceptance_criteria: tuple[CriterionVerdict, ...]
    indicators: tuple[IndicatorReport, ...]
    spec_defects: tuple[SpecDefect, ...]


class Answered(BaseModel):
    """An answer that is a verdict: what the review result is built from."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["verdict"] = "verdict"
    answer: ModelVerdict


class Unavailable(BaseModel):
    """A review that ran and is not a verdict, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["unavailable"] = "unavailable"
    cause: UnavailableCause
    detail: NonEmptyStr
    #: Any specification defects the answer recorded, carried to the approval queue.
    spec_defects: tuple[SpecDefect, ...] = ()


def judge(
    structured: object,
    scan_hits: tuple[ScanHit, ...],
    rubric_items: tuple[RubricItem, ...],
    *,
    criteria: tuple[str, ...] | None = None,
    not_evaluable: NotEvaluableNeeds = "blocking",
) -> Answered | Unavailable:
    """What the reviewer's structured answer ``structured`` amounts to.

    Fails closed. Whatever the model wrote, and whatever goes wrong while reading
    it, the outcome is an accept, a reject or a blocked only when every check below
    has passed on the validated answer itself; anything else is an unavailable
    review with its cause. Nothing is defaulted: no field is filled in, no verdict
    assumed, and the verdict is read only from the validated copy, never from the
    raw answer.
    """
    try:
        return _judge(structured, scan_hits, rubric_items, criteria, not_evaluable)
    except Exception as exc:  # noqa: BLE001 - every failure of reading an answer is no verdict
        detail = f"the answer could not be read: {type(exc).__name__}"
        return Unavailable(cause="invalid_verdict", detail=detail)


def _judge(
    structured: object,
    scan_hits: tuple[ScanHit, ...],
    rubric_items: tuple[RubricItem, ...],
    criteria: tuple[str, ...] | None,
    not_evaluable: NotEvaluableNeeds,
) -> Answered | Unavailable:
    structured = as_answer(structured, rubric_items)
    if structured is None:
        return Unavailable(cause="no_verdict", detail="the review ended without a verdict")
    try:
        # Through JSON, as the answer arrived: strict validation then reads an array
        # as the tuple the model holds, and nothing else is coerced.
        answer = ModelVerdict.model_validate_json(json.dumps(structured, allow_nan=False))
    except ValidationError as exc:
        problem = exc.errors()[0]
        where = ".".join(str(part) for part in problem["loc"]) or "the answer"
        return Unavailable(cause="invalid_verdict", detail=f"{where}: {problem['msg']}")
    # A criterion line's own defect is a specification defect like any other.
    inline = tuple(
        SpecDefect(finding=c.defect.finding, blocking=c.defect.blocking, item=c.criterion)
        for c in answer.acceptance_criteria
        if c.defect is not None
    )
    answer = answer.model_copy(update={"spec_defects": (*answer.spec_defects, *inline)})
    problem_text = _unanswered(answer, rubric_items, criteria) or _inconsistency(
        answer, scan_hits, not_evaluable
    )
    if problem_text is not None:
        return Unavailable(cause="invalid_verdict", detail=problem_text)
    if answer.verdict not in REVIEW_VERDICT:  # pragma: no cover - the type allows no other
        return Unavailable(cause="invalid_verdict", detail="an unknown verdict")
    return Answered(answer=answer)


def _unanswered(
    answer: ModelVerdict, rubric_items: tuple[RubricItem, ...], criteria: tuple[str, ...] | None
) -> str | None:
    """Why the answer does not answer exactly the rubric's items and the issued criteria."""
    expected = {item.id: item.section for item in rubric_items}
    if not expected:
        return "there is no rubric item to answer, so no verdict can be checked"
    given = [i.item for i in answer.items]
    twice = sorted({i for i in given if given.count(i) > 1})
    if twice:
        return "an item is answered twice: " + ", ".join(twice)
    missing = [i for i in expected if i not in given]
    if missing:
        return "the verdict leaves rubric items unanswered: " + ", ".join(missing)
    unknown = sorted(set(given) - set(expected))
    if unknown:
        return "the verdict answers items the rubric does not have: " + ", ".join(unknown)
    moved = sorted(i.item for i in answer.items if expected[i.item] != i.section)
    if moved:
        return "an item is answered under another section than its own: " + ", ".join(moved)
    given_criteria = [c.criterion for c in answer.acceptance_criteria]
    if not given_criteria:
        return "every acceptance criterion of the issued specification has its line, at least one"
    if len(given_criteria) != len(set(given_criteria)):
        return "an acceptance criterion of the issued specification is answered twice"
    if criteria is not None and sorted(given_criteria) != sorted(criteria):
        return (
            "the issued specification's acceptance criteria are "
            + ", ".join(criteria)
            + "; the verdict answers "
            + ", ".join(given_criteria)
        )
    named = set(expected) | set(given_criteria)
    if answer.failing_item is not None and answer.failing_item not in named:
        return "the failing item is not an item of the rubric nor a criterion of the specification"
    return None


def _inconsistency(
    answer: ModelVerdict, scan_hits: tuple[ScanHit, ...], not_evaluable: NotEvaluableNeeds
) -> str | None:
    unmet = {i.item for i in answer.items if i.result in REJECTING_RESULTS} | {
        c.criterion for c in answer.acceptance_criteria if c.result == "unmet"
    }
    confirmed = any(r.disposition == "confirmed" for r in answer.indicators)
    rejecting = bool(unmet) or confirmed
    blocking = {d.item for d in answer.spec_defects if d.blocking}
    if answer.verdict == "accept" and (rejecting or blocking):
        return "an accept carries no rejecting finding and no blocking specification defect"
    if answer.verdict == "reject" and not rejecting:
        return "a reject names at least one unmet item or confirmed indicator"
    if answer.verdict == "blocked" and (rejecting or not blocking):
        return "blocked is a blocking specification defect and no rejecting finding"
    if answer.verdict == "reject" and answer.failing_item is None:
        return "a reject names the rubric item that rejects"
    if answer.verdict != "reject" and answer.failing_item is not None:
        return "only a reject names a failing item"
    if answer.verdict == "reject" and unmet and answer.failing_item not in unmet:
        return "the failing item is not one the verdict found unmet"
    if not_evaluable == "blocking":
        unblocked = sorted(
            c.criterion
            for c in answer.acceptance_criteria
            if c.result == "not evaluable" and c.defect is not None and not c.defect.blocking
        )
        if unblocked:
            return "a criterion not evaluable carries a blocking defect: " + ", ".join(unblocked)
    unevaluated = {i.item for i in answer.items if i.result == "not evaluable"}
    named = blocking if not_evaluable == "blocking" else {d.item for d in answer.spec_defects}
    if unevaluated - named:
        missing = ", ".join(sorted(unevaluated - named))
        kind = "a blocking specification defect" if not_evaluable == "blocking" else "a defect"
        return f"an item not evaluable is named by {kind}: " + missing
    answered = {r.evidence for r in answer.indicators}
    unanswered = sorted({h.evidence for h in scan_hits} - answered)
    if unanswered:
        return "a check the trajectory shows switched off is not answered: " + ", ".join(unanswered)
    return None


def to_result(
    answered: Answered,
    *,
    reviewer_model: str,
    session_id: str,
    usage: tuple[MessageUsage, ...],
    rubric_sha256: str,
    rubric_kind: Literal["paired", "generalist"],
    packet_sha256: str,
    reading_verified: bool,
    peak_context_tokens: int,
    schema_refusals: int | None = None,
    max_output_tokens: int | None = None,
    context_window: int | None = None,
) -> ReviewResult:
    """The review result a verdict becomes: the answer as given, and the record.

    ``accept`` is the review's pass, ``reject`` its fail and ``blocked`` stays blocked;
    nothing here changes which, specification defects included.
    """
    answer = answered.answer
    return ReviewResult(
        verdict=REVIEW_VERDICT[answer.verdict],
        finding=answer.finding,
        reviewer_model=reviewer_model,
        session_id=session_id,
        usage=usage,
        failing_item=answer.failing_item,
        subject=answer.subject,
        numeric_output=answer.numeric_output,
        items=answer.items,
        criteria=answer.acceptance_criteria,
        indicators=answer.indicators,
        spec_defects=answer.spec_defects,
        rubric_sha256=rubric_sha256,
        rubric_kind=rubric_kind,
        packet_sha256=packet_sha256,
        reading_verified=reading_verified,
        peak_context_tokens=peak_context_tokens,
        schema_refusals=schema_refusals,
        max_output_tokens=max_output_tokens,
        context_window=context_window,
    )
