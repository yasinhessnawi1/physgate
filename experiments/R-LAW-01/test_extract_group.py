"""R-LAW-01 §2.1, §2.2 and §2.4 on the synthetic fixture: the allowlist, the lines, the grouping.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import law_extract as X
import law_fixture as F
import law_group as GR
import pytest


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    fx = F.build(tmp_path_factory.mktemp("fx"))
    lines, counts, sets = F.extract_fixture(fx)
    flaws, s1, s6, gc = GR.group(lines, sets)
    return {
        **fx,
        "lines": lines,
        "counts": counts,
        "setdata": sets,
        "flaws": flaws,
        "s1": s1,
        "s6": s6,
        "gc": gc,
    }


def by_text(fx: dict[str, Any], words: str, run: str) -> dict[str, Any]:
    found = [x for x in fx["lines"] if words in x["text"] and x["run"] == run]
    assert len(found) == 1, (words, run)
    return found[0]


def flaw_of(fx: dict[str, Any], line: dict[str, Any]) -> dict[str, Any]:
    return next(f for f in fx["flaws"] if line["line_id"] in f["lines"])


# ---------------------------------------------------------------- the allowlist


def test_a_run_file_off_its_digest_is_refused(fx: dict[str, Any], tmp_path: Path) -> None:
    pins = replace(fx["pins"], repo=fx["root"])
    pin = X.RUNS[0]
    copy = tmp_path / "run"
    shutil.copytree(fx["runs"][pin.label], copy)
    with (copy / "events.jsonl").open("a") as f:
        f.write("\n")
    with pytest.raises(X.Refused, match="differs from its recorded digest"):
        X.load_run(pins, pin, copy, fx["digests"])


def test_a_run_of_another_set_kind_or_id_is_refused(fx: dict[str, Any], tmp_path: Path) -> None:
    pins = replace(fx["pins"], repo=fx["root"])
    for field, value, why in (
        ("reviewer_kind", "generalist", "reviewer kind"),
        ("run_id", "someone-else", "run id"),
        ("seed", 99, "seed"),
        ("corpus_manifest_sha256", "0" * 64, "corpus"),
    ):
        pin = X.RUNS[0]
        copy = tmp_path / f"run-{field}"
        shutil.copytree(fx["runs"][pin.label], copy)
        ins = json.loads((copy / "instrument.json").read_text())
        ins[field] = value
        (copy / "instrument.json").write_text(json.dumps(ins))
        digests = {"runs": {pin.label: X.run_digests(copy)}}
        with pytest.raises(X.Refused, match=why):
            X.load_run(pins, pin, copy, digests)


def test_a_set_off_its_manifest_or_sheet_is_refused(fx: dict[str, Any], tmp_path: Path) -> None:
    pins = replace(fx["pins"], repo=fx["root"])
    wrong = replace(
        pins, sets={**pins.sets, "fresh": replace(pins.sets["fresh"], manifest="0" * 64)}
    )
    with pytest.raises(X.Refused, match="manifest"):
        X.load_set(wrong, "fresh")
    sheet = replace(pins, parts_sheet="0" * 64)
    with pytest.raises(X.Refused, match="parts sheet"):
        X.load_set(sheet, "fresh")
    copy = tmp_path / "set"
    shutil.copytree(fx["sets"]["fresh"], copy)
    (copy / "base.json").write_text((copy / "base.json").read_text() + " ")
    with pytest.raises(X.Refused, match="differs from its manifest"):
        X.load_set(pins, "fresh", copy)


def test_not_exactly_the_seven_runs_is_refused(fx: dict[str, Any]) -> None:
    pins = replace(fx["pins"], repo=fx["root"])
    six = {k: v for k, v in fx["runs"].items() if k != "round-1"}
    with pytest.raises(X.Refused, match="seven"):
        X.load_all(pins, six, fx["digests"])


def test_the_cli_holds_the_frozen_pins_and_refuses_the_fixture(fx: dict[str, Any]) -> None:
    args = [a for label, d in fx["runs"].items() for a in ("--run", f"{label}={d}")]
    if not X.INPUTS.exists():
        pytest.skip("inputs/digests.json is filled after the scripts' commit")
    assert X.main(["lines", *args, "--out", str(fx["root"] / "out")]) == 1


# ---------------------------------------------------------------- the lines


def test_lines_are_numbered_by_set_run_side_pair_position(fx: dict[str, Any]) -> None:
    keys = [
        (
            X.SET_ORDER.index(x["set"]),
            [p.label for p in X.RUNS].index(x["run"]),
            X.SIDE_ORDER.index(x["side"]),
            x["pair"],
            x["position"],
        )
        for x in fx["lines"]
    ]
    assert keys == sorted(keys)
    assert [x["line_id"] for x in fx["lines"]] == [f"L{i:04d}" for i in range(1, len(keys) + 1)]


def test_only_the_last_review_line_counts(fx: dict[str, Any]) -> None:
    # a-fresh's m1 injected has a pass line and then a fail line: the fail line's three entries
    assert (
        sum(
            1
            for x in fx["lines"]
            if x["run"] == "a-fresh" and x["pair"] == "m1" and x["side"] == "injected"
        )
        == 3
    )


def test_unmet_and_confirmed_entries_and_the_failing_item(fx: dict[str, Any]) -> None:
    met = [x for x in fx["lines"] if x["text"] == "fine"]
    assert met == []
    added = by_text(fx, "current_limit is 30 A.", "b-fresh")
    assert added["item"] == "ES-5"
    confirmed = by_text(fx, "Values look tuned.", "practice-0")
    assert confirmed["section"] == "reward_hacking"


def test_review_unavailable_contributes_nothing(fx: dict[str, Any]) -> None:
    assert not [x for x in fx["lines"] if x["run"] == "a-fresh" and x["pair"] == "e1"]


def test_item_ids_are_stripped_and_the_locus_found(fx: dict[str, Any]) -> None:
    x = by_text(fx, "sample_rate is 50000 Hz", "a-fresh")
    assert "ES-3" not in x["text"] and "[rule]" in x["text"]
    assert x["locus"] == [["electrical.imu", "sample_rate"]]
    assert by_text(fx, "No numbers here.", "a-fresh")["locus"] == []
    # a parts-sheet row id is never taken for an item id
    assert "R8.01" in by_text(fx, "too high for R8.01", "b-fresh")["text"]


def test_excluded_records_are_counted_not_coded(fx: dict[str, Any]) -> None:
    ex = fx["counts"]["excluded"]["a-fresh"]
    assert ex["criteria"] >= 1 and ex["finding"] >= 1
    assert not [x for x in fx["lines"] if x["text"] == "restated"]


def test_names_pair_is_r_pg_02s_rule() -> None:
    assert X.names_pair("the IMU Sample_Rate is high", "electrical.imu", "sample_rate")
    assert not X.names_pair("the imu sample_rates are high", "electrical.imu", "sample_rate")
    assert not X.names_pair("sample_rate is high", "electrical.imu", "sample_rate")
    assert X.names_pair("electrical.imu_x sample_rate", "electrical.imu", "sample_rate")


def test_strip_ids_spares_row_ids_and_longer_ids() -> None:
    ids = {"R1", "ES-3", "ES-31"}
    assert X.strip_ids("R1 and [R1.02] and ES-31 and ES-3.", ids) == (
        "[rule] and [R1.02] and [rule] and [rule]."
    )


# ---------------------------------------------------------------- the grouping


def test_step_a_absorbs_a_section_1_line_into_its_review_s_line(fx: dict[str, Any]) -> None:
    s1 = by_text(fx, "The imu sample_rate is out of range.", "a-fresh")
    target = by_text(fx, "sample_rate is 50000 Hz", "a-fresh")
    assert flaw_of(fx, s1) is flaw_of(fx, target)
    assert s1["line_id"] not in flaw_of(fx, s1)["locus_lines"]
    assert fx["gc"]["absorbed_by_step_a"] == 1


def test_step_b_joins_one_item_on_one_pair_across_runs_and_sides(fx: dict[str, Any]) -> None:
    a = by_text(fx, "sample_rate is 50000 Hz", "a-fresh")
    b = by_text(fx, "too high for R8.01", "b-fresh")
    twin = by_text(fx, "imu sample_rate is odd", "repeat-K")
    assert flaw_of(fx, a) is flaw_of(fx, b) is flaw_of(fx, twin)


def test_step_b_keeps_empty_locus_lines_apart(fx: dict[str, Any]) -> None:
    empty = by_text(fx, "No numbers here.", "a-fresh")
    f = flaw_of(fx, empty)
    assert f["lines"] == [empty["line_id"]] and f["locus"] == []


def test_step_c_merges_identical_loci_under_two_items(fx: dict[str, Any]) -> None:
    a = by_text(fx, "changed alone", "a-fresh")
    b = by_text(fx, "edit skips the driver", "a-fresh")
    assert a["item"] != b["item"]
    assert flaw_of(fx, a) is flaw_of(fx, b)


def test_step_d_merges_a_base_condition_across_pairs(fx: dict[str, Any]) -> None:
    a = by_text(fx, "lacks a source row", "a-fresh")
    b = by_text(fx, "has no source", "round-1")
    assert a["pair"] != b["pair"]
    f = flaw_of(fx, a)
    assert f is flaw_of(fx, b) and f["base"] and len(f["pairs"]) == 2
    assert fx["gc"]["base_flaws_before_merge"] == 2
    assert fx["gc"]["base_flaws_after_merge"] == 1


def test_a_changed_pair_is_never_a_base_flaw(fx: dict[str, Any]) -> None:
    m1 = by_text(fx, "sample_rate is 50000 Hz", "a-fresh")
    assert not flaw_of(fx, m1)["base"]


def test_the_counts_follow_the_steps(fx: dict[str, Any]) -> None:
    gc = fx["gc"]
    assert gc["after_b"] >= gc["after_c"] >= gc["after_d"]
    assert len(fx["s1"]) == gc["after_c"]
    assert len(fx["flaws"]) == gc["after_d"]
    every = sorted(i for f in fx["flaws"] for i in f["lines"])
    assert every == [x["line_id"] for x in fx["lines"]]


def test_the_wide_merge_joins_base_flaws_on_any_shared_pair(fx: dict[str, Any]) -> None:
    sets = fx["setdata"]
    units = [
        {
            "set": "fresh",
            "pairs": {"u1"},
            "rows": [],
            "locus": frozenset({("n", "a"), ("n", "b")}),
            "items": {"X-1"},
            "base": True,
        },
        {
            "set": "fresh",
            "pairs": {"e1"},
            "rows": [],
            "locus": frozenset({("n", "b")}),
            "items": {"X-2"},
            "base": True,
        },
    ]
    assert len(GR.step_d(units, wide=False)) == 2
    assert len(GR.step_d(units, wide=True)) == 1
    del sets


def test_changed_pairs_include_a_propagation_edge_s_end_nodes(fx: dict[str, Any]) -> None:
    sd = fx["setdata"]["fresh"]
    ch = sd.changed_pairs("p1")
    assert ("electrical.driver", "current_limit") in ch
    assert ("electrical.motor_left", "stall_current") in ch
    assert sd.changed_pairs("m1") == {("electrical.imu", "sample_rate")}
