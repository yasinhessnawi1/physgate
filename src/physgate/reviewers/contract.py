"""The answer contract a reviewer is held to, as the binary's own schema check enforces it.

The first real reviews read everything, then answered with a verdict the binary
accepted at once: the schema it was given said nothing about which items there are or
what each section allows. The harness's check then refused each verdict after the
session had ended, where the reviewer could neither see why nor try again.

So the schema a review is offered is generated from its own rubric
(:func:`verdict_schema`). A submission that breaks it is refused by the binary inside
the session, with the reasons, and the reviewer submits again. The verdict is the one
property of the submission (``review``): the API refuses a tool schema with ``allOf``,
``anyOf`` or ``oneOf`` at its top level, and the verdict's rules relate its fields to one
another, so they apply to the verdict, one level down. Every subschema states its type.
It holds:

- ``items``: one entry per rubric item, keyed by the item's own id, every id required and
  no other key allowed, each answered only with a result its section allows
  (``SECTION_RESULTS``) and the evidence;
- ``acceptance_criteria``: one line per acceptance criterion of the issued
  specification, apart from the rubric's items, each with its own reference. When the
  issued specification numbers its criteria under an acceptance-criteria heading
  (:func:`issued_criteria`), exactly those, each once; otherwise at least one;
- ``indicators``: one naming each check the trajectory shows switched off;
- the verdict's own consistency: an accept or a blocked carries no rejecting answer and
  no failing item, an accept no blocking defect and a blocked at least one; a reject
  names its failing item and has a rejecting answer;
- every ``not evaluable`` rubric item named by a specification defect, and every
  ``not evaluable`` criterion line carrying its own (``defect``: what the issued
  specification lacks, and whether it blocks), blocking where the role's rubric
  requires it (``rubric.not_evaluable_needs``); a line's own defect is a specification
  defect like any other, and an accept carries none that blocks.

The harness's own check (``verdict.judge``) stays the last word, unchanged in what it
refuses: the schema only lets the reviewer learn of a refusal while it can still act.
"""

from __future__ import annotations

import re
from typing import Any

from physgate.orchestrator.protocols import REJECTING_RESULTS, SECTION_RESULTS
from physgate.reviewers.rubric import NotEvaluableNeeds, RubricItem
from physgate.reviewers.scan import ScanHit

_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_NUMBERED = re.compile(r"^\s*(?P<ref>\d+)[.)]\s+\S")
CRITERION_RESULTS = ("met", "unmet", "not evaluable")
#: The one property a submission has: the verdict, whose rules cannot sit at the top.
WRAPPER = "review"


def issued_criteria(spec: str | None) -> tuple[str, ...] | None:
    """The issued specification's acceptance criteria, by number, if it numbers them.

    Read from the numbered lines under a heading that names acceptance criteria, up to
    the next heading. ``None`` when there is no specification, no such heading, or no
    numbered line beneath it: the criteria are then not countable by machine.
    """
    if spec is None:
        return None
    refs: list[str] = []
    inside = False
    for line in spec.splitlines():
        heading = _HEADING.match(line)
        if heading:
            inside = "acceptance criteria" in heading["title"].casefold()
            continue
        numbered = _NUMBERED.match(line) if inside else None
        if numbered and numbered["ref"] not in refs:
            refs.append(numbered["ref"])
    return tuple(refs) or None


def _string(**more: Any) -> dict[str, Any]:  # noqa: ANN401 - a schema fragment's own values
    return {"type": "string", **more}


_confirmed = {"const": "confirmed"}
_not_confirmed = {"not": _confirmed}
_not_blocking = {"properties": {"blocking": {"const": False}}}
#: A criterion line whose own defect blocks.
_blocks = {"properties": {"blocking": {"const": True}}, "required": ["blocking"]}
_inline_block = {"properties": {"defect": _blocks}, "required": ["defect"]}
#: A criterion line whose own defect, if it has one, does not block.
_no_inline_block = {"properties": {"defect": _not_blocking}}


