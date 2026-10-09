"""The verdict a reviewer is offered is its own rubric's, and the binary can enforce it in-session.

Built from the promoted control and firmware rubrics: every item keyed by its own id,
each with its section's results in the rubric's own words; the issued specification's
criteria on their own lines; the verdict's consistency; and each rubric's rule for an
answer that is not evaluable. Every case the schema refuses here is refused by the
harness's own check too, so the schema never lets through what the check would refuse,
and a valid verdict passes both. The two real submissions of the first real reviews
break the schema in the ways they broke the check.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from schema_subset import errors

from physgate.reviewers.contract import (
    WRAPPER,
    as_answer,
    contract_text,
    issued_criteria,
    verdict_schema,
)
from physgate.reviewers.rubric import (
    NotEvaluableNeeds,
    RubricItem,
    evaluation_words,
    generalist_of,
    load_rubric,
    not_evaluable_needs,
)
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict import Answered, Unavailable, judge

REPO = Path(__file__).resolve().parents[3]
REPLAYED = REPO / "tests" / "integration" / "orchestrator" / "replayed"
HIT = ScanHit(kind="disabled_checks", evidence="t2", what="a lint rule suppressed")
DISMISSED = {
    "kind": "disabled_checks",
    "evidence": "t2",
    "disposition": "dismissed",
    "reason": "the suppressed rule is line length in a generated table",
}
NUMBERED = (
    "# s1\n\n## Acceptance criteria\n\n1. The gain is set.\n2. Its unit is stated.\n\n"
    "## Notes\n\n3. not a criterion\n"
)


def _rubric(role: str) -> tuple[RubricItem, ...]:
    return load_rubric(REPO / "knowledge", role).items


def _first(items: tuple[RubricItem, ...], section: str) -> str:
    return next(i.id for i in items if i.section == section)


def valid(items: tuple[RubricItem, ...], criteria: tuple[str, ...] | None) -> dict[str, Any]:
    """An accept answering every item in its section's words, every criterion met."""
    clean = {
        "acceptance_criteria": "met",
        "domain_standards": "n/a",
        "antipatterns": "n/a",
        "reward_hacking": "not observed",
    }
    return {
        "verdict": "accept",
        "finding": "every item is met",
        "failing_item": None,
        "subject": None,
        "numeric_output": None,
        "items": {
            i.id: {"result": clean[i.section], "evidence": "diff.patch: the one file it adds"}
            for i in items
        },
        "acceptance_criteria": [
            {"criterion": ref, "result": "met", "evidence": "worktree: m/ctl.py:1"}
            for ref in (criteria or ("the node is written exactly as given",))
        ],
        "indicators": [DISMISSED],
        "spec_defects": [],
    }


def _schema(
    items: tuple[RubricItem, ...], criteria: tuple[str, ...] | None, needs: NotEvaluableNeeds
) -> dict[str, Any]:
    return verdict_schema(items, criteria=criteria, scan_hits=(HIT,), not_evaluable=needs)


def _both(
    answer: dict[str, Any],
    items: tuple[RubricItem, ...],
    criteria: tuple[str, ...] | None,
    needs: NotEvaluableNeeds,
) -> tuple[list[str], Answered | Unavailable]:
    found = errors({WRAPPER: answer}, _schema(items, criteria, needs))
    return found, judge(answer, (HIT,), items, criteria=criteria, not_evaluable=needs)


def test_the_issued_criteria_are_counted_only_where_the_specification_numbers_them() -> None:
    assert issued_criteria(NUMBERED) == ("1", "2")
    assert issued_criteria("STAND-IN BRIEF. Propose exactly this node.\n") is None
    assert issued_criteria("## Acceptance criteria\n\nThe gain is set.\n") is None
    assert issued_criteria(None) is None


@pytest.mark.parametrize("role", ["control", "firmware"])
@pytest.mark.parametrize("criteria", [None, ("1", "2")], ids=["uncounted", "counted"])
def test_a_valid_verdict_passes_the_schema_and_the_check(
    role: str, criteria: tuple[str, ...] | None
) -> None:
    items = _rubric(role)
    found, outcome = _both(valid(items, criteria), items, criteria, not_evaluable_needs(role))
    assert found == []
    assert isinstance(outcome, Answered) and len(outcome.answer.items) == len(items)
    assert [i.item for i in outcome.answer.items] == [i.id for i in items]  # rubric order


@pytest.mark.parametrize("role", ["control", "firmware"])
def test_the_first_real_submissions_break_the_schema_where_they_broke_the_check(
    role: str,
) -> None:
    items = _rubric(role)
    real = json.loads((REPLAYED / f"review_submission_{role}.json").read_text())
    entries = {x["item"]: {"result": x["result"], "evidence": x["evidence"]} for x in real["items"]}
    keyed = {**real, "items": entries}
    found = errors({WRAPPER: keyed}, _schema(items, None, not_evaluable_needs(role)))
    assert any(f"must have required property '{items[0].id}'" in e for e in found)
    assert any("must NOT have additional properties" in e for e in found)
    assert any("acceptance_criteria" in e for e in found)  # its criteria were items instead
    outcome = judge(real, (), items, not_evaluable=not_evaluable_needs(role))
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


