"""A review's exposure is found again after a kill between its end record and the loop's lines.

The reviewer writes its session's end record as the session ends, before it reads the stream; the
loop records what the review came to only once the review is back. A process killed in between
leaves a review the event log does not say is back: the next process reads it as a leftover, every
stream its spawns wrote, and an exposure there halts the run. An exposure the loop is told of is
recorded before the review's tokens, which are the loop's word that the review is back. A review in
its repair resume keeps its first invocation's end on disk while it runs again: it is stopped, and
its repair stream read.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from left_session import INSTALL_BIN
from loop_fakes import FakeDispatcher, FakeReviewer, KilledError, Rig, plan, usage
from orch_helpers import make_config
from test_a_session_end_s_findings_are_recorded_before_its_incidents_and_a_kill_writes_the_rest import (  # noqa: E501
    kinds,
    lines,
    outcome,
    taken_over,
)

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Event
from physgate.orchestrator.exceptions import HeldOutExposedError, InvocationError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.processes import started_at
from physgate.orchestrator.protocols import MessageUsage

CANARY = "9d3a7c51e08b46f2a1c7d4e95b0f3a68"
STARTED = "Mon Jan  1 00:00:00 2001"
SHOWN = (
    json.dumps(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": f"x <!-- {CANARY} -->"}]},
        }
    )
    + "\n"
)
CLEAN = (
    json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}})
    + "\n"
)
ENDED = {"exit": 0, "timed_out": False, "left_running": []}


def _dispatcher(run_dir: Path, review_root: Path) -> ClaudeDispatcher:
    return ClaudeDispatcher(
        config=make_config(held_out_canaries=(CANARY,)),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=INSTALL_BIN,
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=review_root,
    )


def _review_session(
    review_root: Path, sid: str, pid: int, started: str, streams: dict[str, str]
) -> Path:
    """A review's session directory as its reviewer leaves it, with ``streams`` written."""
    sdir = review_root / sid / "session"
    sdir.mkdir(parents=True)
    (sdir / "owner.json").write_text(json.dumps({"run_id": "run-1"}))
    record = {"pid": pid, "started": started, "session_id": sid, "kind": "reviewer"}
    (sdir / "process.json").write_text(json.dumps(record))
    for name, text in streams.items():
        (sdir / name).write_text(text)
    return sdir


# --- in the loop: a kill after the review's end record -------------------------------------------


@dataclass
class EndedReviewer(FakeReviewer):
    """Its first review ends on disk, as the real reviewer's does, and then the process dies."""

    review_root: Path | None = None
    stream: str = SHOWN
    #: "killed": the process dies after the end record; "raises": the exposure reaches the loop.
    mode: str = "killed"
    hook: Callable[[str, int, str], None] | None = None

    def record_spawns(self, hook: Callable[[str, int, str], None]) -> None:
        self.hook = hook

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        if self.seen:
            return super().review(artefact)
        self.seen.append(artefact)
        assert self.hook is not None and self.review_root is not None
        sid = "rev-sess-1"
        self.hook(sid, 999_999, STARTED)
        sdir = _review_session(self.review_root, sid, 999_999, STARTED, {"stdout.jsonl": ""})
        (sdir / "stdout.jsonl").write_text(self.stream)
        (sdir / "ended.json").write_text(json.dumps(ENDED))
        if self.mode == "killed":
            raise KilledError
        spent = (MessageUsage(message_id="rv1", usage=usage(3)),)
        msg = "held-out material"
        raise HeldOutExposedError(msg, session_id=sid, reviewer_model=self.model, usage=spent)


@dataclass
class RealStop(FakeDispatcher):
    """The fakes' sessions, with the real dispatcher's stop over the review root."""

    review_root: Path | None = None
    run_dir: Path | None = None
    held: ClaudeDispatcher | None = None

    def stop_leftovers(self) -> Any:  # noqa: ANN401
        assert self.run_dir is not None and self.review_root is not None
        self.held = _dispatcher(self.run_dir, self.review_root)
        return self.held.stop_leftovers()

    def end_leftovers(self) -> None:
        assert self.held is not None
        self.held.end_leftovers()


