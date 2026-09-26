"""The token account: rebuilt from the log, deduplicated by message, routing zero."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orch_helpers import ticking_clock
from pydantic import ValidationError

from physgate.orchestrator.accounting import TokenAccount, require_matching_totals
from physgate.orchestrator.decompose import read_stream
from physgate.orchestrator.events import (
    EventLog,
    RunStarted,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import AccountingError, RoutingTokensError
from physgate.orchestrator.protocols import Usage


def usage(i: int, o: int, cr: int = 0, cc: int = 0) -> Usage:
    return Usage(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cc
    )


def _log(path: Path) -> EventLog:
    log = EventLog(path, run_id="run-1", gate_mode="on", clock=ticking_clock())
    log.emit(RunStarted, config_sha256="c" * 64)
    return log


def test_a_message_repeated_per_content_block_is_counted_once(tmp_path: Path) -> None:
    # The measured case: one message with a text block and a tool call arrives as
    # two stream events carrying the same id and the same usage, then a second
    # message. Summed per event that is 40 input tokens; charged, it is 30.
    path = tmp_path / "e.jsonl"
    log = _log(path)
    for message_id, u in (("m1", usage(10, 5)), ("m1", usage(10, 5)), ("m2", usage(20, 7))):
        log.emit(TokensUsed, attribution="session:abc", message_id=message_id, usage=u)
    log.close()
    account = TokenAccount.from_events(read_events(path))
    assert account.by_attribution() == {"session:abc": usage(30, 12)}


def test_cache_reads_and_writes_stay_separate() -> None:
    account = TokenAccount()
    account.add("session:a", "m1", usage(10, 5, cr=100, cc=50))
    account.add("session:a", "m2", usage(20, 7, cr=200, cc=0))
    assert account.by_attribution()["session:a"] == usage(30, 12, cr=300, cc=50)


def test_one_message_with_two_usages_is_an_error_not_a_choice() -> None:
    account = TokenAccount()
    account.add("session:a", "m1", usage(10, 5))
    with pytest.raises(AccountingError):
        account.add("session:a", "m1", usage(11, 5))


def test_every_token_lands_in_exactly_one_kind_and_routing_is_zero() -> None:
    account = TokenAccount()
    account.add("decomposition:d1", "m0", usage(100, 50))
    account.add("session:s1", "m1", usage(10, 5))
    account.add("reviewer:r1", "m2", usage(7, 3))
    kinds = account.by_kind()
    assert kinds["decomposition"].total() == 150
    assert kinds["session"].total() == 15
    assert kinds["reviewer"].total() == 10
    assert kinds["routing"].total() == 0
    assert sum(u.total() for u in kinds.values()) == 175
    account.assert_no_routing()
    assert account.decomposition_invocations() == 1


def test_a_single_routing_token_fails_the_assertion() -> None:
    account = TokenAccount()
    account.add("session:s1", "m1", usage(10, 5))
    account.add("routing:loop", "m2", usage(0, 1))
    with pytest.raises(RoutingTokensError) as caught:
        account.assert_no_routing()
    assert caught.value.context["tokens"] == "1"


def test_two_decomposition_calls_are_counted_as_two() -> None:
    account = TokenAccount()
    account.add("decomposition:d1", "m1", usage(1, 1))
    account.add("decomposition:d2", "m2", usage(1, 1))
    assert account.decomposition_invocations() == 2


@pytest.mark.parametrize(
    "attribution", ["", "session", "planner:x", "session:", "routing", "reviewer:a b", "SESSION:x"]
)
def test_an_attribution_outside_the_closed_set_cannot_be_recorded(
    tmp_path: Path, attribution: str
) -> None:
    log = _log(tmp_path / "e.jsonl")
    with pytest.raises(ValidationError):
        log.emit(TokensUsed, attribution=attribution, message_id="m1", usage=usage(1, 1))
    log.close()


def _line(event: dict[str, object]) -> str:
    return json.dumps(event)


def _assistant(message_id: str, usage: dict[str, int], block: str) -> str:
    content = [{"type": block}]
    message = {"id": message_id, "model": "claude-sonnet-5", "usage": usage, "content": content}
    return _line({"type": "assistant", "message": message})


def _stream(kind: str, payload: dict[str, object], thread: str | None = None) -> str:
    return _line(
        {"type": "stream_event", "event": {"type": kind, **payload}, "parent_tool_use_id": thread}
    )


def _result(input_: int, output: int, read: int, created: int) -> str:
    totals = {
        "inputTokens": input_,
        "outputTokens": output,
        "cacheReadInputTokens": read,
        "cacheCreationInputTokens": created,
    }
    return _line({"type": "result", "modelUsage": {"claude-sonnet-5": totals}})


START = {
    "input_tokens": 5,
    "cache_read_input_tokens": 3,
    "cache_creation_input_tokens": 2,
    "output_tokens": 1,
}
FINAL = {**START, "output_tokens": 9}


def test_each_message_counts_its_final_usage_once_and_matches_the_binary_s_totals() -> None:
    # Two messages; the first has a text block and a tool call, so the binary
    # writes two assistant events for it, each with the usage it started with.
    stream = "\n".join(
        [
            _stream("message_start", {"message": {"id": "m1", "usage": START}}),
            _assistant("m1", START, "text"),
            _assistant("m1", START, "tool_use"),
            _stream("message_delta", {"usage": FINAL}),
            _stream("message_start", {"message": {"id": "m2", "usage": START}}),
            _assistant("m2", START, "text"),
            _stream("message_delta", {"usage": FINAL}),
            _result(10, 18, 6, 4),
        ]
    )
    result, usages, _ = read_stream(stream)
    assert [(u.message_id, u.usage.output_tokens) for u in usages] == [("m1", 9), ("m2", 9)]
    require_matching_totals(result, usages)
    # The earlier measurement, under the corrected rule: summed per event the
    # input is 15 against the binary's 10 (it was 40 against 30), and the start
    # usage alone would give 3 output tokens against 18.
    per_event = sum(
        json.loads(line)["message"]["usage"]["input_tokens"]
        for line in stream.splitlines()
        if '"assistant"' in line
    )
    assert per_event == 15 and sum(u.usage.input_tokens for u in usages) == 10


def test_the_real_stream_s_start_usage_is_caught_by_the_cross_check() -> None:
    # The decomposition call against the real API (2.1.272, 26.09.2026), without
    # partial messages: the message's events carried 2 output tokens; the
    # binary's totals said 673.
    started = {
        "input_tokens": 2,
        "cache_creation_input_tokens": 10958,
        "cache_read_input_tokens": 0,
        "output_tokens": 2,
    }
    stream = "\n".join(
        [
            _assistant("m", started, "thinking"),
            _assistant("m", started, "tool_use"),
            _result(2, 673, 0, 10958),
        ]
    )
    result, usages, _ = read_stream(stream)
    with pytest.raises(AccountingError) as caught:
        require_matching_totals(result, usages)
    assert caught.value.context == {"field": "output_tokens", "account": "2", "result": "673"}


def test_a_message_without_its_delta_keeps_its_start_and_no_result_is_unchecked() -> None:
    killed = "\n".join(
        [
            _stream("message_start", {"message": {"id": "m", "usage": START}}),
            _assistant("m", START, "text"),
        ]
    )
    result, usages, _ = read_stream(killed)
    assert result is None and usages[0].usage.output_tokens == 1
    require_matching_totals(result, usages)  # nothing to hold it against


def test_threads_keep_their_own_open_message() -> None:
    stream = "\n".join(
        [
            _stream("message_start", {"message": {"id": "main", "usage": START}}),
            _stream("message_start", {"message": {"id": "sub", "usage": START}}, thread="toolu_1"),
            _stream("message_delta", {"usage": {**START, "output_tokens": 4}}, thread="toolu_1"),
            _stream("message_delta", {"usage": FINAL}),
        ]
    )
    _, usages, _ = read_stream(stream)
    assert {u.message_id: u.usage.output_tokens for u in usages} == {"main": 9, "sub": 4}
