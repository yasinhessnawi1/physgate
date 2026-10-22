"""R-LAW-01, CRITERIA.md §5.6, §5.7, §7, §8 and §10: the tally, after every session.

Usage (from the repository root, with the project environment):

    uv run python -I experiments/R-LAW-01/law_tally.py <work dir> [--dry-run]

Reads ``lines.jsonl``, ``flaws.jsonl``, ``units_s1.jsonl``, ``units_s6.jsonl``, ``slice.json``,
``reality.jsonl``, ``reality_summary.json``, ``codes.jsonl``, ``matches.jsonl``,
``extract_counts.json``, ``group_counts.json`` and, if present, ``deviations.json`` and the ledger's
``VOID`` marker. Refuses any output a stand-in wrote unless ``--dry-run``. Writes ``tally.json``
and prints it: κ and the floor first, then the shares, intervals, readings and the decision.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402
import law_regate as G  # noqa: E402
import law_verify as V  # noqa: E402

T = 0.15
FLOOR = 0.60
SEED = 13
DRAWS = 10_000
Z = 1.959963984540054
EXPECTED = {"lines": 993, "flaws": 348, "before_d": 367}
ORDER = ("G", "L", "L-if-data", "D", "N")
#: A missing form (§7): a category of its own that never agrees, not even with another one.
NONE = "none"
CATS6 = ("G", "L", "L-if-data", "D", "N", NONE)
CATS_L = ("GL", "rest", NONE)
TIE_ORDER = ("N", "D", "L-if-data", "G", "L")
TRUE = "true_flaw"


# ---------------------------------------------------------------- statistics


def wilson(k: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def cluster_share(per_cluster: list[tuple[int, int]], draws: int = DRAWS) -> list[float] | None:
    """Percentile interval of sum(k)/sum(n) over clusters resampled with replacement."""
    if not per_cluster or sum(n for _, n in per_cluster) == 0:
        return None
    rng = random.Random(SEED)
    m = len(per_cluster)
    vals = []
    for _ in range(draws):
        k = n = 0
        for _ in range(m):
            a, b = per_cluster[rng.randrange(m)]
            k += a
            n += b
        if n:
            vals.append(k / n)
    return [percentile(vals, 0.025), percentile(vals, 0.975)]


def kappa_from(
    w: float, agree: float, m1: Mapping[str, float], m2: Mapping[str, float]
) -> float | None:
    """Cohen's κ from weighted counts. Chance agreement runs over the codes only: two missing
    forms never agree, so ``none`` adds nothing to it."""
    if w <= 0:
        return None
    po = agree / w
    pe = sum((m1.get(c, 0.0) / w) * (m2.get(c, 0.0) / w) for c in (set(m1) | set(m2)) - {NONE})
    return None if pe >= 1 else (po - pe) / (1 - pe)


def kappa_stats(
    rows: list[tuple[str, str, float, Any]], k_categories: int, draws: int = DRAWS
) -> dict[str, Any]:
    """Weighted κ with a cluster-bootstrap interval, and the unweighted κ, raw agreement and
    PABAK beside it. ``rows``: (code 1, code 2, weight, cluster). A missing form (``none``) is
    a disagreement whatever stands against it, another missing form included (§7)."""

    Marg = defaultdict[str, float]

    def parts(rs: Iterable[tuple[str, str, float, Any]]) -> tuple[float, float, Marg, Marg]:
        w = agree = 0.0
        m1: Marg = defaultdict(float)
        m2: Marg = defaultdict(float)
        for a, b, wt, _ in rs:
            w += wt
            agree += wt * (a == b != NONE)
            m1[a] += wt
            m2[b] += wt
        return w, agree, m1, m2

    w, agree, m1, m2 = parts(rows)
    kw = kappa_from(w, agree, m1, m2)
    uw = parts((a, b, 1.0, c) for a, b, _, c in rows)
    ku = kappa_from(uw[0], uw[1], uw[2], uw[3])
    by: dict[Any, list[tuple[str, str, float, Any]]] = defaultdict(list)
    for r in rows:
        by[r[3]].append(r)
    cl = [parts(v) for v in by.values()]
    rng = random.Random(SEED)
    vals = []
    for _ in range(draws if cl else 0):
        tw = ta = 0.0
        t1: Marg = defaultdict(float)
        t2: Marg = defaultdict(float)
        for _ in range(len(cl)):
            cw, ca, c1, c2 = cl[rng.randrange(len(cl))]
            tw += cw
            ta += ca
            for key, val in c1.items():
                t1[key] += val
            for key, val in c2.items():
                t2[key] += val
        k = kappa_from(tw, ta, t1, t2)
        if k is not None:
            vals.append(k)
    raw_w = agree / w if w else None
    raw_u = uw[1] / uw[0] if uw[0] else None

    def pabak(po: float | None) -> float | None:
        return None if po is None else (k_categories * po - 1) / (k_categories - 1)

    return {
        "weighted": kw,
        "interval": [percentile(vals, 0.025), percentile(vals, 0.975)] if vals else None,
        "unweighted": ku,
        "raw_agreement_weighted": raw_w,
        "raw_agreement_unweighted": raw_u,
        "pabak_weighted": pabak(raw_w),
        "pabak_unweighted": pabak(raw_u),
        "lines": len(rows),
    }


# ---------------------------------------------------------------- codes


def by_line(codes: list[dict[str, Any]], step: str) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in codes:
        if r["step"] == step:
            out[r["line_id"]][r["who"]] = r
    return out


def coder_code(r: dict[str, Any] | None) -> str:
    return NONE if r is None or r.get("form") is None else str(r["code"])


def gl(code: str) -> str:
    """κ_L's three categories: G or L, the rest, and a missing form."""
    return NONE if code in (NONE, "uncoded") else ("GL" if code in ("G", "L") else "rest")


