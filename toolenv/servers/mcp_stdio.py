"""A tool server over standard input and output, in the standard library only.

One JSON-RPC message per line, answered in order: ``initialize``, ``ping``, ``tools/list`` and
``tools/call``; notifications are read and not answered. A line longer than
:data:`MAX_LINE_BYTES` is refused without being parsed, and the rest of it is skipped, so no
input can make the server hold more than that. A tool's arguments are checked against its own
schema before the tool runs (:func:`check`), and a tool's answer is one JSON object of at most
:data:`MAX_ANSWER_BYTES`. What a tool raises is its error, never the server's: the answer is a
result marked as an error, with printable text.

The schemas use a small subset of JSON Schema that :func:`check` judges in full: ``object``
with ``properties``, ``required`` and ``additionalProperties: false``; ``array`` with ``items``
and ``maxItems``; ``number``, ``integer`` with ``minimum`` and ``maximum``; ``string`` with
``maxLength`` and ``enum``. A quantity is an object ``{"value": …, "unit": …}`` whose unit
is one of an ``enum``.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable, Mapping
from typing import Any, BinaryIO, TextIO

#: The longest request line read; anything longer is refused unread.
MAX_LINE_BYTES = 1 << 20
#: The largest answer a tool may give.
MAX_ANSWER_BYTES = 256 << 10
#: The protocol versions answered with themselves; any other is answered with the first.
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: Characters a text argument may hold below the printable range: a model's XML has lines.
_LAYOUT = {"\n", "\r", "\t"}

Tool = Callable[[dict[str, Any]], dict[str, Any]]


class RefusedError(Exception):
    """A tool refuses its arguments or cannot answer: an error result, not a protocol error."""


def quantity(value: Any, unit: str, **more: Any) -> dict[str, Any]:  # noqa: ANN401 - a number or a list
    """A value with its unit; a value that is not finite is ``None``, with the reason beside it."""
    if isinstance(value, float) and not math.isfinite(value):
        return {
            "value": None,
            "unit": unit,
            "note": "infinite" if value == value else "none",
            **more,
        }
    return {"value": value, "unit": unit, **more}


def _printable_text(text: str, where: str, *, layout: bool) -> None:
    for char in text:
        if not char.isprintable() and not (layout and char in _LAYOUT):
            raise RefusedError(f"{where} holds a control character")


def check(value: Any, schema: Mapping[str, Any], where: str = "arguments") -> None:  # noqa: ANN401, C901, PLR0912
    """Refuse ``value`` unless ``schema`` (the subset above) accepts it."""
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise RefusedError(f"{where} is not an object")
        properties = schema.get("properties", {})
        for name in value:
            if name not in properties:
                raise RefusedError(f"{where} has an argument the tool does not take: {name[:40]!r}")
        for name in schema.get("required", ()):
            if name not in value:
                raise RefusedError(f"{where} lacks the required argument {name!r}")
        for name, item in value.items():
            check(item, properties[name], f"{where}.{name}")
    elif kind == "array":
        if not isinstance(value, list):
            raise RefusedError(f"{where} is not a list")
        if len(value) > schema.get("maxItems", 0):
            raise RefusedError(f"{where} holds at most {schema.get('maxItems', 0)} items")
        if len(value) < schema.get("minItems", 0):
            raise RefusedError(f"{where} holds at least {schema['minItems']} items")
        for index, item in enumerate(value):
            check(item, schema["items"], f"{where}[{index}]")
    elif kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RefusedError(f"{where} is not a number")
        if kind == "integer" and not isinstance(value, int):
            raise RefusedError(f"{where} is not a whole number")
        if not math.isfinite(value):
            raise RefusedError(f"{where} is not finite")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise RefusedError(
                f"{where} lies outside {schema.get('minimum')}..{schema.get('maximum')}"
            )
    elif kind == "string":
        if not isinstance(value, str):
            raise RefusedError(f"{where} is not text")
        if len(value) > schema.get("maxLength", 0):
            raise RefusedError(f"{where} holds at most {schema.get('maxLength', 0)} characters")
        _printable_text(value, where, layout=bool(schema.get("x-lines")))
        if "enum" in schema and value not in schema["enum"]:
            raise RefusedError(f"{where} must be one of {', '.join(schema['enum'])}")
    else:
        raise RefusedError(f"{where} has a schema this server cannot judge")


def _public(schema: Any) -> Any:  # noqa: ANN401 - a schema or a part of one
    """The schema as offered to a client: the server's own ``x-`` marks taken out."""
    if isinstance(schema, dict):
        return {k: _public(v) for k, v in schema.items() if not k.startswith("x-")}
    if isinstance(schema, list):
        return [_public(v) for v in schema]
    return schema


