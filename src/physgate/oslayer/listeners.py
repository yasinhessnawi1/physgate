"""The TCP services listening where a command on this machine could reach them by loopback.

An offline run (``network: none``) records them at its start. A service bound to a
loopback address, or to every address, answers at 127.0.0.1, and a session's shell
command reached such services while the OS layer allowed local binding. Local binding is
off now, so the layer keeps an offline session from them; this record says what was
listening for it to keep the session from, so a run on a machine full of local services
is visibly that. A listing that cannot be read is ``None``, never an empty tuple: "nothing
listens" is concluded only from a listing that was read.
"""

from __future__ import annotations

import ipaddress
import subprocess
import sys

#: How long the listing program has to answer.
LISTING_TIMEOUT_S = 10.0

_ANY = frozenset({"*", "0.0.0.0", "::", "[::]"})  # noqa: S104 - parsed, never bound
_SEARCH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _reachable_at_loopback(host: str) -> bool:
    if host in _ANY:
        return True
    plain = host.strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(plain).is_loopback
    except ValueError:
        return False


def _ports(pairs: list[tuple[str, str]]) -> tuple[int, ...]:
    found = {int(port) for host, port in pairs if port.isdigit() and _reachable_at_loopback(host)}
    return tuple(sorted(found))


def parse_netstat(text: str) -> tuple[int, ...]:
    """The ports in macOS ``netstat -an -p tcp`` output that listen where loopback reaches."""
    pairs = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[-1] != "LISTEN" or not parts[0].startswith("tcp"):
            continue
        host, _, port = parts[3].rpartition(".")
        pairs.append((host, port))
    return _ports(pairs)


def parse_ss(text: str) -> tuple[int, ...]:
    """The ports in Linux ``ss -Hltn`` output that listen where loopback reaches."""
    pairs = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "LISTEN":
            continue
        host, _, port = parts[3].rpartition(":")
        pairs.append((host, port))
    return _ports(pairs)


def loopback_listeners(system: str | None = None) -> tuple[int, ...] | None:
    """The TCP ports listening where loopback reaches them, or ``None`` if not read.

    ``system`` is ``sys.platform`` unless given. Other platforms are not read.
    """
    system = system or sys.platform
    if system == "darwin":
        argv, parse = ["netstat", "-an", "-p", "tcp"], parse_netstat
    elif system.startswith("linux"):
        argv, parse = ["ss", "-Hltn"], parse_ss
    else:
        return None
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": _SEARCH_PATH, "LC_ALL": "C"},
            timeout=LISTING_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return parse(done.stdout)
