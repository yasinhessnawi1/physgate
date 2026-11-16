"""A run ended mid-session leaves no session's credential file in its run directory.

A session's credential is a file in its own directory, inside the run directory, while it runs
(``credentials``); the session's end removes it. A run process ended by a stop signal used to
end at once: its session, leading a process group of its own, ran on, and the file stayed in
the run directory, which is evidence that gets copied.

So, under :func:`on_stop_signals`, a stop signal (SIGTERM, an interrupt, a hang-up) does what a
kill does, every record of the run left as it stood for the resume, and before that: every
credential file this process put on disk, or a session of its may hold, is removed; every
session it spawned and has not reaped is stopped with its group (SIGTERM, :data:`GRACE_S`,
SIGKILL, with every process seen in its tree before the stop); and the files are removed once
more, since a session may write its own while it runs. The process then ends by that signal. A
signal its launcher set to be ignored stays ignored.

A run killed outright leaves the files; the next command on the run removes the file of every
session nothing runs as any more before anything else (:func:`remove_left_credentials`), and
leaves a running one's alone: the leftovers' stop ends it and removes its file, as before.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from physgate.orchestrator.credentials import (
    hold_session,
    remove_held_secrets,
    remove_secrets,
)
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.processes import (
    PS_TIMEOUT_S,
    Proc,
    ProcessTableError,
    signal_if_same,
    tree,
)

#: The signals that end a run: a supervisor's SIGTERM, an interrupt, a terminal's hang-up.
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
#: How long the run's sessions have to end on SIGTERM before SIGKILL.
GRACE_S = 5.0
_WAIT_S = 0.05
#: How long a session is waited for after its SIGKILL.
_REAP_S = 2.0

_Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

#: Every session this process spawned, until it is reaped.
_live: list[subprocess.Popen[bytes]] = []


def track(process: subprocess.Popen[bytes], credential_dirs: tuple[Path, Path] | None) -> None:
    """Hold a just-spawned session for a stop signal: its process, and its credential's files.

    ``credential_dirs`` is the session's hook state and configuration directories.
    """
    if credential_dirs is not None:
        hold_session(*credential_dirs)
    _live[:] = [p for p in _live if p.returncode is None]
    _live.append(process)


def _reaped(pid: int) -> bool:
    """Reap ``pid`` if it has ended; whether it is reaped now (by this call or before it)."""
    try:
        done, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return done == pid


def end_live_sessions(grace_s: float = GRACE_S) -> int:
    """Stop every session this process spawned and has not reaped; return how many there were.

    Each one's tree is collected while it runs, then its group gets SIGTERM. After the grace,
    whatever is left of each tree gets SIGKILL, and so does each group whose leader is still
    unreaped, whose pid and group are then still its own (``processes.kill_own``); it is reaped
    if it ends within :data:`_REAP_S`.
    Reaped with ``os.waitpid``, never ``Popen.wait``: the signal may have landed inside the
    run's own wait on the same process, which holds that process's lock.
    """
    live = [p for p in _live if p.returncode is None]
    trees: list[list[Proc]] = []
    for process in live:
        try:
            trees.append(tree(process.pid))
        except OSError:
            trees.append([])
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGTERM)
    reaped: set[int] = set()
    deadline = time.monotonic() + grace_s
    while len(reaped) < len(live) and time.monotonic() < deadline:
        reaped.update(p.pid for p in live if p.pid not in reaped and _reaped(p.pid))
        time.sleep(_WAIT_S)
    for process, collected in zip(live, trees, strict=True):
        for proc in collected[1:]:
            with contextlib.suppress(OSError):
                signal_if_same(proc, signal.SIGKILL)
        if process.pid not in reaped and not _reaped(process.pid):
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
            # Bounded: a process the kernel holds past its SIGKILL is not waited for.
            killed = time.monotonic() + _REAP_S
            while not _reaped(process.pid) and time.monotonic() < killed:
                time.sleep(_WAIT_S)
    _live.clear()
    return len(live)


def _on_stop(signum: int, _frame: FrameType | None) -> None:
    # Nothing here returns to the run. A second signal runs this again, inside, to the same end.
    remove_held_secrets()
    ended = end_live_sessions()
    remove_held_secrets()
    said = {"stopped_by": signal.Signals(signum).name, "sessions_ended": ended}
    # Unbuffered: the signal may have landed inside a write of the run's own to stderr.
    with contextlib.suppress(OSError):
        os.write(2, (json.dumps(said, sort_keys=True) + "\n").encode())
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    os._exit(128 + signum)  # only if the signal was not delivered: the run ends either way


@contextmanager
def on_stop_signals() -> Iterator[None]:
    """Inside, a stop signal ends this process's sessions and removes their credentials first.

    Installed from the main thread only, where Python runs a signal's handler; a signal the
    launcher set to be ignored is left so. What each signal had is put back on the way out.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    found: dict[signal.Signals, _Handler] = {}
    for signum in STOP_SIGNALS:
        handler = signal.getsignal(signum)
        if handler == signal.SIG_IGN:
            continue
        found[signum] = handler
        signal.signal(signum, _on_stop)
    try:
        yield
    finally:
        for each, before in found.items():
            signal.signal(each, before)


def running_session_ids() -> frozenset[str]:
    """The session id every running process names on its command line (``--session-id <id>``).

    A session's own command line carries its id, from its held start on. Any process may name
    an id, so this says only which sessions may be running, never that one is.

    Raises:
        ProcessTableError: ``ps`` could not be run, failed, or listed no process of this one's.
    """
    try:
        done = subprocess.run(
            ["ps", "-axww", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=PS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"ps could not be run: {exc!r}"
        raise ProcessTableError(msg) from exc
    ids: set[str] = set()
    pids: set[str] = set()
    for line in done.stdout.splitlines():
        words = line.split()
        if not words:
            continue
        pids.add(words[0])
        pairs = zip(words, words[1:], strict=False)
        ids.update(after for before, after in pairs if before == "--session-id")
    if done.returncode != 0 or str(os.getpid()) not in pids:
        msg = f"ps exited {done.returncode} and did not list this process"
        raise ProcessTableError(msg)
    return frozenset(ids)


def remove_left_credentials(run_dir: Path) -> tuple[str, ...]:
    """Remove the credential files of every session of the run no process runs as now.

    For the first step of a command on a run that may have been killed: a session nothing
    names by its id on a command line is gone, and needs its credential no more. A running one
    keeps its files. Without a process listing nothing is removed here, and a directory that
    cannot be reached without a link is left; the leftovers' stop, after its own stop, removes
    or refuses as before. Returns the ids of the sessions it cleared.
    """
    try:
        sdirs = sorted(
            p for p in (run_dir / "sessions").iterdir() if p.is_dir() and not p.is_symlink()
        )
        running = running_session_ids()
    except OSError:
        return ()
    removed: list[str] = []
    for sdir in sdirs:
        if sdir.name in running:
            continue
        try:
            remove_secrets(sdir / "state", sdir / "config")
        except (OSError, InvocationError):
            continue
        removed.append(sdir.name)
    return tuple(removed)
