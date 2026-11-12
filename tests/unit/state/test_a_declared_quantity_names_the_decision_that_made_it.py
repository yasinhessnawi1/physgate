"""A quantity a person declared names the decision that made it, and nothing else may look like one.

A part a person already owns enters the graph as quantities they stated. Such a quantity
carries a typed record of the decision behind it (the queue item, the digest of the decision's
line, and who decided) together with one reserved source. The schema holds the two together:

- the record is present exactly when the source is the reserved one;
- a source that only reads like the reserved one is refused as an imitation;
- a declared quantity names no simulation record, since it was stated and not read off one;
- on a node, a declared quantity's writer is the node's owner, so a node stays one writer's.

The record is optional and left out of every dump when absent, and it is left out of the JSON
schema, so no existing node, journal line, digest or decomposition schema changes.

Each refusal row reads the schema's own words for the rule it holds: a payload refused for
another reason (an unknown field, say) does not pass the row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

import physgate.state as state
from physgate.orchestrator.decompose import plan_schema
from physgate.state import schema
from physgate.state.exceptions import MissingUnitError
from physgate.state.protocol import canonical_json
from physgate.state.schema import Node, Quantity, quantities_are_valid, validate_node

RESERVED = "declared by the person"
PLAIN = {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": "electrical"}
RECORD = {
    "item_id": "run-7-parts-motor_left",
    "decision_sha256": "ab" * 32,
    "operator": "the operator",
}
DECLARED = {**PLAIN, "source": RESERVED, "declared": RECORD}

#: The rule each refusal names, in the schema's words.
NEEDS_RECORD = "names no decision"
NEEDS_SOURCE = "only under the source"
IMITATES = "imitates"
NO_SERIES = "names no simulation record"
ONE_WRITER = "written by the node's owner"


def _node(quantities: dict[str, Any], owner: str = "electrical") -> dict[str, Any]:
    return {
        "id": "electrical.motor_left",
        "kind": "component",
        "domain": "electrical",
        "owner_role": owner,
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-12T00:00:00Z",
    }


def _refusal(model: type[Quantity] | type[Node], payload: object) -> str:
    """Every message of the refusal of ``payload``, or the empty string if it is accepted."""
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        return " | ".join(error["msg"] for error in exc.errors())
    return ""


def _refused_at(payload: object) -> list[tuple[Any, ...]]:
    """Where in ``payload`` a quantity's refusal points, or nowhere if it is accepted."""
    try:
        Quantity.model_validate(payload)
    except ValidationError as exc:
        return [tuple(error["loc"]) for error in exc.errors()]
    return []


# --- the reserved source and the record, together or not at all ------------------------------


def test_the_reserved_source_is_one_fixed_text() -> None:
    assert getattr(schema, "DECLARED_SOURCE", None) == RESERVED
    assert getattr(state, "DECLARED_SOURCE", None) == RESERVED
    assert "Declared" in state.__all__


def test_a_declared_quantity_is_accepted_and_keeps_its_record() -> None:
    assert _refusal(Quantity, DECLARED) == ""
    quantity = Quantity.model_validate(DECLARED)
    record = getattr(quantity, "declared", None)
    assert record is not None
    assert (record.item_id, record.decision_sha256, record.operator) == (
        RECORD["item_id"],
        RECORD["decision_sha256"],
        RECORD["operator"],
    )
    assert quantity.model_dump() == DECLARED
    assert json.loads(quantity.model_dump_json()) == DECLARED


def test_the_reserved_source_without_a_record_is_refused() -> None:
    assert NEEDS_RECORD in _refusal(Quantity, {**PLAIN, "source": RESERVED})
    # The store reports a quantity fault from this one predicate.
    assert quantities_are_valid(_node({"stall_current": {**PLAIN, "source": RESERVED}})) is False


def test_a_record_without_the_reserved_source_is_refused() -> None:
    assert NEEDS_SOURCE in _refusal(Quantity, {**PLAIN, "declared": RECORD})
    assert NEEDS_SOURCE in _refusal(Quantity, {**PLAIN, "source": "a person", "declared": RECORD})


def test_an_absent_record_spelled_as_null_is_the_same_as_none() -> None:
    assert _refusal(Quantity, {**PLAIN, "declared": None}) == ""
    assert Quantity.model_validate({**PLAIN, "declared": None}).model_dump() == PLAIN
    assert NEEDS_RECORD in _refusal(Quantity, {**PLAIN, "source": RESERVED, "declared": None})


# --- imitations ------------------------------------------------------------------------------

