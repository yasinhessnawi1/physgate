"""A quantity a person declared is written only through ``declare``, never by a session's write.

``write_node`` is the path every session's proposals reach the graph by. It refuses a revision
that adds a quantity carrying the declared record (``declared_forged``) and one that changes or
drops a quantity the node holds as declared (``declared_fixed``). A role may still add quantities
of its own to a declared node and rewrite the node with the declared ones as they stand. A fault
an earlier guard already refuses keeps its old reason. A refusal writes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from physgate.state.protocol import REJECT_CROSS_ROLE, REJECT_MISSING_UNIT
from physgate.state.store import Store

RESERVED = "declared by the person"
FORGED = "declared_forged"
FIXED = "declared_fixed"


def _declared(value: float = 0.4, unit: str = "kg", **record: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "value": value,
        "unit": unit,
        "source": RESERVED,
        "written_by": "control",
        "declared": {
            "item_id": "run-1-parts-1",
            "decision_sha256": "a" * 64,
            "operator": "yasin",
        }
        | record,
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


@pytest.fixture
def declared_store(tmp_path: Path) -> Store:
    """A store that holds one node whose ``mass`` a person declared, as ``declare`` wrote it."""
    store = Store(tmp_path / "graph")
    result = store.declare(_node({"mass": _declared()}), ("run-1-parts-1",))
    assert result.accepted, result
    return store


def _lines(store: Store) -> int:
    return len(store.journal_path.read_text().splitlines())


def _reason(store: Store, node: dict[str, Any], role: str = "control") -> tuple[bool, str | None]:
    result = store.write_node(node, role)
    return result.accepted, result.reason


def test_a_session_cannot_create_a_node_that_holds_a_declared_quantity(tmp_path: Path) -> None:
    store = Store(tmp_path / "graph")
    assert _reason(store, _node({"mass": _declared()})) == (False, FORGED)
    assert _lines(store) == 0


def test_a_session_cannot_add_a_declared_quantity_to_a_node(declared_store: Store) -> None:
    both = _node({"mass": _declared(), "stall_current": _declared(2.0, "A")})
    assert _reason(declared_store, both) == (False, FORGED)
    assert _lines(declared_store) == 1


def test_a_session_cannot_turn_its_own_quantity_into_a_declared_one(tmp_path: Path) -> None:
    store = Store(tmp_path / "graph")
    assert store.write_node(_node({"mass": _plain(0.5, "kg")}), "control").accepted
    assert _reason(store, _node({"mass": _declared()})) == (False, FORGED)
    assert _lines(store) == 1


@pytest.mark.parametrize(
    "changed",
    [
        _declared(0.5),
        _declared(0.4, "g"),
        _declared(operator="someone else"),
        _declared(item_id="run-1-parts-2"),
        _declared(decision_sha256="b" * 64),
    ],
)
def test_a_session_cannot_change_what_was_declared(declared_store: Store, changed: Any) -> None:  # noqa: ANN401
    assert _reason(declared_store, _node({"mass": changed})) == (False, FIXED)
    assert _lines(declared_store) == 1


def test_a_session_cannot_drop_a_declared_quantity(declared_store: Store) -> None:
    assert _reason(declared_store, _node({"stall_current": _plain()})) == (False, FIXED)
    assert _reason(declared_store, _node({})) == (False, FIXED)
    assert _lines(declared_store) == 1


def test_a_session_cannot_overwrite_a_declared_quantity_with_its_own(declared_store: Store) -> None:
    assert _reason(declared_store, _node({"mass": _plain(0.9, "kg")})) == (False, FIXED)


def test_a_role_may_add_a_quantity_of_its_own_beside_a_declared_one(declared_store: Store) -> None:
    both = _node({"mass": _declared(), "stall_current": _plain()})
    assert _reason(declared_store, both) == (True, None)


def test_a_role_may_rewrite_the_node_with_the_declared_quantity_as_it_stands(
    declared_store: Store,
) -> None:
    again = _node({"mass": _declared()}, constrains=["control.imu"])
    assert _reason(declared_store, again) == (True, None)


def test_a_fault_an_earlier_guard_refuses_keeps_its_reason(declared_store: Store) -> None:
    assert _reason(declared_store, _node({"mass": _declared(0.5)}), "electrical") == (
        False,
        REJECT_CROSS_ROLE,
    )
    broken = _node({"mass": {"value": 1.0, "source": "datasheet", "written_by": "control"}})
    assert _reason(declared_store, broken) == (False, REJECT_MISSING_UNIT)


def test_the_followed_interface_path_is_not_changed_by_the_guard(tmp_path: Path) -> None:
    store = Store(tmp_path / "graph")
    plain = _node({"mass": _plain(0.5, "kg")})
    assert store.write_node(plain, "control").accepted
    assert store.write_node({**plain, "updated": "later"}, "control").accepted


@pytest.mark.parametrize(
    "source", [RESERVED, "Declared", "user-declared", "Declared By The Person"]
)
def test_the_reserved_source_without_the_record_is_declared_forged_not_a_missing_unit(
    tmp_path: Path, source: str
) -> None:
    store = Store(tmp_path / "store")
    try:
        bare = {"value": 1.0, "unit": "A", "source": source, "written_by": "control"}
        result = store.write_node(_node({"stall_current": bare}), "control")
        assert (result.accepted, result.reason) == (False, FORGED)
    finally:
        store.close()


def test_a_bare_number_keeps_the_missing_unit_reason_beside_a_declared_one(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    try:
        result = store.write_node(_node({"stall_current": {"value": 1.0}}), "control")
        assert (result.accepted, result.reason) == (False, REJECT_MISSING_UNIT)
    finally:
        store.close()
