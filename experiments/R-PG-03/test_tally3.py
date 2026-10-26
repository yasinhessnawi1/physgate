"""Tests of tally3.py: the three rules, the strata, Q1-Q4, the class rule, the row, and R8.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

The runs are real instrument runs over the fixture set (``fixture``), each review scripted per
item and arm; nothing is called, and no set of the experiment is read. R-PG-02's ``tally.py`` is
imported unedited, and a test holds it to its blob.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import fixture as fx  # noqa: E402
import tally3 as t3  # noqa: E402

AC, DS = fx.SECTION1, fx.SECTION2
#: The edge of the fixture's propagation item: its target's id, as a reviewer would name it.
EDGE_TARGET = "control.balance_loop"
#: Each arm's scripted reviews, per item: (injected, twin).
BY_ARM: dict[str, dict[str, tuple[fx.Script, fx.Script]]] = {
    "A2": {
        "c1": (fx.fail(("D25", DS, "the gain's unit")), ("pass",)),
        "e1": (fx.fail(("EA-9", AC, "the rate")), ("pass",)),
        "f1": (
            fx.fail(("DS-30", DS, f"{EDGE_TARGET} is not revisited")),
            fx.fail(("DS-30", DS, "the tick")),
        ),
        "k1": (("pass",), ("pass",)),
    },
    "A1": {
        "c1": (fx.fail(("D26", DS, "units")), fx.fail(("D99", DS, "another thing"))),
        "e1": (fx.fail(("ES-32", DS, "the rate is too high")), ("pass",)),
        "f1": (("pass",), ("pass",)),
        "k1": (("blocked",), ("unavailable", "infrastructure")),
    },
    "B": {
        "c1": (fx.fail(("A7", AC, "the gain")), ("pass",)),
        "e1": (fx.fail(("ES-32", DS, "x")), ("pass",)),
        "f1": (fx.fail(("AC-9", AC, "y")), fx.fail(("AC-9", AC, "y"))),
        "k1": (fx.fail(("MA-10", AC, "the mass is in newtons")), ("pass",)),
    },
}
WANT = {
    # item: (R_common, R_strict, A) per arm
    "A2": {"c1": (1, 1, 1), "e1": (1, 0, 1), "f1": (0, 0, 0), "k1": (0, 0, 1)},
    "A1": {"c1": (1, 1, 0), "e1": (1, 1, 1), "f1": (0, 0, 1), "k1": (0, 0, 0)},
    "B": {"c1": (1, 1, 1), "e1": (0, 0, 1), "f1": (0, 0, 0), "k1": (1, 1, 1)},
}


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("tally")
    sets = fx.write_sets(base / "sets", [common.BLOCK_CORPUS[b] for b in common.PRIMARY_BLOCKS])
    attempts = []
    for block in common.PRIMARY_BLOCKS:
        runs = {}
        for arm in common.ARMS:
            runs[arm] = fx.real_run(
                sets / common.BLOCK_CORPUS[block],
                base / block / arm,
                common.BLOCK_SEED[block],
                arm,
                BY_ARM[arm],
            )
        attempts.append(fx.attempt(block, runs))
    records = base / "records"
    fx.write_blocks(
        records, attempts, {"s": "the class's cap", "p1": "fresh-v1c failed", "p2": "same"}
    )
    tuning = fx.write_set(base / "tuning")
    practice = {
        "round-1": fx.real_run(tuning, base / "p-r1", 13, "A2", BY_ARM["A2"]),
        "a-fresh": fx.real_run(tuning, base / "p-af", 13, "A1", BY_ARM["A1"]),
        "repeat-K": fx.real_run(tuning, base / "p-rk", 13, "A1", BY_ARM["A1"]),
    }
    return {
        "base": base,
        "sets": sets,
        "records": records,
        "tuning": tuning,
        "practice": practice,
        "attempts": attempts,
    }


def run_tally(made: dict[str, Any], **kw: Any) -> dict[str, Any]:  # noqa: ANN401
    args: dict[str, Any] = {
        "practice_pinned": False,
        "fills": None,
        "any_count": True,
        "tuning": made["tuning"],
    }
    args.update(kw)
    return t3.tally(made["records"], made["sets"], made["practice"], None, {}, 200, **args)


def test_the_frozen_tally_is_imported_unedited() -> None:
    blob = subprocess.run(
        [
            "git",
            "-C",
            str(common.REPO),
            "hash-object",
            str(common.REPO / "experiments/R-PG-02/tally.py"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    pinned = subprocess.run(
        ["git", "-C", str(common.REPO), "rev-parse", "9993b2f:experiments/R-PG-02/tally.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert blob == pinned
    for name in (
        "set_facts",
        "Run",
        "per_item",
        "naming",
        "names_pair",
        "wilson",
        "j_of",
        "contrast_interval",
        "drop_interval",
    ):
        assert getattr(t3.T, name) is not None


def test_every_item_is_scored_under_the_common_and_strict_rules(made: dict[str, Any]) -> None:
    got = run_tally(made)
    for arm in common.ARMS:
        items = [p for p in got["per_item"][arm] if p["corpus"] == "fresh-v2-x1"]
        have = {p["item"]: (int(p["R_common"]), int(p["R_strict"]), int(p["A"])) for p in items}
        assert have == WANT[arm], arm


def test_the_locating_rule_holds_the_twin_condition(made: dict[str, Any]) -> None:
    got = run_tally(made)
    a2 = {p["item"]: p for p in got["per_item"]["A2"] if p["corpus"] == "fresh-v2-x1"}
    # f1's injected review locates the edge's target, but its twin's review fails too and
    # does not locate it: the locating rule credits it although the cell rules do not.
    assert a2["f1"]["R_locating"] and not a2["f1"]["R_common"]
    assert not a2["k1"]["R_locating"]


def test_a_changed_quantity_s_name_with_its_node_locates_and_its_name_alone_does_not() -> None:
    pair = [("power.supply", "max_voltage")]
    assert t3.locates("the supply's max_voltage is above the regulator's", [], pair)
    assert t3.locates("power.supply max_voltage", [], pair)
    assert not t3.locates("max_voltage is above the regulator's", [], pair)
    assert not t3.locates("the supply is fine", [], pair)
    assert t3.locates("see power.supply here", ["power.supply"], [])
    assert not t3.locates("see power.supply2 here", ["power.supply"], [])


def test_the_primary_counts_are_120_pairs_in_three_strata_of_40_in_line_order(
    made: dict[str, Any],
) -> None:
    got = run_tally(made)
    a2 = got["per_item"]["A2"]
    assert [p["corpus"] for p in a2][:4] == ["fresh-v2-x1"] * 4
    assert [p["corpus"] for p in a2][4] == "fresh-v2-x2"
    assert got["primary"]["figures"]["A2"]["common"]["n"] == 24  # 6 blocks of the 4-item fixture
    assert got["primary"]["figures"]["A2"]["common"]["R"] == 12


def test_no_verdicts_count_against_the_arm_with_the_ranges_beside(made: dict[str, Any]) -> None:
    f = run_tally(made)["primary"]["figures"]["A1"]["common"]
    assert f["no_verdict"] == {"injected": 6, "twins": 6}
    assert f["range_if_each_no_verdict_went_either_way"]["R"] == [f["R"], f["R"] + 6]


def test_the_decision_is_taken_by_the_row_and_the_class_clause_says_not_measured(
    made: dict[str, Any],
) -> None:
    got = run_tally(made)
    assert got["decision"]["row"] in ("1", "2a", "2b", "3a", "3b")
    assert "was not measured" in got["decision"]["class_clause"]
    assert got["not_run"] == {"s": "the class's cap", "p1": "fresh-v1c failed", "p2": "same"}
    assert got["criteria"]["Q4"]["J_before"] == round(
        t3.T.j_of([(1, 1), (1, 1), (0, 0), (0, 1)]), 4
    )


def test_r8_nothing_is_tallied_before_the_last_block_has_ended(
    made: dict[str, Any], tmp_path: Path
) -> None:
    rec = tmp_path / "records"
    with pytest.raises(t3.RefusedError, match="R8"):
        t3.blocks_record(rec)
    fx.write_blocks(rec, made["attempts"][:-1], {"s": "x", "p1": "x", "p2": "x"})
    with pytest.raises(t3.RefusedError, match="R8"):
        t3.blocks_record(rec)
    open_ = [*made["attempts"][:-1], {**made["attempts"][-1], "ended_utc": None}]
    fx.write_blocks(rec, open_, {"s": "x", "p1": "x", "p2": "x"})
    with pytest.raises(t3.RefusedError, match="R8"):
        t3.blocks_record(rec)
    cut = [*made["attempts"][:-1], fx.attempt("x2", {a: Path("/r") for a in common.ARMS}, cut=1)]
    fx.write_blocks(rec, cut, {"s": "x", "p1": "x", "p2": "x"})
    with pytest.raises(t3.RefusedError, match="R8"):
        t3.blocks_record(rec)
    fx.write_blocks(rec, made["attempts"], {"x1": "never"})
    with pytest.raises(t3.RefusedError, match="primary"):
        t3.blocks_record(rec)


def _broken_copy(made: dict[str, Any], tmp: Path, change: Any) -> t3.Block:  # noqa: ANN401
    src = Path(made["attempts"][0]["runs"]["A2"])
    dst = fx.copy_run(src, tmp / "run")
    change(dst)
    corpus = made["sets"] / "fresh-v2-x1"
    runs = {"A2": t3.T.Run.read(dst, any_count=True)}
    return t3.Block("x1", corpus, runs, t3.T.set_facts(corpus), t3.set_data(corpus))


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [("seed", 1, "seed"), ("reviewer_kind", "generalist", "reviewer_kind"), ("lanes", 2, "lanes")],
)
def test_a_run_that_is_not_its_block_s_and_arm_s_is_refused(
    made: dict[str, Any],
    tmp_path: Path,
    field: str,
    value: Any,
    match: str,  # noqa: ANN401
) -> None:
    def change(d: Path) -> None:
        cfg = json.loads((d / "instrument.json").read_text())
        cfg[field] = value
        (d / "instrument.json").write_text(json.dumps(cfg))

    block = _broken_copy(made, tmp_path, change)
    with pytest.raises(t3.RefusedError, match=match):
        t3.check_run(block, "A2", None, any_count=True)


def test_a_review_line_with_another_arm_s_rubric_digest_voids_the_block(
    made: dict[str, Any], tmp_path: Path
) -> None:
    def change(d: Path) -> None:
        text = (d / "events.jsonl").read_text()
        for role, digest in common.RUBRIC_SHA256["A2"].items():
            text = text.replace(digest, common.RUBRIC_SHA256["A1"][role])
        (d / "events.jsonl").write_text(text)

    block = _broken_copy(made, tmp_path, change)
    with pytest.raises(t3.RefusedError, match="void"):
        t3.check_run(block, "A2", None, any_count=True)


def test_a_run_with_another_corpus_than_set_filled_s_is_refused(
    made: dict[str, Any], tmp_path: Path
) -> None:
    block = _broken_copy(made, tmp_path, lambda d: None)
    fills = {"sets": {"manifests": {"fresh-v2-x1": "0" * 64}}}
    with pytest.raises(t3.RefusedError, match="Set filled"):
        t3.check_run(block, "A2", fills, any_count=True)


def test_the_knowledge_check_rests_on_the_tree_pins_when_no_record_is_kept(
    made: dict[str, Any], tmp_path: Path
) -> None:
    block = _broken_copy(made, tmp_path, lambda d: None)
    assert t3.check_knowledge(common.REPO, block, "A2")["rests_on_the_launch_tree_pins"]


def test_the_expected_knowledge_is_the_pinned_trees_files_for_the_arm_and_role() -> None:
    a2 = t3.expected_knowledge(common.REPO, "A2", "electrical")
    b = t3.expected_knowledge(common.REPO, "B", "electrical")
    assert set(a2) == {
        "knowledge/cross/standards.md",
        "knowledge/electrical/standards.md",
        "knowledge/electrical/skill.md",
    }
    assert set(b) == {"knowledge/cross/standards.md"}
    assert a2["knowledge/cross/standards.md"] == b["knowledge/cross/standards.md"]


@pytest.fixture(scope="module")
def s_made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Block ``s`` run for real over a set of the instrument's ``standard`` class, by every arm."""
    base = tmp_path_factory.mktemp("block-s")
    sets = fx.write_sets(base / "sets", [common.BLOCK_CORPUS["s"]])
    corpus = sets / common.BLOCK_CORPUS["s"]
    seed = common.BLOCK_SEED["s"]
    runs = {arm: fx.real_run(corpus, base / arm, seed, arm, BY_ARM[arm]) for arm in common.ARMS}
    return {"sets": sets, "attempt": fx.attempt("s", runs)}


