"""A revision issued with no specification answers Section 1 in exactly one line, met or unmet.

Every rubric says so: with no specification, Section 1 is one line, whether the revision
is consistent with the design it changes and with the rubric, and the missing
specification is no specification defect. So the contract a review is held to says the
same, in the schema the binary enforces in-session and in the harness's own check after:
exactly one criterion line, named ``consistency``, answered ``met`` or ``unmet``; no
``not evaluable`` anywhere in Section 1, so nothing can block for want of a
specification. A review of an attempt that does have a specification is held to the
contract as before.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from schema_subset import errors

from physgate.reviewers.contract import (
    CONSISTENCY,
    WRAPPER,
    contract_text,
    verdict_schema,
)
from physgate.reviewers.rubric import RubricItem, load_rubric, not_evaluable_needs
from physgate.reviewers.verdict import Answered, Unavailable, judge

REPO = Path(__file__).resolve().parents[3]
ROLES = ("control", "firmware", "electrical", "mechanical")


def _items(role: str) -> tuple[RubricItem, ...]:
    return load_rubric(REPO / "knowledge", role).items


def _answer(items: tuple[RubricItem, ...], line: str = "met") -> dict[str, Any]:
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    return {
        "verdict": "accept" if line == "met" else "reject",
        "finding": "the revision is consistent with the design it changes",
        "failing_item": None if line == "met" else CONSISTENCY,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "design/nodes/n1.json: the node"}
            for i in items
        },
        "acceptance_criteria": [
            {"criterion": CONSISTENCY, "result": line, "evidence": "design/nodes/n1.json"}
        ],
        "indicators": [],
        "spec_defects": [],
    }


def _both(role: str, answer: dict[str, Any]) -> tuple[list[str], Answered | Unavailable]:
    items, needs = _items(role), not_evaluable_needs(role)
    schema = verdict_schema(items, criteria=None, scan_hits=(), not_evaluable=needs, issued=False)
    found = errors({WRAPPER: answer}, schema)
    return found, judge(answer, (), items, not_evaluable=needs, issued=False)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("line", ["met", "unmet"])
def test_one_consistency_line_met_or_unmet_passes_both(role: str, line: str) -> None:
    found, outcome = _both(role, _answer(_items(role), line))
    assert found == []
    assert isinstance(outcome, Answered)
    assert [c.criterion for c in outcome.answer.acceptance_criteria] == [CONSISTENCY]


def _refused(role: str, answer: dict[str, Any]) -> None:
    found, outcome = _both(role, answer)
    assert found, "the schema let it through"
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


@pytest.mark.parametrize("role", ROLES)
def test_no_line_is_refused(role: str) -> None:
    answer = _answer(_items(role))
    answer["acceptance_criteria"] = []
    _refused(role, answer)


@pytest.mark.parametrize("role", ROLES)
def test_a_second_line_is_refused(role: str) -> None:
    answer = _answer(_items(role))
    answer["acceptance_criteria"].append(
        {"criterion": "the node is sourced", "result": "met", "evidence": "n1.json"}
    )
    _refused(role, answer)


@pytest.mark.parametrize("role", ROLES)
def test_a_line_under_another_name_is_refused(role: str) -> None:
    answer = _answer(_items(role))
    answer["acceptance_criteria"][0]["criterion"] = "the revision is right"
    _refused(role, answer)


@pytest.mark.parametrize("role", ROLES)
def test_the_line_is_never_not_evaluable(role: str) -> None:
    answer = _answer(_items(role))
    answer["verdict"] = "blocked"
    answer["acceptance_criteria"][0] = {
        "criterion": CONSISTENCY,
        "result": "not evaluable",
        "evidence": "no specification was issued",
        "defect": {"finding": "no specification was issued", "blocking": True},
    }
    _refused(role, answer)


@pytest.mark.parametrize("role", ROLES)
def test_no_section_1_item_is_not_evaluable(role: str) -> None:
    items = _items(role)
    first = next(i.id for i in items if i.section == "acceptance_criteria")
    answer = copy.deepcopy(_answer(items))
    answer["verdict"] = "blocked"
    answer["items"][first] = {"result": "not evaluable", "evidence": "no specification"}
    answer["spec_defects"] = [
        {"finding": "no specification was issued", "blocking": True, "item": first}
    ]
    _refused(role, answer)


@pytest.mark.parametrize("role", ROLES)
def test_with_a_specification_the_contract_is_unchanged(role: str) -> None:
    items, needs = _items(role), not_evaluable_needs(role)
    issued = verdict_schema(items, criteria=None, scan_hits=(), not_evaluable=needs)
    default = verdict_schema(items, criteria=None, scan_hits=(), not_evaluable=needs, issued=True)
    assert issued == default
    answer = _answer(items)
    answer["acceptance_criteria"][0]["criterion"] = "the node is written exactly as given"
    assert errors({WRAPPER: answer}, issued) == []
    assert isinstance(judge(answer, (), items, not_evaluable=needs), Answered)


@pytest.mark.parametrize("role", ROLES)
def test_the_prompt_asks_for_the_one_line_and_never_speaks_of_a_specification_s_criteria(
    role: str,
) -> None:
    items, needs = _items(role), not_evaluable_needs(role)
    text = contract_text(items, criteria=None, not_evaluable=needs, issued=False)
    assert "No specification was issued" in text
    assert f"`{CONSISTENCY}`" in text
    assert "exactly one" in text
    assert "does not number" not in text
    assert "not evaluable carries its own" not in text
