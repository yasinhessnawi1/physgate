"""The per-role report: the design's denominators, every rate with its count, nothing pooled.

The golden table was rendered from the fixture design and records in ``report_fixtures``
and checked by hand before it was stored: the Wilson bounds against the closed form, each
arm's sums of tokens, dollars and hours, the medians, the paired differences per task, the
firmware counts per arm, and the secondary view's two readings.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from report_fixtures import design, trials

from physgate.evaluation.per_role import cli
from physgate.evaluation.per_role.report import (
    FIRMWARE_TIMING,
    GATE_SCOPE,
    ReportError,
    TrialRecord,
    cluster_bootstrap,
    parse_design,
    parse_trials,
    render,
    wilson,
)

GOLDEN = Path(__file__).parent / "golden" / "per_role_report.md"


def _render(spec: dict[str, Any] | None = None, records: list[dict[str, Any]] | None = None) -> str:
    spec = design() if spec is None else spec
    records = trials(spec) if records is None else records
    return render(
        parse_design(json.dumps(spec).encode()),
        parse_trials(json.dumps(r) for r in records),
    )


def _row(text: str, heading: str, arm: str, table: int = 0) -> list[str]:
    """The cells of ``arm``'s row in the ``table``-th table under ``heading``."""
    section = text.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0]
    tables = [t for t in section.split("\n\n") if t.startswith("| ")]
    for line in tables[table].splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0] == arm:
            return cells
    raise AssertionError(f"no row {arm!r}")


# ------------------------------------------------------------------------------- golden


def test_the_fixture_records_give_the_golden_table_byte_for_byte() -> None:
    assert _render() == GOLDEN.read_text(encoding="utf-8")


def test_the_same_records_in_another_order_give_the_same_bytes() -> None:
    records = trials()
    assert _render(records=list(reversed(records))) == _render(records=records)


# --------------------------------------------------------------------- the denominators


@pytest.mark.parametrize("outcome", ["fail", "flaky", "unscored"])
def test_a_trial_left_out_refuses_the_report_whatever_its_outcome(outcome: str) -> None:
    records = trials()
    dropped = next(i for i, r in enumerate(records) if r["outcome"] == outcome)
    del records[dropped]
    with pytest.raises(ReportError, match="denominator is its tasks times its trials"):
        _render(records=records)


def test_a_trial_recorded_twice_refuses_the_report() -> None:
    records = trials()
    records.append(dict(records[0]))
    with pytest.raises(ReportError, match="recorded twice"):
        _render(records=records)


@pytest.mark.parametrize(
    ("field", "value"),
    [("trial", 2), ("task", "control.z"), ("arm", "observe"), ("suite", "elsewhere")],
)
def test_a_trial_the_design_does_not_run_refuses_the_report(field: str, value: Any) -> None:
    records = trials()
    index = next(i for i, r in enumerate(records) if r["suite"] == "benchmark_category")
    records[index] = {**records[index], field: value}
    with pytest.raises(ReportError):
        _render(records=records)


def test_a_firmware_record_in_a_control_suite_refuses_the_report() -> None:
    records = trials()
    index = next(i for i, r in enumerate(records) if r["suite"] == "control_visible")
    record = dict(records[index])
    del record["control"]
    record["firmware"] = {
        "executions": 3,
        "sandbox_failed": 0,
        "limit_hits": 0,
        "infrastructure_ends": 0,
    }
    records[index] = record
    with pytest.raises(ReportError, match="is not a control trial"):
        _render(records=records)


def test_a_task_in_two_suites_is_refused_because_it_would_count_twice() -> None:
    spec = design()
    spec["suites"][1]["tasks"][0] = "control.a"
    with pytest.raises(ReportError, match="in two suites"):
        parse_design(json.dumps(spec).encode())


# ---------------------------------------------------------- every way a trial can fail


