"""Processes a role session's shell command left running after it ended, found and stopped.

A command can start a process in a session of its own (``Popen(start_new_session=True)``,
a double fork), which the hooks' refusal of backgrounding cannot see in the command's text.
When the command ends, that process lives on: on macOS Seatbelt keeps it in the sandbox but
does not end it, and it was measured acting across later commands (linking files the series
writer made). Nothing a command starts may outlive it.

**Linux.** Claude Code runs each sandboxed command under bubblewrap with its own process
namespace (``--unshare-pid``, ``--die-with-parent``): when the command ends, the namespace's
first process ends, and the kernel ends every process left in it. Nothing is done here, and
an integration test holds the platform to that.

**macOS.** There is no process namespace and no subreaper: a process whose parent ended is
handed to launchd, and its descent from the command is gone. It is recognised by its sandbox
instead. Seatbelt answers, for any process of the same user, whether that process's sandbox
allows an operation on a path (``sandbox_check``). A role session's sandbox denies reads of the
session's state directory, opens its home to reads again inside the run's ``sessions/`` that
every other session's sandbox denies, and lets it write the session's worktree. A sandboxed
process of the user, started after the session's state directory was made, whose sandbox
allows reading this session's home and writing its worktree and denies reading its state
directory runs under this session's sandbox: no other session's, no other sandboxed
program's (an application's or a system agent's sandbox does not draw that line between two
sibling directories of a run), and no unsandboxed process. Every one of the four is needed:
asked with looser paths, the rule was measured to match the user's own sandboxed agents. One
that does not descend from a process the hook itself descends from (the session's Claude Code
and everything above it) is no longer part of any running command: it is a survivor, and is
killed. A survivor that forks as it is killed leaves a child handed to launchd, found by the
next round; rounds repeat until one finds none.
"""

from __future__ import annotations

import ctypes
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

#: How long ``ps`` has to list the processes.
PS_TIMEOUT_S = 10.0
#: The most rounds of finding and killing before giving up on a survivor that keeps forking.
MAX_ROUNDS = 20

#: ``sandbox_check``'s filter for a path, and its flag that keeps a check out of the log.
_FILTER_PATH = 1
_NO_REPORT = 0x40000000


class SurvivorError(OSError):
    """The process table or the sandbox could not be asked: no answer is "nothing survives"."""


@dataclass(frozen=True)
class Process:
    """One process as ``ps`` lists it."""

    pid: int
    ppid: int
    uid: int
    started: str


def table() -> dict[int, Process]:
    """Every process on the machine but the zombies, by pid.

    Raises:
        SurvivorError: ``ps`` could not be run, failed, or did not list this process.
    """
    try:
        done = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid=,uid=,stat=,lstart="],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=PS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"ps could not be run: {exc!r}"
        raise SurvivorError(msg) from exc
    procs: dict[int, Process] = {}
    for line in done.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5 or not all(p.isdigit() for p in parts[:3]):
            continue
        if parts[3].startswith("Z"):
            continue
        pid, ppid, uid = (int(p) for p in parts[:3])
        procs[pid] = Process(pid, ppid, uid, " ".join(parts[4].split()))
    if done.returncode != 0 or os.getpid() not in procs:
        msg = f"ps exited {done.returncode} and listed {len(procs)} processes, not this one"
        raise SurvivorError(msg)
    return procs


def ancestors(pid: int, procs: dict[int, Process]) -> list[int]:
    """``pid``'s parent, its parent's parent and so on, up to and without launchd."""
    found: list[int] = []
    seen = {pid}
    current = procs.get(pid)
    while current is not None and current.ppid > 1 and current.ppid not in seen:
        found.append(current.ppid)
        seen.add(current.ppid)
        current = procs.get(current.ppid)
    return found


