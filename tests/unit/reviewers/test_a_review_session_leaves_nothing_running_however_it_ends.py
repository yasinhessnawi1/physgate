"""A review session leaves nothing running, whether it exits, fails or is stopped at its clock.

Before, a review session's process tree was stopped only when its wall clock ran
out; a session that exited on its own left whatever it had started running. Here
a stand-in session starts two long-lived children, one in its process group and
one in a process group of its own (as the Bash tool starts its commands), then
ends: by exiting 0, by exiting 1, or by outliving its wall clock. Afterwards
neither child is running. Each test that relies on the wait having seen the tree
while the session ran says so: it asserts the child is among the processes the
end found running and stopped, so a run in which the collection missed it fails
instead of passing vacuously.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers import ending
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.ending import await_session
from physgate.reviewers.packet import WORKTREE_NAME, Packet
from physgate.reviewers.rubric import Rubric

#: A stand-in session: two children that would run for two minutes, their pids written,
#: then a pause, then the end its mode names.
SESSION = r"""
import os, subprocess, sys, time
marker, mode, pause = sys.argv[1], sys.argv[2], float(sys.argv[3])
deaf = "import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); " if mode == "deaf" else ""
sleeper = [sys.executable, "-c", deaf + "import time; time.sleep(120)"]
same = subprocess.Popen(sleeper, stdin=subprocess.DEVNULL)
own = subprocess.Popen(sleeper, stdin=subprocess.DEVNULL, start_new_session=True)
with open(marker + ".tmp", "w") as out:
    out.write(f"{same.pid} {own.pid}")
os.replace(marker + ".tmp", marker)
time.sleep(pause)
if mode == "hang":
    time.sleep(120)
sys.exit(1 if mode == "fail" else 0)
"""


def _pids(marker: Path) -> tuple[int, int]:
    deadline = time.monotonic() + 20
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    same, own = (int(x) for x in marker.read_text().split())
    return same, own


@pytest.fixture
def leftovers() -> Iterator[list[int]]:
    """Pids a test started; any still running when it ends is killed, so none outlives it."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if started_at(pid) is not None:
            os.kill(pid, signal.SIGKILL)


def _session(tmp_path: Path, mode: str, pause: float) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", SESSION, str(tmp_path / "pids"), mode, str(pause)],
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


@pytest.mark.parametrize(("mode", "code"), [("exit", 0), ("fail", 1)])
def test_a_session_that_exits_leaves_neither_child_running(
    tmp_path: Path, leftovers: list[int], mode: str, code: int
) -> None:
    process = _session(tmp_path, mode, pause=1.5)
    started = started_at(process.pid)
    same, own = _pids(tmp_path / "pids")
    leftovers += [same, own]
    ended = await_session(process, started, wall_clock_s=60.0)
    assert (ended.exit_code, ended.timed_out) == (code, False)
    # Reached: both were found running after the session exited, and stopped.
    assert set(ended.left_running) == {same, own}
    assert started_at(same) is None and started_at(own) is None


def test_a_session_stopped_at_its_clock_leaves_neither_child_running(
    tmp_path: Path, leftovers: list[int]
) -> None:
    process = _session(tmp_path, "hang", pause=0.0)
    started = started_at(process.pid)
    same, own = _pids(tmp_path / "pids")
    leftovers += [same, own]
    ended = await_session(process, started, wall_clock_s=2.0)
    assert ended.timed_out and ended.exit_code is not None
    assert started_at(same) is None and started_at(own) is None


def test_a_child_left_in_the_session_s_group_is_stopped_even_if_no_poll_saw_it(
    tmp_path: Path, leftovers: list[int]
) -> None:
    """The group sweep needs no poll: a session that exits at once still leaves nothing there."""
    process = _session(tmp_path, "exit", pause=0.0)
    started = started_at(process.pid)
    same, own = _pids(tmp_path / "pids")
    leftovers += [same, own]
    ended = await_session(process, started, wall_clock_s=60.0, poll_s=30.0)
    assert ended.exit_code == 0
    assert same in ended.left_running
    assert started_at(same) is None


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(
    tmp_path: Path, leftovers: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ending, "GRACE_S", 0.5)
    process = _session(tmp_path, "deaf", pause=1.5)
    started = started_at(process.pid)
    same, own = _pids(tmp_path / "pids")
    leftovers += [same, own]
    ended = await_session(process, started, wall_clock_s=60.0)
    assert ended.exit_code == 0 and set(ended.left_running) == {same, own}
    # Both ignored SIGTERM; neither is running once the grace is over.
    assert started_at(same) is None and started_at(own) is None


def _reviewer(tmp_path: Path, binary: Path, wall_clock_s: float) -> ClaudeReviewer:
    setup = ReviewerSetup(
        run_id="run-1",
        models={"electrical": "claude-opus-5-5"},
        claude_version="2.1.283",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=wall_clock_s,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary=str(binary),
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    rubric = Rubric(role="electrical", text="r", sha256="0" * 64)
    return ClaudeReviewer(role="electrical", setup=setup, rubric=rubric)


@pytest.mark.parametrize(("mode", "wall_clock_s"), [("exit", 60.0), ("hang", 3.0)])
def test_the_claude_reviewer_s_session_leaves_nothing_running(
    tmp_path: Path, leftovers: list[int], mode: str, wall_clock_s: float
) -> None:
    """Through the reviewer's own spawn: its record of the end names what it stopped."""
    marker = tmp_path / "pids"
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    pause = 1.5 if mode == "exit" else 0.0
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nsys.argv = [sys.argv[0], {str(marker)!r}, "
        f"{mode!r}, {str(pause)!r}]\n" + SESSION
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    read = tmp_path / "rs" / "review" / "read"
    (read / WORKTREE_NAME).mkdir(parents=True)
    sdir = tmp_path / "rs" / "review" / "session"
    sdir.mkdir()
    reviewer = _reviewer(tmp_path, binary, wall_clock_s)
    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env={})
    packet = cast(Packet, SimpleNamespace(read_root=str(read)))
    result: Any = reviewer._spawn(packet, sdir, installed, "sid", prompt="p", schema={})
    same, own = _pids(marker)
    leftovers += [same, own]
    _, exit_code, timed_out = result
    ended = json.loads((sdir / "ended.json").read_text())
    assert (ended["exit"], ended["timed_out"]) == (exit_code, timed_out)
    assert timed_out is (mode == "hang")
    if mode == "exit":
        assert set(ended["left_running"]) == {same, own}
    assert started_at(same) is None and started_at(own) is None
