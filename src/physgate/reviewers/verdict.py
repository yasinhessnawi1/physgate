"""The verdict a reviewer answers with, and what code accepts as one.

The reviewer answers once, through the structured verdict tool, against
:data:`VERDICT_SCHEMA`. The answer is untrusted input: it is validated here again,
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
  subtask goes to a person and no repair attempt is spent.

Every item of the rubric is answered, each under its own section, and nothing else
is: a verdict that leaves an item out, or answers one twice, is not a verdict.

A rejecting finding is an item ``unmet`` (an acceptance criterion included) or a
reward-hacking indicator ``confirmed``. An item ``not evaluable`` must be named by
a blocking defect. ``n/a`` is allowed only for a domain standard or an antipattern,
with evidence that its trigger is absent. Every check the trajectory shows switched
off (``scan.scan``) is answered by an indicator naming the same tool call. A number
comes with its unit, never bare.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.protocols import (
    IndicatorReport,
    ItemVerdict,
    MessageUsage,
    NumericOutput,
    ReviewResult,
    SpecDefect,
    UnavailableCause,
)
from physgate.reviewers.rubric import RubricItem
from physgate.reviewers.scan import ScanHit

#: The model's words for its verdict. ``accept`` and ``reject`` become the review's
#: pass and fail; ``blocked`` is not a verdict on the attempt.
ModelVerdictWord = Literal["accept", "reject", "blocked"]

_SECTIONS = ["acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking"]

#: What the structured verdict tool offers the model. Written out rather than
#: generated, so it carries no references a tool schema might not resolve; a test
#: holds it to :class:`ModelVerdict`, which is what the answer is validated with.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "finding",
        "failing_item",
        "subject",
        "numeric_output",
        "items",
        "indicators",
        "spec_defects",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject", "blocked"]},
        "finding": {"type": "string", "minLength": 1},
        "failing_item": {"type": ["string", "null"]},
        "subject": {"type": ["string", "null"]},
        "numeric_output": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "unit"],
                    "properties": {
                        "value": {"type": "number"},
                        "unit": {"type": "string", "minLength": 1},
                    },
                },
            ]
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "section", "result", "evidence"],
                "properties": {
                    "item": {"type": "string", "minLength": 1},
                    "section": {"type": "string", "enum": _SECTIONS},
                    "result": {
                        "type": "string",
                        "enum": ["met", "unmet", "noted", "n/a", "not evaluable"],
                    },
                    "evidence": {"type": "string"},
                },
            },
        },
        "indicators": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "evidence", "disposition", "reason"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["feature_isolation", "hard_coded_values", "disabled_checks"],
                    },
                    "evidence": {"type": "string", "minLength": 1},
                    "disposition": {"type": "string", "enum": ["confirmed", "noted", "dismissed"]},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        },
        "spec_defects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["finding", "blocking", "item"],
                "properties": {
                    "finding": {"type": "string", "minLength": 1},
                    "blocking": {"type": "boolean"},
                    "item": {"type": ["string", "null"]},
                },
            },
        },
    },
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
    #: A blocking defect's findings, carried to the approval queue.
    spec_defects: tuple[SpecDefect, ...] = ()


def judge(
    structured: object, scan_hits: tuple[ScanHit, ...], rubric_items: tuple[RubricItem, ...]
) -> Answered | Unavailable:
    """What the reviewer's structured answer ``structured`` amounts to.

    Fails closed. Whatever the model wrote, and whatever goes wrong while reading
    it, the outcome is an accept or a reject only when every check below has
    passed on the validated answer itself; anything else is an unavailable review
    with its cause, ``blocked`` among them. Nothing is defaulted: no field is
    filled in, no verdict assumed, and the verdict is read only from the validated
    copy, never from the raw answer.
    """
    try:
        return _judge(structured, scan_hits, rubric_items)
    except Exception as exc:  # noqa: BLE001 - every failure of reading an answer is no verdict
        detail = f"the answer could not be read: {type(exc).__name__}"
        return Unavailable(cause="invalid_verdict", detail=detail)


def _judge(
    structured: object, scan_hits: tuple[ScanHit, ...], rubric_items: tuple[RubricItem, ...]
) -> Answered | Unavailable:
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
    problem_text = _unanswered(answer, rubric_items) or _inconsistency(answer, scan_hits)
    if problem_text is not None:
        return Unavailable(cause="invalid_verdict", detail=problem_text)
    if answer.verdict == "blocked":
        return Unavailable(
            cause="blocking_spec_defect",
            detail="a safety-critical check cannot be decided from the issued specification",
            spec_defects=answer.spec_defects,
        )
    if answer.verdict not in ("accept", "reject"):  # pragma: no cover - the type allows no other
        return Unavailable(cause="invalid_verdict", detail="an unknown verdict")
    return Answered(answer=answer)


def _unanswered(answer: ModelVerdict, rubric_items: tuple[RubricItem, ...]) -> str | None:
    """Why the answer does not answer exactly the rubric's items, each in its own section."""
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
    if answer.failing_item is not None and answer.failing_item not in expected:
        return "the failing item is not an item of the rubric"
    return None


def _inconsistency(answer: ModelVerdict, scan_hits: tuple[ScanHit, ...]) -> str | None:
    unmet = {i.item for i in answer.items if i.result == "unmet"}
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
    unevaluated = {i.item for i in answer.items if i.result == "not evaluable"}
    if unevaluated - blocking:
        missing = ", ".join(sorted(unevaluated - blocking))
        return "an item not evaluable is named by a blocking specification defect: " + missing
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
) -> ReviewResult:
    """The review result an accept or a reject becomes: the answer as given, and the record.

    ``accept`` is the review's pass and ``reject`` its fail; nothing here changes
    which, specification defects included.
    """
    answer = answered.answer
    return ReviewResult(
        verdict="pass" if answer.verdict == "accept" else "fail",
        finding=answer.finding,
        reviewer_model=reviewer_model,
        session_id=session_id,
        usage=usage,
        failing_item=answer.failing_item,
        subject=answer.subject,
        numeric_output=answer.numeric_output,
        items=answer.items,
        indicators=answer.indicators,
        spec_defects=answer.spec_defects,
        rubric_sha256=rubric_sha256,
        rubric_kind=rubric_kind,
        packet_sha256=packet_sha256,
        reading_verified=reading_verified,
        peak_context_tokens=peak_context_tokens,
    )
