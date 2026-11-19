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
ended early) has only the usage it started with, marked ``abandoned`` on its line.
Whether the binary's per-model totals count that usage is not said by the stream,
and both have been seen: a real run's review, whose network broke mid-response and
which ended in an API error, had totals of the first response alone (its top-level
``usage`` added the cut one); at the scripted endpoint, on both pinned binaries, the
totals counted the cut response, whether the binary then retried and completed or
ended in an API error. So the totals decide (:func:`settle`). Where they equal every
line, the cut responses included, each cut response is counted as they count it and
marked ``in_binary_totals``. Otherwise it is kept apart from every sum held to the
totals, its billing unknown, and that is read only at an API error's end, the one
end it was seen at; a cut response the totals leave out of a session that ended any
other way is an error. Either way it is recorded under the attribution that spent
it and listed, so each token the totals count is in exactly one bucket and the cut
one is visible beside them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

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


def _charged(per_model: Mapping[str, object]) -> Usage:
    """The result's per-model totals, summed over every model, by the account's fields."""
    return Usage(
        **{
            field: sum(int(m.get(key) or 0) for m in per_model.values() if isinstance(m, dict))
            for field, key in _MODEL_USAGE_FIELDS.items()
        }
    )


def settle(
    # The binary's result object: an untyped boundary, only its totals are read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> tuple[MessageUsage, ...]:
    """The lines, each cut response marked as counted or not by the binary's totals.

    The totals count a session's cut responses where they equal every line, the cut ones
    included, in each of the four token classes: each unmarked one is then marked
    ``in_binary_totals``. Where they are of another figure, none is newly so marked. A cut
    response that started with no usage meets both figures, and is read the one way, as
    counted.

    A mark is only ever set here, never cleared: a line an earlier invocation's totals settled
    keeps its mark whatever this result's totals are. A resumed invocation's totals are the
    whole session's, cumulative, so a response an earlier result counted is still in them; and
    a compaction's call makes them equal no plain sum of the lines. So the lines returned may
    mix a cut response counted earlier with one this result leaves out: the check reads that as
    it reads any cut response left out, at an API error's end only, and holds the totals to
    every counted line. Within one settling it is all or none: totals that count one of the
    unmarked cut responses and not another leave both unmarked, and the check then refuses
    them, the counted one's usage being in the totals and in no counted line.

    The comparison is of the totals summed over every model. The usage line
    (:class:`~physgate.orchestrator.protocols.MessageUsage`) has no model: a response's
    ``message_start`` in the stream names one, but the stream's reader does not take it onto
    the line, so the comparison is not held per model. Equality is still no proof: totals that
    left a cut response out but counted a response the stream does not show, whose four classes
    equal the cut one's, would be read as counting the cut response.

    A result with no totals settles nothing, and the lines are returned as given: a line read
    from a stream is then not counted. Nothing is raised here and no other line is changed.
    """
    usages = tuple(usages)
    per_model = (result or {}).get("modelUsage")
    if not any(m.abandoned for m in usages) or not isinstance(per_model, dict) or not per_model:
        return usages
    every = _ZERO
    for message in usages:
        every = _plus(every, message.usage)
    counted = every == _charged(per_model)
    if not counted:
        return usages
    return tuple(
        m.model_copy(update={"in_binary_totals": True})
        if m.abandoned and not m.in_binary_totals
        else m
        for m in usages
    )


def lines_in_totals(
    # The binary's result object: an untyped boundary, only its end is read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> tuple[MessageUsage, ...]:
    """The lines the binary's per-model totals count: every one but a cut response they omit.

    A cut response not marked ``in_binary_totals`` (:func:`settle`) is left out of the sum held
    to the totals; whether it was billed is unknown. That was seen only where the session ended
    in an API error; in a session that ended any other way nothing says the totals left it out,
    so the account is refused rather than read.

    Raises:
        AccountingError: a cut response the totals omit, in a session whose result is no API
            error's end.
    """
    usages = tuple(usages)
    cut = [m.message_id for m in usages if not m.counted]
    if cut and not ended_in_api_error(result):
        msg = "a response the binary cut short, in a session that did not end in an API error"
        end = str((result or {}).get("terminal_reason"))
        raise AccountingError(msg, message_id=cut[0], terminal_reason=end)
    return tuple(m for m in usages if m.counted)


def require_matching_totals(
    # The binary's result object: an untyped boundary, only its totals are read.
    result: Mapping[str, object] | None,
    usages: Iterable[MessageUsage],
) -> tuple[MessageUsage, ...]:
    """Hold one invocation's per-message account against the binary's own totals; its lines.

    The result's ``modelUsage`` sums every model the invocation used, and is held to
    every line they count (:func:`settle`, :func:`lines_in_totals`), field by field and
    exactly. A session with no result (killed, or stopped at its wall clock) has nothing
    to hold it against, and is not checked. The lines are returned as the totals settled
    them, each cut response marked as counted or not: what the caller records.

    Raises:
        AccountingError: a field's per-message sum differs from the result's total, or
            a response the totals omit was cut short in a session that did not end in an
            API error.
    """
    settled = settle(result, usages)
    per_model = (result or {}).get("modelUsage")
    if not isinstance(per_model, dict) or not per_model:
        return settled
    total = _ZERO
    for message in lines_in_totals(result, settled):
        total = _plus(total, message.usage)
    charged = _charged(per_model)
    for field in _MODEL_USAGE_FIELDS:
        counted, billed = int(getattr(total, field)), int(getattr(charged, field))
        if counted != billed:
            msg = "the per-message account differs from the binary's own totals"
            raise AccountingError(msg, field=field, account=str(counted), result=str(billed))
    return settled


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
    holds them. A result without totals has nothing to hold the messages against. Where there
    are boundaries, a cut response is counted as ``usages`` mark it (:func:`lines_in_totals`):
    the difference cannot tell its usage from a compaction's.

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
    """Tokens per attribution, deduplicated by message id; every cut response listed."""

    def __init__(self) -> None:
        """An empty account."""
        self._messages: dict[tuple[str, str], tuple[Usage, bool, bool]] = {}

    @classmethod
    def from_events(cls, events: Iterable[Event]) -> TokenAccount:
        """The account a run's event log records."""
        account = cls()
        for event in events:
            if isinstance(event, TokensUsed):
                account.add(
                    event.attribution,
                    event.message_id,
                    event.usage,
                    abandoned=event.abandoned,
                    in_binary_totals=event.in_binary_totals,
                )
        return account

    def add(
        self,
        attribution: str,
        message_id: str,
        usage: Usage,
        *,
        abandoned: bool = False,
        in_binary_totals: bool = False,
    ) -> None:
        """Count one message's usage once; a response cut short (``abandoned``) is listed.

        A cut response is counted in the sums only where the binary's totals count it
        (``in_binary_totals``), and kept apart from them otherwise.

        Raises:
            AccountingError: the same message was already counted with other usage, or
                was recorded once as one kind of line and once as another.
        """
        key = (attribution, message_id)
        line = (usage, abandoned, in_binary_totals)
        seen = self._messages.get(key)
        if seen is not None and seen != line:
            msg = "one message reported with two different usages"
            raise AccountingError(msg, attribution=attribution, message_id=message_id)
        self._messages[key] = line

    def _summed(self, keep: Callable[[bool, bool], bool]) -> dict[str, Usage]:
        """Usage per attribution of the lines ``keep`` takes, given: cut short, counted."""
        totals: dict[str, Usage] = {}
        for (attribution, _), (usage, cut, in_totals) in sorted(self._messages.items()):
            if keep(cut, in_totals):
                totals[attribution] = _plus(totals.get(attribution, _ZERO), usage)
        return totals

    def by_attribution(self) -> dict[str, Usage]:
        """Summed usage per attribution, e.g. ``session:<id>``: every line the totals count."""
        return self._summed(lambda cut, in_totals: not cut or in_totals)

    def abandoned(self) -> dict[str, Usage]:
        """Responses cut short that the binary's totals omit, per attribution; billing unknown.

        Each such response's usage is what it started with, and is in no sum here
        (:meth:`by_attribution`, :meth:`by_kind`, :meth:`total`), as in none of the binary's
        per-model totals. The result's top-level usage counts it, and the API may have billed
        it: whether it did, nothing the run holds says.
        """
        return self._summed(lambda cut, in_totals: cut and not in_totals)

    def cut_in_binary_totals(self) -> dict[str, Usage]:
        """Responses cut short that the binary's totals count, per attribution.

        Their starting usage is in every sum here, as in the binary's totals; they are listed so
        a reader sees that what each streamed before it was cut is in no figure.
        """
        return self._summed(lambda cut, in_totals: cut and in_totals)

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
