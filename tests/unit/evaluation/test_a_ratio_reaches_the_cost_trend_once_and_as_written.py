"""A generalist review's ratio reaches the cost trend, once, and only as its writer wrote it.

The trend already carries every run's cost line and its review tokens by subtask. The
paired-versus-generalist ratio joins it as a line of its own, read from an existing
``baseline.json`` and held to the records beside it: no model is called and nothing is
rerun. The one reader refuses a ratio line it could not have written (a ratio edited by
hand, a line with no kind, a field it does not know, a sheet cited with another digest)
and a ratio appended twice.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from observe_rig import fake_run, target_repo
from test_the_pairing_ratio_compares_one_attempt_read_under_one_seal import _packet, _review

from physgate.cli import main
from physgate.evaluation.observe.cost import (
    CostLine,
    append_cost_line,
    append_ratio_line,
    load_price_sheet,
    price_run,
    read_trend,
    read_trend_lines,
)
from physgate.evaluation.observe.exceptions import ManifestError, TrendError
from physgate.evaluation.observe.generalist import (
    BASELINE_NAME,
    CONFIG_NAME,
    EVENTS_NAME,
    GeneralistConfig,
    ratio_line_from,
    review_ratio,
)
from physgate.evaluation.observe.ratio import RatioLine
from physgate.orchestrator.events import EventLog, ReviewRan, RunStarted, SubtaskPlanned
from physgate.orchestrator.protocols import ReviewResult

DATE = "2026-09-27"


def _baseline(
    tmp_path: Path, *, recorded: ReviewResult | None = None, paired_session: str = "paired-1"
) -> Path:
    """A generalist review's directory, as ``physgate generalist`` leaves it; its baseline."""
    out = tmp_path / "generalist"
    out.mkdir()
    generalist = _review("generalist", 1_000_000)
    ratio = review_ratio(
        (_review("paired", 2_500_000), _packet()), (generalist, _packet()), load_price_sheet(DATE)
    )
    config = GeneralistConfig(
        run_id="run-1-generalist",
        paired_run_id="run-1",
        paired_config_sha256="4" * 64,
        subtask_id="s1",
        attempt=1,
        paired_review_session=paired_session,
        paired_packet_sha256="5" * 64,
        paired_rubric_sha256="6" * 64,
        generalist_rubric_sha256="7" * 64,
        reviewer_model="claude-sonnet-5",
        claude_version="2.1.283",
        effort="high",
        max_output_tokens=64000,
    )
    (out / CONFIG_NAME).write_text(config.model_dump_json(indent=1) + "\n")
    log = EventLog(out / EVENTS_NAME, run_id="run-1-generalist", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="8" * 64))
    log.append(
        SubtaskPlanned(
            **log.envelope(),
            subtask_id="s1",
            spec_path="-",
            assigned_role="control",
            module_dir="-",
        )
    )
    result = recorded or generalist
    log.append(ReviewRan(**log.envelope(), subtask_id="s1", attempt=1, result=result))
    log.close()
    baseline = out / BASELINE_NAME
    baseline.write_text(ratio.model_dump_json(indent=1) + "\n")
    return baseline


def _cost_line(tmp_path: Path) -> CostLine:
    return price_run(fake_run(tmp_path, "run-a", target_repo(tmp_path)), load_price_sheet(DATE))


def test_the_ratio_line_is_the_baseline_with_where_it_was_measured(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path)
    line = ratio_line_from(baseline)
    assert (line.kind, line.run_id, line.paired_run_id) == (
        "review_ratio",
        "run-1-generalist",
        "run-1",
    )
    assert line.baseline_sha256 == hashlib.sha256(baseline.read_bytes()).hexdigest()
    assert line.ratio.token_ratio == 2.5 and line.ratio.paired.session_id == "paired-1"


def test_a_cost_line_and_a_ratio_line_share_the_trend_and_each_reads_back(
    tmp_path: Path,
) -> None:
    trend = tmp_path / "trend.jsonl"
    cost, ratio = _cost_line(tmp_path), ratio_line_from(_baseline(tmp_path))
    append_cost_line(trend, cost)
    append_ratio_line(trend, ratio)
    assert read_trend_lines(trend) == (cost, ratio)
    assert read_trend(trend) == (cost,)  # the cost reader's answer is unchanged


