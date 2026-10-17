"""Tests of tally_rows.py, above all §6 item 10's rule (named against caught).

Run explicitly, from the repository root: uv run pytest -q experiments/R-PG-01/test_tally_rows.py

The pilot's run directory (the instrument's four-role test corpus, never the measurement's) is
read from R_PG_01_PILOT_RUN, or ~/pilot-runs/real-laptop-1. Where neither exists the pilot test
is skipped; where the variable names a directory that does not exist, it fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
_spec = importlib.util.spec_from_file_location("tally_rows", HERE / "tally_rows.py")
assert _spec is not None and _spec.loader is not None
tally_rows = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tally_rows)


# ---- the table is the criteria's, and every id is a Section 2 item of the pinned rubric ----


def criteria_table() -> dict[str, dict[str, tuple[str, ...]]]:
    """§6 item 10's table as CRITERIA.md prints it."""
    lines = [ln.strip() for ln in (HERE / "CRITERIA.md").read_text().splitlines()]
    start = lines.index("| Expected check | control | electrical | firmware | mechanical |")
    table: dict[str, dict[str, tuple[str, ...]]] = {r: {} for r in tally_rows.ROLES}
    for line in lines[start + 2 :]:
        if not line.startswith("| `"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        check = cells[0].strip("`")
        for role, cell in zip(tally_rows.ROLES, cells[1:], strict=True):
            if cell != "—":
                table[role][check] = tuple(i.strip() for i in cell.split(","))
    return table


def test_the_script_s_table_is_the_criteria_s_table() -> None:
    assert criteria_table() == tally_rows.ERROR_ITEMS


def test_every_error_item_is_a_section_2_item_of_the_rubric_at_its_pinned_digest() -> None:
    from physgate.reviewers.rubric import load_rubric

    for role, cells in tally_rows.ERROR_ITEMS.items():
        rubric = load_rubric(REPO / "knowledge", role)
        assert rubric.sha256 == tally_rows.RUBRIC_SHA256[role], role
        sections = {i.id: i.section for i in rubric.items}
        for check, ids in cells.items():
            assert check in tally_rows.CHECKS
            for item in ids:
                assert sections.get(item) == "domain_standards", (role, check, item)


def test_the_pinned_digests_are_the_criteria_s() -> None:
    text = (HERE / "CRITERIA.md").read_text()
    for role, digest in tally_rows.RUBRIC_SHA256.items():
        assert re.search(rf"{role} sha256 `{digest}`", text), role


# ---- the rule, on small built logs ----


def item(i: str, result: str, section: str = "domain_standards") -> dict[str, str]:
    return {"item": i, "section": section, "result": result, "evidence": "-"}


def ran(sid: str, verdict: str, items: list[dict[str, str]], failing: str | None = None) -> dict[str, Any]:
    return {
        "kind": "review_ran",
        "subtask_id": sid,
        "attempt": 1,
        "result": {"verdict": verdict, "items": items, "failing_item": failing},
    }


def unavailable(sid: str, cause: str, retry: bool) -> dict[str, Any]:
    return {"kind": "review_unavailable", "subtask_id": sid, "attempt": 1, "cause": cause, "retry": retry}


def gate(sid: str, *outcomes: tuple[str, str]) -> dict[str, Any]:
    checks = [{"name": name, "outcome": out} for name, out in outcomes]
    verdict = "fail" if any(o == "fail" for _, o in outcomes) else "pass"
    return {"kind": "gate_ran", "subtask_id": sid, "attempt": 1, "result": {"verdict": verdict, "checks": checks}}


def planned(sid: str, role: str) -> dict[str, Any]:
    return {"kind": "subtask_planned", "subtask_id": sid, "assigned_role": role}


#: (artefact, class, role, expected check, injected log lines, twin log lines, row verdict)
CASES: list[tuple[str, str, str, str, list[dict[str, Any]], list[dict[str, Any]], str]] = [
    # Named: D26 cited, the twin cites only D25.
    ("x1", "unit", "control", "units",
     [ran("i1", "fail", [item("D26", "unmet"), item("A7", "unmet", "acceptance_criteria")])],
     [ran("t1", "fail", [item("D25", "unmet"), item("D26", "noted"), item("D26", "met")])], "fail"),
    # Cited, not named: the twin cites the same item.
    ("x2", "magnitude", "electrical", "magnitude",
     [ran("i2", "fail", [item("ES-32", "unmet")])],
     [ran("t2", "fail", [item("ES-32", "unmet")])], "fail"),
    # No error item: an empty cell.
    ("x3", "equilibrium", "firmware", "equilibrium",
     [ran("i3", "fail", [item("DS-30", "unmet")])],
     [ran("t3", "pass", [])], "fail"),
    # Retried once for infrastructure, then a verdict naming DS-30 as its failing item only;
    # the twin gave no verdict, so it cites nothing.
    ("x4", "propagation", "firmware", "propagation",
     [unavailable("i4", "infrastructure", True), ran("i4", "fail", [item("DS-30", "noted")], "DS-30")],
     [unavailable("t4", "timeout", False)], "fail"),
    # No verdict at all: cites nothing, so not named; approved by nobody.
    ("x5", "propagation", "control", "propagation",
     [unavailable("i5", "timeout", False)],
     [ran("t5", "pass", [])], "review_unavailable"),
    # An approval the gate caught, with an indicator confirmed (never an error item).
    ("x6", "unit", "mechanical", "units",
     [ran("i6", "pass", [item("MH-2", "confirmed", "reward_hacking")])],
     [ran("t6", "pass", [])], "pass"),
]


def build(tmp: Path, cases: list[Any] = CASES) -> Path:
    run = tmp / "run"
    (run / "controls").mkdir(parents=True)
    inj: list[dict[str, Any]] = []
    ctl: list[dict[str, Any]] = []
    rows = []
    for n, (aid, cls, role, check, ilines, tlines, verdict) in enumerate(cases, 1):
        rid, cid = f"i{n}", f"t{n}"
        caught = aid != "x2"
        inj += [planned(rid, role), *ilines, gate(rid, (check, "fail" if caught else "pass"), ("thermal", "unchecked"))]
        ctl += [planned(cid, role), *tlines, gate(cid, (check, "pass"))]
        rows.append({
            "artefact": aid, "review_id": rid, "control_id": cid, "error_class": cls,
            "expected_check": check, "reviewer_verdict": verdict,
            "gate_verdict": "fail" if caught else "pass", "gate_blocking": [check] if caught else [],
        })
    write = lambda p, xs: p.write_text("".join(json.dumps(x) + "\n" for x in xs))  # noqa: E731
    write(run / "results.jsonl", rows)
    write(run / "events.jsonl", inj)
    write(run / "controls" / "events.jsonl", ctl)
    return run


def test_the_rule_on_built_logs(tmp_path: Path) -> None:
    out = tally_rows.tally(build(tmp_path), any_count=True)
    per = {p["artefact"]: p for p in out["per_artefact"]}
    assert {a: per[a]["named"] for a in per} == {
        "x1": True, "x2": False, "x3": None, "x4": True, "x5": False, "x6": False,
    }
    assert {a: per[a]["cited_at_all"] for a in per} == {
        "x1": True, "x2": True, "x3": None, "x4": True, "x5": False, "x6": False,
    }
    assert per["x1"]["deciding"] == ["D26"] and per["x4"]["deciding"] == ["DS-30"]
    s10 = out["s6_10_named_against_caught"]
    assert (s10["named"], s10["cited_at_all"], s10["no_error_item"]) == (2, 3, 1)
    assert s10["per_class"]["propagation"] == {
        "named_and_caught": 1, "named_not_caught": 0, "caught_not_named": 1, "neither": 0, "no_error_item": 0,
    }
    assert s10["per_class"]["magnitude"]["neither"] == 1
    assert s10["without_twin_condition"]["per_class"]["magnitude"]["named_not_caught"] == 1
    assert s10["per_role"]["firmware"]["no_error_item"] == 1
    # The primary quantities are untouched by item 10.
    assert (out["A_approved"], out["C_caught_among_approved"], out["kill_criterion_fires"]) == (1, 1, True)
    assert out["s6_9_not_judged_per_role"]["firmware"]["twins"]["review_unavailable"] == [["x4", "timeout"]]
    assert out["s6_9_not_judged_per_role"]["control"]["artefacts"]["review_unavailable"] == [["x5", "timeout"]]


def test_the_denominator_is_forty_unless_lifted(tmp_path: Path) -> None:
    with pytest.raises(tally_rows.TallyError, match="denominator"):
        tally_rows.tally(build(tmp_path))


def test_a_row_that_disagrees_with_its_log_stops_the_tally(tmp_path: Path) -> None:
    run = build(tmp_path)
    rows = [json.loads(x) for x in (run / "results.jsonl").read_text().splitlines()]
    rows[0]["reviewer_verdict"] = "pass"
    (run / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(tally_rows.TallyError, match="disagrees"):
        tally_rows.tally(run, any_count=True)


# ---- the rule on the pilot's own run directory ----


def pilot_run() -> Path:
    given = os.environ.get("R_PG_01_PILOT_RUN")
    if given:
        path = Path(given).expanduser()
        assert path.is_dir(), f"R_PG_01_PILOT_RUN names no directory: {path}"
        return path
    path = Path.home() / "pilot-runs" / "real-laptop-1"
    if not path.is_dir():
        pytest.skip("the pilot's run directory is not on this machine")
    return path


def test_the_pilot_gives_three_of_four_named_and_four_of_four_without_the_twin() -> None:
    pilot = pilot_run()
    out = tally_rows.tally(pilot / "run", corpus_dir=pilot / "corpus", any_count=True)
    per = {p["artefact"]: p for p in out["per_artefact"]}
    assert {a: per[a]["named"] for a in per} == {"c1": True, "e1": False, "f1": True, "k1": True}
    assert {a: per[a]["deciding"] for a in per} == {"c1": ["D26"], "e1": [], "f1": ["DS-30"], "k1": ["MS-2"]}
    s10 = out["s6_10_named_against_caught"]
    assert (s10["named"], s10["cited_at_all"], s10["no_error_item"]) == (3, 4, 0)
    assert s10["per_role"]["electrical"]["caught_not_named"] == 1
    assert (out["A_approved"], out["C_caught_among_approved"]) == (0, 0)
    assert out["s6_7_twin_reviews"] == {"outcomes": {"fail": 4}, "refused": 4, "of": 4}
    assert out["controls_gate_failing"] == 0
    assert list(out["s6_4_propagation_edges_by_domain_pair"]) == ["firmware -> control"]