def _items_where(ids: list[str], result: dict[str, Any]) -> dict[str, Any]:
    """Every item's result held to ``result``."""
    return {
        "properties": {
            "items": {
                "properties": {i: {"properties": {"result": result}} for i in ids},
            }
        }
    }


def _no_rejecting_answer(ids: list[str]) -> dict[str, Any]:
    """No item rejecting, no criterion unmet, no indicator confirmed, and no failing item."""
    no_reject = _items_where(ids, {"not": {"enum": sorted(REJECTING_RESULTS)}})
    no_reject["properties"].update(
        {
            "failing_item": {"type": "null"},
            "acceptance_criteria": {
                "items": {"properties": {"result": {"not": {"const": "unmet"}}}}
            },
            "indicators": {"items": {"properties": {"disposition": _not_confirmed}}},
        }
    )
    return no_reject


def _defect_naming(ref: str, needs: NotEvaluableNeeds) -> dict[str, Any]:
    named: dict[str, Any] = {"properties": {"item": {"const": ref}}, "required": ["item"]}
    if needs == "blocking":
        named["properties"]["blocking"] = {"const": True}
    return {"properties": {"spec_defects": {"contains": named}}, "required": ["spec_defects"]}


def verdict_schema(
    items: tuple[RubricItem, ...],
    *,
    criteria: tuple[str, ...] | None,
    scan_hits: tuple[ScanHit, ...],
    not_evaluable: NotEvaluableNeeds,
) -> dict[str, Any]:
    """The schema a review of a rubric with ``items`` answers to; see the module."""
    ids = [i.id for i in items]
    criterion_ref = _string(enum=list(criteria)) if criteria else _string(minLength=1)
    # A line that is not evaluable carries its own specification defect: what the issued
    # specification lacks, and whether it blocks, as the role's rubric decides that.
    inline_defect = {
        "type": "object",
        "additionalProperties": False,
        "required": ["finding", "blocking"],
        "properties": {
            "finding": _string(minLength=1),
            "blocking": {"const": True} if not_evaluable == "blocking" else {"type": "boolean"},
        },
    }
    criteria_list: dict[str, Any] = {
        "type": "array",
        "minItems": len(criteria) if criteria else 1,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["criterion", "result", "evidence"],
            "properties": {
                "criterion": criterion_ref,
                "result": _string(enum=list(CRITERION_RESULTS)),
                "evidence": _string(minLength=1),
                "defect": inline_defect,
            },
            "if": {
                "properties": {"result": {"const": "not evaluable"}},
                "required": ["result"],
            },
            "then": {"required": ["defect"]},
        },
    }
    if criteria:
        criteria_list["maxItems"] = len(criteria)
        criteria_list["allOf"] = [
            {"contains": {"properties": {"criterion": {"const": ref}}, "required": ["criterion"]}}
            for ref in criteria
        ]
    indicators: dict[str, Any] = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "evidence", "disposition", "reason"],
            "properties": {
                "kind": _string(enum=["feature_isolation", "hard_coded_values", "disabled_checks"]),
                "evidence": _string(minLength=1),
                "disposition": _string(enum=["confirmed", "noted", "dismissed"]),
                "reason": _string(minLength=1),
            },
        },
    }
    if scan_hits:
        indicators["allOf"] = [
            {"contains": {"properties": {"evidence": {"const": hit.evidence}}}} for hit in scan_hits
        ]
    # A countable specification's criteria are named by number; otherwise a reject's
    # failing criterion is named in the reviewer's words, and the check after reads it.
    failing_one = _string(enum=[*ids, *criteria]) if criteria else _string(minLength=1)
    rejecting_somewhere = {
        "anyOf": [
            *(
                _items_where([i], {"enum": sorted(REJECTING_RESULTS)}) | {"required": ["items"]}
                for i in ids
            ),
            {
                "properties": {
                    "acceptance_criteria": {
                        "contains": {"properties": {"result": {"const": "unmet"}}}
                    }
                }
            },
            {
                "properties": {
                    "indicators": {"contains": {"properties": {"disposition": _confirmed}}}
                }
            },
        ]
    }
    rules: list[dict[str, Any]] = [
        {
            "if": {"properties": {"verdict": {"const": "accept"}}, "required": ["verdict"]},
            "then": {
                "allOf": [
                    _no_rejecting_answer(ids),
                    {"properties": {"spec_defects": {"items": _not_blocking}}},
                    {"properties": {"acceptance_criteria": {"items": _no_inline_block}}},
                ]
            },
        },
        {
            "if": {"properties": {"verdict": {"const": "blocked"}}, "required": ["verdict"]},
            "then": {
                "allOf": [
                    _no_rejecting_answer(ids),
                    {
                        "anyOf": [
                            {
                                "properties": {
                                    "spec_defects": {
                                        "contains": {"properties": {"blocking": {"const": True}}}
                                    }
                                }
                            },
                            {"properties": {"acceptance_criteria": {"contains": _inline_block}}},
                        ]
                    },
                ]
            },
        },
        {
            "if": {"properties": {"verdict": {"const": "reject"}}, "required": ["verdict"]},
            "then": {"allOf": [{"properties": {"failing_item": failing_one}}, rejecting_somewhere]},
        },
    ]
    for item in items:
        if "not evaluable" not in SECTION_RESULTS[item.section]:
            continue
        rules.append(
            {
                "if": {
                    "properties": {
                        "items": {
                            "properties": {
                                item.id: {"properties": {"result": {"const": "not evaluable"}}}
                            }
                        }
                    }
                },
                "then": _defect_naming(item.id, not_evaluable),
            }
        )
    inner = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "verdict",
            "finding",
            "failing_item",
            "subject",
            "numeric_output",
            "items",
            "acceptance_criteria",
            "indicators",
            "spec_defects",
        ],
        "properties": {
            "verdict": _string(enum=["accept", "reject", "blocked"]),
            "finding": _string(minLength=1),
            "failing_item": {"anyOf": [{"type": "null"}, _string(minLength=1)]},
            "subject": {"anyOf": [{"type": "null"}, _string(minLength=1)]},
            "numeric_output": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["value", "unit"],
                        "properties": {"value": {"type": "number"}, "unit": _string(minLength=1)},
                    },
                ]
            },
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ids,
                "properties": {
                    item.id: {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["result", "evidence"],
                        "properties": {
                            "result": _string(enum=list(SECTION_RESULTS[item.section])),
                            "evidence": _string(minLength=1),
                        },
                    }
                    for item in items
                },
            },
            "acceptance_criteria": criteria_list,
            "indicators": indicators,
            "spec_defects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["finding", "blocking", "item"],
                    "properties": {
                        "finding": _string(minLength=1),
                        "blocking": {"type": "boolean"},
                        "item": {"anyOf": [{"type": "null"}, _string(minLength=1)]},
                    },
                },
            },
        },
        "allOf": rules,
    }
    # The API refuses a tool input schema with oneOf, allOf or anyOf at its top level
    # (measured: a 400 on the first request of every review). The verdict's own rules
    # relate its fields to one another, so they sit on the verdict, one level down.
    return _typed(
        {
            "type": "object",
            "additionalProperties": False,
            "required": [WRAPPER],
            "properties": {WRAPPER: inner},
        }
    )


