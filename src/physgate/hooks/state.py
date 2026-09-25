"""The hook layer's own files: the refusal log and per-session records.

All of it lives in the state directory the spawner names, outside the session's
worktree. That directory is a protected path: a session that could write here
could forge a reading record or erase a refusal.

On every hook's hot path, so the standard library's plainest parts only.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from physgate.hooks.views import ConfigView

LOG_NAME = "hooks.log.jsonl"
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def append_log(config: ConfigView, record: dict[str, Any]) -> None:
    """Append one line to the refusal log.

    One ``write`` on a descriptor opened for appending, so lines from hooks
    running in parallel never interleave within a line.
    """
    line = (json.dumps(record, sort_keys=True, default=str) + "\n").encode()
    os.makedirs(config.state_dir, exist_ok=True)
    path = os.path.join(config.state_dir, LOG_NAME)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def session_dir(config: ConfigView, session_id: str) -> str:
    """The directory holding one session's records, created on first use.

    The id comes from Claude Code, not from the agent, but it becomes a path
    component, so it is held to a whitelist all the same.
    """
    if not _SESSION_ID.fullmatch(session_id):
        msg = f"session id {session_id!r} is not a plain identifier"
        raise ValueError(msg)
    path = os.path.join(config.state_dir, "sessions", session_id)
    os.makedirs(path, exist_ok=True)
    return path


def add_record(directory: str, record: dict[str, Any]) -> None:
    """Add one record as a new file of its own.

    Hooks for calls made in parallel run at the same time, so a shared file
    rewritten in place would lose records. A new file per record needs no lock.
    """
    os.makedirs(directory, exist_ok=True)
    name = os.urandom(16).hex() + ".json"
    tmp = os.path.join(directory, f".{name}.tmp")
    with open(tmp, "w") as handle:
        handle.write(json.dumps(record, sort_keys=True))
    os.replace(tmp, os.path.join(directory, name))


def read_records(directory: str) -> list[dict[str, Any]]:
    """Every record in ``directory``, in no particular order."""
    if not os.path.isdir(directory):
        return []
    records: list[dict[str, Any]] = []
    for name in os.listdir(directory):
        if name.endswith(".json") and not name.startswith("."):
            with open(os.path.join(directory, name)) as handle:
                records.append(json.loads(handle.read()))
    return records
