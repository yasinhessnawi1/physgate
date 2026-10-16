"""A cost line prices each call's cache writes at the rate that call paid, and checks the binary.

The first sheet priced every cache write at the five-minute rate, on the premise
that the binary marks its cache breakpoints with no time to live. On the
subscription it writes one-hour entries, at twice the input price, so every
subscription line was low by its cache-write tokens times the difference. A
sheet from 16.10.2026 on prices both rates, and each call's writes are split by
the time to live its own result event records (``usage.cache_creation``). Every
call whose result reports the binary's own ``total_cost_usd`` is held to it, and
a call whose figures disagree is named on the line, never averaged away.

The recorded calls below are copied, figure for figure, from the result events of
real subscription runs on 02.10.2026 and 08.10.2026: three calls of a run on the
role model, and four calls of a run with its reviews on the reviewer model. Every
one reproduces the binary's figure exactly at the new sheet, and is low at the
old one by its one-hour writes times the difference of the two rates.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.observe.calls import CacheWrites, RecordedCall, read_call, run_calls
from physgate.evaluation.observe.cost import (
    KNOWN_SHEETS,
    PRICES,
    DatedSheet,
    load_price_sheet,
    price_events,
    price_run,
)
from physgate.evaluation.observe.exceptions import ManifestError, PriceSheetError
from physgate.evaluation.observe.manifest import read_manifest, read_run_events
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import ReviewRan, read_events
from physgate.orchestrator.protocols import Usage

OLD, NEW = "2026-09-27", "2026-10-16"
MTOK = Decimal(1_000_000)

#: (model, input, output, cache read, one-hour cache writes, the binary's total_cost_usd)
RECORDED: tuple[tuple[str, int, int, int, int, float], ...] = (
    ("claude-opus-5-5", 2, 1292, 0, 6159, 0.07512),
    ("claude-opus-5-5", 6, 987, 34970, 18698, 0.176342),
    ("claude-opus-5-5", 6, 938, 46031, 7654, 0.0892222),
    ("claude-opus-5-5", 2, 1378, 0, 6162, 0.076864),
    ("claude-opus-5-5", 6, 1023, 54367, 16129, 0.16038940000000002),
    ("claude-sonnet-5", 8, 20086, 195258, 79571, 0.5582116),
    ("claude-sonnet-5", 10, 46146, 263990, 113933, 0.9700099999999999),
)


def result_event(
    session_id: str,
    usage: Usage,
    *,
    five_minute: int = 0,
    one_hour: int | None = None,
    total_cost_usd: float | None = None,
) -> dict[str, Any]:
    """A result event as the binary writes one: its usage, its writes by TTL, its cost."""
    body: dict[str, Any] = usage.model_dump()
    if one_hour is not None:
        body["cache_creation"] = {
            "ephemeral_5m_input_tokens": five_minute,
            "ephemeral_1h_input_tokens": one_hour,
        }
    event: dict[str, Any] = {"type": "result", "session_id": session_id, "usage": body}
    if total_cost_usd is not None:
        event["total_cost_usd"] = total_cost_usd
    return event


def write_stream(path: Path, *events: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "system", "subtype": "init"}, *events]
    path.write_text("".join(json.dumps(e) + "\n" for e in lines))
    return path


@pytest.fixture
def new() -> DatedSheet:
    return load_price_sheet(NEW)


@pytest.fixture
def old() -> DatedSheet:
    return load_price_sheet(OLD)


def test_the_new_sheet_prices_both_write_rates_and_the_old_sheet_is_kept_as_read(
    new: DatedSheet, old: DatedSheet
) -> None:
    assert new.sha256 == KNOWN_SHEETS[NEW] and old.sha256 == KNOWN_SHEETS[OLD]
    assert (new.sheet.cache_write_ttl, old.sheet.cache_write_ttl) == ("per_call", "5m")
    assert new.sheet.source == old.sheet.source and new.sheet.page_sha256 != old.sheet.page_sha256
    for model, price in old.sheet.usd_per_mtok.items():
        now = new.sheet.usd_per_mtok[model]
        assert (now.input, now.cache_write, now.cache_read, now.output) == (
            price.input,
            price.cache_write,
            price.cache_read,
            price.output,
        )
        # The page's one-hour write rate is twice the input rate, for every model priced.
        assert now.cache_write_1h == 2 * now.input
        assert price.cache_write_1h is None


def _body(date: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((PRICES / f"{date}.json").read_text())
    return body


def _sheet(tmp_path: Path, body: dict[str, Any]) -> DatedSheet:
    raw = json.dumps(body).encode()
    (tmp_path / f"{body['date']}.json").write_bytes(raw)
    known = {body["date"]: hashlib.sha256(raw).hexdigest()}
    return load_price_sheet(body["date"], directory=tmp_path, known=known)


def test_a_sheet_that_prices_per_call_names_a_one_hour_rate_for_every_model(
    tmp_path: Path,
) -> None:
    body = _body(NEW)
    del body["usd_per_mtok"]["claude-sonnet-5"]["cache_write_1h"]
    with pytest.raises(PriceSheetError, match="incomplete"):
        _sheet(tmp_path, body)


def test_a_five_minute_sheet_names_no_one_hour_rate(tmp_path: Path) -> None:
    body = _body(OLD)
    body["usd_per_mtok"]["claude-sonnet-5"]["cache_write_1h"] = "4"
    with pytest.raises(PriceSheetError, match="incomplete"):
        _sheet(tmp_path, body)


@pytest.mark.parametrize("call", RECORDED, ids=[f"call-{n}" for n in range(len(RECORDED))])
def test_every_recorded_call_reproduces_the_binary_s_figure_at_the_new_sheet(
    tmp_path: Path, new: DatedSheet, old: DatedSheet, call: tuple[str, int, int, int, int, float]
) -> None:
    model, inputs, output, read, one_hour, binary = call
    usage = Usage(
        input_tokens=inputs,
        output_tokens=output,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=one_hour,
    )
    stream = write_stream(
        tmp_path / "stdout.jsonl",
        result_event("s1", usage, one_hour=one_hour, total_cost_usd=binary),
    )
    recorded = read_call(stream, "s1")
    assert recorded == RecordedCall(
        session_id="s1",
        cache_writes=CacheWrites(five_minute=0, one_hour=one_hour),
        binary_usd=Decimal(repr(binary)),
    )
    priced = new.sheet.usd_per_mtok[model].usd(usage, recorded.cache_writes)
    assert abs(priced - Decimal(repr(binary))) < Decimal("1e-12")
    at_old = old.sheet.usd_per_mtok[model].usd(usage)
    rates = new.sheet.usd_per_mtok[model]
    assert rates.cache_write_1h is not None
    assert priced - at_old == one_hour * (rates.cache_write_1h - rates.cache_write) / MTOK


@pytest.mark.parametrize(
    ("five_minute", "one_hour", "figure"),
    [
        # A mixed split: 2000 tokens at the five-minute rate ($5), 1000 at the one-hour ($8).
        (2000, 1000, "0.02024"),
        # Every write to the five-minute cache, as a call on an API key may write them.
        (3000, 0, "0.01724"),
    ],
)
def test_five_minute_writes_are_priced_at_the_five_minute_rate(
    tmp_path: Path, new: DatedSheet, five_minute: int, one_hour: int, figure: str
) -> None:
    """Each half of a split at its own rate, held to a figure worked by hand from the sheet.

    claude-opus-5-5 at 2026-10-16, per million: input 4, output 20, cache read 0.20,
    five-minute write 5, one-hour write 8. With 10 input, 100 output and 1000 read:
    40 + 2000 + 200 = 2240, plus the writes, over a million.
    """
    usage = Usage(
        input_tokens=10,
        output_tokens=100,
        cache_read_input_tokens=1000,
        cache_creation_input_tokens=five_minute + one_hour,
    )
    stream = write_stream(
        tmp_path / "stdout.jsonl",
        result_event(
            "s1", usage, five_minute=five_minute, one_hour=one_hour, total_cost_usd=float(figure)
        ),
    )
    recorded = read_call(stream, "s1")
    assert recorded is not None
    assert recorded.cache_writes == CacheWrites(five_minute=five_minute, one_hour=one_hour)
    priced = new.sheet.usd_per_mtok["claude-opus-5-5"].usd(usage, recorded.cache_writes)
    assert priced == Decimal(figure) == recorded.binary_usd


def test_a_split_that_is_not_the_call_s_writes_is_refused(new: DatedSheet) -> None:
    usage = Usage(
        input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=10
    )
    with pytest.raises(PriceSheetError, match="add up"):
        new.sheet.usd_per_mtok["claude-opus-5-5"].usd(usage, CacheWrites(five_minute=0, one_hour=9))


def test_a_stream_is_read_up_to_its_runtime_s_result_and_no_further(tmp_path: Path) -> None:
    zero = Usage(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=4
    )
    stream = write_stream(
        tmp_path / "stdout.jsonl",
        result_event("s1", zero, one_hour=4, total_cost_usd=0.5),
        # A line after the runtime's result is not the runtime's: never read.
        result_event("s1", zero, five_minute=4, one_hour=0, total_cost_usd=0.1),
    )
    found = read_call(stream, "s1")
    assert found is not None and found.binary_usd == Decimal("0.5")
    assert found.cache_writes == CacheWrites(five_minute=0, one_hour=4)
    assert read_call(write_stream(tmp_path / "none.jsonl"), "s1") is None
    bare = write_stream(tmp_path / "bare.jsonl", result_event("s1", zero))
    assert read_call(bare, "s1") == RecordedCall(
        session_id="s1", cache_writes=None, binary_usd=None
    )
    with pytest.raises(ManifestError, match="another session"):
        read_call(stream, "s2")


def _streams(run: Path, review_root: Path, *, off_by: Decimal = Decimal(0)) -> Path:
    """Give every call of a fake run the result event a subscription call would have written.

    Each role session's writes are one-hour entries; each review's, which wrote none,
    report its cost. The first session's figure is off by ``off_by``.
    """
    events = read_events(run / "events.jsonl")
    sheet = load_price_sheet(NEW).sheet
    first = True
    for attribution, usage in TokenAccount.from_events(events).by_attribution().items():
        kind, who = attribution.split(":", 1)
        model = "claude-sonnet-5" if kind == "session" else "claude-opus-5-5"
        writes = CacheWrites(five_minute=0, one_hour=usage.cache_creation_input_tokens)
        cost = sheet.usd_per_mtok[model].usd(usage, writes)
        if kind == "session" and first:
            cost, first = cost + off_by, False
        place = (
            run / "sessions" / who / "stdout.jsonl"
            if kind == "session"
            else review_root / who / "session" / "stdout.jsonl"
        )
        write_stream(
            place,
            result_event(who, usage, one_hour=writes.one_hour, total_cost_usd=float(cost)),
        )
    return review_root


def test_a_run_s_line_holds_each_call_to_the_binary_and_agrees_when_priced_right(
    tmp_path: Path, new: DatedSheet, old: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides={"auth": "subscription"})
    review_root = _streams(run, tmp_path / "reviews")
    line = price_run(run, new, review_roots=(review_root,))
    assert line.calls and line.reconciliation is not None
    sessions = [c for c in line.calls if c.attribution.startswith("session:")]
    assert sessions and all(c.cache_writes is not None for c in sessions)
    assert all(c.agrees for c in line.calls)
    assert line.reconciliation.differs == () and line.reconciliation.unread == ()
    assert line.reconciliation.binary_usd == line.usd == sum(c.usd for c in line.calls)

    # The same records at the old sheet: every role session's line is low, and each is named.
    low = price_run(run, old, review_roots=(review_root,))
    assert low.reconciliation is not None
    assert set(low.reconciliation.differs) == {c.attribution for c in sessions}
    one_hour = sum(c.tokens.cache_creation_input_tokens for c in sessions)
    rates = new.sheet.usd_per_mtok["claude-sonnet-5"]
    assert rates.cache_write_1h is not None
    assert line.usd - low.usd == one_hour * (rates.cache_write_1h - rates.cache_write) / MTOK


def test_a_call_whose_figures_disagree_is_named_never_averaged(
    tmp_path: Path, new: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides={"auth": "subscription"})
    review_root = _streams(run, tmp_path / "reviews", off_by=Decimal("0.01"))
    line = price_run(run, new, review_roots=(review_root,))
    assert line.reconciliation is not None
    (differs,) = line.reconciliation.differs
    (call,) = [c for c in line.calls if c.attribution == differs]
    assert call.agrees is False and call.binary_usd is not None
    assert call.binary_usd - call.usd == Decimal("0.01")
    assert line.reconciliation.binary_usd - line.usd == Decimal("0.01")


def test_a_call_with_no_result_read_is_named_and_its_writes_are_a_lower_bound(
    tmp_path: Path, new: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides={"auth": "subscription"})
    _streams(run, tmp_path / "reviews")
    # No review root named: the reviews' results are not read.
    line = price_run(run, new)
    assert line.reconciliation is not None
    reviews = sorted(c.attribution for c in line.calls if c.attribution.startswith("reviewer:"))
    assert reviews and list(line.reconciliation.unread) == reviews
    # A session whose stream is gone: its writes are priced at the five-minute rate and named.
    events = read_run_events(run)
    (session, *_) = sorted(c.attribution for c in line.calls if c.attribution.startswith("session"))
    (run / "sessions" / session.split(":", 1)[1] / "stdout.jsonl").unlink()
    calls = run_calls(run, TokenAccount.from_events(events).by_attribution())
    missing = price_events(read_manifest(run).config, line.manifest_id, events, new, calls=calls)
    assert missing.reconciliation is not None
    assert session in missing.reconciliation.ttl_unread
    (priced,) = [c for c in missing.calls if c.attribution == session]
    assert priced.cache_writes is None
    rates = new.sheet.usd_per_mtok["claude-sonnet-5"]
    assert priced.usd == rates.usd(priced.tokens)


def test_a_line_priced_without_the_records_carries_no_reconciliation(
    tmp_path: Path, old: DatedSheet
) -> None:
    """The form every earlier line has, and what a reader without the streams writes."""
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_run_events(run)
    line = price_events(read_manifest(run).config, read_manifest(run).manifest_id, events, old)
    assert (line.calls, line.reconciliation) == ((), None)
    assert line.usd == price_run(run, old).usd


def test_a_review_s_result_is_found_under_each_review_root_named(tmp_path: Path) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    events = read_events(run / "events.jsonl")
    review = next(e.result.session_id for e in events if isinstance(e, ReviewRan))
    zero = Usage(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    write_stream(
        tmp_path / "second" / review / "session" / "stdout.jsonl",
        result_event(review, zero, one_hour=0, total_cost_usd=0),
    )
    roots = (tmp_path / "first", tmp_path / "second")
    found = run_calls(run, [f"reviewer:{review}"], roots)
    assert found[f"reviewer:{review}"].binary_usd == Decimal(0)
    assert run_calls(run, [f"reviewer:{review}"], roots[:1]) == {}


@pytest.mark.parametrize(("off_by", "code"), [(Decimal(0), 0), (Decimal("0.01"), 1)])
def test_the_command_reads_the_reviews_under_their_root_and_exits_one_on_a_disagreement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], off_by: Decimal, code: int
) -> None:
    from physgate.cli import main

    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides={"auth": "subscription"})
    review_root = _streams(run, tmp_path / "reviews", off_by=off_by)
    trend = tmp_path / "trend.jsonl"
    capsys.readouterr()
    args = ["cost", "--run-dir", str(run), "--prices", NEW, "--review-root", str(review_root)]
    assert main([*args, "--append", str(trend)]) == code
    printed = json.loads(capsys.readouterr().out)
    assert printed["reconciliation"]["unread"] == []
    assert len(printed["reconciliation"]["differs"]) == (1 if code else 0)
    # Appended either way: the disagreement is recorded on the run's line.
    (line,) = [json.loads(x) for x in trend.read_text().splitlines()]
    assert line["reconciliation"] == printed["reconciliation"]
