"""The token account: rebuilt from the log, deduplicated by message, routing zero."""

from __future__ import annotations

from pathlib import Path

import pytest
from orch_helpers import ticking_clock
from pydantic import ValidationError

from physgate.orchestrator.accounting import TokenAccount
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
