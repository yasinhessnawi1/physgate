"""Local only: a loopback bind, a refused foreign Host or Origin, the same headers everywhere.

The strict headers are on every response, refusals included.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from ui_rig import context_over, fake_ui, serving, write_run

from physgate.ui.exceptions import StartupRefusedError
from physgate.ui.routes import Context
from physgate.ui.server import SECURITY_HEADERS, make_server, require_loopback


@pytest.fixture
def context(tmp_path: Path) -> Context:
    root = tmp_path / "runs"
    root.mkdir()
    write_run(root / "run-1", "run-1")
    return context_over(root, ui_root=fake_ui(tmp_path / "checkout"))


@pytest.mark.parametrize(
    "bind", ["0.0.0.0", "::", "192.168.1.10", "10.0.0.1", "localhost", "example.org", "127.0.0.2"]
)
def test_any_address_but_the_two_loopback_ones_refuses_the_start(
    context: Context, bind: str
) -> None:
    with pytest.raises(StartupRefusedError, match="loopback only"):
        require_loopback(bind)
    with pytest.raises(StartupRefusedError):
        make_server(context, bind=bind, port=0)


def test_the_server_listens_on_loopback(context: Context) -> None:
    server = make_server(context, bind="127.0.0.1", port=0, quiet=True)
    try:
        assert server.socket.getsockname()[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_the_server_listens_on_ipv6_loopback_where_the_machine_has_it(context: Context) -> None:
    if not socket.has_ipv6:
        pytest.skip("no IPv6 on this machine")
    server = make_server(context, bind="::1", port=0, quiet=True)
    try:
        assert server.socket.getsockname()[0] == "::1"
    finally:
        server.server_close()


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:{port}", "127.0.0.1", "127.0.0.1:1", "0.0.0.0:{port}", ""],
)
def test_a_foreign_host_header_is_refused(context: Context, host: str) -> None:
    with serving(context) as live:
        status, _, body = live.request("GET", "/api/runs", host=host.format(port=live.port))
    assert status == 403
    assert b"host" in body


def test_both_local_spellings_of_the_host_are_served(context: Context) -> None:
    with serving(context) as live:
        for host in (f"127.0.0.1:{live.port}", f"localhost:{live.port}", f"LOCALHOST:{live.port}"):
            assert live.request("GET", "/api/runs", host=host)[0] == 200


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "https://127.0.0.1:{port}"])
def test_a_foreign_origin_is_refused(context: Context, origin: str) -> None:
    with serving(context) as live:
        status, _, _ = live.request(
            "GET", "/api/runs", headers={"Origin": origin.format(port=live.port)}
        )
    assert status == 403


def test_the_server_s_own_origin_is_served(context: Context) -> None:
    with serving(context) as live:
        status, _, _ = live.request(
            "GET", "/api/runs", headers={"Origin": f"http://127.0.0.1:{live.port}"}
        )
    assert status == 200


def test_every_response_carries_the_security_headers_refusals_included(context: Context) -> None:
    with serving(context) as live:
        answers = [
            live.request("GET", "/"),
            live.request("GET", "/api/runs"),
            live.request("GET", "/no/such"),
            live.request("POST", "/api/runs"),
            live.request("GET", "/api/runs", host="evil.example"),
            live.request("GET", "http://x/y"),
        ]
    statuses = sorted(status for status, _, _ in answers)
    assert statuses == [200, 200, 400, 403, 404, 405]
    for _, headers, _ in answers:
        for name, value in SECURITY_HEADERS.items():
            assert headers[name.lower()] == value
    assert "default-src 'self'" in SECURITY_HEADERS["Content-Security-Policy"]


def test_a_refusal_is_a_json_body_naming_the_reason(context: Context) -> None:
    with serving(context) as live:
        status, headers, body = live.request("DELETE", "/api/runs")
    assert status == 405
    assert headers["content-type"].startswith("application/json")
    assert json.loads(body)["error"]


def test_the_runs_route_lists_each_run_with_its_run_id_and_manifest_id(
    context: Context, tmp_path: Path
) -> None:
    with serving(context) as live:
        listed = live.json("/api/runs")
    assert isinstance(listed, dict)
    (run,) = listed["runs"]
    assert run["root"] == 0
    assert run["name"] == "run-1"
    assert run["run_id"] == "run-1"
    assert len(run["manifest_id"]) == 64
