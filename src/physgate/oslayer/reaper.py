"""Nothing a role session's shell command starts outlives it, on macOS.

A command can start a process in a session of its own (``Popen(start_new_session=True)``, a
double fork): the hooks' refusal of backgrounding cannot see it in the command's text, it
leaves the command's process group, and once its parent ends macOS hands it to launchd, so
neither a group kill nor a parent chain reaches it. On macOS it lived on across later
commands (M-128).

**What does reach it is the command's own Seatbelt sandbox.** Claude Code runs each sandboxed
command under a ``sandbox-exec`` of its own, whose profile allows a signal only to a process
of the same sandbox (``(allow signal (target same-sandbox))``). Every process inherits its
sandbox, and none can leave or join one: a member of the command's sandbox descends from the
command's ``sandbox-exec``, whatever its parent is now. Measured 21.10.2026 on macOS 26.2: from
inside one sandbox, a signal (0 as well) to an unsandboxed process of the user, or to a
process in another sandbox with the identical profile, fails with EPERM; to the sandbox's own
orphan it is delivered.

**This program is the command's first process inside that sandbox.** The session's
``CLAUDE_CODE_SHELL_PREFIX`` names it, and Claude Code 2.1.301 applies the prefix before it
wraps the command in ``sandbox-exec``. It runs the command, and when the command ends (or
Claude Code stops it with SIGTERM) it stops and kills every process the kernel lets it signal
that started at or after it, other than itself. The kernel refuses
every signal it sends to any process outside the sandbox, so no choice it makes can reach
one.

Before any signal other than 0, three guards must all hold, or nothing is signalled:

1. **It is sandboxed** (``sandbox_check`` on its own pid). Not sandboxed (a hook command,
   which the prefix wraps as well, or a call by hand) means it only runs the command, with
   ``exec``, and sends no signal at all.
2. **The canary refuses it**: signal 0 to the session's Claude Code (its pid in
   ``PHYSGATE_REAPER_CANARY``, set by the harness) must fail with EPERM, and the canary must
   be this program's parent (Claude Code spawned the command; the shells between exec).
   Anything else (unset, gone, delivered, another process) means the fence is not what it
   was measured to be: nothing is signalled, and the command is told why.
3. **Start time**: a target must have started at or after this program did, checked again
   just before each signal.

Every signal goes through :meth:`Reaper._send`, which refuses a pid of 1 or less (so no group
and no broadcast signal) and any signal but 0 unless the first two guards held.
``--dry-run`` reports what would be signalled and sends signal 0 only.

Each line it writes stands on its own (a newline before it), and a sandboxed run always ends
with ``physgate-reaper: done``: a command that killed its reaper leaves no such line, which
the survivors hook refuses. A command can print the line itself and then kill its reaper;
that forgery stays a residual (the reaper shares the command's sandbox, as it must).

The standard library only, and nothing of physgate: it runs inside the sandbox, from a copy
in the session's write-denied settings directory, under the base interpreter.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

#: The shell the command string is written for. Claude Code picks zsh where neither
#: ``CLAUDE_CODE_SHELL`` nor ``SHELL`` names another, as for a role session (which has no
#: ``SHELL``); the installer pins it, so a command runs in the shell it did before.
SHELL = "/bin/zsh"
#: Where the harness puts the session's Claude Code pid, the canary.
CANARY_ENV = "PHYSGATE_REAPER_CANARY"
#: The prefix of every line this program writes on the command's standard error.
TAG = "physgate-reaper:"
#: How long reaping may go on: Claude Code follows its SIGTERM with SIGKILL after 1500 ms,
#: and the whole of the reaper's answer (reaping, a last wait for the command's shell, its
#: lines) must end well inside that. Measured worst case on fixtures: see the integration test.
BUDGET_S = 0.6
#: The longest last wait for the command's shell after a stop signal.
FINAL_WAIT_S = 0.1
#: How many rounds in a row must find nothing before the reaper says none is left.
EMPTY_ROUNDS = 2
#: The most rounds of stopping and killing before giving up on a process that keeps forking.
MAX_ROUNDS = 400

#: The signals that ask a command to stop: Claude Code's SIGTERM, an interrupt, a hang-up.
_STOPS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)

#: ``proc_pidinfo``'s flavour for ``struct proc_bsdinfo``, the struct's size, and its fields.
_PIDTBSDINFO = 3
_BSDINFO_SIZE = 136
_SZOMB = 5


@dataclass(frozen=True)
class Info:
    """What the reaper reads of a process: its parent, state and start time."""

    ppid: int
    zombie: bool
    #: Start time in microseconds since the epoch.
    started_us: int


class KernelView(Protocol):
    """The few calls the reaper makes, so a test can stand in for the kernel."""

    def sandboxed(self, pid: int) -> bool: ...  # noqa: D102
    def pids(self) -> list[int]: ...  # noqa: D102
    def info(self, pid: int) -> Info | None: ...  # noqa: D102
    def kill(self, pid: int, sig: int) -> None: ...  # noqa: D102


class Kernel:
    """The calls, on macOS: ``libproc``, ``sandbox_check`` and ``kill(2)``."""

    def __init__(self) -> None:
        """Bind ``libproc`` and ``sandbox_check``."""
        self._proc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        system = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        # ``sandbox_check(pid, NULL, SANDBOX_FILTER_NONE)``: no variadic argument is passed.
        self._check = system.sandbox_check
        self._check.restype = ctypes.c_int
        self._check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]

    def sandboxed(self, pid: int) -> bool:
        """Whether ``pid`` runs under a sandbox (the reaper asks this of itself only)."""
        return int(self._check(pid, None, 0)) == 1

    def pids(self) -> list[int]:
        """Every pid on the machine; only numbers, no process is judged by being listed."""
        size = 4096
        while True:
            buf = (ctypes.c_int * size)()
            count = int(self._proc.proc_listallpids(buf, ctypes.sizeof(buf)))
            if count < 0:
                msg = "proc_listallpids failed"
                raise OSError(ctypes.get_errno(), msg)
            if count < size:
                return [p for p in buf[:count] if p > 0]
            size *= 2

    def info(self, pid: int) -> Info | None:
        """``pid``'s parent, state and start time; ``None`` when it cannot be read (gone)."""
        buf = ctypes.create_string_buffer(_BSDINFO_SIZE)
        got = int(self._proc.proc_pidinfo(pid, _PIDTBSDINFO, 0, buf, _BSDINFO_SIZE))
        if got != _BSDINFO_SIZE:
            return None
        raw = buf.raw

        def u32(at: int) -> int:
            return int.from_bytes(raw[at : at + 4], "little")

        def u64(at: int) -> int:
            return int.from_bytes(raw[at : at + 8], "little")

        started_us = u64(120) * 1_000_000 + u64(128)
        return Info(ppid=u32(16), zombie=u32(4) == _SZOMB, started_us=started_us)

    def kill(self, pid: int, sig: int) -> None:
        """``kill(2)``; only :meth:`Reaper._send` calls it."""
        os.kill(pid, sig)


