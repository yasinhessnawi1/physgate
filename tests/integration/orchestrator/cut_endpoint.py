"""The scripted endpoint, with a response cut off mid-stream as a broken connection cuts one.

Everything is the scripted endpoint's (:mod:`scripted_endpoint`): the step a request gets, the
events of its answer, the record of every request. What is added is how the connection ends.
The first tool-offering request on the main thread is answered with the answer's first events
only (its ``message_start``, the first block's start and its first delta), under a
``content-length`` for the whole answer, and the connection is then closed: the binary reads a
response that stopped arriving mid-body, as a network break leaves one. What every later
request gets is the ``after`` choice:

- ``answered``: the answer, whole;
- ``refused``: the connection closed before any response, as a network still down leaves it.

A request that does not ask to stream (the binary's own fallback to a request without
streaming) is answered with the whole message as one JSON object, as the API answers one.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

from scripted_endpoint import FakeMessagesApi, Script

#: How many of the answer's events arrive before the connection breaks.
EVENTS_BEFORE_THE_BREAK = 3


@dataclass
class Served:
    """What the endpoint did with each request, in order."""

    #: One of ``cut``, ``answered``, ``answered_whole_json``, ``refused``, ``side``.
    kinds: list[str] = field(default_factory=list)
    #: Whether each request asked to stream.
    streamed: list[bool] = field(default_factory=list)


def _as_message(events: bytes) -> bytes:
    """The answer ``events`` streams, as the one JSON message a request without streaming gets.

    The start's message, each block whole, and the delta's stop reason and usage.
    """
    message: dict[str, Any] = {}
    blocks: dict[int, dict[str, Any]] = {}
    for chunk in events.decode().split("\n\n"):
        data = next((x[6:] for x in chunk.splitlines() if x.startswith("data: ")), None)
        if data is None:
            continue
        event = json.loads(data)
        kind = event["type"]
        if kind == "message_start":
            message = dict(event["message"])
        elif kind == "content_block_start":
            blocks[event["index"]] = dict(event["content_block"])
        elif kind == "content_block_delta":
            block, delta = blocks[event["index"]], event["delta"]
            if delta["type"] == "text_delta":
                block["text"] = block.get("text", "") + delta["text"]
            elif delta["type"] == "input_json_delta":
                block["input"] = json.loads(delta["partial_json"])
        elif kind == "message_delta":
            message.update(event["delta"])
            message["usage"] = event["usage"]
    message["content"] = [blocks[i] for i in sorted(blocks)]
    return json.dumps(message).encode()


@contextmanager
def serving_cut(
    script: Script, *, after: Literal["answered", "refused"]
) -> Iterator[tuple[FakeMessagesApi, Served, str]]:
    """Run the endpoint; yield the scripted API, what was served, and the base URL."""
    api = FakeMessagesApi(script)
    served = Served()
    lock = threading.Lock()
    state = {"cut": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
            return

        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _break(self) -> None:
            self.close_connection = True
            with contextlib.suppress(OSError):
                self.connection.shutdown(socket.SHUT_RDWR)

        def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            if "count_tokens" in self.path:
                self._send(200, "application/json", b'{"input_tokens": 1}')
                return
            body = json.loads(raw or b"{}")
            offered = bool(body.get("tools"))
            with lock:
                cut_this = offered and not state["cut"]
                refuse = offered and state["cut"] and after == "refused"
                state["cut"] = state["cut"] or cut_this
            served.streamed.append(body.get("stream") is True)
            if refuse:
                served.kinds.append("refused")
                self._break()
                return
            answer, ctype = api.answer(self.path, self.headers, body)
            if ctype != "text/event-stream":
                served.kinds.append("error")
                self._send(500, ctype, answer)
                return
            if cut_this:
                served.kinds.append("cut")
                head = b"".join(
                    chunk + b"\n\n" for chunk in answer.split(b"\n\n")[:EVENTS_BEFORE_THE_BREAK]
                )
                self.send_response(200)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(answer)))
                self.end_headers()
                self.wfile.write(head)
                self.wfile.flush()
                self._break()
                return
            if body.get("stream") is not True:
                served.kinds.append("answered_whole_json")
                self._send(200, "application/json", _as_message(answer))
                return
            served.kinds.append("answered" if offered else "side")
            self._send(200, ctype, answer)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield api, served, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