@pytest.fixture(scope="module")
def block_s(s_made: dict[str, Any]) -> t3.Block:
    return t3.read_block("s", s_made["attempt"], s_made["sets"], {})


def test_the_frozen_per_item_refuses_the_standard_class_and_the_own_path_scores_it(
    block_s: t3.Block,
) -> None:
    for arm in common.ARMS:
        # The rows are the instrument's own, written under the class it loaded.
        assert {r["error_class"] for r in block_s.runs[arm].rows} == {t3.STANDARD}, arm
        t3.check_run(block_s, arm, None, any_count=True)
    with pytest.raises(t3.TallyError):
        t3.T.per_item(block_s.runs["A2"], block_s.facts, "paired")
    cells = t3.Cells.at(common.REPO)
    scored = {p["item"]: p for p in t3.score(block_s, "A2", cells)}
    # e1's review cites EA-9 (the Section 1 line), in the standard class's common cell
    assert scored["e1"]["R_common"] and scored["c1"]["R_common"]  # D25 is a control Section 2 item
    assert not scored["f1"]["R_common"]  # its twin's review cites the same item
    assert "R_strict" not in scored["e1"] and scored["e1"]["class"] == t3.STANDARD
    generalist = {p["item"]: p for p in t3.score(block_s, "B", cells)}
    # B's cell is the Section 1 line alone: A7 and MA-10 are, ES-32 is not
    assert generalist["c1"]["R_common"] and generalist["k1"]["R_common"]
    assert not generalist["e1"]["R_common"]
    assert t3.STANDARD == common.STANDARD_CLASS


