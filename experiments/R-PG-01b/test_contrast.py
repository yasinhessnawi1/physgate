"""Tests of contrast.py (§5, R6, §12's stops) on invented runs, and of its statistics.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import contrast as K  # noqa: E402
import testsupport as T  # noqa: E402

# ---- the statistics ----


def test_newcombe_s_method_10_gives_the_paper_s_example() -> None:
    # Newcombe (1998), paired example (36, 12, 2, 0): 0.0569 to 0.3404, as a proportion.
    pairs = [(1, 1)] * 36 + [(1, 0)] * 12 + [(0, 1)] * 2
    found = K.newcombe_paired(pairs)
    n = len(pairs)
    assert round(found["low"] / n, 4) == 0.0569 and round(found["high"] / n, 4) == 0.3404
    assert math.isclose(found["difference"], 10.0)


def test_wilson_gives_the_paper_s_single_proportion_example() -> None:
    low, high = K.wilson(81, 263)
    assert (round(low, 4), round(high, 4)) == (0.2553, 0.3662)


def test_the_exact_mcnemar_test_is_twice_the_smaller_binomial_tail() -> None:
    assert K.mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert K.mcnemar_exact(1, 9) == pytest.approx(2 * 11 / 1024)
    assert K.mcnemar_exact(3, 3) == 1.0 and K.mcnemar_exact(0, 0) == 1.0


def test_cohen_s_kappa_on_two_ratings() -> None:
    assert K.kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert K.kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0
    assert K.kappa([1, 1], [1, 1]) is None


def test_the_bootstrap_draws_are_random_13_and_the_percentiles_interpolate() -> None:
    rng = random.Random(13)
    assert K.draws(5, 2) == [[rng.randrange(5) for _ in range(5)] for _ in range(2)]
    assert K.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert K.percentile([0, 10], 0.25) == 2.5


# ---- invented runs ----

#: (artefact, class, role, expected check, caught by the gate)
ARTEFACTS = [
    ("a1", "unit", "electrical", "units", True),
    ("a2", "magnitude", "control", "magnitude", True),
    ("a3", "equilibrium", "mechanical", "equilibrium", True),
    ("a4", "propagation", "firmware", "propagation", True),
    ("a5", "unit", "mechanical", "units", False),
    ("a6", "magnitude", "electrical", "magnitude", False),
]


def build(tmp: Path, name: str, approved: set[str], twins: set[str], **kw: Any) -> Path:
    """One invented run: ``approved`` artefacts and ``twins`` pass, the rest fail."""
    run = tmp / name
    inj: list[dict[str, Any]] = []
    ctl: list[dict[str, Any]] = []
    rows = []
    for n, (aid, cls, role, check, caught) in enumerate(ARTEFACTS, 1):
        rid, cid = f"r{n:012x}", f"r{n + 100:012x}"
        digest = kw.get("rubric") or C.RUBRIC_SHA256[role]
        verdict = "pass" if aid in approved else kw.get("rejected", {}).get(aid, "fail")
        items = [] if verdict == "pass" else [T.item("X1", "unmet")]
        inj += [T.planned(rid, role), T.ran(rid, verdict, items, rubric=digest)]
        outcome = "fail" if caught else "pass"
        if kw.get("gate_differs") and aid == "a1":
            inj.append(T.gate(rid, (check, outcome), ("thermal", "unchecked")))
        else:
            inj.append(T.gate(rid, (check, outcome)))
        twin = "pass" if aid in twins else "fail"
        ctl += [
            T.planned(cid, role),
            T.ran(cid, twin, [], rubric=digest),
            T.gate(cid, (check, "pass")),
        ]
        rows.append(
            {
                "artefact": aid,
                "review_id": rid,
                "control_id": cid,
                "error_class": cls,
                "expected_check": check,
                "reviewer_verdict": verdict,
                "gate_verdict": "fail" if caught else "pass",
                "gate_blocking": [check] if caught else [],
            }
        )
    T.write_jsonl(run / "results.jsonl", rows)
    T.write_jsonl(run / "events.jsonl", inj)
    T.write_jsonl(run / "controls" / "events.jsonl", ctl)
    return run


def four(tmp: Path, **kw: Any) -> dict[str, tuple[Path, Path | None]]:
    """Arm I approves more of the caught artefacts than arm F, in both rounds."""
    return {
        "I1": (build(tmp, "i1", {"a1", "a2", "a3", "a5"}, {"a1", "a2"}, **kw), None),
        "F1": (build(tmp, "f1", {"a1", "a5"}, {"a1", "a2", "a3"}), None),
        "I2": (build(tmp, "i2", {"a1", "a2", "a4"}, {"a1"}), None),
        "F2": (build(tmp, "f2", {"a2", "a6"}, {"a1", "a2"}), None),
    }


def analyse(specs: dict[str, tuple[Path, Path | None]]) -> dict[str, Any]:
    return K.analyse(specs, {"I": None, "F": None}, any_count=True, resample_count=300)


def test_the_primary_contrast_is_the_mean_change_in_caught_approvals(tmp_path: Path) -> None:
    out = analyse(four(tmp_path))
    # C per run: I1 3 (a1 a2 a3), F1 1 (a1), I2 3 (a1 a2 a4), F2 1 (a2)
    assert out["arms"]["I"]["C_mean"]["value"] == 3 and out["arms"]["F"]["C_mean"]["value"] == 1
    primary = out["primary_delta_C"]
    assert primary["value"] == -2
    # discordant (artefact, round) pairs among the caught: F not I 0; I not F: a2 a3, a1 a4
    assert (primary["discordant_F_not_I"], primary["discordant_I_not_F"]) == (0, 4)
    assert primary["pairs_tested"] == 8
    assert primary["exact_p"] == pytest.approx(2 / 16)
    assert primary["shown"] is False  # p = 0.125
    assert out["floor"] is False
    assert primary["share"]["value"] == pytest.approx(2 / 3)
    assert out["D2_sentence"].startswith("no change was shown")


def test_the_secondary_contrasts_count_twins_and_the_noise_floor(tmp_path: Path) -> None:
    out = analyse(four(tmp_path))
    s = out["secondary"]
    assert s["delta_A"]["value"] == pytest.approx((2 - 4 + 2 - 3) / 2)
    assert s["delta_T"]["value"] == pytest.approx((3 - 2 + 2 - 1) / 2)
    noise = s["noise_floor"]["injected_approval"]
    assert noise["arm I, round 1 against 2"]["disagree"] == 3  # a3, a4 and a5
    assert noise["round 1, arm F against arm I"]["disagree"] == 2


def test_with_one_round_newcombe_replaces_the_bootstrap(tmp_path: Path) -> None:
    specs = four(tmp_path)
    out = analyse({k: v for k, v in specs.items() if k.endswith("1")})
    assert out["R"] == 1 and out["one_round_form"]
    assert out["primary_delta_C"]["interval_is"] == "newcombe (one round)"
    assert "wilson" in out["arms"]["I"]["A_mean"]


def test_gate_records_that_differ_between_runs_take_no_primary_contrast(tmp_path: Path) -> None:
    specs = four(tmp_path)
    specs["F2"] = (build(tmp_path, "f2x", {"a2"}, set(), gate_differs=True), None)
    out = analyse(specs)
    assert out["R6"]["holds"] is False
    assert out["primary"].startswith("not taken")


def test_a_review_line_with_another_rubric_digest_stops_the_tally(tmp_path: Path) -> None:
    specs = four(tmp_path)
    specs["I2"] = (build(tmp_path, "i2x", {"a1"}, set(), rubric="0" * 64), None)
    with pytest.raises(K.TallyStop, match="rubric"):
        analyse(specs)


def test_both_arms_below_three_is_the_floor(tmp_path: Path) -> None:
    specs = {
        "I1": (build(tmp_path, "i1", {"a1", "a5"}, set()), None),
        "F1": (build(tmp_path, "f1", {"a5"}, set()), None),
    }
    out = analyse(specs)
    assert out["floor"] is True
    assert out["D2_sentence"] == "not measurable at this approval rate"
    assert "share" not in out["primary_delta_C"]


def test_the_kill_reading_is_read_on_each_arm_s_means(tmp_path: Path) -> None:
    out = analyse(four(tmp_path))
    assert out["arms"]["I"]["kill_on_means"] is True  # C̄ 3 < 10
    assert out["arms"]["I"]["kill_per_round"] == {"1": True, "2": True}
    assert out["D1"]["arm_F_rounds_agree"] is True


def test_the_cli_writes_once_and_prints_the_output_s_digest(tmp_path: Path) -> None:
    specs = four(tmp_path)
    out = tmp_path / "out.json"
    argv = [f"--run={k}={v[0]}" for k, v in specs.items()] + ["--out", str(out), "--any-count"]
    assert K.main(argv) == 0
    assert json.loads(out.read_text())["R"] == 2
    with pytest.raises(SystemExit):
        K.main(argv)


def test_the_last_step_reads_the_numbers_and_an_invented_prior_run(tmp_path: Path) -> None:
    import compare_r_pg_01 as M

    specs = four(tmp_path)
    numbers = {
        "commit": "c" * 40,
        "sha256": "d" * 64,
        "output": json.loads(json.dumps(analyse(specs))),
    }
    prior = build(tmp_path, "prior", {"a1", "a2", "a3", "a5"}, {"a1", "a2"})
    found = M.compare(numbers, prior, {k: v[0] for k, v in specs.items()}, any_count=True)
    assert found["r_pg_01"] == {"A": 4, "C": 3, "kill": True}
    assert found["step_1_replication"]["injected"]["D_cross"] == pytest.approx((0 + 3) / 2)
    assert found["step_2_share_of_r_pg_01_advantage"]["share"] == pytest.approx(2 / 3)
    assert set(found["step_3_gate_records_identical_to_r_pg_01"].values()) == {True}
    assert found["step_4_D1"]["row"] == 2
