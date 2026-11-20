"""A response the binary cut short is recorded apart, and the cost beside it is a lower bound.

The orchestrator's rows show the stream and the account (a review whose network broke
mid-response: the cut response's starting usage on a line of its own, marked ``abandoned``, in
no sum held to the binary's totals). These hold the evaluation's two readers of those lines to
the same: the generalist review's log keeps the mark on the try it retries, and the cost line
prices every token the binary's per-model totals count once, names the cut usage apart as not in
those totals with its billing unknown, reads no cache-write split that counted the cut
response's writes as the counted writes' split, and is a lower bound whenever a cut response is
on the record: the API may have billed it, and nothing the run holds says whether it did.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo
from pydantic import ValidationError

from physgate.evaluation.observe.calls import CacheWrites, RecordedCall
from physgate.evaluation.observe.cost import CostLine, load_price_sheet, price_events
from physgate.evaluation.observe.generalist import review_retried_once
from physgate.evaluation.observe.manifest import read_manifest, read_run_events
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    Event,
    EventLog,
    RunStarted,
    SubtaskPlanned,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage

COMPLETE = Usage(
    input_tokens=2, output_tokens=180, cache_read_input_tokens=0, cache_creation_input_tokens=46710
)
CUT = Usage(
    input_tokens=2, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=55515
)


#: Where the cost line names the cut responses' usage: not in the binary's totals, billing unknown.
APART = "not_in_binary_totals_billing_unknown"


def _apart(line: CostLine) -> object:
    assert APART in CostLine.model_fields, "the cost line names no cut response's usage apart"
    return getattr(line, APART)


def _outcome(how: Callable[[], object]) -> object:
    """What ``how`` returned, or the exception it raised: the row asserts on either."""
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - the escape is what the row asserts on
        return exc


def _lines() -> tuple[MessageUsage, ...]:
    assert "abandoned" in MessageUsage.model_fields, "a usage line cannot be marked abandoned"
    assert "abandoned" in TokensUsed.model_fields, "a token line cannot be marked abandoned"
    return (
        MessageUsage(message_id="msg_01", usage=COMPLETE),
        MessageUsage(message_id="msg_02", usage=CUT, abandoned=True),
    )


def test_the_generalist_review_s_retry_records_the_cut_line_marked(tmp_path: Path) -> None:
    lines = _lines()
    tries: list[int] = []
    answer = ReviewResult(
        verdict="pass",
        finding="sound",
        reviewer_model="claude-opus-5-5",
        session_id="rev-2",
        usage=(),
    )

    def review() -> ReviewResult:
        tries.append(1)
        if len(tries) == 1:
            raise ReviewUnavailableError(
                "the session ended with api_error",
                cause="infrastructure",
                session_id="rev-1",
                reviewer_model="claude-opus-5-5",
                usage=lines,
            )
        return answer

    log = EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on")
    log.emit(RunStarted, config_sha256="c" * 64)
    log.emit(
        SubtaskPlanned, subtask_id="s1", spec_path="-", assigned_role="electrical", module_dir="-"
    )
    review_retried_once(review, log, subtask_id="s1", attempt=1, delays=(), sleep=lambda _: None)
    log.close()
    events = read_events(tmp_path / "events.jsonl")
    marked = [e.message_id for e in events if isinstance(e, TokensUsed) and e.abandoned]
    assert marked == ["msg_02"] and len(tries) == 2
    account = TokenAccount.from_events(events)
    assert account.by_attribution()["reviewer:rev-1"] == COMPLETE
    assert account.abandoned() == {"reviewer:rev-1": CUT}


def test_the_cost_line_prices_the_counted_tokens_and_names_the_cut_response_apart(
    tmp_path: Path,
) -> None:
    lines = _lines()
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_run_events(run)
    before = TokenAccount.from_events(events).by_attribution()
    who = next(a for a in before if a.startswith("session:"))
    last = events[-1]
    added = [
        TokensUsed(
            seq=last.seq + n,
            ts=last.ts,
            run_id=last.run_id,
            gate_mode=last.gate_mode,
            attribution=who,
            message_id=f"cut-{line.message_id}",
            usage=line.usage,
            abandoned=line.abandoned,
        )
        for n, line in enumerate(lines, start=1)
    ]
    resumed = [*events, *added]
    counted = TokenAccount.from_events(resumed).by_attribution()[who]
    assert counted.cache_creation_input_tokens == (
        before[who].cache_creation_input_tokens + COMPLETE.cache_creation_input_tokens
    )
    # The call's result splits by time to live every cache write it counted: the cut
    # response's among them, which the binary's per-model totals do not count.
    writes = CacheWrites(
        five_minute=0,
        one_hour=counted.cache_creation_input_tokens + CUT.cache_creation_input_tokens,
    )
    session = who.split(":", 1)[1]
    calls = {who: RecordedCall(session_id=session, cache_writes=writes, binary_usd=None)}
    manifest = read_manifest(run)
    line = _outcome(
        lambda: price_events(
            manifest.config,
            manifest.manifest_id,
            resumed,
            load_price_sheet("2026-10-16"),
            calls=calls,
        )
    )
    assert isinstance(line, CostLine), f"the run was not priced: {line!r}"
    (call,) = [c for c in line.calls if c.attribution == who]
    assert call.tokens == counted
    # Its writes were not read as a split of the counted ones: a lower bound, named.
    assert call.cache_writes is None and line.lower_bound
    assert line.reconciliation is not None and who in line.reconciliation.ttl_unread
    assert _apart(line) == {who: CUT}
    raw = json.loads(line.model_dump_json())
    assert raw[APART][who]["cache_creation_input_tokens"] == CUT.cache_creation_input_tokens


def test_a_cost_line_with_no_cut_response_keeps_its_bytes(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    manifest = read_manifest(run)
    line = price_events(
        manifest.config, manifest.manifest_id, read_run_events(run), load_price_sheet("2026-10-16")
    )
    assert not line.lower_bound or line.reconciliation is None
    assert APART not in json.loads(line.model_dump_json())
    assert "abandoned" not in json.loads(line.model_dump_json())


# --- the lower bound: set by any cut response, whatever else the line read ----------------------


def _read_whole(
    tmp_path: Path,
) -> tuple[Path, list[Event], dict[str, Usage], dict[str, RecordedCall]]:
    """A run whose every call's result was read: each figure and each write's cache known."""
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_run_events(run)
    counted = TokenAccount.from_events(events).by_attribution()
    calls = {
        who: RecordedCall(
            session_id=who.split(":", 1)[1],
            cache_writes=CacheWrites(five_minute=usage.cache_creation_input_tokens, one_hour=0),
            binary_usd=Decimal("0.01"),
        )
        for who, usage in counted.items()
    }
    return run, events, counted, calls


def _with_lines(events: list[Event], who: str, lines: tuple[MessageUsage, ...]) -> list[Event]:
    last = events[-1]
    return [
        *events,
        *(
            TokensUsed(
                seq=last.seq + n,
                ts=last.ts,
                run_id=last.run_id,
                gate_mode=last.gate_mode,
                attribution=who,
                message_id=f"cut-{line.message_id}",
                usage=line.usage,
                abandoned=line.abandoned,
            )
            for n, line in enumerate(lines, start=1)
        ),
    ]


def _priced(run: Path, events: list[Event], calls: dict[str, RecordedCall]) -> object:
    manifest = read_manifest(run)
    return _outcome(
        lambda: price_events(
            manifest.config,
            manifest.manifest_id,
            events,
            load_price_sheet("2026-10-16"),
            calls=calls,
        )
    )


def test_a_line_whose_every_call_was_read_is_no_lower_bound(tmp_path: Path) -> None:
    # The rows below mean something only if this line, with no cut response, is exact.
    run, events, _, calls = _read_whole(tmp_path)
    line = _priced(run, events, calls)
    assert isinstance(line, CostLine), f"the run was not priced: {line!r}"
    assert line.reconciliation is not None and not line.reconciliation.unread
    assert not line.reconciliation.ttl_unread and not line.lower_bound


def test_a_call_whose_every_response_was_cut_makes_the_line_a_lower_bound(tmp_path: Path) -> None:
    # Every response of this call was cut: no call row prices it, and no other mark is raised.
    run, events, _, calls = _read_whole(tmp_path)
    cut_only = "reviewer:rev-cut-only"
    resumed = _with_lines(
        events, cut_only, (MessageUsage(message_id="m1", usage=CUT, abandoned=True),)
    )
    line = _priced(run, resumed, calls)
    assert isinstance(line, CostLine), f"the run was not priced: {line!r}"
    assert cut_only not in [c.attribution for c in line.calls]
    assert line.reconciliation is not None and not line.reconciliation.unread
    assert line.lower_bound, "a cut response the API may have billed left the cost exact"
    assert _apart(line) == {cut_only: CUT}


def test_a_cut_response_beside_a_call_with_no_cache_writes_makes_the_line_a_lower_bound(
    tmp_path: Path,
) -> None:
    run, events, counted, calls = _read_whole(tmp_path)
    who = next(a for a, u in counted.items() if u.cache_creation_input_tokens == 0)
    resumed = _with_lines(events, who, (MessageUsage(message_id="m1", usage=CUT, abandoned=True),))
    line = _priced(run, resumed, calls)
    assert isinstance(line, CostLine), f"the run was not priced: {line!r}"
    (call,) = [c for c in line.calls if c.attribution == who]
    assert call.tokens == counted[who] and call.tokens.cache_creation_input_tokens == 0
    assert line.reconciliation is not None and who not in line.reconciliation.ttl_unread
    assert line.lower_bound, "a cut response the API may have billed left the cost exact"
    assert _apart(line) == {who: CUT}


@pytest.mark.parametrize("read", [True, False], ids=["with its calls read", "with none read"])
def test_a_line_naming_a_cut_response_and_not_a_lower_bound_is_refused(
    tmp_path: Path, read: bool
) -> None:
    run, events, _, calls = _read_whole(tmp_path)
    resumed = _with_lines(events, "reviewer:rev-cut-only", _lines()[1:])
    line = _priced(run, resumed, calls)
    assert isinstance(line, CostLine), f"the run was not priced: {line!r}"
    fields = line.model_dump()
    if not read:
        fields |= {"calls": (), "reconciliation": None}
    marked = _outcome(lambda: CostLine.model_validate({**fields, "lower_bound": True}))
    assert isinstance(marked, CostLine), f"a line marked a lower bound was refused: {marked!r}"
    unmarked = _outcome(lambda: CostLine.model_validate({**fields, "lower_bound": False}))
    assert isinstance(unmarked, ValidationError), "a cut response left the cost exact"
    assert "cut response" in str(unmarked)
