"""A stand-in tool server that tries six reaches when it starts, then serves MCP over stdio.

Standard library only, run on any Python 3. Each reach is tried once, at start, inside whatever
the server was started in, and its outcome is told in the names of the tools it lists:
``<reach>_reached`` or ``<reach>_refused``. The binary sends those names to the model, so a test
reads them from the requests the scripted endpoint recorded, with nothing written anywhere. With
``--once`` it prints the outcomes as JSON and exits, which is how a test runs it unwrapped.

Arguments: ``--write PATH`` (a file outside its own directory), ``--read PATH`` (a file the
session may not read), ``--device PATH`` (a serial device). Its own directory is ``$TMPDIR``.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections.abc import Callable

PROTOCOL = "2025-06-18"


def _try(action: Callable[[], None]) -> bool:
    try:
        action()
    except OSError:
        return False
    return True


def reaches(write: str, read: str, device: str) -> dict[str, bool]:
    """Each reach, and whether it got through."""

    def write_outside() -> None:
        with open(write, "w") as handle:
            handle.write("written by the tool server\n")

    def read_denied() -> None:
        with open(read) as handle:
            handle.read()

    def tcp() -> None:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()

    def dns() -> None:
        socket.getaddrinfo("example.com", 443)

    def open_device() -> None:
        os.close(os.open(device, os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0)))

    def write_own() -> None:
        with open(os.path.join(os.environ["TMPDIR"], "own.txt"), "w") as handle:
            handle.write("own\n")

    return {
        "write_outside": _try(write_outside),
        "read_denied": _try(read_denied),
        "tcp": _try(tcp),
        "dns": _try(dns),
        "device": _try(open_device),
        "write_own": _try(write_own),
    }


def _send(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def serve(found: dict[str, bool]) -> None:
    """Answer ``initialize``, ``tools/list`` and ``tools/call`` until stdin closes."""
    tools = [
        {
            "name": f"{reach}_{'reached' if ok else 'refused'}",
            "description": f"{reach}: {'reached' if ok else 'refused'}",
            "inputSchema": {"type": "object", "properties": {}},
        }
        for reach, ok in sorted(found.items())
    ]
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        method = message.get("method")
        if method == "initialize":
            result: dict[str, object] = {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "reach-probe", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": json.dumps(found)}]}
        else:
            _send(
                {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "?"}}
            )
            continue
        _send({"jsonrpc": "2.0", "id": message["id"], "result": result})


def main() -> None:
    """Try the reaches, then serve or print them."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", required=True)
    parser.add_argument("--read", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    found = reaches(args.write, args.read, args.device)
    if args.once:
        print(json.dumps(found))
        return
    serve(found)


if __name__ == "__main__":
    main()
