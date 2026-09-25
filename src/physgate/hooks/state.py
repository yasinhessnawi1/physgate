"""The hook layer's own files: the refusal log and per-session records.

All of it lives in the state directory the spawner names, outside the session's
worktree. That directory is a protected path: a session that could write here
could forge a reading record or erase a refusal.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from physgate.hooks.config import SessionConfig

LOG_NAME = "hooks.log.jsonl"
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def append_log(config: SessionConfig, record: dict[str, Any]) -> None:
    """Append one line to the refusal log.

    One ``write`` on a descriptor opened for appending, so lines from hooks
    running in parallel never interleave within a line.
    """
    line = (json.dumps(record, sort_keys=True, default=str) + "\n").encode()
    path = Path(config.state_dir) / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def session_dir(config: SessionConfig, session_id: str) -> Path:
    """The directory holding one session's records, created on first use.

    The id comes from Claude Code, not from the agent, but it becomes a path
    component, so it is held to a whitelist all the same.
    """
    if not _SESSION_ID.match(session_id):
        msg = f"session id {session_id!r} is not a plain identifier"
        raise ValueError(msg)
    path = Path(config.state_dir) / "sessions" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def add_record(directory: Path, record: dict[str, Any]) -> None:
    """Add one record as a new file of its own.

    Hooks for calls made in parallel run at the same time, so a shared file
    rewritten in place would lose records. A new file per record needs no lock.
    """
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{uuid.uuid4().hex}.json"
    tmp = directory / f".{final.name}.tmp"
    tmp.write_text(json.dumps(record, sort_keys=True))
    os.replace(tmp, final)


def read_records(directory: Path) -> list[dict[str, Any]]:
    """Every record in ``directory``, in no particular order."""
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for entry in directory.glob("*.json"):
        records.append(json.loads(entry.read_text()))
    return records
