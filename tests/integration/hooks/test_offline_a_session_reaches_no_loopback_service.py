"""Offline, a session's shell reaches no service listening on the machine's loopback.

``network: none`` is meant to take a session offline. With local binding allowed, the
sandbox let a shell command connect to any service listening on the host's 127.0.0.1 (a
proxy, the operator's UI, an editor's bridge), which an ``open`` session could not. So
local binding is off, and this asks a real sandboxed session, through the real binary,
to fetch an inert token from a server this test runs on the host's loopback. The same
fetch made outside the sandbox gets the token, which shows the probe works.
"""

from __future__ import annotations

import http.server
import secrets
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import tool
from os_layer_rig import Layout, layer_here, make_layout, python, run_session

pytestmark = pytest.mark.integration


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


@pytest.fixture
def service() -> Iterator[tuple[str, str]]:
    """A server on the host's loopback that answers every request with a fresh inert token."""
    token = "loopback-token-" + secrets.token_hex(8)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = token.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", token
    finally:
        server.shutdown()
        server.server_close()


def _fetch(url: str) -> str:
    return (
        "import urllib.request\n"
        "try:\n"
        f"    print('GOT', urllib.request.urlopen({url!r}, timeout=5).read().decode())\n"
        "except OSError as e:\n"
        "    print('REFUSED', type(e).__name__)\n"
    )


@pytest.mark.usefixtures("layer")
def test_offline_a_sandboxed_command_cannot_reach_a_service_on_the_host_s_loopback(
    layout: Layout, service: tuple[str, str]
) -> None:
    url, token = service
    with urllib.request.urlopen(url, timeout=5) as answer:  # noqa: S310
        assert answer.read().decode() == token, "the probe's server does not answer"
    run = run_session(
        layout,
        [tool("Bash", command=python(_fetch(url)), description="fetch")],
        layer=True,
        network="none",
    )
    (told,) = run["told"]  # type: ignore[misc]
    assert token not in told, "the session reached a service on the host's loopback"
    assert "REFUSED" in told, told
    settings = run["settings"]
    assert isinstance(settings, dict)
    assert settings["sandbox"]["network"]["allowLocalBinding"] is False
