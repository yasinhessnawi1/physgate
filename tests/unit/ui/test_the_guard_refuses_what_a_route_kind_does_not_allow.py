"""The per-request guard: a read route can write nothing, reach nothing off loopback, spawn nothing.

Each refusal is exercised for real inside the guard's scope, in this process, so the test
proves the audit hook aborts the operation and not only that the policy function says no.
Outside a scope the same operations go through, which is what lets the server start, and what
will let a later kind carry its own, narrower policy.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from physgate.ui import guard
from physgate.ui.exceptions import GuardRefusedError, UnregisteredKindError


@pytest.fixture(autouse=True)
def _installed() -> None:
    guard.install()


def test_a_read_route_may_read(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x\n")
    with guard.scope("read"):
        assert (tmp_path / "f").read_text() == "x\n"
        assert os.listdir(tmp_path) == ["f"]


@pytest.mark.parametrize("mode", ["w", "a", "x", "r+", "wb", "ab"])
def test_a_read_route_may_not_open_a_file_for_writing(tmp_path: Path, mode: str) -> None:
    target = tmp_path / "f"
    if mode != "x":
        target.write_text("x\n")
    with guard.scope("read"), pytest.raises(GuardRefusedError, match="for writing"):
        open(target, mode).close()  # noqa: SIM115 - the open itself is the subject
    if mode != "x":
        assert target.read_text() == "x\n"
    else:
        assert not target.exists()


def test_a_read_route_may_not_open_with_write_flags_at_the_os_level(tmp_path: Path) -> None:
    with guard.scope("read"), pytest.raises(GuardRefusedError):
        os.open(tmp_path / "g", os.O_WRONLY | os.O_CREAT, 0o644)
    assert not (tmp_path / "g").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda p: os.mkdir(p / "d"),
        lambda p: os.remove(p / "f"),
        lambda p: os.rename(p / "f", p / "h"),
        lambda p: os.replace(p / "f", p / "h"),
        lambda p: os.truncate(p / "f", 0),
        lambda p: os.chmod(p / "f", 0o600),
        lambda p: os.utime(p / "f", (0, 0)),
        lambda p: os.symlink(p / "f", p / "l"),
        lambda p: os.link(p / "f", p / "l"),
    ],
)
def test_a_read_route_may_not_change_the_filesystem(tmp_path: Path, change: object) -> None:
    (tmp_path / "f").write_text("x\n")
    before = sorted(os.listdir(tmp_path)), os.stat(tmp_path / "f").st_mtime_ns
    with guard.scope("read"), pytest.raises(GuardRefusedError, match="changed"):
        change(tmp_path)  # type: ignore[operator]
    assert (sorted(os.listdir(tmp_path)), os.stat(tmp_path / "f").st_mtime_ns) == before


def test_a_read_route_may_not_start_a_process() -> None:
    with guard.scope("read"), pytest.raises(GuardRefusedError, match="process"):
        subprocess.run([sys.executable, "-c", "pass"], check=False)


def test_a_read_route_may_not_connect_off_loopback() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Bounded, so that with the guard weakened this fails in seconds rather than waiting
    # out the kernel's connect timeout to an unroutable address.
    sock.settimeout(2)
    try:
        with guard.scope("read"), pytest.raises(GuardRefusedError, match="loopback"):
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1: refused before a packet is sent
    finally:
        sock.close()


def test_a_read_route_may_not_resolve_a_host_name() -> None:
    with guard.scope("read"), pytest.raises(GuardRefusedError):
        socket.getaddrinfo("example.org", 80)


def test_a_read_route_may_not_build_an_outbound_request() -> None:
    with guard.scope("read"), pytest.raises(GuardRefusedError):
        urllib.request.urlopen("http://192.0.2.1/", timeout=1)  # noqa: S310 - the subject


def test_a_read_route_may_connect_to_loopback() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with guard.scope("read"):
            client.connect(listener.getsockname())
    finally:
        client.close()
        listener.close()


def test_outside_a_scope_nothing_is_refused(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("written outside any request\n")
    assert (tmp_path / "f").exists()


def test_an_unregistered_kind_is_refused_when_a_scope_is_entered() -> None:
    with pytest.raises(UnregisteredKindError, match="no policy"), guard.scope("act"):
        pass


def test_the_scope_ends_with_its_block_even_when_the_body_raises(tmp_path: Path) -> None:
    with pytest.raises(GuardRefusedError), guard.scope("read"):
        open(tmp_path / "x", "w").close()  # noqa: SIM115 - the open itself is the subject
    (tmp_path / "y").write_text("after the scope\n")
    assert (tmp_path / "y").exists()


def test_the_policy_answers_every_write_mode_and_flag() -> None:
    assert guard.read_policy("open", ("p", "r", os.O_RDONLY)) is None
    assert guard.read_policy("open", ("p", "rb", os.O_RDONLY)) is None
    assert guard.read_policy("open", ("p", None, os.O_RDONLY | os.O_CLOEXEC)) is None
    for flag in (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_APPEND, os.O_TRUNC, os.O_EXCL):
        assert guard.read_policy("open", ("p", None, flag)) is not None
