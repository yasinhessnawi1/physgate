"""Every reader of a session's tokens counts a cut response as the run's account does.

The account counts a response the binary cut short exactly where the binary's per-model
totals count it (the orchestrator's rows): where the totals count every line, the cut
response's starting usage is counted and listed as cut short; where they leave it out (an API
error's end), it is listed apart, its billing unknown; with no totals to read, it is listed
apart. The cost line is a lower bound whenever a cut response is on the record, counted or not:
what it streamed before the break is in nobody's figure.

The raw arm (the baseline) and the inject runner summed every line. A cut response the totals
leave out was then counted against the raw arm's cap, which is the harness run's counted total,
and in the inject runner's reviewer tokens. Here both count as the account does, and say what
they left out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from instrument_corpus import write_corpus
from observe_rig import fake_run, target_repo

from physgate.evaluation.inject.corpus import load_corpus
from physgate.evaluation.inject.runner import RESULTS_NAME, REVIEWS_DIRNAME, run_instrument
from physgate.evaluation.observe.calls import CacheWrites, RecordedCall
from physgate.evaluation.observe.cost import CostLine, load_price_sheet, price_events
from physgate.evaluation.observe.manifest import read_manifest, read_run_events
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.raw import stream_total
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import TokensUsed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import Artefact, MessageUsage, ReviewResult, Usage

MODEL = "claude-sonnet-5"
COMPLETE_START = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 46710,
    "cache_read_input_tokens": 0,
    "output_tokens": 1,
}
COMPLETE_FINAL = {**COMPLETE_START, "output_tokens": 180}
CUT_START = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 55515,
    "cache_read_input_tokens": 0,
    "output_tokens": 1,
}
COMPLETE = Usage(**COMPLETE_FINAL)
CUT = Usage(**CUT_START)


def _event(event: dict[str, Any], **outer: Any) -> dict[str, Any]:  # noqa: ANN401 - the same
    return {"type": "stream_event", "event": event, "parent_tool_use_id": None, **outer}


def _totals(*parts: dict[str, int]) -> dict[str, Any]:
    return {
        MODEL: {
            "inputTokens": sum(p["input_tokens"] for p in parts),
            "outputTokens": sum(p["output_tokens"] for p in parts),
            "cacheReadInputTokens": sum(p["cache_read_input_tokens"] for p in parts),
            "cacheCreationInputTokens": sum(p["cache_creation_input_tokens"] for p in parts),
        }
    }


def _stream(model_usage: dict[str, Any] | None, *, terminal: str = "api_error") -> str:
    """One complete response, one the binary cut short and closed, and the result, if any."""
    events: list[dict[str, Any]] = [
        _event({"type": "message_start", "message": {"id": "msg_01", "usage": COMPLETE_START}}),
        {
            "type": "assistant",
            "message": {"id": "msg_01", "model": MODEL, "usage": COMPLETE_START},
        },
        _event({"type": "message_delta", "usage": COMPLETE_FINAL}),
        _event({"type": "message_stop"}),
        _event(
            {"type": "message_start", "message": {"id": "msg_02", "usage": CUT_START}},
            api_message_id="msg_02",
        ),
        _event(
            {"type": "message_stop"},
            api_message_id="msg_02",
            abandoned_blocks={"api_message_id": "msg_02", "from_block_index": 0},
        ),
    ]
    if model_usage is not None:
        events.append(
            {
                "type": "result",
                "subtype": "success",
                "is_error": terminal == "api_error",
                "terminal_reason": terminal,
                "modelUsage": model_usage,
            }
        )
    return "".join(json.dumps(e) + "\n" for e in events)


#: The real run's API-error end: the totals leave the cut response out.
LEFT_OUT = _totals(COMPLETE_FINAL)
#: Both pins' ends at the scripted endpoint: the totals count it.
COUNTED = _totals(COMPLETE_FINAL, CUT_START)

RULE = "a cut response is counted as the run's account counts it"


# --- the raw arm: its cap and its record -------------------------------------------------------


@pytest.mark.parametrize(
    ("model_usage", "expected"),
    [
        pytest.param(LEFT_OUT, COMPLETE.total(), id="totals leaving it out"),
        pytest.param(COUNTED, COMPLETE.total() + CUT.total(), id="totals counting it"),
        pytest.param(None, COMPLETE.total(), id="no result yet"),
    ],
)
def test_the_raw_arm_s_watch_counts_against_its_cap_what_the_account_counts(
    tmp_path: Path, model_usage: dict[str, Any] | None, expected: int
) -> None:
    stream = tmp_path / "stdout.jsonl"
    stream.write_text(_stream(model_usage))
    assert stream_total(stream) == expected, RULE


def _raw_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> dict[str, Any]:
    """The raw arm's record of a session whose stream is ``text``; nothing is spawned."""
    sdir = tmp_path / "session"
    sdir.mkdir()

    def session(*_a: object, **_k: object) -> tuple[object, ...]:
        (sdir / "stdout.jsonl").write_text(text)
        ended = SimpleNamespace(timed_out=False, exit_code=1, left_running=())
        return ended, SimpleNamespace(end=None, failure=None), 1.0, {}

    monkeypatch.setattr(raw, "_session", session)
    monkeypatch.setattr(raw, "_clean", lambda *a, **k: None)
    setup = SimpleNamespace(credential=SimpleNamespace(secret="not-a-key"), held_out_canaries=())
    return raw._run("brief", setup, tmp_path, tmp_path, sdir, "raw-1", None, 10**9)  # type: ignore[arg-type]