class RefusedError(RuntimeError):
    """A signal :meth:`Reaper._send` will not send."""


@dataclass
class Reaper:
    """The selection and the one signal function, for one command."""

    kernel: KernelView
    me: int
    #: This process's parent: the canary must be it (Claude Code spawned the command).
    parent: int
    started_us: int
    dry_run: bool = False
    #: Set once the sandbox and canary guards held; no signal but 0 goes out before.
    armed: bool = False

    def _send(self, pid: int, sig: int) -> str:
        """Send ``sig`` to the one process ``pid``: ``delivered``, ``refused`` or ``gone``.

        The only place a signal leaves this program. ``refused`` is the kernel's EPERM: the
        process is outside this sandbox (or another user's).

        Raises:
            RefusedError: ``pid`` is 1 or less (launchd, a group, a broadcast), or ``sig`` is
                not 0 and the guards have not held (or this is a dry run).
        """
        if pid <= 1:
            msg = f"refused: pid {pid} names launchd, a process group or every process"
            raise RefusedError(msg)
        if sig != 0 and (self.dry_run or not self.armed):
            msg = f"refused: signal {sig} before the sandbox and canary guards held"
            raise RefusedError(msg)
        try:
            self.kernel.kill(pid, sig)
        except ProcessLookupError:
            return "gone"
        except PermissionError:
            return "refused"
        return "delivered"

    def reachable(self, pid: int) -> bool:
        """Whether the kernel lets this process signal ``pid``: signal 0, which delivers nothing."""
        return self._send(pid, 0) == "delivered"

    def fence(self, environ: Mapping[str, str]) -> str | None:
        """``None`` when the canary, this process's parent, refuses it; else why not."""
        raw = environ.get(CANARY_ENV, "")
        if not raw.isdigit() or int(raw) <= 1:
            return f"{CANARY_ENV} is not a pid ({raw!r})"
        answer = self._send(int(raw), 0)
        if answer == "gone":
            return f"the canary {raw} is gone"
        if answer == "delivered":
            return f"the canary {raw} could be signalled from inside the sandbox"
        if int(raw) != self.parent:
            return f"the canary {raw} is not this process's parent ({self.parent})"
        return None

    def _eligible(self, pid: int) -> bool:
        info = self.kernel.info(pid)
        return info is not None and not info.zombie and info.started_us >= self.started_us

    def members(self) -> list[int]:
        """The processes to stop: started at or after this one, and signalable from here.

        This process is left out, and a pid of 1 or less is never considered.
        """
        found: list[int] = []
        for pid in self.kernel.pids():
            if pid <= 1 or pid == self.me:
                continue
            if self._eligible(pid) and self.reachable(pid):
                found.append(pid)
        return found

    def _stop_round(self) -> tuple[list[int], bool]:
        """Stop each member as soon as it is found, newest pid first.

        A process that hops from pid to pid (forks, and the parent ends) every few
        milliseconds is gone by the time a whole listing has been asked about: its newest
        pid is asked first, and stopped at once, so it cannot hop on. Returns the stopped
        pids, and whether a process that started after this one vanished between its
        reading and its signal (a hop under way, so the round is not an empty one).
        """
        stopped: list[int] = []
        churn = False
        for pid in sorted(self.kernel.pids(), reverse=True):
            if pid <= 1 or pid == self.me or not self._eligible(pid):
                continue
            answer = self._send(pid, 0)
            if answer == "gone":
                churn = True
            # Checked again just before the signal: a pid handed meanwhile to a process
            # that started earlier is let alone (one outside the sandbox the kernel refuses).
            elif answer == "delivered" and self._eligible(pid):
                if self._send(pid, signal.SIGSTOP) == "delivered":
                    stopped.append(pid)
                else:
                    churn = True
        return stopped, churn

    def reap(self, *, deadline: float) -> tuple[int, bool]:
        """Stop, then kill, every member, in rounds until two rounds in a row find none.

        Two, and a round in which a young process vanished mid-round does not count as
        empty, so a process that hops pids is looked for again. Returns how many distinct
        processes were killed, and whether the last two rounds found none.
        """
        killed: set[int] = set()
        empty = 0
        for _ in range(MAX_ROUNDS):
            found, churn = self._stop_round()
            if not found and not churn:
                empty += 1
                if empty == EMPTY_ROUNDS:
                    return len(killed), True
                continue
            empty = 0
            for pid in found:
                if self._eligible(pid) and self._send(pid, signal.SIGKILL) == "delivered":
                    killed.add(pid)
            if time.monotonic() > deadline:
                break
        return len(killed), False