def test_the_class_s_own_path_refuses_a_run_whose_rows_are_not_of_the_class(
    made: dict[str, Any],
) -> None:
    x1 = t3.read_block("x1", made["attempts"][0], made["sets"], {})
    as_s = t3.Block("s", x1.corpus, x1.runs, x1.facts, x1.law)
    with pytest.raises(t3.TallyError, match="a class other than standard"):
        t3.score(as_s, "A2", t3.Cells.at(common.REPO))


def test_the_tally_scores_block_s_by_its_own_path_into_the_class_rule(
    made: dict[str, Any], s_made: dict[str, Any], tmp_path: Path
) -> None:
    sets = tmp_path / "sets"
    shutil.copytree(made["sets"], sets)
    name = common.BLOCK_CORPUS["s"]
    shutil.copytree(s_made["sets"] / name, sets / name)
    records = tmp_path / "records"
    attempts = [*made["attempts"], s_made["attempt"]]
    fx.write_blocks(records, attempts, {"p1": "fresh-v1c failed", "p2": "same"})
    got = t3.tally(
        records,
        sets,
        made["practice"],
        None,
        {},
        200,
        practice_pinned=False,
        fills=None,
        any_count=True,
        tuning=made["tuning"],
    )
    assert "s" in got["blocks"] and set(got["not_run"]) == {"p1", "p2"}
    cls = got["secondary"]["standard"]
    # A2 credits e1 (EA-9), which B misses; B credits k1 (MA-10), which A2 passed.
    assert {k: cls["halves"]["common"][k] for k in ("n_A2", "n_B", "d")} == {
        "n_A2": 1,
        "n_B": 1,
        "d": 0,
    }
    assert cls["acceptance"]["raw_of_10"] == {"A2": 3, "B": 3}  # f1's twin fails in both
    assert not cls["catch_half_holds"] and not cls["class_rule_holds"]
    assert "the class was not measured" not in got["decision"]["class_clause"]
    assert got["decision"]["class_clause"].startswith(
        "On the domain-standard class (10 pairs, secondary), the fixed specialists credited 1 "
    )