def test_a_ratio_appended_twice_is_refused_and_the_file_is_unchanged(tmp_path: Path) -> None:
    trend = tmp_path / "trend.jsonl"
    line = ratio_line_from(_baseline(tmp_path))
    append_ratio_line(trend, line)
    before = trend.read_bytes()
    with pytest.raises(TrendError, match="already holds this ratio"):
        append_ratio_line(trend, line)
    assert trend.read_bytes() == before
    # Written by hand, the reader refuses it, naming the line.
    with trend.open("a") as out:
        out.write(line.model_dump_json() + "\n")
    with pytest.raises(TrendError, match="already holds this ratio") as refused:
        read_trend_lines(trend)
    assert refused.value.context["line"] == "2"


def _foreign(line: RatioLine, change: str) -> str:
    data = json.loads(line.model_dump_json())
    if change == "a ratio edited by hand":
        data["ratio"]["token_ratio"] = "1.5"
    elif change == "a cost edited by hand":
        data["ratio"]["paired"]["usd"] = "1"
    elif change == "no kind":
        del data["kind"]
    elif change == "another kind":
        data["kind"] = "review_ratios"
    elif change == "a field it does not know":
        data["note"] = "x"
    elif change == "two generalist reviews":
        data["ratio"]["paired"]["rubric_kind"] = "generalist"
    return json.dumps(data) + "\n"


@pytest.mark.parametrize(
    "change",
    [
        "a ratio edited by hand",
        "a cost edited by hand",
        "no kind",
        "another kind",
        "a field it does not know",
        "two generalist reviews",
    ],
)
def test_a_line_its_writer_could_not_have_written_is_refused(tmp_path: Path, change: str) -> None:
    trend = tmp_path / "trend.jsonl"
    append_cost_line(trend, _cost_line(tmp_path))
    with trend.open("a") as out:
        out.write(_foreign(ratio_line_from(_baseline(tmp_path)), change))
    with pytest.raises(TrendError, match="could not have written") as refused:
        read_trend_lines(trend)
    assert refused.value.context["line"] == "2"
    with pytest.raises(TrendError):
        append_cost_line(trend, _cost_line(tmp_path / "other"))


def test_a_ratio_citing_its_sheet_with_another_digest_is_refused(tmp_path: Path) -> None:
    line = ratio_line_from(_baseline(tmp_path))
    edited = line.model_copy(
        update={"ratio": line.ratio.model_copy(update={"prices_sha256": "e" * 64})}
    )
    with pytest.raises(TrendError, match="another digest"):
        append_ratio_line(tmp_path / "trend.jsonl", edited)


@pytest.mark.parametrize("what", ["another session", "other tokens", "another paired review"])
def test_a_baseline_its_directory_does_not_describe_is_refused(tmp_path: Path, what: str) -> None:
    generalist = _review("generalist", 1_000_000)
    if what == "another session":
        baseline = _baseline(
            tmp_path, recorded=generalist.model_copy(update={"session_id": "generalist-2"})
        )
    elif what == "other tokens":
        baseline = _baseline(tmp_path, recorded=_review("generalist", 999_999))
    else:
        baseline = _baseline(tmp_path, paired_session="paired-2")
    with pytest.raises(ManifestError, match="not the review its directory's records describe"):
        ratio_line_from(baseline)


def test_the_command_appends_once_and_refuses_the_second(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline, trend = _baseline(tmp_path), tmp_path / "trend.jsonl"
    assert main(["ratio", "--baseline", str(baseline), "--append", str(trend)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["kind"] == "review_ratio" and printed["appended_to"] == str(trend)
    assert read_trend_lines(trend) == (ratio_line_from(baseline),)
    assert main(["ratio", "--baseline", str(baseline), "--append", str(trend)]) == 2
    assert "already holds this ratio" in capsys.readouterr().err
    assert len(read_trend_lines(trend)) == 1
