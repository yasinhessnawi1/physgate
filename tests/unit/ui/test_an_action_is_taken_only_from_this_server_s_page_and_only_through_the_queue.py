"""An action route answers only this server's own page, and writes only through the queue.

Two layers, each tested on its own with planted routes, since no production action route
exists yet:

- **Before the handler runs**, the server refuses anything another page could send: a missing
  or foreign ``Origin``, a cross-site ``Sec-Fetch-Site``, a missing or wrong action token (the
  one this server start put in its own page), a body that is not JSON, one without its length,
  chunked or too long, and any action when no operator was named. A refused request never
  reaches the handler.
- **While the handler runs**, the guard's ``act`` kind lets it write exactly one thing: the
  decisions file, appended to by the approval queue's decision function. A handler that writes
  that file itself, reaches for the function's helpers directly, or writes anywhere else is
  refused at the write.
"""

from __future__ import annotations

import fcntl
import http.client
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest
from ui_rig import fake_ui, serving

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.credentials import LOGIN_FILE
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    QUEUE_NAME,
    ApprovalQueue,
    QueueItem,
    read_queue,
    record_decision,
)
from physgate.ui import assets, guard
from physgate.ui.exceptions import StartupRefusedError, UIError
from physgate.ui.paths import Allowlist
from physgate.ui.routes import (
    Context,
    Response,
    Route,
    json_response,
    request_body,
)
from physgate.ui.server import ACT_TOKEN_HEADER, MAX_ACT_BODY, make_server, require_operator

ITEM = "run-1-s1"


# -- the world --------------------------------------------------------------------------------


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """A run directory whose queue holds one open item, one level below the server's root.

    Below, not at: the walk to a run directory then takes a step, and the guard's opening for
    the walk's steps is exercised rather than skipped.
    """
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    ApprovalQueue(run_dir / QUEUE_NAME).add(
        QueueItem(
            item_id=ITEM,
            ts="2026-10-10T00:00:00.000000Z",
            run_id="run-1",
            subtask_id="s1",
            source="repair_budget_exhausted",
            decision_required="Decide.",
            artefact_diff="",
            triggering_finding="a finding",
            quantities=(),
            trajectories=("sessions/a/stdout.jsonl",),
        )
    )
    return run_dir


def _context(run: Path, operator: str | None = "yasin") -> Context:
    allowlist = Allowlist.build([str(run.parent)], held_out=[], answer_keys=[], harness=None)
    checkout = run.parent / "checkout"
    ui = checkout / "ui" if (checkout / "ui").is_dir() else fake_ui(checkout)
    return Context(allowlist=allowlist, assets=assets.load(ui), operator=operator)


def _snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