def test_the_standard_cell_is_section_2_whole_with_the_section_1_line_and_b_s_is_the_line() -> None:
    cells = t3.Cells.at(common.REPO)
    cell = t3.common_cell("paired", "electrical", "standard", cells)
    assert "EA-9" in cell and "ES-1" in cell and "ES-34" in cell and "EH-1" not in cell
    assert t3.common_cell("generalist", "electrical", "standard", cells) == ("EA-9",)
    assert t3.common_cell("paired", "control", "unit", cells) == ("D25", "D26", "A7")
    assert t3.strict_cell("paired", "control", "unit") == ("D25", "D26")


# ---- the statistics ------------------------------------------------------------------------------


def test_a_stratified_draw_resamples_each_stratum_within_itself_in_order() -> None:
    strata = [[0, 1, 2], [3, 4], [5]]
    rng = random.Random(13)
    for _ in range(50):
        drawn = t3.strat_draw(rng, strata)
        assert len(drawn) == 6
        assert set(drawn[:3]) <= {0, 1, 2} and set(drawn[3:5]) <= {3, 4} and drawn[5] == 5


def test_the_intervals_are_seeded_and_repeat() -> None:
    pairs = [(1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (0.0, 0.0)] * 3
    strata = [list(range(0, 4)), list(range(4, 8)), list(range(8, 12))]
    assert t3.j_strat(pairs, strata, 300) == t3.j_strat(pairs, strata, 300)
    other = [(1.0, 1.0)] * 12
    lo, hi = t3.contrast_strat(other, pairs, strata, 300)
    assert lo <= 1.0 <= hi or lo > 0


def test_the_noise_band_scales_with_the_root_of_the_pairs() -> None:
    assert t3.noise_band(40) == 0.175 and t3.noise_band(120) == round(0.175 * (1 / 3) ** 0.5, 4)


@pytest.mark.parametrize(
    ("interval", "row"),
    [
        ([0.01, 0.3], "1"),
        ([-0.14, 0.2], "2"),
        ([-0.15, 0.2], "3b"),
        ([-0.3, -0.01], "3a"),
        ([-0.3, 0.0], "3b"),
        ([-0.1, -0.02], "2"),
    ],
)
def test_the_row_follows_q2_and_q3(interval: list[float], row: str) -> None:
    assert t3.row_of(interval) == row


def test_the_fix_s_sentence_and_its_guards() -> None:
    guards = t3.q1_guards(
        {"A": 10, "R_common": 50, "R_strict": 40}, {"A": 9, "R_common": 57, "R_strict": 44}
    )
    assert guards == {"A": True, "R under the common rule": False, "R under the strict rule": True}
    assert t3.fix_sentence([0.1, 0.3], guards)["sentence"] == "a guard failed"
    assert t3.fix_sentence([0.1, 0.3], {k: True for k in guards})["sentence"] == "met"
    assert t3.fix_sentence([-0.3, -0.1], guards)["sentence"] == "worse"
    assert t3.fix_sentence([-0.1, 0.1], guards)["sentence"] == "not shown"


def test_q4_tailoring_and_possible_tailoring() -> None:
    before = [(1.0, 1.0)] * 40
    after = [(0.0, 0.0)] * 60 + [(1.0, 1.0)] * 60
    got = t3.q4(before, after, 300)
    assert got["tailoring"] and not got["possible_tailoring"]
    near = [(1.0, 1.0)] * 30 + [(0.0, 0.0)] * 10
    mixed = [(1.0, 1.0)] * 70 + [(0.0, 0.0)] * 50
    got = t3.q4(near, mixed, 300)
    assert got["drop"] > 0.15 and (got["tailoring"] or got["possible_tailoring"])


@pytest.mark.parametrize(
    ("status", "verdict", "own", "way", "credited"),
    [
        ("unflawed", "pass", False, 1, True),
        ("unflawed", "fail", True, 2, False),
        ("undecided", "pass", False, 1, True),
        ("undecided", "fail", False, 1, False),
        ("undecided", "fail", False, 2, True),
        ("undecided", "pass", False, 2, False),
        ("flawed", "fail", True, 1, True),
        ("flawed", "fail", False, 1, False),
        ("flawed", "pass", False, 2, False),
    ],
)
def test_the_corrected_a_reading_in_both_ways(
    status: str, verdict: str, own: bool, way: int, credited: bool
) -> None:
    assert t3.corrected_a(status, verdict, own, way) is credited


def _cls_items(
    a2: list[int], b: list[int], a2_loc: list[int], b_loc: list[int], accept: tuple[int, int]
) -> dict[str, list[dict[str, Any]]]:
    def arm(r: list[int], loc: list[int], acc: int) -> list[dict[str, Any]]:
        return [
            {
                "item": f"s{k + 1:02d}",
                "R_common": bool(r[k]),
                "R_locating": bool(loc[k]),
                "A": k < acc,
                "rev_open": False,
                "twin_open": False,
                "raw_reject": True,
                "sheet_flaw_rejection": False,
            }
            for k in range(10)
        ]

    return {
        "A2": arm(a2, a2_loc, accept[0]),
        "A1": arm(a2, a2_loc, accept[0]),
        "B": arm(b, b_loc, accept[1]),
    }


def test_the_class_rule_needs_both_halves_under_both_rules() -> None:
    r = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    zero = [0] * 10
    holds = t3.standard_class(_cls_items(r, zero, r, zero, (8, 9)), None, 200)
    assert holds["halves"]["common"]["d"] == 4 and holds["class_rule_holds"]
    assert holds["acceptance"]["counted"].startswith("raw")
    weak = t3.standard_class(
        _cls_items(r, zero, [1, 1, 0, 0, 0, 0, 0, 0, 0, 0], zero, (8, 9)), None, 200
    )
    assert not weak["catch_half_holds"] and not weak["class_rule_holds"]
    gap = t3.standard_class(_cls_items(r, zero, r, zero, (6, 9)), None, 200)
    assert gap["catch_half_holds"] and not gap["acceptance_half_holds"]


def test_the_class_rule_s_acceptance_half_in_both_ways_when_the_reading_is_reliable() -> None:
    r = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    zero = [0] * 10
    statuses = ["flawed", "flawed", "undecided"] + ["unflawed"] * 7
    reading = {
        "reliability": "reliable",
        "standard_twins": [{"item": f"s{k + 1:02d}", "status": s} for k, s in enumerate(statuses)],
    }
    got = t3.standard_class(_cls_items(r, zero, r, zero, (5, 9)), reading, 200)
    assert (
        got["acceptance"]["ways"]["way 1"]["k"] == 8
        and got["acceptance"]["ways"]["way 2"]["k"] == 7
    )
    assert "of all 10" in t3.class_clause(got) and "way 1" in t3.class_clause(got)


def test_r8_the_cli_refuses_without_the_block_record(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "tally3.py"),
            "--records",
            str(tmp_path),
            "--sets",
            str(tmp_path),
            "--out",
            str(tmp_path / "t.json"),
            "--practice-unpinned",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=common.REPO,
    )
    assert done.returncode == 2 and "R8" in done.stdout and not (tmp_path / "t.json").exists()