IMITATIONS = [
    "declared",
    "Declared",
    "DECLARED BY THE PERSON",
    "Declared by the person",
    "declared-by-the-person",
    "declared_by_the_person",
    "declared  by the person",
    " declared by the person",
    "declared by the person ",
    "declaredbytheperson",
    "user-declared",
    "user declared",
    "User_Declared",
    "userdeclared",
    "person-declared",
    "Person Declared",
    "person_declared",
    # Compatibility forms fold to the plain letters: full-width, and a no-break space.
    "ｄｅｃｌａｒｅｄ",
    "user declared",
    "ｕｓｅｒ－ｄｅｃｌａｒｅｄ",
    "u\u017fer-declared",
    "USER-DECLARED",
    # Separators that are not the plain three: a tab, a non-breaking hyphen, a zero-width space.
    "user\tdeclared",
    "user‑declared",
    "de​clared",
]


@pytest.mark.parametrize("source", IMITATIONS)
def test_a_source_that_reads_like_the_reserved_one_is_refused(source: str) -> None:
    assert IMITATES in _refusal(Quantity, {**PLAIN, "source": source})
    assert quantities_are_valid(_node({"stall_current": {**PLAIN, "source": source}})) is False


@pytest.mark.parametrize("source", ["declared", "user-declared", "Declared By The Person"])
def test_an_imitation_is_refused_as_one_even_with_a_record_beside_it(source: str) -> None:
    # Two faults at once: the imitation is named, not the record's misplacement.
    refusal = _refusal(Quantity, {**PLAIN, "source": source, "declared": RECORD})
    assert IMITATES in refusal
    assert NEEDS_SOURCE not in refusal


@pytest.mark.parametrize(
    "source",
    [
        "datasheet",
        "the brief",
        "declared in the brief, section 3",
        "the supplier's declared rating",
        "undeclared",
        "declared by the supplier",
        "user",
        "person",
    ],
)
def test_a_source_that_only_mentions_the_word_is_still_a_source(source: str) -> None:
    assert _refusal(Quantity, {**PLAIN, "source": source}) == ""
    assert Quantity.model_validate({**PLAIN, "source": source}).model_dump()["source"] == source


# --- a declared quantity was stated, not read off a record -----------------------------------


def test_a_declared_quantity_names_no_simulation_record() -> None:
    series = {"record": "loop_nominal", "extract": "phase_margin"}
    assert NO_SERIES in _refusal(Quantity, {**DECLARED, "series": series})
    assert _refusal(Quantity, {**PLAIN, "series": series}) == ""


# --- the record's own shape ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("record", "at"),
    [
        ({k: v for k, v in RECORD.items() if k != "item_id"}, ("declared", "item_id")),
        (
            {k: v for k, v in RECORD.items() if k != "decision_sha256"},
            ("declared", "decision_sha256"),
        ),
        ({k: v for k, v in RECORD.items() if k != "operator"}, ("declared", "operator")),
        ({**RECORD, "item_id": ""}, ("declared", "item_id")),
        ({**RECORD, "item_id": "run/../parts"}, ("declared", "item_id")),
        ({**RECORD, "item_id": "run-7-parts-motor\n"}, ("declared", "item_id")),
        ({**RECORD, "item_id": "a" * 301}, ("declared", "item_id")),
        ({**RECORD, "decision_sha256": "ab" * 31}, ("declared", "decision_sha256")),
        ({**RECORD, "decision_sha256": "AB" * 32}, ("declared", "decision_sha256")),
        ({**RECORD, "decision_sha256": "sha256:" + "ab" * 32}, ("declared", "decision_sha256")),
        ({**RECORD, "decision_sha256": "ab" * 32 + "\n"}, ("declared", "decision_sha256")),
        ({**RECORD, "operator": ""}, ("declared", "operator")),
        ({**RECORD, "operator": "   "}, ("declared", "operator")),
        ({**RECORD, "operator": "the\noperator"}, ("declared", "operator")),
        ({**RECORD, "operator": "o" * 65}, ("declared", "operator")),
        ({**RECORD, "operator": 7}, ("declared", "operator")),
        ({**RECORD, "verdict": "checked"}, ("declared", "verdict")),
    ],
    ids=[
        "no_item",
        "no_digest",
        "no_operator",
        "empty_item",
        "item_with_a_path",
        "item_ending_in_a_newline",
        "item_too_long",
        "short_digest",
        "upper_case_digest",
        "prefixed_digest",
        "digest_ending_in_a_newline",
        "empty_operator",
        "blank_operator",
        "operator_with_a_line_break",
        "operator_too_long",
        "operator_not_text",
        "an_unknown_field",
    ],
)
def test_a_malformed_record_is_refused_at_its_own_field(
    record: dict[str, Any], at: tuple[str, ...]
) -> None:
    assert _refused_at({**PLAIN, "source": RESERVED, "declared": record}) == [at]


def test_the_longest_item_id_and_operator_are_accepted() -> None:
    longest = {**RECORD, "item_id": "a" * 300, "operator": "o" * 64}
    assert _refusal(Quantity, {**PLAIN, "source": RESERVED, "declared": longest}) == ""