def resolution(
    wilson_iv: list[float] | None, cluster_iv: list[float] | None
) -> tuple[bool, list[float] | None]:
    """§10: resolved if the wider of the two intervals lies wholly on one side of T."""
    ivs = [iv for iv in (wilson_iv, cluster_iv) if iv]
    wider = max(ivs, key=lambda iv: iv[1] - iv[0]) if ivs else None
    return wider is not None and (wider[0] >= T or wider[1] < T), wider


def rule1(w: dict[str, dict[str, Any]]) -> str:
    """§5.7 rule 1: agreed code, else the adjudicator's, else uncoded (a form missing)."""
    a, b = coder_code(w.get("c1")), coder_code(w.get("c2"))
    if a == "none" or b == "none":
        return "uncoded"
    if a == b:
        return a
    adj = coder_code(w.get("adj"))
    return "uncoded" if adj == "none" else adj


def aggregate(codes: list[str]) -> str:
    """§5.7 rule 2: G, else L, else L-if-data, else D, else N; all uncoded is uncoded."""
    for c in ORDER:
        if c in codes:
            return c
    return "uncoded"


def majority(codes: list[str]) -> str:
    """Reading S3: the most frequent line code, ties broken N, D, L-if-data, G, L."""
    c = Counter(x for x in codes if x != "uncoded")
    if not c:
        return "uncoded"
    top = max(c.values())
    return next(x for x in TIE_ORDER if c.get(x) == top)


# ---------------------------------------------------------------- the tally


Unit = dict[str, Any]


def _is(f: Callable[[Unit], str], v: str) -> Callable[[Unit], bool]:
    return lambda u: f(u) == v


def _has(f: Callable[[Unit], set[str]], v: str) -> Callable[[Unit], bool]:
    return lambda u: v in f(u)