def _case(
    name: str, items: tuple[RubricItem, ...], criteria: tuple[str, ...] | None
) -> dict[str, Any]:
    answer = valid(items, criteria)
    ac, ds = _first(items, "acceptance_criteria"), _first(items, "domain_standards")
    rh = _first(items, "reward_hacking")
    entries = answer["items"]
    if name == "grouped ids":
        first, second = [i.id for i in items if i.section == "domain_standards"][:2]
        entries[f"{first}/{second}"] = entries.pop(first)
        del entries[second]
    elif name == "an unknown id":
        entries["X-99"] = {"result": "met", "evidence": "e"}
    elif name == "a missing id":
        del entries[ds]
    elif name == "n/a on a reward-hacking item":
        entries[rh] = {"result": "n/a", "evidence": "e"}
    elif name == "noted on a standard":
        entries[ds] = {"result": "noted", "evidence": "e"}
    elif name == "met on a reward-hacking item":
        entries[rh] = {"result": "met", "evidence": "e"}
    elif name == "accept beside an unmet item":
        entries[ac] = {"result": "unmet", "evidence": "e"}
    elif name == "accept beside a confirmed indicator item":
        entries[rh] = {"result": "confirmed", "evidence": "e"}
    elif name == "accept beside an unmet criterion":
        answer["acceptance_criteria"][0]["result"] = "unmet"
    elif name == "reject naming no failing item":
        answer["verdict"] = "reject"
        entries[ac] = {"result": "unmet", "evidence": "e"}
    elif name == "reject with nothing rejecting":
        answer["verdict"], answer["failing_item"] = "reject", ac
    elif name == "blocked with no blocking defect":
        answer["verdict"] = "blocked"
    elif name == "accept beside a blocking defect":
        answer["spec_defects"] = [{"finding": "f", "blocking": True, "item": ds}]
    elif name == "a scan hit unanswered":
        answer["indicators"] = []
    elif name == "no criterion line":
        answer["acceptance_criteria"] = []
    elif name == "a criterion left out":
        answer["acceptance_criteria"] = answer["acceptance_criteria"][:1]
    elif name == "a criterion answered twice":
        answer["acceptance_criteria"] = [answer["acceptance_criteria"][0]] * 2
    elif name == "not evaluable with no defect":
        entries[ds] = {"result": "not evaluable", "evidence": "the spec gives no pole"}
    return answer


CASES = [
    "grouped ids",
    "an unknown id",
    "a missing id",
    "n/a on a reward-hacking item",
    "noted on a standard",
    "met on a reward-hacking item",
    "accept beside an unmet item",
    "accept beside a confirmed indicator item",
    "accept beside an unmet criterion",
    "reject naming no failing item",
    "reject with nothing rejecting",
    "blocked with no blocking defect",
    "accept beside a blocking defect",
    "a scan hit unanswered",
    "no criterion line",
    "not evaluable with no defect",
]


@pytest.mark.parametrize("role", ["control", "firmware"])
@pytest.mark.parametrize("name", CASES)
def test_each_breach_is_refused_by_the_schema_and_by_the_check(role: str, name: str) -> None:
    items = _rubric(role)
    needs = not_evaluable_needs(role)
    found, outcome = _both(_case(name, items, None), items, None, needs)
    assert found, f"the schema let through: {name}"
    assert isinstance(outcome, Unavailable) and outcome.cause in ("invalid_verdict",), name


@pytest.mark.parametrize("name", ["a criterion left out", "a criterion answered twice"])
def test_a_numbered_specification_s_criteria_are_answered_exactly(name: str) -> None:
    items, criteria = _rubric("firmware"), ("1", "2")
    found, outcome = _both(_case(name, items, criteria), items, criteria, "blocking")
    assert found
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


def _not_evaluable(role: str, *, blocking: bool) -> dict[str, Any]:
    items = _rubric(role)
    answer = valid(items, None)
    criterion = answer["acceptance_criteria"][0]
    criterion["result"] = "not evaluable"
    criterion["defect"] = {
        "finding": "the issued specification gives no settling time",
        "blocking": blocking,
    }
    if blocking:
        answer["verdict"] = "blocked"
    return answer


def test_control_follows_its_rubric_a_non_blocking_defect_names_an_unevaluable_criterion() -> None:
    items = _rubric("control")
    answer = _not_evaluable("control", blocking=False)
    found, outcome = _both(answer, items, None, "defect")
    assert found == []
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "accept"
    # The line's own defect is counted as a specification defect, and kept.
    (defect,) = outcome.answer.spec_defects
    assert defect.blocking is False and defect.item == answer["acceptance_criteria"][0]["criterion"]


