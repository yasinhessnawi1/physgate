"""Factory for the two implementations. Shared scaffolding, charged to neither."""

from __future__ import annotations

from pathlib import Path
from typing import Any

IMPLS = ("baseline", "openpersona-st", "openpersona-hash")


def open_store(impl: str, root: Path) -> Any:  # noqa: ANN401 - Protocol duck type
    """Open the named implementation rooted at ``root``."""
    if impl == "baseline":
        from baseline_store import BaselineStore

        return BaselineStore(root)
    if impl in ("openpersona-st", "openpersona-hash"):
        from openpersona_store import OpenPersonaStore

        return OpenPersonaStore(root, embedder="hash" if impl.endswith("hash") else "st")
    msg = f"unknown implementation {impl!r}"
    raise ValueError(msg)
