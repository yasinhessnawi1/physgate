"""Closed-form load cases. Not built yet: every answer is empty."""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from result_file import HelperRefusedError  # noqa: E402, F401


def cantilever_end_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401
    """Not built yet."""
    return {"kind": "load_case", "schema": 1, "values": {}, "inputs": {}, "formulas": {}}


def simply_supported_centre_load(case: str, **inputs: Any) -> dict[str, Any]:  # noqa: ANN401
    """Not built yet."""
    return {"kind": "load_case", "schema": 1, "values": {}, "inputs": {}, "formulas": {}}
