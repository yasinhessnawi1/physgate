"""The raw arm's token cap fails closed: a watch that cannot count stops what it cannot count.

The cap is a thread that reads the session's stream and stops the session past its budget.
Every way that thread can stop counting stops the session too, and says so in the record:
a reading or a checkpoint that raises (``watch_failed``), a reading that does not complete
within the heartbeat or a thread that is gone (``watch_stalled``), a stream that never
appears (``no_stream``). A stop that itself fails kills the session's process group and the
run refuses its result. A session left running uncapped would be a budget in name only.

The author's checkpoint's own listing, which needs the evaluation environment, is held in
``tests/scoring``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.raw import BudgetWatch
from physgate.orchestrator.processes import started_at

#: Long enough for every stop in this file, which all happen within a second or two.
WITHIN_S = 8.0


@pytest.fixture
def session() -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True
    )
    yield process
    if process.poll() is None:
        os.killpg(process.pid, 9)
        process.wait()


def _start(stream: Path, process: subprocess.Popen[bytes], **kwargs: Any) -> BudgetWatch:  # noqa: ANN401
    started = started_at(process.pid)
    assert started is not None
    watch = BudgetWatch(stream, process=process, started=started, **kwargs)
    watch.start()
    return watch


def _ended_within(process: subprocess.Popen[bytes], seconds: float = WITHIN_S) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def _end(watch: BudgetWatch) -> str | None:
    end: str | None = getattr(watch, "end", None)
    return end


def _usage_line(tokens: int) -> str:
    message = {"id": "msg_1", "model": "m", "usage": {"input_tokens": tokens, "output_tokens": 0}}
    return json.dumps({"type": "assistant", "message": message}) + "\n"


def test_the_bounds_are_the_ones_decided() -> None:
    assert getattr(raw, "HEARTBEAT_S", None) == 5.0
    assert getattr(raw, "NO_STREAM_S", None) == 10.0


def test_a_stream_that_cannot_be_read_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes]
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.mkdir()  # reading it raises, and the reading is all the cap has
    watch = _start(stream, session, cap=10**6)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a watch that cannot read the stream left the session running"
    assert _end(watch) == "watch_failed"


def test_a_count_that_raises_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")

    def unreadable(_stream: Path) -> int:
        raise ValueError("a usage value that is not a count")

    monkeypatch.setattr(raw, "stream_total", unreadable)
    watch = _start(stream, session, cap=10**6)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a count that raised left the session running"
    assert _end(watch) == "watch_failed"
    failure = getattr(watch, "failure", None)
    assert failure is not None and "not a count" in failure


def test_a_checkpoint_that_raises_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes]
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")

    def broken(_total: int) -> str | None:
        raise FileNotFoundError("an entry went away between the listing and the look")

    watch = _start(stream, session, cap=10**6, check=broken)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a checkpoint that raised left the session running"
    assert _end(watch) == "watch_failed"


def test_a_reading_that_does_not_complete_within_the_heartbeat_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")

    def stuck(_stream: Path) -> int:
        time.sleep(60)
        return 0

    monkeypatch.setattr(raw, "stream_total", stuck)
    monkeypatch.setattr(raw, "HEARTBEAT_S", 1.0, raising=False)
    watch = _start(stream, session, cap=10**6)
    stopped = _ended_within(session)
    assert stopped, "a reading that never completed left the session running"
    assert _end(watch) == "watch_stalled"


def test_a_watch_whose_thread_is_gone_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text("")

    def gone(_self: BudgetWatch) -> None:
        raise SystemExit  # ends a thread, and no ordinary handler catches it

    monkeypatch.setattr(BudgetWatch, "_read_loop", gone, raising=False)
    # A heartbeat far beyond this test's wait: only the thread being gone can stop it here.
    monkeypatch.setattr(raw, "HEARTBEAT_S", 60.0, raising=False)
    watch = _start(stream, session, cap=10**6)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a watch whose thread had ended left the session running"
    assert _end(watch) == "watch_stalled"


def test_a_stream_that_never_appears_stops_the_session(
    tmp_path: Path, session: subprocess.Popen[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(raw, "NO_STREAM_S", 1.0, raising=False)
    watch = _start(tmp_path / "never.jsonl", session, cap=10**6)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a session whose stream never appeared ran on uncounted"
    assert _end(watch) == "no_stream"


def test_a_stop_that_fails_kills_the_session_s_group_and_refuses_the_result(
    tmp_path: Path, session: subprocess.Popen[bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text(_usage_line(600))

    def cannot(*_args: object, **_kwargs: object) -> int:
        raise OSError("the process table could not be read")

    monkeypatch.setattr(raw, "stop_tree", cannot)
    watch = _start(stream, session, cap=500)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped, "a stop that failed left the session running"
    assert _end(watch) == "budget_exhausted"
    stop_error = getattr(watch, "stop_error", None)
    assert stop_error is not None and "process table" in stop_error
    refuse = getattr(raw, "require_stopped", None)
    assert refuse is not None, "nothing refuses the result of a session the watch could not stop"
    with pytest.raises(raw.RawArmError, match="could not be stopped"):
        refuse(watch)


def test_the_run_refuses_a_session_its_watch_could_not_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from task_fixtures import own_task
    from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _script, _setup

    from physgate.evaluation.per_role.task import parse_task

    # A session that spends past its cap at once and then keeps running.
    line = _usage_line(600).strip()
    binary = _script(tmp_path / "claude", f"echo '{line}'\nsleep 30\n")

    def cannot(*_args: object, **_kwargs: object) -> int:
        raise OSError("the process table could not be read")

    monkeypatch.setattr(raw, "stop_tree", cannot)
    task = parse_task(json.dumps(own_task()).encode())
    began = time.monotonic()
    with pytest.raises(raw.RawArmError, match="could not be stopped"):
        raw.run_raw(task, _setup(tmp_path, binary), tmp_path / "work", cap=500)
    assert time.monotonic() - began < 20, "the session ran on to its wall clock"
    assert not (tmp_path / "work" / "raw.json").exists()


def test_a_session_stopped_cleanly_is_not_refused(
    tmp_path: Path, session: subprocess.Popen[bytes]
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text(_usage_line(600))
    watch = _start(stream, session, cap=500)
    stopped = _ended_within(session)
    watch.stop()
    assert stopped and _end(watch) == "budget_exhausted"
    assert getattr(watch, "stop_error", "unset") is None
    refuse = getattr(raw, "require_stopped", None)
    assert refuse is not None
    refuse(watch)


def test_the_raw_session_declares_its_reaper_canary_wherever_the_reaper_runs(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # On macOS the installer gives a sandboxed session the survivor reaper and refuses one
    # whose spawner does not export the canary. Here the reaper is wanted on every platform,
    # so the raw arm's declaration is held on Linux too.
    import argparse

    from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _setup

    from physgate.hooks.cli import add_parser
    from physgate.oslayer import reaper_install

    seen: list[list[str]] = []

    def capture(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", capture)
    worktree = outside_tmp / "worktree"
    worktree.mkdir()
    raw._install(
        _setup(outside_tmp, outside_tmp / "claude"),
        worktree,
        outside_tmp / "session",
        Path("/tmp/pg-0123456789ab"),
    )
    monkeypatch.undo()
    monkeypatch.setattr(reaper_install, "wanted", lambda platform=sys.platform: True)
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(seen[0][1:])
    refused: str | None = None
    try:
        args.func(args)
    except ValueError as exc:
        refused = str(exc)
    capsys.readouterr()
    assert refused is None, refused


def test_the_raw_session_is_spawned_held_which_is_what_exports_the_canary() -> None:
    # The declaration above is true only because the raw session is spawned through the
    # dispatcher's held spawn, which exports the session's pid before it runs the binary.
    import inspect

    from physgate.orchestrator import dispatch

    assert "spawn_held(" in inspect.getsource(raw._session)
    assert vars(raw)["spawn_held"] is dispatch.spawn_held
