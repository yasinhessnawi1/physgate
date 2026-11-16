"""A known limit, written down: ``kill_own`` reaches the session's process group and no further.

The raw arm kills and reaps its session before any clean-up when a way out leaves it maybe alive
(``kill_own``): the session with its whole group, by the group's id. The Bash tool runs each
command in a process group of its own, so a command the session started that is still running
then is not in that group and is not reached: it outlives the kill, reparented, while the clean-up
runs. A descendant that stayed in the session's group is killed with it.

This row shows what survives today, so a change to it is seen; it is a known limit, not a
guarantee. What reaches the rest is the process tree collected by parent pid while the session
still lives (``stop_tree``), which the resume uses. And a descendant that called ``setsid`` (a
session and a group of its own) is found neither by the kill nor by the work root's check for a
living session, which looks through the session's group and its POSIX session.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from physgate.orchestrator.processes import kill_own, started_at

#: The stand-in session: one child in a group of its own (as the Bash tool runs a command), one
#: in the session's own group; each child's pid written down, then it waits.
SESSION = textwrap.dedent(
    """
    import subprocess, sys, time
    sleep = [sys.executable, "-c", "import time; time.sleep(120)"]
    own = subprocess.Popen(sleep, start_new_session=True)
    same = subprocess.Popen(sleep)
    with open(sys.argv[1], "w") as out:
        out.write(f"{own.pid} {same.pid}")
    time.sleep(120)
    """
)


def _runs(pid: int, started: str | None) -> bool:
    return started is not None and started_at(pid) == started


@pytest.fixture
def session(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], int, int, str, str]]:
    pids = tmp_path / "pids"
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-c", SESSION, str(pids)], start_new_session=True
    )
    own = same = 0
    try:
        for _ in range(400):
            if pids.is_file() and pids.read_text().strip():
                own, same = (int(p) for p in pids.read_text().split())
                break
            time.sleep(0.05)
        assert own and same, "the stand-in session did not start its children"
        own_started, same_started = started_at(own), started_at(same)
        assert own_started is not None and same_started is not None
        yield process, own, same, own_started, same_started
    finally:
        for pid in (own, same):
            if pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
        process.kill()
        process.wait()


def test_a_descendant_in_a_group_of_its_own_outlives_the_kill_known_limit(
    session: tuple[subprocess.Popen[bytes], int, int, str, str],
) -> None:
    process, own, same, own_started, same_started = session
    kill_own(process)
    assert process.returncode is not None, "the session itself was not killed and reaped"
    deadline = time.monotonic() + 5.0
    while _runs(same, same_started) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _runs(same, same_started), "a descendant in the session's group outlived the kill"
    # The known limit: what left the group runs on after the kill.
    assert _runs(own, own_started), "a descendant in a group of its own no longer outlives the kill"
