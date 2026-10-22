"""R-LAW-01 §2.3, §5.6, §5.7, §7, §8.2 and §10 on an invented work dir: the tally's own rules.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01

Every set, line, form, verdict and match here is invented; no corpus and no run is read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import law_extract as X
import law_tally as TL
import law_verify as V
import pytest

PAIRS = [f"a{i}" for i in range(1, 14)]


def node(nid: str, qs: dict[str, tuple[float, str]]) -> dict[str, Any]:
    return {
        "id": nid,
        "kind": "part",
        "domain": "electrical",
        "constrains": [],
        "requirements": [],
        "quantities": {q: {"value": v, "unit": u, "source": "sheet"} for q, (v, u) in qs.items()},
    }


def artefact(pid: str) -> dict[str, Any]:
    clean = node("e.a", {"power_draw": (2.0, "W"), "max_power": (1.0, "W")})
    injected = node("e.a", {"power_draw": (3.0, "W"), "max_power": (1.0, "W")})
    return {
        "id": pid,
        "error_class": "magnitude",
        "expected_check": "magnitude",
        "assigned_role": "electrical",
        "edge": None,
        "clean": {"nodes": [clean]},
        "injected": {"nodes": [injected]},
    }


def make_sets() -> dict[str, X.SetData]:
    base = [
        node("e.a", {"power_draw": (2.0, "W"), "max_power": (1.0, "W")}),
        node("e.b", {"power_supply": (5.0, "W")}),
    ]
    return {
        name: X.SetData(name, seed, base, {p: artefact(p) for p in PAIRS}, b"sheet\n")
        for name, seed in (("practice", 11), ("fresh", 13))
    }


SETS = make_sets()
ON_CHANGE = [["e.a", "power_draw"]]
UNCHANGED = [["e.b", "power_supply"]]


def form_for(code: str, version: dict[str, Any], relation: str) -> dict[str, Any]:
    f: dict[str, Any] = {
        "id": "F1",
        "defect": "d",
        "code": code,
        "multiple_defects": False,
        "reason": "r",
    }
    if code in ("G", "L"):
        q = version["e.a"]["quantities"]
        f.update(
            {
                "gate_relation": "power_budget" if code == "G" else "none",
                "relation": relation,
                "law": "a bound",
                "kind": "law",
                "inputs": [
                    {
                        "symbol": "P",
                        "node": "e.a",
                        "quantity": "power_draw",
                        "value": q["power_draw"]["value"],
                        "unit": "W",
                    },
                    {
                        "symbol": "M",
                        "node": "e.a",
                        "quantity": "max_power",
                        "value": q["max_power"]["value"],
                        "unit": "W",
                    },
                ],
                "tolerance": "inequality",
                "evaluation": "e",
                "family": 4,
                "fallback_code": "N",
            }
        )
    elif code == "L-if-data":
        f.update(
            {
                "relation": "P == V**2 / R",
                "law": "Joule heating",
                "kind": "law",
                "inputs": [],
                "missing": [{"node": None, "quantity": "resistance"}],
                "family": 4,
            }
        )
    elif code == "D":
        f["d_kind"] = "table"
    else:
        f["n_kind"] = "judgement"
    return f


def ln(
    pair: str,
    c1: str | None,
    c2: str | None,
    *,
    adj: str | None = None,
    audit: str | None = None,
    side: str = "injected",
    verdict: str = "true_flaw",
    origin: str = "introduced",
    matched: bool = False,
    locus: list[list[str]] | None = None,
    relation: str = "P <= M",
) -> dict[str, Any]:
    return {
        "pair": pair,
        "side": side,
        "codes": {"c1": c1, "c2": c2, "adj": adj, "audit": audit},
        "verdict": verdict,
        "origin": origin,
        "matched": matched,
        "locus": ON_CHANGE if locus is None else locus,
        "relation": relation,
    }


def flaw(lines: list[dict[str, Any]], base: bool = False) -> dict[str, Any]:
    return {"lines": lines, "base": base}


def build(
    tmp: Path, flaws: list[dict[str, Any]], events: list[dict[str, Any]] | None = None
) -> TL.Tally:
    """Write an invented work dir with these flaws (all in the fresh set) and read its tally."""
    lines, units, codes, reality, matches = [], [], [], [], []
    n = 0
    for k, fl in enumerate(flaws, 1):
        ids = []
        for spec in fl["lines"]:
            n += 1
            lid = f"L{n:04d}"
            ids.append(lid)
            lines.append(
                {
                    "line_id": lid,
                    "set": "fresh",
                    "pair": spec["pair"],
                    "side": spec["side"],
                    "run": "a-fresh",
                    "kind": "paired",
                    "item": "ES-1",
                    "section": "domain_standards",
                    "text": "t",
                    "locus": spec["locus"],
                }
            )
            version = SETS["fresh"].version(spec["pair"], spec["side"])
            for who, code in spec["codes"].items():
                if code is None and who in ("adj", "audit"):
                    continue
                row: dict[str, Any] = {
                    "step": "audit" if who == "audit" else "measured",
                    "who": who,
                    "line_id": lid,
                    "packet": "P0001",
                    "fid": "F1",
                    "try": "try1",
                    "standin": False,
                }
                if code is None:
                    row.update({"form": None, "code": None, "code_raw": None, "failure": "no_form"})
                else:
                    f = form_for(code, version, spec["relation"])
                    if who == "adj":
                        f["chosen"] = "other"
                    row.update({"form": f, **V.verify_form(f, version)})
                codes.append(row)
            reality.append(
                {
                    "line_id": lid,
                    "verdict": spec["verdict"],
                    "origin": spec["origin"],
                    "try": "try1",
                }
            )
            matches.append({"line_id": lid, "matched": spec["matched"]})
        pairs = sorted({s["pair"] for s in fl["lines"]})
        units.append(
            {
                "flaw_id": f"F{k:04d}",
                "set": "fresh",
                "pairs": pairs,
                "lines": ids,
                "locus_lines": ids,
                "base": fl["base"],
            }
        )
    (tmp / "ledger").mkdir(parents=True, exist_ok=True)
    X.write_jsonl(tmp / "lines.jsonl", lines)
    for name in ("flaws.jsonl", "units_s1.jsonl", "units_s6.jsonl"):
        X.write_jsonl(tmp / name, units)
    X.write_jsonl(tmp / "codes.jsonl", codes)
    X.write_jsonl(tmp / "reality.jsonl", reality)
    X.write_jsonl(tmp / "matches.jsonl", matches)
    if events:
        X.write_jsonl(tmp / "ledger" / "interruptions.jsonl", list(events))
    (tmp / "slice.json").write_text(json.dumps({"pairs": {"practice": [], "fresh": []}}))
    (tmp / "extract_counts.json").write_text(json.dumps({"lines": 993, "excluded": {}}))
    (tmp / "group_counts.json").write_text(json.dumps({"after_c": 367, "after_d": 348}))
    (tmp / "reality_summary.json").write_text(
        json.dumps(
            {
                "reliable": True,
                "calibration": {},
                "rejection": {},
                "prior_agreement": {},
                "verdicts_by_side": {},
                "flaw_reality": {},
            }
        )
    )
    return TL.Tally(tmp, dry_run=True, sets=SETS)


# ---------------------------------------------------------------- §5.6 and §5.7


def test_the_gate_turns_g_l_and_l_if_data_lines_into_g(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", "L", "L", matched=True)]),
            flaw([ln("a2", "L-if-data", "L-if-data", matched=True)]),
            flaw([ln("a3", "G", "G", matched=True)]),
            flaw([ln("a4", "G", "G", matched=False)]),
            flaw([ln("a5", "D", "D", matched=True)]),
            flaw([ln("a6", "N", "N", matched=True)]),
        ],
    )
    assert t.final == {
        "L0001": "G",
        "L0002": "G",
        "L0003": "G",
        "L0004": "L",
        "L0005": "D",
        "L0006": "N",
    }
    assert t.gap == {"L0004"}


def test_a_flaw_is_real_if_any_of_its_lines_is_a_true_flaw(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", "N", "N"), ln("a1", "N", "N", verdict="not_a_flaw", origin="n/a")]),
            flaw(
                [
                    ln("a2", "N", "N", verdict="not_a_flaw", origin="n/a"),
                    ln("a2", "N", "N", verdict="undecidable", origin="n/a"),
                ]
            ),
            flaw([ln("a3", "N", "N", verdict="undecidable", origin="n/a")]),
            flaw([ln("a4", "N", "N"), ln("a4", "N", "N")]),
        ],
    )
    units = t.unit_rows(t.flaws)
    assert [t.real(u, False) for u in units] == [True, False, False, True]
    assert t.run()["population"]["real_flaws"] == 2


# ---------------------------------------------------------------- §7


def test_kappa_weighs_each_flaw_once(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", "N", "N") for _ in range(4)]),
            flaw([ln("a2", "L", "L")]),
            flaw([ln("a3", "L", "N")]),
            flaw([ln("a4", "N", "N")]),
        ],
    )
    k = t.kappas()
    # weighted: four flaws, three agreeing; c1 half N, c2 three quarters N: κ = (0.75-0.5)/0.5
    assert k["kappa5"]["weighted"] == pytest.approx(0.5)
    assert k["kappaL"]["weighted"] == pytest.approx(0.5)
    # unweighted: seven lines, six agreeing
    assert k["kappa5"]["unweighted"] == pytest.approx(10 / 17)


def test_a_missing_form_is_a_category_that_never_agrees() -> None:
    out = TL.kappa_stats([("none", "none", 1.0, "a"), ("N", "N", 1.0, "b")], 6, draws=10)
    assert out["raw_agreement_weighted"] == pytest.approx(0.5)


def test_kappa_counts_a_missing_form_as_a_disagreement(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", None, "N")]),
            flaw([ln("a2", "N", "N")]),
            flaw([ln("a3", "L", "L")]),
            flaw([ln("a4", None, None)]),
        ],
    )
    k = t.kappas()
    # κ₅: two missing forms disagree; κ_L: a missing form against N disagrees
    assert k["kappa5"]["raw_agreement_weighted"] == pytest.approx(0.5)
    assert k["kappaL"]["raw_agreement_weighted"] == pytest.approx(0.5)
    # PABAK over six categories for κ₅ and three (G or L, the rest, none) for κ_L
    assert k["kappa5"]["pabak_weighted"] == pytest.approx((6 * 0.5 - 1) / 5)
    assert k["kappaL"]["pabak_weighted"] == pytest.approx((3 * 0.5 - 1) / 2)


def test_each_coder_s_g_claims_are_read_from_its_own_rows(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", "G", "G", matched=True, audit="G")]),
            flaw([ln("a2", "L", "N", adj="G", matched=True, audit="N")]),
            flaw([ln("a3", "G", "G", matched=True)]),
            flaw([ln("a4", "N", "N", audit="G")]),
        ],
    )
    assert {i for i, c in t.final.items() if c == "G"} == {"L0001", "L0002", "L0003"}
    per = t.per_coder()
    claimed = {
        w: per[w]["share_of_gate_caught_lines_claimed_G"] for w in ("c1", "c2", "adj", "audit")
    }
    # the coders saw every G-caught line; the adjudicator only L0002, the audit L0001 and L0002
    assert claimed == pytest.approx({"c1": 2 / 3, "c2": 2 / 3, "adj": 1.0, "audit": 0.5})


# ---------------------------------------------------------------- §8.1 and §8.2


def test_a_base_flaw_is_a_cluster_of_its_own(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw([ln("a1", "L", "L", locus=UNCHANGED), ln("a2", "L", "L", locus=UNCHANGED)], True),
            flaw([ln("a1", "N", "N")]),
        ],
    )
    units = t.unit_rows(t.flaws)
    assert [u["cluster"] for u in units] == [("base", "F0001"), ("fresh", "a1")]
    assert t.share(units, False)["clusters"] == 2


def test_every_l_relation_lists_its_literals(tmp_path: Path) -> None:
    t = build(
        tmp_path,
        [
            flaw(
                [
                    ln("a1", "L", "L"),
                    ln("a1", "L", "L", side="twin", relation="P * 2 <= M * 3"),
                ]
            ),
            flaw([ln("a2", "L", "L", relation="P * 2 <= M * 3")]),
        ],
    )
    lits = t.run()["secondary"]["L_literals"]
    by = {e["relation"]: e for e in lits}
    assert set(by) == {"P <= M", "P * 2 <= M * 3"}
    assert by["P <= M"]["literals"] == []
    assert sorted(by["P * 2 <= M * 3"]["literals"]) == [2.0, 3.0]
    assert sorted(by["P * 2 <= M * 3"]["lines"]) == ["L0002", "L0003"]


# ---------------------------------------------------------------- §10


def test_resolved_reads_the_wider_of_the_two_intervals() -> None:
    assert TL.resolution([0.16, 0.20], [0.10, 0.30]) == (False, [0.10, 0.30])
    assert TL.resolution([0.10, 0.30], [0.16, 0.20]) == (False, [0.10, 0.30])
    assert TL.resolution([0.16, 0.30], [0.17, 0.20]) == (True, [0.16, 0.30])
    assert TL.resolution([0.02, 0.12], None) == (True, [0.02, 0.12])
    assert TL.resolution(None, None) == (False, None)


def test_the_scope_note_reads_the_same_flaws_as_the_deciding_share(tmp_path: Path) -> None:
    on_injection = [flaw([ln(p, "L", "L")]) for p in PAIRS[:3]]
    elsewhere = []
    for p in PAIRS[3:13]:
        c = "L-if-data" if p == PAIRS[3] else "N"
        elsewhere.append(flaw([ln(p, c, c, locus=UNCHANGED, origin="already_in_base")]))
    d = build(tmp_path, on_injection + elsewhere).run()["decision"]
    # on the injection 3 of 3 are L, elsewhere 0 of 10: the share elsewhere decides
    assert d["mix_dependent"] and d["deciding_share"] == "elsewhere" and d["share"] == 0
    # L + L-if-data elsewhere is 1 of 10, below T (over every flaw it would be 4 of 13)
    assert d["L_plus_L_if_data"] == pytest.approx(0.1)
    assert d["scope_note_data_side"] is False


def test_the_literal_count_beside_the_decision_reads_the_deciding_flaws(tmp_path: Path) -> None:
    derated = "P * 1.5 <= M"  # one input each side and a non-integer literal
    on_injection = [flaw([ln(p, "L", "L", relation=derated)]) for p in PAIRS[:3]]
    elsewhere = [
        flaw([ln(PAIRS[3], "L", "L", locus=UNCHANGED, origin="already_in_base", relation=derated)])
    ]
    for p in PAIRS[4:13]:
        elsewhere.append(flaw([ln(p, "N", "N", locus=UNCHANGED, origin="already_in_base")]))
    d = build(tmp_path, on_injection + elsewhere).run()["decision"]
    # on the injection 3 of 3 are L, elsewhere 1 of 10: the share elsewhere decides
    assert d["mix_dependent"] and d["deciding_share"] == "elsewhere"
    assert d["share"] == pytest.approx(0.1)
    # the count beside it reads the same flaws as S5 and L + L-if-data (over every flaw: 4)
    assert d["L_flaws_one_input_each_side_non_integer_literal"] == 1


def test_interruptions_are_reported_and_leave_the_decision_taken(tmp_path: Path) -> None:
    events = [
        {"event": "failed_call", "step": "s", "reason": "P0001 try1: usage_limit", "utc": "x"},
        {"event": "stop", "step": "s", "reason": "a failed call", "utc": "x"},
        {"event": "resume", "step": "launch", "reason": "after a stop", "utc": "y"},
    ]
    out = build(tmp_path, [flaw([ln("a1", "L", "L")])], events).run()
    d = out["decision"]
    assert d["taken"] is True and d["deviations"] == []
    assert d["interruptions_reported"] == 3
    assert not any("deviation" in k for k in d if k.startswith("interruption"))
    assert out["interruptions"]["failed_calls"] == 1
    assert out["interruptions"]["stops"] == 1 and out["interruptions"]["resumes"] == 1


# ---------------------------------------------------------------- §12, the token guard


def _ledger(tmp: Path, text: str) -> None:
    (tmp / "ledger" / "ledger.jsonl").write_text(text)


def _row(tokens: int, packet: str = "P0001") -> str:
    return json.dumps({"step": "measured-c1", "packet": packet, "try": 1, "tokens": tokens}) + "\n"


def test_the_tally_sums_the_ledger_and_voids_at_the_guard(tmp_path: Path) -> None:
    build(tmp_path, [flaw([ln("a1", "L", "L")])])
    _ledger(tmp_path, _row(40_000_000) + _row(19_999_999, "P0002"))
    d = TL.Tally(tmp_path, dry_run=True, sets=SETS).run()["decision"]
    assert d["taken"] is True and d["deviations"] == []
    # one token more and the guard is reached, with no VOID marker written
    _ledger(tmp_path, _row(40_000_000) + _row(20_000_000, "P0002"))
    assert not (tmp_path / "ledger" / "VOID").exists()
    d = TL.Tally(tmp_path, dry_run=True, sets=SETS).run()["decision"]
    assert d["taken"] is False
    assert d["deviations"] == ["the 60 M token guard was reached: the result is void"]


@pytest.mark.parametrize(
    "text",
    [
        _row(10) + '{"step": "measured-c1", "packet": "P0002", "tok',
        _row(10) + json.dumps({"step": "s", "packet": "P", "try": 1, "tokens": -3}) + "\n",
        _row(10) + "[1]\n",
    ],
    ids=["a torn line", "a negative count", "not a row"],
)
def test_the_tally_refuses_a_ledger_it_cannot_read_in_full(tmp_path: Path, text: str) -> None:
    build(tmp_path, [flaw([ln("a1", "L", "L")])])
    _ledger(tmp_path, text)
    with pytest.raises(X.Refused, match="ledger"):
        TL.Tally(tmp_path, dry_run=True, sets=SETS)


def test_the_tally_refuses_a_real_run_without_a_ledger(tmp_path: Path) -> None:
    build(tmp_path, [flaw([ln("a1", "L", "L")])])
    with pytest.raises(X.Refused, match="ledger"):
        TL.Tally(tmp_path, dry_run=False, sets=SETS)