def test_an_unscored_answer_is_a_fail_for_its_arm_and_is_counted_beside() -> None:
    records = trials()
    unscored = [
        r for r in records if r["suite"] == "firmware_visible" and r["outcome"] == "unscored"
    ]
    assert unscored, "the fixture has an unscored raw trial"
    text = _render(records=records)
    row = _row(text, "Firmware, own tasks, visible", "raw agent")
    assert row[1].startswith("1/4 ")
    assert row[-1] == "1"
    for record in unscored:
        record["outcome"] = "fail"
    again = _row(_render(records=records), "Firmware, own tasks, visible", "raw agent")
    assert again[1] == row[1], "an unscored trial weighs exactly as a failed one"
    assert again[-1] == "0"


def test_a_flaky_answer_is_a_fail_for_its_arm_and_is_counted_beside() -> None:
    row = _row(_render(), "Firmware, own tasks, visible", "harness (gate on)")
    assert row[1].startswith("3/4 ")
    assert row[5] == "1"


def test_the_sandbox_s_failures_mid_run_are_counted_per_arm() -> None:
    text = _render()
    section = text.split("### Firmware, own tasks, visible\n", 1)[1].split("\n### ", 1)[0]
    line = next(x for x in section.splitlines() if "sandbox runtime wrote to its error" in x)
    assert "harness (gate on) 0/12" in line
    assert "harness (gate observes) 0/12" in line
    assert "raw agent 2/10" in line


def test_the_firmware_section_says_its_timing_is_unchecked_by_the_gate() -> None:
    text = _render()
    firmware = text.split("## Firmware\n", 1)[1]
    assert FIRMWARE_TIMING in firmware.split("### ", 1)[0]
    assert text.count(GATE_SCOPE) == 2


# --------------------------------------------------------------- no rate without its n


def _cells(text: str) -> list[str]:
    """Every body cell of every table, and every bullet: where the report's numbers are."""
    cells = []
    lines = text.splitlines()
    for line, following in zip(lines, [*lines[1:], ""], strict=True):
        is_head = following.startswith("|---")
        if line.startswith("| ") and not is_head:
            cells += [c.strip() for c in line.strip("|").split("|")]
        elif line.startswith("- "):
            cells.append(line)
    return cells


def test_every_percentage_the_report_prints_stands_with_its_count_and_denominator() -> None:
    text = _render()
    # Every percentage is printed as ``k/n · p %``: the count, then the rate.
    for cell in _cells(text):
        for match in re.finditer(r"(\d+(?:\.\d+)?) %", cell):
            before = cell[: match.start()]
            assert re.search(r"\b\d+/\d+ · $", before), f"a percentage without its count: {cell!r}"


def test_each_arm_s_rate_counts_only_that_arm_s_trials() -> None:
    records = trials()
    before = _render(records=records)
    for record in records:
        if record["arm"] == "raw" and record["suite"] == "control_visible":
            record["outcome"] = "pass"
    after = _render(records=records)
    for arm in ("harness (gate on)", "harness (gate observes)"):
        assert _row(after, "Control, own tasks, visible", arm) == _row(
            before, "Control, own tasks, visible", arm
        )
    assert _row(after, "Control, own tasks, visible", "raw agent")[1].startswith("6/6 ")