def _rig(tmp_path: Path, reviewer: EndedReviewer) -> Rig:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    review_root = tmp_path / "reviews"
    review_root.mkdir()
    reviewer.review_root = review_root
    return Rig(
        run_dir, reviewer=reviewer, dispatcher=RealStop(review_root=review_root, run_dir=run_dir)
    )


def _causes(rows: list[dict[str, Any]]) -> list[str]:
    return [r["cause"] for r in rows if r["kind"] == "incident"]


def test_an_exposure_in_a_review_killed_after_its_end_record_halts_the_taken_over_run(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, EndedReviewer())
    loop = rig.open()
    loop.start(plan("s1"))
    assert outcome(loop.run) == "killed"
    loop.close()
    over = taken_over(rig)
    rows = lines(rig)
    assert _causes(rows) == ["held_out_read"], "the review's exposure is on no record"
    assert over == "halted"
    assert "merged" not in kinds(rows), "the exposed attempt merged"
    assert kinds(rows)[-1] == "halted"


def test_a_clean_review_killed_after_its_end_record_is_read_once_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, EndedReviewer(stream=CLEAN))
    loop = rig.open()
    loop.start(plan("s1"))
    assert outcome(loop.run) == "killed"
    loop.close()
    assert taken_over(rig) == "done"
    rows = lines(rig)
    read = [r for r in rows if r["kind"] == "leftover_read" and r["session_id"] == "rev-sess-1"]
    assert len(read) == 1, "the review the killed process left was not read at the resume"
    assert _causes(rows) == []
    assert "merged" in kinds(rows)
    # Read once: a later process does not read it again.
    fresh = rig.open()
    assert outcome(fresh.run) == "done"
    fresh.close()
    again = [r for r in lines(rig) if r["kind"] == "leftover_read"]
    assert len(again) == 1


def _dies_at_the_review_s_tokens(loop: Loop) -> None:
    """The process dies as it is about to write the review's first tokens line."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def emitting(event: Event) -> None:
        if event.kind == "tokens_used" and str(getattr(event, "attribution", "")).startswith(
            "reviewer:"
        ):
            raise KilledError
        emit(event)

    loop._emit = emitting  # type: ignore[method-assign]  # noqa: SLF001


def test_an_exposure_reaching_the_loop_is_recorded_before_the_review_s_tokens(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, EndedReviewer(mode="raises"))
    loop = rig.open()
    loop.start(plan("s1"))
    assert outcome(loop.run) == "halted"
    loop.close()
    rows = lines(rig)
    assert "incident" in kinds(rows)
    spent = [i for i, r in enumerate(rows) if r.get("attribution") == "reviewer:rev-sess-1"]
    assert spent, "the review's tokens are not recorded"
    assert kinds(rows).index("incident") < spent[0], "the review's tokens come before its exposure"


def test_a_kill_at_the_exposed_review_s_tokens_halts_the_taken_over_run_once(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, EndedReviewer(mode="raises"))
    loop = rig.open()
    loop.start(plan("s1"))
    _dies_at_the_review_s_tokens(loop)
    assert outcome(loop.run) == "killed"
    loop.close()
    over = taken_over(rig)
    rows = lines(rig)
    assert _causes(rows) == ["held_out_read"], "the exposure is lost, or written twice"
    assert over == "halted"
    assert "merged" not in kinds(rows)


# --- at the stop: a review in its repair resume --------------------------------------------------


@pytest.fixture
def live() -> Iterator[subprocess.Popen[bytes]]:
    """A stand-in review process: its command line carries its session id, as the binary's does."""
    process = subprocess.Popen(  # noqa: S603 - this interpreter, a fixed program
        [sys.executable, "-c", "import time; time.sleep(600)", "--session-id", "rev-repair"],
        start_new_session=True,
    )
    deadline = time.monotonic() + 10.0
    while started_at(process.pid) is None and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        yield process
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait()


def _spawned(run_dir: Path, *spawns: tuple[str, int, str]) -> None:
    """The run's log, with each spawn line the loop writes."""
    rig = Rig(run_dir)
    loop = rig.open()
    loop.start(plan("s1"))
    for sid, pid, started in spawns:
        loop._spawned(sid, pid, started)  # noqa: SLF001 - the loop's own record of a spawn
    loop.close()


