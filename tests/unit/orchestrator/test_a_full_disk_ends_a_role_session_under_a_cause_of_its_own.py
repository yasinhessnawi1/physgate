"""A role session whose own records a full disk lost ends under a cause of its own.

Measured on 2.1.322 with a session's transcripts on a full volume: the result says
``completed``, the exit status is 0, and the binary writes one more event after its
result, naming what it could not save. A role session's stream is held to ending at its
result, so that one event would read as a tail something else wrote. It is the binary's
own word, and the session is infrastructure under ``disk_full``: nothing it did is taken,
and nothing is called a forgery.

Only that one event is let through, and only as it was measured: alone after the one
result, of this session, with the binary's own keys and listed values, on a pin measured
to write it. Anything else after a result is what it always was. 2.1.301 never writes
the event, so on it the same bytes are a forged tail still.

A stream is something a session can reach, so the event is never taken on its own word.
It counts only where the harness itself, when the session ended, measured the volumes
holding the session's records as full. With space to spare there, or with nothing
measured, the same bytes are a forged tail. A leftover a resume finds was not measured
when it ended, so its tail is a forged one on every pin. And a full disk is never retried
in silence: the run halts under that name for a person, and a resume refuses until then.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from left_session import INSTALL_BIN, sentinel_installed, spawn_logged
from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import make_config

from physgate.orchestrator.budget import (
    DISK_FULL_BELOW_BYTES,
    WRITES_LOST_VERSIONS,
    SessionEnd,
    classify_session_end,
)
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, captured_from, free_bytes, tail_owner
from physgate.orchestrator.events import (
    RESUMABLE_HALTS,
    Halted,
    Incident,
    InfraRetryScheduled,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.trajectory import forged_tail, own_loss_tail

MODEL = "claude-sonnet-5"
SESSION = "2da87ae5-5fde-4ac4-a5a5-013abf528784"
OTHER = "7c1f0c56-0a6e-4f0e-9a51-0d8e1b0a9d11"
USAGE = {"input_tokens": 10, "output_tokens": 5}
START = {
    "type": "stream_event",
    "event": {"type": "message_start", "message": {"id": "m1", "usage": USAGE}},
}
ANSWER = {"type": "assistant", "message": {"id": "m1", "model": MODEL, "usage": USAGE}}
DELTA = {"type": "stream_event", "event": {"type": "message_delta", "usage": USAGE}}
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "terminal_reason": "completed",
    "modelUsage": {MODEL: {"inputTokens": 10, "outputTokens": 5}},
}
#: The event as 2.1.322 wrote it after its result (measured; the ids are the session's own).
LOST: dict[str, Any] = {
    "type": "system",
    "subtype": "session_writes_lost",
    "error_code": "ENOSPC",
    "lost": ["transcript"],
    "transcript_session_ids": [SESSION],
    "uuid": "0a37ef0a-4f10-4967-bafb-d35df17b58a4",
    "session_id": SESSION,
}
COMPLETED = SessionEnd(outcome="completed", cause=None)
DISK_FULL = SessionEnd(outcome="infrastructure", cause="disk_full")


def stream(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


SAVED = stream(START, ANSWER, DELTA, RESULT)
NOT_SAVED = stream(START, ANSWER, DELTA, RESULT, LOST)


def test_the_binary_s_own_word_alone_after_the_one_result_is_read() -> None:
    assert own_loss_tail(NOT_SAVED, SESSION) == "transcript (ENOSPC)"
    quota = {**LOST, "error_code": "EDQUOT", "lost": ["transcript", "global_config"]}
    assert own_loss_tail(stream(ANSWER, RESULT, quota), SESSION) == (
        "transcript, global_config (EDQUOT)"
    )
    # Blank lines around it are no other writer's.
    assert own_loss_tail(NOT_SAVED + "\n  \n", SESSION) == "transcript (ENOSPC)"
    assert own_loss_tail(SAVED, SESSION) is None


NOT_THE_BINARY_S: dict[str, str] = {
    "another session's": stream(ANSWER, RESULT, {**LOST, "session_id": OTHER}),
    "a key the binary does not write": stream(ANSWER, RESULT, {**LOST, "note": "x"}),
    "a key missing": stream(
        ANSWER, RESULT, {k: v for k, v in LOST.items() if k != "transcript_session_ids"}
    ),
    "a cause off the binary's list": stream(ANSWER, RESULT, {**LOST, "error_code": "EIO"}),
    "a record off the binary's list": stream(ANSWER, RESULT, {**LOST, "lost": ["transcript", "x"]}),
    "nothing named as lost": stream(ANSWER, RESULT, {**LOST, "lost": []}),
    "ids that are not text": stream(ANSWER, RESULT, {**LOST, "transcript_session_ids": [7]}),
    "an id that is not text": stream(ANSWER, RESULT, {**LOST, "uuid": 7}),
    "another kind of event": stream(ANSWER, RESULT, {**LOST, "type": "assistant"}),
    "another system event": stream(ANSWER, RESULT, {**LOST, "subtype": "status"}),
    "a line after it": stream(ANSWER, RESULT, LOST, ANSWER),
    "a line before it": stream(ANSWER, RESULT, ANSWER, LOST),
    "the event twice": stream(ANSWER, RESULT, LOST, LOST),
    "a second result after it": stream(ANSWER, RESULT, LOST, RESULT),
    "a second result before it": stream(ANSWER, RESULT, RESULT, LOST),
    "bytes after it": stream(ANSWER, RESULT, LOST) + "not json at all\n",
    "not an object": stream(ANSWER, RESULT) + json.dumps([LOST]) + "\n",
}


@pytest.mark.parametrize("text", NOT_THE_BINARY_S.values(), ids=NOT_THE_BINARY_S.keys())
def test_anything_else_after_a_result_is_no_word_of_the_binary_s(text: str) -> None:
    assert own_loss_tail(text, SESSION) is None
    assert forged_tail(text) is not None
    # Read as a role session's stream on the pin that writes the event: a forged tail still.
    captured = captured_from(text.encode(), own_tail_of=SESSION)
    assert captured.tampered is not None and captured.lost is None


def test_the_event_is_read_for_the_session_it_names_and_no_other() -> None:
    assert own_loss_tail(NOT_SAVED, OTHER) is None
    captured = captured_from(NOT_SAVED.encode(), own_tail_of=OTHER)
    assert captured.tampered is not None and captured.lost is None


def test_a_stream_ending_in_the_binary_s_own_word_is_no_forgery_and_names_the_loss() -> None:
    captured = captured_from(NOT_SAVED.encode(), own_tail_of=SESSION)
    assert captured.tampered is None
    assert captured.lost == "transcript (ENOSPC)"
    # What the runtime wrote up to its result is read as ever.
    assert captured.result == RESULT
    assert [m.message_id for m in captured.usage] == ["m1"]
    assert captured.answered == frozenset({MODEL})


def test_on_a_pin_that_never_writes_the_event_the_same_bytes_are_a_forged_tail() -> None:
    captured = captured_from(NOT_SAVED.encode())
    assert captured.tampered is not None and "after its result" in captured.tampered
    assert captured.lost is None
    assert captured.result == RESULT


FULL = 0
AMPLE = 500 * 1024 * 1024 * 1024


@pytest.mark.parametrize("version", ["2.1.272", "2.1.283", "2.1.301", "9.9.9", ""])
def test_no_pin_but_one_measured_to_write_the_event_has_a_tail_of_its_own(version: str) -> None:
    assert tail_owner(version, SESSION, FULL) is None


def test_the_pin_measured_to_write_the_event_reads_it_only_on_a_volume_measured_full() -> None:
    assert frozenset({"2.1.322"}) == WRITES_LOST_VERSIONS
    assert tail_owner("2.1.322", SESSION, FULL) == SESSION
    assert tail_owner("2.1.322", SESSION, DISK_FULL_BELOW_BYTES - 1) == SESSION


@pytest.mark.parametrize(
    "free", [AMPLE, DISK_FULL_BELOW_BYTES, DISK_FULL_BELOW_BYTES + 1, None], ids=str
)
def test_with_space_to_spare_or_nothing_measured_no_tail_is_the_binary_s(free: int | None) -> None:
    assert tail_owner("2.1.322", SESSION, free) is None
    # The exact event, on the pin that writes it, for the session itself: a forged tail.
    captured = captured_from(NOT_SAVED.encode(), own_tail_of=tail_owner("2.1.322", SESSION, free))
    assert captured.tampered is not None and "after its result" in captured.tampered
    assert captured.lost is None


def test_the_bound_is_fixed_and_small() -> None:
    assert DISK_FULL_BELOW_BYTES == 16 * 1024 * 1024


def test_the_free_space_is_the_harness_s_own_measurement_of_the_least_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here, there, gone = tmp_path / "here", tmp_path / "there", tmp_path / "gone"
    here.mkdir()
    there.mkdir()
    measured = free_bytes(here)
    assert measured is not None and measured > 0
    import os

    real = os.statvfs
    space = {str(here): (4096, 10), str(there): (512, 3)}

    def statvfs(path: object) -> object:
        if str(path) not in space:
            raise FileNotFoundError(2, "no such place", str(path))
        frsize, bavail = space[str(path)]

        class _Volume:
            f_frsize, f_bavail = frsize, bavail

        return _Volume()

    monkeypatch.setattr(os, "statvfs", statvfs)
    assert free_bytes(here) == 40960
    assert free_bytes(here, there) == 1536
    assert free_bytes(there, here) == 1536
    # A place that is not there holds no records; with none to measure, nothing is known.
    assert free_bytes(here, gone) == 40960
    assert free_bytes(gone) is None
    assert free_bytes() is None
    monkeypatch.setattr(os, "statvfs", real)


def test_a_volume_that_cannot_be_measured_is_not_a_full_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    def refuses(path: object) -> object:
        raise PermissionError(13, "denied", str(path))

    monkeypatch.setattr(os, "statvfs", refuses)
    assert free_bytes(tmp_path) is None


def test_a_finished_session_that_lost_its_records_is_infrastructure_under_its_own_cause() -> None:
    end = classify_session_end(
        RESULT, exit_code=0, stopped_at_wall_clock=False, lost="transcript (ENOSPC)"
    )
    assert end == DISK_FULL
    assert classify_session_end(RESULT, exit_code=0, stopped_at_wall_clock=False) == COMPLETED


def test_a_session_that_ended_for_another_reason_keeps_that_reason() -> None:
    lost = "transcript (ENOSPC)"
    overloaded = {**RESULT, "is_error": True, "terminal_reason": "api_error"}
    end = classify_session_end(overloaded, exit_code=1, stopped_at_wall_clock=False, lost=lost)
    assert end.cause == "api_error"
    end = classify_session_end(RESULT, exit_code=0, stopped_at_wall_clock=True, lost=lost)
    assert end.cause == "wall_clock"
    turns = {**RESULT, "is_error": True, "terminal_reason": "max_turns"}
    end = classify_session_end(turns, exit_code=1, stopped_at_wall_clock=False, lost=lost)
    assert end.cause == "turn_limit"


def _left(run_dir: Path, session: str, text: str) -> None:
    sdir = run_dir / "sessions" / session
    sdir.mkdir(parents=True)
    started = "Mon Jan  1 00:00:00 2001"
    record = {"pid": 999_999, "started": started, "session_id": session}
    (sdir / "process.json").write_text(json.dumps(record))
    spawn_logged(run_dir, [(session, 999_999, started)])
    sentinel_installed(sdir, run_dir / "guarded")
    (sdir / "stdout.jsonl").write_text(text)


def _dispatcher(run_dir: Path, version: str) -> ClaudeDispatcher:
    return ClaudeDispatcher(
        config=make_config(claude_version=version),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=INSTALL_BIN,
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=Path("/nonexistent/review-scratch"),
    )


@pytest.mark.parametrize("version", ["2.1.322", "2.1.301"])
def test_a_leftover_that_ends_in_the_binary_s_event_is_a_forged_tail_on_every_pin(
    tmp_path: Path, version: str
) -> None:
    # No one measured the volume when a leftover ended: nothing bears its tail out.
    run_dir = tmp_path / "run"
    _left(run_dir, SESSION, NOT_SAVED)
    (left,) = _dispatcher(run_dir, version).stop_leftovers()
    assert left.tampered is not None and "after its result" in left.tampered
    assert [u.message_id for u in left.usage] == ["m1"]


def test_a_full_disk_halts_the_run_under_its_own_name_and_is_never_retried(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "disk_full"}), delays=(0.0, 0.0))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert [e.cause for e in ended] == ["disk_full"] and ended[0].attempt_commit is None
    # One session, no retry, and no forgery named: the halt carries the cause itself.
    assert len(rig.dispatcher.requests) == 1
    assert not [e for e in events if isinstance(e, InfraRetryScheduled)]
    assert not [e for e in events if isinstance(e, Incident)]
    (halt,) = [e for e in events if isinstance(e, Halted)]
    assert halt.reason == "disk_full" and "s1" in halt.detail


def test_a_run_halted_for_a_full_disk_is_resumed_by_no_one_until_a_person_has_looked(
    tmp_path: Path,
) -> None:
    assert "disk_full" not in RESUMABLE_HALTS
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "disk_full"}), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    again = rig.open()
    with pytest.raises(RunStateError, match="disk_full"):
        again.resume()
    again.close()
    assert len(rig.dispatcher.requests) == 1