def test_the_gap_is_visible_minus_held_out_per_arm() -> None:
    text = _render()
    gap = text.split("### Reward-hacking gap: visible minus held-out\n", 1)[1]
    row = next(line for line in gap.splitlines() if line.startswith("| harness (gate on)"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1].startswith("4/6 ")
    assert cells[2].startswith("3/6 ")
    assert cells[3] == "+16.7 points"


# ------------------------------------------------------------------- published numbers


def test_a_published_number_without_its_record_is_refused() -> None:
    spec = design()
    del spec["published"][0]["record"]
    with pytest.raises(ReportError, match="no record of its split, protocol and scorer"):
        _render(spec)


def test_a_published_number_without_our_raw_arm_on_its_split_is_refused() -> None:
    spec = design()
    spec["published"][0]["suite"] = "nowhere"
    with pytest.raises(ReportError, match="no suite with our raw arm"):
        _render(spec)


def test_a_published_number_is_shown_beside_ours_with_every_difference() -> None:
    beside = _render().split("## Beside, not against: published numbers\n", 1)[1]
    assert "Ours on the same split (`benchmark_category`)" in beside
    assert "raw agent 1/8 · 12.5 %" in beside
    assert "  - its checker reads no gain margin" in beside
    assert "Warning: its tasks are public" in beside


# ------------------------------------------------------------------------- cost basis


def test_one_arm_s_cost_never_mixes_a_billed_price_with_an_estimate() -> None:
    records = trials()
    records[0]["cost"] = {**records[0]["cost"], "basis": "list_price"}
    with pytest.raises(ReportError, match="mixes a billed list price"):
        _render(records=records)


# ------------------------------------------------------------------------------- stats


@pytest.mark.parametrize(
    ("passed", "n", "low", "high"),
    [(5, 10, 0.2366, 0.7634), (0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0), (1, 6, 0.0301, 0.5635)],
)
def test_the_wilson_interval_is_the_closed_form(
    passed: int, n: int, low: float, high: float
) -> None:
    got = wilson(passed, n)
    assert got == pytest.approx((low, high), abs=5e-5)


def test_a_bootstrap_is_the_same_for_its_seed_and_label_and_apart_from_others() -> None:
    groups = [[0.0, 0.2, 0.4, 0.6, 1.0, 1.0, 0.8, 0.2]]

    def mean(sample: Any) -> float:
        return sum(sample[0]) / len(sample[0])

    one = cluster_bootstrap(groups, mean, seed=3, label="a", draws=500)
    assert one == cluster_bootstrap(groups, mean, seed=3, label="a", draws=500)
    assert one != cluster_bootstrap(groups, mean, seed=3, label="b", draws=500)


# --------------------------------------------------------------------- record shapes


def _record(**changes: Any) -> dict[str, Any]:
    base = next(r for r in trials() if r["suite"] == "control_visible" and r["arm"] == "raw")
    return {**base, **changes}


def test_a_raw_trial_records_no_gate_and_no_reviewer() -> None:
    with pytest.raises(ValueError, match="raw arm neither"):
        gate = {"checks_run": 1, "artefacts_caught": 0, "caught_after_reviewer_passed": 0}
        TrialRecord.model_validate_json(json.dumps(_record(gate=gate)))


def test_a_control_trial_is_never_flaky_but_may_be_unscored() -> None:
    with pytest.raises(ValueError, match="never flaky"):
        TrialRecord.model_validate_json(json.dumps(_record(outcome="flaky")))
    record = TrialRecord.model_validate_json(json.dumps(_record(outcome="unscored")))
    assert record.outcome == "unscored"


def test_an_unscored_control_trial_is_a_fail_for_its_arm_and_is_counted_beside() -> None:
    records = trials()
    target = next(
        r
        for r in records
        if r["suite"] == "control_visible" and r["arm"] == "harness" and r["outcome"] == "pass"
    )
    before = _row(_render(records=records), "Control, own tasks, visible", "harness (gate on)")
    target["outcome"] = "unscored"
    after = _row(_render(records=records), "Control, own tasks, visible", "harness (gate on)")
    passed = int(before[1].split("/")[0])
    assert after[1].startswith(f"{passed - 1}/6 ")
    assert after[-1] == "1" and before[-1] == "0"


def test_a_bare_float_for_dollars_is_kept_exact() -> None:
    record = TrialRecord.model_validate_json(json.dumps(_record()))
    assert record.cost.usd == Decimal("1.20")


# --------------------------------------------------------------------------------- cli


def test_the_command_writes_nothing_and_exits_one_on_a_missing_trial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec, records = design(), trials()
    (tmp_path / "design.json").write_text(json.dumps(spec))
    (tmp_path / "trials.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records[1:]))
    out = tmp_path / "report.md"
    args = ["--design", str(tmp_path / "design.json"), "--trials", str(tmp_path / "trials.jsonl")]
    assert _main([*args, "--out", str(out)]) == 1
    assert not out.exists()
    assert "no report" in capsys.readouterr().err
    (tmp_path / "trials.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    assert _main([*args, "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == GOLDEN.read_text(encoding="utf-8")


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers())
    args = parser.parse_args(["per-role", "report", *argv])
    result: int = args.func(args)
    return result
