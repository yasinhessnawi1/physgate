"""Stopping a session so that nothing it started is left running.

Measured on 2.1.272: the Bash tool runs each command in a process group of its
own, so killing the session's process group misses it; a SIGKILL of the session
alone left its tool shell running, reparented to init, writing into the worktree
twenty seconds later; and SIGTERM stopped a session and its tool in under a
fifth of a second, leaving nothing. Killing the orchestrator does not stop its
session either: it finished its whole attempt unobserved.

So a stop collects the session's whole process tree by parent pid first, while
the session is still alive and its children are still its children; sends the
session SIGTERM; waits; and then SIGKILLs every collected process that is still
alive and still the same process, told apart from a reused pid by its start
time. A resume stops any session a previous orchestrator left running, found
from the pid and start time recorded when it was spawned, before anything else
touches the worktree or the store.

A process that detached from its parent before the tree was collected escapes
the walk. The hook layer refuses backgrounding in a session's shell; tagging
processes through an environment marker is not possible on macOS, where ``ps``
shows no environment (checked).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass

_GRACE_S = 5.0
_POLL_S = 0.05


@dataclass(frozen=True)
class Proc:
    """One process as ``ps`` lists it: pid, parent pid, and start time."""

    pid: int
    ppid: int
    started: str


def table() -> dict[int, Proc]:
    """Every running process on the machine, by pid; zombies are left out."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,stat=,lstart="],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    ).stdout
    procs: dict[int, Proc] = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        # A zombie has finished; it only waits for its parent to collect it.
        if parts[2].startswith("Z"):
            continue
        procs[int(parts[0])] = Proc(int(parts[0]), int(parts[1]), " ".join(parts[3].split()))
    return procs


def started_at(pid: int) -> str | None:
    """The start time ``ps`` reports for ``pid``, or ``None`` if it is not running."""
    proc = table().get(pid)
    return proc.started if proc else None


def tree(root: int) -> list[Proc]:
    """``root`` and every process descended from it, root first."""
    procs = table()
    if root not in procs:
        return []
    children: dict[int, list[int]] = {}
    for proc in procs.values():
        children.setdefault(proc.ppid, []).append(proc.pid)
    found, queue = [], [root]
    while queue:
        pid = queue.pop(0)
        found.append(procs[pid])
        queue.extend(children.get(pid, []))
    return found


def _alive(proc: Proc) -> bool:
    return started_at(proc.pid) == proc.started


def _signal(proc: Proc, sig: int) -> None:
    if _alive(proc):
        try:
            os.kill(proc.pid, sig)
        except ProcessLookupError:
            return


def stop_tree(root: int, started: str | None = None) -> int:
    """Stop ``root`` and everything it started; return how many needed SIGKILL.

    ``started``, if given, is the start time recorded for ``root``: a process at
    that pid with any other start time is not the session and is not signalled.
    """
    collected = tree(root)
    if not collected or (started is not None and collected[0].started != started):
        return 0
    _signal(collected[0], signal.SIGTERM)
    deadline = time.monotonic() + _GRACE_S
    while time.monotonic() < deadline and _alive(collected[0]):
        time.sleep(_POLL_S)
    survivors = [p for p in collected if _alive(p)]
    for proc in survivors:
        _signal(proc, signal.SIGKILL)
    return len(survivors)
