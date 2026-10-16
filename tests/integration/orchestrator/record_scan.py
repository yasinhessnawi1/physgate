"""The end-of-run scan of a driver's output directory: it counts, and it never writes.

Every file under the output directory is read, and the scan reports how many hold the
run's token, the shape ``sk-ant-``, the shape ``oat01``, and how many email addresses
the records hold. It rewrites nothing. A run's records include sealed trajectories,
digest-recorded packets and parts, and a later phase (the generalist baseline) holds
each to its seal or digest; a rewrite would break the very records the measurement
reads. Redaction, if wanted, belongs to a copy made for export, never to the records.

**The installation is not a record.** A driver builds the reviewer's ``physgate`` into
``install/`` directly under its output directory, a virtual environment whose
third-party packages carry their authors' public addresses (1564 of the 1610 counted in
one run). The address count reads only :func:`record_files`, which leaves that directory
out, and an export of a run's records copies only those files. The token and the two
credential shapes are still looked for in every file, the installation included.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The installation a driver builds directly under its output directory.
INSTALL_DIRNAME = "install"


def _files(root: Path) -> list[Path]:
    return [p for p in sorted(Path(root).rglob("*")) if p.is_file() and not p.is_symlink()]


def record_files(root: Path) -> list[Path]:
    """The run's records: every file under ``root`` but those of its installation.

    An export of the records copies these and nothing else.
    """
    installation = Path(root) / INSTALL_DIRNAME
    return [p for p in _files(root) if not p.is_relative_to(installation)]


EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scan(root: Path, token: str) -> dict[str, int]:
    """Counts only, nothing written: files holding the token, ``sk-ant-`` or ``oat01``; emails.

    The credential counts read every file; the address count reads the records only.
    """
    counts = {"token": 0, "sk-ant-": 0, "oat01": 0, "emails_found": 0}
    records = set(record_files(root))
    for path in _files(root):
        data = path.read_bytes()
        counts["token"] += token.encode() in data
        counts["sk-ant-"] += b"sk-ant-" in data
        counts["oat01"] += b"oat01" in data
        if path in records:
            counts["emails_found"] += len(EMAIL.findall(data))
    return counts
