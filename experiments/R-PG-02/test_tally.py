"""Tests of tally.py: its table is the criteria's, and its rules on real runs of a test set.

Run explicitly, from the repository root: uv run pytest -q experiments/R-PG-02/

The runs are real instrument runs over the fixture set (``rpg02_fixture``), each review
scripted; nothing is called, and no set of the experiment is read.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import rpg02_fixture as fx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def _load(name: str, path: Path) -> Any:  # noqa: ANN401 - a module
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass reads its module while the module loads
    spec.loader.exec_module(module)
    return module


tally = _load("rpg02_tally", HERE / "tally.py")
EL = "electrical"
DS, AC = "domain_standards", "acceptance_criteria"


# ---- the table is the criteria's, and every id an item of its section --------------------


def criteria_table() -> tuple[dict[str, dict[str, tuple[str, ...]]], dict[str, tuple[str, ...]]]:
    """§4.1's table as CRITERIA.md prints it: the paired cells and the generalist column."""
    lines = [ln.strip() for ln in (HERE / "CRITERIA.md").read_text().splitlines()]
    head = "| Class | control | electrical | firmware | mechanical | generalist (every class) |"
    start = lines.index(head)
    paired: dict[str, dict[str, tuple[str, ...]]] = {r: {} for r in tally.ROLES}
    generalist: dict[str, tuple[str, ...]] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("| `"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        error_class = cells[0].strip("`")
        for role, text in zip(tally.ROLES, cells[1:5], strict=True):
            paired[role][error_class] = tuple(i.strip() for i in text.split(","))
        if cells[5] != "as above":
            for part in cells[5].split(";"):
                role, item = part.split()
                generalist[role] = (item,)
    return paired, generalist


def test_the_script_s_table_is_the_criteria_s_and_fills_every_cell() -> None:
    paired, generalist = criteria_table()
    assert paired == tally.ERROR_ITEMS
    assert generalist == tally.GENERALIST_ITEMS
    for role in tally.ROLES:
        assert set(tally.ERROR_ITEMS[role]) == set(tally.CLASSES)
        assert all(tally.ERROR_ITEMS[role].values())


def test_the_regrouping_rule_derives_the_table_from_r_pg_01_s() -> None:
    old = _load("rpg01_tally", REPO / "experiments" / "R-PG-01" / "tally_rows.py").ERROR_ITEMS
    assert old == tally.R_PG_01_ITEMS
    for role, cells in old.items():
        balance = set(cells.get("magnitude", ()))
        for check in ("equilibrium", "power", "conservation"):
            balance |= set(cells.get(check, ()))
        assert set(tally.ERROR_ITEMS[role]["unit"]) == set(cells["units"])
        assert set(tally.ERROR_ITEMS[role]["magnitude"]) == set(cells["magnitude"])
        assert set(tally.ERROR_ITEMS[role]["propagation"]) == set(cells["propagation"])
        assert set(tally.ERROR_ITEMS[role]["equilibrium"]) == balance


def test_every_id_is_an_item_of_its_section_in_the_rubric_in_force() -> None:
    from physgate.reviewers.rubric import generalist_of, load_rubric

    for role in tally.ROLES:
        rubric = load_rubric(REPO / "knowledge", role)
        sections = {i.id: i.section for i in rubric.items}
        for ids in tally.ERROR_ITEMS[role].values():
            for item in ids:
                assert sections.get(item) == DS, (role, item)
        general = {i.id: i.section for i in generalist_of(rubric).items}
        for item in tally.GENERALIST_ITEMS[role]:
            assert general.get(item) == AC, (role, item)


def test_the_criteria_name_no_threshold_the_script_does_not_hold() -> None:
    text = (HERE / "CRITERIA.md").read_text()
    assert f"R_gate on the fresh set ≥ **{tally.P2_FLOOR} of 40**" in text
    assert f"exceeds **{tally.POSSIBLE_TAILORING}**" in text
    assert re.search(rf"10,000 draws, seed \*\*{tally.BOOTSTRAP_SEED}\*\*", text)
    assert tally.BOOTSTRAP_DRAWS == 10_000


# ---- the rules on real runs ---------------------------------------------------------------

#: What each arm's stand-in says, per item: (injected, twin).
PAIRED = {
    # Named: ES-32 cited, the twin passes.
    "m1": (("fail", [("ES-32", DS, "sample_rate is 50 kHz")], "ES-32"), ("pass",)),
    # Named by ES-34; ES-32 is cited by both. The twin's failing item names a listed sheet
    # pair (the sensor's rate, whose row gives no number): a sheet-flaw rejection.
    "p1": (
        ("fail", [("ES-34", DS, "driver not revisited"), ("ES-32", DS, "x y z")], "ES-34"),
        ("fail", [("ES-32", DS, "electrical.imu sample_rate has no row giving it")], "ES-32"),
    ),
}
GENERALIST = {
    # Cited by both: not named.
    "m1": (
        ("fail", [("EA-9", AC, "the rate is out of range")], "EA-9"),
        ("fail", [("EA-9", AC, "the rate is not sourced")], "EA-9"),
    ),
    # No verdict on the injected item; the twin is blocked.
    "p1": (("unavailable", "no_verdict"), ("blocked",)),
}
OLD = {
    "m1": (("pass",), ("pass",)),
    "p1": (("fail", [("ES-34", DS, "driver not revisited")], "ES-34"), ("pass",)),
    "u1": (("fail", [("ES-31", DS, "a current in volts")], "ES-31"), ("pass",)),
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("runs")
    fresh = fx.write_set(base / "set-f")
    old = fx.write_set(base / "set-o", stated=True)
    return {
        "fresh": fresh,
        "old": old,
        "a-fresh": fx.real_run(fresh, base / "af", 13, PAIRED),
        "b-fresh": fx.real_run(fresh, base / "bf", 13, GENERALIST, kind="generalist"),
        "a-old": fx.real_run(old, base / "ao", 7, OLD, lanes=2),
    }


@pytest.fixture(scope="module")
def out(runs: dict[str, Path]) -> dict[str, Any]:
    return tally.tally(
        runs["a-fresh"],
        runs["b-fresh"],
        runs["a-old"],
        runs["fresh"],
        runs["old"],
        any_count=True,
        draws=500,
    )


def test_the_paired_arm_names_by_the_twin_condition_and_counts_the_sheet_flaw(
    out: dict[str, Any],
) -> None:
    per = {p["artefact"]: p for p in out["runs"]["a-fresh"]["per_item"]}
    assert {a: per[a]["deciding"] for a in per} == {"m1": ["ES-32"], "p1": ["ES-34"]}
    assert per["p1"]["sheet_flaw_rejection"] and not per["m1"]["sheet_flaw_rejection"]
    paired = out["primary_fresh"]["paired"]
    assert (paired["R"], paired["A"], paired["J"]) == (2, 1, 0.5)
    assert paired["sheet_flaw_rejections"] == 1
    assert paired["without_sheet_flaw_rejections"] == {"A": [1, 1], "J": 1.0}
    assert paired["unscored"] == 0 and paired["R_with_unscored_dropped"] == [2, 2]


def test_no_verdict_counts_against_the_generalist_in_both_directions(out: dict[str, Any]) -> None:
    gen = out["primary_fresh"]["generalist"]
    assert (gen["R"], gen["A"], gen["J"]) == (0, 0, -1.0)
    assert gen["no_verdict"] == {"injected": 1, "twins": 1}
    assert gen["range_if_each_no_verdict_went_either_way"]["J"] == [-1.0, 0.0]
    assert gen["among_verdicts_only"] == {"R": [0, 1], "A": [0, 1], "J": -1.0}
    listed = out["runs"]["b-fresh"]["no_verdict_by_role"][EL]
    assert listed == {
        "injected": [["p1", "review_unavailable", "no_verdict"]],
        "twins": [["p1", "blocked", "blocking_spec_defect"]],
    }
    contrast = out["primary_fresh"]["contrast_paired_minus_generalist"]
    assert contrast["J"] == 1.5 and len(contrast["interval"]) == 2


def test_the_gate_s_right_reason_and_its_counts_beside_its_passes(out: dict[str, Any]) -> None:
    gate = out["primary_fresh"]["gate"]
    assert (gate["R"], gate["A"], gate["caught_any_record"], gate["caught_elsewhere"]) == (
        2,
        2,
        2,
        0,
    )
    checks = out["runs"]["a-fresh"]["gate_checks"]["twins"]["per_check"]
    assert all(
        row["evaluated"] >= 0 and row["pass_records"] >= row["nothing_in_scope"]
        for row in checks.values()
    )
    assert checks["magnitude"]["pass_records"] > 0 and checks["magnitude"]["evaluated"] > 0
    assert "items_with_a_forces_only_pass" in out["runs"]["a-fresh"]["gate_checks"]["twins"]
    assert out["criteria"]["P2_gate_right_reason_fresh"]["R_gate_fresh"] == [2, 2]


def test_a_headroom_refusal_against_a_continuous_rating_is_the_stated_limit(
    out: dict[str, Any],
) -> None:
    old_gate = out["old_set"]["gate"]
    assert old_gate["twins_refused_under_the_stated_headroom_limit"] == ["u1"]
    assert (old_gate["A"], old_gate["A_gate_strict"]) == (3, 2)
    assert out["criteria"]["P1_gate_accepts_every_old_twin"]["met"] is True
    assert out["old_set_facts"]["current_limit_values_citing_a_continuous_rating"] >= 1


def test_the_risk_row_and_the_r_pg_01_sense_are_reported_only(out: dict[str, Any]) -> None:
    assert out["s7_risk_row_fresh"] == {
        "A": 0,
        "C": 0,
        "thresholds": {"C": 10, "A": 4},
        "verdict": "reported only",
    }
    sense = out["runs"]["a-old"]["r_pg_01_sense"]
    assert sense["approved"] == 1 and sense["caught_any_record"] == 3


def test_the_cost_and_the_lanes_are_read_from_the_run(out: dict[str, Any]) -> None:
    cost = out["runs"]["a-fresh"]["cost"]
    assert cost["reviews"] == 4 and cost["tokens_of_verdict_lines"]["output_tokens"] == 80
    assert cost["usd_list_price_equivalent"] >= 0
    assert set(out["runs"]["a-old"]["per_lane"]) <= {"0", "1"}
    assert out["runs"]["a-old"]["lanes"] == 2


def test_the_practice_figures_give_p5_with_the_gate_at_this_commit(runs: dict[str, Path]) -> None:
    got = tally.tally(
        runs["a-fresh"],
        runs["b-fresh"],
        runs["a-old"],
        runs["fresh"],
        runs["old"],
        practice_run=runs["a-fresh"],
        practice_corpus=runs["fresh"],
        any_count=True,
        draws=200,
    )
    p5 = got["criteria"]["P5_not_tailored"]
    assert p5["paired"]["drop"] == 0.0 and p5["paired"]["tailoring"] is False
    assert p5["gate"]["J_practice"] == p5["gate"]["J_fresh"] == 1.0
    assert got["practice"]["label"] == "PRACTICE, never a result"


def test_a_row_that_disagrees_with_its_log_stops_the_tally(
    runs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    import shutil

    copy = tmp_path_factory.mktemp("bad") / "run"
    shutil.copytree(runs["a-fresh"], copy)
    rows = [json.loads(x) for x in (copy / "results.jsonl").read_text().splitlines()]
    rows[0]["reviewer_verdict"] = "pass" if rows[0]["reviewer_verdict"] != "pass" else "fail"
    (copy / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(tally.TallyError, match="disagrees"):
        tally.tally(
            copy,
            runs["b-fresh"],
            runs["a-old"],
            runs["fresh"],
            runs["old"],
            any_count=True,
            draws=10,
        )


def test_the_denominator_is_forty_unless_lifted(runs: dict[str, Path]) -> None:
    with pytest.raises(tally.TallyError, match="denominator"):
        tally.tally(
            runs["a-fresh"], runs["b-fresh"], runs["a-old"], runs["fresh"], runs["old"], draws=10
        )


def test_the_arms_must_be_the_kinds_they_are_named(runs: dict[str, Path]) -> None:
    with pytest.raises(tally.TallyError, match="generalist"):
        tally.tally(
            runs["a-fresh"],
            runs["a-fresh"],
            runs["a-old"],
            runs["fresh"],
            runs["old"],
            any_count=True,
            draws=10,
        )


def test_the_statistics() -> None:
    assert tally.wilson(0, 40)[0] == 0.0 and tally.wilson(40, 40)[1] == 1.0
    assert tally.j_of([(1, 1), (0, 0)]) == 0.0
    pairs = [(1, 1)] * 30 + [(0, 1)] * 10
    lo, hi = tally.j_interval(pairs, 500)
    assert 0 < lo <= tally.j_of(pairs) <= hi <= 1
    assert tally.j_interval(pairs, 500) == [lo, hi]  # the seed fixes the draws
    assert tally.contrast_interval(pairs, pairs, 200) == [0.0, 0.0]


def test_the_command_refuses_without_every_run(tmp_path_factory: pytest.TempPathFactory) -> None:
    empty = tmp_path_factory.mktemp("empty")
    with pytest.raises(SystemExit):
        tally.main(["--a-fresh", str(empty)])
