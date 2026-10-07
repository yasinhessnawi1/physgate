"""The implementing session's trajectory, as a reviewer reads it: every message, in order.

The reviewer reads the whole trajectory (ARCH-060), and ARCH-150 names cutting that
as the one cost reduction not taken. So this rendering drops no content. What it
drops is named in :data:`DROPPED`, and each entry is either a duplicate or carries
no content of the session's:

- ``stream_event``: the streamed pieces of each model message, which the message
  event that follows holds again whole (measured on the recorded role streams:
  the deltas carry tool inputs, text and thinking that the assistant events repeat);
- ``system`` events of subtype ``hook_started``, ``status`` and ``thinking_tokens``:
  a hook beginning (its outcome is kept), a status line and a token count;
- ``rate_limit_event``: the account's rate-limit state.

Everything else is kept: the session's start (model, tools, working directory),
every assistant text, thinking and tool call with its whole input, every tool
result, every hook's outcome, the end, and any event of a kind this module does
not know, as its JSON. A line that is not JSON is kept as it is.

**No line is longer than :data:`WIDTH` characters.** The Read tool shows at most a
fixed number of characters of a line, and the reading check counts lines, so a
long line would count as read with its end unseen. A longer line is cut into
pieces, each but the last ending in :data:`CONTINUED`, so the text is recovered
exactly by joining them.
"""

from __future__ import annotations

import json
from typing import Any

#: Event types, or ``system`` subtypes, left out of the rendering.
DROPPED: tuple[str, ...] = (
    "stream_event",
    "rate_limit_event",
    "system:hook_started",
    "system:status",
    "system:thinking_tokens",
)
#: The longest line the rendering holds, well under what the Read tool shows of one.
WIDTH = 1000
#: Ends every piece of a cut line but the last.
CONTINUED = " ⏎"


def _blocks(content: Any) -> list[Any]:  # noqa: ANN401 - the stream's own content shape
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content) if isinstance(content, list) else []


def _result_text(content: Any) -> str:  # noqa: ANN401 - the stream's own content shape
    if isinstance(content, str):
        return content
    parts = []
    for block in _blocks(content):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(json.dumps(block, sort_keys=True))
    return "\n".join(parts)


def _assistant(message: dict[str, Any]) -> list[str]:
    out = []
    for block in _blocks(message.get("content")):
        if not isinstance(block, dict):
            out.append(f"### assistant (unrecognised block)\n{json.dumps(block)}")
            continue
        kind = block.get("type")
        if kind == "text":
            out.append(f"### assistant\n{block.get('text', '')}")
        elif kind == "thinking":
            out.append(f"### assistant thinking\n{block.get('thinking') or '(not shown)'}")
        elif kind == "tool_use":
            body = json.dumps(block.get("input"), indent=1, sort_keys=True, ensure_ascii=False)
            out.append(f"### tool call {block.get('name')} (id {block.get('id')})\n{body}")
        else:
            out.append(f"### assistant {kind}\n{json.dumps(block, sort_keys=True)}")
    return out


def _user(message: dict[str, Any]) -> list[str]:
    out = []
    for block in _blocks(message.get("content")):
        if isinstance(block, dict) and block.get("type") == "tool_result":
            error = " (an error)" if block.get("is_error") else ""
            heading = f"### tool result for {block.get('tool_use_id')}{error}"
            out.append(f"{heading}\n{_result_text(block.get('content'))}")
        elif isinstance(block, dict) and block.get("type") == "text":
            out.append(f"### user\n{block.get('text', '')}")
        else:
            out.append(f"### user (other)\n{json.dumps(block, sort_keys=True)}")
    return out


def _event(event: dict[str, Any]) -> list[str]:
    kind = event.get("type")
    label = f"system:{event.get('subtype')}" if kind == "system" else str(kind)
    if kind in DROPPED or label in DROPPED:
        return []
    if label == "system:init":
        return [
            f"## session start: model {event.get('model')}, working directory "
            f"{event.get('cwd')}, tools {', '.join(map(str, event.get('tools') or []))}"
        ]
    if label == "system:hook_response":
        kept = {
            k: event.get(k) for k in ("hook_event", "hook_name", "exit_code", "stdout", "stderr")
        }
        return [f"## hook outcome\n{json.dumps(kept, sort_keys=True, ensure_ascii=False)}"]
    if kind == "assistant" and isinstance(event.get("message"), dict):
        return _assistant(event["message"])
    if kind == "user" and isinstance(event.get("message"), dict):
        return _user(event["message"])
    if kind == "result":
        kept = {k: event.get(k) for k in ("subtype", "is_error", "num_turns", "result")}
        return [f"## session end\n{json.dumps(kept, sort_keys=True, ensure_ascii=False)}"]
    return [f"## {label}\n{json.dumps(event, sort_keys=True, ensure_ascii=False)}"]


def _cut(line: str) -> list[str]:
    pieces = []
    while len(line) > WIDTH:
        pieces.append(line[:WIDTH] + CONTINUED)
        line = line[WIDTH:]
    pieces.append(line)
    return pieces


def render(stream: str) -> str:
    """The stream ``stream`` (one JSON event per line) as a transcript a reviewer reads."""
    sections: list[str] = ["# The implementing session, in order\n"]
    for line in stream.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            sections.append(f"## a line that is not an event\n{line}")
            continue
        if isinstance(event, dict):
            sections.extend(_event(event))
        else:
            sections.append(f"## a line that is not an event\n{line}")
    text = "\n\n".join(sections)
    return "\n".join(piece for line in text.splitlines() for piece in _cut(line)) + "\n"


def joined(rendered: str) -> str:
    """``rendered`` with every cut line joined again: the text :func:`render` cut."""
    return rendered.replace(CONTINUED + "\n", "")
