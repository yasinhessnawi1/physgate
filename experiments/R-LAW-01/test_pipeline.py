"""R-LAW-01 end to end on the synthetic fixture: every script, sessions by the scripted stand-in.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01

No set or run of the experiment is read, and no model is called.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import law_extract as X
import law_fixture as F
import law_group as GR
import law_packets as P
import law_reality as R
import law_regate as G
import law_tally as TL
import law_verify as V
import pytest

HERE = Path(__file__).resolve().parent
SLICE = {"practice": ["u1"], "fresh": ["e1"]}
DIGEST = X.sha256_bytes(F.SHEET.encode())


def sessions(
    work: Path,
    step: str,
    kind: str,
    packets: Path,
    out: Path,
    model: str = "claude-opus-5-5",
    ids: Path | None = None,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "RLAW_STANDIN": str(work / "standin"),
        "RLAW_PROMPTS": str(work / "prompts"),
        "RLAW_LEDGER": str(work / "ledger" / "ledger.jsonl"),
        "RLAW_SHEET_SHA256": DIGEST,
        **(extra or {}),
    }
    args = [
        "bash",
        str(HERE / "law_sessions.sh"),
        "run",
        step,
        kind,
        str(packets),
        str(out),
        model,
        "2",
    ]
    if ids is not None:
        args.append(str(ids))
    return subprocess.run(args, capture_output=True, text=True, env=env, check=False)


def last_json(text: str) -> dict[str, Any]:
    return json.loads([x for x in text.splitlines() if x.startswith("{")][-1])


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("rlaw")
    fx = F.build(root / "fx")
    work = root / "work"
    work.mkdir()
    (work / "ledger").mkdir()
    (work / "state").mkdir()
    # the binary sees only an allowlisted environment, so the stand-in carries its own memory
    F.write_standin(work, state=work / "state")
    lines, counts, sets = F.extract_fixture(fx)
    X.write_jsonl(work / "lines.jsonl", lines)
    (work / "extract_counts.json").write_text(json.dumps(counts))
    flaws, s1, s6, gc = GR.group(lines, sets)
    X.write_jsonl(work / "flaws.jsonl", flaws)
    X.write_jsonl(work / "units_s1.jsonl", s1)
    X.write_jsonl(work / "units_s6.jsonl", s6)
    (work / "group_counts.json").write_text(json.dumps(gc))
    (work / "slice.json").write_text(
        json.dumps({"pairs": SLICE, "base_flaws_spanning_slice_and_measured": 1})
    )
    P.write_prompts(work / "prompts", ())
    measured = R.measured(work)
    pk = work / "packets"
    se = work / "sessions"
    P.build_coder_packets(measured, sets, P.SEED_C1, pk / "c1")
    P.build_coder_packets(measured, sets, P.SEED_C2, pk / "c2")
    runs = {}
    runs["c1"] = sessions(work, "measured-c1", "coder", pk / "c1", se / "c1")
    runs["c2"] = sessions(work, "measured-c2", "coder", pk / "c2", se / "c2")
    codes = V.codes_for("measured", "c1", pk / "c1", se / "c1", sets, DIGEST)
    codes += V.codes_for("measured", "c2", pk / "c2", se / "c2", sets, DIGEST)
    X.write_jsonl(work / "codes.jsonl", codes)
    P.build_adjudicator_packets(lines, codes, "measured", sets, pk / "adj")
    runs["adj"] = sessions(work, "measured-adj", "adjudicator", pk / "adj", se / "adj")
    codes += V.codes_for("measured", "adj", pk / "adj", se / "adj", sets, DIGEST)
    P.build_audit(pk / "c1", pk / "audit")
    runs["audit"] = sessions(work, "audit", "coder", pk / "audit", se / "audit", "claude-fable-5-1")
    codes += V.codes_for("audit", "audit", pk / "audit", se / "audit", sets, DIGEST)
    X.write_jsonl(work / "codes.jsonl", codes)
    R.build_packets(measured, sets, pk / "reality")
    runs["reality-injected"] = sessions(
        work,
        "reality-injected",
        "reality",
        pk / "reality",
        se / "reality",
        ids=pk / "reality" / "injected.txt",
    )
    got = R.verdicts(pk / "reality", se / "reality", DIGEST)
    first = len(json.loads((pk / "reality" / "key.json").read_text())) + 1
    R.build_controls(measured, sets, got, first, pk / "controls")
    runs["reality-twin"] = sessions(
        work,
        "reality-twin",
        "reality",
        pk / "reality",
        se / "reality",
        ids=pk / "reality" / "twin.txt",
        extra={"RLAW_RESUME": "1"},
    )
    runs["controls"] = sessions(work, "controls", "reality", pk / "controls", se / "controls")
    prior = {
        "packets": {
            "P01": {
                "artefact": "m1",
                "side": "injected",
                "findings": [
                    {"arm": "paired", "item": "ES-3", "verdict": "true_flaw"},
                    {"arm": "generalist", "item": "ES-3", "verdict": "not_a_flaw"},
                    {"arm": "paired", "item": "ZZ-9", "verdict": "true_flaw"},
                ],
            }
        }
    }
    (work / "prior.json").write_text(json.dumps(prior))
    rows, summary = R.score(
        work,
        pk / "reality",
        se / "reality",
        pk / "controls",
        se / "controls",
        work / "prior.json",
        sets,
        None,
        DIGEST,
    )
    X.write_jsonl(work / "reality.jsonl", rows)
    (work / "reality_summary.json").write_text(json.dumps(summary))
    regate = []
    for name, d in fx["sets"].items():
        regate += [{"set": name, **r} for r in G.gate_set(d, X.SETS[name].seed)]
    X.write_jsonl(work / "regate.jsonl", regate)
    m = G.match_all(lines, V.deciding_forms(codes), regate, sets)
    X.write_jsonl(work / "matches.jsonl", m)
    tally = TL.Tally(work, dry_run=True, sets=sets).run()
    return {
        "fx": fx,
        "work": work,
        "lines": lines,
        "flaws": flaws,
        "sets": sets,
        "codes": codes,
        "runs": runs,
        "summary": summary,
        "regate": regate,
        "tally": tally,
        "measured": measured,
    }


def test_every_session_step_ran_and_marked_the_stand_in(pipeline: dict[str, Any]) -> None:
    for name, done in pipeline["runs"].items():
        assert done.returncode == 0, (name, done.stderr)
        out = last_json(done.stdout)
        assert out["standin"] is True
        assert out["sessions"] > 0
    ledger = X.read_jsonl(pipeline["work"] / "ledger" / "ledger.jsonl")
    assert all(r["standin"] for r in ledger)
    assert {r["model_asked"] for r in ledger if r["step"] == "audit"} == {"claude-fable-5-1"}
    assert any(r["try"] == 2 for r in ledger), "the flaky stand-in forces some retries"


def test_retries_fill_every_form(pipeline: dict[str, Any]) -> None:
    rows = [r for r in pipeline["codes"] if r["who"] in ("c1", "c2")]
    assert rows and all(r["form"] is not None for r in rows)
    assert any(r["try"] == "try2" for r in rows)


def test_every_measured_line_is_coded_twice_and_adjudicated_where_disputed(
    pipeline: dict[str, Any],
) -> None:
    measured = {x["line_id"] for x in pipeline["measured"]}
    by = TL.by_line(pipeline["codes"], "measured")
    assert set(by) == measured
    for lid in P.disputed(pipeline["codes"], "measured"):
        assert "adj" in by[lid]


def test_the_slice_never_reaches_a_measured_packet(pipeline: dict[str, Any]) -> None:
    slice_lines = {x["line_id"] for x in pipeline["lines"] if x["pair"] in SLICE[x["set"]]}
    for sub in ("c1", "c2", "adj", "audit", "reality", "controls"):
        key = json.loads((pipeline["work"] / "packets" / sub / "key.json").read_text())
        for k in key.values():
            assert not set(k["findings"].values()) & slice_lines


def test_coder_packets_are_blind(pipeline: dict[str, Any]) -> None:
    for sub in ("c1", "c2", "adj", "audit"):
        res = P.blind_counts(pipeline["work"] / "packets" / sub, pipeline["sets"])
        assert res["blind"], (sub, res)
        assert res["hits"]["findings_item_ids"] == 0


def test_reality_packets_name_no_side_arm_or_run(pipeline: dict[str, Any]) -> None:
    for sub in ("reality", "controls"):
        res = P.blind_counts(pipeline["work"] / "packets" / sub, pipeline["sets"])
        assert res["blind"], (sub, res)


def test_every_packet_carries_the_full_sheet(pipeline: dict[str, Any]) -> None:
    digest = X.sha256_bytes(F.SHEET.encode())
    for p in (pipeline["work"] / "packets").rglob("*.md"):
        assert V.sheet_ok(p.read_text(), digest)


def test_controls_are_built_for_the_clean_twin(pipeline: dict[str, Any]) -> None:
    key = json.loads((pipeline["work"] / "packets" / "controls" / "key.json").read_text())
    lines = {x["line_id"]: x for x in pipeline["lines"]}
    for k in key.values():
        assert k["side"] == "twin" and k["control"] and len(k["findings"]) == 1
        assert lines[k["findings"]["F1"]]["side"] == "injected"


def test_the_prior_agreement_matches_by_pair_side_run_and_item(pipeline: dict[str, Any]) -> None:
    pa = pipeline["summary"]["prior_agreement"]
    assert pa["prior_findings"] == 3
    assert pa["unmatched"] == 1


def test_the_tally_runs_and_refuses_stand_in_output_outside_a_dry_run(
    pipeline: dict[str, Any],
) -> None:
    t = pipeline["tally"]
    assert t["dry_run"] is True
    assert t["primary"]["n"] == t["population"]["real_flaws"]
    assert set(t["readings"]) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert t["decision"]["branch"] in ("priority", "small, targeted library")
    with pytest.raises(X.Refused):
        TL.Tally(pipeline["work"], dry_run=False, sets=pipeline["sets"])


def test_the_regate_repeats_the_fixture_runs_gate_lines(pipeline: dict[str, Any]) -> None:
    fx = pipeline["fx"]
    pin = next(p for p in X.RUNS if p.label == "a-fresh")
    from dataclasses import replace

    run = X.load_run(
        replace(fx["pins"], repo=fx["root"]), pin, fx["runs"]["a-fresh"], fx["digests"]
    )
    fresh = [r for r in pipeline["regate"] if r["set"] == "fresh"]
    assert G.compare(fresh, run)["holds"]
    bad = json.loads(json.dumps(fresh))
    bad[0]["result"]["finding"] = "something else"
    assert G.compare(bad, run)["differ"] == 1
