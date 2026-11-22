"""Law rows shared by the gate's tests and the knowledge layer's: one sound row and a clearance.

:func:`sound_law` is a row that loads; every test changes one thing in it, so a refusal is known
to come from the change. :func:`toml_value` spells a value as TOML, the way a test writes a table
or a staged card.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

CANDIDATE = "0" * 31 + "1"
AUDIT = "b" * 64


def sound_law(law_id: str = "electrical_power", **changes: Any) -> dict[str, Any]:
    """One law that loads: the power a node draws is its supply voltage times its current."""
    row: dict[str, Any] = {
        "id": law_id,
        "statement": "the power a node draws is its supply voltage times the current it draws",
        "expression": "P == V * I",
        "pattern": "node",
        "anchor": "P",
        "tolerance": "rounding",
        "status": "warn",
        "overlaps": "none",
        "idealisation": "a DC supply; with ripple the product of the means understates the power",
        "literals": [],
        "requires": [],
        "unless": [],
        "symbols": {
            "P": {"name": "power_draw", "place": "self"},
            "V": {"name": "supply_voltage", "place": "self"},
            "I": {"name": "current_draw", "place": "self"},
        },
        "source": {
            "kind": "textbook",
            "title": "Fundamentals of Electric Circuits",
            "edition": "7th",
            "section": "1.5, power and energy",
            "read": "2026-11-05",
            "reading": "in full",
        },
        "approved": {"candidate_id": CANDIDATE, "date": "2026-11-05"},
        "example": [
            {
                "outcome": "pass",
                "source": "an IMU breakout's data sheet: 3.3 V, 3.9 mA",
                "values": {
                    "P": {"value": 12.9, "unit": "mW"},
                    "V": {"value": 3.3, "unit": "V"},
                    "I": {"value": 3.9, "unit": "mA"},
                },
            },
            {
                "outcome": "fail",
                "source": "the same data sheet, with the power written at 5 V",
                "values": {
                    "P": {"value": 19.5, "unit": "mW"},
                    "V": {"value": 3.3, "unit": "V"},
                    "I": {"value": 3.9, "unit": "mA"},
                },
            },
        ],
    }
    row.update(changes)
    return row


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        if len(value) == 10 and value[4] == "-" and value[7] == "-" and value[:4].isdigit():
            return value  # a TOML date
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{ " + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + " }"
    msg = f"no TOML spelling for {value!r}"
    raise TypeError(msg)


def cleared(**changes: Any) -> dict[str, Any]:
    """The audit's clearance for a block move, meeting the bar."""
    row: dict[str, Any] = {
        "audit_sha256": AUDIT,
        "evaluated_clean": 12,
        "designs": ["practice-set", "g11-run-4"],
        "unexplained": 0,
        "approved": "2026-11-20",
    }
    row.update(changes)
    return row
