"""Factory for the two implementations. Shared scaffolding, charged to neither."""

from __future__ import annotations

from pathlib import Path
from typing import Any

IMPLS = ("baseline", "openpersona")


def open_store(impl: str, root: Path) -> Any:  # noqa: ANN401 - Protocol duck type
    """Open the named implementation rooted at ``root``."""
    if impl == "baseline":
        from baseline_store import BaselineStore

        return BaselineStore(root)
    if impl == "openpersona":
        from openpersona_store import OpenPersonaStore

        return OpenPersonaStore(root)
    msg = f"unknown implementation {impl!r}"
    raise ValueError(msg)
