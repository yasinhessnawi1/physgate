"""A design review session a killed ``decompose`` left is stopped by the next command on its run.

``decompose`` has no event log before its opening is written, so its review's spawn is on no run
record. When the review's session is spawned, its id, pid and start time are written beside the
decomposition's rounds, and removed once the review is over. A ``decompose`` killed during the
review leaves that file: the next ``decompose`` or ``run`` on the directory stops the session, by
its pid and only while that pid is the session's (its start time and its own command line), says
so, and then refuses the directory as before. It scans every stream the review's spawns wrote for
the held-out canaries the file names: an exposure is written to a file of its own, and every later
command on the directory names it and refuses. The file stays until the round's end is journalled.
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
from physgate.orchestrator import design_rounds
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.protocols import ReviewResult

__all__ = ["calls"]  # the fixture, used by name

SESSION = "11111111-2222-4333-8444-555555555555"
SIDE_FILE = Path("decomposition", "review_session.json")
EXPOSED_FILE = Path("decomposition", "review_exposed.json")
OTHER_START = "Mon Jan  1 00:00:00 2001"
CANARY = "9d3a7c51e08b46f2a1c7d4e95b0f3a68"
WITH_CANARY = {**REVIEWING, "held_out_canaries": [CANARY]}
SHOWN = json.dumps({"type": "user", "message": {"content": f"x <!-- {CANARY} -->"}}) + "\n"
CLEAN = json.dumps({"type": "user", "message": {"content": "x"}}) + "\n"


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

    def __init__(
        self,
        answer: ReviewResult | BaseException,
        spawned: tuple[str, int, str],
        stream: str | None = CLEAN,
        root: Path | None = None,
    ) -> None:
        super().__init__(answer)
        self.spawned = spawned
        self.stream = stream
        self.root = root
        self.hook: Callable[[str, int, str], None] | None = None

    def record_spawns(self, hook: Callable[[str, int, str], None]) -> None:
        self.hook = hook

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        if self.hook is not None:
            self.hook(*self.spawned)
        if self.root is not None and self.stream is not None:
            # Its stream, where the reviewer writes it: beneath the review root, by its id.
            sdir = self.root / self.spawned[0] / "session"
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "stdout.jsonl").write_text(self.stream)
        return super().review_plan(under)


def _killed_in_the_review(
    tmp_path: Path,
    spawned: tuple[str, int, str],
    *,
    stream: str | None = CLEAN,
    params: dict[str, Any] | None = None,
) -> list[str]:
    """A ``decompose`` killed during its review; the arguments it ran with."""
    args = _args(tmp_path, REVIEWING if params is None else params)
    root = (tmp_path / "review-scratch").resolve()
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(args, Recording(Stopped(), spawned, stream=stream, root=root))
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
    assert recorded == {
        "session_id": SESSION,
        "pid": 4242,
        "started": OTHER_START,
        "spawns": 1,
        "session_dir": str((tmp_path / "review-scratch").resolve() / SESSION / "session"),
        "held_out_canaries": [],
    }


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


# --- the next command scans what the review showed ---------------------------------------------


def test_an_exposure_in_a_killed_review_is_recorded_and_refused_by_the_next_decompose(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _killed_in_the_review(
        tmp_path, (SESSION, 4242, OTHER_START), stream=SHOWN, params=WITH_CANARY
    )
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    err = capsys.readouterr().err
    assert "held-out" in err, "the review's exposure is on no record"
    assert CANARY not in err, "the canary itself is named"
    assert (tmp_path / "run" / EXPOSED_FILE).is_file()
    assert json.loads((tmp_path / "run" / EXPOSED_FILE).read_text()) == {"session_id": SESSION}
    assert not _side_file(tmp_path).exists()


@pytest.mark.parametrize("second", ["decompose", "run"])
def test_every_later_command_names_the_exposure_and_refuses(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str], second: str
) -> None:
    args = _killed_in_the_review(
        tmp_path, (SESSION, 4242, OTHER_START), stream=SHOWN, params=WITH_CANARY
    )
    assert _exit(args, StandIn(_verdict())) == 2
    capsys.readouterr()
    again = _exit(args, StandIn(_verdict())) if second == "decompose" else main(_run_args(tmp_path))
    err = capsys.readouterr().err
    assert again == 2
    assert "held-out" in err and SESSION in err, "a later command does not name the exposure"
    assert calls.made == 1


def test_a_clean_stream_records_no_exposure(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _killed_in_the_review(
        tmp_path, (SESSION, 4242, OTHER_START), stream=CLEAN, params=WITH_CANARY
    )
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    err = capsys.readouterr().err
    assert "held-out" not in err
    assert "a decomposition is never resumed" in err
    assert not (tmp_path / "run" / EXPOSED_FILE).exists()
    assert not _side_file(tmp_path).exists()


def test_a_stream_that_cannot_be_read_keeps_the_record(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _killed_in_the_review(
        tmp_path, (SESSION, 4242, OTHER_START), stream=None, params=WITH_CANARY
    )
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    assert "cannot be read" in capsys.readouterr().err
    assert _side_file(tmp_path).exists(), "an unscanned review's record was removed"


def test_a_kill_between_the_review_s_end_and_its_round_s_end_line_keeps_the_record(
    tmp_path: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = design_rounds._append  # noqa: SLF001 - the journal's own writer

    def dies_at_the_round_s_end(journal: Path, line: Any) -> None:  # noqa: ANN401
        if isinstance(line, design_rounds.RoundEnded):
            raise Stopped
        append(journal, line)

    monkeypatch.setattr(design_rounds, "_append", dies_at_the_round_s_end)
    root = (tmp_path / "review-scratch").resolve()
    reviewer = Recording(_verdict(), (SESSION, 4242, OTHER_START), stream=SHOWN, root=root)
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(_args(tmp_path, WITH_CANARY), reviewer)
    assert stopped.type is Stopped
    assert _side_file(tmp_path).exists(), "the review's record went before its round's end line"


class Repaired(Recording):
    """A review spawned again to repair its verdict, its repair stream showing the canary."""

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        assert self.hook is not None and self.root is not None
        sdir = self.root / self.spawned[0] / "session"
        sdir.mkdir(parents=True, exist_ok=True)
        self.hook(*self.spawned)
        (sdir / "stdout.jsonl").write_text(CLEAN)
        self.hook(*self.spawned)
        (sdir / "stdout-repair-1.jsonl").write_text(SHOWN)
        raise Stopped


def test_a_killed_review_s_repair_stream_is_scanned(
    tmp_path: Path, calls: Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(tmp_path, WITH_CANARY)
    root = (tmp_path / "review-scratch").resolve()
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(args, Repaired(Stopped(), (SESSION, 4242, OTHER_START), root=root))
    assert stopped.type is Stopped
    assert json.loads(_side_file(tmp_path).read_text())["spawns"] == 2
    capsys.readouterr()
    assert _exit(args, StandIn(_verdict())) == 2
    assert "held-out" in capsys.readouterr().err, "the repair stream's exposure is on no record"


class Credentialed(Recording):
    """A review killed with its credential still in its directory, and in its stream."""

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        assert self.hook is not None and self.root is not None
        sdir = self.root / self.spawned[0] / "session"
        for where in ("state", "config"):
            (sdir / where).mkdir(parents=True, exist_ok=True)
        self.hook(*self.spawned)
        (sdir / "state" / "key-helper.sh").write_text(f"#!/bin/sh\necho {SECRET}\n")
        (sdir / "state" / "key").write_text(SECRET)
        (sdir / "config" / ".credentials.json").write_text(json.dumps({"token": SECRET}))
        (sdir / "stdout.jsonl").write_text(json.dumps({"type": "user", "echo": SECRET}) + "\n")
        raise Stopped


#: The dummy key the ``calls`` fixture puts in the command's environment.
SECRET = "sk-ant-test-dummy-not-a-credential"


@pytest.mark.parametrize("second", ["decompose", "run"])
def test_a_killed_review_s_credential_is_gone_after_the_next_command(
    tmp_path: Path, calls: Calls, second: str
) -> None:
    args = _args(tmp_path, WITH_CANARY)
    root = (tmp_path / "review-scratch").resolve()
    with pytest.raises(BaseException) as stopped:  # noqa: PT011 - the stop is the point
        _exit(args, Credentialed(Stopped(), (SESSION, 4242, OTHER_START), root=root))
    assert stopped.type is Stopped
    sdir = root / SESSION / "session"
    assert any(SECRET.encode() in p.read_bytes() for p in sdir.rglob("*") if p.is_file())
    _exit(args, StandIn(_verdict())) if second == "decompose" else main(_run_args(tmp_path))
    held = sorted(
        str(p.relative_to(sdir))
        for p in sdir.rglob("*")
        if p.is_file() and SECRET.encode() in p.read_bytes()
    )
    assert held == [], f"the credential is still in the review's directory: {held}"