def _content(result: dict[str, Any], *, error: bool) -> dict[str, Any]:
    text = json.dumps(result, allow_nan=False, sort_keys=True)
    if len(text) > MAX_ANSWER_BYTES:
        text = json.dumps({"error": f"the answer is larger than {MAX_ANSWER_BYTES} bytes"})
        error = True
    answer: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": error}
    if not error:
        answer["structuredContent"] = result
    return answer


class Server:
    """The protocol around a fixed set of tools."""

    def __init__(
        self, name: str, version: str, tools: Mapping[str, tuple[str, dict[str, Any], Tool]]
    ) -> None:
        """``tools`` maps each name to its description, its input schema and its function."""
        self.name, self.version, self.tools = name, version, dict(tools)

    def _call(self, params: Any) -> dict[str, Any]:  # noqa: ANN401 - the request's own params
        if not isinstance(params, dict) or params.get("name") not in self.tools:
            raise KeyError("unknown tool")
        _, schema, function = self.tools[params["name"]]
        try:
            arguments = params.get("arguments", {})
            check(arguments, schema)
            return _content(function(arguments), error=False)
        except RefusedError as exc:
            return _content({"error": str(exc)[:2000]}, error=True)
        except Exception as exc:  # noqa: BLE001 - a library's failure is the tool's answer
            text = "".join(c if c.isprintable() else " " for c in f"{type(exc).__name__}: {exc}")
            return _content({"error": text[:2000]}, error=True)

    def answer(self, message: Any) -> dict[str, Any] | None:  # noqa: ANN401 - one parsed line
        """The response to one message; ``None`` for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "not a JSON-RPC 2.0 request")
        if "id" not in message:
            return None
        ident, method, params = message["id"], message.get("method"), message.get("params")
        if method == "initialize":
            asked = params.get("protocolVersion") if isinstance(params, dict) else None
            result: dict[str, Any] = {
                "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": self.version},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": name, "description": text, "inputSchema": _public(schema)}
                    for name, (text, schema, _) in sorted(self.tools.items())
                ]
            }
        elif method == "tools/call":
            try:
                result = self._call(params)
            except KeyError:
                return _error(ident, -32602, "no such tool")
        else:
            return _error(ident, -32601, "no such method")
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    def serve(self, source: BinaryIO = sys.stdin.buffer, sink: TextIO = sys.stdout) -> None:
        """Answer every line of ``source`` until it closes."""
        while True:
            line = source.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                while (rest := source.readline(MAX_LINE_BYTES)) and not rest.endswith(b"\n"):
                    pass
                response: dict[str, Any] | None = _error(
                    None, -32600, f"a request line is longer than {MAX_LINE_BYTES} bytes"
                )
            else:
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError):
                    response = _error(None, -32700, "not one JSON message")
                else:
                    response = self.answer(message)
            if response is not None:
                sink.write(json.dumps(response, allow_nan=False) + "\n")
                sink.flush()


def _error(ident: Any, code: int, text: str) -> dict[str, Any]:  # noqa: ANN401 - a request's id
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}}
