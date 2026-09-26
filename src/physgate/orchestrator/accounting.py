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

from collections.abc import Iterable

from physgate.orchestrator.events import Event, TokensUsed
from physgate.orchestrator.exceptions import AccountingError, RoutingTokensError
from physgate.orchestrator.protocols import Usage

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
