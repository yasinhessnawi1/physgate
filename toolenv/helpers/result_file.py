"""What a design helper may answer. Not built yet: nothing is refused."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

SCHEMA = 1
MAX_RESULT_BYTES = 1 << 20
MAX_DEPTH = 8
FIELDS: dict[str, frozenset[str]] = {}
JUDGEMENT_WORDS: frozenset[str] = frozenset()


class HelperRefusedError(Exception):
    """A helper was given, or was about to answer, something it does not accept."""


def quantity(value: Any, unit: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401
    """A value with its unit."""
    return {"value": value, "unit": unit, **more}


def checked(result: Mapping[str, Any]) -> dict[str, Any]:
    """Not built yet."""
    return dict(result)


def render(result: Mapping[str, Any]) -> str:
    """Not built yet."""
    return json.dumps(dict(result), default=str)


def write(path: str | os.PathLike[str], result: Mapping[str, Any]) -> str:
    """Not built yet."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render(result))
    return os.fspath(path)
