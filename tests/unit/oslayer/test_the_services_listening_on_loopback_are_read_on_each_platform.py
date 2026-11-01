"""The TCP services a command could reach on the machine's loopback, read at a run's start.

An offline run records them: a service bound to a loopback address or to every address
is reachable at 127.0.0.1. The OS layer keeps an offline session from them (local binding
off); the record says what was there for it to keep the session from. A listing that
cannot be read is recorded as unread, never as "none listening".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from physgate.oslayer import listeners

NETSTAT = """\
Active Internet connections (including servers)
Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)
tcp4       0      0  127.0.0.1.8811         *.*                    LISTEN
tcp46      0      0  *.52092                *.*                    LISTEN
tcp4       0      0  *.52092                *.*                    LISTEN
tcp6       0      0  ::1.631                *.*                    LISTEN
tcp4       0      0  192.168.1.20.7000      *.*                    LISTEN
tcp4       0      0  127.0.0.1.50000        127.0.0.1.50001        ESTABLISHED
tcp6       0      0  fe80::1%lo0.9000       *.*                    LISTEN
"""

SS = """\
LISTEN 0      5          127.0.0.1:37881 0.0.0.0:*
LISTEN 0      4096      127.0.0.54:53    0.0.0.0:*
LISTEN 0      4096   127.0.0.53%lo:53    0.0.0.0:*
LISTEN 0      4096         0.0.0.0:111   0.0.0.0:*
LISTEN 0      128             [::]:22       [::]:*
LISTEN 0      128            [::1]:631      [::]:*
LISTEN 0      128      10.0.0.5:8080     0.0.0.0:*
LISTEN 0      128                *:9090         *:*
"""


#: ``/proc/net/tcp`` on a little-endian host: 127.0.0.1:37881, 0.0.0.0:111, 10.0.0.5:8080,
#: an established 127.0.0.1:50000 and 127.0.0.54:53.
PROC_TCP = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:93F9 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 11 1
   1: 00000000:006F 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12 1
   2: 0500000A:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 13 1
   3: 0100007F:C350 0100007F:C351 01 00000000:00000000 00:00000000 00000000  1000        0 14 1
   4: 3600007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000   991        0 15 1
"""
#: ``/proc/net/tcp6``: [::]:22, [::1]:631, ::ffff:127.0.0.1:9090 and fe80::1:7000.
PROC_TCP6 = """\
  sl  local_address                         remote_address                        st tx_queue
   0: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A 00000000
   1: 00000000000000000000000001000000:0277 00000000000000000000000000000000:0000 0A 00000000
   2: 0000000000000000FFFF00000100007F:2382 00000000000000000000000000000000:0000 0A 00000000
   3: 000080FE000000000000000001000000:1B58 00000000000000000000000000000000:0000 0A 00000000
"""


def _proc_net(root: Path, *, tcp: str | None = PROC_TCP, tcp6: str | None = PROC_TCP6) -> Path:
    root.mkdir()
    for name, text in (("tcp", tcp), ("tcp6", tcp6)):
        if text is not None:
            (root / name).write_text(text)
    return root


def test_proc_net_s_listing_gives_every_port_reachable_at_loopback() -> None:
    v4 = listeners.parse_proc_net(PROC_TCP, byteorder="little")
    v6 = listeners.parse_proc_net(PROC_TCP6, byteorder="little")
    assert v4 == (53, 111, 37881)
    assert v6 == (22, 631, 9090)


def test_proc_net_is_read_in_the_host_s_byte_order() -> None:
    big = "  sl  local_address rem_address   st\n   0: 7F000001:0050 00000000:0000 0A\n"
    assert listeners.parse_proc_net(big, byteorder="big") == (80,)
    assert listeners.parse_proc_net(big, byteorder="little") == ()