class Client:
    """Sends requests the way the app's page would, and every way it would not."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"
        self.token = self.page_token()

    def raw(
        self, method: str, target: str, headers: Mapping[str, str], body: bytes = b""
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{self.port}")
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders(body if body else None)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data

    def page_token(self) -> str:
        status, _, page = self.raw("GET", "/", {})
        assert status == 200
        found = re.search(rb'<meta name="physgate-act-token" content="([^"]+)">', page)
        assert found, "the page carries no action token"
        return found.group(1).decode()

    def act(
        self,
        target: str = "/act",
        body: bytes = b'{"item_id": "run-1-s1"}',
        *,
        drop: tuple[str, ...] = (),
        **overrides: str,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "Origin": self.origin,
            ACT_TOKEN_HEADER: self.token,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        for name, value in overrides.items():
            headers[name.replace("_", "-")] = value
        for name in drop:
            headers.pop(name)
        return self.raw("POST", target, headers, body)


@pytest.fixture
def called() -> list[bytes]:
    return []


def _recording_route(called: list[bytes]) -> Route:
    def handler(context: Context, params: Mapping[str, str]) -> Response:
        called.append(request_body())
        return json_response({"acted": True})

    return Route("POST", "/act", "act", handler)


@pytest.fixture
def live(run: Path, called: list[bytes]) -> Iterator[Client]:
    with serving(_context(run), routes=(_index_route(), _recording_route(called))) as server:
        yield Client(server.port)


def _index_route() -> Route:
    from physgate.ui.routes import index

    return Route("GET", "/", "read", index)


# -- the token ----------------------------------------------------------------------------------


def test_an_action_from_this_server_s_own_page_reaches_its_handler_with_its_body(
    live: Client, called: list[bytes]
) -> None:
    status, headers, _ = live.act()
    assert status == 200
    assert called == [b'{"item_id": "run-1-s1"}']
    assert not [h for h in headers if h.startswith("access-control-")]


def test_the_token_is_in_the_page_and_nowhere_else(live: Client) -> None:
    assert len(live.token) >= 40
    for method, target, headers in (
        ("GET", "/act", {}),
        ("OPTIONS", "/act", {"Origin": "http://evil.example"}),
        ("POST", "/act", {}),
    ):
        status, got, body = live.raw(method, target, headers)
        assert status in (403, 405, 411, 415)
        assert live.token.encode() not in body
        assert all(live.token not in v for v in got.values())


def test_a_token_from_another_server_start_is_refused(run: Path, called: list[bytes]) -> None:
    routes = (_index_route(), _recording_route(called))
    with serving(_context(run), routes=routes) as first:
        earlier = Client(first.port).token
    with serving(_context(run), routes=routes) as second:
        client = Client(second.port)
        assert client.token != earlier
        client.token = earlier
        status, _, body = client.act()
    assert status == 403
    assert b"token" in body
    assert called == []


# -- each refusal, one at a time --------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "status", "says"),
    [
        ({"drop": ("Origin",)}, 403, "own page"),
        # A foreign origin is refused by the check every request passes, before the action's.
        ({"Origin": "http://evil.example"}, 403, "another origin"),
        ({"Origin": "null"}, 403, "another origin"),
        ({"Origin": "http://127.0.0.1:1"}, 403, "another origin"),
        ({"Sec_Fetch_Site": "cross-site"}, 403, "own page"),
        ({"Sec_Fetch_Site": "same-site"}, 403, "own page"),
        ({"Sec_Fetch_Site": "none"}, 403, "own page"),
        ({"drop": (ACT_TOKEN_HEADER,)}, 403, "token"),
        ({ACT_TOKEN_HEADER.replace("-", "_"): "not-the-token"}, 403, "token"),
        ({"Content_Type": "text/plain"}, 415, "application/json"),
        ({"Content_Type": "application/x-www-form-urlencoded"}, 415, "application/json"),
        ({"Content_Type": "multipart/form-data; boundary=x"}, 415, "application/json"),
        ({"drop": ("Content-Type",)}, 415, "application/json"),
        ({"Content_Type": "application/json; charset=utf-16"}, 415, "application/json"),
        ({"drop": ("Content-Length",)}, 411, "length"),
        ({"Content_Length": "abc"}, 411, "length"),
        ({"Transfer_Encoding": "chunked"}, 411, "chunked"),
    ],
)
def test_a_request_another_page_could_send_is_refused_before_the_handler(
    live: Client,
    called: list[bytes],
    change: dict[str, object],
    status: int,
    says: str,
) -> None:
    drop = change.pop("drop", ())
    got, _, body = live.act(drop=drop, **change)  # type: ignore[arg-type]
    assert got == status, body
    assert says in body.decode()
    assert called == []


def test_a_same_origin_fetch_site_and_a_utf8_charset_are_accepted(
    live: Client, called: list[bytes]
) -> None:
    status, _, _ = live.act(
        Sec_Fetch_Site="same-origin", Content_Type="application/json; charset=utf-8"
    )
    assert status == 200
    assert len(called) == 1


def test_a_body_one_byte_over_its_bound_is_refused_and_one_at_it_accepted(
    live: Client, called: list[bytes]
) -> None:
    at = b'"' + b"x" * (MAX_ACT_BODY - 2) + b'"'
    assert live.act(body=at)[0] == 200
    over = at + b" "
    status, _, body = live.act(body=over)
    assert status == 413, body
    assert len(called) == 1


def test_an_action_without_a_named_operator_is_refused(run: Path, called: list[bytes]) -> None:
    routes = (_index_route(), _recording_route(called))
    with serving(_context(run, operator=None), routes=routes) as server:
        status, _, body = Client(server.port).act()
    assert status == 403
    assert b"no operator was named" in body
    assert called == []


def test_a_preflight_and_a_get_on_an_action_path_are_refused(
    live: Client, called: list[bytes]
) -> None:
    status, headers, _ = live.raw(
        "OPTIONS",
        "/act",
        {"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert status == 405
    assert not [h for h in headers if h.startswith("access-control-")]
    status, headers, _ = live.raw("GET", "/act", {})
    assert status == 405
    assert headers["allow"] == "POST"
    assert called == []


def test_a_request_that_stops_sending_is_dropped_at_its_timeout(
    run: Path, called: list[bytes]
) -> None:
    server = make_server(
        _context(run),
        bind="127.0.0.1",
        port=0,
        routes=(_index_route(), _recording_route(called)),
        quiet=True,
        timeout_s=0.5,
    )
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        token = Client(port).token
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(
                (
                    f"POST /act HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
                    f"Origin: http://127.0.0.1:{port}\r\n{ACT_TOKEN_HEADER}: {token}\r\n"
                    "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
                ).encode()
            )
            started = time.monotonic()
            sock.settimeout(5)
            closed = sock.recv(1024)
            waited = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    assert closed == b"", "the server answered a request whose body never came"
    assert 0.4 <= waited < 3
    assert called == []


# -- what may be declared, and who may act -------------------------------------------------------


def test_an_action_route_answers_post_only_and_a_read_route_get_only() -> None:
    def handler(context: Context, params: Mapping[str, str]) -> Response:
        return json_response({})

    with pytest.raises(ValueError, match="act route answers POST only"):
        Route("GET", "/act", "act", handler)
    with pytest.raises(ValueError, match="read route answers GET only"):
        Route("POST", "/read", "read", handler)


def test_a_request_body_is_read_only_inside_an_action() -> None:
    with pytest.raises(UIError, match="only while an action request"):
        request_body()


@pytest.mark.parametrize("name", ["", "   ", "a\nb", "tab\there", "x" * 65])
def test_an_operator_name_that_is_empty_unprintable_or_too_long_is_refused(
    name: str, run: Path
) -> None:
    with pytest.raises(StartupRefusedError, match="printable name"):
        require_operator(name)
    with pytest.raises(StartupRefusedError, match="printable name"):
        make_server(_context(run, operator=name), bind="127.0.0.1", port=0)


def test_an_operator_name_within_bounds_is_taken_as_given() -> None:
    assert require_operator(None) is None
    assert require_operator("Yasin H.") == "Yasin H."
    assert require_operator("x" * 64) == "x" * 64


def test_a_page_with_no_head_and_no_doctype_cannot_carry_the_token() -> None:
    built = assets.Assets(index=b"<html><body></body></html>", files={})
    with pytest.raises(StartupRefusedError, match="carry the action token"):
        built.with_act_token("t")
    headed = assets.Assets(index=b"<html><head></head></html>", files={})
    assert (
        b'<meta name="physgate-act-token" content="t"></head>' in headed.with_act_token("t").index
    )


# -- the guard's act kind ---------------------------------------------------------------------


def _run_of(context: Context) -> Path:
    return context.allowlist.roots[0].path / "run-1"


def _act_route(action: Callable[[Context, Path], object]) -> Route:
    def handler(context: Context, params: Mapping[str, str]) -> Response:
        action(context, _run_of(context))
        return json_response({"acted": True})

    return Route("POST", "/act", "act", handler)


def _acting(run: Path, action: Callable[[Context, Path], object]) -> tuple[int, bytes]:
    with serving(_context(run), routes=(_index_route(), _act_route(action))) as server:
        status, _, body = Client(server.port).act()
    return status, body


def _decide_through_the_queue(context: Context, run_dir: Path) -> None:
    with context.allowlist.opened_directory(run_dir) as fd:
        record_decision(run_dir, ITEM, decision="approve", resolved_by="yasin", dir_fd=fd)


def test_the_queue_s_decision_function_acts_under_the_act_kind(run: Path) -> None:
    """The positive control: the walk and the decision function, as the decision route will.

    The run lies one level below the root, so the walk takes a step and the guard must admit
    it; a guard that refused the walk's steps turns this red.
    """
    status, body = _acting(run, _decide_through_the_queue)
    assert status == 200, body
    assert [d.item_id for _, d in read_queue(run).decisions] == [ITEM]


def test_the_decision_function_is_refused_under_the_read_kind(run: Path) -> None:
    def handler(context: Context, params: Mapping[str, str]) -> Response:
        _decide_through_the_queue(context, _run_of(context))
        return json_response({})

    before = _snapshot(run)
    with serving(_context(run), routes=(Route("GET", "/read", "read", handler),)) as server:
        status, _, body = server.request("GET", "/read")
    assert status == 500, body
    assert _snapshot(run) == before


def _append_by_name(context: Context, run_dir: Path) -> None:
    with (run_dir / DECISIONS_NAME).open("ab") as handle:
        handle.write(b"{}\n")


def _append_beneath_the_walk(context: Context, run_dir: Path) -> None:
    with context.allowlist.opened_directory(run_dir) as fd:
        os.close(os.open(DECISIONS_NAME, os.O_WRONLY | os.O_APPEND, dir_fd=fd))


def _append_through_the_queue_s_helper(context: Context, run_dir: Path) -> None:
    with context.allowlist.opened_directory(run_dir) as fd:
        os.close(queue_module._open_in(fd, DECISIONS_NAME, queue_module._APPEND_FLAGS))


def _write_elsewhere(context: Context, run_dir: Path) -> None:
    (run_dir / "elsewhere.txt").write_text("x\n")


def _read_a_credential_beneath_the_walk(context: Context, run_dir: Path) -> None:
    with context.allowlist.opened_directory(run_dir) as fd:
        queue_module._read_in(fd, LOGIN_FILE, cap=1024)


def _lock_directly(context: Context, run_dir: Path) -> None:
    fd = os.open(run_dir / DECISIONS_NAME, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def _truncate_directly(context: Context, run_dir: Path) -> None:
    fd = os.open(run_dir / DECISIONS_NAME, os.O_RDONLY)
    try:
        os.ftruncate(fd, 0)
    finally:
        os.close(fd)


def _start_a_thread(context: Context, run_dir: Path) -> None:
    threading.Thread(target=lambda: None).start()


def _spawn(context: Context, run_dir: Path) -> None:
    subprocess.run([sys.executable, "-c", "pass"], check=False)


def _connect_out(context: Context, run_dir: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        sock.connect(("192.0.2.1", 9))


@pytest.mark.parametrize(
    ("action", "says"),
    [
        (_append_by_name, "outside the decision function"),
        (_append_beneath_the_walk, "outside the decision function"),
        (_append_through_the_queue_s_helper, "outside the decision function"),
        (_write_elsewhere, "outside the decision function"),
        (_read_a_credential_beneath_the_walk, "relative path outside the decision"),
        (_lock_directly, "lock outside the decision function"),
        (_truncate_directly, "truncated a file outside the decision function"),
        (_start_a_thread, "an action route started a thread"),
        (_spawn, "an action route started or signalled a process"),
        (_connect_out, "an action route connected somewhere other than loopback"),
    ],
)
def test_an_action_route_that_does_anything_but_call_the_decision_function_is_refused(
    run: Path, action: Callable[[Context, Path], object], says: str
) -> None:
    (run / LOGIN_FILE).write_text("secret\n")
    before = _snapshot(run)
    status, body = _acting(run, action)
    assert status == 500, body
    assert says in body.decode()
    assert _snapshot(run) == before


def test_the_decision_function_itself_is_held_to_append_only(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixed write rule stands without the caller check.

    A regression inside the decision function that opened the file to create it is refused at
    the open.
    """
    monkeypatch.setattr(queue_module, "_APPEND_FLAGS", queue_module._APPEND_FLAGS | os.O_CREAT)
    before = _snapshot(run)
    status, body = _acting(run, _decide_through_the_queue)
    assert status == 500, body
    assert "other than to append" in body.decode()
    assert _snapshot(run) == before


def test_the_decision_function_itself_may_append_to_no_other_file(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (run / "other.jsonl").write_bytes((run / DECISIONS_NAME).read_bytes())
    monkeypatch.setattr(queue_module, "DECISIONS_NAME", "other.jsonl")
    before = _snapshot(run)
    status, body = _acting(run, _decide_through_the_queue)
    assert status == 500, body
    assert "other than the decisions file" in body.decode()
    assert _snapshot(run) == before
    assert guard.DECISIONS_FILE == "queue_decisions.jsonl"
