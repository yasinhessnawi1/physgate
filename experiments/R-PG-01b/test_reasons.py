"""Tests of the rejection reading (§6) on invented runs: the lines, the packets, the controls, the
sessions (with a scripted stand-in for the binary, never a model), and the classes and bars.

Run explicitly, in the run checkout: ``uv run --frozen pytest -q experiments/R-PG-01b``.
"""

from __future__ import annotations

import json
import os
import random
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import reasons_extract as X  # noqa: E402
import reasons_packets as P  # noqa: E402
import reasons_tally as Y  # noqa: E402
import testsupport as T  # noqa: E402

# ---- an invented corpus and runs ----


def q(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "design: invented"}


BASE = [
    {"id": "electrical.motor", "quantities": {"stall_current": q(1.5, "A")}},
    {"id": "electrical.driver", "quantities": {"current_limit": q(1.8, "A")}},
    {"id": "control.loop", "quantities": {"sample_rate": q(100, "Hz")}},
]
ARTEFACTS = {
    "a1": {
        "assigned_role": "electrical",
        "edge": None,
        "clean": {
            "nodes": [{"id": "electrical.motor", "quantities": {"stall_current": q(1.6, "A")}}]
        },
        "injected": {
            "nodes": [{"id": "electrical.motor", "quantities": {"stall_current": q(16, "A")}}]
        },
    },
    "a2": {
        "assigned_role": "control",
        "edge": None,
        "clean": {"nodes": [{"id": "control.loop", "quantities": {"sample_rate": q(200, "Hz")}}]},
        "injected": {"nodes": [{"id": "control.loop", "quantities": {"sample_rate": q(200, "s")}}]},
    },
}
ROWS = {
    "R1.01": {"quantity": "stall", "value": 1.5, "unit": "A", "url": "https://e.invalid"},
    "R8.01": {"quantity": "rates", "value": None, "unit": None, "url": "https://e.invalid"},
}
IDS = {
    "electrical": {"ES-31", "ES-32"},
    "control": {"D25", "D26"},
    "firmware": set(),
    "mechanical": set(),
}
SPEC = {"a1": ("unit", "units"), "a2": ("magnitude", "magnitude")}


def corpus(tmp: Path) -> Path:
    root = tmp / "corpus"
    (root / "artefacts").mkdir(parents=True)
    (root / "base.json").write_text(json.dumps({"label": "x", "nodes": BASE}))
    for aid, a in ARTEFACTS.items():
        (root / "artefacts" / f"{aid}.json").write_text(json.dumps({"id": aid, **a}))
    (root / "sources.json").write_text(json.dumps({"label": "s", "rows": ROWS}))
    return root


def run(
    tmp: Path, name: str, reviews: dict[tuple[str, str], tuple[str, list[dict[str, str]]]]
) -> Path:
    """``reviews``: (artefact, side) -> (verdict, items)."""
    out = tmp / name
    inj, ctl, rows = [], [], []
    for n, aid in enumerate(sorted(ARTEFACTS), 1):
        role = ARTEFACTS[aid]["assigned_role"]
        rid, cid = f"r{n:012x}", f"r{n + 50:012x}"
        cls, check = SPEC[aid]
        v, items = reviews[(aid, "injected")]
        inj += [T.planned(rid, role), T.ran(rid, v, items), T.gate(rid, (check, "fail"))]
        tv, titems = reviews[(aid, "twin")]
        ctl += [T.planned(cid, role), T.ran(cid, tv, titems), T.gate(cid, (check, "pass"))]
        rows.append(
            {
                "artefact": aid,
                "review_id": rid,
                "control_id": cid,
                "error_class": cls,
                "expected_check": check,
                "reviewer_verdict": v,
                "gate_verdict": "fail",
                "gate_blocking": [check],
            }
        )
    T.write_jsonl(out / "results.jsonl", rows)
    T.write_jsonl(out / "events.jsonl", inj)
    T.write_jsonl(out / "controls" / "events.jsonl", ctl)
    return out


def unmet(item: str, evidence: str, section: str = "domain_standards") -> dict[str, str]:
    return T.item(item, "unmet", section, evidence)


