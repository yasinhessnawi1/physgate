"""A node may say why it was left unchanged when a node constraining it changed.

The propagation check fails a changed quantity whose constrained nodes were not
rewritten, unless the constrained node carries an explicit excuse (ARCH-082).
The excuse is part of the node: typed, keyed by the constraining node's id,
with a reason that says something, and recorded in the journal like every
other field, so it can be audited later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from physgate.state.schema import NODE_ID_MAX_LENGTH, Node, validate_node
from physgate.state.store import JOURNAL_NAME, Store, journal_records_after, node_file_body


def budget(**extra: Any) -> dict[str, Any]:  # noqa: ANN401 - the field under test
    """The current budget a motor constrains, owned by the electrical role."""
    return {
        "id": "power.budget",
        "kind": "module",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "current_limit": {
                "value": 5.0,
                "unit": "A",
                "source": "sizing note",
                "written_by": "electrical",
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-09-27T10:00:00Z",
        **extra,
    }


REASON = "the budget keeps 2 A of headroom above the new stall current"


def test_a_node_without_a_justification_has_none() -> None:
    assert validate_node(budget()).no_change_justified == {}


def test_a_justification_keyed_by_the_constraining_node_is_accepted() -> None:
    node = validate_node(budget(no_change_justified={"electrical.motor_left": REASON}))
    assert node.no_change_justified == {"electrical.motor_left": REASON}


@pytest.mark.parametrize(
    "reason",
    ["", " ", "\t\n", 3, None, ["a reason"]],
    ids=["empty", "a space", "whitespace", "a number", "null", "a list"],
)
def test_a_justification_without_a_reason_is_refused(reason: object) -> None:
    with pytest.raises(ValidationError, match="no_change_justified"):
        validate_node(budget(no_change_justified={"electrical.motor_left": reason}))


@pytest.mark.parametrize(
    "key",
    ["../motor", "motor", "Electrical.Motor", "electrical/motor", "e." + "a" * NODE_ID_MAX_LENGTH],
    ids=["a parent reference", "no dot", "capitals", "a separator", "too long"],
)
def test_a_justification_for_something_that_is_not_a_node_id_is_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="no_change_justified"):
        validate_node(budget(no_change_justified={key: REASON}))


def test_a_justification_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(ValidationError, match="no_change_justified"):
        Node.model_validate(budget(no_change_justified=["electrical.motor_left"]))


def test_a_justification_is_journalled_with_the_node_and_read_back(tmp_path: Path) -> None:
    """Its presence is on the durable record: a fresh reader of the journal sees it."""
    store = Store(tmp_path / "g")
    assert store.write_node(budget(), "electrical").accepted
    justified = budget(no_change_justified={"electrical.motor_left": REASON})
    assert store.write_node(justified, "electrical").accepted
    # Read with the writer still open, from the journal alone.
    first, second = journal_records_after(tmp_path / "g", 0)
    store.close()
    assert "no_change_justified" not in first.payload
    assert second.payload["no_change_justified"] == {"electrical.motor_left": REASON}
    assert REASON in (tmp_path / "g" / JOURNAL_NAME).read_text()


def test_a_blank_justification_is_refused_by_the_store_and_writes_nothing(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "g")
    with pytest.raises(ValidationError, match="no_change_justified"):
        store.write_node(budget(no_change_justified={"electrical.motor_left": " "}), "electrical")
    assert store.head_revision() == 0
    store.close()


def test_a_node_written_before_the_field_existed_keeps_its_bytes(tmp_path: Path) -> None:
    """The field has a default, and a node file holds the raw payload, so no file changes."""
    store = Store(tmp_path / "g")
    assert store.write_node(budget(), "electrical").accepted
    store.close()
    (line,) = journal_records_after(tmp_path / "g", 0)
    on_disk = (tmp_path / "g" / "nodes" / "power.budget.json").read_text()
    assert on_disk == node_file_body(line.rev, line.version, budget())
    reopened = Store(tmp_path / "g")
    assert reopened.read_node("power.budget") == budget()
    reopened.close()


def test_the_decomposition_plan_schema_carries_the_field() -> None:
    """Interface nodes the one model call writes are held to the same shape."""
    from physgate.orchestrator.decompose import plan_schema

    assert "no_change_justified" in plan_schema()