def test_an_ipv4_mapped_address_is_read_as_its_ipv4_one() -> None:
    # A socket on the mapped any-address, ::ffff:0.0.0.0, takes IPv4 connections at every
    # address of the host, loopback among them.
    six = (
        "  sl  local_address                         remote_address                        st\n"
        "   0: 0000000000000000FFFF000000000000:1F40 00000000000000000000000000000000:0000 0A\n"
    )
    assert listeners.parse_proc_net(six, byteorder="little") == (8000,)


def test_netstat_s_listing_gives_every_port_reachable_at_loopback() -> None:
    assert listeners.parse_netstat(NETSTAT) == (631, 8811, 52092)


def test_ss_s_listing_gives_every_port_reachable_at_loopback() -> None:
    assert listeners.parse_ss(SS) == (22, 53, 111, 631, 9090, 37881)


class Fails:
    """``subprocess`` for the module: the listing program fails, hangs or cannot start."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, how: str) -> None:
        self.how = how

    def run(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if kwargs.get("timeout") is None:
            pytest.fail(f"{argv[0]} was called with no time limit")
        if self.how == "hangs":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if self.how == "raises":
            raise OSError(2, "not found")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")


@pytest.mark.parametrize("system", ["darwin", "linux"])
@pytest.mark.parametrize("how", ["hangs", "raises", "fails"])
def test_a_listing_that_cannot_be_read_is_unread_not_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, how: str, system: str
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails(how))
    monkeypatch.setattr(listeners, "PROC_NET", tmp_path / "no-proc-net")
    assert listeners.loopback_listeners(system) is None


@pytest.mark.parametrize("how", ["hangs", "raises", "fails"])
def test_on_linux_without_ss_the_kernel_s_own_listing_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, how: str
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails(how))
    monkeypatch.setattr(listeners, "PROC_NET", _proc_net(tmp_path / "net"))
    monkeypatch.setattr(sys, "byteorder", "little")  # the fixtures' order
    assert listeners.loopback_listeners("linux") == (22, 53, 111, 631, 9090, 37881)


def test_a_host_without_ipv6_is_read_from_its_ipv4_listing_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails("raises"))
    monkeypatch.setattr(listeners, "PROC_NET", _proc_net(tmp_path / "net", tcp6=None))
    monkeypatch.setattr(sys, "byteorder", "little")  # the fixtures' order
    assert listeners.loopback_listeners("linux") == (53, 111, 37881)


@pytest.mark.parametrize(
    ("tcp", "tcp6"),
    [
        (None, PROC_TCP6),
        ("  sl  local_address\n   0: 0100007F:ZZZZ 00000000:0000 0A\n", PROC_TCP6),
        (PROC_TCP, "  sl  local_address\n   0: 0000:0016 0000:0000 0A\n"),
    ],
    ids=["no-ipv4-listing", "a-port-that-is-no-number", "an-address-of-another-length"],
)
def test_a_kernel_listing_that_cannot_be_read_whole_is_unread_not_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tcp: str | None, tcp6: str | None
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails("raises"))
    monkeypatch.setattr(listeners, "PROC_NET", _proc_net(tmp_path / "net", tcp=tcp, tcp6=tcp6))
    assert listeners.loopback_listeners("linux") is None


def test_an_ipv6_listing_that_is_there_but_unreadable_is_unread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    net = _proc_net(tmp_path / "net", tcp6=None)
    (net / "tcp6").mkdir()  # there, and no file to read
    monkeypatch.setattr(listeners, "subprocess", Fails("raises"))
    monkeypatch.setattr(listeners, "PROC_NET", net)
    assert listeners.loopback_listeners("linux") is None


def test_macos_never_reads_a_kernel_listing_in_place_of_netstat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails("raises"))
    monkeypatch.setattr(listeners, "PROC_NET", _proc_net(tmp_path / "net"))
    assert listeners.loopback_listeners("darwin") is None


def test_this_machine_s_listing_is_read() -> None:
    # Whatever listens here, the listing is read: a tuple, never ``None``.
    found = listeners.loopback_listeners()
    assert isinstance(found, tuple)
