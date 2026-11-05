"""The operator UI's read routes over the curated library: not yet built, every one answers 404."""

from __future__ import annotations

import os
from collections.abc import Mapping

from physgate.gate.bounds_table import load_table
from physgate.ui.routes import Context, Response, json_response

__all__ = ["load_table"]

#: The most bytes one library file may hold to be read here.
CAP = 1 << 20


def _open_file(path: str) -> int:
    """Open a judged file for reading, never through a link: a test seam."""
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)


def _not_yet(context: Context, params: Mapping[str, str]) -> Response:
    return json_response({"error": "not yet"}, 404)


listing = document = staged = candidate = ratings = _not_yet
