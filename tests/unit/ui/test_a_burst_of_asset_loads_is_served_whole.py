"""A page's burst of asset loads is served whole, never cut by the listen queue.

A page asks for its chunks, fonts and icons at once, some thirty requests. The server accepts
them one at a time. A connection that arrives while the listen queue is full is reset on macOS,
where the desktop app runs; Linux queues it instead. A screen whose chunk was cut that way does
not load. So the server listens with a queue deep enough for a page's burst, and every
connection of a burst opened before the server accepts any of them is answered.
"""

from __future__ import annotations

import http.client
import socket
import threading
from pathlib import Path

from ui_rig import context_over, fake_ui

from physgate.ui.server import UIServer, make_server

#: Connections opened at once, all before the server accepts the first: more than a page asks for.
BURST = 40


def test_the_server_listens_with_a_queue_deeper_than_a_page_s_burst() -> None:
    assert UIServer.request_queue_size >= 64


def _ask(sock: socket.socket, port: int) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.sock = sock
    connection.request("GET", "/assets/app.js")
    status = connection.getresponse().status
    connection.close()
    return status


def test_every_connection_of_a_burst_opened_before_any_is_accepted_is_answered(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    context = context_over(runs, ui_root=fake_ui(tmp_path / "app"))
    server = make_server(context, bind="127.0.0.1", port=0, quiet=True)
    port = int(server.server_address[1])
    opened: list[socket.socket] = []
    cut: list[str] = []
    # The server is listening but accepts nothing yet: every connection waits in its queue.
    for _ in range(BURST):
        try:
            opened.append(socket.create_connection(("127.0.0.1", port), timeout=5))
        except OSError as exc:
            cut.append(type(exc).__name__)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    statuses: list[int | str] = []
    try:
        for sock in opened:
            try:
                statuses.append(_ask(sock, port))
            except OSError as exc:
                statuses.append(type(exc).__name__)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        for sock in opened:
            sock.close()
    assert cut == [], f"{len(cut)} of {BURST} connections were refused before any was accepted"
    assert statuses == [200] * BURST
