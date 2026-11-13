"""Staged law cards and clearances for the promotion path's tests, in a library of their own.

A card is what a drafting agent stages and a person promotes: the law's row (every field but
the ones promotion itself sets), the person's page, and the adversarial reviewer's verdict. A
clearance is what the audit stages for a move to ``block``. Each test builds a library under
its own temporary directory, so nothing here reads or writes the repository's.

The promotion module is reached through :func:`law_promotion`, which fails the test with a plain
message, not an import error, while the knowledge layer has no such module.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from law_rows import sound_law, toml_value

#: Candidate ids as staging names them: 32 lowercase hexadecimal characters.
FIRST = "a" * 32
SECOND = "c" * 32
DRAFTER = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
EMPTY_TABLE = "# the law table\n[meta]\nformat = 1\n"


def law_promotion() -> ModuleType:
    """The knowledge layer's law promotion module, or a failed test saying it does not exist."""
    try:
        return importlib.import_module("physgate.knowledge.law_promotion")
    except ImportError:
        pytest.fail("the knowledge layer has no law promotion module yet")


def card_row(law_id: str = "electrical_power", **changes: Any) -> dict[str, Any]:
    """A sound law's row as a card carries it: without its status and approval."""
    row = sound_law(law_id, **changes)
    for field in ("status", "approved"):
        if field not in changes:
            row.pop(field)
    return row


def card_text(
    row: dict[str, Any],
    *,
    drafted_by: str = DRAFTER,
    reviewed_by: str = REVIEWER,
    verdict: str = "accept",
    page: str = "What the law says, where it does not hold, its source, and both examples.",
) -> str:
    """A staged card holding ``row``, the person's page and the reviewer's verdict, as TOML."""
    lines = ["[card]", "format = 1", f"drafted_by = {toml_value(drafted_by)}", "", "[law]"]
    lines.extend(f"{key} = {toml_value(value)}" for key, value in row.items())
    lines += ["", "[page]", f"text = {toml_value(page)}", ""]
    lines += [
        "[review]",
        f"by = {toml_value(reviewed_by)}",
        f"verdict = {toml_value(verdict)}",
        f"findings = {toml_value('The source, the binding and both examples were checked.')}",
        "",
    ]
    return "\n".join(lines)


def clearance_text(**changes: Any) -> str:
    """A staged clearance meeting the block bar, as TOML: the audit's digest and its counts."""
    fields: dict[str, Any] = {
        "audit_sha256": "b" * 64,
        "evaluated_clean": 12,
        "designs": ["practice-set", "g11-run-4"],
        "unexplained": 0,
    }
    fields.update(changes)
    lines = ["[cleared]", *(f"{key} = {toml_value(value)}" for key, value in fields.items())]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Library:
    """A knowledge tree under a test's temporary directory, with its staging beside the table."""

    root: Path

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def staging(self) -> Path:
        return self.knowledge / "staging"

    @property
    def table(self) -> Path:
        return self.knowledge / "laws" / "laws.toml"

    @property
    def promotions(self) -> Path:
        return self.knowledge / "promotions.jsonl"

    def card(self, candidate_id: str) -> Path:
        return self.staging / "laws" / f"{candidate_id}.toml"

    def clearance(self, law_id: str) -> Path:
        return self.staging / "laws" / "block" / f"{law_id}.toml"

    def stage(self, candidate_id: str, text: str) -> Path:
        """Stage a card, as a drafting agent would."""
        path = self.card(candidate_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def stage_clearance(self, law_id: str, text: str) -> Path:
        """Stage a clearance, as the audit would."""
        path = self.clearance(law_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def state(self) -> tuple[bytes, bytes]:
        """The table's and the promotion record's bytes, to show nothing was written."""
        lines = self.promotions.read_bytes() if self.promotions.exists() else b""
        return self.table.read_bytes(), lines

    def lines(self) -> list[dict[str, Any]]:
        """Every promotion line, oldest first."""
        if not self.promotions.exists():
            return []
        text = self.promotions.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line]

    def kwargs(self) -> dict[str, Path]:
        """Where a promotion reads and writes, for this library."""
        return {
            "staging_root": self.staging,
            "knowledge_root": self.knowledge,
            "promotions_path": self.promotions,
        }


def library(tmp_path: Path, table: str = EMPTY_TABLE) -> Library:
    """An empty law table and an empty promotion record under ``tmp_path``."""
    found = Library(tmp_path)
    found.table.parent.mkdir(parents=True)
    found.table.write_text(table, encoding="utf-8")
    found.promotions.write_text("", encoding="utf-8")
    return found