def test_a_review_in_its_repair_resume_is_stopped_and_its_repair_stream_read(
    tmp_path: Path, live: subprocess.Popen[bytes]
) -> None:
    run_dir, review_root = tmp_path / "run", tmp_path / "reviews"
    run_dir.mkdir()
    started = started_at(live.pid)
    assert started is not None
    _spawned(run_dir, ("rev-repair", 4242, STARTED), ("rev-repair", live.pid, started))
    streams = {"stdout.jsonl": CLEAN, "stdout-repair-1.jsonl": SHOWN}
    sdir = _review_session(review_root, "rev-repair", live.pid, started, streams)
    (sdir / "ended.json").write_text(json.dumps(ENDED))  # its first invocation's
    dispatcher = _dispatcher(run_dir, review_root)
    left = {x.session_id: x for x in dispatcher.stop_leftovers()}
    assert "rev-repair" in left, "the review in its repair resume is not a leftover"
    assert left["rev-repair"].stopped
    assert left["rev-repair"].held_out_seen is not None, "its repair stream was not scanned"
    deadline = time.monotonic() + 10.0
    while live.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert live.poll() is not None, "the review process still runs"
    dispatcher.end_leftovers()
    ended = json.loads((sdir / "ended.json").read_text())
    assert ended.get("stopped_at_resume") is True, "its end is still its first invocation's"


def test_a_repair_stream_that_ended_on_disk_is_read_again(tmp_path: Path) -> None:
    run_dir, review_root = tmp_path / "run", tmp_path / "reviews"
    run_dir.mkdir()
    _spawned(run_dir, ("rev-repair", 4242, STARTED), ("rev-repair", 4243, STARTED))
    streams = {"stdout.jsonl": CLEAN, "stdout-repair-1.jsonl": SHOWN}
    sdir = _review_session(review_root, "rev-repair", 4243, STARTED, streams)
    (sdir / "ended.json").write_text(json.dumps(ENDED))
    left = {x.session_id: x for x in _dispatcher(run_dir, review_root).stop_leftovers()}
    assert "rev-repair" in left
    assert not left["rev-repair"].stopped
    assert left["rev-repair"].held_out_seen is not None


def test_a_repair_spawned_before_its_process_record_is_honoured_and_signals_nothing(
    tmp_path: Path,
) -> None:
    run_dir, review_root = tmp_path / "run", tmp_path / "reviews"
    run_dir.mkdir()
    # The repair's spawn line is written; its process record is still the first invocation's.
    _spawned(run_dir, ("rev-repair", 4242, STARTED), ("rev-repair", 4243, STARTED))
    streams = {"stdout.jsonl": CLEAN, "stdout-repair-1.jsonl": ""}
    sdir = _review_session(review_root, "rev-repair", 4242, STARTED, streams)
    (sdir / "ended.json").write_text(json.dumps(ENDED))
    try:
        found = _dispatcher(run_dir, review_root).stop_leftovers()
    except InvocationError as exc:
        found = []
        refused = str(exc)
    else:
        refused = ""
    assert refused == "", f"the resume was refused: {refused}"
    assert [(x.session_id, x.stopped) for x in found] == [("rev-repair", False)]


def test_a_repair_stream_the_log_says_was_spawned_and_is_gone_refuses_the_resume(
    tmp_path: Path,
) -> None:
    run_dir, review_root = tmp_path / "run", tmp_path / "reviews"
    run_dir.mkdir()
    _spawned(run_dir, ("rev-repair", 4242, STARTED), ("rev-repair", 4243, STARTED))
    sdir = _review_session(review_root, "rev-repair", 4243, STARTED, {"stdout.jsonl": CLEAN})
    (sdir / "ended.json").write_text(json.dumps(ENDED))
    try:
        _dispatcher(run_dir, review_root).stop_leftovers()
    except InvocationError as exc:
        refused = f"{exc} {exc.context}"
    else:
        refused = ""
    assert "rev-repair" in refused, "a review stream the log says was spawned is gone, unread"