def test_a_bare_string_is_not_a_record() -> None:
    assert _refused_at({**PLAIN, "source": RESERVED, "declared": "run-7-parts-motor_left"}) == [
        ("declared",)
    ]
    assert quantities_are_valid(_node({"stall_current": {**DECLARED, "declared": True}})) is False


# --- one writer per node ---------------------------------------------------------------------


def test_a_declared_quantity_is_written_by_the_node_s_owner() -> None:
    assert _refusal(Node, _node({"stall_current": DECLARED})) == ""
    node = validate_node(_node({"stall_current": DECLARED}))
    assert node.quantities["stall_current"].model_dump() == DECLARED


def test_a_declared_quantity_under_another_writer_s_name_is_refused() -> None:
    foreign = {**DECLARED, "written_by": "the person"}
    assert ONE_WRITER in _refusal(Node, _node({"stall_current": foreign}))
    assert ONE_WRITER in _refusal(Node, _node({"stall_current": DECLARED}, owner="sizing"))
    # The quantity alone is well formed; it is the node that refuses it.
    assert _refusal(Quantity, foreign) == ""


def test_a_role_s_own_quantity_beside_a_declared_one_keeps_its_own_writer() -> None:
    # The rule binds declared quantities only: what a node may hold otherwise is as before.
    own = {**PLAIN, "source": "computed from the stall current", "written_by": "sizing"}
    payload = _node({"stall_current": DECLARED, "operating_current": own})
    assert _refusal(Node, payload) == ""
    assert _refusal(Node, _node({"operating_current": own})) == ""


def test_a_bare_number_is_still_refused_with_a_record_beside_it() -> None:
    bare = {"value": 2.4, "source": RESERVED, "declared": RECORD}
    with pytest.raises(MissingUnitError):
        validate_node(_node({"stall_current": bare}))


# --- nothing that exists changes -------------------------------------------------------------


def test_a_quantity_nobody_declared_dumps_exactly_as_before() -> None:
    quantity = Quantity.model_validate(PLAIN)
    assert quantity.model_dump() == PLAIN
    assert quantity.model_dump(mode="json") == PLAIN
    assert json.loads(quantity.model_dump_json()) == PLAIN
    assert "declared" not in quantity.model_dump_json()
    with_series = {**PLAIN, "series": {"record": "loop_nominal", "extract": "phase_margin"}}
    assert Quantity.model_validate(with_series).model_dump() == with_series


def test_a_node_nobody_declared_anything_on_keeps_its_bytes() -> None:
    payload = _node({"stall_current": PLAIN})
    dumped = validate_node(payload).model_dump()
    assert dumped == {**payload, "no_change_justified": {}}
    # The digests of the validated node's two dumps, taken before the record existed.
    node = validate_node(payload)
    assert hashlib.sha256(canonical_json(node.model_dump()).encode()).hexdigest() == (
        "c5232d30b265613d207ce37d0cc1927cc05bf83a51e3d08fc989b195d724ad89"
    )
    assert hashlib.sha256(node.model_dump_json().encode()).hexdigest() == (
        "77c05738b72c0f2cb83aa69c4931101c84c1e7773b63849bb13786d86ec97bb3"
    )


def test_a_declared_node_round_trips() -> None:
    payload = _node({"stall_current": DECLARED, "rated_voltage": {**PLAIN, "unit": "V"}})
    assert _refusal(Node, payload) == ""
    node = Node.model_validate(payload)
    assert node.model_dump() == {**payload, "no_change_justified": {}}
    assert "declared" not in node.model_dump()["quantities"]["rated_voltage"]


#: The schema every run without the cross-cutting roles is sent, and the one a run with sizing
#: and integration is sent, as recorded before a quantity could carry a record.
PLAN_SCHEMA_SHA256 = {
    ("control", "firmware"): "fae5d012d4633b0f2650310ffbe62ad712a16bf7764dc7757e54aa72b21f3357",
    (
        "control",
        "firmware",
        "integration",
        "sizing",
    ): "6f531bcd22eb1d69b563acd763ca4f73d80ecccd3ccf973c32962ba410882e08",
}


@pytest.mark.parametrize("roles", sorted(PLAN_SCHEMA_SHA256))
def test_the_decomposition_s_schema_does_not_offer_the_record(roles: tuple[str, ...]) -> None:
    # The plan's answer is held to this schema, which holds a quantity's: a record offered
    # there would change what every run sends, and would let a plan declare for a person.
    sent = plan_schema(list(roles))
    assert hashlib.sha256(sent.encode()).hexdigest() == PLAN_SCHEMA_SHA256[roles]
    quantity = json.loads(sent)["$defs"]["Quantity"]
    assert sorted(quantity["properties"]) == ["series", "source", "unit", "value", "written_by"]
    assert quantity["additionalProperties"] is False
    assert "Declared" not in json.loads(sent)["$defs"]
