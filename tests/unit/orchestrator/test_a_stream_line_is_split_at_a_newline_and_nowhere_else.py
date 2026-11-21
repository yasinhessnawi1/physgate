"""Every reader of a stream, a log or a record splits it into lines at a newline and nowhere else.

The binary writes one JSON event per line. A JSON string may hold U+2028, U+2029 or U+0085 as
themselves (both pinned binaries write the first two raw; 2.1.301 writes U+0085 raw too), and
``str.splitlines`` splits at each of them, so a reader that used it cut one event in two: the
indicator scan refused the stream, the transcript showed two unreadable lines, the result went
unseen, a forged tail after a result passed, and an abort went unrecorded. A reader of the bytes
splits only at the newline byte; every reader here reads the lines the bytes have.

Each row plants one event with such a character inside a string, with a marker on each side,
and asserts the reader saw the one event whole.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import physgate.reviewers.claude as claude
from physgate.evaluation.observe import calls, sequence
from physgate.orchestrator.decompose import model_declined, read_stream, schema_refusal
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.trajectory import forged_tail, result_lines, through_first_result
from physgate.oslayer.abort import aborted_tool_uses, is_abort
from physgate.reviewers.scan import ScanUnreadableError, scan
from physgate.reviewers.transcript import render

#: The characters ``str.splitlines`` splits at that a JSON string may hold as themselves.
BREAKS = [" ", " ", "\u0085"]
IDS = ["U+2028", "U+2029", "U+0085"]
LEFT, RIGHT = "MARKER-LEFT-7f3a", "MARKER-RIGHT-9c1d"


def _line(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def _write(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": "m1",
            "model": "claude-sonnet-5",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Write",
                    "input": {"file_path": "/w/m/x.py", "content": text},
                }
            ],
        },
    }


def _result(text: str) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "result": text,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _split(brk: str) -> str:
    return f"{LEFT}{brk}{RIGHT}"


def _try(call: Any, *args: Any) -> Any:  # noqa: ANN401 - whatever the reader returns, or raised
    try:
        return call(*args)
    except (ScanUnreadableError, json.JSONDecodeError) as exc:
        return exc


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_indicator_scan_reads_the_event_whole(brk: str) -> None:
    hits = _try(scan, _line(_write(_split(brk))))
    assert not isinstance(hits, Exception), f"the scan cut one event in two: {hits}"


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_reviewer_s_transcript_shows_the_event_as_an_event(brk: str) -> None:
    rendered, _ = render(_line(_write(_split(brk))))
    assert "a line that is not an event" not in rendered
    assert LEFT in rendered and RIGHT in rendered


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_reviewer_s_transcript_keeps_the_character_where_it_stood(brk: str) -> None:
    rendered, _ = render(_line(_write(_split(brk))))
    assert any(LEFT in line and RIGHT in line for line in rendered.split("\n"))


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_review_s_end_reads_every_event_whole(brk: str) -> None:
    events = claude._events(_line(_write(_split(brk))) + _line(_result("ok")))
    assert [e["type"] for e in events] == ["assistant", "result"]


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_stream_s_result_is_read_when_its_text_holds_the_character(brk: str) -> None:
    result, _, _ = read_stream(_line(_write("x")) + _line(_result(_split(brk))))
    assert result is not None and result["result"] == _split(brk)


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_refused_structured_answer_is_read_when_its_text_holds_the_character(brk: str) -> None:
    refusal = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "is_error": True,
                    "content": f"Output does not match required schema: {_split(brk)}",
                }
            ]
        },
    }
    told = schema_refusal(_line(refusal))
    assert told is not None and RIGHT in told


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_tail_after_a_result_whose_text_holds_the_character_is_still_forged(brk: str) -> None:
    stream = _line(_write("x")) + _line(_result(_split(brk))) + _line(_write("forged"))
    assert result_lines(stream) == [1]
    told = forged_tail(stream)
    assert told is not None and "after its result" in told
    assert through_first_result(stream) == _line(_write("x")) + _line(_result(_split(brk)))


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_stream_that_ends_at_its_result_is_not_forged_by_the_character_before_it(
    brk: str,
) -> None:
    # The lines after the result are counted in the same lines the result was found in: an
    # earlier event holding the character must not push the result itself into its own tail.
    stream = _line(_write(_split(brk))) + _line(_result("done"))
    assert result_lines(stream) == [1]
    assert forged_tail(stream) is None
    assert through_first_result(stream) == stream


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_evaluation_reads_the_runtime_s_result_whole(brk: str) -> None:
    found = calls._runtime_result(_line(_result(_split(brk))))
    assert found is not None and found["result"] == _split(brk)


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_an_abort_in_an_event_that_holds_the_character_is_found(brk: str) -> None:
    event = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t9",
                    "is_error": True,
                    "content": f"bwrap: setting up uid map: Permission denied\n{_split(brk)}",
                }
            ]
        },
    }
    assert aborted_tool_uses(_line(event)) == ("t9",)


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_command_s_own_output_cannot_start_a_line_of_bubblewrap_s_after_the_character(
    brk: str,
) -> None:
    assert not is_abort(f"done{brk}bwrap: a line the command printed itself")


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_the_hook_log_is_read_whole_when_a_record_holds_the_character(
    tmp_path: Path, brk: str
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    records: list[dict[str, Any]] = [
        {"session": "s1", "decision": "reaper_unverified", "tool_input": {"command": _split(brk)}},
        {"session": "s1", "decision": "journal append", "line": _split(brk)},
    ]
    (state / "hooks.log.jsonl").write_text("".join(_line(r) for r in records))
    unverified = _try(ClaudeDispatcher._reaper_unverified, state, "s1")
    assert not isinstance(unverified, Exception), f"a hook-log record was cut: {unverified}"
    assert len(unverified) == 1 and RIGHT in unverified[0]
    log = _try(ClaudeDispatcher._hook_log, state, "s1")
    assert not isinstance(log, Exception), f"a hook-log record was cut: {log}"


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_run_record_whose_line_holds_the_character_is_read_whole(
    tmp_path: Path, brk: str
) -> None:
    path = tmp_path / "queue.jsonl"
    path.write_text(_line({"item_id": "q1", "detail": _split(brk)}))
    lines = _try(sequence._lines, path)
    assert not isinstance(lines, Exception), f"a record line was cut: {lines}"
    assert lines == [{"item_id": "q1", "detail": _split(brk)}]


@pytest.mark.parametrize("brk", BREAKS, ids=IDS)
def test_a_model_s_refusal_is_read_when_its_event_holds_the_character(brk: str) -> None:
    # The plan call reads a model's refusal from an event of its own; an event cut in two at
    # the character is no event, and the refusal would go unseen.
    refusal = {
        "type": "system",
        "subtype": "model_refusal_notice",
        "message": f"{LEFT}{brk}{RIGHT}",
    }
    assert model_declined(_line(refusal) + _line(_result("ok"))) is True
    # The same words inside another event's string are one string of that event.
    quoted = _line(_write(f"{LEFT}{brk}{json.dumps(refusal, ensure_ascii=False)}{brk}{RIGHT}"))
    assert model_declined(quoted + _line(_result("ok"))) is False
