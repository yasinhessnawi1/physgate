"""R-LAW-01: the pre-registered figures the frozen tally does not compute. Written after the run.

Usage (from the repository root, with the project environment):

    uv run python -I experiments/R-LAW-01/law_report.py <data dir> [--dry-run]

Added on 23.10.2026, after the run and after the tally, to report what `CRITERIA.md` asks for and
`law_tally.py` leaves out. Every figure here is "reported, never a result": none changes a code, a
share, a label or the decision. It reuses the tally's own classes and functions and reads only the
published data: the files of ``<data dir>`` (``experiments/R-LAW-01/data/``), the committed
``slice.json`` beside it, and the frozen corpora the tally reads too. It writes
``<data dir>/report_extra.json``.

- **§6**, per prompt version (v0 in round 1, v1 in round 2): the slice's κ between the two coders,
  its disagreement counts and its L share. The slice has no reality verdicts, so every slice line
  is taken as real; its lines are coded by §5.7 rule 1 and turned into G by §5.6, with the gate
  match computed from that round's deciding forms and the published re-gate records; its flaws are
  the flaws of ``flaws.jsonl`` cut to their slice lines, aggregated by §5.7 rule 2.
- **§8.2 item 1**: G's two parts and the kinds of D and N, as shares of the real flaws.
- **§8.2 item 4**: every code's share by role, error class, set, reviewer kind and origin, each with
  the cluster bootstrap of §8.1.
- **§8.2 item 6**: the flaws' reality (§2.3) by side: a flaw whose measured lines are all on the
  injected side, all on the twin side, or on both.
- **§9 threat 3**: the L flaws by the ``family`` field §5.1 defines, read from each L flaw's
  representative line, as the tally reads its other L fields; beside it, family by
  ``relation_origin``.
- **Checks 1 and 7 after the fact** (post-run, descriptive, never a result; the owner ruled on
  24.10.2026 that this is a disclosed limitation, not a deviation). §5.5's relation grammar cannot
  state check 1's rule (a unit's dimension or kind) or check 7's (a change owed along an edge, or a
  justification record), so every G claim on them fell back to D or N, and frozen §5.6 never turns
  a D or N line into G. This variant re-runs the whole tally with every measured line that a
  failing check-1 or check-7 record catches (§5.6's locus condition) and that ended D or N because
  its deciding form failed §5.5 set to G. It also sorts the measured step's failed G claims into
  structural (checks 1 and 7, and the relation either does not parse once a trailing comment is
  cut, or parses with two dimensions) and writable (any other).

Outside ``--dry-run`` it refuses unless the tally, run on the same files, reproduces the published
``tally.json`` byte for byte, so every figure here is computed on exactly the data the result
rests on.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402
import law_regate as G  # noqa: E402
import law_slice as S  # noqa: E402
import law_tally as TL  # noqa: E402
import law_verify as V  # noqa: E402

CODES = (*TL.ORDER, "uncoded")
VERSIONS = (("v0", "slice-r1"), ("v1", "slice-r2"))
#: The published files the tally reads, by the name its work dir gives them.
TALLY_INPUTS = {
    "lines.jsonl": "lines.jsonl",
    "flaws.jsonl": "flaws.jsonl",
    "units_s1.jsonl": "units_s1.jsonl",
    "units_s6.jsonl": "units_s6.jsonl",
    "codes.jsonl": "codes.jsonl",
    "reality.jsonl": "reality.jsonl",
    "reality_summary.json": "reality_summary.json",
    "matches.jsonl": "matches.jsonl",
    "extract_counts.json": "extract_counts.json",
    "group_counts.json": "group_counts.json",
    "regate_check.json": "regate_check.json",
    "ledger.jsonl": "ledger/ledger.jsonl",
}


# ---------------------------------------------------------------- §6, the slice


def slice_line_ids(t: TL.Tally) -> set[str]:
    pairs = {(s, p) for s in X.SET_ORDER for p in t.slice["pairs"][s]}
    return {lid for lid, x in t.lines.items() if (x["set"], x["pair"]) in pairs}


def slice_units(t: TL.Tally, ids: set[str]) -> list[dict[str, Any]]:
    """Each flaw cut to its slice lines, with the cluster the tally gives it."""
    out = []
    for u in t.flaws:
        ls = [i for i in u["lines"] if i in ids]
        if ls:
            cluster = ("base", u["flaw_id"]) if u["base"] else (u["set"], u["pairs"][0])
            out.append({"id": u["flaw_id"], "lines": ls, "cluster": cluster})
    return out


def slice_matches(
    t: TL.Tally, step: str, regate: list[dict[str, Any]], ids: set[str]
) -> dict[str, bool]:
    """§5.6's match for the slice lines, under that round's deciding forms."""
    lines = [t.lines[i] for i in sorted(ids)]
    forms = V.deciding_forms(t.codes, step)
    return {m["line_id"]: m["matched"] for m in G.match_all(lines, forms, regate, t.sets)}


def final_code(w: dict[str, dict[str, Any]], matched: bool) -> str:
    """§5.7 rule 1, then §5.6, as the tally applies them to the measured lines."""
    c = TL.rule1(w)
    if c in ("G", "L", "L-if-data") and matched:
        return "G"
    return "L" if c == "G" else c


def slice_figures(t: TL.Tally, step: str, matched: dict[str, bool]) -> dict[str, Any]:
    ids = slice_line_ids(t)
    units = slice_units(t, ids)
    coded = TL.by_line(t.codes, step)
    size = {i: len(u["lines"]) for u in units for i in u["lines"]}
    cluster = {i: u["cluster"] for u in units for i in u["lines"]}
    rows5, rows_l = [], []
    for lid in sorted(ids):
        w = coded.get(lid, {})
        a, b = TL.coder_code(w.get("c1")), TL.coder_code(w.get("c2"))
        rows5.append((a, b, 1.0 / size[lid], cluster[lid]))
        rows_l.append((TL.gl(a), TL.gl(b), 1.0 / size[lid], cluster[lid]))
    final = {i: final_code(coded.get(i, {}), matched.get(i, False)) for i in ids}
    per: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
    k = 0
    for u in units:
        hit = TL.aggregate([final[i] for i in u["lines"]]) == "L"
        k += hit
        per[u["cluster"]][0] += hit
        per[u["cluster"]][1] += 1
    n = len(units)
    lines_l = sum(1 for i in ids if final[i] == "L")
    return {
        "lines": len(ids),
        "flaws": n,
        "kappa5": TL.kappa_stats(rows5, len(TL.CATS6)),
        "kappaL": TL.kappa_stats(rows_l, len(TL.CATS_L)),
        "disagreements": S.disagreements(t.codes, step),
        "L_share_flaws": {
            "k": k,
            "n": n,
            "share": k / n if n else None,
            "wilson": TL.wilson(k, n),
            "cluster": TL.cluster_share([(a, b) for a, b in per.values()]),
            "clusters": len(per),
        },
        "L_share_lines": {
            "k": lines_l,
            "n": len(ids),
            "share": lines_l / len(ids) if ids else None,
        },
        "final_codes_lines": dict(Counter(final.values())),
        "gate_matched_lines": sum(1 for i in ids if matched.get(i, False)),
    }


# ---------------------------------------------------------------- §8.2


def role_of(t: TL.Tally, u: dict[str, Any]) -> str:
    if u["base"]:
        return "base"
    return str(t.sets[u["set"]].artefacts[u["pairs"][0]]["assigned_role"])


def class_of(t: TL.Tally, u: dict[str, Any]) -> str:
    if u["base"]:
        return "base"
    return str(t.sets[u["set"]].artefacts[u["pairs"][0]]["error_class"])


def groups(t: TL.Tally, flaws: list[dict[str, Any]]) -> dict[str, dict[str, Callable[..., bool]]]:
    """The breakdowns of §8.2 item 4, as the tally forms them: one predicate per group."""

    def eq(f: Callable[[dict[str, Any]], str], v: str) -> Callable[[dict[str, Any]], bool]:
        return lambda u: f(u) == v

    def has(kind: str) -> Callable[[dict[str, Any]], bool]:
        return lambda u: kind in {t.lines[i]["kind"] for i in u["lines"]}

    def role(u: dict[str, Any]) -> str:
        return role_of(t, u)

    def cls(u: dict[str, Any]) -> str:
        return class_of(t, u)

    return {
        "role": {v: eq(role, v) for v in sorted({role(u) for u in flaws})},
        "class": {v: eq(cls, v) for v in sorted({cls(u) for u in flaws})},
        "set": {s: eq(lambda u: str(u["set"]), s) for s in X.SET_ORDER},
        "reviewer_kind": {k: has(k) for k in ("paired", "generalist")},
        "origin": {
            "on the injection": t.on_injection,
            "elsewhere": lambda u: not t.on_injection(u),
        },
    }


def shares_by_group(t: TL.Tally) -> dict[str, Any]:
    er = not t.reliable
    flaws = t.unit_rows(t.flaws)
    return {
        g: {v: {c: t.share(flaws, er, (c,), keep=keep) for c in CODES} for v, keep in by.items()}
        for g, by in groups(t, flaws).items()
    }


def parts_as_shares(tally: dict[str, Any]) -> dict[str, Any]:
    n = tally["primary"]["n"]
    sec = tally["secondary"]

    def frac(d: dict[str, int]) -> dict[str, Any]:
        return {k: {"k": v, "n": n, "share": v / n if n else None} for k, v in sorted(d.items())}

    return {
        "G_parts": frac(sec["G_parts"]),
        "D_by_kind": frac(sec["D_by_kind"]),
        "N_by_kind": frac(sec["N_by_kind"]),
    }


def flaw_reality(t: TL.Tally, u: dict[str, Any]) -> str:
    """§2.3: real if any line is true_flaw, not real if every line is not_a_flaw, else undecided."""
    vs = [t.reality.get(i, {}).get("verdict") for i in u["lines"]]
    if any(v == TL.TRUE for v in vs):
        return "real"
    if vs and all(v == "not_a_flaw" for v in vs):
        return "not_real"
    return "undecided"


def reality_by_side(t: TL.Tally) -> dict[str, Any]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for u in t.unit_rows(t.flaws):
        sides = {t.lines[i]["side"] for i in u["lines"]}
        side = "both" if len(sides) > 1 else f"{next(iter(sides))} only"
        out[side][flaw_reality(t, u)] += 1
    return {s: dict(c) for s, c in sorted(out.items())}


def l_by_family(t: TL.Tally) -> dict[str, Any]:
    er = not t.reliable
    fam: Counter[str] = Counter()
    cross: Counter[str] = Counter()
    for u in t.unit_rows(t.flaws):
        if not t.real(u, er) or t.unit_code(u, er) != "L":
            continue
        rep = t.representative(u, "L")
        if rep is None:
            continue
        f = t.deciding.get(rep) or {}
        family = str(f.get("family"))
        fam[family] += 1
        cross[f"{family} | {t.l_fields(rep)['relation_origin']}"] += 1
    return {
        "family": dict(sorted(fam.items())),
        "family_by_relation_origin": dict(sorted(cross.items())),
    }


# ---------------------------------------------------------------- checks 1 and 7, after the fact

#: The checks whose rule §5.5's relation grammar cannot state, by the gate relation that names it.
UNSTATABLE = {1: "units_kind", 7: "propagation"}
#: A trailing comment a coder wrote after a relation: a final parenthesis, or a "; …" or ", i.e. …".
COMMENT = re.compile(r"\s*(?:;|,\s*i\.e\.).*$|\s*\([^()]*\)\s*$")
LABEL = "post-run, descriptive, never a result"


def caught_by_1_or_7(
    t: TL.Tally,
    lid: str,
    by_version: dict[tuple[str, str, str], list[dict[str, Any]]],
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """The failing check-1 and check-7 records of the line's version that meet §5.6's locus
    condition (a locus pair on a record's node, its quantity in the check's set and, for these two
    checks, named in the record's message)."""
    line = t.lines[lid]
    ids = set(t.sets[line["set"]].version(line["pair"], line["side"]))
    out = []
    for rec in by_version.get((line["set"], line["pair"], line["side"]), []):
        k = rec.get("check")
        if rec.get("outcome") != "fail" or k not in UNSTATABLE:
            continue
        nodes = G.record_nodes(rec, ids)
        msg = rec.get("message") or ""
        if any(n in nodes and G.in_q(k, q, table) and G.word_in(q, msg) for n, q in line["locus"]):
            out.append({"check": k, "name": rec.get("name"), "scope": rec.get("scope")})
    return [dict(x) for x in sorted({tuple(sorted(r.items())) for r in out})]


def fell_back(t: TL.Tally, lid: str) -> dict[str, Any] | None:
    """The deciding form's verified row, if the form failed §5.5 and the line ended D or N."""
    f = t.deciding.get(lid)
    ver = (f or {}).get("_verified") or {}
    if f is None or ver.get("failure") is None or t.final[lid] not in ("D", "N"):
        return None
    return dict(ver)


def gate_variant(t: TL.Tally, regate: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole tally with the lines checks 1 and 7 caught, which fell back to D or N, as G.

    Mutates ``t.final``; pass a Tally of its own."""
    table = G.appendix_c()
    by_version = {(r["set"], r["pair"], r["side"]): r["result"]["checks"] for r in regate}
    caught: dict[str, dict[str, Any]] = {}
    for lid in sorted(t.measured):
        ver = fell_back(t, lid)
        if ver is None:
            continue
        recs = caught_by_1_or_7(t, lid, by_version, table)
        if recs:
            caught[lid] = {
                "who": ver.get("who"),
                "claimed": ver.get("code_raw"),
                "gate_relation": (t.deciding.get(lid) or {}).get("gate_relation"),
                "failure": ver.get("failure"),
                "final_as_tallied": t.final[lid],
                "true_flaw": t.is_true(lid),
                "full_match": bool(t.matches.get(lid, {}).get("matched")),
                "records": recs,
            }
    er = not t.reliable
    flaws = t.unit_rows(t.flaws)
    before = {u["id"]: t.unit_code(u, er) for u in flaws if t.real(u, er)}
    for lid in caught:
        t.final[lid] = "G"
    out = t.run()
    moved = []
    for u in flaws:
        if u["id"] in before and before[u["id"]] == "L" and t.unit_code(u, er) != "L":
            moved.append(
                {
                    "flaw": u["id"],
                    "set": u["set"],
                    "pairs": u["pairs"],
                    "code_after": t.unit_code(u, er),
                    "lines": [{"line": i, **caught[i]} for i in u["lines"] if i in caught],
                }
            )
    p = out["primary"]
    w = p["wilson"]
    return {
        "label": LABEL,
        "lines_set_to_G": len(caught),
        "lines_set_to_G_true_flaw": sum(1 for v in caught.values() if v["true_flaw"]),
        "primary": p,
        "wilson_holds_T": w is not None and w[0] < TL.T <= w[1],
        "shares": out["secondary"]["shares"],
        "counts": out["secondary"]["counts"],
        "decision": out["decision"],
        "readings": out["readings"],
        "origin": out["breakdowns"]["origin"],
        "L_flaws_that_become_G": moved,
    }


def why_failed(form: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """A failed G claim, structural or writable, and why.

    Structural only for checks 1 and 7, whose rule the grammar cannot state: the relation does not
    parse once a trailing comment is cut, or it parses and its two sides differ in dimension (a
    unit's wrong dimension is the very defect check 1 reads). Anything else could have been
    written in the grammar."""
    if form.get("gate_relation") not in UNSTATABLE.values():
        return "writable", "a gate relation other than checks 1 and 7"
    rel = str(form.get("relation") or "")
    for text in dict.fromkeys((rel, COMMENT.sub("", rel).strip())):
        try:
            V.parse_relation(text)
        except V.Failure:
            continue
        break
    else:
        return "structural", "does not parse as one comparison, with or without a trailing comment"
    try:
        V.verify_relation({**form, "relation": text}, nodes)
    except V.Failure as f:
        if f.kind == "dimension":
            return "structural", "parses, and its two sides differ in dimension"
        return "writable", f"parses as one comparison, then fails on {f.kind}"
    except (KeyError, TypeError, ValueError):
        return "writable", "parses as one comparison; its form is incomplete"
    return "writable", "parses as one comparison, and holds"


def failed_g_claims(t: TL.Tally) -> dict[str, Any]:
    """The measured step's G claims that failed §5.5, by coder, gate relation and kind."""
    rows = [
        r
        for r in t.codes
        if r["step"] == "measured" and r.get("code_raw") == "G" and r.get("failure")
    ]
    kinds: Counter[str] = Counter()
    detail: Counter[str] = Counter()
    writable = []
    for r in rows:
        x = t.lines[r["line_id"]]
        nodes = t.sets[x["set"]].version(x["pair"], x["side"])
        kind, why = why_failed(r["form"], nodes)
        kinds[kind] += 1
        detail[f"{kind} | {r['form'].get('gate_relation')} | {r['failure']} | {why}"] += 1
        if kind == "writable":
            writable.append(
                {"line": r["line_id"], "who": r["who"], "relation": r["form"].get("relation")}
            )
    every = [r for r in t.codes if r["step"] == "measured" and r.get("code_raw") == "G"]
    passed = [
        {"line": r["line_id"], "who": r["who"], "relation": r["form"].get("relation")}
        for r in every
        if not r.get("failure") and r["form"].get("gate_relation") in UNSTATABLE.values()
    ]
    return {
        "label": LABEL,
        "every_G_claim_by_gate_relation": dict(
            sorted(
                Counter(
                    f"{r['form'].get('gate_relation')} | {'failed' if r.get('failure') else 'passed'}"
                    for r in every
                ).items()
            )
        ),
        "passed_on_checks_1_and_7": passed,
        "claims": len(rows),
        "by_coder": dict(sorted(Counter(r["who"] for r in rows).items())),
        "by_gate_relation_and_failure": dict(
            sorted(
                Counter(f"{r['form'].get('gate_relation')} | {r['failure']}" for r in rows).items()
            )
        ),
        "kind": dict(sorted(kinds.items())),
        "kind_detail": dict(sorted(detail.items())),
        "writable": writable,
    }


def gate_matched_by_final(t: TL.Tally) -> dict[str, int]:
    """The measured lines a failing gate record matches (§5.6, ``matches.jsonl``), by final code."""
    return dict(
        sorted(
            Counter(t.final[i] for i in t.measured if t.matches.get(i, {}).get("matched")).items()
        )
    )


# ---------------------------------------------------------------- all


def report(
    t: TL.Tally, tally: dict[str, Any], matched: dict[str, dict[str, bool]]
) -> dict[str, Any]:
    """Every figure of this file but the variant; ``matched`` holds each slice round's §5.6 match
    per line."""
    return {
        "computed_after_the_run": True,
        "dry_run": t.dry_run,
        "slice": {v: slice_figures(t, step, matched.get(step, {})) for v, step in VERSIONS},
        "parts_as_shares": parts_as_shares(tally),
        "shares_by_group": shares_by_group(t),
        "reality_by_side": reality_by_side(t),
        "L_by_family": l_by_family(t),
        "checks_1_and_7": {
            "label": LABEL,
            "gate_matched_lines_by_final_code": gate_matched_by_final(t),
            "failed_G_claims": failed_g_claims(t),
        },
    }


def work_dir(data: Path, slice_path: Path, into: Path) -> Path:
    """The published files laid out as the tally's work dir, copied into ``into``."""
    (into / "ledger").mkdir(parents=True)
    for src, dest in TALLY_INPUTS.items():
        if (data / src).exists() or src != "regate_check.json":
            shutil.copyfile(data / src, into / dest)
    shutil.copyfile(slice_path, into / "slice.json")
    return into


def compute(
    data: Path, slice_path: Path, dry: bool, sets: dict[str, X.SetData] | None = None
) -> dict[str, Any]:
    """The tally on the published files, held to ``tally.json``, and then this file's figures."""
    with tempfile.TemporaryDirectory() as tmp:
        work = work_dir(data, slice_path, Path(tmp) / "work")
        t = TL.Tally(work, dry, sets)
        tally = t.run()
        text = json.dumps(tally, indent=1, sort_keys=True, default=str)
        same = text == (data / "tally.json").read_text()
        if not dry and not same:
            raise X.Refused("the tally on these files does not reproduce tally.json")
        ids = slice_line_ids(t)
        with gzip.open(data / "regate.jsonl.gz", "rt") as fh:
            regate = [json.loads(x) for x in fh]
        matched = {step: slice_matches(t, step, regate, ids) for _, step in VERSIONS}
        out = report(t, tally, matched)
        out["checks_1_and_7"]["variant"] = gate_variant(TL.Tally(work, dry, sets), regate)
    out["tally_reproduced"] = same
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    data = Path(args[0])
    try:
        out = compute(data, data.parent / "slice.json", "--dry-run" in argv)
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    dest = data / "report_extra.json"
    dest.write_text(json.dumps(out, indent=1, sort_keys=True, default=str))
    print(json.dumps({"written": str(dest), "tally_reproduced": out["tally_reproduced"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
