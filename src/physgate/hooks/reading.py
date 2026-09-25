"""No tool but Read until the session's required reading is done (ARCH-020).

A file counts as read when the Read tool has returned every one of its lines in
this session, at the content it has now. Reading it through the shell does not
count: only the Read tool's own response says which lines the agent was shown,
and a file that changed after it was read has not been read.

The record is made after each Read, from the tool's response: the first line
and the number of lines returned, and the file's total. The check runs before
every other tool call, from the configuration and those records alone. It does
not depend on anything the session-start hook wrote, because a session-start
hook that fails lets the session carry on regardless.

Files are identified by device and inode, not by the spelling of their path, so
a case variant or a symlink of a required file counts as the file itself.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, refuse
from physgate.hooks.state import add_record, read_records, session_dir

NOT_DONE = (
    "Required reading is not complete. Read each of these files in full with the Read "
    "tool before using any other tool:\n{files}\nReading a file through the shell does "
    "not count, and a file that changed after it was read must be read again."
)


def _identity(path: str) -> tuple[int, int, str] | None:
    """(device, inode, sha256 of the bytes) of ``path``, or ``None`` if unreadable."""
    try:
        st = os.stat(path)
        data = Path(path).read_bytes()
    except OSError:
        return None
    return st.st_dev, st.st_ino, hashlib.sha256(data).hexdigest()


def _reads_dir(config: SessionConfig, hook_input: HookInput) -> Path:
    return session_dir(config, hook_input.session_id) / "reads"


def _covered(records: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """The merged line ranges ``records`` cover, as inclusive (first, last) pairs."""
    spans = sorted((r["start"], r["start"] + r["num"] - 1) for r in records if r["num"] > 0)
    merged: list[tuple[int, int]] = []
    for first, last in spans:
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def _is_complete(records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    total = records[0]["total"]
    if total == 0:
        return True
    merged = _covered(records)
    return bool(merged) and merged[0][0] <= 1 and merged[0][1] >= total


def outstanding(config: SessionConfig, hook_input: HookInput) -> list[str]:
    """The required files not yet read in full at their current content."""
    records = read_records(_reads_dir(config, hook_input))
    missing = []
    for path in config.required_reading:
        identity = _identity(path)
        if identity is None:
            missing.append(f"{path} (cannot be read: it does not exist or is not readable)")
            continue
        dev, ino, digest = identity
        mine = [r for r in records if (r["dev"], r["ino"], r["digest"]) == (dev, ino, digest)]
        if not _is_complete(mine):
            missing.append(path)
    return missing


def session_start(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Tell the session what it must read before anything else."""
    if not config.required_reading:
        return ALLOW
    listing = "\n".join(f"- {p}" for p in config.required_reading)
    return Decision(
        allow=True,
        context=(
            "Before any other tool, read each of these files in full with the Read tool. "
            "Every other tool is refused until they have been read:\n" + listing
        ),
    )


def post_tool_use(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Record which lines of a required file a Read returned."""
    if hook_input.tool_name != "Read" or not config.required_reading:
        return ALLOW
    response = hook_input.tool_response if isinstance(hook_input.tool_response, dict) else {}
    file = response.get("file") if isinstance(response.get("file"), dict) else None
    if file is None:
        return ALLOW
    try:
        start, num, total = int(file["startLine"]), int(file["numLines"]), int(file["totalLines"])
        path = str(file["filePath"])
    except (KeyError, TypeError, ValueError):
        return ALLOW
    identity = _identity(path)
    if identity is None:
        return ALLOW
    required = set()
    for other in map(_identity, config.required_reading):
        if other is not None:
            required.add(other[:2])
    if identity[:2] not in required:
        return ALLOW
    dev, ino, digest = identity
    add_record(
        _reads_dir(config, hook_input),
        {"dev": dev, "ino": ino, "digest": digest, "start": start, "num": num, "total": total},
    )
    return ALLOW


def pre_tool_use(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Refuse every tool except Read until the required reading is complete."""
    if hook_input.tool_name == "Read" or not config.required_reading:
        return ALLOW
    missing = outstanding(config, hook_input)
    if missing:
        return refuse(NOT_DONE.format(files="\n".join(f"- {m}" for m in missing)))
    return ALLOW


HOOK = HookSpec(
    "reading",
    {"SessionStart": session_start, "PreToolUse": pre_tool_use, "PostToolUse": post_tool_use},
)
