"""The TCP services a command could reach on the machine's loopback, read at a run's start.

An offline run records them: a service bound to a loopback address or to every address
is reachable at 127.0.0.1. The OS layer keeps an offline session from them (local binding
off); the record says what was there for it to keep the session from. A listing that
cannot be read is recorded as unread, never as "none listening".
"""

from __future__ import annotations

import subprocess
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
    monkeypatch: pytest.MonkeyPatch, how: str, system: str
) -> None:
    monkeypatch.setattr(listeners, "subprocess", Fails(how))
    assert listeners.loopback_listeners(system) is None


def test_this_machine_s_listing_is_read() -> None:
    # Whatever listens here, the listing is read: a tuple, never ``None``.
    found = listeners.loopback_listeners()
    assert isinstance(found, tuple)
