"""A response the binary cut short is recorded apart on the evaluation's records, and never priced.

The orchestrator's rows show the stream and the account (a review whose network broke
mid-response: the cut response's starting usage on a line of its own, marked ``abandoned``, in
no charged sum). These hold the evaluation's two readers of those lines to the same: the
generalist review's log keeps the mark on the try it retries, and the cost line prices every
charged token once, names the cut usage apart, and reads no cache-write split that counted the
cut response's writes as the charged writes' split.
"""

from __future__ import annotations

import json
from pathlib import Path

from observe_rig import fake_run, target_repo

from physgate.evaluation.observe.calls import CacheWrites, RecordedCall
from physgate.evaluation.observe.cost import load_price_sheet, price_events
from physgate.evaluation.observe.generalist import review_retried_once
from physgate.evaluation.observe.manifest import read_manifest, read_run_events
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
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


def test_the_cost_line_prices_the_charged_tokens_and_names_the_cut_response_apart(
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
    charged = TokenAccount.from_events(resumed).by_attribution()[who]
    assert charged.cache_creation_input_tokens == (
        before[who].cache_creation_input_tokens + COMPLETE.cache_creation_input_tokens
    )
    # The call's result splits by time to live every cache write it counted: the cut
    # response's among them, which the account does not charge.
    writes = CacheWrites(
        five_minute=0,
        one_hour=charged.cache_creation_input_tokens + CUT.cache_creation_input_tokens,
    )
    session = who.split(":", 1)[1]
    calls = {who: RecordedCall(session_id=session, cache_writes=writes, binary_usd=None)}
    manifest = read_manifest(run)
    line = price_events(
        manifest.config, manifest.manifest_id, resumed, load_price_sheet("2026-10-16"), calls=calls
    )
    (call,) = [c for c in line.calls if c.attribution == who]
    assert call.tokens == charged
    # Its writes were not read as a split of the charged ones: a lower bound, named.
    assert call.cache_writes is None and line.lower_bound
    assert line.reconciliation is not None and who in line.reconciliation.ttl_unread
    assert line.abandoned == {who: CUT}
    raw = json.loads(line.model_dump_json())
    assert raw["abandoned"][who]["cache_creation_input_tokens"] == CUT.cache_creation_input_tokens


def test_a_cost_line_with_no_cut_response_keeps_its_bytes(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    manifest = read_manifest(run)
    line = price_events(
        manifest.config, manifest.manifest_id, read_run_events(run), load_price_sheet("2026-10-16")
    )
    assert "abandoned" not in json.loads(line.model_dump_json())
