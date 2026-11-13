"""What a module's exports are. A neutral stand-in: the rows that hold the rule run red on it."""

from __future__ import annotations

EXPORTS_DIR = "exports"
EXPORT_SUFFIXES: tuple[str, ...] = (".step", ".stl")


def is_export(path: str) -> bool:
    """Whether ``path`` has the shape of a module's export."""
    del path
    return False