def test_the_practice_runs_are_held_to_r_law_01_s_digests(made: dict[str, Any]) -> None:
    with pytest.raises(t3.RefusedError, match="practice run"):
        t3.practice_items(made["practice"], made["tuning"], pinned=True)
    with pytest.raises(t3.RefusedError):
        t3.practice_items({"round-1": made["practice"]["round-1"]}, made["tuning"], pinned=False)


def test_the_cli_writes_a_test_s_tally_labelled_never_a_result(
    made: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "t.json"
    sets = tmp_path / "sets"
    shutil.copytree(made["sets"], sets)
    args = [
        sys.executable,
        "-I",
        str(HERE / "tally3.py"),
        "--records",
        str(made["records"]),
        "--sets",
        str(sets),
        "--out",
        str(out),
        "--practice-unpinned",
        "--any-count",
        "--draws",
        "100",
        "--fills",
        str(tmp_path / "fills.json"),
        "--tuning",
        str(made["tuning"]),
    ]
    (tmp_path / "fills.json").write_text("{}")
    for label, path in made["practice"].items():
        args += ["--practice", f"{label}={path}"]
    done = subprocess.run(args, capture_output=True, text=True, check=False, cwd=common.REPO)
    assert done.returncode == 0, done.stdout
    assert json.loads(out.read_text())["label"] == "A TEST ON FIXTURES: never a result"
