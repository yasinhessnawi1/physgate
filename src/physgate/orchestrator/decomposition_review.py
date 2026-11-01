"""A design review's session, recorded beside the decomposition's rounds while it runs.

``decompose`` writes no event log before its opening, so a review session's spawn is on no run
record, and a resume's stop never finds it. While the review runs, its session's id, pid and start
time stand in a file of the run directory's, beneath the decomposition: written at the spawn, before
the session runs anything, and removed once the review is over, so a decomposition that ends as it
should leaves nothing new. A ``decompose`` killed during the review leaves the file. The next
command on that directory (``decompose``, which then refuses it as before, or ``run``) stops the
session and says so. It signals the pid only while it is that session's: the start time recorded
and its own command line, which carries the session id. The file is the orchestrator's: a review
session reads only its packet, beneath the review root.

Not synced: the file guards against this process being killed, and a machine that goes down takes
the session with it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

from physgate.orchestrator.ports import SpawnHook
from physgate.orchestrator.processes import is_session, stop_tree

#: Where a design review's session is recorded while it runs, beneath the run directory.
REVIEW_SESSION = PurePosixPath("decomposition", "review_session.json")


def review_spawned(run_dir: Path) -> SpawnHook:
    """The hook that records a review session at its spawn, while it is held before it runs."""

    def spawned(session_id: str, pid: int, started: str) -> None:
        path = run_dir / REVIEW_SESSION
        path.parent.mkdir(parents=True, exist_ok=True)
        written = path.with_name(f".{path.name}.part")
        written.write_text(json.dumps({"session_id": session_id, "pid": pid, "started": started}))
        # A repair resume of the same review is spawned again: its record replaces the first.
        os.replace(written, path)

    return spawned


def review_over(run_dir: Path) -> None:
    """Remove the review session's record: its review is over, and nothing of it runs."""
    (run_dir / REVIEW_SESSION).unlink(missing_ok=True)


def stop_left_review(run_dir: Path) -> str | None:
    """Stop the review session a killed ``decompose`` left, and say what was done; ``None`` if none.

    The record is removed once the session is stopped, or once its pid is not that session's. An
    unreadable record, or a process table that cannot be read, signals nothing and keeps it.
    """
    path = run_dir / REVIEW_SESSION
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
        session_id = str(record["session_id"])
        pid = int(record["pid"])
        started = str(record["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return (
            f"the record {path} of a design review session a killed decompose left cannot be "
            "read; nothing was signalled"
        )
    try:
        if is_session(pid, started, session_id):
            killed = stop_tree(pid, started)
            said = (
                f"stopped the design review session {session_id} (pid {pid}) a killed decompose "
                f"left running; {killed} process(es) needed SIGKILL"
            )
        else:
            said = (
                f"the design review session {session_id} (pid {pid}) a killed decompose left is "
                "not running; nothing was signalled"
            )
    except OSError as exc:
        return (
            f"the design review session {session_id} (pid {pid}) a killed decompose left could "
            f"not be checked: {exc!r}; nothing was signalled"
        )
    path.unlink(missing_ok=True)
    return said