_OBJECT_KEYWORDS = ("properties", "required", "additionalProperties")
_ARRAY_KEYWORDS = ("items", "contains", "minItems", "maxItems")
_SUBSCHEMA_LISTS = ("allOf", "anyOf", "oneOf")
_SUBSCHEMAS = ("items", "contains", "not", "if", "then", "else")


def _typed(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with every subschema that uses an object or array keyword typed as such.

    The binary compiles the schema in strict mode and warns of each subschema that uses
    such a keyword without its type (measured: hundreds of warnings on every review).
    Every such subschema here constrains a value that is an object or an array anyway,
    so stating the type changes nothing it accepts.
    """
    typed = dict(schema)
    if "type" not in typed:
        if any(k in typed for k in _OBJECT_KEYWORDS):
            typed["type"] = "object"
        elif any(k in typed for k in _ARRAY_KEYWORDS):
            typed["type"] = "array"
    if isinstance(typed.get("properties"), dict):
        typed["properties"] = {k: _typed(v) for k, v in typed["properties"].items()}
    for key in _SUBSCHEMAS:
        if isinstance(typed.get(key), dict):
            typed[key] = _typed(typed[key])
    for key in _SUBSCHEMA_LISTS:
        if isinstance(typed.get(key), list):
            typed[key] = [_typed(part) for part in typed[key]]
    return typed


def as_answer(structured: object, items: tuple[RubricItem, ...]) -> object:
    """The submission in the form the verdict check reads: items as a list, in rubric order.

    A key the rubric does not have is kept, with no section, so the check refuses it; a
    submission not in this shape is returned as it is, for the check to refuse.
    """
    if isinstance(structured, dict) and set(structured) == {WRAPPER}:
        structured = structured[WRAPPER]
    if not isinstance(structured, dict) or not isinstance(structured.get("items"), dict):
        return structured
    given: dict[str, Any] = structured["items"]
    sections = {i.id: i.section for i in items}
    order = [i.id for i in items if i.id in given] + [k for k in given if k not in sections]
    listed = []
    for key in order:
        entry = given[key]
        if not isinstance(entry, dict):
            return structured
        listed.append({"item": key, "section": sections.get(key, "unknown"), **entry})
    return {**structured, "items": listed}


def contract_text(
    items: tuple[RubricItem, ...],
    *,
    criteria: tuple[str, ...] | None,
    not_evaluable: NotEvaluableNeeds,
) -> str:
    """What the prompt says of the contract the schema holds the verdict to."""
    counted = (
        f"The issued specification numbers {len(criteria)} acceptance criteria "
        f"({', '.join(criteria)}): give one line for each, by its number."
        if criteria
        else "The issued specification does not number its acceptance criteria: give one line "
        "for each criterion it states, by its own words, at least one."
    )
    blocking = (
        "true: your rubric makes it blocking"
        if not_evaluable == "blocking"
        else "true when your rubric's safety-critical list covers it, false otherwise"
    )
    defect = (
        "a blocking specification defect naming it"
        if not_evaluable == "blocking"
        else "a specification defect naming it, blocking when your rubric's safety-critical "
        "list covers it"
    )
    return (
        "Your verdict is held to a schema built from your rubric, and a verdict that breaks it "
        "is refused with the reasons; correct it and submit again. Submit it as "
        f"`{{{WRAPPER}: {{...the verdict...}}}}`: `{WRAPPER}` is an object, never a string "
        "holding JSON.\n"
        f"- `items`: one entry for every one of the rubric's {len(items)} items, keyed by the "
        "item's id exactly as the rubric gives it (for example "
        f"`{items[0].id}`), never grouped, never renamed, nothing else.\n"
        "- Results: an acceptance-criteria item is met, unmet or not evaluable; a domain "
        "standard or an antipattern is met, unmet, n/a (its trigger is absent, with evidence) "
        "or not evaluable; a reward-hacking item is not observed, noted or confirmed.\n"
        f"- `acceptance_criteria`: the issued specification's own criteria, apart from the "
        f"rubric's items, each met, unmet or not evaluable with its evidence. {counted}\n"
        f"- A rubric item not evaluable needs {defect} in `spec_defects`. A criterion line "
        "not evaluable carries its own `defect` on the line: what the issued specification "
        f"lacks, and `blocking` ({blocking}).\n"
        "- Checked after you submit, not by the schema: each criterion of a specification that "
        "does not number them has one line only, and a reject's failing item is one you found "
        "unmet.\n"
        "- `indicators`: one for each check the trajectory shows switched off (listed below), "
        "and any you raise yourself.\n"
    )
