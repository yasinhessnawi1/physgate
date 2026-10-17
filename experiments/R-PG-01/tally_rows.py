"""R-PG-01: the rows and both run logs to A, C, the kill reading and every figure of §6.

Usage, after the run has ended and never before:

    uv run python -I tally_rows.py <run-dir> [--corpus <corpus-dir>] [--any-count]

Read-only. Prints one JSON document. It reads the instrument's ``results.jsonl``, the
injected log ``events.jsonl`` and the controls log ``controls/events.jsonl`` as plain JSON
lines; ``--corpus`` is needed only for §6 item 4 (the propagation edges by domain pair).
``--any-count`` lifts the denominator check, for a test corpus only.

Every quantity follows the criteria's definitions:

- **A**: rows whose review came to ``pass``. **Caught**: the injected artefact's gate result
  holds at least one record with outcome ``fail`` (an ``unchecked`` record never counts); this is
  held to the row's ``gate_verdict``, and a disagreement stops the script. **C**: caught among A.
  **Kill**: C < 10 or A < 4.
- **§6 item 10, named against caught**, decided from item ids alone, with no language model:
  - a review's *cited items* are those its final review line records with the result ``unmet``
    or ``confirmed``, and its failing item. The final line is the subtask's last
    ``review_ran`` or ``review_unavailable`` line; a ``review_unavailable`` line cites nothing;
  - an artefact's *error items* are ``ERROR_ITEMS[role][expected_check]``, its role being the
    ``assigned_role`` its ``subtask_planned`` line records;
  - *named*: the review cites an error item that the clean twin's review does not cite;
  - *cited at all*: the review cites an error item, twin or not (reported beside it);
  - an artefact whose cell is empty has *no error item*, and is neither named nor missed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

#: §6 item 10's table, verbatim: by role, then by expected check. An absent check is an
#: empty cell. Every id is a Section 2 item of that role's rubric at the digests below.
ERROR_ITEMS: dict[str, dict[str, tuple[str, ...]]] = {
    "control": {
        "units": ("D25", "D26"),
        "magnitude": ("D25", "D27"),
        "propagation": ("D28",),
    },
    "electrical": {
        "units": ("ES-31", "ES-32"),
        "magnitude": ("ES-32",),
        "power": ("ES-7", "ES-33"),
        "conservation": ("ES-7", "ES-9", "ES-33"),
        "thermal": ("ES-19", "ES-20", "ES-35"),
        "propagation": ("ES-34",),
    },
    "firmware": {
        "units": ("DS-27",),
        "magnitude": ("DS-27",),
        "propagation": ("DS-30",),
    },
    "mechanical": {
        "units": ("MS-2",),
        "magnitude": ("MS-3",),
        "equilibrium": ("MS-4",),
        "conservation": ("MS-3", "MS-26"),
        "propagation": ("MS-5",),
    },
}
#: The promoted rubrics the table was drawn from (§2).
RUBRIC_SHA256 = {
    "control": "18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5",
    "electrical": "a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3",
    "firmware": "e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a",
    "mechanical": "3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa",
}
CHECKS = ("units", "magnitude", "equilibrium", "power", "conservation", "thermal", "propagation")
CLASSES = ("unit", "magnitude", "equilibrium", "propagation")
ROLES = ("control", "electrical", "firmware", "mechanical")
DENOMINATOR = 40
CITING_RESULTS = ("unmet", "confirmed")
REVIEW_LINES = ("review_ran", "review_unavailable")


class TallyError(Exception):
    """The run directory is not one this script can read faithfully."""


def read_log(path: Path) -> list[dict[str, Any]]:
    """A run log's lines, in the order written."""
    if not path.is_file():
        raise TallyError(f"no run log at {path}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Log:
    """One run log, indexed by subtask: its role, its final review line and its gate result."""

    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.role: dict[str, str] = {}
        self.review: dict[str, dict[str, Any]] = {}
        self.gate: dict[str, dict[str, Any]] = {}
        self.gate_lines = 0
        for line in lines:
            kind, sid = line.get("kind"), line.get("subtask_id")
            if kind == "subtask_planned":
                if sid in self.role:
                    raise TallyError(f"subtask {sid} is planned twice")
                self.role[sid] = line["assigned_role"]
            elif kind in REVIEW_LINES:
                self.review[sid] = line
            elif kind == "gate_ran":
                self.gate[sid] = line["result"]
                self.gate_lines += 1


def cited(line: dict[str, Any] | None) -> frozenset[str]:
    """The items a review cites: unmet or confirmed, and its failing item."""
    if line is None or line["kind"] != "review_ran":
        return frozenset()
    result = line["result"]
    items = {i["item"] for i in result["items"] if i["result"] in CITING_RESULTS}
    if result.get("failing_item"):
        items.add(result["failing_item"])
    return frozenset(items)


def outcome(line: dict[str, Any] | None) -> tuple[str, str | None]:
    """A review's outcome and its cause, as the instrument derives them."""
    if line is None:
        return "missing", "no review line"
    if line["kind"] == "review_unavailable":
        return "review_unavailable", line["cause"]
    verdict = line["result"]["verdict"]
    return verdict, ("blocking_spec_defect" if verdict == "blocked" else None)


def error_items(role: str, check: str) -> tuple[str, ...]:
    """§6 item 10's cell for this role and expected check; empty where the table has none."""
    if role not in ERROR_ITEMS or check not in CHECKS:
        raise TallyError(f"no table row for role {role!r} and check {check!r}")
    return ERROR_ITEMS[role].get(check, ())


def naming(role: str, check: str, review: frozenset[str], twin: frozenset[str]) -> dict[str, Any]:
    """Whether a review named its artefact's error, with and without the twin condition."""
    cell = error_items(role, check)
    if not cell:
        return {"error_items": [], "named": None, "cited_at_all": None, "deciding": []}
    hit = set(cell) & review
    deciding = sorted(hit - twin)
    return {
        "error_items": list(cell),
        "named": bool(deciding),
        "cited_at_all": bool(hit),
        "deciding": deciding,
    }


def _records(gate: dict[str, Any]) -> list[dict[str, Any]]:
    return list(gate.get("checks", []))


def _two_by_two(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter()
    for r in rows:
        if r[key] is None:
            counts["no_error_item"] += 1
        elif r[key] and r["caught"]:
            counts["named_and_caught"] += 1
        elif r[key]:
            counts["named_not_caught"] += 1
        elif r["caught"]:
            counts["caught_not_named"] += 1
        else:
            counts["neither"] += 1
    keys = ("named_and_caught", "named_not_caught", "caught_not_named", "neither", "no_error_item")
    return {k: counts[k] for k in keys}


def tally(run_dir: Path, corpus_dir: Path | None = None, any_count: bool = False) -> dict[str, Any]:
    """Every figure of §5 and §6 from one instrument run directory."""
    rows = read_log(run_dir / "results.jsonl")
    if len(rows) != DENOMINATOR and not any_count:
        raise TallyError(f"{len(rows)} rows; the denominator is {DENOMINATOR}")
    injected = Log(read_log(run_dir / "events.jsonl"))
    controls = Log(read_log(run_dir / "controls" / "events.jsonl"))

    per: list[dict[str, Any]] = []
    for row in rows:
        rid, cid = row["review_id"], row["control_id"]
        if rid not in injected.role or rid not in injected.gate:
            raise TallyError(f"{row['artefact']}: no planned line or gate line in the injected log")
        if cid not in controls.gate:
            raise TallyError(f"{row['artefact']}: no gate line for its twin in the controls log")
        role = injected.role[rid]
        records = _records(injected.gate[rid])
        caught = any(rec["outcome"] == "fail" for rec in records)
        if caught != (row["gate_verdict"] == "fail"):
            raise TallyError(f"{row['artefact']}: failing records disagree with the row's verdict")
        twin_records = _records(controls.gate[cid])
        verdict, cause = outcome(injected.review.get(rid))
        if verdict != row["reviewer_verdict"]:
            raise TallyError(f"{row['artefact']}: the log's review outcome disagrees with the row")
        twin_verdict, twin_cause = outcome(controls.review.get(cid))
        review_items = cited(injected.review.get(rid))
        twin_items = cited(controls.review.get(cid))
        per.append(
            {
                "artefact": row["artefact"],
                "class": row["error_class"],
                "role": role,
                "expected_check": row["expected_check"],
                "review": verdict,
                "review_cause": cause,
                "twin_review": twin_verdict,
                "twin_review_cause": twin_cause,
                "approved": verdict == "pass",
                "caught": caught,
                "gate_blocking": list(row["gate_blocking"]),
                "unchecked_records": sum(rec["outcome"] == "unchecked" for rec in records),
                "unchecked_on_expected_check": any(
                    rec["outcome"] == "unchecked" and rec["name"] == row["expected_check"]
                    for rec in records
                ),
                "records": len(records),
                "twin_gate_failing_records": sum(rec["outcome"] == "fail" for rec in twin_records),
                "twin_records": len(twin_records),
                "cited_by_review": sorted(review_items),
                "cited_by_twin_review": sorted(twin_items),
                **naming(role, row["expected_check"], review_items, twin_items),
            }
        )

    a = [p for p in per if p["approved"]]
    c = [p for p in a if p["caught"]]
    caught_all = [p for p in per if p["caught"]]

    def by(key: str, values: tuple[str, ...], subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {v: [p for p in subset if p[key] == v] for v in values}

    def a_and_c(key: str, values: tuple[str, ...]) -> dict[str, dict[str, int]]:
        return {
            v: {
                "artefacts": sum(p[key] == v for p in per),
                "A": sum(p[key] == v for p in a),
                "C": sum(p[key] == v for p in c),
            }
            for v in values
        }

    def not_judged(kind: str, rows_: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
        verdict_key, cause_key = (
            ("review", "review_cause") if kind == "artefact" else ("twin_review", "twin_review_cause")
        )
        return {
            "blocked": [[p["artefact"], p[cause_key]] for p in rows_ if p[verdict_key] == "blocked"],
            "review_unavailable": [
                [p["artefact"], p[cause_key]] for p in rows_ if p[verdict_key] == "review_unavailable"
            ],
        }

    out: dict[str, Any] = {
        "rows": len(per),
        "A_approved": len(a),
        "C_caught_among_approved": len(c),
        "kill_criterion_fires": len(c) < 10 or len(a) < 4,
        "review_outcomes": dict(sorted(Counter(p["review"] for p in per).items())),
        "listed_not_approved_without_a_verdict": [
            [p["artefact"], p["review"], p["review_cause"]]
            for p in per
            if p["review"] in ("blocked", "review_unavailable", "missing")
        ],
        "s6_1_per_class": a_and_c("class", CLASSES),
        "s6_2_expected_check": {
            "among_C": sum(p["expected_check"] in p["gate_blocking"] for p in c),
            "C": len(c),
            "among_all_caught": sum(p["expected_check"] in p["gate_blocking"] for p in caught_all),
            "all_caught": len(caught_all),
            "caught_on_another_check": [
                [p["artefact"], p["expected_check"], p["gate_blocking"]]
                for p in caught_all
                if p["expected_check"] not in p["gate_blocking"]
            ],
        },
        "s6_3_unchecked": {
            k: {
                "unchecked_records": sum(p["unchecked_records"] for p in v),
                "not_judged_on_expected_check": sorted(
                    p["artefact"] for p in v if not p["caught"] and p["unchecked_on_expected_check"]
                ),
            }
            for k, v in by("class", CLASSES, per).items()
        },
        "s6_4_propagation_edges_by_domain_pair": _edges(per, corpus_dir),
        "s6_5_gate_caught_by_review_outcome": {
            v: {"artefacts": sum(p["review"] == v for p in per), "caught": sum(p["caught"] for p in per if p["review"] == v)}
            for v in ("pass", "fail", "blocked", "review_unavailable")
        },
        "s6_6_gate_events_and_records": {
            "injected_gate_lines": injected.gate_lines,
            "controls_gate_lines": controls.gate_lines,
            "injected_records": sum(p["records"] for p in per),
            "injected_failing_records": sum(
                sum(rec["outcome"] == "fail" for rec in _records(injected.gate[r["review_id"]])) for r in rows
            ),
            "controls_records": sum(p["twin_records"] for p in per),
            "controls_failing_records": sum(p["twin_gate_failing_records"] for p in per),
            "artefacts_caught": len(caught_all),
        },
        "s6_7_twin_reviews": {
            "outcomes": dict(sorted(Counter(p["twin_review"] for p in per).items())),
            "refused": sum(p["twin_review"] == "fail" for p in per),
            "of": len(per),
        },
        "s6_8_per_role": a_and_c("role", ROLES),
        "s6_9_not_judged_per_role": {
            role: {"artefacts": not_judged("artefact", v), "twins": not_judged("twin", v)}
            for role, v in by("role", ROLES, per).items()
        },
        "s6_10_named_against_caught": {
            "named": sum(p["named"] is True for p in per),
            "cited_at_all": sum(p["cited_at_all"] is True for p in per),
            "no_error_item": sum(p["named"] is None for p in per),
            "per_class": {k: _two_by_two(v, "named") for k, v in by("class", CLASSES, per).items()},
            "per_role": {k: _two_by_two(v, "named") for k, v in by("role", ROLES, per).items()},
            "without_twin_condition": {
                "per_class": {k: _two_by_two(v, "cited_at_all") for k, v in by("class", CLASSES, per).items()},
                "per_role": {k: _two_by_two(v, "cited_at_all") for k, v in by("role", ROLES, per).items()},
            },
        },
        "controls_gate_failing": sum(p["twin_gate_failing_records"] > 0 for p in per),
        "per_artefact": per,
    }
    return out


def _edges(per: list[dict[str, Any]], corpus_dir: Path | None) -> dict[str, Any] | None:
    """§6 item 4: the propagation class's edges by domain pair, with A and C. Needs the corpus."""
    if corpus_dir is None:
        return None
    from physgate.evaluation.inject.corpus import load_corpus  # only after the run

    corpus = load_corpus(corpus_dir.resolve())
    edges = {a.id: a.edge for a in corpus.artefacts if a.edge is not None}
    pairs: dict[str, dict[str, Any]] = defaultdict(lambda: {"artefacts": [], "A": 0, "C": 0})
    for p in per:
        if p["class"] != "propagation":
            continue
        edge = edges[p["artefact"]]
        pair = pairs[f"{edge.source.split('.')[0]} -> {edge.target.split('.')[0]}"]
        pair["artefacts"].append(p["artefact"])
        pair["A"] += p["approved"]
        pair["C"] += p["approved"] and p["caught"]
    return dict(sorted(pairs.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--any-count", action="store_true", help="a test corpus only")
    args = parser.parse_args(argv)
    try:
        out = tally(args.run_dir.resolve(), args.corpus, args.any_count)
    except TallyError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