REVIEWS = {
    # a1 injected: names its error (ES-31, the twin does not cite it): P
    ("a1", "injected"): (
        "fail",
        [
            unmet("ES-31", "ES-31: the motor stall_current of 16 A is flawed"),
            unmet("ES-32", "the driver current_limit is fine per R8.01"),
        ],
    ),
    ("a1", "twin"): ("fail", [unmet("ES-32", "the motor stall_current is fine")]),
    ("a2", "injected"): ("blocked", []),
    ("a2", "twin"): ("pass", []),
}


def work(tmp: Path) -> Path:
    runs = {"I1": run(tmp, "i1", REVIEWS), "F1": run(tmp, "f1", REVIEWS)}
    lines, reviews, counts = X.extract(runs, corpus(tmp), IDS, any_count=True)
    w = tmp / "work"
    w.mkdir()
    (w / "lines.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (w / "reviews.jsonl").write_text("".join(json.dumps(x) + "\n" for x in reviews))
    (w / "design.json").write_text(json.dumps(X.design_record(corpus(tmp / "c2"))))
    return w


# ---- the lines ----


def test_lines_are_numbered_by_round_arm_side_artefact_and_position(tmp_path: Path) -> None:
    lines = [json.loads(x) for x in (work(tmp_path) / "lines.jsonl").read_text().splitlines()]
    order = [(x["arm"], x["side"], x["artefact"], x["position"]) for x in lines]
    assert order == [
        ("I", "injected", "a1", 0),
        ("I", "injected", "a1", 1),
        ("I", "twin", "a1", 0),
        ("F", "injected", "a1", 0),
        ("F", "injected", "a1", 1),
        ("F", "twin", "a1", 0),
    ]
    assert [x["line_id"] for x in lines] == [f"L000{n}" for n in range(1, 7)]
    first = lines[0]
    assert first["text"] == "[rule]: the motor stall_current of 16 A is flawed"
    assert first["locus"] == [["electrical.motor", "stall_current"]]
    assert first["error_item_line"] is True and lines[1]["error_item_line"] is True
    assert lines[1]["tag_missing_row"] is True and first["tag_missing_row"] is False


def test_the_failing_item_joins_its_entry_when_not_already_a_line() -> None:
    result = {
        "items": [T.item("A1", "met"), T.item("B2", "noted"), T.item("C3", "unmet")],
        "failing_item": "B2",
    }
    assert [p for p, _ in X.rejecting_entries(result)] == [1, 2]


def test_a_pair_is_named_by_its_quantity_and_its_node_or_its_short_name() -> None:
    assert X.names_pair("motor stall_current too high", "electrical.motor", "stall_current")
    assert X.names_pair("electrical.motor: stall_current", "electrical.motor", "stall_current")
    assert not X.names_pair("motorised stall_current", "electrical.motor", "stall_current")
    assert not X.names_pair("motor stall current", "electrical.motor", "stall_current")


def test_changed_pairs_are_those_the_patches_write_differently() -> None:
    d = X.Designs.__new__(X.Designs)
    d.base, d.artefacts = BASE, {k: dict(v) for k, v in ARTEFACTS.items()}
    assert d.changed("a1") == {("electrical.motor", "stall_current")}
    d.artefacts["a1"]["edge"] = {"source": "electrical.motor", "target": "electrical.driver"}
    assert ("electrical.driver", "current_limit") in d.changed("a1")


# ---- the packets ----

SHEET = b"| Row | Quantity |\n| R1.01 | stall |\n"


def test_packets_pool_a_version_s_lines_shuffled_by_random_37(tmp_path: Path) -> None:
    w = work(tmp_path)
    key = P.build_packets(w, tmp_path / "packets", SHEET)
    # blocked and passing reviews are not adjudicated; the injected version comes first
    assert [(k["artefact"], k["side"]) for _, k in sorted(key.items())] == [
        ("a1", "injected"),
        ("a1", "twin"),
    ]
    ids = ["L0001", "L0002", "L0004", "L0005"]
    random.Random(37).shuffle(ids)
    assert list(key["Q0001"]["findings"].values()) == ids
    text = (tmp_path / "packets" / "Q0001.md").read_text()
    assert text.endswith(P.SHEET_MARK + SHEET.decode())
    assert "A reviewer of the electrical domain rejected" in text
    assert (tmp_path / "packets" / "injected.txt").read_text() == "Q0001\n"
    found = P.blind(w, tmp_path / "packets", SHEET)
    assert found["blind"] and found["not_their_template"] == 0
    (tmp_path / "packets" / "Q0002.md").write_text(
        text.replace("## Findings", "## Findings (arm F)")
    )
    assert P.blind(w, tmp_path / "packets", SHEET)["not_their_template"] == 1


def test_the_prompt_and_schema_are_r_law_01_s_at_their_digests() -> None:
    prompt, schema = P.prompt_and_schema()
    assert "\n" not in prompt and prompt.startswith("You are an experienced mechatronics")
    assert schema["required"] == ["findings"]


def _answers(sessions: Path, pid: str, forms: dict[str, tuple[str, str]], tr: int = 1) -> None:
    findings = [{"id": f, "verdict": v, "origin": o, "reason": "r"} for f, (v, o) in forms.items()]
    sessions.mkdir(exist_ok=True)
    result = {"type": "result", "is_error": False, "structured_output": {"findings": findings}}
    (sessions / f"{pid}.try{tr}.json").write_text(json.dumps(result))


def test_the_rejection_control_draws_one_eligible_line_per_injected_version(tmp_path: Path) -> None:
    w = work(tmp_path)
    key = P.build_packets(w, tmp_path / "packets", SHEET)
    labels = {lid: f for f, lid in key["Q0001"]["findings"].items()}
    forms = {f: ("not_a_flaw", "n/a") for f in key["Q0001"]["findings"]}
    forms[labels["L0001"]] = ("true_flaw", "introduced")  # locus: the changed pair alone
    forms[labels["L0002"]] = ("true_flaw", "introduced")  # locus: an unchanged pair
    _answers(tmp_path / "s", "Q0001", forms)
    ctl = P.build_controls(w, tmp_path / "packets", tmp_path / "s", tmp_path / "ctl", SHEET)
    assert ctl == {
        "Q0003": {"artefact": "a1", "side": "twin", "control": True, "findings": {"F1": "L0001"}}
    }
    text = (tmp_path / "ctl" / "Q0003.md").read_text()
    assert '"value": 1.6' in text and '"value": 16' not in text  # the clean twin's patch


def test_a_line_is_eligible_for_the_control_only_if_every_locus_pair_is_changed() -> None:
    changed = {("electrical.motor", "stall_current")}
    line = {"side": "injected", "locus": [["electrical.motor", "stall_current"]]}
    true = {"verdict": "true_flaw", "origin": "introduced"}
    assert P.eligible(line, true, changed)
    partly = {**line, "locus": [*line["locus"], ["control.loop", "sample_rate"]]}
    assert not P.eligible(partly, true, changed)
    assert not P.eligible({**line, "locus": []}, true, changed)
    assert not P.eligible({**line, "side": "twin"}, true, changed)
    assert not P.eligible(line, {**true, "origin": "both"}, changed)


def test_a_retry_s_form_is_used_where_the_first_try_lacks_one(tmp_path: Path) -> None:
    w = work(tmp_path)
    key = P.build_packets(w, tmp_path / "packets", SHEET)
    fids = list(key["Q0001"]["findings"])
    _answers(tmp_path / "s", "Q0001", {fids[0]: ("true_flaw", "both")})
    _answers(tmp_path / "s", "Q0001", {f: ("undecidable", "n/a") for f in fids}, tr=2)
    got = P.verdicts(tmp_path / "packets", tmp_path / "s")
    lid0 = key["Q0001"]["findings"][fids[0]]
    assert got[lid0] == {"packet": "Q0001", "verdict": "true_flaw", "origin": "both", "try": "try1"}
    assert {v["try"] for k, v in got.items() if k != lid0 and v["packet"] == "Q0001"} == {"try2"}


# ---- the sessions, with a stand-in ----

STANDIN = """#!{python}
import json, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
packet = sys.stdin.read()
ids = re.findall(r"^### (F[0-9]+)$", packet, re.M)
mode = open(os.path.join(here, "mode")).read().strip()
if mode == "fail":
    print(json.dumps({{"type": "result", "is_error": True, "api_error_status": 500}}))
    sys.exit(1)
seen = os.path.join(here, "seen")
first = not os.path.exists(seen)
open(seen, "a").write("x")
if mode == "invalid-once" and first:
    ids = ids[:-1]
findings = [{{"id": i, "verdict": "not_a_flaw", "origin": "n/a", "reason": "r"}} for i in ids]
assert os.environ.get("{name}", "").startswith("{prefix}")
assert os.listdir(".") == [] and os.environ["HOME"] != os.getcwd()
print(json.dumps({{"type": "result", "is_error": False, "terminal_reason": "completed",
                  "usage": {{"input_tokens": 100, "output_tokens": 20}},
                  "structured_output": {{"findings": findings}}}}))
"""


def _sessions(tmp: Path, mode: str, ledger_text: str = "") -> tuple[int, Path, dict[str, Any]]:
    w = work(tmp)
    P.build_packets(w, tmp / "packets", SHEET)
    standin = tmp / "standin" / "claude"
    standin.parent.mkdir()
    standin.write_text(
        STANDIN.format(python=sys.executable, name=T.TOKEN_NAME, prefix=T.TOKEN_PREFIX)
    )
    standin.chmod(standin.stat().st_mode | stat.S_IXUSR)
    (standin.parent / "mode").write_text(mode)
    prompts = tmp / "prompts"
    prompt, schema = P.prompt_and_schema()
    prompts.mkdir()
    (prompts / "reality_prompt.txt").write_text(prompt)
    (prompts / "reality_schema.json").write_text(json.dumps(schema))
    env_file = tmp / "run.env"
    env_file.write_text(T.token_line(T.TOKEN_PREFIX + "z" * 30) + "\n")
    ledger = tmp / "ledger" / "ledger.jsonl"
    ledger.parent.mkdir()
    ledger.write_text(ledger_text)
    ids = tmp / "packets" / "injected.txt"
    done = subprocess.run(
        [
            str(HERE / "reasons_sessions.sh"),
            "run",
            str(tmp / "packets"),
            str(tmp / "out"),
            str(ids),
        ],
        env={
            **os.environ,
            "RPB_PROMPTS": str(prompts),
            "RPB_LEDGER": str(ledger),
            "RPB_STANDIN": str(standin),
            "RPB_ENV_FILE": str(env_file),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    summary = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    return done.returncode, ledger, summary


def test_each_packet_is_one_session_and_each_call_one_ledger_line(tmp_path: Path) -> None:
    code, ledger, summary = _sessions(tmp_path, "ok")
    rows = C.read_jsonl(ledger)
    assert code == 0 and summary["sessions"] == 1 and summary["tries"] == 1
    assert rows[0]["tokens"] == 120 and rows[0]["valid"] and rows[0]["standin"]
    assert (tmp_path / "out" / "Q0001.try1.json").is_file()


def test_a_try_missing_a_form_is_tried_once_more(tmp_path: Path) -> None:
    code, ledger, summary = _sessions(tmp_path, "invalid-once")
    assert code == 0 and summary["tries"] == 2 and summary["invalid_tries"] == 1
    assert (tmp_path / "out" / "Q0001.try2.json").is_file()


def test_a_failed_call_stops_the_reading(tmp_path: Path) -> None:
    code, ledger, summary = _sessions(tmp_path, "fail")
    assert code == 4 and summary["failed_calls"] == 1
    assert (ledger.parent / "STOPPED").is_file()


def test_the_token_guard_voids_the_reading_at_30_m(tmp_path: Path) -> None:
    filled = json.dumps({"packet": "Q9999", "try": 1, "tokens": 30_000_000}) + "\n"
    code, ledger, _ = _sessions(tmp_path, "ok", filled)
    assert code == 3 and (ledger.parent / "VOID").is_file()
    assert not (tmp_path / "out" / "Q0001.try1.json").exists()


# ---- the classes and the bars ----


def review(outcome: str, side: str = "injected", named: bool | None = False) -> dict[str, Any]:
    return {"outcome": outcome, "side": side, "named": named}


def line(lid: str) -> dict[str, Any]:
    return {"line_id": lid}


@pytest.mark.parametrize(
    ("rv", "verdicts", "cls"),
    [
        (review("blocked", named=True), {}, "B"),
        (review("fail", named=True), {"L1": ("not_a_flaw", "n/a")}, "P"),
        (
            review("fail", "twin", None),
            {"L1": ("true_flaw", "both"), "L2": ("true_flaw", "already_in_base")},
            "O-introduced",
        ),
        (
            review("fail"),
            {"L1": ("true_flaw", "already_in_base"), "L2": ("not_a_flaw", "n/a")},
            "O-base",
        ),
        (review("fail"), {"L1": ("true_flaw", "n/a")}, "O-unsplit"),
        (review("fail"), {"L1": ("not_a_flaw", "n/a"), "L2": ("not_a_flaw", "n/a")}, "N"),
        (review("fail"), {"L1": ("not_a_flaw", "n/a"), "L2": ("undecidable", "n/a")}, "U"),
        (review("fail"), {"L1": ("not_a_flaw", "n/a"), "L2": None}, "U"),
        (review("fail"), {}, "U"),
        (review("pass"), {"L1": ("true_flaw", "introduced")}, None),
    ],
    ids=[
        "blocked",
        "named",
        "o-introduced",
        "o-base",
        "o-unsplit",
        "n",
        "u",
        "u-missing",
        "u-no-line",
        "pass",
    ],
)
def test_one_class_per_rejection_the_first_that_holds(
    rv: dict[str, Any], verdicts: dict[str, Any], cls: str | None
) -> None:
    lines = [line(k) for k in verdicts]
    got = {k: {"verdict": v[0], "origin": v[1]} for k, v in verdicts.items() if v is not None}
    assert Y.classify(rv, lines, got) == cls


def test_a_control_needs_ten_cases_and_seventy_percent() -> None:
    assert Y.bar(9, 9)["status"] == "not checked"
    assert Y.bar(7, 10)["status"] == "met" and Y.bar(6, 10)["status"] == "missed"
    met, missed, unchecked = Y.bar(7, 10), Y.bar(6, 10), Y.bar(1, 2)
    assert Y.label(met, met) == "reliable"
    assert Y.label(met, missed) == "unreliable" and Y.label(missed, unchecked) == "unreliable"
    assert Y.label(met, unchecked) == "unchecked"


def test_the_tally_classes_every_rejection_and_voids_at_the_guard(tmp_path: Path) -> None:
    w = work(tmp_path)
    key = P.build_packets(w, tmp_path / "packets", SHEET)
    for pid, k in key.items():
        _answers(tmp_path / "s", pid, {f: ("not_a_flaw", "n/a") for f in k["findings"]})
    ledger = tmp_path / "ledger" / "ledger.jsonl"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps({"tokens": 5}) + "\n")
    out = Y.tally(
        w, tmp_path / "packets", tmp_path / "s", tmp_path / "none", tmp_path / "none", ledger
    )
    per = out["classes"]
    assert per["round 1, arm I, injected"]["P"] == 1 and per["round 1, arm I, injected"]["B"] == 1
    assert per["round 1, arm F, twin"]["N"] == 1
    assert out["twins_corrected_refusal_rate"]["round 1, arm I"]["N"] == 1
    assert out["split"] == "unchecked" and out["D4"]["label"] == "the O/N split is unchecked"
    assert out["descriptive"]["P_error_item_lines_not_a_flaw"] == 4
    (ledger.parent / "VOID").write_text("guard")
    void = Y.tally(
        w, tmp_path / "packets", tmp_path / "s", tmp_path / "none", tmp_path / "none", ledger
    )
    assert void["void"] is True and "classes" not in void
