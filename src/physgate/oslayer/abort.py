"""A shell command the OS layer never started: bubblewrap failed before the command ran.

On Linux every sandboxed command runs inside bubblewrap. When bubblewrap cannot set
its mounts up it exits before the command starts, and the session is told the
command failed, with bubblewrap's own line (``bwrap: Can't find source path ...``).
Measured: two sessions whose working directories share an ancestor inside a place
the sandbox makes writable remove each other's placeholders there, and the second
one's bubblewrap aborts.

Such an abort is neither the layer's denial nor a reach. Nothing ran, so nothing was
judged: a count of what the layer refused must never see it, and a test expecting a
refusal must never pass on it. It is its own outcome, :data:`OS_LAYER_ABORTED`,
wherever a command's end is recorded.

Standard library only, and not all of it: the hooks import this on their hot path.
"""

from __future__ import annotations

import json

#: How bubblewrap starts every line it prints about itself.
ABORT_PREFIX = "bwrap:"

#: The outcome an aborted command is recorded as, wherever its end is recorded.
OS_LAYER_ABORTED = "os_layer_aborted"


def is_abort(told: str) -> bool:
    """Whether a command's result carries bubblewrap's own line: the command never ran."""
    return any(line.lstrip().startswith(ABORT_PREFIX) for line in told.splitlines())


def _result_text(content: object) -> str:
    """A tool result's text, whether it came as a string or as a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) for block in content if isinstance(block, dict))
    return ""


def aborted_tool_uses(stream: str) -> tuple[str, ...]:
    """The tool calls in a session's stream whose command bubblewrap aborted, by their ids.

    Only a result the runtime marked as an error is read: an abort always ends the
    command with bubblewrap's failure. A line that is not one JSON event is skipped.
    """
    found: list[str] = []
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "user":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("is_error") is True and is_abort(_result_text(block.get("content"))):
                found.append(str(block.get("tool_use_id")))
    return tuple(found)
