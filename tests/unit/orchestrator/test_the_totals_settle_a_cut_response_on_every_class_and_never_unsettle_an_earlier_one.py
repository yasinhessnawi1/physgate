"""How the binary's totals settle a cut response, at the edges of the rule.

The totals (``modelUsage``) settle a response the binary cut short by equality: where they equal
every line, the cut ones included, each cut response is counted; where they equal every line but
the cut ones, it is kept apart (read only at an API error's end). The rows here hold the edges:

- the equality is on all four token classes, never on one: a cut response whose only usage is a
  cache read, at totals that leave it out, is kept apart, not taken for counted;
- a cut response that started with no usage satisfies both shapes. It is read the one way the
  rule reads first, as counted, at any end; nothing it holds is in doubt;
- a session that compacted and also holds a cut response: the difference between the totals and
  the lines is read as the compaction's call, and cannot tell a cut response's usage from it.
  At a completed end such a session is refused, as before. At an API error's end each token the
  totals count is counted once: the sums equal the totals, the cut response listed apart;
- a mark an earlier invocation's totals set stands: a resumed invocation that compacted has
  totals that equal no plain sum of the lines, and its settling must not clear that mark.

The per-model totals are summed over every model before the comparison: the lines do not carry
the model that answered them, so the comparison cannot be held per model.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_a_response_cut_short_by_an_api_error_is_kept_apart_from_the_binary_s_totals import (
    FIRST_FINAL,
    _result,
)

from physgate.orchestrator.accounting import (
    TokenAccount,
    compaction_line,
    require_matching_totals,
    settle,
)
from physgate.orchestrator.exceptions import AccountingError
from physgate.orchestrator.protocols import MessageUsage, Usage

#: The complete response every row starts with.
FIRST = MessageUsage(message_id="msg_01", usage=Usage(**FIRST_FINAL))
#: A cut response that started with a cache read and nothing else.
READ_ONLY = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=7, cache_creation_input_tokens=0
)
ZERO = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)
#: A cut response as both pins' scripted endpoint started it.
CUT_USAGE = Usage(
    input_tokens=2, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=55515
)
#: The compaction's own call: in the totals, in no line of the stream.
SUMMARY = Usage(
    input_tokens=3, output_tokens=500, cache_read_input_tokens=1000, cache_creation_input_tokens=0
)
#: A response a resumed invocation completed.
RESUMED = MessageUsage(
    message_id="msg_03",
    usage=Usage(
        input_tokens=3,
        output_tokens=240,
        cache_read_input_tokens=55515,
        cache_creation_input_tokens=0,
    ),
)


def _cut(usage: Usage, message_id: str = "msg_02") -> MessageUsage:
    return MessageUsage(message_id=message_id, usage=usage, abandoned=True)


def _sum(*usages: Usage) -> Usage:
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cache_read_input_tokens=sum(u.cache_read_input_tokens for u in usages),
        cache_creation_input_tokens=sum(u.cache_creation_input_tokens for u in usages),
    )


def _ended(totals: Usage, *, api_error: bool) -> dict[str, Any]:
    model_usage = {
        "inputTokens": totals.input_tokens,
        "outputTokens": totals.output_tokens,
        "cacheReadInputTokens": totals.cache_read_input_tokens,
        "cacheCreationInputTokens": totals.cache_creation_input_tokens,
    }
    if api_error:
        ended: dict[str, Any] = json.loads(_result(model_usage))
    else:
        ended = json.loads(_result(model_usage, is_error=False, terminal="completed"))
    return ended


def _marked(lines: tuple[MessageUsage, ...], message_id: str = "msg_02") -> bool:
    (line,) = [m for m in lines if m.message_id == message_id]
    assert line.abandoned
    return line.in_binary_totals


# --- the comparison holds all four classes ------------------------------------------------------

EVERY_CLASS = "the totals settle a cut response on all four token classes, not on one"


def test_a_cut_response_whose_only_usage_is_a_cache_read_is_kept_apart_where_totals_omit_it() -> (
    None
):
    lines = (FIRST, _cut(READ_ONLY))
    # The totals are the complete response's: equal to every line in three classes of four.
    at_an_api_error = _ended(FIRST.usage, api_error=True)
    assert not _marked(settle(at_an_api_error, lines)), EVERY_CLASS
    try:
        settled = require_matching_totals(at_an_api_error, lines)
    except AccountingError as exc:
        pytest.fail(f"{EVERY_CLASS}: refused with {exc.context}")
    assert not _marked(settled), EVERY_CLASS
    # The same totals at a completed end leave a cut response out, and are refused.
    with pytest.raises(AccountingError):
        require_matching_totals(_ended(FIRST.usage, api_error=False), lines)


# --- a cut response that started with no usage --------------------------------------------------

NO_USAGE = "a cut response with no usage is read one way, as counted, at any end"


@pytest.mark.parametrize("api_error", [True, False], ids=["an API error's end", "a completed end"])
def test_a_cut_response_with_no_usage_is_counted_at_any_end(api_error: bool) -> None:
    lines = (FIRST, _cut(ZERO))
    ended = _ended(FIRST.usage, api_error=api_error)
    try:
        settled = require_matching_totals(ended, lines)
    except AccountingError as exc:
        pytest.fail(f"{NO_USAGE}: refused with {exc.context}")
    assert _marked(settled), NO_USAGE
    assert settle(ended, lines) == settled


# --- a compaction beside a cut response ---------------------------------------------------------

COMPACTED = "a compacted session with a cut response counts each token of the totals once"


@pytest.mark.parametrize(
    "counts_the_cut", [True, False], ids=["totals counting it", "totals leaving it out"]
)
def test_a_compacted_session_with_a_cut_response_is_refused_at_a_completed_end(
    counts_the_cut: bool,
) -> None:
    lines = (FIRST, _cut(CUT_USAGE))
    totals = _sum(FIRST.usage, *([CUT_USAGE] if counts_the_cut else []), SUMMARY)
    ended = _ended(totals, api_error=False)
    with pytest.raises(AccountingError) as caught:
        compaction_line(ended, settle(ended, lines), compactions=1, message_id="compaction-1")
    assert caught.value.context.get("message_id") == "msg_02"


@pytest.mark.parametrize(
    "counts_the_cut", [True, False], ids=["totals counting it", "totals leaving it out"]
)
def test_a_compacted_session_with_a_cut_response_at_an_api_error_counts_each_token_once(
    counts_the_cut: bool,
) -> None:
    lines = (FIRST, _cut(CUT_USAGE))
    totals = _sum(FIRST.usage, *([CUT_USAGE] if counts_the_cut else []), SUMMARY)
    ended = _ended(totals, api_error=True)
    # As the reviewer reads a session's end: the lines settled, then the compaction's line.
    settled = settle(ended, lines)
    line = compaction_line(ended, settled, compactions=1, message_id="compaction-1")
    assert line is not None and line.compaction
    # The difference cannot tell the cut response's usage from the compaction's call.
    assert line.usage == (_sum(CUT_USAGE, SUMMARY) if counts_the_cut else SUMMARY)
    account = TokenAccount()
    for m in (*settled, line):
        account.add(
            "reviewer:rev-1",
            m.message_id,
            m.usage,
            abandoned=m.abandoned,
            in_binary_totals=m.in_binary_totals,
        )
    assert account.total() == totals, f"{COMPACTED}: the sums are not the binary's totals"
    # Kept apart from those sums and listed once, its billing unknown.
    assert account.abandoned() == {"reviewer:rev-1": CUT_USAGE}, COMPACTED
    assert account.cut_in_binary_totals() == {}


# --- an earlier invocation's mark ---------------------------------------------------------------

STANDS = "a cut response an earlier invocation's totals counted stays counted"


def test_an_earlier_invocation_s_counted_mark_stands_when_a_resumed_one_compacted() -> None:
    # The first invocation ends in an API error; its totals count the cut response.
    first = (FIRST, _cut(CUT_USAGE))
    prior = require_matching_totals(_ended(_sum(FIRST.usage, CUT_USAGE), api_error=True), first)
    assert _marked(prior)
    # Resumed, the session compacts and completes. Its totals are the whole session's, the
    # compaction's call included, so no plain sum of the lines equals them.
    totals = _sum(FIRST.usage, CUT_USAGE, RESUMED.usage, SUMMARY)
    ended = _ended(totals, api_error=False)
    usage = settle(ended, (*prior, RESUMED))
    assert _marked(usage), f"{STANDS}: the resumed invocation's settling cleared it"
    try:
        line = compaction_line(ended, usage, compactions=1, message_id="compaction-1")
    except AccountingError as exc:
        pytest.fail(f"{STANDS}: the resumed review was refused with {exc.context}")
    assert line is not None and line.usage == SUMMARY, STANDS
