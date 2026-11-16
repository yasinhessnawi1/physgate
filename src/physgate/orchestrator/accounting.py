"""The token account: every token attributed, and none to routing (ARCH-001).

The account is rebuilt from the run-event log, never kept only in memory. Every
token belongs to exactly one of four things: the decomposition call, a role
session, a reviewer, or routing. The first three are what a run is meant to
spend. Routing is the loop deciding what runs next or whether to merge, which in
the deterministic binding is code and costs nothing; its bucket exists so that
the claim "zero tokens on routing" is an assertion over a number rather than an
absence nobody checked.

Usage is keyed by message id. Claude Code's stream repeats a message's usage
once per content block, so summing per stream event over-counts (measured: two
events of one message, 40 input tokens summed against 30 charged). A message
seen twice is counted once, and seeing it twice with different usage is an
error, not a choice between them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from physgate.orchestrator.events import Event, TokensUsed
from physgate.orchestrator.exceptions import AccountingError, RoutingTokensError
from physgate.orchestrator.protocols import MessageUsage, Usage

_ZERO = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


def _plus(left: Usage, right: Usage) -> Usage:
    return Usage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cache_read_input_tokens=left.cache_read_input_tokens + right.cache_read_input_tokens,
        cache_creation_input_tokens=(
            left.cache_creation_input_tokens + right.cache_creation_input_tokens
        ),
    )


#: The result's per-model totals, by the account's field names.
_MODEL_USAGE_FIELDS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}


def require_matching_totals(
    # The binary's result object: an untyped boundary, only its totals are read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> None:
    """Hold one invocation's per-message account against the binary's own totals.

    The result's ``modelUsage`` sums every model the invocation used. A session
    with no result (killed, or stopped at its wall clock) has nothing to hold it
    against, and is not checked.

    Raises:
        AccountingError: a field's per-message sum differs from the result's total.
    """
    per_model = (result or {}).get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return
    total = _ZERO
    for message in usages:
        total = _plus(total, message.usage)
    for field, key in _MODEL_USAGE_FIELDS.items():
        charged = sum(int(m.get(key) or 0) for m in per_model.values() if isinstance(m, dict))
        counted = int(getattr(total, field))
        if counted != charged:
            msg = "the per-message account differs from the binary's own totals"
            raise AccountingError(msg, field=field, account=str(counted), result=str(charged))


#: The most one compaction call may add to the binary's input totals (fresh, cache read and cache
#: written together): the context window both pinned binaries report for the reviewer's model
#: (``modelUsage.contextWindow``, 1,000,000). The call reads the conversation it summarises,
#: which the window bounds.
COMPACTION_INPUT_BOUND = 1_000_000
#: The most one compaction call may add to the output totals: the output cap both pinned binaries
#: report for the reviewer's model (``modelUsage.maxOutputTokens``, 64,000).
COMPACTION_OUTPUT_BOUND = 64_000


def compaction_line(
    # The binary's result object: an untyped boundary, only its totals are read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
    *,
    compactions: int,
    message_id: str,
) -> MessageUsage | None:
    """The usage of an invocation's compaction calls as one line, or ``None`` if there is none.

    The call that writes a compaction's summary is counted in the result's ``modelUsage`` and is
    no message of the stream (measured on both pinned binaries). So where the invocation's stream
    shows ``compactions`` boundaries, the totals less every message counted so far (``usages``,
    an earlier invocation's compaction line included) is those calls' usage, counted once. Where
    the stream shows none, the totals are held to the messages as :func:`require_matching_totals`
    holds them. A result without totals has nothing to hold the messages against.

    Raises:
        AccountingError: a difference without a boundary; a field the totals charge less than
            the messages; more than ``compactions`` calls could add.
    """
    usages = tuple(usages)
    if compactions == 0:
        require_matching_totals(result, usages)
        return None
    per_model = (result or {}).get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return None
    counted = _ZERO
    for message in usages:
        counted = _plus(counted, message.usage)
    difference: dict[str, int] = {}
    for field, key in _MODEL_USAGE_FIELDS.items():
        charged = sum(int(m.get(key) or 0) for m in per_model.values() if isinstance(m, dict))
        account = int(getattr(counted, field))
        difference[field] = charged - account
        if difference[field] < 0:
            msg = "the binary's totals are less than the per-message account"
            raise AccountingError(msg, field=field, account=str(account), result=str(charged))
    read = sum(v for f, v in difference.items() if f != "output_tokens")
    if read > compactions * COMPACTION_INPUT_BOUND:
        msg = "more input than the compactions the stream shows could have read"
        raise AccountingError(msg, compactions=str(compactions), difference=str(read))
    written = difference["output_tokens"]
    if written > compactions * COMPACTION_OUTPUT_BOUND:
        msg = "more output than the compactions the stream shows could have written"
        raise AccountingError(msg, compactions=str(compactions), difference=str(written))
    if not any(difference.values()):
        return None
    return MessageUsage(message_id=message_id, usage=Usage(**difference), compaction=True)


class TokenAccount:
    """Tokens per attribution, deduplicated by message id."""

    def __init__(self) -> None:
        """An empty account."""
        self._messages: dict[tuple[str, str], Usage] = {}

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> TokenAccount:
        """The account a run's event log records."""
        account = cls()
        for event in events:
            if isinstance(event, TokensUsed):
                account.add(event.attribution, event.message_id, event.usage)
        return account

    def add(self, attribution: str, message_id: str, usage: Usage) -> None:
        """Count one message's usage once.

        Raises:
            AccountingError: the same message was already counted with other usage.
        """
        key = (attribution, message_id)
        seen = self._messages.get(key)
        if seen is not None and seen != usage:
            msg = "one message reported with two different usages"
            raise AccountingError(msg, attribution=attribution, message_id=message_id)
        self._messages[key] = usage

    def by_attribution(self) -> dict[str, Usage]:
        """Summed usage per attribution, e.g. ``session:<id>``."""
        totals: dict[str, Usage] = {}
        for (attribution, _), usage in sorted(self._messages.items()):
            totals[attribution] = _plus(totals.get(attribution, _ZERO), usage)
        return totals

    def by_kind(self) -> dict[str, Usage]:
        """Summed usage per kind of spender: decomposition, session, reviewer, routing."""
        totals = {kind: _ZERO for kind in ("decomposition", "session", "reviewer", "routing")}
        for attribution, usage in self.by_attribution().items():
            kind = attribution.split(":", 1)[0]
            totals[kind] = _plus(totals[kind], usage)
        return totals

    def total(self) -> Usage:
        """Every token the run spent, each counted once: the sum over every attribution.

        A run's headline figure. Summed here, by the account that deduplicated each
        message, so a reader never totals the parts itself and never counts a message
        twice.
        """
        total = _ZERO
        for usage in self.by_attribution().values():
            total = _plus(total, usage)
        return total

    def decomposition_invocations(self) -> int:
        """How many distinct decomposition calls spent tokens. A run makes one."""
        return len({a for a, _ in self._messages if a.startswith("decomposition:")})

    def assert_no_routing(self) -> None:
        """Raise unless routing spent nothing.

        Raises:
            RoutingTokensError: any token is attributed to routing.
        """
        routing = self.by_kind()["routing"]
        if routing.total():
            msg = "tokens were spent on routing in the deterministic binding"
            raise RoutingTokensError(msg, tokens=str(routing.total()))
