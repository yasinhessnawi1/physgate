"""The store's ``declare``: the one writer of a declared quantity (ARCH-122).

``write_node`` is unchanged and ``declare`` is not on the frozen interface. It writes a node
whose changed quantities each carry the record of a decision (and none other), by the owner
the node names, and nothing else of the node moves. A refusal writes nothing and names its
reason; the line it appends is an ordinary ``write`` that recovery replays like any other.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physgate.state.store import Store

RESERVED = "declared by the person"
ITEM = "run-1-parts-1"
OTHER_ITEM = "run-1-parts-2"
SHA = "a" * 64
REFUSED = "declare_refused"


def _declared(value: float = 0.4, unit: str = "kg", item: str = ITEM) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "source": RESERVED,
        "written_by": "control",
        "declared": {"item_id": item, "decision_sha256": SHA, "operator": "yasin"},
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
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "graph")


def _declare(store: Store, node: dict[str, Any], items: tuple[str, ...] = (ITEM,)) -> Any:  # noqa: ANN401
    method = getattr(store, "declare", None)
    assert method is not None, "the store has no declare"
    return method(node, items)


def _lines(store: Store) -> int:
    return len(store.journal_path.read_text().splitlines())


def test_the_method_is_not_on_the_frozen_interface() -> None:
    from physgate.state import protocol

    assert "declare" not in {
        name for name in dir(protocol.DesignStateStore) if not name.startswith("_")
    }


def test_a_declared_node_is_created_with_the_quantities_a_decision_gave(store: Store) -> None:
    result = _declare(store, _node({"mass": _declared()}))
    assert (result.accepted, result.reason) == (True, None)
    assert result.revision == 1
    held = store.read_node("control.motor_left")
    assert held["quantities"]["mass"] == _declared()
    assert store.head_revision() == 1


def test_the_line_it_appends_is_an_ordinary_write_that_reopens_as_written(
    store: Store, tmp_path: Path
) -> None:
    _declare(store, _node({"mass": _declared()}))
    line = json.loads(store.journal_path.read_text().splitlines()[-1])
    assert line["op"] == "create"
    store.close()
    again = Store(tmp_path / "graph")
    assert again.read_node("control.motor_left")["quantities"]["mass"] == _declared()


def test_a_second_decision_is_a_new_revision_beside_the_first(store: Store) -> None:
    _declare(store, _node({"mass": _declared()}))
    both = _node({"mass": _declared(), "stall_current": _declared(2.0, "A", OTHER_ITEM)})
    result = _declare(store, both, (OTHER_ITEM,))
    assert (result.accepted, result.revision) == (True, 2)


def test_a_quantity_without_the_record_is_refused_and_nothing_is_written(store: Store) -> None:
    result = _declare(store, _node({"mass": _plain(0.4, "kg")}))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 0


def test_a_node_that_holds_a_plain_beside_a_declared_quantity_is_refused(store: Store) -> None:
    result = _declare(store, _node({"mass": _declared(), "stall_current": _plain()}))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 0


def test_a_decision_the_call_does_not_name_is_refused(store: Store) -> None:
    result = _declare(store, _node({"mass": _declared(item=OTHER_ITEM)}), (ITEM,))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 0


def test_a_quantity_naming_a_decision_the_call_does_not_name_is_refused_beside_one_it_does(
    store: Store,
) -> None:
    node = _node({"mass": _declared(), "stall_current": _declared(2.4, "A", item=OTHER_ITEM)})
    result = _declare(store, node, (ITEM,))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 0


def test_an_item_named_that_no_quantity_carries_is_refused(store: Store) -> None:
    result = _declare(store, _node({"mass": _declared()}), (ITEM, OTHER_ITEM))
    assert (result.accepted, result.reason) == (False, REFUSED)


def test_no_item_named_is_refused(store: Store) -> None:
    result = _declare(store, _node({"mass": _declared()}), ())
    assert (result.accepted, result.reason) == (False, REFUSED)


def test_an_interface_is_never_declared(store: Store) -> None:
    node = _node({"mass": _declared()}, id="iface.control.bus", kind="interface")
    result = _declare(store, node)
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 0


def test_a_revision_that_changes_another_field_of_the_node_is_refused(store: Store) -> None:
    _declare(store, _node({"mass": _declared()}))
    for field, value in (("owner_role", "electrical"), ("domain", "firmware"), ("kind", "module")):
        grown = _node(
            {"mass": _declared(), "stall_current": _declared(2.0, "A", OTHER_ITEM)},
            **{field: value},
        )
        result = _declare(store, grown, (OTHER_ITEM,))
        assert (result.accepted, result.reason) == (False, REFUSED), field
    assert _lines(store) == 1


def test_a_revision_that_changes_a_quantity_a_role_wrote_is_refused(store: Store) -> None:
    store.write_node(_node({"mass": _plain(0.5, "kg")}), "control")
    result = _declare(store, _node({"mass": _declared()}))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 1


def test_a_role_s_own_quantity_beside_a_declared_one_is_kept(store: Store) -> None:
    store.write_node(_node({"stall_current": _plain()}), "control")
    both = _node({"stall_current": _plain(), "mass": _declared()})
    result = _declare(store, both)
    assert (result.accepted, result.revision) == (True, 2)


def test_a_revision_that_changes_nothing_is_refused(store: Store) -> None:
    _declare(store, _node({"mass": _declared()}))
    result = _declare(store, _node({"mass": _declared()}))
    assert (result.accepted, result.reason) == (False, REFUSED)
    assert _lines(store) == 1


def test_a_declared_quantity_dropped_by_a_revision_is_refused(store: Store) -> None:
    _declare(store, _node({"mass": _declared()}))
    result = _declare(
        store, _node({"stall_current": _declared(2.0, "A", OTHER_ITEM)}), (OTHER_ITEM,)
    )
    assert (result.accepted, result.reason) == (False, REFUSED)


def test_a_stale_handle_refuses_as_every_write_does(store: Store, tmp_path: Path) -> None:
    from physgate.state.exceptions import StoreStaleError

    other = Store(tmp_path / "graph")
    other.write_node(_node({"stall_current": _plain()}, id="control.imu"), "control")
    with pytest.raises(StoreStaleError):
        _declare(store, _node({"mass": _declared()}))