class Tally:
    def __init__(self, work: Path, dry_run: bool, sets: dict[str, X.SetData] | None = None) -> None:
        self.work = work
        r = X.read_jsonl
        self.lines = {x["line_id"]: x for x in r(work / "lines.jsonl")}
        self.flaws = r(work / "flaws.jsonl")
        self.s1 = r(work / "units_s1.jsonl")
        self.s6 = r(work / "units_s6.jsonl")
        self.slice = json.loads((work / "slice.json").read_text())
        self.reality = {x["line_id"]: x for x in r(work / "reality.jsonl")}
        self.rsum = json.loads((work / "reality_summary.json").read_text())
        self.codes = r(work / "codes.jsonl")
        self.matches = {x["line_id"]: x for x in r(work / "matches.jsonl")}
        self.ecounts = json.loads((work / "extract_counts.json").read_text())
        self.gcounts = json.loads((work / "group_counts.json").read_text())
        dev = work / "deviations.json"
        self.deviations: list[str] = json.loads(dev.read_text()) if dev.exists() else []
        if (work / "VOID").exists() or (work / "ledger" / "VOID").exists():
            self.deviations.append("the 60 M token guard was reached: the result is void")
        check = work / "regate_check.json"
        if check.exists():
            if not json.loads(check.read_text())["fresh_against_a_fresh"]["holds"]:
                self.deviations.append(
                    "the re-gate differs from the a-fresh gate lines: G is not decided"
                )
        elif not dry_run:
            self.deviations.append("no re-gate check was recorded")
        if self.ecounts["lines"] != EXPECTED["lines"] and not dry_run:
            self.deviations.append("extraction did not give 993 lines")
        if not dry_run and (
            self.gcounts["after_d"] != EXPECTED["flaws"]
            or self.gcounts["after_c"] != EXPECTED["before_d"]
        ):
            self.deviations.append("grouping did not give 348 flaws (367 before step D)")
        standin = any(c.get("standin") for c in self.codes) or any(
            v.get("standin") for v in self.reality.values()
        )
        if standin and not dry_run:
            raise X.Refused("a stand-in wrote some outputs; only a dry run reads them")
        self.dry_run = dry_run
        in_slice = {(s, p) for s in X.SET_ORDER for p in self.slice["pairs"][s]}
        self.measured = {
            lid for lid, x in self.lines.items() if (x["set"], x["pair"]) not in in_slice
        }
        self.sets = sets if sets is not None else {n: X.load_set(X.FROZEN, n) for n in X.SETS}
        self.coded = by_line(self.codes, "measured")
        self.deciding = V.deciding_forms(self.codes)
        self.reliable = bool(self.rsum.get("reliable"))
        self.pre: dict[str, str] = {}
        self.final: dict[str, str] = {}
        self.gap: set[str] = set()
        for lid in self.measured:
            c = rule1(self.coded.get(lid, {}))
            self.pre[lid] = c
            m = self.matches.get(lid, {}).get("matched", False)
            if c in ("G", "L", "L-if-data") and m:
                self.final[lid] = "G"
            elif c == "G":
                self.final[lid] = "L"
                self.gap.add(lid)
            else:
                self.final[lid] = c

    # ---- units

    def is_true(self, lid: str) -> bool:
        return self.reality.get(lid, {}).get("verdict") == TRUE

    def unit_rows(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The measured part of each unit: its measured lines and locus lines, and its cluster."""
        out = []
        for u in units:
            ls = [i for i in u["lines"] if i in self.measured]
            if not ls:
                continue
            loc_lines = [i for i in u["locus_lines"] if i in self.measured]
            locus = {(n, q) for i in loc_lines for n, q in self.lines[i]["locus"]}
            st = u["set"]
            cluster = ("base", u["flaw_id"]) if u["base"] else (st, u["pairs"][0])
            out.append(
                {
                    "id": u["flaw_id"],
                    "lines": ls,
                    "set": st,
                    "pairs": u["pairs"],
                    "base": u["base"],
                    "locus": locus,
                    "cluster": cluster,
                }
            )
        return out

    def line_units(self) -> list[dict[str, Any]]:
        return [
            {
                "id": lid,
                "lines": [lid],
                "set": self.lines[lid]["set"],
                "pairs": [self.lines[lid]["pair"]],
                "base": False,
                "locus": {(n, q) for n, q in self.lines[lid]["locus"]},
                "cluster": (self.lines[lid]["set"], self.lines[lid]["pair"]),
            }
            for lid in sorted(self.measured)
        ]

    def real(self, u: dict[str, Any], every_line_real: bool) -> bool:
        if every_line_real:
            return True
        return any(self.is_true(i) for i in u["lines"])

    def code_lines(self, u: dict[str, Any], every_line_real: bool) -> list[str]:
        return [i for i in u["lines"] if every_line_real or self.is_true(i)]

    def line_code(self, lid: str, strict: bool) -> str:
        c = self.final[lid]
        if strict and c == "L":
            f = self.deciding.get(lid)
            if f is not None and f.get("kind") == "limit":
                return str(f.get("fallback_code") or "N")
        return c

    def unit_code(
        self, u: dict[str, Any], every_line_real: bool, how: str = "rule2", strict: bool = False
    ) -> str:
        cs = [self.line_code(i, strict) for i in self.code_lines(u, every_line_real)]
        return majority(cs) if how == "majority" else aggregate(cs)

    def on_injection(self, u: dict[str, Any]) -> bool:
        if u["base"] or len(u["pairs"]) != 1:
            return False
        sd = self.sets[u["set"]]
        if not (u["locus"] & sd.changed_pairs(u["pairs"][0])):
            return False
        if any(self.lines[i]["side"] == "twin" for i in u["lines"]):
            return False
        return any(
            self.is_true(i) and self.reality[i].get("origin") == "introduced" for i in u["lines"]
        )

    def share(
        self,
        units: list[dict[str, Any]],
        every_line_real: bool,
        target: tuple[str, ...] = ("L",),
        how: str = "rule2",
        strict: bool = False,
        keep: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        per: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
        k = n = 0
        for u in units:
            if keep is not None and not keep(u):
                continue
            if not self.real(u, every_line_real):
                continue
            hit = self.unit_code(u, every_line_real, how, strict) in target
            k += hit
            n += 1
            per[u["cluster"]][0] += hit
            per[u["cluster"]][1] += 1
        w = wilson(k, n)
        cb = cluster_share([(a, b) for a, b in per.values()])
        return {
            "k": k,
            "n": n,
            "share": (k / n) if n else None,
            "wilson": w,
            "cluster": cb,
            "clusters": len(per),
        }

    # ---- κ

    def kappas(self) -> dict[str, Any]:
        flaw_of: dict[str, tuple[str, int, Any]] = {}
        for u in self.unit_rows(self.flaws):
            for i in u["lines"]:
                flaw_of[i] = (u["id"], len(u["lines"]), u["cluster"])
        rows5, rowsL = [], []
        for lid in sorted(self.measured):
            w = self.coded.get(lid, {})
            a, b = coder_code(w.get("c1")), coder_code(w.get("c2"))
            _, nlines, cl = flaw_of[lid]
            rows5.append((a, b, 1.0 / nlines, cl))
            rowsL.append((gl(a), gl(b), 1.0 / nlines, cl))
        k5 = kappa_stats(rows5, len(CATS6))
        kl = kappa_stats(rowsL, len(CATS_L))
        meets = (
            k5["weighted"] is not None
            and kl["weighted"] is not None
            and k5["weighted"] >= FLOOR
            and kl["weighted"] >= FLOOR
        )
        return {"kappa5": k5, "kappaL": kl, "floor": FLOOR, "meets_floor": meets}

    def kappa_flaw_level(self) -> dict[str, Any] | None:
        pairs = []
        for u in self.unit_rows(self.flaws):
            if not self.real(u, not self.reliable):
                continue
            ls = self.code_lines(u, not self.reliable)
            a = aggregate([coder_code(self.coded.get(i, {}).get("c1")) for i in ls])
            b = aggregate([coder_code(self.coded.get(i, {}).get("c2")) for i in ls])
            a, b = (NONE if c == "uncoded" else c for c in (a, b))
            pairs.append((a, b, 1.0, u["cluster"]))
        return kappa_stats(pairs, len(CATS6)) if pairs else None

    def audit(self) -> dict[str, Any] | None:
        rows = [r for r in self.codes if r["who"] == "audit" and r["line_id"] in self.measured]
        if not rows:
            return None
        flaw_of: dict[str, tuple[int, Any]] = {}
        for u in self.unit_rows(self.flaws):
            for i in u["lines"]:
                flaw_of[i] = (len(u["lines"]), u["cluster"])
        r5, rl = [], []
        for r in rows:
            a, b = coder_code(r), self.pre[r["line_id"]]
            b = NONE if b == "uncoded" else b
            n, cl = flaw_of[r["line_id"]]
            r5.append((a, b, 1.0 / n, cl))
            rl.append((gl(a), gl(b), 1.0 / n, cl))
        lines = [
            r["line_id"] for r in rows if self.real({"lines": [r["line_id"]]}, not self.reliable)
        ]
        by_audit = sum(1 for r in rows if r["line_id"] in lines and coder_code(r) == "L")
        by_final = sum(1 for i in lines if self.pre[i] == "L")
        return {
            "models_in_ledger": self.ledger_models("audit"),
            "kappa5": kappa_stats(r5, len(CATS6)),
            "kappaL": kappa_stats(rl, len(CATS_L)),
            "real_lines": len(lines),
            "L_share_by_audit_codes": by_audit / len(lines) if lines else None,
            "L_share_by_final_codes": by_final / len(lines) if lines else None,
        }

    # ---- secondaries

    def representative(self, u: dict[str, Any], code: str) -> str | None:
        ls = sorted(i for i in self.code_lines(u, not self.reliable) if self.final[i] == code)
        return ls[0] if ls else None

    def l_fields(self, lid: str) -> dict[str, Any]:
        f = self.deciding.get(lid) or {}
        version = self.sets[self.lines[lid]["set"]].version(
            self.lines[lid]["pair"], self.lines[lid]["side"]
        )
        gr = f.get("gate_relation")
        origin = (
            "existing relation the gate did not form" if gr and gr != "none" else "new relation"
        )
        inputs = f.get("inputs") or []
        nodes = sorted({i.get("node") for i in inputs if i.get("node")})
        table = G.appendix_c()
        unformed = None
        if gr and gr != "none" and gr in table:
            member = table[gr][1]
            if any(
                not isinstance(i.get("quantity"), str) or not member(i["quantity"]) for i in inputs
            ):
                unformed = "name"
            elif len(nodes) > 1 and not all(
                V.joined(a, b, version) for a in nodes for b in nodes if a < b
            ):
                unformed = "edge"
            else:
                unformed = "formed"
        if len(nodes) == 1:
            joined = "one node"
        elif len(nodes) == 2 and V.joined(nodes[0], nodes[1], version):
            joined = "two nodes joined by one edge"
        else:
            joined = "neither"
        facts = (f.get("_verified") or {}).get("relation_facts") or {}
        return {
            "relation_origin": origin,
            "unformed_by": unformed,
            "joined": joined,
            "kind": f.get("kind"),
            "law": f.get("law"),
            "relation": f.get("relation"),
            "literals": facts.get("literals", []),
            "one_input_each_side_non_integer_literal": bool(
                facts.get("one_input_each_side") and facts.get("non_integer_literal")
            ),
            "gap": lid in self.gap,
        }

    def kind_of(self, lid: str | None, code: str) -> str:
        if lid is None:
            return "?"
        f = self.deciding.get(lid) or {}
        if f.get("code") != code:
            return "fallback"
        return str(f.get("d_kind" if code == "D" else "n_kind") or "?")

    def false_positive_audit(self, l_lines: list[str]) -> dict[str, Any]:
        seen: dict[str, dict[str, Any]] = {}
        for lid in l_lines:
            f = self.deciding.get(lid)
            if not f:
                continue
            sig = json.dumps(
                [
                    self.lines[lid]["set"],
                    f.get("relation"),
                    sorted(
                        [i.get("symbol"), i.get("node"), i.get("quantity"), i.get("requirement")]
                        for i in f.get("inputs") or []
                    ),
                    f.get("tolerance"),
                    f.get("tolerance_percent"),
                    f.get("kind"),
                ],
                default=str,
            )
            seen.setdefault(sig, {"line": lid, "form": f, "set": self.lines[lid]["set"]})
        per = []
        blocked_twins: set[tuple[str, str]] = set()
        for _sig, s in sorted(seen.items()):
            sd = self.sets[s["set"]]
            blocks = []
            for pair in sorted(sd.artefacts):
                nodes = sd.version(pair, "twin")
                form = dict(s["form"])
                inputs = []
                ok = True
                for i in form.get("inputs") or []:
                    i = dict(i)
                    if "quantity" in i:
                        q = (nodes.get(i["node"], {}).get("quantities") or {}).get(i["quantity"])
                        if q is None or q.get("value") is None:
                            ok = False
                            break
                        i["value"], i["unit"] = q["value"], q["unit"]
                    inputs.append(i)
                if not ok:
                    continue
                form["inputs"] = inputs
                try:
                    V.verify_relation(form, nodes)
                    blocks.append(pair)
                except V.Failure:
                    continue
            blocked_twins |= {(s["set"], p) for p in blocks}
            per.append(
                {"line": s["line"], "relation": s["form"].get("relation"), "blocks": len(blocks)}
            )
        return {
            "relations": len(per),
            "per_relation": per,
            "blocks_total": sum(p["blocks"] for p in per),
            "distinct_twins_blocked": len(blocked_twins),
        }

    # ---- everything

    def run(self) -> dict[str, Any]:
        out: dict[str, Any] = {"dry_run": self.dry_run}
        k = self.kappas()
        out["agreement"] = k
        er = not self.reliable
        flaws = self.unit_rows(self.flaws)
        out["reality"] = {
            "reliable": self.reliable,
            "primary_presumes_every_line_real": er,
            **{
                k_: self.rsum[k_]
                for k_ in ("calibration", "rejection", "prior_agreement", "verdicts_by_side")
            },
        }
        out["population"] = {
            "measured_lines": len(self.measured),
            "measured_flaws": len(flaws),
            "real_flaws": sum(1 for u in flaws if self.real(u, er)),
            "flaw_reality": dict(Counter(self.rsum["flaw_reality"].values())),
        }
        prim = self.share(flaws, er)
        out["primary"] = prim
        # secondaries
        codes = Counter(self.unit_code(u, er) for u in flaws if self.real(u, er))
        n = prim["n"]

        def sh(c: int) -> float | None:
            return c / n if n else None

        g_parts: Counter[str] = Counter()
        d_kinds: Counter[str] = Counter()
        n_kinds: Counter[str] = Counter()
        l_reps: list[str] = []
        l_all: list[str] = []
        for u in flaws:
            if not self.real(u, er):
                continue
            c = self.unit_code(u, er)
            rep = self.representative(u, c) if c in ORDER else None
            if c == "G" and rep is not None:
                g_parts[
                    "coders claimed G" if self.pre[rep] == "G" else "coders coded L or L-if-data"
                ] += 1
            if c == "D":
                d_kinds[self.kind_of(rep, "D")] += 1
            if c == "N":
                n_kinds[self.kind_of(rep, "N")] += 1
            if c == "L" and rep is not None:
                l_reps.append(rep)
                l_all += [i for i in self.code_lines(u, er) if self.final[i] == "L"]
        fields = [self.l_fields(i) for i in l_reps]
        out["secondary"] = {
            "shares": {c: sh(codes.get(c, 0)) for c in (*ORDER, "uncoded")},
            "counts": dict(codes),
            "G_parts": dict(g_parts),
            "D_by_kind": dict(d_kinds),
            "N_by_kind": dict(n_kinds),
            "L_plus_L_if_data": self.share(flaws, er, ("L", "L-if-data")),
            "L_split": {
                key: dict(Counter(str(f[key]) for f in fields))
                for key in ("relation_origin", "unformed_by", "joined", "kind", "law")
            },
            "L_gap_from_coder_G": sum(1 for f in fields if f["gap"]),
            "L_literals": self.l_literals(),
        }

        def role_of(u: dict[str, Any]) -> str:
            return (
                "base"
                if u["base"]
                else self.sets[u["set"]].artefacts[u["pairs"][0]]["assigned_role"]
            )

        def class_of(u: dict[str, Any]) -> str:
            return (
                "base" if u["base"] else self.sets[u["set"]].artefacts[u["pairs"][0]]["error_class"]
            )

        def kinds_of(u: dict[str, Any]) -> set[str]:
            return {self.lines[i]["kind"] for i in u["lines"]}

        bd: dict[str, Any] = {}
        for name, f in (("role", role_of), ("class", class_of)):
            vals = sorted({f(u) for u in flaws})
            bd[name] = {v: self.share(flaws, er, keep=_is(f, v)) for v in vals}
        bd["set"] = {
            s: self.share(flaws, er, keep=_is(lambda u: str(u["set"]), s)) for s in X.SET_ORDER
        }
        bd["reviewer_kind"] = {
            k_: self.share(flaws, er, keep=_has(kinds_of, k_)) for k_ in ("paired", "generalist")
        }
        inj = self.share(flaws, er, keep=self.on_injection)
        else_ = self.share(flaws, er, keep=lambda u: not self.on_injection(u))
        bd["origin"] = {"on the injection": inj, "elsewhere": else_}
        bd["origin_earlier_definition_count"] = sum(
            1
            for i in self.measured
            if self.lines[i]["side"] == "injected"
            and {(a, b) for a, b in self.lines[i]["locus"]}
            & self.sets[self.lines[i]["set"]].changed_pairs(self.lines[i]["pair"])
        )
        out["breakdowns"] = bd
        out["false_positive_audit"] = self.false_positive_audit(l_all)
        mult = [
            i for i in self.measured if (self.deciding.get(i) or {}).get("multiple_defects") is True
        ]
        out["counts"] = {
            "multiple_defects_lines": len(mult),
            "further_codes": dict(
                Counter(
                    fu.get("code")
                    for i in mult
                    for fu in (self.deciding.get(i) or {}).get("further") or []
                )
            ),
            "base_flaws_measured": sum(1 for u in flaws if u["base"]),
            "base_flaws_spanning_slice": self.slice.get("base_flaws_spanning_slice_and_measured"),
            "excluded_records": self.ecounts.get("excluded"),
        }
        out["interruptions"] = self.interruptions()
        out["per_coder"] = self.per_coder()
        out["kappa_flaw_level"] = self.kappa_flaw_level()
        out["audit"] = self.audit()
        # the decision
        mix = (
            inj["share"] is not None
            and else_["share"] is not None
            and ((inj["share"] >= T) != (else_["share"] >= T))
        )
        deciding_name = "elsewhere" if mix else "primary"
        deciding = else_ if mix else prim
        keep = (lambda u: not self.on_injection(u)) if mix else None
        readings = {
            "S1": self.share(self.unit_rows(self.s1), er, keep=keep),
            "S2": self.share(self.line_units(), er, keep=keep),
            "S3": self.share(flaws, er, how="majority", keep=keep),
            "S4": self.share(flaws, True, keep=keep),
            "S5": self.share(flaws, er, strict=True, keep=keep),
            "S6": self.share(self.unit_rows(self.s6), er, keep=keep),
        }
        out["readings"] = readings
        ds = deciding["share"]
        side = None if ds is None else ds >= T
        resolved, wider = resolution(deciding["wilson"], deciding["cluster"])
        crossing = [
            name for name, r in readings.items() if r["share"] is None or (r["share"] >= T) != side
        ]
        # beside the deciding share, on its own flaws: all of them, or those elsewhere
        lplus = self.share(flaws, er, ("L", "L-if-data"), keep=keep)["share"]
        taken = not self.deviations
        priority = bool(side) and k["meets_floor"] and taken
        out["decision"] = {
            "threshold": T,
            "deciding_share": deciding_name,
            "mix_dependent": mix,
            "share": ds,
            "branch": "priority" if priority else "small, targeted library",
            "taken": taken,
            "resolved": resolved,
            "wider_interval": wider,
            "robust": not crossing,
            "readings_crossing": crossing,
            "strict_law_share": readings["S5"]["share"],
            "L_flaws_one_input_each_side_non_integer_literal": sum(
                1 for f in fields if f["one_input_each_side_non_integer_literal"]
            ),
            "L_plus_L_if_data": lplus,
            "scope_note_data_side": bool(
                ds is not None and ds < T and lplus is not None and lplus >= T
            ),
            "below_kappa_floor": not k["meets_floor"],
            "unreliable_label": None if k["meets_floor"] else "unreliable, not a ceiling",
            "deviations": self.deviations,
            "interruptions_reported": out["interruptions"]["events"],
        }
        return out

    def l_literals(self) -> list[dict[str, Any]]:
        """§8.2 item 8: every L relation of the measured set, with its literals and the lines that
        state it (every measured line whose final code is L, not one line per flaw)."""
        by: dict[str, dict[str, Any]] = {}
        for lid in sorted(self.measured):
            if self.final[lid] != "L":
                continue
            f = self.deciding.get(lid) or {}
            facts = (f.get("_verified") or {}).get("relation_facts") or {}
            rel = str(f.get("relation"))
            e = by.setdefault(
                rel,
                {"relation": rel, "literals": facts.get("literals", []), "kinds": [], "lines": []},
            )
            e["lines"].append(lid)
            if f.get("kind") not in e["kinds"]:
                e["kinds"].append(f.get("kind"))
        return [by[r] for r in sorted(by)]

    def interruptions(self) -> dict[str, Any]:
        """Every logged stop, failed call and resume, with its time: each an interruption RESULT
        reports, never a deviation. None changes whether the decision is taken: a resumed packet
        is an independent session on fixed inputs, and a failed call is not a try."""
        p = self.work / "ledger" / "interruptions.jsonl"
        rows = X.read_jsonl(p) if p.exists() else []
        return {
            "events": len(rows),
            "stops": sum(1 for r in rows if r["event"] == "stop"),
            "failed_calls": sum(1 for r in rows if r["event"] == "failed_call"),
            "resumes": sum(1 for r in rows if r["event"] == "resume"),
            "log": rows,
        }

    def ledger_models(self, step: str) -> list[str]:
        led = self.work / "ledger" / "ledger.jsonl"
        if not led.exists():
            return []
        return sorted({m for r in X.read_jsonl(led) if r["step"] == step for m in r["models_used"]})

    def per_coder(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        g_lines = [i for i in self.measured if self.final[i] == "G"]
        for who in ("c1", "c2", "adj", "audit"):
            rows = [r for r in self.codes if r["who"] == who and r["line_id"] in self.measured]
            if not rows:
                continue
            claimed = sum(1 for i in g_lines if coder_code(self.coded.get(i, {}).get(who)) == "G")
            out[who] = {
                "forms": len(rows),
                "without_form": sum(1 for r in rows if r.get("form") is None),
                "failures": dict(Counter(r["failure"] for r in rows if r.get("failure"))),
                "inconsistent_l_if_data": sum(1 for r in rows if r.get("inconsistent")),
                "share_of_gate_caught_lines_claimed_G": (claimed / len(g_lines))
                if g_lines
                else None,
            }
        adj = [r for r in self.codes if r["who"] == "adj" and r["line_id"] in self.measured]
        out["adjudicator_choices"] = dict(
            Counter(
                (r.get("labels") or {}).get(r["form"]["chosen"], "other")
                if r.get("form") and r["form"].get("chosen") in ("A", "B")
                else (r["form"] or {}).get("chosen", "none")
                for r in adj
            )
        )
        return out


def main(argv: list[str]) -> int:
    if not argv or len(argv) > 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(argv[0])
    try:
        res = Tally(work, "--dry-run" in argv).run()
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    (work / "tally.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    print(json.dumps(res, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
