"""A verdict whose finding is empty or one word is refused, and the session is asked again.

Measured on a practice run: after four refusals of its structured answer, a session gave
a reject whose finding read "test", whose item evidence read "x" and whose blocking defect
read "x", and it was recorded as a fail. A placeholder is not a judgement. The check after
the session now refuses it by name, which is the cause the repair resume answers, so the
same session is resumed once and told which finding to write; a verdict given in words
passes as before. The prompt tells the session the answer's shape before its first
attempt: one object under the wrapper key, never a string holding JSON, and no one-word
finding.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_a_malformed_verdict_never_becomes_an_accept import HIT, RUBRIC, good
from test_a_refused_verdict_gets_one_repair_resume_of_the_same_session import VALID, _review

from physgate.orchestrator.protocols import ReviewResult
from physgate.reviewers.claude import SHAPE, review_prompt
from physgate.reviewers.contract import WRAPPER
from physgate.reviewers.verdict import Answered, Unavailable, judge


def _judged(answer: dict[str, Any]) -> Answered | Unavailable:
    return judge(answer, (HIT,), RUBRIC, criteria=("1",))


def _reject(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    answer = good()
    answer["verdict"] = "reject"
    answer["failing_item"] = "AC-1"
    answer["finding"] = "the stated rating is below the load it carries"
    answer["items"][0] = {**answer["items"][0], "result": "unmet", "evidence": "nodes/x.json: 2 A"}
    return {**answer, **fields}


def test_a_reject_written_out_is_a_verdict() -> None:
    judged = _judged(_reject())
    assert isinstance(judged, Answered) and judged.answer.verdict == "reject"


@pytest.mark.parametrize(
    ("answer", "named"),
    [
        (_reject(finding="test"), "the finding"),
        (_reject(finding="x"), "the finding"),
        (_reject(finding="   "), "the finding"),
        (
            _reject(items=[{**_reject()["items"][0], "evidence": "x"}]),
            "the evidence of item AC-1",
        ),
        (
            _reject(acceptance_criteria=[{"criterion": "1", "result": "unmet", "evidence": "no"}]),
            "the evidence of criterion 1",
        ),
        (
            _reject(spec_defects=[{"finding": "x", "blocking": False, "item": "AC-1"}]),
            "the defect on AC-1",
        ),
        (
            _reject(spec_defects=[{"finding": "x", "blocking": False, "item": None}]),
            "the defect on the specification",
        ),
        (
            _reject(
                indicators=[
                    {
                        "kind": "disabled_checks",
                        "evidence": "t2",
                        "disposition": "noted",
                        "reason": "r",
                    }
                ]
            ),
            "the reason of the disabled_checks indicator",
        ),
    ],
    ids=[
        "finding test",
        "finding x",
        "finding blank",
        "unmet evidence x",
        "criterion evidence one word",
        "defect x on an item",
        "defect x on the specification",
        "noted indicator reason one letter",
    ],
)
def test_an_empty_or_one_word_finding_is_refused_by_name(
    answer: dict[str, Any], named: str
) -> None:
    judged = _judged(answer)
    assert isinstance(judged, Unavailable)
    assert judged.cause == "invalid_verdict"
    assert "empty or one word" in judged.detail and named in judged.detail


def test_a_met_item_s_short_evidence_and_a_dismissed_reason_are_not_held() -> None:
    # The table's own well-formed accept: "x:1" on a met item, "r" on a dismissed indicator.
    judged = _judged(good())
    assert isinstance(judged, Answered) and judged.answer.verdict == "accept"


def test_two_words_are_the_least_a_finding_says_unless_it_is_a_pointer() -> None:
    assert isinstance(_judged(_reject(finding="rating exceeded")), Answered)
    assert isinstance(_judged(_reject(finding="exceeded")), Unavailable)
    # A file-and-line pointer is the evidence form the protocol asks for: one token, kept.
    for pointer in ("n1.json", "x:1", "design/nodes/n1.json", "nodes/x.json:12"):
        unmet = {**_reject()["items"][0], "evidence": pointer}
        assert isinstance(_judged(_reject(items=[unmet])), Answered), pointer


def test_a_one_word_finding_resumes_the_same_session_once_and_names_the_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    placeholder = copy.deepcopy(VALID)
    placeholder["finding"] = "x"
    result, spawns, _ = _review(tmp_path, monkeypatch, [(placeholder, None), (VALID, None)], 1)
    assert isinstance(result, ReviewResult) and result.verdict == "pass"
    assert result.repair_resumes == 1
    assert [s.get("resume", False) for s in spawns] == [False, True]
    assert "empty or one word" in spawns[1]["prompt"] and "the finding" in spawns[1]["prompt"]


def test_a_one_word_finding_with_resumes_off_is_no_verdict_never_a_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    placeholder = copy.deepcopy(VALID)
    placeholder["finding"] = "x"
    result, spawns, _ = _review(tmp_path, monkeypatch, [(placeholder, None)], 0)
    assert not isinstance(result, ReviewResult)
    assert "empty or one word" in str(result)
    assert len(spawns) == 1


def test_the_prompt_tells_the_shape_before_the_first_attempt() -> None:
    packet = SimpleNamespace(
        read_root="/r",
        spec_as_issued_sha256=None,
        series_parts=(),
        required_reading=("/r/rubric.md",),
        files_parts=(),
        indicators=(),
        transcript_parts=(SimpleNamespace(name="t-1"),),
        diff_parts=(SimpleNamespace(name="d-1"),),
        artefact=None,
    )
    prompt = review_prompt("control", packet)  # type: ignore[arg-type]
    assert SHAPE in prompt
    assert f"only key is `{WRAPPER}`" in SHAPE
    assert "never a string that holds JSON" in SHAPE
    assert "empty or a single word is refused" in SHAPE
