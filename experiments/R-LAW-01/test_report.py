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
