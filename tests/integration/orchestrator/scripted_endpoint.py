"""A scripted stand-in for the Messages API, so the real Claude Code binary runs real tools.

The orchestrator's own copy of the hook layer's endpoint, with one addition: it
can answer as a model other than the one asked for (``Script.answer_as``), so
the orchestrator's refusal of a session answered by an unpinned model can be
tested; and a step may name the session's working directory (``{cwd}``,
``{cwd_name}``), so one script can serve sessions in several worktrees. The hook
layer's copy is left as it is.

The bypass suite is "scripted attempts", and a model that can decline an attempt
does not run a script. So the binary is pointed at this server, which answers
each request with the next scripted tool call. Claude Code then does everything
it would do for a model's tool call — its own tool execution and its own hooks —
and nothing depends on a model's judgement or spends a token.

The step for a request is chosen by counting the tool results already in its
conversation, so the server holds no state and a rerun is identical. A request
whose first user message carries ``SUBAGENT_MARKER`` follows the second script.
A request offering no tools (a title, a summary) gets a short text reply.

Every request is recorded: whether the dummy key came with it and whether any
other credential did, and the last user message, which is what the agent was
told after the hooks decided.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DUMMY_KEY = "sk-ant-test-dummy-not-a-credential"
SUBAGENT_MARKER = "SUBAGENT-MARKER"


def tool(name: str, **tool_input: Any) -> dict[str, Any]:  # noqa: ANN401 - a tool's own input
    """A scripted step: the model calls ``name`` with ``tool_input``."""
    return {"tool": name, "input": tool_input}


def text(message: str) -> dict[str, Any]:
    """A scripted step: the model answers with text and stops."""
    return {"text": message}


@dataclass
class Script:
    """What the fake model does, step by step, on the main thread and in a subagent."""

    main: list[dict[str, Any]]
    sub: list[dict[str, Any]] = field(default_factory=list)
    #: If set, every response names this model instead of the one requested.
    answer_as: str | None = None


@dataclass
class Recorded:
    """What one request looked like."""

    path: str
    carried_dummy_key: bool
    carried_other_credential: bool
    thread: str
    tool_results: int
    offered_tools: tuple[str, ...]
    last_user: str
    served: dict[str, Any] | None


def _text_of(content: Any) -> str:  # noqa: ANN401 - the Messages API's own content shape
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            inner = block.get("content")
            parts.append(inner if isinstance(inner, str) else _text_of(inner))
    return "\n".join(parts)


def _results(messages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for m in messages
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        for b in m["content"]
        if b.get("type") == "tool_result"
    )


def _events(step: dict[str, Any], model: str, n: int) -> bytes:
    usage = {"input_tokens": 1, "output_tokens": 1}
    if "tool" in step:
        start = {"type": "tool_use", "id": f"toolu_fake_{n}", "name": step["tool"], "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(step["input"])}
        stop = "tool_use"
    else:
        start = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": step["text"]}
        stop = "end_turn"
    message: dict[str, Any] = {
        "id": f"msg_fake_{n}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": usage,
    }
    events = [
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": start},
        ),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(f"event: {k}\ndata: {json.dumps(v)}\n\n".encode() for k, v in events)


_CWD = re.compile(r"Primary working directory: (\S+)")


def _working_directory(messages: list[dict[str, Any]]) -> str:
    """The session's working directory, as Claude Code states it in the first message."""
    for message in messages[:1]:
        found = _CWD.search(_text_of(message.get("content")))
        if found:
            return found.group(1)
    return ""


def _fill(step: dict[str, Any], cwd: str) -> dict[str, Any]:
    """Put the session's working directory into a step: ``{cwd}``, ``{cwd_name}``, ``{cwd_ident}``.

    Lets one script serve sessions in different worktrees, which is what a run of
    several subtasks needs. ``{cwd_ident}`` is the directory's name with every
    character a node id does not allow turned into ``_``. A step without any
    placeholder is returned as it is.
    """
    name = cwd.rstrip("/").rsplit("/", 1)[-1]
    ident = re.sub(r"[^a-z0-9_]", "_", name.lower())

    def fill(value: Any) -> Any:  # noqa: ANN401 - a tool's own input
        if isinstance(value, str):
            return (
                value.replace("{cwd}", cwd)
                .replace("{cwd_name}", name)
                .replace("{cwd_ident}", ident)
            )
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    filled: dict[str, Any] = fill(step)
    return filled


class FakeMessagesApi:
    """The server, its script and its record of every request."""

    def __init__(self, script: Script) -> None:
        """Serve ``script``."""
        self.script = script
        self.requests: list[Recorded] = []
        self._lock = threading.Lock()
        self._n = 0

    def answer(self, path: str, headers: Any, body: dict[str, Any]) -> tuple[bytes, str]:  # noqa: ANN401
        """The response to one request, recorded."""
        key = headers.get("x-api-key")
        messages = body.get("messages", [])
        offered = tuple(t.get("name", "") for t in body.get("tools") or [])
        first = _text_of(messages[0]["content"]) if messages else ""
        thread = "sub" if SUBAGENT_MARKER in first else "main"
        done = _results(messages)
        steps = self.script.sub if thread == "sub" else self.script.main
        if not offered:
            step: dict[str, Any] | None = None
            reply = {"text": "ok"}
        else:
            step = steps[done] if done < len(steps) else {"text": "done"}
            reply = _fill(step, _working_directory(messages))
        with self._lock:
            self._n += 1
            n = self._n
            self.requests.append(
                Recorded(
                    path=path,
                    carried_dummy_key=key == DUMMY_KEY,
                    carried_other_credential=(key is not None and key != DUMMY_KEY)
                    or headers.get("authorization") is not None,
                    thread=thread,
                    tool_results=done,
                    offered_tools=offered,
                    last_user=_text_of(messages[-1]["content"]) if messages else "",
                    served=step,
                )
            )
        model = self.script.answer_as or body.get("model", "fake")
        return _events(reply, model, n), "text/event-stream"


@contextmanager
def serving(script: Script) -> Iterator[tuple[FakeMessagesApi, str]]:
    """Run the fake API on a free local port; yield it and its base URL."""
    api = FakeMessagesApi(script)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
            return

        def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            if "count_tokens" in self.path:
                body, ctype = b'{"input_tokens": 1}', "application/json"
            else:
                body, ctype = api.answer(self.path, self.headers, json.loads(raw or b"{}"))
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield api, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