def test_control_s_reviewer_may_judge_it_safety_critical_and_block() -> None:
    items = _rubric("control")
    found, outcome = _both(_not_evaluable("control", blocking=True), items, None, "defect")
    assert found == []
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "blocked"


def test_firmware_follows_its_rubric_an_unevaluable_criterion_needs_a_blocking_defect() -> None:
    items = _rubric("firmware")
    _, outcome = _both(_not_evaluable("firmware", blocking=False), items, None, "blocking")
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
    assert "blocking defect" in outcome.detail
    _, blocked = _both(_not_evaluable("firmware", blocking=True), items, None, "blocking")
    assert isinstance(blocked, Answered) and blocked.answer.verdict == "blocked"


def test_an_unevaluable_rubric_item_takes_the_same_rule_and_the_schema_says_so() -> None:
    for role, needs in (("control", "defect"), ("firmware", "blocking")):
        items = _rubric(role)
        answer = valid(items, None)
        ds = _first(items, "domain_standards")
        answer["items"][ds] = {"result": "not evaluable", "evidence": "the spec gives no pole"}
        answer["spec_defects"] = [{"finding": "no pole given", "blocking": False, "item": ds}]
        found, outcome = _both(answer, items, None, needs)  # type: ignore[arg-type]
        assert bool(found) == (needs == "blocking"), role
        assert isinstance(outcome, Answered) == (needs == "defect"), role


def test_a_confirmed_reward_hacking_item_rejects() -> None:
    items = _rubric("firmware")
    answer = valid(items, None)
    rh = _first(items, "reward_hacking")
    answer["items"][rh] = {"result": "confirmed", "evidence": "transcript: the assert removed"}
    answer["verdict"], answer["failing_item"], answer["finding"] = "reject", rh, "a check removed"
    found, outcome = _both(answer, items, None, "blocking")
    assert found == []
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "reject"


def test_a_generalist_is_held_to_its_own_two_sections() -> None:
    rubric = generalist_of(load_rubric(REPO / "knowledge", "control"))
    schema = _schema(rubric.items, None, "defect")
    sections = {i.section for i in rubric.items}
    assert sections == {"acceptance_criteria", "reward_hacking"}
    verdict = schema["properties"][WRAPPER]
    assert set(verdict["properties"]["items"]["required"]) == {i.id for i in rubric.items}
    found, outcome = _both(valid(rubric.items, None), rubric.items, None, "defect")
    assert found == [] and isinstance(outcome, Answered)


def test_the_contract_the_prompt_states_says_nothing_it_must_not() -> None:
    for role in ("control", "firmware"):
        items = _rubric(role)
        for criteria in (None, ("1", "2")):
            text = contract_text(items, criteria=criteria, not_evaluable=not_evaluable_needs(role))
            assert evaluation_words(text) == []
            assert items[0].id in text and "never grouped" in text


def test_the_prompt_says_the_verdict_is_an_object_never_a_string_of_json() -> None:
    items = _rubric("control")
    text = contract_text(items, criteria=None, not_evaluable=not_evaluable_needs("control"))
    assert f"`{WRAPPER}` is an object, never a string holding JSON" in text


def test_a_verdict_sent_as_a_string_of_json_is_never_read_as_a_verdict() -> None:
    items = _rubric("control")
    answer = valid(items, None)
    for sent in (json.dumps(answer), json.dumps(answer) + "}"):
        assert errors({WRAPPER: sent}, _schema(items, None, "blocking")) != []
        passed_on = as_answer({WRAPPER: sent}, items)
        assert passed_on == sent
        outcome = judge(passed_on, (HIT,), items, criteria=None, not_evaluable="blocking")
        assert isinstance(outcome, Unavailable)


def test_a_submission_in_any_other_shape_is_passed_on_for_the_check_to_refuse() -> None:
    assert as_answer(None, ()) is None
    odd = {"items": {"A1": "met"}}
    assert as_answer(copy.deepcopy(odd), _rubric("control")) == odd


def test_a_numbered_criterion_not_evaluable_carries_its_own_defect_in_the_schema_too() -> None:
    items, criteria = _rubric("firmware"), ("1", "2")
    answer = valid(items, criteria)
    answer["acceptance_criteria"][1]["result"] = "not evaluable"
    found, outcome = _both(answer, items, criteria, "blocking")
    assert found and isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
    answer["acceptance_criteria"][1]["defect"] = {"finding": "no settling time", "blocking": True}
    answer["verdict"] = "blocked"
    found, outcome = _both(answer, items, criteria, "blocking")
    assert found == []
    assert isinstance(outcome, Answered) and outcome.answer.verdict == "blocked"
    assert outcome.answer.spec_defects[0].item == "2"


