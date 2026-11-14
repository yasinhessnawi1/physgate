"""The second line names a declared quantity a step changed, dropped or forged past the store.

The store refuses a session's write that touches a declared quantity, so a change in a step's
list that does is one that did not pass the store's guard. The check names it from the record
with the store's own two reasons: ``declared_fixed`` for a declared quantity changed or dropped,
``declared_forged`` for one added. The parts writer's own revisions are admitted by name. A role's
own quantity beside a declared one is not named, and a change already named for an earlier
reason (its owner, a duty) keeps that reason and is named once.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from test_divergence_names_the_foreign_write import (
    append_to_the_journal_behind_the_stores_back as behind_the_stores_back,
)

from physgate.state.divergence import OWNERSHIP_ONLY, Duties, divergence
from physgate.state.protocol import REJECT_CROSS_ROLE
from physgate.state.store import Store

RESERVED = "declared by the person"
FORGED = "declared_forged"
FIXED = "declared_fixed"
RECORD = {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "yasin"}


def _declared(value: float = 0.4, unit: str = "kg") -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "source": RESERVED,
        "written_by": "control",
        "declared": dict(RECORD),
    }


def _plain(value: float = 2.4, unit: str = "A") -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "datasheet", "written_by": "control"}


def _node(quantities: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    node: dict[str, Any] = {
        "id": "control.motor_left",
        "kind": "component",
        "domain": "control",
        "owner_role": "control",
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-12T10:00:00.000000Z",
    }
    return node | fields


def _declared_root(tmp_path: Path) -> tuple[Path, int]:
    """A store holding a node whose ``mass`` a person declared; the head after it."""
    root = tmp_path / "graph"
    store = Store(root)
    assert store.declare(_node({"mass": _declared()}), ("run-1-parts-1",)).accepted
    head = store.head_revision()
    store.close()
    return root, head


def _named(root: Path, since: int, role: str = "control", **kw: Any) -> list[Any]:  # noqa: ANN401
    store = Store(root)
    try:
        return divergence(store, store.diff(since), role, OWNERSHIP_ONLY, **kw)
    finally:
        store.close()


def _reasons(found: list[Any]) -> list[str]:
    return [d.reason for d in found]


def test_a_declared_value_changed_past_the_store_is_named_declared_fixed(tmp_path: Path) -> None:
    root, head = _declared_root(tmp_path)
    rev = behind_the_stores_back(root, _node({"mass": _declared(value=0.9)}))
    found = _named(root, head)
    assert _reasons(found) == [FIXED]
    assert found[0].node_id == "control.motor_left" and found[0].revision == rev
    assert "mass" in found[0].detail
    assert "mass" in str(found[0]) and FIXED in str(found[0])
    assert "declared quantity" in str(found[0]) and "breaks a duty" not in str(found[0])


def test_a_declared_quantity_dropped_past_the_store_is_named_declared_fixed(
    tmp_path: Path,
) -> None:
    root, head = _declared_root(tmp_path)
    behind_the_stores_back(root, _node({"stall_current": _plain()}))
    assert _reasons(_named(root, head)) == [FIXED]


def test_a_declared_quantity_added_past_the_store_is_named_declared_forged(
    tmp_path: Path,
) -> None:
    root, head = _declared_root(tmp_path)
    forged = _declared(value=0.2, unit="N*m")
    behind_the_stores_back(root, _node({"mass": _declared(), "torque_rated": forged}))
    found = _named(root, head)
    assert _reasons(found) == [FORGED]
    assert "torque_rated" in found[0].detail


def test_a_node_created_past_the_store_with_a_declared_quantity_is_named_declared_forged(
    tmp_path: Path,
) -> None:
    root = tmp_path / "graph"
    Store(root).close()
    behind_the_stores_back(root, _node({"mass": _declared()}, id="control.imu"))
    assert _reasons(_named(root, 0)) == [FORGED]


def test_a_roles_own_quantity_beside_a_declared_one_is_not_named(tmp_path: Path) -> None:
    root, head = _declared_root(tmp_path)
    store = Store(root)
    written = store.write_node(_node({"mass": _declared(), "stall_current": _plain()}), "control")
    store.close()
    assert written.accepted
    assert _named(root, head) == []


def test_the_parts_writers_revision_is_admitted_by_name_and_only_it(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    store = Store(root)
    first = store.declare(_node({"mass": _declared()}), ("run-1-parts-1",))
    store.close()
    assert first.accepted and first.revision is not None
    try:
        admitted = _named(root, 0, declared=frozenset({first.revision}))
    except TypeError:
        pytest.fail("divergence does not admit the parts writer's revisions yet")
    assert admitted == []
    assert _reasons(_named(root, 0, declared=frozenset())) == [FORGED]


def test_a_declared_change_by_a_role_that_does_not_own_the_node_keeps_the_owners_reason(
    tmp_path: Path,
) -> None:
    root, head = _declared_root(tmp_path)
    behind_the_stores_back(root, _node({"mass": _declared(value=0.9)}))
    found = _named(root, head, role="electrical")
    assert _reasons(found) == [REJECT_CROSS_ROLE]


def test_a_duty_broken_by_the_same_change_keeps_the_dutys_reason(tmp_path: Path) -> None:
    root, head = _declared_root(tmp_path)
    behind_the_stores_back(root, _node({"mass": _declared(value=0.9)}))
    store = Store(root)
    try:
        duties = Duties(cross_nodes=(), completion=("control",))
        found = divergence(store, store.diff(head), "control", duties)
    finally:
        store.close()
    assert _reasons(found) == ["completion_owner_node"]


def test_with_the_duties_held_a_declared_change_is_still_named(tmp_path: Path) -> None:
    root, head = _declared_root(tmp_path)
    changed = copy.deepcopy(_node({"mass": _declared(unit="g", value=400)}))
    behind_the_stores_back(root, changed)
    store = Store(root)
    try:
        found = divergence(store, store.diff(head), "control", Duties((), ()))
    finally:
        store.close()
    assert _reasons(found) == [FIXED]
