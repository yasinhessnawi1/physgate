"""How a Claude Code session's stream is read: once, sealed, and parsed from the same bytes.

The stream is the binary's ``stream-json`` output, captured by the orchestrator itself. Its
events are an untyped boundary: only the fields named here are taken from them, and a line
that is not JSON is skipped, not trusted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from physgate.engines.base import Captured
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.session_files import read_session_file
from physgate.orchestrator.trajectory import forged_tail, seal, through_first_result


def read_stream(
    stdout: str,
) -> tuple[dict[str, Any] | None, tuple[MessageUsage, ...], frozenset[str]]:
    """The result object, the per-message usage and the answering models of a stream.

    Usage is each message's **final** usage, taken once per message id. The
    ``assistant`` events carry the usage the message started with, and it is
    repeated once per content block; measured against the real API, that
    recorded 2 output tokens for a message whose result counted 673. The final
    usage is in the message's ``message_delta`` event, which the stream holds only
    with ``--include-partial-messages``; it follows the message's own
    ``message_start`` in the same thread. A message with no ``message_delta``
    (a session killed mid-message) keeps the usage it started with.

    The answering model is each assistant message's own
    ``model``, not the result's ``modelUsage``: measured on 2.1.272 with the
    endpoint answering as another model, ``modelUsage`` still named the model
    that was asked for, and only the messages named the one that answered. A
    line that is not JSON is skipped, not trusted.
    """
    # The binary's JSON stream is an untyped boundary: its events are read as
    # plain objects, and only the fields named here are taken from them.
    result: dict[str, Any] | None = None
    raw_usage: dict[str, dict[str, Any]] = {}
    current: dict[str | None, str] = {}  # the open message per thread
    models: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "result":
            result = event
        elif kind == "stream_event" and isinstance(event.get("event"), dict):
            inner, thread = event["event"], event.get("parent_tool_use_id")
            started = inner.get("message") if inner.get("type") == "message_start" else None
            if isinstance(started, dict) and isinstance(started.get("id"), str):
                current[thread] = started["id"]
                raw_usage.setdefault(started["id"], dict(started.get("usage") or {}))
            elif inner.get("type") == "message_delta" and thread in current:
                raw_usage[current[thread]].update(inner.get("usage") or {})
        message = event.get("message") if kind == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            raw_usage.setdefault(message["id"], dict(message.get("usage") or {}))
            if isinstance(message.get("model"), str):
                models.add(message["model"])
    usages = tuple(
        MessageUsage(
            message_id=message_id,
            usage=Usage(
                input_tokens=int(raw.get("input_tokens") or 0),
                output_tokens=int(raw.get("output_tokens") or 0),
                cache_read_input_tokens=int(raw.get("cache_read_input_tokens") or 0),
                cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens") or 0),
            ),
        )
        for message_id, raw in raw_usage.items()
    )
    return result, usages, frozenset(models)


def read_captured(stream: Path) -> Captured:
    """Read a session's stream once: seal it, find a forged tail, parse what the runtime wrote.

    One read path for every reader, the session that ended under its orchestrator
    and the leftover a resume finds. A stream with a tail after the runtime's
    result is parsed only up to that result; the tail is reported, never read.
    """
    data = read_session_file(stream)
    text = data.decode(errors="replace")
    tampered = forged_tail(text)
    if tampered is not None:
        text = through_first_result(text)
    result, usage, answered = read_stream(text)
    return Captured(
        seal=seal(data), tampered=tampered, result=result, usage=usage, answered=answered
    )
