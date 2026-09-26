"""A node carrying a bare number fails validation; the same node with a unit passes.

This is the architecture's acceptance test for the graph schema, written as the
pair it asks for: one payload that must be refused, one that must be accepted,
differing in exactly the thing under test.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from physgate.state.exceptions import MalformedNodeIdError, MissingUnitError
from physgate.state.schema import (
    Node,
    Quantity,
    quantities_are_valid,
    validate_node,
    validate_node_id,
)

WELL_FORMED_QUANTITY = {
    "value": 2.4,
    "unit": "A",
    "source": "datasheet",
    "written_by": "sizing",
}


def node(quantity: Any) -> dict[str, Any]:
    """A legal node whose single quantity is whatever the caller passes."""
    return {
        "id": "electrical.motor_left",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {"stall_current": quantity},
        "requirements": ["REQ-014"],
        "constrains": ["power.budget"],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-09-21T10:02:11Z",
    }


# --- the pair --------------------------------------------------------------


def test_a_quantity_that_is_a_bare_number_is_refused() -> None:
    with pytest.raises(MissingUnitError) as caught:
        validate_node(node(2.4))
    assert caught.value.context["node_id"] == "electrical.motor_left"


def test_the_same_node_with_a_unit_bearing_quantity_is_accepted() -> None:
    accepted = validate_node(node(dict(WELL_FORMED_QUANTITY)))
    assert accepted.quantities["stall_current"].unit == "A"
    assert accepted.quantities["stall_current"].value == 2.4


# --- the ways a quantity can be malformed ----------------------------------


@pytest.mark.parametrize(
    ("label", "quantity"),
    [
        ("a bare number", 2.4),
        ("a bare integer", 2),
        ("a bare string", "2.4 A"),
        ("no unit key at all", {"value": 2.4, "source": "datasheet", "written_by": "sizing"}),
        ("an empty unit", {**WELL_FORMED_QUANTITY, "unit": ""}),
        ("a unit that is not a string", {**WELL_FORMED_QUANTITY, "unit": 1}),
        ("no value", {"unit": "A", "source": "datasheet", "written_by": "sizing"}),
        ("a value that is not a number", {**WELL_FORMED_QUANTITY, "value": "2.4"}),
        ("no source", {"value": 2.4, "unit": "A", "written_by": "sizing"}),
        ("no writer", {"value": 2.4, "unit": "A", "source": "datasheet"}),
        ("an unknown extra field", {**WELL_FORMED_QUANTITY, "tolerance": 0.1}),
        ("null", None),
        # The coercing mode accepts all four of these. A boolean and a
        # not-a-number are not numbers at all, and every one of them would
        # reach the physics gate as something to do arithmetic on.
        ("a boolean", {**WELL_FORMED_QUANTITY, "value": True}),
        ("not a number", {**WELL_FORMED_QUANTITY, "value": float("nan")}),
        ("positive infinity", {**WELL_FORMED_QUANTITY, "value": float("inf")}),
        ("negative infinity", {**WELL_FORMED_QUANTITY, "value": float("-inf")}),
    ],
)
def test_a_malformed_quantity_is_refused(label: str, quantity: Any) -> None:
    assert not quantities_are_valid(node(quantity)), label
    with pytest.raises(MissingUnitError):
        validate_node(node(quantity))


def test_an_integer_value_is_accepted() -> None:
    """JSON has no way to say that ``2`` is a float, so an integer is a number."""
    accepted = validate_node(node({**WELL_FORMED_QUANTITY, "value": 2}))
    assert accepted.quantities["stall_current"].value == 2


def test_a_node_with_no_quantities_at_all_is_legal() -> None:
    """Not every node carries a number; a requirement or an interface may not."""
    payload = node(dict(WELL_FORMED_QUANTITY))
    payload["quantities"] = {}
    assert validate_node(payload).quantities == {}


def test_a_quantity_model_is_frozen() -> None:
    q = Quantity.model_validate(WELL_FORMED_QUANTITY)
    with pytest.raises(ValidationError):
        q.value = 9.9  # type: ignore[misc]  # the assignment the test proves is refused


def test_a_node_model_is_frozen_and_refuses_unknown_fields() -> None:
    n = validate_node(node(dict(WELL_FORMED_QUANTITY)))
    with pytest.raises(ValidationError):
        n.owner_role = "control"  # type: ignore[misc]  # the assignment the test proves is refused
    with pytest.raises(ValidationError):
        Node.model_validate({**node(dict(WELL_FORMED_QUANTITY)), "surprise": 1})


def test_an_unknown_node_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        Node.model_validate({**node(dict(WELL_FORMED_QUANTITY)), "kind": "assembly"})


# --- the identifier, which names a file on disk -----------------------------


@pytest.mark.parametrize(
    "node_id",
    [
        "../../secrets",
        "electrical/../../etc/passwd",
        "/absolute/path",
        "electrical/motor",
        "electrical.motor/../..",
        "..",
        ".",
        "",
        "no_dot",
        "Electrical.Motor",
        "electrical..motor",
        ".leading",
        "trailing.",
        "electrical.motor\x00",
        "electrical.motor\n../escape",
        "a" * 200 + ".b",
    ],
)
def test_a_malformed_node_id_raises(node_id: str) -> None:
    with pytest.raises(MalformedNodeIdError):
        validate_node_id(node_id)
    with pytest.raises(MalformedNodeIdError):
        validate_node({**node(dict(WELL_FORMED_QUANTITY)), "id": node_id})


@pytest.mark.parametrize("node_id", [42, None, ["electrical.motor"], {"id": "x"}])
def test_a_node_id_that_is_not_a_string_raises(node_id: Any) -> None:
    with pytest.raises(MalformedNodeIdError):
        validate_node_id(node_id)


@pytest.mark.parametrize(
    "node_id",
    [
        "electrical.motor_left",
        "iface.control.07",
        "mechanical.node140",
        "cross.power.budget",
        "a.b",
    ],
)
def test_a_well_formed_node_id_is_accepted(node_id: str) -> None:
    assert validate_node_id(node_id) == node_id


def test_every_identifier_the_frozen_workload_produces_is_accepted() -> None:
    """The stricter id rule cannot change what the frozen replay scores."""
    ids = [
        f"{domain}.node{i:03d}"
        for i, domain in enumerate(
            ["mechanical", "electrical", "control", "firmware", "cross"] * 30
        )
    ] + [f"iface.{d}.{i:02d}" for i, d in enumerate(["mechanical", "electrical"] * 25)]
    assert ids, "generated no identifiers to check"
    for node_id in ids:
        assert validate_node_id(node_id) == node_id
