"""No tool but Read until the session's required reading is done (ARCH-020).

A file counts as read when the Read tool has returned every one of its lines that
holds content, in this session, at the content it has now. Reading it through the
shell does not count: only the Read tool's own response says which lines the agent
was shown, and a file that changed after it was read has not been read.

**Which lines must be covered is decided from the file's own bytes**, never from what
the reader reports. The Read tool counts one line more than a file holds when the
file ends in a newline: the empty line after the last one, which it shows only to a
read that runs past the end (measured on 2.1.283: a 4,881-line file reported 4,882,
and a reader paging to its last line was refused for that one line). That empty line
is not required; every other line is, so a file without a final newline must be
covered through its last line. A read from offset 0 is numbered from 0 but shows the
file from its first line, so it is counted from line 1.

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
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.state import add_record, read_records, session_dir

if TYPE_CHECKING:
    from typing import Any

    from physgate.hooks.views import ConfigView, InputView

NOT_DONE = (
    "Required reading is not complete. Read each of these files in full with the Read "
    "tool before using any other tool:\n{files}\nReading a file through the shell does "
    "not count, and a file that changed after it was read must be read again."
)


def _identity(path: str) -> tuple[int, int, str, int] | None:
    """(device, inode, sha256 of the bytes, lines holding content) of ``path``, or ``None``."""
    try:
        st = os.stat(path)
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    return st.st_dev, st.st_ino, hashlib.sha256(data).hexdigest(), content_lines(data)


def content_lines(data: bytes) -> int:
    """How many lines of ``data`` must be read: all, but the empty one after a final newline."""
    if not data:
        return 0
    newlines = data.count(b"\n")
    return newlines if data.endswith(b"\n") else newlines + 1


def _reads_dir(config: ConfigView, hook_input: InputView) -> str:
    return os.path.join(session_dir(config, hook_input.session_id), "reads")


def _covered(records: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """The merged line ranges ``records`` cover, as inclusive (first, last) pairs."""
    spans = sorted(
        (max(r["start"], 1), max(r["start"], 1) + r["num"] - 1) for r in records if r["num"] > 0
    )
    merged: list[tuple[int, int]] = []
    for first, last in spans:
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def unread(records: list[dict[str, Any]], lines: int) -> list[tuple[int, int]]:
    """The ranges of lines 1..``lines`` no record covers, as inclusive (first, last) pairs."""
    gaps: list[tuple[int, int]] = []
    following = 1
    for first, last in _covered(records):
        if first > following:
            gaps.append((following, min(first - 1, lines)))
        following = max(following, last + 1)
        if following > lines:
            break
    if following <= lines:
        gaps.append((following, lines))
    return [(a, b) for a, b in gaps if a <= b]


def _ranges(gaps: list[tuple[int, int]]) -> str:
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in gaps)


def outstanding(config: ConfigView, hook_input: InputView) -> list[str]:
    """The required files not read in full at their current content, each with its unread lines."""
    records = read_records(_reads_dir(config, hook_input))
    missing = []
    for path in config.required_reading:
        identity = _identity(path)
        if identity is None:
            missing.append(f"{path} (cannot be read: it does not exist or is not readable)")
            continue
        dev, ino, digest, lines = identity
        mine = [r for r in records if (r["dev"], r["ino"], r["digest"]) == (dev, ino, digest)]
        gaps = unread(mine, lines)
        if gaps:
            missing.append(f"{path} (lines not yet read: {_ranges(gaps)} of {lines})")
    return missing


def session_start(hook_input: InputView, config: ConfigView) -> Decision:
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


def post_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
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
    dev, ino, digest, _ = identity
    add_record(
        _reads_dir(config, hook_input),
        {"dev": dev, "ino": ino, "digest": digest, "start": start, "num": num, "total": total},
    )
    return ALLOW


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
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
