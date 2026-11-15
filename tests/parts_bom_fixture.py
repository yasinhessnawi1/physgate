"""One run that asked which parts a person has, as data any task can read without the parts code.

A run whose plan names four components and asks: a motor driver the person has (with one shared
value, which lands on the node sizing holds for it), a battery pack the person makes, a wheel
encoder to find, and a chassis plate the person has. Every part is decided, the values are
written, the release gate passes and the run is released; the log ends at that release.

Held here, standard library only, so a reader of the bill of materials and the parts code can each
assert against the same run without importing the other:

- ``EVENT_LOG``: the run-event log's bytes up to and including the release, as replay reads them.
- ``NODES``: the design-state graph's nodes once the parts are written and the encoder's role has
  written the encoder's node (a part to find is written by a role, never by the release), plus the
  interface node the plan fixed.
- ``BOM_LINES``: the bill of materials' lines over ``NODES``: every node of kind ``component`` and
  domain ``electrical``, in the order ``NODES`` lists them. The sizing node holds a declared value
  and is no line: the line is the component's own node.
- ``CHOICES``: each component's choice and declared values, keyed by the component's own node id.
- ``SOURCING``: what sourcing records for each line: a part the person has or makes is skipped as
  owned or custom, never validated; a part to find is left for sourcing to check.
"""

from __future__ import annotations

import json
from typing import Any

#: The digest of what each choice of have or make stated, as its decision names it.
DRIVER_STATED = "c70b2ad2b63778ead5a2b47663ea001110a6e265651455a0248dfd0e3a38f773"
BATTERY_STATED = "b5f13fef25fac1f1158a3b7814de0d8f158b10e3d6fca112f7a818a0cf3df364"
CHASSIS_STATED = "35abf06e98df866d45b7f502ba2a85a067208bc3a42a0a6d49b34f3f43c430d1"

