"""A decision taken in the UI is the one ``physgate queue resolve`` writes, and nothing more.

Every test here runs on a run made by the real loop whose first subtask failed all three
attempts, so its queue holds one open item with three sealed trajectories, and serves it
through the real route table on a live server, asking as the app's own page does: the item
view first, then the decision, carrying the token the page was served with.

- **Byte for byte.** The same decision, once through the command and once through the UI, on
  two copies of the run with the clock pinned, leaves the two run directories equal in every
  file; the route answers exactly what the command prints.
- **The listing** is ``physgate queue list``'s own bytes, before and after, the marking for a
  decision made while a session's window was open included.
- **Refusals** write nothing: an item already decided or unknown, a view that no longer
  matches (another item line, a trajectory tampered since), and anything that is not a decision.
- **The item view** tells a tampered or swapped trajectory from one whose seal holds.
"""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ui_rig import context_over, escalated_run, fake_ui, sealed_session, serving

from physgate.cli import main
from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.queue import DECISIONS_NAME, decision_text, read_queue
from physgate.ui.server import ACT_TOKEN_HEADER, make_server

RUN = "run-esc"
FIXED = datetime(2026, 10, 11, 9, 30, 0, 654321, tzinfo=UTC)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"run": escalated_run(base), "ui": fake_ui(base / "checkout")}


def _copy(built: dict[str, Path], root: Path) -> Path:
    shutil.copytree(
        built["run"], root / RUN, symlinks=True, ignore=shutil.ignore_patterns("worktrees")
    )
    return root / RUN


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_module, "utc_now", lambda: FIXED)


