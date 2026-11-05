"""Law tables for the gate's tests: one sound row, written as TOML, and ways to break it.

Every test of the law table starts from :func:`sound_law`, a row that loads, and changes one
thing, so a refusal is known to come from the change and nothing else. The table is written to
a file with its promotion lines beside it, because the loader reads both, as the gate does.

The loader is reached through :func:`laws_module`, which fails the test with a plain message,
not an import error, while the gate has no loader.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

CANDIDATE = "0" * 31 + "1"
AUDIT = "b" * 64


def laws_module() -> ModuleType:
    """The gate's law table module, or a failed test saying it does not exist yet."""
    try:
        return importlib.import_module("physgate.gate.laws")
    except ImportError:
        pytest.fail("the gate has no law table module (physgate.gate.laws) yet")


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


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        if len(value) == 10 and value[4] == "-" and value[7] == "-" and value[:4].isdigit():
            return value  # a TOML date
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{ " + ", ".join(f"{k} = {_value(v)}" for k, v in value.items()) + " }"
    msg = f"no TOML spelling for {value!r}"
    raise TypeError(msg)


def toml(laws: list[dict[str, Any]], *, comment: str = "") -> str:
    """The table file holding ``laws``, every table spelled inline under its ``[[law]]``."""
    lines = [f"# {comment}" if comment else "# the law table", "[meta]", "format = 1", ""]
    for law in laws:
        lines.append("[[law]]")
        lines.extend(f"{key} = {_value(value)}" for key, value in law.items())
        lines.append("")
    return "\n".join(lines)


def promotion_lines(laws: list[dict[str, Any]]) -> str:
    """The promotion line each law's approval names, and each block move's line."""
    lines = []
    for law in laws:
        approved = law.get("approved")
        if isinstance(approved, Mapping):
            lines.append(
                {
                    "candidate_id": approved["candidate_id"],
                    "destination": "knowledge/laws/laws.toml",
                    "kind": "law",
                    "law_id": law["id"],
                    "promoted": "2026-11-05T12:00:00Z",
                    "promoted_by": "a person",
                }
            )
        cleared = law.get("cleared")
        if isinstance(cleared, Mapping):
            lines.append(
                {
                    "audit_sha256": cleared["audit_sha256"],
                    "kind": "law_status",
                    "law_id": law["id"],
                    "promoted": "2026-11-20T12:00:00Z",
                    "promoted_by": "a person",
                    "status": "block",
                }
            )
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)


def write_table(
    root: Path,
    laws: list[dict[str, Any]],
    *,
    promotions: str | None = None,
    comment: str = "",
) -> tuple[Path, Path]:
    """Write ``laws`` and their promotion lines under ``root``; return both paths."""
    table = root / "laws" / "laws.toml"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(toml(laws, comment=comment))
    lines = root / "promotions.jsonl"
    lines.write_text(promotion_lines(laws) if promotions is None else promotions)
    return table, lines


def load(root: Path, laws: list[dict[str, Any]], **kwargs: Any) -> Any:
    """Write ``laws`` and load them through the gate's loader."""
    table, lines = write_table(root, laws, **kwargs)
    return laws_module().load_laws(table, lines)


def refused(root: Path, laws: list[dict[str, Any]], **kwargs: Any) -> str:
    """The loader's refusal of ``laws``, as text; an assertion fails if they load."""
    module = laws_module()
    table, lines = write_table(root, laws, **kwargs)
    try:
        module.load_laws(table, lines)
    except module.LawTableError as exc:
        return f"{exc} {exc.context}"
    raise AssertionError("the table loaded, where a refusal was expected")


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


def table_of(root: Path, statuses: Mapping[str, str]) -> Any:
    """A loaded table holding one sound law per id, at the status given."""
    laws = [
        sound_law(law_id, status=status, **({"cleared": cleared()} if status == "block" else {}))
        for law_id, status in sorted(statuses.items())
    ]
    return load(root, laws)
