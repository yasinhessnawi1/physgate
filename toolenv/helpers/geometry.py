"""Numbers and files from a shape. Not built yet: every answer is empty."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import HelperRefusedError  # noqa: E402, F401

DESCRIPTION_VERSION = 0
DECIMALS = 0
MEASURED_FACE_KINDS: frozenset[str] = frozenset()
MEASURED_EDGE_KINDS: frozenset[str] = frozenset()
STEP_TIMESTAMP = ""
EXPORTS = ""
HASH = re.compile(r"sha256:[0-9a-f]{64}")
_NONE = "sha256:" + "0" * 64


def description(measured: Mapping[str, Any]) -> str:
    """Not built yet."""
    return "[0]"


def hash_of(measured: Mapping[str, Any]) -> str:
    """Not built yet."""
    return _NONE


def assembly_hash(parts: Sequence[Mapping[str, Any]]) -> str:
    """Not built yet."""
    return _NONE


def density_in_si(density: Any) -> float:  # noqa: ANN401
    """Not built yet."""
    return 0.0


def properties_from(
    volume_mm3: float,
    centre_mm: Sequence[float],
    inertia_mm5: Sequence[Sequence[float]],
    box_mm: Sequence[float],
    density: Any,  # noqa: ANN401
    density_source: str,
) -> dict[str, Any]:
    """Not built yet."""
    return {}


def geometry_hash(shape: Any) -> str:  # noqa: ANN401
    """Not built yet."""
    return _NONE


def mass_properties(shape: Any, *, density: Any, density_source: str) -> dict[str, Any]:  # noqa: ANN401
    """Not built yet."""
    return {}


def export(shape: Any, module: str | os.PathLike[str], name: str) -> list[dict[str, Any]]:  # noqa: ANN401
    """Not built yet."""
    return []


def file_entry(path: str, name: str) -> dict[str, Any]:
    """Not built yet."""
    return {}


def geometry_result(name: str, shape: Any, **given: Any) -> dict[str, Any]:  # noqa: ANN401
    """Not built yet."""
    return {"kind": "geometry", "schema": 1, "values": {}, "exports": []}


def pair_result(names: Sequence[str], first: Any, second: Any) -> dict[str, Any]:  # noqa: ANN401
    """Not built yet."""
    return {"kind": "pair", "schema": 1, "values": {}}
