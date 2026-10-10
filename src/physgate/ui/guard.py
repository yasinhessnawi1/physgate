"""A per-request guard: what a request may do is decided by the kind of route serving it.

The server installs one audit hook in its process (``sys.addaudithook``). Python
reports every file open, every filesystem change, every connection and every
spawn to it before the operation happens, and a hook that raises aborts it. The
hook does nothing on its own: it asks which kind of route the current request
belongs to, through a context variable the dispatcher sets around each handler
call, and applies that kind's policy. Outside a request (start-up, accepting a
connection) no kind is set and the hook lets everything through.

**Why per request and not one process-wide rule.** An audit hook cannot be
removed once added, so a process-wide "never write" would hold for the life of
the server and would have to be torn out the day a route is allowed to act, for
example to record a decision through the approval queue's own function. Scoping
by kind means such a route arrives as one new kind with its own narrow policy,
and every read route keeps exactly the policy it has today.

**The one kind registered: ``read``.** A read route may open files for reading
only, and only files its request may read: beneath an allowed root and outside
the refused set (the same rule as the allowlist's own resolver, applied to the
path the open names, links followed), or the interpreter's and this package's
own files. So a handler that forgets to hold a path to the allowlist is still
refused at the open. It may not open anything with a write, create, append or
truncate flag, change the filesystem in any other way, connect anywhere but
loopback, look a host name up, start a process, or start a thread: the route's
kind lives in a context variable that a new thread does not inherit, so a thread
would run outside the guard, and refusing to start one is what keeps the guard
whole. A kind with no registered policy is refused both when a route is declared
and when a scope is entered.

This is a tripwire against this package's own code, not a sandbox: code that
reaches the C library directly (``ctypes``) is not seen. It is held beside a
syntax-tree fence over the package's imports for that reason.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from physgate.ui.exceptions import GuardRefusedError, UnregisteredKindError

#: The kinds of route there are. A new kind is added here, with a policy in
#: ``POLICIES``; nothing else in the server changes.
RouteKind = Literal["read"]

#: Flags that make an ``open`` more than a read.
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC | os.O_EXCL

#: Mode characters that make a Python-level ``open`` more than a read.
WRITE_MODE_CHARACTERS = frozenset("wax+")

#: Audit events that change the filesystem or the process, whatever their arguments.
MUTATING_EVENTS = frozenset(
    {
        "os.chdir",
        "os.chflags",
        "os.chmod",
        "os.chown",
        "os.lchflags",
        "os.lchmod",
        "os.lchown",
        "os.link",
        "os.mkdir",
        "os.putenv",
        "os.remove",
        "os.removexattr",
        "os.rename",
        "os.rmdir",
        "os.setxattr",
        "os.symlink",
        "os.truncate",
        "os.unsetenv",
        "os.utime",
        "shutil.chown",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
        "shutil.make_archive",
        "shutil.move",
        "shutil.rmtree",
        "shutil.unpack_archive",
        "sqlite3.connect",
    }
)

#: Audit events that start or signal a process.
SPAWN_EVENTS = frozenset(
    {
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.kill",
        "os.killpg",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.system",
        "pty.spawn",
        "subprocess.Popen",
    }
)

#: Audit events that reach the network by name or make a socket do something other
#: than connect. A name lookup is outbound traffic before any connection is made.
NAME_EVENTS = frozenset(
    {
        "socket.bind",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.gethostname",
        "socket.getnameinfo",
        "socket.sendmsg",
        "socket.sendto",
        "urllib.Request",
        "ftplib.connect",
        "http.client.connect",
        "imaplib.open",
        "nntplib.connect",
        "poplib.connect",
        "smtplib.connect",
        "telnetlib.Telnet.open",
        "webbrowser.open",
    }
)

#: Whether a request may open the file at a path for reading.
Readable = Callable[[str], bool]


@dataclass(frozen=True)
class Scope:
    """One request's guard: its route's kind, and which files it may read.

    ``readable`` is ``None`` only where a caller deliberately tests the other rules
    alone; the server always passes its allowlist's rule.
    """

    kind: str
    readable: Readable | None


Policy = Callable[[str, tuple[object, ...], Scope], str | None]


def _loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _write_open(args: tuple[object, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and WRITE_MODE_CHARACTERS & set(mode):
        return True
    return isinstance(flags, int) and bool(flags & WRITE_FLAGS)


def read_policy(event: str, args: tuple[object, ...], scope: Scope) -> str | None:
    """Why a read route may not do ``event``, or ``None`` if it may."""
    if event == "open":
        if _write_open(args):
            return "a read route opened a file for writing"
        path = args[0] if args else None
        if (
            scope.readable is not None
            and isinstance(path, str | bytes)
            and not scope.readable(os.fsdecode(path))
        ):
            return "a read route opened a file outside the roots it may read"
    if event == "_thread.start_new_thread":
        return "a read route started a thread, where its guard could not follow it"
    if event in MUTATING_EVENTS:
        return "a read route changed the filesystem or the process"
    if event in SPAWN_EVENTS:
        return "a read route started or signalled a process"
    if event in NAME_EVENTS:
        return "a read route looked a name up or sent outside a connection"
    if event == "socket.connect":
        address = args[1] if len(args) > 1 else None
        host = address[0] if isinstance(address, tuple) and address else address
        if not _loopback(host):
            return "a read route connected somewhere other than loopback"
    if event == "socket.getaddrinfo" and not _loopback(args[0] if args else None):
        return "a read route resolved a host name"
    return None


#: The policy each registered kind runs under. A kind that is not here is refused.
POLICIES: Mapping[str, Policy] = {"read": read_policy}

_current: ContextVar[Scope | None] = ContextVar("physgate_ui_route_scope", default=None)
_installed = threading.Lock()
_state = {"installed": False}


def require_registered(kind: str) -> None:
    """Refuse a kind that no policy is registered for.

    Raises:
        UnregisteredKindError: ``kind`` is not in ``POLICIES``.
    """
    if kind not in POLICIES:
        msg = "no policy is registered for this route kind, so nothing may run under it"
        raise UnregisteredKindError(msg, kind=kind)


def _hook(event: str, args: tuple[object, ...]) -> None:
    current = _current.get()
    if current is None:
        return
    reason = POLICIES[current.kind](event, args, current)
    if reason is not None:
        raise GuardRefusedError(reason, kind=current.kind, event=event)


def install() -> None:
    """Install the audit hook in this process, once. Later calls do nothing.

    Compiled caches are not written from here on, so a module imported lazily
    inside a request does not count as a write.
    """
    with _installed:
        if _state["installed"]:
            return
        sys.dont_write_bytecode = True
        sys.addaudithook(_hook)
        _state["installed"] = True


def installed() -> bool:
    """Whether the hook is in this process."""
    return _state["installed"]


@contextmanager
def scope(kind: str, *, readable: Readable | None) -> Iterator[None]:
    """Run the body under ``kind``'s policy, reading only what ``readable`` allows.

    Raises:
        UnregisteredKindError: ``kind`` has no registered policy.
        GuardRefusedError: the body did something the policy refuses.
    """
    require_registered(kind)
    if not installed():
        msg = "the guard is not installed, so a scope would enforce nothing"
        raise GuardRefusedError(msg, kind=kind)
    token = _current.set(Scope(kind=kind, readable=readable))
    try:
        yield
    finally:
        _current.reset(token)
