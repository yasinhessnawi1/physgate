"""A review session's end: nothing it started is left running, however it ended.

A stop collects a session's process tree by parent pid while the session is alive
(``processes.stop_tree``), because once the session has exited its children are
reparented and a walk from it finds nothing. So the tree of a review session is
collected while it runs, at every poll of the wait for it, and once it has ended,
by exiting or by being stopped at its wall clock, every process ever seen in its
tree is stopped, with every process still in its process group. The session leads
that group: it is spawned in a session of its own, and a child it starts stays in
the group unless it leaves it. A process is signalled only while it is still the
one that was seen, by its pid and its start time; each gets SIGTERM, a grace, and
then SIGKILL.

What this still misses: a process that left the session's process group and was
started, and outlived its parent, between two polls; and, should the session's pid
be reused by a new group leader in the moment between the session's exit and the
sweep, that group's members. A reviewer is offered the Read tool and its verdict
tool alone, so it starts no shell of its own; this covers what the runtime itself
starts.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass

from physgate.orchestrator.processes import Proc, stop_tree, table, tree

#: How often the session's tree is collected while it runs.
POLL_S = 0.25
#: How long the processes left running have to end on SIGTERM before SIGKILL.
GRACE_S = 5.0
_WAIT_S = 0.05
#: How ``ps`` prints a start time under the C locale.
_LSTART = "%a %b %d %H:%M:%S %Y"


@dataclass(frozen=True)
class SessionEnd:
    """How a review session ended, and what it left running."""

    exit_code: int | None
    timed_out: bool
    #: The pid of every process found running after the session ended, each since stopped.
    left_running: tuple[int, ...]


def group(pgid: int) -> list[Proc]:
    """Every running process in the process group ``pgid``; zombies are left out."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    ).stdout
    found = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5 or not all(p.isdigit() for p in parts[:3]):
            continue
        if int(parts[2]) != pgid or parts[3].startswith("Z"):
            continue
        found.append(Proc(int(parts[0]), int(parts[1]), " ".join(parts[4].split())))
    return found


def _started(proc: Proc) -> float | None:
    try:
        return time.mktime(time.strptime(proc.started, _LSTART))
    except ValueError:
        return None


def _running(procs: Iterable[Proc]) -> list[Proc]:
    """Those of ``procs`` still running as the same process: the same pid, the same start."""
    now = table()
    return [p for p in procs if (seen := now.get(p.pid)) is not None and seen.started == p.started]


def stop_all(procs: Iterable[Proc]) -> tuple[int, ...]:
    """Stop every one of ``procs`` still running; return their pids.

    Each gets SIGTERM; those still running after the grace get SIGKILL.
    """
    unique = {(p.pid, p.started): p for p in procs}
    running = _running(unique.values())
    for proc in running:
        _send(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + GRACE_S
    while time.monotonic() < deadline and _running(running):
        time.sleep(_WAIT_S)
    for proc in _running(running):
        _send(proc.pid, signal.SIGKILL)
    return tuple(sorted(p.pid for p in running))


def _send(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return


def await_session(
    process: subprocess.Popen[bytes],
    started: str | None,
    wall_clock_s: float,
    *,
    poll_s: float = POLL_S,
) -> SessionEnd:
    """Wait for a review session to end, then stop everything it left running.

    ``started`` is the start time recorded for the session when it was spawned. At its
    wall clock the session is stopped with its whole tree; after any end, every process
    seen in its tree while it ran and every process still in its process group is
    stopped too.
    """
    seen: dict[tuple[int, str], Proc] = {}
    deadline = time.monotonic() + wall_clock_s
    while True:
        try:
            exit_code = process.wait(timeout=max(0.0, min(poll_s, deadline - time.monotonic())))
            timed_out = False
            break
        except subprocess.TimeoutExpired:
            pass
        collected = tree(process.pid)
        if collected and (started is None or collected[0].started == started):
            seen.update({(p.pid, p.started): p for p in collected[1:]})
        if time.monotonic() >= deadline:
            stop_tree(process.pid, started)
            exit_code, timed_out = process.wait(), True
            break
    since = _started(Proc(process.pid, 0, started)) if started is not None else None
    members = [
        p
        for p in group(process.pid)
        if p.pid != process.pid and (since is None or (_started(p) or since) >= since)
    ]
    return SessionEnd(
        exit_code=exit_code,
        timed_out=timed_out,
        left_running=stop_all([*seen.values(), *members]),
    )