def test_each_role_takes_its_own_rubric_s_rule_and_a_role_with_none_the_stricter() -> None:
    assert not_evaluable_needs("control") == "defect"  # control rubric, rules 3 and 7
    assert not_evaluable_needs("firmware") == "blocking"  # firmware rubric, verdict policy
    assert not_evaluable_needs("electrical") == "blocking"


def test_a_numbered_specification_s_criteria_are_not_answered_more_than_once_each() -> None:
    items, criteria = _rubric("firmware"), ("1", "2")
    answer = valid(items, criteria)
    answer["acceptance_criteria"].append(dict(answer["acceptance_criteria"][1]))
    found, outcome = _both(answer, items, criteria, "blocking")
    assert any("more than 2" in e for e in found)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


def test_blocked_needs_a_blocking_defect_not_any_defect() -> None:
    items = _rubric("control")
    answer = valid(items, None)
    answer["verdict"] = "blocked"
    answer["spec_defects"] = [{"finding": "a note", "blocking": False, "item": None}]
    found, outcome = _both(answer, items, None, "defect")
    assert any("must contain" in e or "anyOf" in e for e in found)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


_OBJECT = ("properties", "required", "additionalProperties")
_ARRAY = ("items", "contains", "minItems", "maxItems")


def _untyped(schema: object, where: str = "#") -> list[str]:
    """Every subschema using an object or array keyword without its type (strict mode warns)."""
    if isinstance(schema, list):
        return [f for i, part in enumerate(schema) for f in _untyped(part, f"{where}/{i}")]
    if not isinstance(schema, dict):
        return []
    found = []
    if any(k in schema for k in _OBJECT) and schema.get("type") != "object":
        found.append(f"{where}: object keyword without type object")
    if any(k in schema for k in _ARRAY) and schema.get("type") != "array":
        found.append(f"{where}: array keyword without type array")
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            found += [f for k, v in value.items() for f in _untyped(v, f"{where}/properties/{k}")]
        elif key not in ("enum", "const", "required") and isinstance(value, dict | list):
            found += _untyped(value, f"{where}/{key}")
    return found


@pytest.mark.parametrize("role", ["control", "firmware"])
@pytest.mark.parametrize("criteria", [None, ("1", "2")], ids=["uncounted", "counted"])
def test_the_schema_has_no_combinator_at_its_top_and_types_every_subschema(
    role: str, criteria: tuple[str, ...] | None
) -> None:
    items = _rubric(role)
    hits = (HIT,)
    schema = verdict_schema(
        items, criteria=criteria, scan_hits=hits, not_evaluable=not_evaluable_needs(role)
    )
    assert not {"oneOf", "allOf", "anyOf"} & set(schema)  # what the API refuses
    assert schema["type"] == "object" and schema["required"] == [WRAPPER]
    assert _untyped(schema) == []  # what the binary's strict mode warns of


def test_a_submission_is_read_from_inside_its_wrapper() -> None:
    items = _rubric("control")
    answer = valid(items, None)
    outcome = judge({WRAPPER: answer}, (HIT,), items, not_evaluable="defect")
    assert isinstance(outcome, Answered)
    two = judge({WRAPPER: answer, "extra": 1}, (HIT,), items, not_evaluable="defect")
    assert isinstance(two, Unavailable)  # anything else beside it is not a verdict


@pytest.mark.parametrize(("role", "needs"), [("control", "defect"), ("firmware", "blocking")])
def test_a_criterion_not_evaluable_without_its_own_defect_is_refused(
    role: str, needs: NotEvaluableNeeds
) -> None:
    items = _rubric(role)
    answer = valid(items, None)
    answer["acceptance_criteria"][0]["result"] = "not evaluable"
    found, outcome = _both(answer, items, None, needs)
    assert any("defect" in e for e in found)
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
    # A spec_defects entry naming it does not stand in for the line's own.
    answer["spec_defects"] = [{"finding": "f", "blocking": True, "item": "x"}]
    answer["verdict"] = "blocked"
    found, outcome = _both(answer, items, None, needs)
    assert found and isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"


def test_firmware_s_criterion_defect_must_block() -> None:
    items = _rubric("firmware")
    found, outcome = _both(_not_evaluable("firmware", blocking=False), items, None, "blocking")
    assert any("blocking" in e for e in found)
    assert isinstance(outcome, Unavailable) and "blocking defect" in outcome.detail


def test_an_accept_carries_no_line_defect_that_blocks() -> None:
    items = _rubric("control")
    answer = _not_evaluable("control", blocking=True)
    answer["verdict"] = "accept"
    found, outcome = _both(answer, items, None, "defect")
    assert found
    assert isinstance(outcome, Unavailable) and outcome.cause == "invalid_verdict"
