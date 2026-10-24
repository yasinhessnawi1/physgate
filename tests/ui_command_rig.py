"""The real ``physgate ui`` command, started by a test in a process of its own, and stopped.

The tests that run the command start it here and stop it here, so a test that fails, or ends
before it stops what it started, leaves no server running on the machine.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

#: How long a process a test stopped has to be gone.
GONE_WITHIN_S = 5.0


#: Run first in every command a test starts: once the process that started it is gone (a test
#: run killed before its teardown, by a timeout, a cancelled job or a dropped connection), the
#: command kills its own process group, itself included. It leads that group only where
#: :func:`launch_command` made it; anywhere else it ends itself alone.
ORPHANED = """\
import os as _os, signal as _signal, threading as _threading, time as _time
def _orphaned(parent=_os.getppid()):
    while _os.getppid() == parent:
        _time.sleep(0.1)
    if _os.getpgid(0) == _os.getpid():
        _os.killpg(_os.getpid(), _signal.SIGKILL)
    _os._exit(1)
_threading.Thread(target=_orphaned, daemon=True).start()
"""


def launch_command(code: str, *argv: str) -> subprocess.Popen[str]:
    """Start ``python -c code argv...``, the command as the tests run it, in a group of its own.

    The command leads a new process group, so a stop reaches whatever it starts, and the stop
    of that group reaches nothing of the test's own.
    """
    return subprocess.Popen(
        [sys.executable, "-c", code, *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        process_group=0,
    )


def stop_command(process: subprocess.Popen[str], *, grace: float = 10.0) -> tuple[str, str]:
    """Stop the command and its process group as Ctrl-C would, and leave nothing of it running.

    The interrupt goes to the whole group. A command still running after ``grace`` is killed
    with its group before the failure is raised, so a red test leaves no server behind; what
    is left of the group ``grace`` after the command stopped is killed as well. Returns what
    the command printed. A command already reaped is left alone: its group may be gone.
    """
    if process.returncode is not None:
        return "", ""
    group = process.pid  # it leads its group (launch_command made it so)
    # Signalled before the command is reaped, the group's id is still the command's own. A
    # group left with nothing but the command's zombie refuses the signal (macOS: EPERM).
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGINT)
    try:
        printed = process.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(group, signal.SIGKILL)
        process.kill()  # the command itself, unreaped, whether or not it still leads its group
        process.communicate()
        _sweep(group, grace)
        raise
    _sweep(group, grace)
    return printed


def _sweep(group: int, grace: float) -> None:
    """Kill what is left of a stopped command's process group once ``grace`` has passed.

    The command, the group's leader, is reaped by now. Its group's id stays its own while any
    member of the group runs, and a member is looked for with signal 0, which stops nothing;
    the kernel hands out process ids in turn, so the id names no other group in the instant
    between that look and the kill. A group of zombies alone refuses signal 0 on macOS
    (EPERM): nothing of it runs.
    """
    deadline = time.monotonic() + grace
    while True:
        try:
            os.killpg(group, 0)
        except (ProcessLookupError, PermissionError):
            return
        if time.monotonic() > deadline:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signal.SIGKILL)
            return
        time.sleep(0.05)


def running(pid: int) -> bool:
    """Whether ``pid`` runs: neither gone nor a zombie (on Linux, read from ``/proc``)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # another user's: the id was handed out again
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True  # no /proc (macOS): launchd reaps an orphan's zombie at once
    return state != "Z"


def gone(pid: int, within: float = GONE_WITHIN_S) -> bool:
    """Whether ``pid`` stops running within ``within`` seconds."""
    deadline = time.monotonic() + within
    while running(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def kill_left_over(pids: list[int], marker: str) -> list[int]:
    """Kill each of ``pids`` still running whose command line holds ``marker``; return those.

    Only a test's own processes, known by its own marker: a process id handed out again since
    names another command line, and that process is left alone.
    """
    killed = []
    for pid in pids:
        if not running(pid):
            continue
        try:
            line = subprocess.run(
                ["ps", "-ww", "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
        except OSError:
            continue
        if marker in line:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            killed.append(pid)
    return killed