class Page:
    """Asks as the app's own page does: with its origin and the token it was served with."""

    def __init__(self, port: int) -> None:
        self.port = port
        _, _, page = self.request("GET", "/")
        found = re.search(rb'<meta name="physgate-act-token" content="([^"]+)">', page)
        assert found, "the page carries no action token"
        self.token = found.group(1).decode()

    def request(
        self, method: str, target: str, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{self.port}")
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders(body if body else None)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data

    def get(self, target: str) -> tuple[int, bytes]:
        status, _, body = self.request("GET", target)
        return status, body

    def decide(self, payload: object) -> tuple[int, bytes]:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        status, _, answer = self.request(
            "POST",
            f"/api/runs/0/{RUN}/queue/decisions",
            body,
            {
                "Origin": f"http://127.0.0.1:{self.port}",
                ACT_TOKEN_HEADER: self.token,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        return status, answer


@pytest.fixture
def page(built: dict[str, Path], tmp_path: Path) -> Iterator[tuple[Page, Path]]:
    run_dir = _copy(built, tmp_path / "ui-root")
    context = replace(context_over(run_dir.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        yield Page(live.port), run_dir


def _view(page: Page) -> dict[str, object]:
    status, body = page.get(f"/api/runs/0/{RUN}/queue/items/0")
    assert status == 200, body
    view: dict[str, object] = json.loads(body)
    return view


def _trajectories(view: dict[str, object]) -> list[dict[str, str]]:
    found = view["trajectories"]
    assert isinstance(found, list)
    return found


def _decision(view: dict[str, object], verb: str = "approve", note: str = "") -> dict[str, object]:
    item = view["item"]
    assert isinstance(item, dict)
    trajectories = view["trajectories"]
    assert isinstance(trajectories, list)
    return {
        "item_id": item["item_id"],
        "verb": verb,
        "note": note,
        "shown": {
            "item_sha256": view["item_sha256"],
            "trajectories": [t["status"] for t in trajectories],
        },
    }


def _tree(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() and not p.is_symlink() else None)
        for p in sorted(root.rglob("*"))
    }


def _command(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


# -- byte for byte -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verb", "note"),
    [
        ("approve", ""),
        ("approve", "accept the last attempt as it stands"),
        ("reject", "split the subtask: the bound is ø-free — see the third finding\nsecond line"),
    ],
)
def test_a_ui_decision_writes_exactly_what_the_command_writes(
    built: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    verb: str,
    note: str,
) -> None:
    by_command = _copy(built, tmp_path / "command-root")
    by_ui = _copy(built, tmp_path / "ui-root")
    assert _tree(by_command) == _tree(by_ui)
    before = _tree(by_ui)
    item_id = read_queue(by_command).items[0].item_id

    code, printed = _command(
        ["queue", "resolve", item_id, "--run-dir", str(by_command),
         "--decision", decision_text(verb, note), "--by", "yasin"],  # type: ignore[arg-type]  # verb is one of the two
        capsys,
    )  # fmt: skip
    assert code == 0

    context = replace(context_over(by_ui.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        page = Page(live.port)
        status, answered = page.decide(_decision(_view(page), verb, note))
    assert status == 201, answered

    assert answered.decode() == printed
    assert _tree(by_ui) == _tree(by_command)
    changed = {k for k, v in _tree(by_ui).items() if before.get(k) != v}
    assert changed == {DECISIONS_NAME}


def test_the_listing_is_the_command_s_own_bytes_before_and_after_a_decision(
    page: tuple[Page, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    client, run_dir = page
    for _ in range(2):
        status, served = client.get(f"/api/runs/0/{RUN}/queue")
        code, printed = _command(["queue", "list", "--run-dir", str(run_dir)], capsys)
        assert (status, code) == (200, 0)
        assert served.decode() == printed
        if not json.loads(printed)["decided"]:
            assert client.decide(_decision(_view(client)))[0] == 201
    assert json.loads(printed)["decided"][0]["flag"] is None


def test_a_decision_made_while_a_session_s_window_is_open_is_marked_as_the_queue_marks_it(
    built: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A decision made while a session's window is open is marked, as the command marks it.

    The event log is cut right after a session's spawn, so its window is open: any decision
    written now is marked for a person to confirm, in the UI exactly as in the command.
    """
    run_dir = _copy(built, tmp_path / "ui-root")
    lines = (run_dir / "events.jsonl").read_bytes().splitlines(keepends=True)
    opened = max(
        i
        for i, raw in enumerate(lines)
        if json.loads(raw).get("kind") == "stage_entered"
        and json.loads(raw).get("decisions_bytes") is not None
    )
    (run_dir / "events.jsonl").write_bytes(b"".join(lines[: opened + 1]))
    context = replace(context_over(run_dir.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        client = Page(live.port)
        assert client.decide(_decision(_view(client)))[0] == 201
        status, served = client.get(f"/api/runs/0/{RUN}/queue")
    code, printed = _command(["queue", "list", "--run-dir", str(run_dir)], capsys)
    assert (status, code) == (200, 0)
    assert served.decode() == printed
    flags = [d["flag"] for d in json.loads(served)["decided"]]
    assert flags == ["made while session still running or not yet resumed ran; confirm"]


# -- refusals write nothing ------------------------------------------------------------------


def test_a_second_decision_on_the_item_is_refused_and_writes_nothing(
    page: tuple[Page, Path],
) -> None:
    client, run_dir = page
    view = _view(client)
    assert client.decide(_decision(view))[0] == 201
    assert _view(client)["open"] is False
    before = _tree(run_dir)
    status, body = client.decide(_decision(view, "reject", "changed my mind"))
    assert status == 409
    assert b"not an open item" in body
    assert _tree(run_dir) == before


def test_a_decision_on_an_unknown_item_is_refused(page: tuple[Page, Path]) -> None:
    client, run_dir = page
    before = _tree(run_dir)
    status, body = client.decide({**_decision(_view(client)), "item_id": "run-esc-nope"})
    assert status == 409
    assert b"not an open item" in body
    assert _tree(run_dir) == before


def test_a_decision_on_a_view_of_another_item_line_is_refused(page: tuple[Page, Path]) -> None:
    client, run_dir = page
    payload = _decision(_view(client))
    shown = payload["shown"]
    assert isinstance(shown, dict)
    payload["shown"] = {**shown, "item_sha256": "0" * 64}
    before = _tree(run_dir)
    status, body = client.decide(payload)
    assert status == 409
    assert b"no longer the one that was shown" in body
    assert _tree(run_dir) == before


def test_a_decision_on_a_view_whose_trajectory_was_tampered_since_is_refused(
    page: tuple[Page, Path],
) -> None:
    client, run_dir = page
    view = _view(client)
    session = _trajectories(view)[1]["session_id"]
    stream = run_dir / "sessions" / str(session) / "stdout.jsonl"
    with stream.open("ab") as handle:
        handle.write(b"{}\n")
    before = _tree(run_dir)
    status, body = client.decide(_decision(view))
    assert status == 409
    assert b"trajectory of the item is no longer as it was shown" in body
    assert _tree(run_dir) == before


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"extra": "field"}, "not a decision"),
        ({"verb": "defer"}, "not a decision"),
        ({"note": "x" * 4001}, "not a decision"),
        ({"item_id": ""}, "not a decision"),
        ({"shown": None}, "not a decision"),
        ({"verb": "reject", "note": "  "}, "note is required"),
    ],
)
def test_a_request_that_is_not_a_decision_is_refused_with_400(
    page: tuple[Page, Path], change: dict[str, object], says: str
) -> None:
    client, run_dir = page
    before = _tree(run_dir)
    status, body = client.decide({**_decision(_view(client)), **change})
    assert status == 400, body
    assert says in body.decode()
    assert _tree(run_dir) == before


def test_a_body_that_is_not_json_is_refused_with_400(page: tuple[Page, Path]) -> None:
    client, run_dir = page
    before = _tree(run_dir)
    status, _ = client.decide(b"{not json")
    assert status == 400
    assert _tree(run_dir) == before


def test_a_decision_waiting_past_its_bound_for_the_lock_is_refused_with_409(
    page: tuple[Page, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, run_dir = page
    monkeypatch.setattr(queue_module, "LOCK_WAIT_S", 0.3)
    payload = _decision(_view(client))
    holder = os.open(run_dir / DECISIONS_NAME, os.O_RDONLY)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        before = _tree(run_dir)
        status, body = client.decide(payload)
    finally:
        os.close(holder)
    assert status == 409
    assert b"held the approval queue's lock" in body
    assert _tree(run_dir) == before


# -- the item view ---------------------------------------------------------------------------


def test_the_item_view_holds_every_trajectory_to_its_seal(page: tuple[Page, Path]) -> None:
    client, _ = page
    view = _view(client)
    item = view["item"]
    assert isinstance(item, dict)
    assert item["source"] == "repair_budget_exhausted"
    assert view["open"] is True
    assert [t["status"] for t in _trajectories(view)] == ["holds"] * 3
    assert [t["session_id"] for t in _trajectories(view)] == [
        Path(link).parent.name for link in item["trajectories"]
    ]


def test_a_tampered_or_swapped_trajectory_is_flagged_never_shown_as_clean(
    page: tuple[Page, Path], tmp_path: Path
) -> None:
    client, run_dir = page
    sessions = [Path(t["link"]).parent.name for t in _trajectories(_view(client))]
    first = run_dir / "sessions" / sessions[0] / "stdout.jsonl"
    with first.open("ab") as handle:
        handle.write(b"{}\n")
    second = run_dir / "sessions" / sessions[1] / "stdout.jsonl"
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(second.read_bytes())
    second.unlink()
    second.symlink_to(copy)
    third = run_dir / "sessions" / sessions[2] / "stdout.jsonl"
    third.unlink()
    statuses = [t["status"] for t in _trajectories(_view(client))]
    assert statuses == ["tampered", "tampered", "missing"]


def test_a_position_past_the_queue_s_end_is_404(page: tuple[Page, Path]) -> None:
    client, _ = page
    status, body = client.get(f"/api/runs/0/{RUN}/queue/items/1")
    assert status == 404
    assert b"no item at that position" in body


# -- the socket timeout bounds each wait, not the whole request -------------------------------
#
# A connection's socket times out after a wait with no progress, read or write; a request that
# keeps moving is never cut, however long it takes in all. Each test runs the server with a
# timeout far shorter than the whole exchange, then shows a stall longer than it is dropped.

#: The server's timeout in these tests: far shorter than the whole exchange, but long enough that
#: a loaded machine's scheduling never counts as a client that stopped.
TIMEOUT_S = 1.0


@contextmanager
def _short_timeout_server(run_dir: Path, ui: Path) -> Iterator[int]:
    context = replace(context_over(run_dir.parent, ui_root=ui), operator="yasin")
    server = make_server(context, bind="127.0.0.1", port=0, quiet=True, timeout_s=TIMEOUT_S)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _large_trajectory(run_dir: Path, size: int) -> str:
    """Make one sealed session's stream ``size`` bytes, with its seal recorded to match."""
    session = sealed_session(run_dir)
    stream = run_dir / "sessions" / session / "stdout.jsonl"
    line = b'{"type":"assistant","text":"' + b"x" * 1000 + b'"}\n'
    data = line * (size // len(line))
    stream.write_bytes(data)
    lines = []
    for raw in (run_dir / "events.jsonl").read_bytes().splitlines(keepends=True):
        record = json.loads(raw)
        if record.get("kind") == "session_ended" and record.get("session_id") == session:
            record["trajectory_seal"] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "length": len(data),
            }
            raw = json.dumps(record, separators=(",", ":")).encode() + b"\n"
        lines.append(raw)
    (run_dir / "events.jsonl").write_bytes(b"".join(lines))
    return session


def _read_slowly(
    port: int, target: str, *, chunk: int, gap: float, stall_after: int | None
) -> tuple[bytes, float]:
    """Read a response a chunk at a time with a pause between reads, or stall once.

    The socket keeps its default buffers. A receive buffer shrunk after connecting throttles a
    Linux connection to a crawl, and the kernel then reports the server's socket writable only
    once a large share of its send buffer has drained, which tests the kernel's pacing rather
    than the server's timeout (found on CI, reproduced on the server).
    """
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"GET {target} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        received = bytearray()
        started = time.monotonic()
        reads = 0
        while True:
            try:
                data = sock.recv(chunk)
            except OSError:  # the server dropped the connection
                break
            if not data:
                break
            received += data
            reads += 1
            time.sleep(gap if stall_after is None or reads != stall_after else TIMEOUT_S * 4)
        return bytes(received), time.monotonic() - started


def test_a_large_trajectory_read_slowly_but_steadily_is_served_to_its_end(
    built: dict[str, Path], tmp_path: Path
) -> None:
    run_dir = _copy(built, tmp_path / "ui-root")
    # Far more than the kernel buffers on either side (Linux autotunes both to megabytes), so a
    # body sent in one call cannot finish inside the timeout and the test tells the two apart.
    size = 24 << 20
    session = _large_trajectory(run_dir, size)
    target = f"/api/runs/0/{RUN}/trajectories/{session}"
    with _short_timeout_server(run_dir, built["ui"]) as port:
        whole, took = _read_slowly(port, target, chunk=128 * 1024, gap=0.02, stall_after=None)
        cut, _ = _read_slowly(port, target, chunk=128 * 1024, gap=0.02, stall_after=3)
    head, _, body = whole.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.0 200")
    assert (
        len(body) == size - size % 1031
        and body == (run_dir / "sessions" / session / "stdout.jsonl").read_bytes()
    )
    assert took > TIMEOUT_S * 2, f"the read took {took:.2f} s: too fast to prove anything"
    assert len(cut) < len(whole), "a stall past the timeout was not dropped"


def test_a_decision_body_sent_slowly_but_steadily_is_taken_and_a_stall_is_dropped(
    built: dict[str, Path], tmp_path: Path
) -> None:
    run_dir = _copy(built, tmp_path / "ui-root")
    with _short_timeout_server(run_dir, built["ui"]) as port:
        page = Page(port)
        payload = json.dumps(_decision(_view(page))).encode()
        head = (
            f"POST /api/runs/0/{RUN}/queue/decisions HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
            f"Origin: http://127.0.0.1:{port}\r\n{ACT_TOKEN_HEADER}: {page.token}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n"
        ).encode()

        def send(gap: float, stall_at: int | None) -> tuple[bytes, float]:
            with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
                sock.sendall(head)
                started = time.monotonic()
                pieces = [payload[i : i + 10] for i in range(0, len(payload), 10)]
                for n, piece in enumerate(pieces):
                    time.sleep(TIMEOUT_S * 4 if n == stall_at else gap)
                    try:
                        sock.sendall(piece)
                    except OSError:
                        break
                answer = b""
                try:
                    while data := sock.recv(4096):
                        answer += data
                except OSError:  # the server dropped the connection
                    pass
                return answer, time.monotonic() - started

        stalled, _ = send(0.1, stall_at=2)
        steady, took = send(0.1, stall_at=None)
    assert not stalled.startswith(b"HTTP/1.0 201"), "a stall past the timeout was not dropped"
    assert steady.startswith(b"HTTP/1.0 201"), steady[:200]
    assert took > TIMEOUT_S * 2, f"the body took {took:.2f} s: too fast to prove anything"
    assert [d.item_id for _, d in read_queue(run_dir).decisions] == [
        read_queue(run_dir).items[0].item_id
    ]


def test_a_run_directory_swapped_after_the_route_found_it_takes_no_decision(
    built: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route reaches the run by the walk no swap can redirect, never by its name.

    Right after the route finds the run, its name is swapped for a link to a copy outside every
    root. A route that let the decision function open the run by name would write the decision
    into that copy; the walk refuses the link, and neither copy changes.
    """
    from physgate.ui import guard, readers

    run_dir = _copy(built, tmp_path / "ui-root")
    outside = _copy(built, tmp_path / "outside")
    found = readers.run_dir_of

    def found_then_swapped(context: object, params: object) -> Path:
        real = found(context, params)  # type: ignore[arg-type]
        # The swap stands for another process, so it runs outside this request's guard.
        token = guard._current.set(None)
        try:
            real.rename(real.with_name("run-esc.moved"))
            real.symlink_to(outside, target_is_directory=True)
        finally:
            guard._current.reset(token)
        return real

    context = replace(context_over(run_dir.parent, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        client = Page(live.port)
        payload = _decision(_view(client))
        before = (_tree(outside), _tree(run_dir))
        monkeypatch.setattr(readers, "run_dir_of", found_then_swapped)
        status, body = client.decide(payload)
    assert status == 403, body
    assert _tree(outside) == before[0]
    assert _tree(run_dir.with_name("run-esc.moved")) == before[1]
