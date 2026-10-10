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

**The first kind: ``read``.** A read route may open files for reading
only, and only files its request may read: beneath an allowed root and outside
the refused set (the same rule as the allowlist's own resolver, applied to the
path the open names, links followed), or the interpreter's and this package's
own files. So a handler that forgets to hold a path to the allowlist is still
refused at the open. It may not open anything with a write, create, append or
truncate flag, change the filesystem in any other way, connect anywhere but
loopback, look a host name up, start a process, or start a thread: the route's
kind lives in a context variable that a new thread does not inherit, so a thread
would run outside the guard, and refusing to start one is what keeps the guard
whole. Listing a directory is held to the same rule as opening a file, since a
listing names what is in it. A kind with no registered policy is refused both
when a route is declared and when a scope is entered.

**The second kind: ``act``.** It exists for one thing: recording a person's decision
through the approval queue's own decision function, and nothing else. Its rule is the read
rule, with exactly these openings:

- a file may be opened for writing only from inside that decision function, only by the
  decisions file's own name relative to the run directory, and only to append (never to
  create, truncate or read-and-write it);
- a path relative to a directory descriptor may be opened only from inside that function,
  or by the walk that reaches the run directory from its root without following a link;
- the decisions file's lock may be taken, and its torn tail cut, only from inside that
  function.

"From inside" is read off the call stack when the event fires: the function's own code must
be on it. So a route of this kind that writes the decisions file itself, or reaches for the
function's helpers directly, is refused at the write, as is one that writes anywhere else.

This is a tripwire against this package's own code, not a sandbox. What it does
not see: code that reaches the C library directly (``ctypes``); work deferred past
the request (an ``atexit`` callback, a finalizer, a callable kept for later),
which runs after the scope has ended; and ``stat``, ``lstat``, ``access`` and the
``exists`` family, for which Python raises no audit event (measured on 3.12), so
a route could learn a file's size or existence, never its bytes or a directory's
names. It is held beside a syntax-tree fence over the package's imports, and the
thread refusal names the 3.12 event (``_thread.start_new_thread``), which a later
interpreter renames; the thread tests would turn red on such an upgrade.
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
from types import CodeType, FrameType
from typing import Literal

from physgate.orchestrator.queue import DECISIONS_NAME, _decide, _lock
from physgate.ui.exceptions import GuardRefusedError, UnregisteredKindError
from physgate.ui.paths import _open_child

#: The kinds of route there are. A new kind is added here, with a policy in
#: ``POLICIES``; nothing else in the server changes.
RouteKind = Literal["read", "act"]

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

#: Audit events that list a directory. A listing names the files in it, so it is held to the
#: same rule as an open. One given a descriptor instead of a path, or no path at all, cannot be
#: judged and is refused.
LISTING_EVENTS = frozenset({"os.listdir", "os.scandir", "os.walk", "os.listxattr", "os.getxattr"})


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
    if event in LISTING_EVENTS and scope.readable is not None:
        target = args[0] if args else None
        if not isinstance(target, str | bytes) or not scope.readable(os.fsdecode(target)):
            return "a read route listed a directory outside the roots it may read"
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


#: The decisions file's name, bound when this module is imported: the rule holds even if the
#: queue module's own name were changed at run time.
DECISIONS_FILE = DECISIONS_NAME

#: The only flags an action may open the decisions file with: append, never through a link,
#: never waiting. Python adds close-on-exec itself.
APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

#: The decision function's own code, which must be on the stack for an action's write, its
#: relative reads, its torn-tail cut; and its lock's.
DECIDING: frozenset[CodeType] = frozenset({_decide.__code__})
LOCKING: frozenset[CodeType] = frozenset({_lock.__code__})

#: The walk's step, which may open a directory relative to the one before it.
WALKING: frozenset[CodeType] = frozenset({_open_child.__code__})

#: How far up the stack the caller check looks. A decision's deepest open is about a dozen
#: frames below the route's handler; a bound keeps a deep stack from costing anything.
STACK_DEPTH = 64


def _on_stack(codes: frozenset[CodeType]) -> bool:
    """Whether any of ``codes`` is running in a frame above this one."""
    frame: FrameType | None = sys._getframe(1)
    for _ in range(STACK_DEPTH):
        if frame is None:
            return False
        if frame.f_code in codes:
            return True
        frame = frame.f_back
    return False


def _relative(path: object) -> bool:
    return isinstance(path, str | bytes) and not os.path.isabs(os.fsdecode(path))


def act_policy(event: str, args: tuple[object, ...], scope: Scope) -> str | None:
    """Why an action route may not do ``event``, or ``None`` if it may.

    The read rule, opened exactly as far as the approval queue's decision function needs.
    """
    reason = _act_reason(event, args, scope)
    return None if reason is None else reason.replace("a read route", "an action route", 1)


def _act_reason(event: str, args: tuple[object, ...], scope: Scope) -> str | None:
    if event == "open":
        path = args[0] if args else None
        flags = args[2] if len(args) > 2 else 0
        if _write_open(args):
            if not _on_stack(DECIDING):
                return "an action route opened a file for writing outside the decision function"
            if not _relative(path) or os.fsdecode(path) != DECISIONS_FILE:  # type: ignore[arg-type]
                return "an action route opened a file other than the decisions file for writing"
            mode = args[1] if len(args) > 1 else None
            if (
                mode is not None
                or not isinstance(flags, int)
                or not flags & os.O_APPEND
                or flags & ~APPEND_FLAGS
            ):
                return "an action route opened the decisions file other than to append to it"
            return None
        if _relative(path):
            if _on_stack(DECIDING):
                return None
            if isinstance(flags, int) and flags & os.O_DIRECTORY and _on_stack(WALKING):
                return None
            return "an action route opened a relative path outside the decision and the walk"
        return read_policy(event, args, scope)
    if event == "fcntl.flock":
        return (
            None
            if _on_stack(LOCKING)
            else "an action route took a lock outside the decision function"
        )
    if event == "os.truncate":
        if isinstance(args[0] if args else None, int) and _on_stack(DECIDING):
            return None
        return "an action route truncated a file outside the decision function"
    return read_policy(event, args, scope)


#: The policy each registered kind runs under. A kind that is not here is refused.
POLICIES: Mapping[str, Policy] = {"read": read_policy, "act": act_policy}

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
