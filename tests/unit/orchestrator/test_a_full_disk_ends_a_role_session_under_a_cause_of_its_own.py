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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from left_session import INSTALL_BIN, sentinel_installed, spawn_logged
from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import make_config

from physgate.orchestrator.budget import WRITES_LOST_VERSIONS, SessionEnd, classify_session_end
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, captured_from, tail_owner
from physgate.orchestrator.events import Incident, InfraRetryScheduled, SessionEnded, read_events
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


@pytest.mark.parametrize("version", ["2.1.272", "2.1.283", "2.1.301", "9.9.9", ""])
def test_no_pin_but_one_measured_to_write_the_event_has_a_tail_of_its_own(version: str) -> None:
    assert tail_owner(version, SESSION) is None


def test_the_pin_measured_to_write_the_event_reads_it_for_the_session_itself() -> None:
    assert frozenset({"2.1.322"}) == WRITES_LOST_VERSIONS
    assert tail_owner("2.1.322", SESSION) == SESSION


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


def test_a_leftover_that_ends_in_the_binary_s_own_word_is_no_forgery_on_the_pin_that_writes_it(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, SESSION, NOT_SAVED)
    (left,) = _dispatcher(run_dir, "2.1.322").stop_leftovers()
    assert left.tampered is None and left.complete is True
    assert [u.message_id for u in left.usage] == ["m1"]


def test_a_leftover_with_the_same_bytes_on_the_earlier_pin_is_a_forged_tail(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, SESSION, NOT_SAVED)
    (left,) = _dispatcher(run_dir, "2.1.301").stop_leftovers()
    assert left.tampered is not None and "after its result" in left.tampered


def test_a_leftover_whose_tail_names_another_session_is_a_forged_tail_on_either_pin(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, OTHER, NOT_SAVED)
    (left,) = _dispatcher(run_dir, "2.1.322").stop_leftovers()
    assert left.tampered is not None


def test_the_loop_retries_a_full_disk_as_infrastructure_and_calls_nothing_a_forgery(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(infra={1: "disk_full"}), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    ended = [e for e in events if isinstance(e, SessionEnded)]
    assert ended[0].cause == "disk_full" and ended[0].attempt_commit is None
    assert [e for e in events if isinstance(e, InfraRetryScheduled)]
    assert not [e for e in events if isinstance(e, Incident)]
    # The retry is the same attempt in a fresh session: no attempt was spent.
    assert [r.attempt for r in rig.dispatcher.requests[:2]] == [1, 1]
