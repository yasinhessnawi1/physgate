"""What the parts decisions become: the nodes the plan places them on, and the record.

ARCH-122. Pure derivation, from the plan's components and the decisions alone: a component's own
names (and any name a person added) go to its node, the plan's shared names to the cross node,
each quantity carries the record of its decision, and the record a role reads is the decisions as
canonical bytes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from parts_rig import BRACKET, IMU, MOTOR, body

from physgate.orchestrator.parts_write import (
    PARTS_GEOMETRY_HASH,
    TakenPart,
    parts_payload,
    parts_record,
    parts_writes,
)
from physgate.orchestrator.queue import parts_sha256
from physgate.state.schema import Node
from physgate.state.store import Store

IDS = ("run-1-parts-1", "run-1-parts-2", "run-1-parts-3")
TS = "2026-11-12T10:30:00.000000Z"


def _taken(choice: str, stated: Any = None, item: str = IDS[0]) -> TakenPart:  # noqa: ANN401
    return TakenPart(item_id=item, choice=choice, body=stated, operator="yasin", decided_ts=TS)  # type: ignore[arg-type]


STATED = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A"), "extra_note": (1, "m")})


def test_a_component_s_own_names_and_a_name_added_go_to_its_node() -> None:
    payload = parts_payload(
        MOTOR,
        shared=False,
        owner_role="control",
        item_id=IDS[0],
        body=STATED,
        operator="yasin",
        decided_ts=TS,
    )
    assert payload is not None
    assert list(payload["quantities"]) == ["mass", "extra_note"]
    assert (payload["id"], payload["kind"], payload["domain"], payload["owner_role"]) == (
        "control.motor_left",
        "component",
        "control",
        "control",
    )
    assert payload["constrains"] == [] and payload["updated"] == TS
    assert payload["geometry_hash"] == PARTS_GEOMETRY_HASH
    Node.model_validate(payload)


def test_the_plan_s_shared_names_go_to_the_cross_node_joined_to_the_component() -> None:
    payload = parts_payload(
        MOTOR,
        shared=True,
        owner_role="sizing",
        item_id=IDS[0],
        body=STATED,
        operator="yasin",
        decided_ts=TS,
    )
    assert payload is not None
    assert list(payload["quantities"]) == ["stall_current"]
    assert (payload["id"], payload["domain"], payload["owner_role"]) == (
        "sizing.control_motor_left",
        "cross",
        "sizing",
    )
    assert payload["constrains"] == ["control.motor_left"]
    assert payload["quantities"]["stall_current"]["written_by"] == "sizing"


def test_each_quantity_carries_the_decision_that_made_it() -> None:
    payload = parts_payload(
        MOTOR,
        shared=False,
        owner_role="control",
        item_id=IDS[0],
        body=STATED,
        operator="yasin",
        decided_ts=TS,
    )
    assert payload is not None
    quantity = payload["quantities"]["mass"]
    assert quantity == {
        "value": 0.4,
        "unit": "kg",
        "source": "declared by the person",
        "written_by": "control",
        "declared": {
            "item_id": IDS[0],
            "decision_sha256": parts_sha256(STATED),
            "operator": "yasin",
        },
    }


def test_a_node_that_would_hold_no_name_is_not_written() -> None:
    only_own = body({"mass": (0.4, "kg")})
    assert (
        parts_payload(
            MOTOR,
            shared=True,
            owner_role="sizing",
            item_id=IDS[0],
            body=only_own,
            operator="yasin",
            decided_ts=TS,
        )
        is None
    )


def test_the_writes_follow_the_plan_s_order_own_node_then_cross_node() -> None:
    taken = {
        IDS[0]: _taken("have", STATED),
        IDS[1]: _taken("make", body({"mass": (0.1, "kg")}), IDS[1]),
        IDS[2]: _taken("find", None, IDS[2]),
    }
    owed = parts_writes((MOTOR, IMU, BRACKET), IDS, taken, "sizing")
    assert [(w.node_id, w.shared, w.item_id) for w in owed] == [
        ("control.motor_left", False, IDS[0]),
        ("sizing.control_motor_left", True, IDS[0]),
        ("control.imu", False, IDS[1]),
    ]
    assert all(len(w.payload_sha256) == 64 for w in owed)


def test_shared_names_with_no_role_for_the_cross_nodes_are_refused() -> None:
    with pytest.raises(ValueError, match="sizing"):
        parts_writes((MOTOR,), IDS[:1], {IDS[0]: _taken("have", STATED)}, None)
    only_own = {IDS[0]: _taken("have", body({"mass": (0.4, "kg")}))}
    assert len(parts_writes((MOTOR,), IDS[:1], only_own, None)) == 1


def test_every_derived_node_is_accepted_by_declare(tmp_path: Any) -> None:  # noqa: ANN401
    taken = {IDS[0]: _taken("have", STATED)}
    store = Store(tmp_path / "graph")
    for write in parts_writes((MOTOR,), IDS[:1], taken, "sizing"):
        result = store.declare(write.payload, (write.item_id,))
        assert (result.accepted, result.reason) == (True, None), write.node_id


def test_the_record_is_the_decisions_as_canonical_bytes() -> None:
    made = body({"mass": (0.1, "kg")}, texts=("printed in PETG", "wall 3 mm"))
    parts = [
        _taken("have", STATED),
        _taken("make", made, IDS[1]),
        _taken("find", None, IDS[2]),
    ]
    record = parts_record((MOTOR, IMU, BRACKET), parts)
    assert json.loads(record) == {
        "components": [
            {
                "node": "control.motor_left",
                "label": "Left drive motor",
                "choice": "have",
                "declared": {
                    "mass": {"value": 0.4, "unit": "kg"},
                    "stall_current": {"value": 2.4, "unit": "A"},
                    "extra_note": {"value": 1, "unit": "m"},
                },
                "texts": [],
            },
            {
                "node": "control.imu",
                "label": "IMU",
                "choice": "make",
                "declared": {"mass": {"value": 0.1, "unit": "kg"}},
                "texts": ["printed in PETG", "wall 3 mm"],
            },
            {
                "node": "control.bracket",
                "label": "Bracket",
                "choice": "find",
                "declared": {},
                "texts": [],
            },
        ]
    }
    assert record == json.dumps(json.loads(record), sort_keys=True, separators=(",", ":")).encode()
