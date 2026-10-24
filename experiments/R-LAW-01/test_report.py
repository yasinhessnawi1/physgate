"""R-LAW-01's post-run report (law_report.py) on the synthetic fixture and on an invented work dir.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01

No set or run of the experiment is read, and no model is called.
"""

from __future__ import annotations

import gzip
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import law_extract as X
import law_report as RP
import law_tally as TL
import law_verify as V
import pytest
import test_tally_rules as R
from test_pipeline import pipeline  # noqa: F401  (the fixture, built once for this module)

# ---------------------------------------------------------------- end to end on the fixture


@pytest.fixture(scope="module")
def published(pipeline: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> Path:  # noqa: F811
    """The pipeline's work dir laid out as experiments/R-LAW-01/ publishes it."""
    work = pipeline["work"]
    root = tmp_path_factory.mktemp("published")
    data = root / "data"
    data.mkdir()
    for name, src in RP.TALLY_INPUTS.items():
        if (work / src).exists():
            shutil.copyfile(work / src, data / name)
    (data / "tally.json").write_text(
        json.dumps(pipeline["tally"], indent=1, sort_keys=True, default=str)
    )
    with gzip.open(data / "regate.jsonl.gz", "wt") as fh:
        for r in pipeline["regate"]:
            fh.write(json.dumps(r) + "\n")
    shutil.copyfile(work / "slice.json", root / "slice.json")
    return data


@pytest.fixture(scope="module")
def extra(published: Path, pipeline: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    return RP.compute(published, published.parent / "slice.json", True, pipeline["sets"])


def test_the_report_is_computed_on_the_tally_it_reproduces(extra: dict[str, Any]) -> None:
    assert extra["tally_reproduced"] is True
    assert extra["computed_after_the_run"] is True
    assert set(extra["slice"]) == {"v0", "v1"}
    c = extra["checks_1_and_7"]
    assert c["label"] == RP.LABEL and c["variant"]["label"] == RP.LABEL


def test_the_l_row_of_every_group_is_the_tally_s_own(
    extra: dict[str, Any],
    pipeline: dict[str, Any],  # noqa: F811
) -> None:
    bd = pipeline["tally"]["breakdowns"]
    for group, by in extra["shares_by_group"].items():
        assert set(by) == set(bd[group])
        for value, codes in by.items():
            assert codes["L"] == bd[group][value]
            assert sum(c["k"] for c in codes.values()) == codes["L"]["n"]


def test_the_parts_the_reality_and_the_families_add_up(
    extra: dict[str, Any],
    pipeline: dict[str, Any],  # noqa: F811
) -> None:
    t = pipeline["tally"]
    sec = t["secondary"]
    for name in ("G_parts", "D_by_kind", "N_by_kind"):
        got = extra["parts_as_shares"][name]
        assert {k: v["k"] for k, v in got.items()} == sec[name]
        assert all(v["n"] == t["primary"]["n"] for v in got.values())
    side = extra["reality_by_side"]
    assert sum(sum(c.values()) for c in side.values()) == t["population"]["measured_flaws"]
    total: Counter[str] = Counter()
    for c in side.values():
        total.update(c)
    assert dict(total) == dict(Counter(pipeline["summary"]["flaw_reality"].values()))
    assert sum(extra["L_by_family"]["family"].values()) == sec["counts"].get("L", 0)
    # the variant keeps the denominator, and only moves flaws to G
    v = extra["checks_1_and_7"]["variant"]
    assert v["primary"]["n"] == t["primary"]["n"] and v["primary"]["k"] <= t["primary"]["k"]
    assert v["counts"].get("G", 0) >= sec["counts"].get("G", 0)


def test_the_slice_has_no_round_here_and_is_reported_empty(extra: dict[str, Any]) -> None:
    # the fixture's pipeline runs no calibration session: every slice line is without a form
    for v in ("v0", "v1"):
        s = extra["slice"][v]
        assert s["lines"] > 0 and s["disagreements"] == {}
        assert s["final_codes_lines"] == {"uncoded": s["lines"]}
        assert s["L_share_flaws"]["k"] == 0


def test_files_whose_tally_differs_are_flagged_and_refused_outside_a_dry_run(
    published: Path,
    pipeline: dict[str, Any],  # noqa: F811
    tmp_path: Path,
) -> None:
    other = tmp_path / "data"
    shutil.copytree(published, other)
    (other / "tally.json").write_text("{}")
    shutil.copyfile(published.parent / "slice.json", tmp_path / "slice.json")
    got = RP.compute(other, tmp_path / "slice.json", True, pipeline["sets"])
    assert got["tally_reproduced"] is False
    # outside a dry run the tally itself refuses a stand-in's output, before anything is computed
    with pytest.raises(X.Refused):
        RP.compute(other, tmp_path / "slice.json", False, pipeline["sets"])


# ---------------------------------------------------------------- exact figures, invented


def _slice_rows(t: TL.Tally, lid: str, step: str, c1: str, c2: str) -> list[dict[str, Any]]:
    x = t.lines[lid]
    version = R.SETS[x["set"]].version(x["pair"], x["side"])
    rows = []
    for who, code in (("c1", c1), ("c2", c2)):
        f = R.form_for(code, version, "P <= M")
        rows.append(
            {
                "step": step,
                "who": who,
                "line_id": lid,
                "packet": "P0099",
                "fid": "F1",
                "try": "try1",
                "standin": False,
                "form": f,
                **V.verify_form(f, version),
            }
        )
    return rows


@pytest.fixture
def invented(tmp_path: Path) -> TL.Tally:
    R.build(
        tmp_path,
        [
            R.flaw([R.ln("a1", "L", "L")]),
            R.flaw([R.ln("a2", "D", "D", side="twin")]),
            R.flaw([R.ln("a3", "N", "N"), R.ln("a3", "N", "N", side="twin")]),
            R.flaw([R.ln("a4", "N", "N", verdict="not_a_flaw", origin="n/a")]),
            # the slice pair: its lines' measured rows are replaced by two calibration rounds
            R.flaw([R.ln("a9", "L", "L"), R.ln("a9", "N", "N")]),
            R.flaw([R.ln("a9", "D", "N")]),
        ],
    )
    (tmp_path / "slice.json").write_text(json.dumps({"pairs": {"practice": [], "fresh": ["a9"]}}))
    t = TL.Tally(tmp_path, dry_run=True, sets=R.SETS)
    slice_ids = sorted(RP.slice_line_ids(t))
    assert slice_ids == ["L0006", "L0007", "L0008"]
    codes = [r for r in t.codes if r["line_id"] not in slice_ids]
    for step, plan in (
        ("slice-r1", {"L0006": ("L", "L"), "L0007": ("N", "N"), "L0008": ("D", "N")}),
        ("slice-r2", {"L0006": ("L", "L"), "L0007": ("N", "N"), "L0008": ("D", "D")}),
    ):
        for lid, (c1, c2) in plan.items():
            codes += _slice_rows(t, lid, step, c1, c2)
    X.write_jsonl(tmp_path / "codes.jsonl", codes)
    return TL.Tally(tmp_path, dry_run=True, sets=R.SETS)


def test_the_slice_counts_disagreements_kappa_and_l_per_version(invented: TL.Tally) -> None:
    out = RP.report(invented, invented.run(), {})
    v0, v1 = out["slice"]["v0"], out["slice"]["v1"]
    assert v0["disagreements"] == {"D–N": 1} and v1["disagreements"] == {}
    assert v1["kappa5"]["weighted"] == pytest.approx(1.0)
    assert v0["kappa5"]["weighted"] < 1.0
    # flaw a9/1 is L in both rounds; flaw a9/2 is uncoded in v0 (no adjudicator) and D in v1
    assert (v0["L_share_flaws"]["k"], v0["L_share_flaws"]["n"]) == (1, 2)
    assert v0["final_codes_lines"] == {"L": 1, "N": 1, "uncoded": 1}
    assert v1["final_codes_lines"] == {"L": 1, "N": 1, "D": 1}
    assert (v1["L_share_lines"]["k"], v1["L_share_lines"]["n"]) == (1, 3)


def test_a_slice_line_the_gate_catches_is_g(invented: TL.Tally) -> None:
    out = RP.report(invented, invented.run(), {"slice-r2": {"L0006": True}})
    assert out["slice"]["v1"]["final_codes_lines"]["G"] == 1
    assert out["slice"]["v1"]["L_share_flaws"]["k"] == 0
    assert out["slice"]["v0"]["L_share_flaws"]["k"] == 1


def test_every_code_s_share_by_group_and_the_flaws_by_side(invented: TL.Tally) -> None:
    out = RP.report(invented, invented.run(), {})
    role = out["shares_by_group"]["role"]["electrical"]
    assert {c: (v["k"], v["n"]) for c, v in role.items()} == {
        "G": (0, 3),
        "L": (1, 3),
        "L-if-data": (0, 3),
        "D": (1, 3),
        "N": (1, 3),
        "uncoded": (0, 3),
    }
    assert out["reality_by_side"] == {
        "both": {"real": 1},
        "injected only": {"real": 1, "not_real": 1},
        "twin only": {"real": 1},
    }
    assert out["parts_as_shares"]["D_by_kind"] == {"table": {"k": 1, "n": 3, "share": 1 / 3}}
    assert out["L_by_family"] == {
        "family": {"4": 1},
        "family_by_relation_origin": {"4 | new relation": 1},
    }


# ---------------------------------------------------------------- checks 1 and 7 after the fact


def _quantity_node(qs: dict[str, tuple[float, str]]) -> dict[str, dict[str, Any]]:
    return {"n": R.node("n", qs)}


def _claim(
    gate_relation: str, relation: str, inputs: list[tuple[str, str, float, str]]
) -> dict[str, Any]:
    return {
        "code": "G",
        "gate_relation": gate_relation,
        "relation": relation,
        "kind": "law",
        "tolerance": "inequality",
        "fallback_code": "D",
        "inputs": [
            {"symbol": s, "node": "n", "quantity": q, "value": v, "unit": u}
            for s, q, v, u in inputs
        ],
    }


def test_a_failed_g_claim_on_checks_1_and_7_is_structural_unless_it_could_be_written() -> None:
    nodes = _quantity_node({"sample_rate": (5.0, "ms"), "rate": (200.0, "Hz"), "mass": (1.0, "kg")})
    rule = _claim("propagation", "changed(n) => changed(m) or no_change_justified(m)", [])
    assert RP.why_failed(rule, nodes)[0] == "structural"
    unit_fn = _claim(
        "units_kind", "dimension(f) == dimension(Hz)", [("f", "sample_rate", 5.0, "ms")]
    )
    assert RP.why_failed(unit_fn, nodes)[0] == "structural"
    two_dims = _claim(
        "units_kind", "f == g", [("f", "sample_rate", 5.0, "ms"), ("g", "rate", 200.0, "Hz")]
    )
    assert RP.why_failed(two_dims, nodes) == (
        "structural",
        "parses, and its two sides differ in dimension",
    )
    # a mass equality labelled propagation, unparsed only for its trailing comment
    commented = _claim(
        "propagation",
        "m == k (a changed neighbour must follow)",
        [("m", "mass", 1.0, "kg"), ("k", "mass", 1.0, "kg")],
    )
    kind, why = RP.why_failed(commented, nodes)
    assert kind == "writable" and "comparator_class" in why
    other = _claim("power_budget", "sum of draws <= supply", [])
    assert RP.why_failed(other, nodes)[0] == "writable"


RECORD_7 = {
    "check": 7,
    "name": "propagation",
    "outcome": "fail",
    "node": "e.a",
    "module": None,
    "details": {},
    "message": "e.a changed power_draw and owes e.b a change",
    "scope": "system",
}


def _regate(*records: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"set": "fresh", "pair": "a1", "side": "injected", "result": {"checks": list(records)}}]


def _patch(tmp: Path, line: str, **fields: Any) -> TL.Tally:  # noqa: ANN401
    """Change the coders' forms of one line of an invented work dir, verified again (§5.5)."""
    codes = X.read_jsonl(tmp / "codes.jsonl")
    lines = {x["line_id"]: x for x in X.read_jsonl(tmp / "lines.jsonl")}
    x = lines[line]
    version = R.SETS[x["set"]].version(x["pair"], x["side"])
    for r in codes:
        if r["line_id"] == line and r.get("form"):
            r["form"] = {**r["form"], **fields}
            r.update(V.verify_form(r["form"], version))
    X.write_jsonl(tmp / "codes.jsonl", codes)
    return TL.Tally(tmp, dry_run=True, sets=R.SETS)


def test_the_variant_counts_a_line_check_7_caught_as_g_and_its_l_flaw_moves(
    tmp_path: Path,
) -> None:
    R.build(
        tmp_path,
        [
            R.flaw(
                [
                    R.ln("a1", "L", "L"),
                    # both coders claim check 7 with a rule the grammar cannot parse: it falls
                    # back to N
                    R.ln("a1", "G", "G", relation="changed(e.a) => changed(e.b)"),
                ]
            ),
            R.flaw([R.ln("a2", "L", "L")]),
        ],
    )
    t = _patch(tmp_path, "L0002", gate_relation="propagation")
    assert t.final == {"L0001": "L", "L0002": "N", "L0003": "L"}
    as_tallied = t.run()
    assert (as_tallied["primary"]["k"], as_tallied["primary"]["n"]) == (2, 2)
    v = RP.gate_variant(TL.Tally(tmp_path, dry_run=True, sets=R.SETS), _regate(RECORD_7))
    assert v["label"] == RP.LABEL
    assert v["lines_set_to_G"] == 1 and v["lines_set_to_G_true_flaw"] == 1
    assert (v["primary"]["k"], v["primary"]["n"]) == (1, 2)
    assert v["counts"] == {"G": 1, "L": 1}
    assert v["flaws_whose_code_changes"] == {"L -> G": 1}
    [moved] = v["L_flaws_that_become_G"]
    assert moved["flaw"] == "F0001" and moved["code_after"] == "G"
    assert [x["line"] for x in moved["lines"]] == ["L0002"]
    assert moved["lines"][0]["records"] == [{"check": 7, "name": "propagation", "scope": "system"}]
    # a record of another check, or one whose message names no locus quantity, catches nothing
    for other in (
        {**RECORD_7, "check": 4, "name": "power"},
        {**RECORD_7, "message": "e.a changed"},
    ):
        v = RP.gate_variant(TL.Tally(tmp_path, dry_run=True, sets=R.SETS), _regate(other))
        assert v["lines_set_to_G"] == 0 and v["primary"]["k"] == 2
    claims = RP.failed_g_claims(t)
    assert claims["claims"] == 2 and claims["kind"] == {"structural": 2}


def test_the_variant_sets_only_failed_check_1_and_7_claims_to_g(tmp_path: Path) -> None:
    # Three lines check 7 catches and that fell back to N: a failed L `limit` (a literal fails the
    # pairing check), a failed G on another gate relation, and a failed G on check 7. Only the
    # last was a claim on check 1 or 7; a variant reading the locus condition alone took all three.
    R.build(
        tmp_path,
        [
            R.flaw([R.ln("a1", "L", "L", relation="P <= 2 * M")]),
            R.flaw([R.ln("a1", "G", "G", relation="sum of draws <= supply")]),
            R.flaw([R.ln("a1", "G", "G", relation="changed(e.a) => changed(e.b)")]),
        ],
    )
    _patch(tmp_path, "L0001", kind="limit")
    t = _patch(tmp_path, "L0003", gate_relation="propagation")
    assert t.final == {"L0001": "N", "L0002": "N", "L0003": "N"}
    assert {r["line_id"]: r["failure"] for r in t.codes if r["who"] == "c1"} == {
        "L0001": "pairing",
        "L0002": "unparsed",
        "L0003": "unparsed",
    }
    v = RP.gate_variant(TL.Tally(tmp_path, dry_run=True, sets=R.SETS), _regate(RECORD_7))
    assert v["lines_set_to_G"] == 1
    assert v["counts"] == {"G": 1, "N": 2}
    assert v["flaws_whose_code_changes"] == {"N -> G": 1}


def test_the_review_figures_no_form_denominators_own_codes_and_restatements(
    tmp_path: Path,
) -> None:
    R.build(
        tmp_path,
        [
            # two L flaws on one pair whose relations read the same inputs: one restates the other
            R.flaw([R.ln("a1", "L", "L")]),
            R.flaw([R.ln("a1", "L", "L")]),
            # a G-caught line both coders coded L
            R.flaw([R.ln("a2", "L", "L", matched=True)]),
            # coder 2 left the line without a form: the line and its flaw are uncoded
            R.flaw([R.ln("a3", "N", None)]),
            # the adjudicator codes G, which is neither coder's code
            R.flaw([R.ln("a4", "D", "L", adj="G")]),
        ],
    )
    t = TL.Tally(tmp_path, dry_run=True, sets=R.SETS)
    tally = t.run()
    nf = RP.lines_without_a_form(t)
    assert nf["lines"] == [{"line": "L0004", "who": "c2", "packet": "P0001"}]
    assert nf["uncoded_real_flaws"] == [{"flaw": "F0004", "lines": ["L0004"]}]
    den = RP.g_claim_denominators(t)
    assert den["c1"]["lines"] == ["L0003"] and den["c1"]["given"] == 1
    assert den["c1"]["claimed_G_after_5_5"] == 0 and den["c1"]["codes_after_5_5"] == {"L": 1}
    [own] = RP.adjudicator_own_codes(t)
    assert own["line"] == "L0005" and own["claimed"] == "G" and own["code"] == "G"
    comp = RP.l_composition(t, tally)
    # the adjudicator's G on a4 is not gate-caught, so it is an L (gap): three L flaws in all
    assert comp["L_flaws"] == 3 and comp["restating_another"] == 1
    assert comp["shared_inputs"][0]["flaws"] == ["F0001", "F0002"]
    # P <= M fails on every clean twin of the fixture (2 W against 1 W): each blocks them all
    assert comp["blocking_all_or_all_but_one_twin"] == 3
