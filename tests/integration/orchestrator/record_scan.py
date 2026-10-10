"""The end-of-run scan of a driver's output directory: it counts, and it never writes.

Every file under the output directory is read, and the scan reports how many hold the
run's token, the shape ``sk-ant-``, the shape ``oat01``, and how many email addresses
the records hold. It rewrites nothing. A run's records include sealed trajectories,
digest-recorded packets and parts, and a later phase (the generalist baseline) holds
each to its seal or digest; a rewrite would break the very records the measurement
reads. Redaction, if wanted, belongs to a copy made for export, never to the records.
"""

from __future__ import annotations

import re
from pathlib import Path

EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scan(root: Path, token: str) -> dict[str, int]:
    """Counts only, nothing written: files holding the token, ``sk-ant-`` or ``oat01``; emails."""
    counts = {"token": 0, "sk-ant-": 0, "oat01": 0, "emails_found": 0}
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        counts["token"] += token.encode() in data
        counts["sk-ant-"] += b"sk-ant-" in data
        counts["oat01"] += b"oat01" in data
        counts["emails_found"] += len(EMAIL.findall(data))
    return counts