#: The run-event log, line by line, as the loop wrote it.
LINES: tuple[dict[str, Any], ...] = (
    {
        "seq": 0,
        "ts": "2026-09-26T12:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "run_started",
        "config_sha256": "d070ced7045042b7d957cddfae1f1104a424478ee3548cc559854d2a55272b51",
        "escalation_backend": "rules",
        "queue_decisions": "act",
        "parts_on_hand": "on",
        "producer_wait": "hold",
    },
    {
        "seq": 1,
        "ts": "2026-09-26T12:00:00.001000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "tokens_used",
        "attribution": "decomposition:decomposition-session-1",
        "message_id": "d1",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        "partial": False,
    },
    {
        "seq": 2,
        "ts": "2026-09-26T12:00:00.002000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "decomposed",
        "session_id": "decomposition-session-1",
        "model": "claude-sonnet-5",
        "num_turns": 1,
        "subtasks": 2,
        "interface_nodes": ["iface.bus"],
        "spec_commit": "cccccccccccccccccccccccccccccccccccccccc",
        "head_revision": 1,
        "policy_limits_sha256": None,
        "observed_traffic": None,
        "plan_sha256": "b1a73c800df3f61769123ddcf92c8e6390323c67d52d7e3783607c2da4d320d4",
        "components": [
            {
                "node": "electrical.motor_driver",
                "domain": "electrical",
                "role": "control",
                "label": "Motor driver board",
                "own": ["mass"],
                "shared": ["stall_current"],
            },
            {
                "node": "electrical.battery_pack",
                "domain": "electrical",
                "role": "control",
                "label": "Battery pack",
                "own": ["mass"],
                "shared": [],
            },
            {
                "node": "electrical.wheel_encoder",
                "domain": "electrical",
                "role": "control",
                "label": "Wheel encoder",
                "own": [],
                "shared": [],
            },
            {
                "node": "mechanical.chassis_plate",
                "domain": "mechanical",
                "role": "control",
                "label": "Chassis plate",
                "own": ["mass"],
                "shared": [],
            },
        ],
    },
    {
        "seq": 3,
        "ts": "2026-09-26T12:00:00.003000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "subtask_planned",
        "subtask_id": "s1",
        "spec_path": "specs/s1.md",
        "assigned_role": "control",
        "module_dir": "modules/s1",
    },
    {
        "seq": 4,
        "ts": "2026-09-26T12:00:00.004000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "subtask_planned",
        "subtask_id": "s2",
        "spec_path": "specs/s2.md",
        "assigned_role": "control",
        "module_dir": "modules/s2",
    },
    {
        "seq": 5,
        "ts": "2026-09-26T12:00:00.005000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "os_layer_checked",
        "state": {"state": "present", "mechanism": "seatbelt", "claude_version": "2.1.301"},
        "as_recorded": None,
        "network_enforced": None,
        "loopback_listeners": None,
        "loopback_listeners_read": None,
        "absent_allowed": None,
    },
    {
        "seq": 6,
        "ts": "2026-09-26T12:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "os_layer_checked",
        "state": {"state": "present", "mechanism": "seatbelt", "claude_version": "2.1.301"},
        "as_recorded": None,
        "network_enforced": None,
        "loopback_listeners": None,
        "loopback_listeners_read": None,
        "absent_allowed": None,
    },
    {
        "seq": 7,
        "ts": "2026-09-26T12:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "os_layer_checked",
        "state": {"state": "present", "mechanism": "seatbelt", "claude_version": "2.1.301"},
        "as_recorded": None,
        "network_enforced": None,
        "loopback_listeners": None,
        "loopback_listeners_read": None,
        "absent_allowed": None,
    },
    {
        "seq": 8,
        "ts": "2026-09-26T12:00:00.001000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "decision_taken",
        "subtask_id": None,
        "item_id": "run-1-parts-1",
        "verb": "choose",
        "position": "have",
        "note": None,
        "resolved_by": "yasin",
        "decided_ts": "2026-11-15T00:58:45.519936Z",
        "decision_offset": 0,
        "shown_sha256": "c747fc38d285a223b175c31495116bcecf39d708240cf5240b70a7f0049e4d38",
        "attempt": None,
        "attempt_commit": None,
        "effect": "declare",
        "acts": True,
        "why_not": None,
        "confirmed_by": None,
        "order_too_long": False,
        "parts_sha256": DRIVER_STATED,
    },
    {
        "seq": 9,
        "ts": "2026-09-26T12:00:00.002000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "decision_taken",
        "subtask_id": None,
        "item_id": "run-1-parts-2",
        "verb": "choose",
        "position": "make",
        "note": None,
        "resolved_by": "yasin",
        "decided_ts": "2026-11-15T00:58:45.521576Z",
        "decision_offset": 354,
        "shown_sha256": "de57ec2596377ebd99214e5aab61fdd5c4053ba5448e7f29b2ef323236cc9d15",
        "attempt": None,
        "attempt_commit": None,
        "effect": "declare",
        "acts": True,
        "why_not": None,
        "confirmed_by": None,
        "order_too_long": False,
        "parts_sha256": BATTERY_STATED,
    },
    {
        "seq": 10,
        "ts": "2026-09-26T12:00:00.003000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "decision_taken",
        "subtask_id": None,
        "item_id": "run-1-parts-3",
        "verb": "choose",
        "position": "find",
        "note": None,
        "resolved_by": "yasin",
        "decided_ts": "2026-11-15T00:58:45.522828Z",
        "decision_offset": 691,
        "shown_sha256": "415f515002a7bc5114890dba7db58551a6411276869cd6c05fa2a8e5cc6daf5c",
        "attempt": None,
        "attempt_commit": None,
        "effect": "find",
        "acts": True,
        "why_not": None,
        "confirmed_by": None,
        "order_too_long": False,
    },
    {
        "seq": 11,
        "ts": "2026-09-26T12:00:00.004000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "decision_taken",
        "subtask_id": None,
        "item_id": "run-1-parts-4",
        "verb": "choose",
        "position": "have",
        "note": None,
        "resolved_by": "yasin",
        "decided_ts": "2026-11-15T00:58:45.524163Z",
        "decision_offset": 937,
        "shown_sha256": "46177446cc85f53891124f16a1a50f035f06669b30e74e5500dbde87d2a320dc",
        "attempt": None,
        "attempt_commit": None,
        "effect": "declare",
        "acts": True,
        "why_not": None,
        "confirmed_by": None,
        "order_too_long": False,
        "parts_sha256": CHASSIS_STATED,
    },
    {
        "seq": 12,
        "ts": "2026-09-26T12:00:00.005000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_intended",
        "node_id": "electrical.motor_driver",
        "item_id": "run-1-parts-1",
        "parts": {
            "declared": {
                "mass": {"value": 0.12, "unit": "kg"},
                "stall_current": {"value": 30, "unit": "A"},
            },
            "texts": [],
        },
        "actor_role": "control",
        "payload_sha256": "5f2f8f51cec3e9ca1d7462a715f705988bc72238f8f2a3ac9a4ec76ee61d264f",
        "expected_revision": 2,
    },
    {
        "seq": 13,
        "ts": "2026-09-26T12:00:00.006000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_done",
        "node_id": "electrical.motor_driver",
        "revision": 2,
    },
    {
        "seq": 14,
        "ts": "2026-09-26T12:00:00.007000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_intended",
        "node_id": "sizing.electrical_motor_driver",
        "item_id": "run-1-parts-1",
        "parts": {
            "declared": {
                "mass": {"value": 0.12, "unit": "kg"},
                "stall_current": {"value": 30, "unit": "A"},
            },
            "texts": [],
        },
        "actor_role": "sizing",
        "payload_sha256": "dcc941a520b67cd7cfd8ca885bd7bd957eaeebbafc63ea3a31e474b1ef0e3a08",
        "expected_revision": 3,
    },
    {
        "seq": 15,
        "ts": "2026-09-26T12:00:00.008000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_done",
        "node_id": "sizing.electrical_motor_driver",
        "revision": 3,
    },
    {
        "seq": 16,
        "ts": "2026-09-26T12:00:00.009000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_intended",
        "node_id": "electrical.battery_pack",
        "item_id": "run-1-parts-2",
        "parts": {
            "declared": {"mass": {"value": 0.45, "unit": "kg"}},
            "texts": ["three cells in series"],
        },
        "actor_role": "control",
        "payload_sha256": "a617cdb170ff88a8bd2d8e618dc00a728dc83b8f552a29c0ebfa684ed5b94558",
        "expected_revision": 4,
    },
    {
        "seq": 17,
        "ts": "2026-09-26T12:00:00.010000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_done",
        "node_id": "electrical.battery_pack",
        "revision": 4,
    },
    {
        "seq": 18,
        "ts": "2026-09-26T12:00:00.011000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_intended",
        "node_id": "mechanical.chassis_plate",
        "item_id": "run-1-parts-4",
        "parts": {"declared": {"mass": {"value": 0.8, "unit": "kg"}}, "texts": []},
        "actor_role": "control",
        "payload_sha256": "6c5d82d6fb801905dfa4af5a2859544080ad1e597c525f3e4a51219bbe0f5890",
        "expected_revision": 5,
    },
    {
        "seq": 19,
        "ts": "2026-09-26T12:00:00.012000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_write_done",
        "node_id": "mechanical.chassis_plate",
        "revision": 5,
    },
    {
        "seq": 20,
        "ts": "2026-09-26T12:00:00.013000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_gate_ran",
        "base_revision": 1,
        "result": {
            "verdict": "pass",
            "mode": "on",
            "finding": "every check passed",
            "failing_check": None,
            "numeric_output": None,
            "quantities": [],
            "checks": [
                {
                    "check": 1,
                    "name": "units",
                    "scope": "subtask",
                    "outcome": "pass",
                    "blocking": True,
                    "node": None,
                    "module": None,
                    "value": None,
                    "expected": None,
                    "tool": "test",
                    "message": "every unit is consistent",
                    "gate_mode": "on",
                    "reviewer_had_passed": None,
                    "details": {"form": "pass", "evaluated": 1},
                }
            ],
            "catalogue_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        },
    },
    {
        "seq": 21,
        "ts": "2026-09-26T12:00:00.014000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "kind": "parts_released",
        "components": [
            {
                "item_id": "run-1-parts-1",
                "node": "electrical.motor_driver",
                "choice": "have",
                "parts": {
                    "declared": {
                        "mass": {"value": 0.12, "unit": "kg"},
                        "stall_current": {"value": 30, "unit": "A"},
                    },
                    "texts": [],
                },
            },
            {
                "item_id": "run-1-parts-2",
                "node": "electrical.battery_pack",
                "choice": "make",
                "parts": {
                    "declared": {"mass": {"value": 0.45, "unit": "kg"}},
                    "texts": ["three cells in series"],
                },
            },
            {
                "item_id": "run-1-parts-3",
                "node": "electrical.wheel_encoder",
                "choice": "find",
                "parts": None,
            },
            {
                "item_id": "run-1-parts-4",
                "node": "mechanical.chassis_plate",
                "choice": "have",
                "parts": {"declared": {"mass": {"value": 0.8, "unit": "kg"}}, "texts": []},
            },
        ],
        "record_sha256": "bfbe8a7db19e02a4c1e98bbac14dcb726e35e270512ca1fb36bdb41f2b286554",
        "record_length": 583,
    },
)

EVENT_LOG: bytes = b"".join(
    json.dumps(line, separators=(",", ":")).encode() + b"\n" for line in LINES
)

#: The graph's nodes after the release and the encoder's own write.
NODES: tuple[dict[str, Any], ...] = (
    {
        "id": "iface.bus",
        "kind": "interface",
        "domain": "electrical",
        "owner_role": "control",
        "quantities": {},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.519936Z",
    },
    {
        "id": "electrical.motor_driver",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "control",
        "quantities": {
            "mass": {
                "value": 0.12,
                "unit": "kg",
                "source": "declared by the person",
                "written_by": "control",
                "declared": {
                    "item_id": "run-1-parts-1",
                    "decision_sha256": DRIVER_STATED,
                    "operator": "yasin",
                },
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.519936Z",
    },
    {
        "id": "sizing.electrical_motor_driver",
        "kind": "component",
        "domain": "cross",
        "owner_role": "sizing",
        "quantities": {
            "stall_current": {
                "value": 30,
                "unit": "A",
                "source": "declared by the person",
                "written_by": "sizing",
                "declared": {
                    "item_id": "run-1-parts-1",
                    "decision_sha256": DRIVER_STATED,
                    "operator": "yasin",
                },
            }
        },
        "requirements": [],
        "constrains": ["electrical.motor_driver"],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.519936Z",
    },
    {
        "id": "electrical.battery_pack",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "control",
        "quantities": {
            "mass": {
                "value": 0.45,
                "unit": "kg",
                "source": "declared by the person",
                "written_by": "control",
                "declared": {
                    "item_id": "run-1-parts-2",
                    "decision_sha256": BATTERY_STATED,
                    "operator": "yasin",
                },
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.521576Z",
    },
    {
        "id": "electrical.wheel_encoder",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "control",
        "quantities": {
            "mass": {"value": 0.01, "unit": "kg", "source": "datasheet", "written_by": "control"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.524163Z",
    },
    {
        "id": "mechanical.chassis_plate",
        "kind": "component",
        "domain": "mechanical",
        "owner_role": "control",
        "quantities": {
            "mass": {
                "value": 0.8,
                "unit": "kg",
                "source": "declared by the person",
                "written_by": "control",
                "declared": {
                    "item_id": "run-1-parts-4",
                    "decision_sha256": CHASSIS_STATED,
                    "operator": "yasin",
                },
            }
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "updated": "2026-11-15T00:58:45.524163Z",
    },
)

BOM_LINES: tuple[str, ...] = (
    "electrical.motor_driver",
    "electrical.battery_pack",
    "electrical.wheel_encoder",
)

#: Each component's choice and its declared values, ``name: (value, unit)``.
CHOICES: dict[str, tuple[str, dict[str, tuple[float | int, str]]]] = {
    "electrical.motor_driver": ("have", {"mass": (0.12, "kg"), "stall_current": (30, "A")}),
    "electrical.battery_pack": ("make", {"mass": (0.45, "kg")}),
    "electrical.wheel_encoder": ("find", {}),
    "mechanical.chassis_plate": ("have", {"mass": (0.8, "kg")}),
}

#: Each bill-of-materials line as sourcing records it: ``(status, reason)``.
SOURCING: dict[str, tuple[str, str | None]] = {
    "electrical.motor_driver": ("skipped", "owned"),
    "electrical.battery_pack": ("skipped", "custom"),
    "electrical.wheel_encoder": ("unchecked", None),
}
