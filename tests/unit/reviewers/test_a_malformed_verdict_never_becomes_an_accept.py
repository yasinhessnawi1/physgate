"""Fail closed: no malformed, partial or inconsistent answer ever becomes an accept.

The reviewer's structured answer is untrusted model output. Every input below
lands on the invalid path, including a failure inside validation itself. The
table is deliberately broad: what matters is that not one row reaches ``accept``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from physgate.reviewers import verdict as verdicts
from physgate.reviewers.rubric import RubricItem
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict import Answered, Unavailable, judge

HIT = ScanHit(kind="disabled_checks", evidence="t2", what="a lint rule suppressed")
RUBRIC = (RubricItem(id="AC-1", section="acceptance_criteria", title="t"),)


def good() -> dict[str, Any]:
    return {
        "verdict": "accept",
        "finding": "every item is met",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": [
            {"item": "AC-1", "section": "acceptance_criteria", "result": "met", "evidence": "x:1"}
        ],
        "indicators": [
            {"kind": "disabled_checks", "evidence": "t2", "disposition": "dismissed", "reason": "r"}
        ],
        "spec_defects": [],
    }


def _with(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {**good(), **fields}


def _without(name: str) -> dict[str, Any]:
    answer = good()
    del answer[name]
    return answer


def _nested(depth: int) -> object:
    value: object = "x"
    for _ in range(depth):
        value = [value]
    return value


ITEM = good()["items"][0]
MALFORMED: list[tuple[str, object]] = [
    ("a list at the top", [good()]),
    ("a string at the top", json.dumps(good())),
    ("a number at the top", 1),
    ("true at the top", True),
    ("an empty object", {}),
    ("verdict missing", _without("verdict")),
    ("items missing", _without("items")),
    ("indicators missing", _without("indicators")),
    ("spec_defects missing", _without("spec_defects")),
    ("an extra key", _with(approved=True)),
    ("an unknown verdict", _with(verdict="approve")),
    ("the old word", _with(verdict="pass")),
    ("verdict null", _with(verdict=None)),
    ("verdict a list", _with(verdict=["accept"])),
    ("finding empty", _with(finding="")),
    ("finding a number", _with(finding=3)),
    ("items null", _with(items=None)),
    ("an item null", _with(items=[None])),
    ("an item with an extra key", _with(items=[{**ITEM, "ok": True}])),
    ("an unknown section", _with(items=[{**ITEM, "section": "style"}])),
    ("an unknown result", _with(items=[{**ITEM, "result": "fine"}])),
    ("n/a on a criterion", _with(items=[{**ITEM, "result": "n/a"}])),
    (
        "n/a with empty evidence",
        _with(items=[{**ITEM, "section": "domain_standards", "result": "n/a", "evidence": ""}]),
    ),
    ("unmet beside accept", _with(items=[{**ITEM, "result": "unmet"}])),
    (
        "a confirmed indicator beside accept",
        _with(indicators=[{**good()["indicators"][0], "disposition": "confirmed"}]),
    ),
    (
        "a blocking defect beside accept",
        _with(spec_defects=[{"finding": "f", "blocking": True, "item": None}]),
    ),
    (
        "blocking as a string",
        _with(spec_defects=[{"finding": "f", "blocking": "no", "item": None}]),
    ),
    ("the scan hit unanswered", _with(indicators=[])),
    ("a model-set flag", _with(has_rejecting_finding=False)),
    ("numeric_output bare", _with(numeric_output=40)),
    ("numeric_output not finite", _with(numeric_output={"value": float("inf"), "unit": "A"})),
    ("nested beyond reading", _with(subject=_nested(100_000))),
]


@pytest.mark.parametrize("answer", [a for _, a in MALFORMED], ids=[n for n, _ in MALFORMED])
def test_every_malformed_answer_takes_the_invalid_path(answer: object) -> None:
    outcome = judge(answer, (HIT,), RUBRIC)
    assert isinstance(outcome, Unavailable), outcome
    assert outcome.cause == "invalid_verdict"


def test_the_well_formed_answer_is_an_accept_so_the_table_tests_something() -> None:
    outcome = judge(good(), (HIT,), RUBRIC)
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "accept"


def test_a_failure_inside_validation_is_no_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> str | None:
        raise RuntimeError

    monkeypatch.setattr(verdicts, "_inconsistency", broken)
    outcome = judge(good(), (HIT,), RUBRIC)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


def test_the_raw_answer_is_not_read_after_validation() -> None:
    answer = good()
    outcome = judge(answer, (HIT,), RUBRIC)
    answer["verdict"] = "reject"
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "accept"
