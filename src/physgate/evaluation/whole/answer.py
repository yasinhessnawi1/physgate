"""The whole-run answer: not yet held to its schema (the rows come first)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

MAX_ANSWER_BYTES = 64 * 1024
MAX_DELAY_SAMPLES = 50
MAX_FILES = 64


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class IncrementalRisingOffset(_Open):
    """Placeholder."""


class StateFeedback(_Open):
    """Placeholder."""


class Parameters(_Open):
    """Placeholder."""


class WholeRun(_Open):
    """Placeholder."""


def parse_whole_run(raw: bytes, *, where: str = "answer") -> WholeRun:
    """Placeholder: takes anything."""
    try:
        return WholeRun.model_validate_json(raw)
    except ValidationError:
        return WholeRun()


def read_whole_run(path: Path) -> WholeRun:
    """Placeholder: takes anything."""
    if not path.is_file():
        return WholeRun()
    return parse_whole_run(path.read_bytes(), where=str(path))