def test_the_raw_arm_records_the_tokens_the_account_counts_and_the_cut_ones_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _raw_record(tmp_path, monkeypatch, _stream(LEFT_OUT))
    assert record["tokens"] == COMPLETE.total(), RULE
    assert record.get("tokens_not_in_binary_totals") == CUT.total(), "the cut tokens are unsaid"


def test_the_raw_arm_records_a_cut_response_the_totals_count_among_its_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _raw_record(tmp_path, monkeypatch, _stream(COUNTED))
    assert record["tokens"] == COMPLETE.total() + CUT.total()
    assert record.get("tokens_not_in_binary_totals") == 0


# --- the inject runner: its reviewer tokens ---------------------------------------------------


@dataclass
class _CutReviewer:
    """Every first try is cut off at an API error; every retry is a pass with the same lines."""

    lines: tuple[MessageUsage, ...]
    model: str = "claude-opus-5-5"
    seen: list[Artefact] = field(default_factory=list)

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact)
        if len(self.seen) % 2:
            raise ReviewUnavailableError(
                "the session ended with api_error",
                cause="infrastructure",
                session_id=f"s{len(self.seen)}",
                reviewer_model=self.model,
                usage=self.lines,
            )
        return ReviewResult(
            verdict="pass",
            finding="every item is met",
            reviewer_model=self.model,
            session_id=f"s{len(self.seen)}",
            usage=self.lines,
        )


def _instrument(tmp_path: Path, lines: tuple[MessageUsage, ...]) -> list[dict[str, Any]]:
    run_instrument(
        load_corpus(write_corpus(tmp_path / "corpus")),
        {"electrical": _CutReviewer(lines)},
        run_dir=tmp_path / "run",
        scratch=tmp_path / "scratch",
        run_id="cut-1",
        seed=11,
        retry_delays_s=(0.0,),
        sleep=lambda _: None,
        progress=lambda line: None,
    )
    text = (tmp_path / "run" / RESULTS_NAME).read_text()
    return [json.loads(x) for x in text.splitlines()]


def test_each_review_s_row_counts_the_tokens_the_account_counts(tmp_path: Path) -> None:
    lines = (
        MessageUsage(message_id="msg_01", usage=COMPLETE),
        MessageUsage(message_id="msg_02", usage=CUT, abandoned=True),
    )
    rows = _instrument(tmp_path, lines)
    assert rows
    for row in rows:
        assert row["reviewer_tokens"] == 2 * COMPLETE.total(), RULE
        assert row.get("reviewer_tokens_not_in_binary_totals") == 2 * CUT.total()
        review = json.loads(
            (tmp_path / "run" / REVIEWS_DIRNAME / f"{row['review_id']}.json").read_text()
        )
        assert review["tokens"] == 2 * COMPLETE.total()
        assert review.get("tokens_not_in_binary_totals") == 2 * CUT.total()


