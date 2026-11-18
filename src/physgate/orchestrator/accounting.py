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

A response the binary cut short and closed itself (its stream broke, stalled or
ended early) has only the usage it started with, and where the session then
ended in an API error it is not in the binary's per-model totals (measured: a
review whose network broke mid-response, its result's ``modelUsage`` the first
response's alone while its top-level ``usage`` added the cut one). Whether the
API billed it is unknown: the request was accepted and its cache writes begun.
Such a line is marked ``abandoned``: it is recorded under the attribution that
spent it and kept apart from every sum held to those totals, so each token they
count is still in exactly one bucket and the cut one is visible beside them. A
cut response in a session that ended any other way is an error.
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


def ended_in_api_error(
    # The binary's result object: an untyped boundary, only its end is read.
    result: Mapping[str, object] | None,
) -> bool:
    """Whether the binary's result is an API error's end, as every session's end reads one."""
    return (
        result is not None
        and result.get("is_error") is True
        and result.get("terminal_reason") == "api_error"
    )


def lines_in_totals(
    # The binary's result object: an untyped boundary, only its end is read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> tuple[MessageUsage, ...]:
    """The lines the binary's per-model totals count: every one but a response it cut short.

    A cut response (``abandoned``) is in none of those totals where the session ended in an
    API error, and is left out of the sum held to them; whether it was billed is unknown. In a
    session that ended any other way nothing says the totals left it out, so the account is
    refused rather than read.

    Raises:
        AccountingError: a cut response in a session whose result is no API error's end.
    """
    usages = tuple(usages)
    cut = [m.message_id for m in usages if m.abandoned]
    if cut and not ended_in_api_error(result):
        msg = "a response the binary cut short, in a session that did not end in an API error"
        end = str((result or {}).get("terminal_reason"))
        raise AccountingError(msg, message_id=cut[0], terminal_reason=end)
    return tuple(m for m in usages if not m.abandoned)


def require_matching_totals(
    # The binary's result object: an untyped boundary, only its totals are read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> None:
    """Hold one invocation's per-message account against the binary's own totals.

    The result's ``modelUsage`` sums every model the invocation used, and is held to
    every line they count (:func:`lines_in_totals`), field by field and exactly. A session
    with no result (killed, or stopped at its wall clock) has nothing to hold it
    against, and is not checked.

    Raises:
        AccountingError: a field's per-message sum differs from the result's total, or
            a response was cut short in a session that did not end in an API error.
    """
    per_model = (result or {}).get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return
    total = _ZERO
    for message in lines_in_totals(result, usages):
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
    holds them. A result without totals has nothing to hold the messages against. Either way
    a response the binary cut short is no message the totals count (:func:`lines_in_totals`).

    Raises:
        AccountingError: a difference without a boundary; a field the totals charge less than
            the messages; more than ``compactions`` calls could add; a response cut short in a
            session that did not end in an API error.
    """
    usages = tuple(usages)
    if compactions == 0:
        require_matching_totals(result, usages)
        return None
    per_model = (result or {}).get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return None
    counted = _ZERO
    for message in lines_in_totals(result, usages):
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
    """Tokens per attribution, deduplicated by message id; a cut response kept apart."""

    def __init__(self) -> None:
        """An empty account."""
        self._messages: dict[tuple[str, str], tuple[Usage, bool]] = {}

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> TokenAccount:
        """The account a run's event log records."""
        account = cls()
        for event in events:
            if isinstance(event, TokensUsed):
                account.add(
                    event.attribution, event.message_id, event.usage, abandoned=event.abandoned
                )
        return account

    def add(
        self, attribution: str, message_id: str, usage: Usage, *, abandoned: bool = False
    ) -> None:
        """Count one message's usage once; a response cut short (``abandoned``) is kept apart.

        Raises:
            AccountingError: the same message was already counted with other usage, or was
                counted once as cut short and once as counted in the totals.
        """
        key = (attribution, message_id)
        seen = self._messages.get(key)
        if seen is not None and seen != (usage, abandoned):
            msg = "one message reported with two different usages"
            raise AccountingError(msg, attribution=attribution, message_id=message_id)
        self._messages[key] = (usage, abandoned)

    def _summed(self, *, abandoned: bool) -> dict[str, Usage]:
        totals: dict[str, Usage] = {}
        for (attribution, _), (usage, cut) in sorted(self._messages.items()):
            if cut == abandoned:
                totals[attribution] = _plus(totals.get(attribution, _ZERO), usage)
        return totals

    def by_attribution(self) -> dict[str, Usage]:
        """Summed usage per attribution, e.g. ``session:<id>``, less every cut response."""
        return self._summed(abandoned=False)

    def abandoned(self) -> dict[str, Usage]:
        """Responses the binary cut short, per attribution: not in its totals; billing unknown.

        Each such response's usage is what it started with, and is in no sum here
        (:meth:`by_attribution`, :meth:`by_kind`, :meth:`total`), as in none of the binary's
        per-model totals. The result's top-level usage counts it, and the API may have billed
        it: whether it did, nothing the run holds says.
        """
        return self._summed(abandoned=True)

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
