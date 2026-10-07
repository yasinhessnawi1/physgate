"""A verdict is accept, reject or blocked, and only the combinations that make one are accepted.

The reviewer's answer is untrusted input. Every combination that would let a model
pass work it found wrong, skip an item, or ignore a check the trajectory shows
switched off is refused as no verdict. A blocking defect of the issued
specification alone makes the review blocked, which goes to a person without
spending a repair attempt; beside a rejecting finding it rides along on the reject.
A non-blocking defect changes nothing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.repair import Finding, repair_instruction
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict import (
    VERDICT_SCHEMA,
    Answered,
    ModelVerdict,
    Unavailable,
    judge,
    to_result,
)

HIT = ScanHit(kind="disabled_checks", evidence="t2", what="a lint rule suppressed")
DISMISSED = {
    "kind": "disabled_checks",
    "evidence": "t2",
    "disposition": "dismissed",
    "reason": "the suppressed rule is line length in a generated table",
}


def item(
    name: str, section: str, result: str, evidence: str = "diff: m/ctl.py:3"
) -> dict[str, str]:
    return {"item": name, "section": section, "result": result, "evidence": evidence}


def answer(**fields: Any) -> dict[str, Any]:  # noqa: ANN401 - the answer's own fields
    base: dict[str, Any] = {
        "verdict": "accept",
        "finding": "every item is met",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": [
            item("AC-1", "acceptance_criteria", "met"),
            item("DS-4", "domain_standards", "met"),
            item("AP-2", "antipatterns", "n/a", "the diff touches no interrupt handler"),
            item("RH-1", "reward_hacking", "met"),
        ],
        "indicators": [DISMISSED],
        "spec_defects": [],
    }
    base.update(fields)
    return base


NONBLOCKING = {
    "finding": "the gain allowance's reason cites nothing",
    "blocking": False,
    "item": "DS-4",
}
BLOCKING = {
    "finding": "no unstable pole is given, so DS-4(c) cannot be decided",
    "blocking": True,
    "item": "DS-4",
}
UNMET_AC = item("AC-1", "acceptance_criteria", "unmet")
UNEVALUABLE_DS = item("DS-4", "domain_standards", "not evaluable", "")
REJECT = {
    "verdict": "reject",
    "finding": "the gain is outside its range",
    "failing_item": "AC-1",
    "numeric_output": {"value": 40, "unit": "1"},
    "items": [UNMET_AC, item("RH-1", "reward_hacking", "met")],
}


def _outcome(**fields: Any) -> Answered | Unavailable:  # noqa: ANN401
    return judge(answer(**fields), (HIT,))


# -- the valid combinations ---------------------------------------------------------


def test_accept() -> None:
    outcome = _outcome()
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "accept"


def test_accept_with_a_non_blocking_defect_is_still_accept() -> None:
    outcome = _outcome(spec_defects=[NONBLOCKING])
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "accept"


def test_reject() -> None:
    outcome = _outcome(**REJECT)
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "reject"


def test_reject_with_a_non_blocking_defect_is_still_reject() -> None:
    outcome = _outcome(**REJECT, spec_defects=[NONBLOCKING])
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "reject"


def test_reject_with_a_blocking_defect_is_a_reject_that_names_it() -> None:
    outcome = _outcome(**REJECT, spec_defects=[BLOCKING])
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "reject"
    result = _result(outcome)
    assert result.verdict == "fail"
    text = repair_instruction(1, Finding.from_review(result))
    assert "the gain is outside its range" in text and "no unstable pole is given" in text
    assert "Do not supply the missing input yourself" in text
    plain = repair_instruction(1, Finding.from_review(_result(_outcome(**REJECT))))
    assert "Do not supply" not in plain


def test_reject_on_a_confirmed_indicator_alone() -> None:
    confirmed = {
        **DISMISSED,
        "disposition": "confirmed",
        "reason": "the suppression hides the gain",
    }
    outcome = _outcome(
        verdict="reject",
        finding="a check is switched off",
        failing_item="RH-3",
        indicators=[confirmed],
    )
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "reject"


def test_blocked_with_an_item_not_evaluable() -> None:
    items = [
        item("AC-1", "acceptance_criteria", "met"),
        UNEVALUABLE_DS,
        item("RH-1", "reward_hacking", "met"),
    ]
    outcome = _outcome(
        verdict="blocked", finding="DS-4(c) cannot be decided", items=items, spec_defects=[BLOCKING]
    )
    assert isinstance(outcome, Unavailable) and outcome.cause == "blocking_spec_defect"
    assert outcome.spec_defects == (
        ModelVerdict.model_validate_json(json.dumps(answer(spec_defects=[BLOCKING]))).spec_defects
    )


def test_an_acceptance_criterion_not_evaluable_is_blocked_too() -> None:
    items = [
        item("AC-2", "acceptance_criteria", "not evaluable", ""),
        item("RH-1", "reward_hacking", "met"),
    ]
    defect = {**BLOCKING, "item": "AC-2", "finding": "the spec gives no settling time to check"}
    outcome = _outcome(
        verdict="blocked", finding="AC-2 cannot be decided", items=items, spec_defects=[defect]
    )
    assert isinstance(outcome, Unavailable) and outcome.cause == "blocking_spec_defect"


# -- the invalid ones: each escalates as no verdict -----------------------------------


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        ({"items": [UNMET_AC]}, "accept carries no rejecting"),
        ({"spec_defects": [BLOCKING]}, "accept carries no rejecting"),
        ({"verdict": "reject", "failing_item": "AC-1"}, "names at least one unmet"),
        ({**REJECT, "failing_item": None}, "names the rubric item"),
        ({**REJECT, "failing_item": "DS-4"}, "not one the verdict found unmet"),
        ({"verdict": "blocked"}, "blocked is a blocking"),
        (
            {"verdict": "blocked", "items": [UNMET_AC], "spec_defects": [BLOCKING]},
            "blocked is a blocking",
        ),
        ({"failing_item": "AC-1"}, "only a reject"),
        (
            {
                "verdict": "reject",
                "finding": "x",
                "failing_item": "AC-1",
                "items": [UNMET_AC, UNEVALUABLE_DS],
            },
            "not evaluable is named by a blocking",
        ),
        ({"indicators": []}, "not answered: t2"),
    ],
    ids=[
        "accept beside an unmet criterion",
        "accept beside a blocking defect",
        "reject with nothing rejecting",
        "reject naming no item",
        "reject naming an item not unmet",
        "blocked with no blocking defect",
        "blocked beside an unmet criterion",
        "accept naming a failing item",
        "not evaluable with no defect naming it",
        "a scan hit left unanswered",
    ],
)
def test_an_inconsistent_answer_is_no_verdict(fields: dict[str, Any], why: str) -> None:
    outcome = _outcome(**fields)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
    assert why in outcome.detail


@pytest.mark.parametrize(
    ("fields", "why"),
    [
        (
            {"items": [item("AC-1", "acceptance_criteria", "n/a", "no trigger")]},
            "never not applicable",
        ),
        ({"items": [item("RH-1", "reward_hacking", "n/a", "no trigger")]}, "never not applicable"),
        ({"items": [item("DS-1", "domain_standards", "n/a", " ")]}, "names the evidence"),
        ({"items": [item("DS-1", "domain_standards", "noted")]}, "only a reward-hacking"),
        ({"items": [item("RH-1", "reward_hacking", "not evaluable")]}, "never left unevaluated"),
        ({"numeric_output": {"value": 40}}, "numeric_output.unit"),
        ({"numeric_output": 40}, "numeric_output"),
        ({"verdict": "pass"}, "verdict"),
        ({"surprise": 1}, "surprise"),
    ],
    ids=[
        "n/a criterion",
        "n/a indicator",
        "n/a without evidence",
        "noted standard",
        "unevaluated indicator",
        "number without unit",
        "bare number",
        "old word",
        "extra field",
    ],
)
def test_a_malformed_answer_is_no_verdict(fields: dict[str, Any], why: str) -> None:
    outcome = _outcome(**fields)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
    assert why in outcome.detail


def test_no_answer_is_no_verdict() -> None:
    outcome = judge(None, ())
    assert isinstance(outcome, Unavailable) and outcome.cause == "no_verdict"


# -- what a verdict becomes ---------------------------------------------------------


def _result(outcome: Answered | Unavailable) -> ReviewResult:
    assert isinstance(outcome, Answered)
    return to_result(
        outcome,
        reviewer_model="claude-sonnet-5",
        session_id="s1",
        usage=(),
        rubric_sha256="a" * 64,
        rubric_kind="paired",
        packet_sha256="b" * 64,
        reading_verified=True,
        peak_context_tokens=1234,
    )


def test_accept_is_a_pass_and_reject_a_fail_whatever_the_non_blocking_defects() -> None:
    assert _result(_outcome(spec_defects=[NONBLOCKING])).verdict == "pass"
    assert _result(_outcome(**REJECT, spec_defects=[NONBLOCKING])).verdict == "fail"


def test_a_reject_carries_its_item_and_number_into_the_second_repair_instruction() -> None:
    result = _result(_outcome(**REJECT))
    text = repair_instruction(2, Finding.from_review(result))
    assert "Failing check: AC-1" in text and "Computed value: 40 1" in text


def test_a_review_result_cannot_hold_a_pass_beside_a_rejecting_finding_or_a_lone_block() -> None:
    accepted = _result(_outcome())
    with pytest.raises(ValueError, match="a pass carries no rejecting"):
        ReviewResult(
            **{
                **accepted.model_dump(),
                "items": (ModelVerdict.model_validate_json(json.dumps(answer(**REJECT))).items),
            }
        )
    with pytest.raises(ValueError, match="blocked, not a fail"):
        ReviewResult(
            **{
                **accepted.model_dump(),
                "verdict": "fail",
                "spec_defects": ModelVerdict.model_validate_json(
                    json.dumps(answer(spec_defects=[BLOCKING]))
                ).spec_defects,
            }
        )


def test_the_schema_offered_is_the_model_validated() -> None:
    props = VERDICT_SCHEMA["properties"]
    assert set(props) == set(ModelVerdict.model_fields) == set(VERDICT_SCHEMA["required"])
    assert props["verdict"]["enum"] == ["accept", "reject", "blocked"]
    assert props["items"]["items"]["properties"]["result"]["enum"] == [
        "met",
        "unmet",
        "noted",
        "n/a",
        "not evaluable",
    ]
