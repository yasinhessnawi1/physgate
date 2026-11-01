"""R-LAW-01, CRITERIA.md §2.2 steps A to D: finding lines grouped into flaws, by a fixed rule.

Usage (from the repository root, after ``law_extract.py lines``):

    python -I experiments/R-LAW-01/law_group.py <work dir>

Reads ``<work>/lines.jsonl`` and the two sets; writes ``flaws.jsonl`` (the primary unit),
``units_s1.jsonl`` (step D undone), ``units_s6.jsonl`` (the wider base merge) and
``group_counts.json``. No model output is read. Prints counts only.

Every unit row: ``flaw_id``, ``set``, ``pairs``, ``lines`` (every line, absorbed section 1 lines
included), ``locus_lines`` (the lines whose loci form its locus), ``locus``, ``items``, ``base``.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402

S1_SECTION = "acceptance_criteria"
Pair = tuple[str, str]


class _UF:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _loc(line: dict[str, Any]) -> frozenset[Pair]:
    return frozenset((n, q) for n, q in line["locus"])


def step_a(lines: list[dict[str, Any]]) -> dict[str, str]:
    """A section 1 line with a locus joins the same review's section 2-4 line sharing the most
    pairs, ties broken by the lower item id in string order (then the lower line id)."""
    review: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for x in lines:
        review[(x["set"], x["run"], x["pair"], x["side"])].append(x)
    attach: dict[str, str] = {}
    for rows in review.values():
        others = [y for y in rows if y["section"] != S1_SECTION and y["locus"]]
        for x in rows:
            if x["section"] != S1_SECTION or not x["locus"]:
                continue
            lx = _loc(x)
            best = sorted(others, key=lambda y: (-len(lx & _loc(y)), y["item"], y["line_id"]))
            if best and lx & _loc(best[0]):
                attach[x["line_id"]] = best[0]["line_id"]
    return attach


def steps_b_c(
    lines: list[dict[str, Any]], attach: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    """Step B (components of one (set, pair, item) by shared pairs; the empty-locus lines one
    further unit), then step C (same (set, pair), identical non-empty locus unions merge)."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for x in lines:
        if x["line_id"] not in attach:
            groups[(x["set"], x["pair"], x["item"])].append(x)
    units: list[dict[str, Any]] = []
    for (st, pair, _item), rows in sorted(groups.items()):
        located = [x for x in rows if x["locus"]]
        uf = _UF(len(located))
        by_pair: dict[Pair, int] = {}
        for i, x in enumerate(located):
            for p in _loc(x):
                if p in by_pair:
                    uf.union(i, by_pair[p])
                else:
                    by_pair[p] = i
        comps: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for i, x in enumerate(located):
            comps[uf.find(i)].append(x)
        for comp in comps.values():
            units.append({"set": st, "pairs": {pair}, "rows": comp})
        empty = [x for x in rows if not x["locus"]]
        if empty:
            units.append({"set": st, "pairs": {pair}, "rows": empty})
    for u in units:
        u["locus"] = frozenset().union(*(_loc(x) for x in u["rows"]))
    after_b = len(units)
    merged: dict[tuple[str, str, frozenset[Pair]], dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for u in units:
        if u["locus"]:
            k = (u["set"], next(iter(u["pairs"])), u["locus"])
            if k in merged:
                merged[k]["rows"] += u["rows"]
                continue
            merged[k] = u
        out.append(u)
    return out, after_b


def mark_base(units: list[dict[str, Any]], sets: dict[str, X.SetData]) -> None:
    for u in units:
        pair = next(iter(u["pairs"]))
        u["items"] = {x["item"] for x in u["rows"]}
        u["base"] = bool(u["locus"]) and sets[u["set"]].unchanged(pair, u["locus"])


def step_d(units: list[dict[str, Any]], wide: bool) -> list[dict[str, Any]]:
    """Base flaws of one set merge (transitively) when they share an item and a locus pair, or
    their locus unions are identical; ``wide`` merges on any shared pair (reading S6)."""
    uf = _UF(len(units))
    base = [i for i, u in enumerate(units) if u["base"]]
    for a_i, i in enumerate(base):
        for j in base[a_i + 1 :]:
            a, b = units[i], units[j]
            if a["set"] != b["set"]:
                continue
            shared = a["locus"] & b["locus"]
            if wide:
                hit = bool(shared)
            else:
                hit = bool(a["items"] & b["items"] and shared) or a["locus"] == b["locus"]
            if hit:
                uf.union(i, j)
    out: dict[int, dict[str, Any]] = {}
    for i, u in enumerate(units):
        r = uf.find(i)
        if r not in out:
            out[r] = {**u, "rows": list(u["rows"]), "pairs": set(u["pairs"]), "parts": 1}
        else:
            o = out[r]
            o["rows"] += u["rows"]
            o["pairs"] |= u["pairs"]
            o["locus"] = o["locus"] | u["locus"]
            o["items"] = o["items"] | u["items"]
            o["parts"] += 1
    return list(out.values())


def finish(
    units: list[dict[str, Any]], attach: dict[str, str], prefix: str
) -> list[dict[str, Any]]:
    """Unit rows with ids in order of their first line; absorbed lines join their target's unit."""
    where: dict[str, int] = {}
    for i, u in enumerate(units):
        for x in u["rows"]:
            where[x["line_id"]] = i
    members: dict[int, list[str]] = defaultdict(list)
    for lid, i in where.items():
        members[i].append(lid)
    for lid, target in attach.items():
        members[where[target]].append(lid)
    order = sorted(range(len(units)), key=lambda i: min(members[i]))
    out = []
    for n, i in enumerate(order, 1):
        u = units[i]
        out.append(
            {
                "flaw_id": f"{prefix}{n:04d}",
                "set": u["set"],
                "pairs": sorted(u["pairs"]),
                "lines": sorted(members[i]),
                "locus_lines": sorted(x["line_id"] for x in u["rows"]),
                "locus": sorted([n_, q] for n_, q in u["locus"]),
                "items": sorted(u["items"]),
                "base": u["base"],
                "parts": u.get("parts", 1),
            }
        )
    return out


Rows = list[dict[str, Any]]


def group(
    lines: list[dict[str, Any]], sets: dict[str, X.SetData]
) -> tuple[Rows, Rows, Rows, dict[str, Any]]:
    attach = step_a(lines)
    units, after_b = steps_b_c(lines, attach)
    mark_base(units, sets)
    flaws = step_d(units, wide=False)
    wide = step_d(units, wide=True)
    f = finish(flaws, attach, "W")
    s1 = finish(units, attach, "U")
    s6 = finish(wide, attach, "V")
    base_merged = [x for x in f if x["base"]]
    counts = {
        "s1_lines": sum(1 for x in lines if x["section"] == S1_SECTION),
        "absorbed_by_step_a": len(attach),
        "after_b": after_b,
        "after_c": len(units),
        "after_d": len(f),
        "after_d_by_set": dict(Counter(x["set"] for x in f)),
        "base_flaws_before_merge": sum(1 for u in units if u["base"]),
        "base_flaws_after_merge": len(base_merged),
        "base_spanning_more_than_one_pair": sum(1 for x in base_merged if len(x["pairs"]) > 1),
        "largest_base_span": max((len(x["pairs"]) for x in base_merged), default=0),
        "wide_merge_s6": len(s6),
    }
    return f, s1, s6, counts


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(argv[0])
    lines = X.read_jsonl(work / "lines.jsonl")
    try:
        sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    f, s1, s6, counts = group(lines, sets)
    X.write_jsonl(work / "flaws.jsonl", f)
    X.write_jsonl(work / "units_s1.jsonl", s1)
    X.write_jsonl(work / "units_s6.jsonl", s6)
    (work / "group_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
