"""A design review session a killed ``decompose`` left is stopped by the next command on its run.

``decompose`` has no event log before its opening is written, so its review's spawn is on no run
record. When the review's session is spawned, its id, pid and start time are written beside the
decomposition's rounds, and removed once the review is over. A ``decompose`` killed during the
review leaves that file: the next ``decompose`` or ``run`` on the directory stops the session, by
its pid and only while that pid is the session's (its start time and its own command line), says
so, and then refuses the directory as before.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_decompose_reviews_the_plan_before_it_writes_anything import (
    REVIEWING,
    Calls,
    StandIn,
    Stopped,
    _args,
    _exit,
    _verdict,
    calls,
)
from test_the_physgate_command_starts_and_decides import _run_args

from physgate.cli import main
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.protocols import ReviewResult

__all__ = ["calls"]  # the fixture, used by name

SESSION = "11111111-2222-4333-8444-555555555555"
SIDE_FILE = Path("decomposition", "review_session.json")
OTHER_START = "Mon Jan  1 00:00:00 2001"


@pytest.fixture
def review() -> Iterator[subprocess.Popen[bytes]]:
    """A stand-in review session: its command line carries its session id, as the binary's does."""
    code = "import time; time.sleep(600)"
    process = subprocess.Popen(  # noqa: S603 - this interpreter, a fixed program
        [sys.executable, "-c", code, "--session-id", SESSION], start_new_session=True
    )
    assert _settled(lambda: started_at(process.pid) is not None, 10.0)
    try:
        yield process
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait()


def _settled(check: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


class Recording(StandIn):
    """A plan reviewer that tells the hook it is given its session's spawn, then answers."""

    def __init__(self, answer: ReviewResult | BaseException, spawned: tuple[str, int, str]) -> None:
        super().__init__(answer)
        self.spawned = spawned
        self.hook: Callable[[str, int, str], None] | None = None

    def record_spawns(self, hook: Callable[[str, int, str], None]) -> None:
        self.hook = hook

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        if self.hook is not None:
            self.hook(*self.spawned)
        return super().review_plan(under)


def _killed_in_the_review(tmp_path: Path, spawned: tuple[str, int, str]) -> list[str]:
    """A ``decompose`` killed during its review; the arguments it ran with."""
    args = _args(tmp_path, REVIEWING)
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(args, Recording(Stopped(), spawned))
    assert stopped.type is Stopped
    return args


def _side_file(tmp_path: Path) -> Path:
    return tmp_path / "run" / SIDE_FILE


# --- the side file: written at the review's spawn, gone once the review is over -----------------


def test_a_review_s_spawn_is_written_beside_the_rounds_and_left_by_a_kill(
    tmp_path: Path, calls: Calls
) -> None:
    _killed_in_the_review(tmp_path, (SESSION, 4242, OTHER_START))
    assert _side_file(tmp_path).exists(), "the review's spawn is on no record a later command reads"
    recorded = json.loads(_side_file(tmp_path).read_text())
    assert recorded == {"session_id": SESSION, "pid": 4242, "started": OTHER_START}


@pytest.mark.parametrize("ending", ["verdict", "unavailable"])
def test_a_review_that_ends_leaves_no_side_file(tmp_path: Path, calls: Calls, ending: str) -> None:
    answer: ReviewResult | BaseException = (
        _verdict()
        if ending == "verdict"
        else ReviewUnavailableError(
            "a required file was not read in full",
            cause="reading_incomplete",
            session_id="review-session-2",
            reviewer_model="claude-opus-5-5",
            usage=(),
        )
    )
    assert _exit(_args(tmp_path, REVIEWING), Recording(answer, (SESSION, 4242, OTHER_START))) == 0
    assert not _side_file(tmp_path).exists()


# --- the next command stops it ------------------------------------------------------------------


def test_decompose_after_a_kill_in_the_review_stops_its_session_and_refuses_as_before(
    tmp_path: Path,
    calls: Calls,
    review: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = started_at(review.pid)
    assert started is not None
    args = _killed_in_the_review(tmp_path, (SESSION, review.pid, started))
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    err = capsys.readouterr().err
    assert _settled(lambda: review.poll() is not None, 10.0), "the review session still runs"
    assert SESSION in err and str(review.pid) in err
    assert "a decomposition is never resumed" in err
    assert not _side_file(tmp_path).exists()
    assert calls.made == 1


def test_run_after_a_kill_in_the_review_stops_its_session(
    tmp_path: Path,
    calls: Calls,
    review: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = started_at(review.pid)
    assert started is not None
    _killed_in_the_review(tmp_path, (SESSION, review.pid, started))
    capsys.readouterr()
    assert main(_run_args(tmp_path)) == 2
    err = capsys.readouterr().err
    assert _settled(lambda: review.poll() is not None, 10.0), "the review session still runs"
    assert SESSION in err
    assert "no run configuration" in err


def test_a_pid_now_held_with_another_start_time_is_not_signalled(
    tmp_path: Path,
    calls: Calls,
    review: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _killed_in_the_review(tmp_path, (SESSION, review.pid, OTHER_START))
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    assert "a decomposition is never resumed" in capsys.readouterr().err
    time.sleep(0.5)
    assert review.poll() is None, "a process the record does not name was stopped"


def test_with_no_side_file_decompose_refuses_as_before_and_stops_nothing(
    tmp_path: Path,
    calls: Calls,
    review: subprocess.Popen[bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _args(tmp_path, REVIEWING)
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(args, StandIn(Stopped()))
    assert stopped.type is Stopped
    assert not _side_file(tmp_path).exists()
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    err = capsys.readouterr().err
    assert "a decomposition is never resumed" in err
    assert SESSION not in err
    assert review.poll() is None
