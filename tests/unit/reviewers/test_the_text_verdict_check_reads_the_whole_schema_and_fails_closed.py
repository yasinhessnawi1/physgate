"""The check a verdict sent as text is held to: the contract's own schema, read whole, closed.

A text the binary refused only for being one is read as the object it holds and held to the very
schema the session was given. The check that does it knows the keywords the contract uses and no
other: a schema with one it does not know, anywhere, even in a branch the value never takes, is
refused, so nothing is passed for want of reading a clause. It agrees with the tests' own reading
of the schema on every breach the contract's rows name, and on the valid verdict. Only the
session's last try is read, and only where the binary's whole refusal was the form.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from schema_subset import errors
from test_a_verdict_sent_as_text_is_a_verdict_only_when_it_holds_to_the_schema import REPO
from test_the_verdict_contract_is_the_rubric_s_own import CASES, HIT, _case, _rubric, valid

from physgate.reviewers.contract import WRAPPER, verdict_schema
from physgate.reviewers.rubric import generalist_of, load_rubric, not_evaluable_needs
from physgate.reviewers.scan import ScanHit
from physgate.reviewers.verdict_text import (
    FORM_REFUSAL,
    last_text_verdict,
    parse_verdict_text,
    same,
    schema_errors,
    unreadable,
)

EARLIER = ScanHit(kind="feature_isolation", evidence="t9", what="a flag set", attempt=1)


@pytest.mark.parametrize("role", ["control", "firmware", "electrical", "integration", "design"])
@pytest.mark.parametrize("issued", [True, False], ids=["issued", "unissued"])
@pytest.mark.parametrize("hits", [(), (HIT,), (HIT, EARLIER)], ids=["none", "own", "earlier"])
def test_every_schema_the_contract_builds_is_one_the_check_reads_whole(
    role: str, issued: bool, hits: tuple[ScanHit, ...]
) -> None:
    rubric = load_rubric(REPO / "knowledge", role)
    for items in (rubric.items, generalist_of(rubric).items):
        schema = verdict_schema(
            items,
            criteria=("1", "2") if issued else None,
            scan_hits=hits,
            not_evaluable=not_evaluable_needs(role),
            issued=issued,
        )
        assert unreadable(schema) == []


@pytest.mark.parametrize("role", ["control", "firmware"])
@pytest.mark.parametrize("name", ["valid", *CASES])
def test_the_check_agrees_with_the_schema_s_reading_on_every_named_breach(
    role: str, name: str
) -> None:
    items = _rubric(role)
    answer = valid(items, None) if name == "valid" else _case(name, items, None)
    schema = verdict_schema(
        items, criteria=None, scan_hits=(HIT,), not_evaluable=not_evaluable_needs(role)
    )
    ours = schema_errors({WRAPPER: answer}, schema)
    assert bool(ours) == bool(errors({WRAPPER: answer}, schema)), (name, ours)
    assert bool(ours) == (name != "valid")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "format": "date"},
        {"type": "object", "if": {"required": ["x"]}, "then": {"oneOf": []}},
        {"type": "object", "additionalProperties": True},
        {"type": "object", "properties": {"a": {"type": "string", "maxLength": 3}}},
        {"type": "array", "items": [{"type": "string"}]},
    ],
    ids=["unknown-keyword", "unknown-in-an-untaken-branch", "open-object", "nested", "tuple-items"],
)
def test_a_schema_with_a_clause_the_check_does_not_know_passes_nothing(
    schema: dict[str, Any],
) -> None:
    assert unreadable(schema) != []
    sent = json.dumps({"verdict": "accept"}) + "}"
    told = last_text_verdict(
        _stream(sent, FORM_REFUSAL), {"type": "object", "properties": {WRAPPER: schema}}
    )
    assert told is not None and told.answer is None
    assert told.refused is not None and "does not know" in told.refused


def test_json_equality_holds_a_boolean_apart_from_a_number() -> None:
    assert not same(True, 1) and not same(0, False) and same(1, 1.0)
    assert schema_errors(1, {"const": True}) != []
    assert schema_errors(True, {"enum": [1]}) != []
    assert schema_errors(2.0, {"type": "integer", "minimum": 1}) == []
    assert schema_errors(0, {"type": "integer", "minimum": 1}) != []
    assert schema_errors(True, {"type": "number"}) != []


def test_each_keyword_the_contract_uses_refuses_what_it_should() -> None:
    assert schema_errors(" ", {"type": "string", "pattern": "\\S"}) != []
    assert schema_errors("a reason", {"type": "string", "pattern": "\\S"}) == []
    assert schema_errors([], {"type": "array", "contains": {"const": 1}}) != []
    assert schema_errors([2, 1], {"type": "array", "contains": {"const": 1}}) == []
    assert schema_errors([1, 2], {"type": "array", "maxItems": 1}) != []
    assert schema_errors([], {"type": "array", "minItems": 1}) != []
    assert schema_errors("", {"type": "string", "minLength": 1}) != []
    assert schema_errors({"a": 1}, {"type": "object", "not": {"required": ["a"]}}) != []
    assert schema_errors(None, {"anyOf": [{"type": "string"}, {"type": "object"}]}) != []
    branch = {"if": {"const": 1}, "then": {"const": 1}, "else": {"const": 2}}
    assert schema_errors(3, branch) != [] and schema_errors(2, branch) == []
    assert schema_errors({"b": 1}, {"type": "object", "additionalProperties": False}) != []


def _stream(review: object, refusal: str, *more: dict[str, Any]) -> str:
    events = [
        {
            "type": "assistant",
            "message": {
                "model": "m",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "v1",
                        "name": "StructuredOutput",
                        "input": {WRAPPER: review},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "v1",
                        "is_error": True,
                        "content": [{"type": "text", "text": refusal}],
                    }
                ]
            },
        },
        *more,
    ]
    return "".join(json.dumps(e) + "\n" for e in events)


OPEN = {"type": "object", "properties": {WRAPPER: {"type": "object"}}}


def test_a_try_refused_for_more_than_its_form_or_for_anything_else_is_not_read() -> None:
    text = json.dumps({"verdict": "accept"}) + "}"
    assert last_text_verdict(_stream(text, FORM_REFUSAL), OPEN) is not None
    for refusal in (
        FORM_REFUSAL + ", /review/items: must have required property 'A1'",
        "PreToolUse:StructuredOutput hook error: Required reading is not complete.",
        "Structured output provided successfully",
    ):
        assert last_text_verdict(_stream(text, refusal), OPEN) is None
    assert last_text_verdict(_stream({"verdict": "accept"}, FORM_REFUSAL), OPEN) is None
    assert last_text_verdict("", OPEN) is None


def test_a_try_the_binary_never_answered_is_not_read() -> None:
    text = json.dumps({"verdict": "accept"}) + "}"
    lines = _stream(text, FORM_REFUSAL).splitlines()
    assert last_text_verdict(lines[0] + "\n", OPEN) is None


def test_the_measured_form_parses_and_nothing_wider_does() -> None:
    body = {"verdict": "accept", "n": 1.5}
    for text in (
        json.dumps(body) + "}",
        "\n" + json.dumps(body, indent=2) + "\n}\n",
        json.dumps(body),
    ):
        assert parse_verdict_text(text) == body
    for text in (
        json.dumps(body) + "}}",
        json.dumps(body) + "]",
        "x" + json.dumps(body),
        json.dumps(body) + " trailing words",
        json.dumps(body).replace("1.5", "Infinity"),
        json.dumps(body).replace("1.5", "-Infinity"),
        "[" + json.dumps(body) + "]",
    ):
        assert isinstance(parse_verdict_text(text), str), text
