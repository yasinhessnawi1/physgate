"""The TCP services listening where a command on this machine could reach them by loopback.

An offline run (``network: none``) records them at its start. A service bound to a
loopback address, or to every address, answers at 127.0.0.1, and a session's shell
command reached such services while the OS layer allowed local binding. Local binding is
off now, so the layer keeps an offline session from them; this record says what was
listening for it to keep the session from, so a run on a machine full of local services
is visibly that. A listing that cannot be read is ``None``, never an empty tuple: "nothing
listens" is concluded only from a listing that was read.

macOS is read with ``netstat``, Linux with ``ss``. A Linux host without a working ``ss`` (a
minimal image carries none) is read from the kernel's own listing, ``/proc/net/tcp`` and
``tcp6``, which every Linux kernel with a ``/proc`` has.
"""

from __future__ import annotations

import ipaddress
import subprocess
import sys
from pathlib import Path

#: How long the listing program has to answer.
LISTING_TIMEOUT_S = 10.0

_ANY = frozenset({"*", "0.0.0.0", "::", "[::]"})  # noqa: S104 - parsed, never bound
_SEARCH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
#: Where a Linux kernel lists its TCP sockets.
PROC_NET = Path("/proc/net")
#: A socket's state in the kernel's listing: ``0A`` is listening.
_LISTEN = "0A"


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


def _address(hexed: str, byteorder: str) -> str:
    """An address as the kernel's listing writes it: each 32-bit word in the host's order.

    Raises:
        ValueError: not the hexadecimal of an IPv4 or IPv6 address.
    """
    raw = bytes.fromhex(hexed)
    words = [raw[i : i + 4] for i in range(0, len(raw), 4)]
    if byteorder == "little":
        words = [word[::-1] for word in words]
    address = ipaddress.ip_address(b"".join(words))
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


def parse_proc_net(text: str, *, byteorder: str) -> tuple[int, ...]:
    """The ports in a ``/proc/net/tcp`` or ``tcp6`` listing that listen where loopback reaches.

    Raises:
        ValueError: a listening line whose address or port cannot be read.
    """
    pairs = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[3] != _LISTEN:  # noqa: PLR2004 - the state is the fourth
            continue
        hexed, _, port = parts[1].partition(":")
        pairs.append((_address(hexed, byteorder), str(int(port, 16))))
    return _ports(pairs)


def _kernel_listing() -> tuple[int, ...] | None:
    """The kernel's listing, IPv4 and IPv6, or ``None`` unless every part there was read.

    No IPv6 listing (a kernel without IPv6) leaves the IPv4 one whole; one that is there and
    cannot be read leaves the listing unread.
    """
    try:
        found = parse_proc_net((PROC_NET / "tcp").read_text(), byteorder=sys.byteorder)
        try:
            six = (PROC_NET / "tcp6").read_text()
        except FileNotFoundError:
            return found
        return tuple(sorted({*found, *parse_proc_net(six, byteorder=sys.byteorder)}))
    except (OSError, ValueError):
        return None


def _listed(argv: list[str]) -> str | None:
    """What the listing program printed, or ``None`` if it did not run or failed."""
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
    return done.stdout if done.returncode == 0 else None


def loopback_listeners(system: str | None = None) -> tuple[int, ...] | None:
    """The TCP ports listening where loopback reaches them, or ``None`` if not read.

    ``system`` is ``sys.platform`` unless given. Other platforms are not read.
    """
    system = system or sys.platform
    if system == "darwin":
        listed = _listed(["netstat", "-an", "-p", "tcp"])
        return parse_netstat(listed) if listed is not None else None
    if system.startswith("linux"):
        listed = _listed(["ss", "-Hltn"])
        return parse_ss(listed) if listed is not None else _kernel_listing()
    return None
