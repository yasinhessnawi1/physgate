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


def holds(call: Any) -> Any:  # noqa: ANN401
    """The call returns; one of this module's refusals fails on an assertion."""
    return fx.holds(call, t3.RefusedError, common.RefusedError)


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
    # It marks that a tally ran: no withdrawal recorded later is taken (R8).
    mark = made["records"] / common.TALLIES
    assert json.loads(mark.read_text().splitlines()[0])["withdrawn"] == 0
    mark.unlink()


# ---- the decision's inputs held (the practice figure, the reading, the draws, the frozen tally) -


def test_a_practice_figure_other_than_the_criteria_s_is_refused() -> None:
    t3.check_practice_figure(0.775)
    t3.check_practice_figure(0.77504)
    with pytest.raises(t3.RefusedError, match="0.775"):
        t3.check_practice_figure(0.75)


def test_the_practice_figure_on_records_not_at_their_digests_is_not_computable(
    made: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    code = t3.main(["practice-figure", "--practice", f"round-1={made['practice']['round-1']}"])
    assert code == 4 and "not computable" in capsys.readouterr().out


def test_a_tally_outside_a_test_needs_the_reading(tmp_path: Path) -> None:
    with pytest.raises(t3.RefusedError, match="reading"):
        t3.tally(tmp_path, tmp_path, {}, None, {}, practice_pinned=True)


def test_a_tally_outside_a_test_takes_the_criteria_s_draws(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--records", str(tmp_path), "--sets", str(tmp_path), "--out", str(tmp_path / "t.json")]
    assert t3.main([*argv, "--draws", "100"]) == 2
    assert "draws" in capsys.readouterr().out


def test_the_frozen_tally_is_held_to_its_digest_when_the_tally_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(common, "RPG02_TALLY_SHA256", "0" * 64)
    with pytest.raises(t3.RefusedError, match="tally.py"):
        t3.tally(tmp_path, tmp_path, {}, None, {}, practice_pinned=False)


def test_the_knowledge_is_checked_from_the_block_record_s_review_roots(
    made: dict[str, Any], tmp_path: Path
) -> None:
    first = made["attempts"][0]
    scratch = fx.copy_run(Path(first["scratch"]["A2"]), tmp_path / "scratch")
    line = next(
        json.loads(x)
        for x in (Path(first["runs"]["A2"]) / "events.jsonl").read_text().splitlines()
        if '"review_ran"' in x
    )
    packet = common.lane_roots(scratch)[0] / line["result"]["session_id"] / "packet.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(json.dumps({"knowledge_sha256": {"knowledge/cross/standards.md": "0" * 64}}))
    records = tmp_path / "records"
    attempts = [
        {**first, "scratch": {**first["scratch"], "A2": str(scratch)}},
        *made["attempts"][1:],
    ]
    fx.write_blocks(records, attempts, {"s": "x", "p1": "x", "p2": "x"})
    with pytest.raises(t3.RefusedError, match="knowledge"):
        run_tally({**made, "records": records})


def test_a_set_not_at_set_filled_s_digest_is_refused_though_its_run_recorded_it(
    made: dict[str, Any], tmp_path: Path
) -> None:
    corpus = tmp_path / "fresh-v2-x1"
    shutil.copytree(made["sets"] / "fresh-v2-x1", corpus)
    recorded = common.sha256_file(corpus / "MANIFEST.json")
    (corpus / "MANIFEST.json").write_text((corpus / "MANIFEST.json").read_text() + "\n")
    block = _broken_copy(made, tmp_path, lambda d: None)
    block = t3.Block("x1", corpus, block.runs, block.facts, block.law)
    fills = {"sets": {"manifests": {"fresh-v2-x1": recorded}}}
    with pytest.raises(t3.RefusedError, match="Set filled"):
        t3.check_run(block, "A2", fills, any_count=True)


def test_each_block_s_attempts_and_the_chosen_one_s_deviations_are_carried_beside_the_gate(
    made: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    r6 = "the gate's records differ (R6): a deviation for the gate's figures"
    void = {**made["attempts"][0], "valid": False, "void_causes": ["usage limit"]}
    chosen = {**made["attempts"][0], "attempt": 2, "deviations": [r6]}
    fx.write_blocks(
        records, [void, chosen, *made["attempts"][1:]], {"s": "x", "p1": "x", "p2": "x"}
    )
    gate = run_tally({**made, "records": records})["secondary"]["gate"]
    assert gate["attempts"]["x1"]["chosen"] == 2 and gate["attempts"]["x1"]["deviations"] == [r6]
    assert gate["attempts"]["x1"]["others"] == [
        {
            "attempt": 1,
            "valid": False,
            "void_causes": ["usage limit"],
            "deviation": None,
            "classified": None,
        }
    ]


NOT_RUN = {"s": "x", "p1": "x", "p2": "x"}
#: A correction that touches block x1, as "Commits corrected" adds one.
CORRECTS_X1 = {
    "id": "c1",
    "R": "f" * 40,
    "R_K": "e" * 40,
    "blocks": {"x1": {"attempt": 1, "test": "experiments/R-PG-03/test_checks.py"}},
}
#: x1's first attempt classified an instrument defect with it.
MARK = {"route": "instrument defect", "correction": "c1", "recorded_utc": "2026-11-05T10:30:00Z"}
IMPOSSIBLE = {
    "route": "anything else impossible as specified",
    "recorded_utc": "2026-11-05T10:30:00Z",
}
CLEAN = {"tests": {"experiments/R-PG-03/test_checks.py": "passes"}, "utc": "2026-11-06T00:00:00Z"}


def check_record(records: Path, utc: str) -> Path:
    """CORRECTS_X1's passing check record, made at ``utc``."""
    check = records / "corrections" / "c1" / "check.json"
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text(json.dumps({"passed": True, "entry": CORRECTS_X1, "checked_utc": utc}))
    return check


def impossible(block: str) -> dict[str, Any]:
    """A block's first attempt, a deviation classified impossible as specified."""
    row = {"block": block, "attempt": 1, "valid": False, "deviation": {"causes": ["x"]}}
    return {**row, "classified": IMPOSSIBLE}


def test_the_tally_uses_the_corrected_attempt_of_a_touched_block_and_lists_both(
    made: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    first = {**made["attempts"][0], "classified": MARK}
    second = {**made["attempts"][0], "attempt": 2}
    fx.write_blocks(records, [first, second, *made["attempts"][1:]], NOT_RUN)
    gate = run_tally({**made, "records": records})["secondary"]["gate"]
    assert gate["attempts"]["x1"]["chosen"] == 2
    assert gate["attempts"]["x1"]["others"] == [
        {"attempt": 1, "valid": True, "void_causes": [], "deviation": None, "classified": MARK}
    ]
    check_record(records, "2026-11-05T11:00:00Z")  # made after every block ended
    assert t3.blocks_record(records, {"corrections": [CORRECTS_X1]})["chosen"]["x1"] == second


def test_a_block_not_taken_is_not_tallied_and_the_decisions_it_feeds_are_not_taken(
    made: dict[str, Any], tmp_path: Path
) -> None:
    # §11: anything else impossible as specified; the decisions it feeds are not taken.
    records = tmp_path / "records"
    fx.write_blocks(records, [impossible("x1"), *made["attempts"][1:]], NOT_RUN)
    rec = json.loads((records / "blocks.json").read_text())
    got = holds(lambda: run_tally({**made, "records": records}))
    whole = holds(lambda: run_tally(made))
    # The primary over the pairs present, labelled with their count.
    corpora = {p["corpus"] for p in got["per_item"]["A2"]}
    assert got["primary"]["pairs"] == len(got["per_item"]["A2"]) < whole["primary"]["pairs"]
    assert "fresh-v2-x1" not in corpora and "fresh-v2-x2" in corpora
    assert got["not_taken"] == {"x1": 1}
    assert all(q["taken"] is False for q in got["criteria"].values())
    assert all(q["taken"] is True for q in whole["criteria"].values())
    assert "not taken" in got["decision"] and "row" not in got["decision"]
    assert got["decision"]["class_clause"] == whole["decision"]["class_clause"]
    # Q4's readings beside it rest on the same pairs.
    assert got["q4_set_adjusted"]["taken"] is False and "not taken" in got["q4_sheet_matched"]
    # Any primary block, not x1 alone.
    rec["attempts"] = [*(a for a in made["attempts"] if a["block"] != "z2"), impossible("z2")]
    (records / "blocks.json").write_text(json.dumps(rec))
    assert "not taken" in holds(lambda: run_tally({**made, "records": records}))["decision"]
    # A block s or p1 not taken: the class was not measured; the sheet-matched Q4 is not taken.
    rec["not_run"] = {"p2": "same"}
    rec["attempts"] = [*made["attempts"], impossible("s"), impossible("p1")]
    (records / "blocks.json").write_text(json.dumps(rec))
    got = holds(lambda: run_tally({**made, "records": records}))
    assert "not measured" in got["decision"]["class_clause"]
    assert isinstance(got["q4_sheet_matched"], dict) and "not taken" in got["q4_sheet_matched"]
    assert got["decision"]["row"]
    rec["not_run"] = {"s": "x", "p1": "x"}  # p2 alone not taken
    rec["attempts"] = [*made["attempts"], impossible("p2")]
    (records / "blocks.json").write_text(json.dumps(rec))
    got = holds(lambda: run_tally({**made, "records": records}))
    assert isinstance(got["q4_sheet_matched"], dict) and "not taken" in got["q4_sheet_matched"]
    # Both blocks of author pair X not taken: its figures and its comparison are left out.
    rec["not_run"] = NOT_RUN
    rest = [a for a in made["attempts"] if a["block"] not in ("x1", "x2")]
    rec["attempts"] = [*rest, impossible("x1"), impossible("x2")]
    (records / "blocks.json").write_text(json.dumps(rec))
    got = holds(lambda: run_tally({**made, "records": records}))
    assert sorted(got["secondary"]["per_author_pair"]) == ["Y", "Z"]
    compared = got["secondary"]["author_pairs_compared"]["A2_minus_B"]
    assert sorted(compared["intervals"]) == ["Y", "Z"]
    assert compared["comparisons"] == "2 per contrast, 4 in all, uncorrected"


def test_a_block_ended_after_a_correction_s_check_needs_its_result_and_not_touched(
    made: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    fx.write_blocks(records, made["attempts"], NOT_RUN)
    fills = {"corrections": [CORRECTS_X1]}
    first = {**made["attempts"][0], "classified": MARK}
    second = {**made["attempts"][0], "attempt": 2}
    fx.write_blocks(records, [first, second, *made["attempts"][1:]], NOT_RUN)
    fx.refuses(
        common.RefusedError,
        "no passing correction-check record",
        lambda: t3.blocks_record(records, fills),
    )
    # Every tallied attempt ended after it (the fixture's end: 5.11 10:00 UTC).
    check_record(records, "2026-11-05T09:00:00Z")
    fx.refuses(
        t3.RefusedError,
        "carries no result of its tests",
        lambda: t3.blocks_record(records, fills),
    )
    for a in [second, *made["attempts"][1:]]:
        where = records / "blocks" / f"{a['block']}-{a['attempt']}"
        where.mkdir(parents=True)
        (where / "touched.json").write_text(json.dumps({"c1": CLEAN}))
    assert holds(lambda: t3.blocks_record(records, fills))["chosen"]["x1"] == second
    touched = records / "blocks" / "y1-1" / "touched.json"
    failing = {**CLEAN, "tests": {"experiments/R-PG-03/test_checks.py": "fails"}}
    touched.write_text(json.dumps({"c1": failing}))
    fx.refuses(
        t3.RefusedError,
        "y1's attempt 1 ended after correction c1",
        lambda: t3.blocks_record(records, fills),
    )
    # A check made after they all ended asks nothing of them.
    check_record(records, "2026-11-05T11:00:00Z")
    assert holds(lambda: t3.blocks_record(records, fills))["chosen"]["y1"]


def test_the_tally_holds_the_check_record_and_the_touched_results_as_l2_does(
    made: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    first = {**made["attempts"][0], "classified": MARK}
    second = {**made["attempts"][0], "attempt": 2}
    fx.write_blocks(records, [first, second, *made["attempts"][1:]], NOT_RUN)
    fills = {"corrections": [CORRECTS_X1]}
    other = {**CORRECTS_X1, "R_K": "d" * 40}  # a record of another entry under that id
    check = check_record(records, "2026-11-05T09:00:00Z")
    check.write_text(
        json.dumps({"passed": True, "entry": other, "checked_utc": "2026-11-05T09:00Z"})
    )
    fx.refuses(
        common.RefusedError,
        "no passing correction-check record",
        lambda: t3.blocks_record(records, fills),
    )
    check_record(records, "2026-11-05T09:00:00Z")
    for a in [second, *made["attempts"][1:]]:  # a result with no tests is no result
        where = records / "blocks" / f"{a['block']}-{a['attempt']}"
        where.mkdir(parents=True, exist_ok=True)
        (where / "touched.json").write_text(
            json.dumps({"c1": {"touched": False, "utc": "2026-11-06T00:00:00Z"}})
        )
    fx.refuses(
        t3.RefusedError, "carries no result of its tests", lambda: t3.blocks_record(records, fills)
    )
    # A result made before the attempt ended is no result of its records.
    for a in [second, *made["attempts"][1:]]:
        where = records / "blocks" / f"{a['block']}-{a['attempt']}"
        early = {**CLEAN, "utc": "2026-11-05T09:30:00Z"}  # the fixture's end: 5.11 10:00 UTC
        (where / "touched.json").write_text(json.dumps({"c1": early}))
    fx.refuses(
        t3.RefusedError, "carries no result of its tests", lambda: t3.blocks_record(records, fills)
    )


def test_the_reading_s_lines_are_taken_with_the_fills_the_tally_takes(made: dict[str, Any]) -> None:
    import reality as rl

    named = {"corrections": [CORRECTS_X1]}  # x1 named, never classified: the tally refuses
    fx.refuses(
        common.RefusedError,
        "named by the corrections",
        lambda: rl.extract(made["records"], made["sets"], named),
    )


def test_a_reading_of_other_attempts_than_the_tally_s_is_refused(
    made: dict[str, Any], tmp_path: Path
) -> None:
    reading = tmp_path / "reading.json"
    reading.write_text(json.dumps({"attempts": {"x1": 2}, "reliability": "unchecked"}))
    fx.refuses(
        t3.RefusedError,
        "other attempts than the ones tallied",
        lambda: t3.tally(
            made["records"],
            made["sets"],
            made["practice"],
            reading,
            {},
            200,
            practice_pinned=False,
            any_count=True,
            tuning=made["tuning"],
        ),
    )


def test_the_tally_refuses_while_a_block_a_correction_names_lacks_its_corrected_attempt(
    made: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    first = {**made["attempts"][0], "classified": MARK}
    fx.write_blocks(records, [first, *made["attempts"][1:]], NOT_RUN)
    with pytest.raises(t3.RefusedError, match=r"x1 has 0 valid attempt\(s\) at its corrected"):
        t3.blocks_record(records, {"corrections": [CORRECTS_X1]})
    # Named and never classified, the tally refuses, as the launch does.
    named = r"named by the corrections \['c1'\], and its attempts are classified with \[\]"
    fx.refuses(
        common.RefusedError, named, lambda: run_tally(made, fills={"corrections": [CORRECTS_X1]})
    )
    # Classified with a correction that no fill names.
    second = {**made["attempts"][0], "attempt": 2}
    fx.write_blocks(records, [first, second, *made["attempts"][1:]], NOT_RUN)
    with pytest.raises(common.RefusedError, match=r"classified with \['c1'\]"):
        t3.blocks_record(records, {})


# ---- §6.4 item 10: blocks p1 and p2 against R-PG-02's published runs ----------------------------


def _p_item(item: str, review: str, r: bool, a: bool) -> dict[str, Any]:
    return {
        "item": item,
        "review": review,
        "twin_review": "pass" if a else "fail",
        "R_common": r,
        "A": a,
        "rev_open": False,
        "twin_open": False,
        "raw_reject": review == "fail",
        "sheet_flaw_rejection": False,
    }


def test_the_p_blocks_compare_r_and_a_per_item_and_refuse_an_item_with_no_published_row() -> None:
    def scored(extra: list[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        ids = [f"a{k:02d}" for k in range(1, 41)] + extra
        items = [_p_item(i, "fail", k % 2 == 0, k % 3 == 0) for k, i in enumerate(ids)]
        half = len(items) // 2
        return {
            "p1": dict.fromkeys(common.ARMS, items[:half]),
            "p2": dict.fromkeys(common.ARMS, items[half:]),
        }

    got = t3._p_blocks(scored([]), 50)
    assert got is not None
    rows = got["per_item_against_r_pg_02"]
    assert len(rows) == 120 and {"R_common", "A", "review", "twin_review"} <= set(rows[0])
    assert all(len(r["R_common"]) == 2 and len(r["A"]) == 2 for r in rows)
    with pytest.raises(t3.RefusedError, match="published"):
        t3._p_blocks(scored(["a99"]), 50)


# ---- §8's labels and their boundaries ------------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "row"),
    [
        ([0.0, 0.3], "2"),  # Q2 needs the interval wholly above 0
        ([0.0001, 0.3], "1"),
        ([-0.1499, 0.0], "2"),
        ([-0.15, -0.0001], "3a"),
        ([-0.15, 0.0], "3b"),  # 3a needs the interval wholly below 0
    ],
)
def test_the_row_at_its_boundaries(interval: list[float], row: str) -> None:
    assert t3.row_of(interval) == row


@pytest.mark.parametrize(
    ("a2", "a1", "holds"),
    [
        ({"A": 9, "R_common": 50, "R_strict": 40}, {"A": 9, "R_common": 56, "R_strict": 46}, True),
        ({"A": 9, "R_common": 50, "R_strict": 40}, {"A": 9, "R_common": 57, "R_strict": 40}, False),
        ({"A": 9, "R_common": 50, "R_strict": 40}, {"A": 9, "R_common": 50, "R_strict": 47}, False),
        ({"A": 8, "R_common": 50, "R_strict": 40}, {"A": 9, "R_common": 50, "R_strict": 40}, False),
    ],
    ids=["a-gap-of-six-and-a-equal", "a-common-gap-of-seven", "a-strict-gap-of-seven", "a-below"],
)
def test_q1_s_guards_at_their_boundaries(
    a2: dict[str, int], a1: dict[str, int], holds: bool
) -> None:
    assert all(t3.q1_guards(a2, a1).values()) is holds


@pytest.mark.parametrize(
    ("a2_r", "catch"),
    [([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], True), ([1, 1, 0, 0, 0, 0, 0, 0, 0, 0], False)],
    ids=["d-of-three", "d-of-two"],
)
def test_the_class_rule_s_catch_half_at_d_of_three(a2_r: list[int], catch: bool) -> None:
    zero = [0] * 10
    got = t3.standard_class(_cls_items(a2_r, zero, a2_r, zero, (9, 9)), None, 50)
    assert got["halves"]["common"]["d"] == sum(a2_r) and got["catch_half_holds"] is catch


@pytest.mark.parametrize(("accepted", "holds"), [((7, 9), True), ((6, 9), False)])
def test_the_class_rule_s_acceptance_half_at_a_gap_of_two(
    accepted: tuple[int, int], holds: bool
) -> None:
    r = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    zero = [0] * 10
    got = t3.standard_class(_cls_items(r, zero, r, zero, accepted), None, 50)
    assert got["acceptance_half_holds"] is holds


def test_the_class_rule_matches_the_arms_by_item() -> None:
    r = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    b = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1]  # B credits s10, which A2 misses
    items = _cls_items(r, b, r, b, (8, 9))
    shuffled = {**items, "B": list(reversed(items["B"]))}
    want = t3.standard_class(items, None, 50)
    got = t3.standard_class(shuffled, None, 50)
    assert got["halves"] == want["halves"] and got["acceptance"] == want["acceptance"]


def test_the_class_clause_gives_each_way_only_where_the_ways_differ() -> None:
    r = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    zero = [0] * 10
    same = {
        "reliability": "reliable",
        "standard_twins": [{"item": f"s{k:02d}", "status": "unflawed"} for k in range(1, 11)],
    }
    clause = t3.class_clause(t3.standard_class(_cls_items(r, zero, r, zero, (5, 9)), same, 50))
    assert (
        "way 1" not in clause and "of its 10 correct twins that the reading does not mark" in clause
    )
    statuses = ["flawed", "undecided"] + ["unflawed"] * 8
    differ = {
        "reliability": "reliable",
        "standard_twins": [{"item": f"s{k + 1:02d}", "status": s} for k, s in enumerate(statuses)],
    }
    clause = t3.class_clause(t3.standard_class(_cls_items(r, zero, r, zero, (5, 9)), differ, 50))
    assert "way 1" in clause and "way 2" in clause


@pytest.mark.parametrize(
    ("row", "readings", "fix", "robust"),
    [
        ("2a", {"locating": "2"}, {"strict": "met"}, (True, True)),
        ("2b", {"locating": "3b", "corrected-A way 1": "2"}, {"strict": "met"}, (False, True)),
        ("3a", {"locating": "3a"}, {"strict": "not shown"}, (True, False)),
    ],
)
def test_the_robustness_labels(
    row: str, readings: dict[str, str], fix: dict[str, str], robust: tuple[bool, bool]
) -> None:
    got = t3.robust_labels({"row": readings, "fix": fix}, row, {"sentence": "met"})
    assert (got["row_is_robust"], got["fix_is_robust"]) == robust
    base = "2" if row in ("2a", "2b") else row
    assert got["row_readings_that_differ"] == [k for k, v in readings.items() if v != base]


@pytest.mark.parametrize(
    ("flags", "interval", "point", "label"),
    [
        (True, [-0.1, 0.2], 0.1, "a shift of the set, not shown to be tailoring"),
        (True, [0.0, 0.2], 0.15, "a shift of the set, not shown to be tailoring"),
        (True, [0.01, 0.3], 0.1, None),
        (True, [-0.1, 0.4], 0.16, None),
        (False, [-0.1, 0.2], 0.1, None),
    ],
)
def test_q4_s_set_adjusted_label(
    flags: bool, interval: list[float], point: float, label: str | None
) -> None:
    q4_main = {"tailoring": flags, "possible_tailoring": False}
    assert t3.set_adjusted_label(q4_main, {"point": point, "interval": interval}) == label


def test_the_author_pairs_differ_only_where_an_interval_excludes_zero() -> None:
    assert not t3.pairs_differ({"X": [-0.1, 0.1], "Y": [0.0, 0.2], "Z": [-0.3, 0.0]})
    assert t3.pairs_differ({"X": [-0.1, 0.1], "Y": [0.01, 0.2], "Z": [-0.3, 0.0]})
    assert t3.pairs_differ({"X": [-0.2, -0.01], "Y": [0.0, 0.2], "Z": [-0.3, 0.0]})


@pytest.mark.parametrize(
    ("row", "interval", "bracket", "test"),
    [
        ("2a", [-0.1, -0.01], True, True),
        ("2b", [-0.1, 0.0], False, True),
        ("3b", [-0.2, 0.15], False, False),
        ("3b", [-0.2, 0.149], False, True),
    ],
)
def test_row_two_s_bracket_and_row_3b_s_test_of_the_generalist(
    row: str, interval: list[float], bracket: bool, test: bool
) -> None:
    assert t3.row_clauses(row, interval) == (bracket, test)
    contrast = {"J": -0.05, "interval": interval}
    sentence = t3.row_sentence(row, contrast, 2.0, bracket, test)
    if row.startswith("2"):
        assert ("shown worse by less than the margin" in sentence) is bracket
    else:
        assert ("the generalist is shown worse" in sentence) is test
        assert ("the generalist is not shown worse" in sentence) is not test


def test_q4_s_set_adjusted_reading_subtracts_k_s_drop_from_the_fixed_rubrics_drop() -> None:
    before_a2 = [(1.0, 1.0)] * 30 + [(0.0, 1.0)] * 10  # J 0.75
    before_k = [(1.0, 1.0)] * 20 + [(0.0, 1.0)] * 20  # J 0.5
    a2 = [(1.0, 1.0)] * 60 + [(0.0, 1.0)] * 60  # J 0.5
    a1 = [(1.0, 1.0)] * 54 + [(0.0, 1.0)] * 66  # J 0.45
    got = t3.set_adjusted(before_a2, before_k, a2, a1, 200)
    assert got["point"] == round((0.75 - 0.5) - (0.5 - 0.45), 4) == 0.2
    assert got["interval"] == t3.joint_drop_difference(before_a2, before_k, a2, a1, 200)


def test_the_sheet_matched_q4_is_a2_s_drop_from_blocks_p1_and_p2_with_a1_s_beside() -> None:
    def items(r: list[int]) -> list[dict[str, Any]]:
        return [_p_item(f"a{k + 1:02d}", "fail", bool(x), True) for k, x in enumerate(r)]

    scored = {
        "p1": {"A2": items([1] * 20), "A1": items([1] * 10 + [0] * 10), "B": items([0] * 20)},
        "p2": {"A2": items([1] * 20), "A1": items([1] * 10 + [0] * 10), "B": items([0] * 20)},
    }
    a2 = [(1.0, 1.0)] * 30 + [(0.0, 1.0)] * 30
    a1 = [(1.0, 1.0)] * 15 + [(0.0, 1.0)] * 45
    got = t3.sheet_matched_q4(scored, a2, a1, 200)
    assert got is not None
    assert got["q4"]["J_before"] == 1.0 and got["q4"]["J_after"] == 0.5
    assert got["set_adjusted"]["point"] == round((1.0 - 0.5) - (0.5 - 0.25), 4)
    assert t3.sheet_matched_q4({"p1": scored["p1"]}, a2, a1, 200) is None