class Seatbelt:
    """Asks Seatbelt what another process's sandbox allows (``sandbox_check``, libsystem).

    ``sandbox_check`` takes its filter's argument as a variadic one. On arm64 macOS a variadic
    argument is passed on the stack, after the eight argument registers, where a call
    declared with fixed arguments would put it in a register: five unused words fill the
    registers so the path lands where the function reads it. On x86_64 both conventions use
    the same registers. The binding checks itself on this process before it is used.

    Raises:
        SurvivorError: the function cannot be bound here, or answers wrongly about this process.
    """

    def __init__(self) -> None:
        """Bind ``sandbox_check`` and check the binding on this process."""
        try:
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            self._call = lib.sandbox_check
        except (OSError, AttributeError) as exc:
            msg = f"sandbox_check cannot be bound: {exc!r}"
            raise SurvivorError(msg) from exc
        self._call.restype = ctypes.c_int
        self._padded = platform.machine() == "arm64"
        pad: list[type[ctypes.c_int64]] = [ctypes.c_int64] * 5 if self._padded else []
        self._call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, *pad, ctypes.c_char_p]
        me = os.getpid()
        if self.sandboxed(me) or self._ask(me, b"file-read-data", "/") != 0:
            msg = "sandbox_check answers wrongly about this unsandboxed process"
            raise SurvivorError(msg)

    def _ask(self, pid: int, operation: bytes | None, path: str | None) -> int:
        kind = _FILTER_PATH | _NO_REPORT if path is not None else 0
        argument = None if path is None else os.fsencode(path)
        pad = (0, 0, 0, 0, 0) if self._padded else ()
        return int(self._call(pid, operation, kind, *pad, argument))

    def sandboxed(self, pid: int) -> bool:
        """Whether ``pid`` runs under any sandbox."""
        return self._ask(pid, None, None) == 1

    def allows(self, pid: int, operation: bytes, path: str) -> bool | None:
        """Whether ``pid``'s sandbox allows ``operation`` on the existing ``path``.

        ``None`` where Seatbelt gives no answer (a path that does not exist, a process gone).
        """
        answer = self._ask(pid, operation, path)
        return None if answer not in (0, 1) else answer == 0


@dataclass(frozen=True)
class SessionMark:
    """What only this session's sandboxed commands answer to (the module's docstring says why).

    ``since`` is when the session's state directory was made, before the session started: a
    process that started earlier is no process of its commands, whatever its sandbox says.
    """

    home: str
    state_dir: str
    worktree: str
    since: float

    @classmethod
    def of(cls, *, home: str, state_dir: str, worktree: str) -> SessionMark:
        """The mark of the session whose state directory is ``state_dir``."""
        made = os.stat(state_dir)
        return cls(home, state_dir, worktree, getattr(made, "st_birthtime", made.st_ctime))


def _started(proc: Process) -> float | None:
    try:
        return time.mktime(time.strptime(proc.started, _LSTART))
    except ValueError:
        return None


#: How ``ps`` prints a start time under the C locale.
_LSTART = "%a %b %d %H:%M:%S %Y"


def session_survivors(
    *, mark: SessionMark, seatbelt: Seatbelt, procs: dict[int, Process], me: int
) -> list[Process]:
    """This session's sandboxed processes that no running command holds any longer."""
    held = set(ancestors(me, procs)) | {me}
    uid = os.getuid()
    found: list[Process] = []
    for proc in procs.values():
        if proc.uid != uid or proc.pid in held or proc.pid <= 1:
            continue
        started = _started(proc)
        # ``ps`` gives whole seconds, cut down: compared as whole seconds.
        if started is None or started < int(mark.since):
            continue
        if set(ancestors(proc.pid, procs)) & held:
            continue
        if _ours(proc.pid, mark, seatbelt):
            found.append(proc)
    return found


def _ours(pid: int, mark: SessionMark, seatbelt: Seatbelt) -> bool:
    """Whether ``pid`` runs under this session's sandbox (the module's docstring says why)."""
    return (
        seatbelt.sandboxed(pid)
        and seatbelt.allows(pid, b"file-read-data", mark.home) is True
        and seatbelt.allows(pid, b"file-write-data", mark.worktree) is True
        and seatbelt.allows(pid, b"file-read-data", mark.state_dir) is False
    )


def reap(mark: SessionMark, *, seatbelt: Seatbelt | None = None) -> list[Process]:
    """Kill every process this session's commands left running; return the ones killed.

    Only on macOS; elsewhere the platform ends them itself and nothing is done.

    Raises:
        SurvivorError: the process table or the sandbox could not be asked, or a survivor
            was still found after :data:`MAX_ROUNDS` rounds.
    """
    if sys.platform != "darwin":
        return []
    seatbelt = seatbelt or Seatbelt()
    killed: list[Process] = []
    for _ in range(MAX_ROUNDS):
        found = session_survivors(mark=mark, seatbelt=seatbelt, procs=table(), me=os.getpid())
        if not found:
            return killed
        # Each is asked again just before it is killed, so a pid handed to another process
        # since the listing is let alone. None is stopped first: a hook cut short by its
        # watchdog between a stop and a kill would leave a process stopped for good. One that
        # forks meanwhile leaves its child to the next round.
        for proc in found:
            if _ours(proc.pid, mark, seatbelt) and _signal(proc, signal.SIGKILL):
                killed.append(proc)
    msg = f"processes of this session's commands were still running after {MAX_ROUNDS} rounds"
    raise SurvivorError(msg)


def _signal(proc: Process, sig: int) -> bool:
    try:
        os.kill(proc.pid, sig)
    except ProcessLookupError:
        return False
    return True