def _say(line: str) -> None:
    # A line of its own whatever the command wrote last: output without a final newline
    # cannot run into it and hide it from the hook.
    with contextlib.suppress(OSError):
        os.write(2, f"\n{TAG} {line}\n".encode())


def _status(returncode: int) -> int:
    return 128 - returncode if returncode < 0 else returncode


def run(
    argv: list[str],
    *,
    kernel: KernelView | None = None,
    environ: Mapping[str, str] = os.environ,
    execv: Callable[[str, list[str]], object] = os.execv,
) -> int:
    """Run the command ``argv[-1]`` and reap what it left; return the exit status to give."""
    dry_run = "--dry-run" in argv[:-1]
    command = argv[-1]
    if sys.platform != "darwin":
        execv(SHELL, [SHELL, "-c", command])
        return 0
    kernel = kernel or Kernel()
    me = os.getpid()
    if not kernel.sandboxed(me):
        # Guard 1: not sandboxed. Only run the command; nothing is signalled, ever.
        execv(SHELL, [SHELL, "-c", command])
        return 0
    own = kernel.info(me)
    started = own.started_us if own is not None else None
    reaper = Reaper(kernel, me, os.getppid(), started or 0, dry_run=dry_run)
    why_not = reaper.fence(environ) if started is not None else "its own start time is unreadable"
    reaper.armed = why_not is None and not dry_run
    if why_not is not None:
        _say(f"not reaping: {why_not}")

    # A stop signal (Claude Code's SIGTERM on a timeout or an interrupt, then SIGKILL after
    # 1500 ms) ends the wait and is answered by reaping. Before and after the wait it is
    # only noted, so it never cuts the start of the command or the reaping short.
    stopped: list[int] = []
    waiting = [False]

    def on_signal(signum: int, _frame: object) -> None:
        stopped.append(signum)
        if waiting[0]:
            raise InterruptedError

    before = {signum: signal.signal(signum, on_signal) for signum in _STOPS}
    try:
        return _run_and_reap(command, reaper, why_not, stopped, waiting)
    finally:
        for signum, handler in before.items():
            signal.signal(signum, handler)


def _run_and_reap(
    command: str, reaper: Reaper, why_not: str | None, stopped: list[int], waiting: list[bool]
) -> int:
    child = subprocess.Popen([SHELL, "-c", command], close_fds=False)  # noqa: S603
    returncode: int | None = None
    try:
        waiting[0] = True
        if not stopped:
            returncode = child.wait()
    except InterruptedError:
        returncode = None
    finally:
        waiting[0] = False
    deadline = time.monotonic() + BUDGET_S
    if reaper.dry_run:
        _say(
            f"dry run: fence {'held' if why_not is None else 'not proven'}; would signal "
            f"{reaper.members()}; parent {reaper.parent}"
        )
    elif reaper.armed:
        killed, clean = reaper.reap(deadline=deadline)
        if killed and returncode is not None:
            _say(f"stopped {killed} process(es) this command left running")
        elif killed:
            _say(f"stopped {killed} process(es) when the command was stopped (signal {stopped[0]})")
        if not clean:
            _say("some process of this command was still running after reaping")
    if returncode is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=FINAL_WAIT_S)
        _say("done")
        return 128 + stopped[0]
    _say("done")
    return _status(returncode)


def main() -> None:
    """Entry point: ``reaper [--dry-run] <command string>``."""
    if len(sys.argv) < 2:  # noqa: PLR2004 - the program and the command
        _say("no command given")
        sys.exit(2)
    sys.exit(run(sys.argv))


if __name__ == "__main__":
    main()
