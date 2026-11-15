"""A compaction's own model call is counted exactly once, and nothing else is let through.

Measured on both pinned binaries at the scripted endpoint: the call that writes a compaction's
summary is no message of the stream, and the result's per-model totals include it. So the
per-message account differs from the totals by exactly that call. Where the stream shows a
compaction boundary, the difference is taken as that invocation's compaction usage and recorded
as a line of its own, marked as one; where it shows none, any difference raises as before. A
difference that is negative in any field, or larger than a compaction call can be, raises too.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from physgate.orchestrator import accounting
from physgate.orchestrator.events import TokensUsed
from physgate.orchestrator.exceptions import AccountingError
from physgate.orchestrator.protocols import MessageUsage, Usage


def _usage(i: int, o: int, r: int = 0, c: int = 0) -> Usage:
    return Usage(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=r, cache_creation_input_tokens=c
    )


MESSAGES = (
    MessageUsage(message_id="m1", usage=_usage(5, 9, 998_984, 2)),
    MessageUsage(message_id="m2", usage=_usage(5, 9, 3, 2)),
)
#: The compaction call's own figures, as the scripted endpoint gave them.
CALL = _usage(70_001, 301)


Extra = tuple[int, int, int, int]


def _ints(u: Usage) -> Extra:
    return (
        u.input_tokens,
        u.output_tokens,
        u.cache_read_input_tokens,
        u.cache_creation_input_tokens,
    )


def _result(extra: Usage | Extra) -> dict[str, Any]:
    """A result whose totals are the messages' and ``extra`` (input, output, read, creation)."""
    more = _ints(extra) if isinstance(extra, Usage) else extra
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    keys = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
    totals = {
        key: sum(int(getattr(m.usage, field)) for m in MESSAGES) + add
        for field, key, add in zip(fields, keys, more, strict=True)
    }
    return {"modelUsage": {"claude-sonnet-5": totals}}


def _counter() -> Callable[..., MessageUsage | None]:
    count = getattr(accounting, "compaction_line", None)
    assert count is not None, "no reader of a compaction's own usage"
    return count  # type: ignore[no-any-return]


def test_a_difference_with_a_boundary_is_one_line_of_that_compaction_s_usage() -> None:
    line = _counter()(_result(CALL), MESSAGES, compactions=1, message_id="compaction-1")
    assert line is not None
    assert line.usage == CALL and line.message_id == "compaction-1"
    assert getattr(line, "compaction", False) is True


def test_with_the_line_the_account_matches_the_binary_s_totals() -> None:
    line = _counter()(_result(CALL), MESSAGES, compactions=1, message_id="compaction-1")
    assert line is not None
    accounting.require_matching_totals(_result(CALL), (*MESSAGES, line))


def test_three_compactions_in_one_invocation_are_one_line_of_all_three() -> None:
    thrice = _usage(3 * 70_001, 3 * 301)
    line = _counter()(_result(thrice), MESSAGES, compactions=3, message_id="compaction-1")
    assert line is not None and line.usage == thrice


def test_without_a_boundary_any_difference_still_raises() -> None:
    with pytest.raises(AccountingError) as refused:
        _counter()(_result(CALL), MESSAGES, compactions=0, message_id="compaction-1")
    assert refused.value.context["field"] == "input_tokens"


def test_without_a_boundary_and_no_difference_there_is_no_line() -> None:
    assert _counter()(_result(_usage(0, 0)), MESSAGES, compactions=0, message_id="c-1") is None


def test_a_boundary_with_no_difference_adds_no_line() -> None:
    # A resume after a compaction: its earlier line is already in the account, so no new one.
    assert _counter()(_result(_usage(0, 0)), MESSAGES, compactions=1, message_id="c-1") is None


@pytest.mark.parametrize(
    "extra",
    [(-1, 301, 0, 0), (70_001, -1, 0, 0), (70_001, 301, -1, 0), (70_001, 301, 0, -1)],
    ids=["input", "output", "cache_read", "cache_creation"],
)
def test_a_negative_difference_in_any_field_raises(extra: Extra) -> None:
    # A field the totals charge less than the messages: not a compaction's call.
    with pytest.raises(AccountingError):
        _counter()(_result(extra), MESSAGES, compactions=1, message_id="compaction-1")


def test_a_difference_past_the_bound_per_boundary_raises() -> None:
    bound = getattr(accounting, "COMPACTION_INPUT_BOUND", None)
    assert bound == 1_000_000
    at = _usage(bound - 10, 0, 10)
    assert _counter()(_result(at), MESSAGES, compactions=1, message_id="c-1") is not None
    past = _usage(bound - 10, 0, 11)
    with pytest.raises(AccountingError):
        _counter()(_result(past), MESSAGES, compactions=1, message_id="c-1")
    # The bound is per boundary: two compactions may be twice as large.
    assert _counter()(_result(past), MESSAGES, compactions=2, message_id="c-1") is not None


def test_an_output_past_the_bound_per_boundary_raises() -> None:
    bound = getattr(accounting, "COMPACTION_OUTPUT_BOUND", None)
    assert bound == 64_000
    assert (
        _counter()(_result(_usage(1, bound)), MESSAGES, compactions=1, message_id="c") is not None
    )
    with pytest.raises(AccountingError):
        _counter()(_result(_usage(1, bound + 1)), MESSAGES, compactions=1, message_id="c")


def test_a_result_without_totals_is_not_held_and_gives_no_line() -> None:
    assert _counter()({}, MESSAGES, compactions=1, message_id="compaction-1") is None
    assert _counter()(None, MESSAGES, compactions=1, message_id="compaction-1") is None


def _line(**extra: Any) -> dict[str, Any]:  # noqa: ANN401 - a line's own fields
    line = {
        "seq": 0,
        "ts": "2026-11-16T00:00:00.000000Z",
        "run_id": "r1",
        "gate_mode": "on",
        "kind": "tokens_used",
        "attribution": "reviewer:s1",
        "message_id": "m1",
        "usage": CALL.model_dump(),
        **extra,
    }
    return line


def test_the_mark_is_left_out_of_every_line_that_is_no_compaction() -> None:
    plain = MessageUsage(message_id="m1", usage=CALL)
    assert "compaction" not in plain.model_dump()
    line = TokensUsed.model_validate_json(json.dumps(_line()))
    assert "compaction" not in line.model_dump()
    try:
        marked: dict[str, Any] = TokensUsed.model_validate_json(
            json.dumps(_line(message_id="compaction-1", compaction=True))
        ).model_dump()
    except ValidationError:
        marked = {}
    assert marked.get("compaction") is True