def test_each_review_s_row_counts_a_cut_response_the_totals_count(tmp_path: Path) -> None:
    lines = (
        MessageUsage(message_id="msg_01", usage=COMPLETE),
        MessageUsage(message_id="msg_02", usage=CUT, abandoned=True, in_binary_totals=True),
    )
    rows = _instrument(tmp_path, lines)
    for row in rows:
        assert row["reviewer_tokens"] == 2 * (COMPLETE.total() + CUT.total())
        # A row with nothing left out keeps its bytes.
        assert "reviewer_tokens_not_in_binary_totals" not in row


# --- the cost line: a lower bound that lists the counted cut response ---------------------------


def test_the_cost_line_counts_and_lists_a_cut_response_the_totals_count(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_run_events(run)
    last = events[-1]
    before = TokenAccount.from_events(events).by_attribution()
    who = next(a for a in before if a.startswith("session:"))
    added = [
        TokensUsed(
            seq=last.seq + n,
            ts=last.ts,
            run_id=last.run_id,
            gate_mode=last.gate_mode,
            attribution=who,
            message_id=line.message_id,
            usage=line.usage,
            abandoned=line.abandoned,
            in_binary_totals=line.in_binary_totals,
        )
        for n, line in enumerate(
            (
                MessageUsage(message_id="msg_01", usage=COMPLETE),
                MessageUsage(message_id="msg_02", usage=CUT, abandoned=True, in_binary_totals=True),
            ),
            start=1,
        )
    ]
    manifest = read_manifest(run)
    line = price_events(
        manifest.config,
        manifest.manifest_id,
        [*events, *added],
        load_price_sheet("2026-10-16"),
    )
    assert line.lower_bound, f"{RULE}: the cost is not marked a lower bound"
    assert line.cut_short_in_binary_totals == {who: CUT}, RULE
    assert line.not_in_binary_totals_billing_unknown == {}
    # Priced as the totals count it: every line, the cut one included.
    priced = sum(r.tokens.total() for r in line.rows)
    assert priced == sum(u.total() for u in before.values()) + COMPLETE.total() + CUT.total()
    refused = {**line.model_dump(), "lower_bound": False}
    with pytest.raises(ValueError, match="lower bound"):
        CostLine.model_validate(refused)


def test_a_counted_cut_response_alone_makes_a_wholly_read_line_a_lower_bound(
    tmp_path: Path,
) -> None:
    # Every call's result read, its writes' cache known: the line is exact but for the cut.
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_run_events(run)
    who = next(a for a in TokenAccount.from_events(events).by_attribution() if a.startswith("s"))
    last = events[-1]
    resumed = [
        *events,
        TokensUsed(
            seq=last.seq + 1,
            ts=last.ts,
            run_id=last.run_id,
            gate_mode=last.gate_mode,
            attribution=who,
            message_id="msg_02",
            usage=CUT,
            abandoned=True,
            in_binary_totals=True,
        ),
    ]
    calls = {
        a: RecordedCall(
            session_id=a.split(":", 1)[1],
            cache_writes=CacheWrites(five_minute=u.cache_creation_input_tokens, one_hour=0),
            binary_usd=Decimal("0.01"),
        )
        for a, u in TokenAccount.from_events(resumed).by_attribution().items()
    }
    manifest = read_manifest(run)
    line = price_events(
        manifest.config,
        manifest.manifest_id,
        resumed,
        load_price_sheet("2026-10-16"),
        calls=calls,
    )
    assert line.reconciliation is not None and not line.reconciliation.unread
    assert not line.reconciliation.ttl_unread
    assert line.lower_bound, f"{RULE}: a counted cut response left the cost exact"
