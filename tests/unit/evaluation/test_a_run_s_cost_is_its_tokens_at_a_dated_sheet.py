"""A run's cost is its tokens at a dated sheet's prices, and the trend refuses an edited price.

ARCH-150: the cost of every run, recorded and trended. The figures here are exact,
because the stand-in session and reviewer spend known tokens and the prices are
decimals: two sessions on the role model (10 and 20 input, 3 output and 5 cache
writes each) and two reviews on the reviewer model (40 input, 9 output each).
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from observe_rig import config, fake_run, target_repo

from physgate.evaluation.observe.cost import (
    KNOWN_SHEETS,
    PRICES,
    CostLine,
    DatedSheet,
    append_cost_line,
    load_price_sheet,
    price_run,
    read_trend,
)
from physgate.evaluation.observe.exceptions import ManifestError, PriceSheetError, TrendError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.orchestrator.events import LeftoverRead, ReviewUnavailable, TokensUsed
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.run_config import ModelStrings

DATE = "2026-09-27"


@pytest.fixture
def sheet() -> DatedSheet:
    return load_price_sheet(DATE)


def write_sheet(directory: Path, body: dict[str, Any], date: str = DATE) -> dict[str, str]:
    """A sheet file in ``directory``, and the registry that records it as written."""
    raw = json.dumps(body).encode()
    (directory / f"{date}.json").write_bytes(raw)
    return {date: hashlib.sha256(raw).hexdigest()}


def recorded_sheet() -> dict[str, Any]:
    body: dict[str, Any] = json.loads((PRICES / f"{DATE}.json").read_text())
    return body


def test_the_recorded_sheet_loads_and_names_its_sources(sheet: DatedSheet) -> None:
    assert sheet.sha256 == KNOWN_SHEETS[DATE]
    assert sheet.sheet.source.startswith("https://") and sheet.sheet.exchange.source
    assert sheet.sheet.usd_per_mtok["claude-sonnet-5"].output == Decimal(10)


def test_cost_is_each_model_s_tokens_times_its_price_per_class(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    line = price_run(run, sheet)
    rows = {r.model: r for r in line.rows}
    assert rows["claude-sonnet-5"].tokens == Usage(
        input_tokens=30, output_tokens=6, cache_read_input_tokens=0, cache_creation_input_tokens=10
    )
    assert rows["claude-opus-5-5"].tokens == Usage(
        input_tokens=80, output_tokens=18, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    # 30 x 2 + 10 x 2.50 + 6 x 10, and 80 x 4 + 18 x 20, per million.
    assert rows["claude-sonnet-5"].usd == Decimal("0.000145")
    assert rows["claude-opus-5-5"].usd == Decimal("0.00068")
    assert line.usd == Decimal("0.000825")
    assert line.nok == Decimal("0.000825") * Decimal("9.5063")
    assert (line.prices_date, line.prices_sha256) == (DATE, KNOWN_SHEETS[DATE])
    # What reviewing spent, by subtask: every subtask's reviews, summed, and nothing else.
    assert line.review_tokens and "(left over)" not in line.review_tokens
    reviewed = Usage(
        input_tokens=sum(u.input_tokens for u in line.review_tokens.values()),
        output_tokens=sum(u.output_tokens for u in line.review_tokens.values()),
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    assert reviewed == rows["claude-opus-5-5"].tokens
    assert line.manifest_id == read_manifest(run).manifest_id
    assert (line.basis, line.auth, line.partial) == ("list_price", "api_key", False)


def test_a_subscription_run_is_labelled_a_list_price_estimate(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path), overrides={"auth": "subscription"})
    line = price_run(run, sheet)
    assert (line.auth, line.basis) == ("subscription", "list_price_estimate")
    wrong = line.model_dump() | {"basis": "list_price"}
    with pytest.raises(ValueError, match="list_price_estimate"):
        CostLine.model_validate_json(json.dumps(wrong, default=str))


def test_a_model_the_sheet_does_not_price_is_refused_never_priced_at_zero(
    tmp_path: Path,
) -> None:
    body = recorded_sheet()
    del body["usd_per_mtok"]["claude-opus-5-5"]
    known = write_sheet(tmp_path, body)
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    with pytest.raises(PriceSheetError, match="no price") as refused:
        price_run(run, load_price_sheet(DATE, directory=tmp_path, known=known))
    assert refused.value.context["model"] == "claude-opus-5-5"


@pytest.mark.parametrize("field", ["source", "date", "retrieved", "page_sha256"])
def test_a_sheet_without_its_source_or_date_does_not_load(tmp_path: Path, field: str) -> None:
    body = recorded_sheet()
    del body[field]
    known = write_sheet(tmp_path, body)
    with pytest.raises(PriceSheetError, match="incomplete"):
        load_price_sheet(DATE, directory=tmp_path, known=known)


def test_a_rate_without_its_source_or_date_does_not_load(tmp_path: Path) -> None:
    body = recorded_sheet()
    del body["exchange"]["date"]
    known = write_sheet(tmp_path, body)
    with pytest.raises(PriceSheetError, match="incomplete"):
        load_price_sheet(DATE, directory=tmp_path, known=known)


def test_an_edited_sheet_does_not_load_under_its_recorded_date(tmp_path: Path) -> None:
    body = recorded_sheet()
    body["usd_per_mtok"]["claude-sonnet-5"]["output"] = "15"
    write_sheet(tmp_path, body)
    with pytest.raises(PriceSheetError, match="new price is a new sheet"):
        load_price_sheet(DATE, directory=tmp_path)


def test_a_date_with_no_recorded_sheet_or_another_date_inside_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PriceSheetError, match="no price sheet is recorded"):
        load_price_sheet("2026-01-01")
    known = write_sheet(tmp_path, recorded_sheet(), date="2026-10-01")
    with pytest.raises(PriceSheetError, match="another date"):
        load_price_sheet("2026-10-01", directory=tmp_path, known=known)


def test_the_trend_reads_back_every_line_it_was_given(tmp_path: Path, sheet: DatedSheet) -> None:
    repo = target_repo(tmp_path)
    lines = [price_run(fake_run(tmp_path, f"run-{n}", repo), sheet) for n in "ab"]
    trend = tmp_path / "trend.jsonl"
    assert read_trend(trend) == ()
    for line in lines:
        append_cost_line(trend, line)
    assert read_trend(trend) == tuple(lines)
    with pytest.raises(TrendError, match="already holds this run"):
        append_cost_line(trend, lines[0])
    assert read_trend(trend) == tuple(lines)


def test_a_sheet_date_cited_with_another_digest_is_refused(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    run = fake_run(tmp_path, "run-a", target_repo(tmp_path))
    line = price_run(run, sheet)
    other = line.model_copy(update={"prices_sha256": "e" * 64})
    trend = tmp_path / "trend.jsonl"
    with pytest.raises(TrendError, match="another digest"):
        append_cost_line(trend, other)
    # A date no registry knows, cited twice with two digests: the second is refused.
    new = {"prices_date": "2027-01-01"}
    append_cost_line(trend, line.model_copy(update=new | {"prices_sha256": "a" * 64}))
    with pytest.raises(TrendError, match="another digest"):
        append_cost_line(trend, line.model_copy(update=new | {"prices_sha256": "b" * 64}))
    # The same line written by hand is refused by the reader, naming where it is.
    with trend.open("a") as out:
        out.write(other.model_dump_json() + "\n")
    with pytest.raises(TrendError, match="another digest") as refused:
        read_trend(trend)
    assert refused.value.context["line"] == "2"


def test_a_line_cut_short_or_not_a_cost_line_is_refused(tmp_path: Path, sheet: DatedSheet) -> None:
    line = price_run(fake_run(tmp_path, "run-a", target_repo(tmp_path)), sheet)
    trend = tmp_path / "trend.jsonl"
    trend.write_text(line.model_dump_json())
    with pytest.raises(TrendError, match="could not have written"):
        read_trend(trend)
    trend.write_text('{"usd": "1"}\n')
    with pytest.raises(TrendError, match="could not have written"):
        append_cost_line(trend, line)


def test_partial_usage_is_marked_and_a_leftover_is_priced_at_the_one_role_model(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    repo = target_repo(tmp_path)
    run = fake_run(tmp_path, "run-a", repo)
    before = price_run(run, sheet)
    record = RunRecord(config("run-a", repo), run)
    record.emit(
        LeftoverRead(
            **record.envelope(),
            session_id="left-1",
            stopped=True,
            complete=False,
            trajectory_seal=None,
        )
    )
    record.emit(
        TokensUsed(
            **record.envelope(),
            attribution="session:left-1",
            message_id="m",
            usage=Usage(
                input_tokens=1_000_000,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            partial=True,
        )
    )
    record.close()
    after = price_run(run, sheet)
    assert after.partial and not before.partial
    assert after.usd - before.usd == Decimal(2)  # a million input tokens on the role model


def test_a_leftover_whose_role_the_log_cannot_name_is_refused(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    repo = target_repo(tmp_path)
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles={"electrical": "claude-sonnet-5", "mechanical": "claude-haiku-4-5-20251001"},
        reviewers={"electrical": "claude-opus-5-5", "mechanical": "claude-opus-5-5"},
    )
    run = fake_run(tmp_path, "run-a", repo, overrides={"models": models})
    record = RunRecord(config("run-a", repo, models=models), run)
    record.emit(
        TokensUsed(
            **record.envelope(),
            attribution="session:left-1",
            message_id="m",
            usage=Usage(
                input_tokens=1,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            partial=True,
        )
    )
    record.close()
    with pytest.raises(ManifestError, match="which role"):
        price_run(run, sheet)


def _spend(record: RunRecord, attribution: str, input_tokens: int) -> None:
    record.emit(
        TokensUsed(
            **record.envelope(),
            attribution=attribution,
            message_id=f"m-{attribution}",
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
    )


def test_a_review_with_no_verdict_is_priced_at_the_model_it_ran_on(tmp_path: Path) -> None:
    """Read from the log as the loop writes it: the unavailable review names its model."""
    from physgate.evaluation.observe.cost import _model_of

    unavailable = ReviewUnavailable(
        seq=9,
        ts="2026-10-08T00:00:00.000000Z",
        run_id="run-a",
        gate_mode="on",
        subtask_id="s1",
        attempt=1,
        cause="no_verdict",
        detail="the session ran out of turns before a verdict",
        retry=False,
        session_id="rev-none",
        reviewer_model="claude-opus-5-5",
    )
    cfg = config("run-a", target_repo(tmp_path))
    assert _model_of("reviewer:rev-none", cfg, [unavailable]) == "claude-opus-5-5"
    with pytest.raises(ManifestError, match="no review for"):
        _model_of("reviewer:rev-other", cfg, [unavailable])


def test_a_left_over_review_is_priced_at_the_one_reviewer_model(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    repo = target_repo(tmp_path)
    run = fake_run(tmp_path, "run-a", repo)
    before = price_run(run, sheet)
    record = RunRecord(config("run-a", repo), run)
    record.emit(
        LeftoverRead(
            **record.envelope(),
            session_id="rev-left",
            stopped=True,
            complete=False,
            trajectory_seal=None,
        )
    )
    _spend(record, "reviewer:rev-left", 1_000_000)
    record.close()
    after = price_run(run, sheet)
    assert after.usd - before.usd == Decimal(4)
    assert after.review_tokens["(left over)"].input_tokens == 1_000_000


def test_reviewer_tokens_no_review_or_leftover_accounts_for_are_refused(
    tmp_path: Path, sheet: DatedSheet
) -> None:
    repo = target_repo(tmp_path)
    run = fake_run(tmp_path, "run-a", repo)
    record = RunRecord(config("run-a", repo), run)
    _spend(record, "reviewer:nobody", 1)
    record.close()
    with pytest.raises(ManifestError, match="no review for"):
        price_run(run, sheet)
