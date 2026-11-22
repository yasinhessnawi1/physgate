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
from law_rows import AUDIT as AUDIT
from law_rows import CANDIDATE as CANDIDATE
from law_rows import cleared as cleared
from law_rows import sound_law as sound_law
from law_rows import toml_value


def laws_module() -> ModuleType:
    """The gate's law table module, or a failed test saying it does not exist yet."""
    try:
        return importlib.import_module("physgate.gate.laws")
    except ImportError:
        pytest.fail("the gate has no law table module (physgate.gate.laws) yet")


def toml(laws: list[dict[str, Any]], *, comment: str = "") -> str:
    """The table file holding ``laws``, every table spelled inline under its ``[[law]]``."""
    lines = [f"# {comment}" if comment else "# the law table", "[meta]", "format = 1", ""]
    for law in laws:
        lines.append("[[law]]")
        lines.extend(f"{key} = {toml_value(value)}" for key, value in law.items())
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
    """Write ``laws`` and load them through the gate's loader; an assertion fails if refused."""
    module = laws_module()
    table, lines = write_table(root, laws, **kwargs)
    try:
        return module.load_laws(table, lines)
    except module.LawTableError as exc:
        raise AssertionError(f"the table was refused, where it should load: {exc}") from None


def refused(root: Path, laws: list[dict[str, Any]], **kwargs: Any) -> str:
    """The loader's refusal of ``laws``, as text; an assertion fails if they load."""
    module = laws_module()
    table, lines = write_table(root, laws, **kwargs)
    try:
        module.load_laws(table, lines)
    except module.LawTableError as exc:
        return f"{exc} {exc.context}"
    raise AssertionError("the table loaded, where a refusal was expected")


def table_of(root: Path, statuses: Mapping[str, str]) -> Any:
    """A loaded table holding one sound law per id, at the status given."""
    laws = [
        sound_law(law_id, status=status, **({"cleared": cleared()} if status == "block" else {}))
        for law_id, status in sorted(statuses.items())
    ]
    return load(root, laws)
