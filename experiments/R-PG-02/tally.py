"""R-PG-02: the three runs to §4's R, A and J per layer and set, P1–P5, and every §8 figure.

Usage, after every run has ended and never before:

    uv run python -I tally.py --a-fresh <run> --b-fresh <run> --a-old <run>
        --fresh-corpus <dir> --old-corpus <dir>
        [--practice-run <run> --practice-corpus <dir>] [--any-count] [--draws N]

Read-only over the runs and the sets; prints one JSON document. Every quantity follows
CRITERIA.md, and every rule is closed and mechanical: no model reads a review.

- **R_rev (§4.1, the item rule):** the injected review is a ``fail`` and *names* the error: it
  cites (``unmet`` or ``confirmed``, or as its failing item) an item of its cell in
  :data:`ERROR_ITEMS` (paired) or :data:`GENERALIST_ITEMS` that its twin's review does not cite.
  A review line that is not a verdict cites nothing. An empty cell is *unscored*.
- **R_gate:** a failing record of the injected item intersects the nodes the injection
  changed (:func:`changed_nodes`, :func:`intersects`). *Caught* is any failing record.
- **A_rev:** the twin's review is a ``pass``. **A_gate:** the twin has no failing record,
  except that a twin whose every failing record is a headroom refusal against a
  continuous-rating ``current_limit`` is scored as that stated limit (§4.2); the strict figure
  is printed beside.
- **Sheet-flaw rejection (§4.2):** a twin's ``fail`` whose failing item's evidence names a
  (node, quantity) pair the source check lists as ``subtracted`` or ``unresolved`` in the base
  or the twin's own revision.
- **No verdict and unscored (§4.4)** count against the layer in both directions; the
  verdict-only figures, the ranges and the unscored-dropped figure are printed beside.
- **J = R + A − 1**; Wilson 95 % intervals for R and A; a bootstrap over pairs for J and its
  differences, ``--draws`` draws (10,000) at seed 13.

``--any-count`` lifts the denominator check (40), for a test corpus only.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

#: §4.1's table, verbatim: the paired column, by role, then by error class.
ERROR_ITEMS: dict[str, dict[str, tuple[str, ...]]] = {
    "control": {
        "unit": ("D25", "D26"),
        "magnitude": ("D25", "D27"),
        "equilibrium": ("D25", "D27"),
        "propagation": ("D28",),
    },
    "electrical": {
        "unit": ("ES-31", "ES-32"),
        "magnitude": ("ES-32",),
        "equilibrium": ("ES-7", "ES-9", "ES-32", "ES-33"),
        "propagation": ("ES-34",),
    },
    "firmware": {
        "unit": ("DS-27",),
        "magnitude": ("DS-27",),
        "equilibrium": ("DS-27",),
        "propagation": ("DS-30",),
    },
    "mechanical": {
        "unit": ("MS-2",),
        "magnitude": ("MS-3",),
        "equilibrium": ("MS-3", "MS-4", "MS-26"),
        "propagation": ("MS-5",),
    },
}
#: §4.1's generalist column: each role's Section 1 line for a revision with no issued
#: specification, the same for every class.
GENERALIST_ITEMS: dict[str, tuple[str, ...]] = {
    "control": ("A7",),
    "electrical": ("EA-9",),
    "firmware": ("AC-9",),
    "mechanical": ("MA-10",),
}
#: R-PG-01's own table (its CRITERIA §6), keyed by the expected check: secondary result 5.
R_PG_01_ITEMS: dict[str, dict[str, tuple[str, ...]]] = {
    "control": {"units": ("D25", "D26"), "magnitude": ("D25", "D27"), "propagation": ("D28",)},
    "electrical": {
        "units": ("ES-31", "ES-32"),
        "magnitude": ("ES-32",),
        "power": ("ES-7", "ES-33"),
        "conservation": ("ES-7", "ES-9", "ES-33"),
        "thermal": ("ES-19", "ES-20", "ES-35"),
        "propagation": ("ES-34",),
    },
    "firmware": {"units": ("DS-27",), "magnitude": ("DS-27",), "propagation": ("DS-30",)},
    "mechanical": {
        "units": ("MS-2",),
        "magnitude": ("MS-3",),
        "equilibrium": ("MS-4",),
        "conservation": ("MS-3", "MS-26"),
        "propagation": ("MS-5",),
    },
}
CLASSES = ("unit", "magnitude", "equilibrium", "propagation")
ROLES = ("control", "electrical", "firmware", "mechanical")
CHECKS = ("units", "magnitude", "equilibrium", "power", "conservation", "thermal", "propagation")
DENOMINATOR = 40
CITING = ("unmet", "confirmed")
NO_VERDICT = ("blocked", "review_unavailable", "missing")
BOOTSTRAP_SEED = 13
BOOTSTRAP_DRAWS = 10_000
#: P2's floor, P5's judgement, and the risk row's thresholds (§6, §7).
P2_FLOOR = 20
POSSIBLE_TAILORING = 0.15
ROW_C_THRESHOLD, ROW_A_THRESHOLD = 10, 4
#: The dated price sheet the cost is read at; cache writes at the one-hour rate (§8, item 8).
PRICE_SHEET = "2026-10-16"
FORCES_ONLY = re.compile(r"(\d+) passed on forces alone")
UNKNOWN_NAME = "catalogue does not know"
HEADROOM = "current limit of"


class TallyError(Exception):
    """The runs or sets are not ones this script can read faithfully."""


# ---------------------------------------------------------------- reading a run


def read_lines(path: Path) -> list[dict[str, Any]]:
    """A JSON-lines file's lines, in the order written."""
    if not path.is_file():
        raise TallyError(f"no file at {path}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@dataclass
class Log:
    """One run log, indexed by subtask: role, last review line, gate result, every review line."""

    role: dict[str, str] = field(default_factory=dict)
    review: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate: dict[str, dict[str, Any]] = field(default_factory=dict)
    reviews: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def read(cls, path: Path) -> Log:
        log = cls()
        for line in read_lines(path):
            kind, sid = line.get("kind"), line.get("subtask_id")
            if kind == "subtask_planned":
                if sid in log.role:
                    raise TallyError(f"subtask {sid} is planned twice in {path}")
                log.role[sid] = line["assigned_role"]
            elif kind in ("review_ran", "review_unavailable"):
                log.review[sid] = line
                log.reviews.append(line)
            elif kind == "gate_ran":
                log.gate[sid] = line["result"]
        return log


@dataclass
class Run:
    """One instrument run directory, read whole."""

    path: Path
    rows: list[dict[str, Any]]
    injected: Log
    controls: Log
    config: dict[str, Any]
    records: dict[str, dict[str, Any]]
    pauses: int

    @classmethod
    def read(cls, path: Path, any_count: bool) -> Run:
        rows = read_lines(path / "results.jsonl")
        if len(rows) != DENOMINATOR and not any_count:
            raise TallyError(f"{path}: {len(rows)} rows; the denominator is {DENOMINATOR}")
        records = {}
        reviews = path / "reviews"
        if reviews.is_dir():
            for p in sorted(reviews.glob("*.json")):
                records[p.stem] = json.loads(p.read_text())
        pauses_path = path / "pauses.jsonl"
        pauses = len(read_lines(pauses_path)) if pauses_path.is_file() else 0
        return cls(
            path=path,
            rows=rows,
            injected=Log.read(path / "events.jsonl"),
            controls=Log.read(path / "controls" / "events.jsonl"),
            config=json.loads((path / "instrument.json").read_text()),
            records=records,
            pauses=pauses,
        )

    @property
    def kind(self) -> str:
        return str(self.config.get("reviewer_kind", "paired"))


# ---------------------------------------------------------------- one review


def outcome(line: dict[str, Any] | None) -> tuple[str, str | None]:
    """A review's outcome and cause, as the instrument derives them."""
    if line is None:
        return "missing", "no review line"
    if line["kind"] == "review_unavailable":
        return "review_unavailable", line["cause"]
    verdict = line["result"]["verdict"]
    return verdict, ("blocking_spec_defect" if verdict == "blocked" else None)


def cited(line: dict[str, Any] | None) -> frozenset[str]:
    """The items a review cites: unmet or confirmed, and its failing item."""
    if line is None or line["kind"] != "review_ran":
        return frozenset()
    result = line["result"]
    items = {i["item"] for i in result.get("items", ()) if i["result"] in CITING}
    if result.get("failing_item"):
        items.add(result["failing_item"])
    return frozenset(items)


def failing_evidence(line: dict[str, Any] | None) -> str:
    """The evidence a review gives for its failing item, joined; '' if none."""
    if line is None or line["kind"] != "review_ran":
        return ""
    result = line["result"]
    item = result.get("failing_item")
    return " ".join(i["evidence"] for i in result.get("items", ()) if i["item"] == item)


def cell(kind: str, role: str, error_class: str) -> tuple[str, ...]:
    """§4.1's cell for an item: its class and role in the paired column, or the generalist's."""
    if role not in ERROR_ITEMS or error_class not in CLASSES:
        raise TallyError(f"no table cell for role {role!r} and class {error_class!r}")
    if kind == "generalist":
        return GENERALIST_ITEMS[role]
    return ERROR_ITEMS[role].get(error_class, ())


def naming(items: tuple[str, ...], review: frozenset[str], twin: frozenset[str]) -> dict[str, Any]:
    """Whether a review named its error, with and without the twin condition."""
    if not items:
        return {"error_items": [], "named": None, "cited_at_all": None, "deciding": []}
    hit = set(items) & review
    deciding = sorted(hit - twin)
    return {
        "error_items": list(items),
        "named": bool(deciding),
        "cited_at_all": bool(hit),
        "deciding": deciding,
    }


def names_pair(text: str, node: str, quantity: str) -> bool:
    """Whether the text names (node, quantity): the quantity as a word, and the node or its name."""
    low = text.casefold()
    if not re.search(rf"\b{re.escape(quantity.casefold())}\b", low):
        return False
    short = node.split(".", 1)[1] if "." in node else node
    return node.casefold() in low or bool(re.search(rf"\b{re.escape(short.casefold())}\b", low))


# ---------------------------------------------------------------- the set


@dataclass(frozen=True)
class SetFacts:
    """What the tally reads from a set itself, mechanically, after the run."""

    changed: dict[str, frozenset[str]]
    sheet_pairs: dict[str, frozenset[tuple[str, str]]]
    mismatched_twins: tuple[str, ...]
    continuous_limits: dict[str, frozenset[str]]
    continuous_count: int
    edges: dict[str, tuple[str, str]]


def changed_nodes(
    clean: Iterable[dict[str, Any]],
    injected: Iterable[dict[str, Any]],
    edge: tuple[str, str] | None,
) -> frozenset[str]:
    """Every node whose payload differs between the patches, or is in one only; the edge's ends."""
    a = {n["id"]: json.dumps(n, sort_keys=True) for n in clean}
    b = {n["id"]: json.dumps(n, sort_keys=True) for n in injected}
    found = {i for i in a.keys() | b.keys() if a.get(i) != b.get(i)}
    if edge is not None:
        found |= set(edge)
    return frozenset(found)


def _continuous_rows(corpus: Any, source: str, written: Any) -> bool:  # noqa: ANN401
    """Whether the rows a number cites include a continuous rating, by the row's own words."""
    from physgate.evaluation.inject.corpus import _numbers, derivation

    rows = corpus.sources.rows
    head, _, rest = source.partition(":")
    if head == "derived":
        try:
            _, ids = derivation(rest)
        except ValueError:
            return False
        return any("continuous" in rows[i].quantity.casefold() for i in ids if i in rows)
    numbers = _numbers(corpus.sources)
    for row_id, row in rows.items():
        if (
            row.url != source
            or row_id not in numbers
            or "continuous" not in row.quantity.casefold()
        ):
            continue
        number = numbers[row_id]
        if number.dimensionality != written.dimensionality:
            continue
        value = Fraction(str(written.to(number.units).magnitude))
        target = Fraction(str(number.magnitude))
        if abs(value - target) <= Fraction(5, 1000) * abs(target):
            return True
    return False


def set_facts(corpus_dir: Path) -> SetFacts:
    """Changed nodes, the sheet's listed pairs, and the continuous-rating limits of one set."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.source_check import check_sources
    from physgate.gate.units import PINT_ERRORS, UnitRefusedError, parse

    corpus = load_corpus(corpus_dir.resolve())
    changed, edges = {}, {}
    for a in corpus.artefacts:
        edge = (a.edge.source, a.edge.target) if a.edge is not None else None
        if edge is not None:
            edges[a.id] = edge
        changed[a.id] = changed_nodes(a.clean.nodes, a.injected.nodes, edge)
    findings = check_sources(corpus)
    places: dict[str, set[tuple[str, str]]] = {}
    mismatched: set[str] = set()
    for f in findings:
        place = "base" if f.where == "base" else f.where.removeprefix("revision ")
        if f.kind in ("subtracted", "unresolved"):
            places.setdefault(place, set()).add((f.node, f.quantity))
        elif place != "base":
            mismatched.add(place)
    base_pairs = frozenset(places.get("base", set()))
    sheet_pairs = {a.id: base_pairs | frozenset(places.get(a.id, set())) for a in corpus.artefacts}
    continuous: dict[str, frozenset[str]] = {}
    count = 0
    base_nodes = {n["id"]: n for n in corpus.base.nodes}
    for a in corpus.artefacts:
        graph = {**base_nodes, **{n["id"]: n for n in a.clean.nodes}}
        found = set()
        for node_id, payload in graph.items():
            q = (payload.get("quantities") or {}).get("current_limit")
            if not q:
                continue
            try:
                written = parse(q["value"], q["unit"])
            except (UnitRefusedError, *PINT_ERRORS):
                continue
            if _continuous_rows(corpus, str(q["source"]), written):
                found.add(node_id)
        continuous[a.id] = frozenset(found)
    for payload in [*corpus.base.nodes, *(n for a in corpus.artefacts for n in a.clean.nodes)]:
        q = (payload.get("quantities") or {}).get("current_limit")
        if q:
            try:
                count += _continuous_rows(corpus, str(q["source"]), parse(q["value"], q["unit"]))
            except (UnitRefusedError, *PINT_ERRORS):
                pass
    return SetFacts(changed, sheet_pairs, tuple(sorted(mismatched)), continuous, count, edges)


# ---------------------------------------------------------------- the gate


def intersects(record: dict[str, Any], nodes: frozenset[str]) -> bool:
    """A failing record touches a changed node: its node, module, details, or message."""
    if record.get("node") in nodes or record.get("module") in nodes:
        return True
    details = record.get("details") or {}
    named: set[str] = set(details.get("contributing", ()))
    named |= {t["node_id"] for t in details.get("terms", ())}
    named |= {r["support"] for r in (*details.get("solved", ()), *details.get("declared", ()))}
    if named & nodes:
        return True
    text = " ".join([record.get("message") or "", *details.get("unwritten", ())])
    return any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", text) for n in nodes)


def is_stated_headroom(record: dict[str, Any], continuous: frozenset[str]) -> bool:
    """A headroom refusal whose supply's ``current_limit`` cites a continuous rating."""
    return (
        record["name"] == "power"
        and HEADROOM in (record.get("message") or "")
        and record.get("node") in continuous
    )


def gate_item(result: dict[str, Any], nodes: frozenset[str]) -> dict[str, Any]:
    """One injected item's gate figures."""
    fails = [r for r in result.get("checks", ()) if r["outcome"] == "fail"]
    right = any(intersects(r, nodes) for r in fails)
    return {
        "caught": bool(fails),
        "right_reason": right,
        "caught_elsewhere": bool(fails) and not right,
        "failing_checks": sorted({r["name"] for r in fails}),
    }


def check_counts(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Per check, over the records given: passes with their evaluated counts beside them."""
    out: dict[str, dict[str, int]] = {
        c: {
            "pass_records": 0,
            "evaluated": 0,
            "nothing_in_scope": 0,
            "fail_records": 0,
            "unchecked_records": 0,
        }
        for c in CHECKS
    }
    forces_mounts = forces_items = 0
    for result in results:
        item_forces = False
        for r in result.get("checks", ()):
            row = out[r["name"]]
            if r["outcome"] == "pass":
                evaluated = int((r.get("details") or {}).get("evaluated", 0))
                row["pass_records"] += 1
                row["evaluated"] += evaluated
                row["nothing_in_scope"] += evaluated == 0
                m = FORCES_ONLY.search(r.get("tool") or "")
                if r["name"] == "equilibrium" and m:
                    forces_mounts += int(m.group(1))
                    item_forces = True
            elif r["outcome"] == "fail":
                row["fail_records"] += 1
            elif r["outcome"] == "unchecked":
                row["unchecked_records"] += 1
        forces_items += item_forces
    return {
        "per_check": out,
        "equilibrium_mounts_passed_on_forces_alone": forces_mounts,
        "items_with_a_forces_only_pass": forces_items,
    }


def unknown_names(results: Iterable[dict[str, Any]]) -> list[str]:
    """Distinct quantity names the units check recorded unchecked as uncatalogued."""
    found: set[str] = set()
    for result in results:
        for r in result.get("checks", ()):
            if r["outcome"] == "unchecked" and UNKNOWN_NAME in (r.get("message") or ""):
                found |= set((r.get("details") or {}).get("quantities", ()))
    return sorted(found)


# ---------------------------------------------------------------- statistics


def wilson(k: int, n: int) -> list[float]:
    """The Wilson 95 % interval of k of n."""
    if n == 0:
        return [0.0, 1.0]
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def percentiles(values: list[float]) -> list[float]:
    """The 2.5th and 97.5th percentiles, nearest rank on the sorted draws."""
    s = sorted(values)
    lo = s[math.floor(0.025 * (len(s) - 1))]
    hi = s[math.ceil(0.975 * (len(s) - 1))]
    return [round(lo, 4), round(hi, 4)]


def j_of(pairs: list[tuple[int, int]]) -> float:
    """J over pairs of (rejected for the right reason, accepted)."""
    n = len(pairs)
    return sum(r for r, _ in pairs) / n + sum(a for _, a in pairs) / n - 1


def boot(stat: Callable[[random.Random], float], draws: int) -> list[float]:
    """The bootstrap interval of ``stat``, at the pre-registered seed, a fresh stream each time."""
    rng = random.Random(BOOTSTRAP_SEED)
    return percentiles([stat(rng) for _ in range(draws)])


def resample(rng: random.Random, n: int) -> list[int]:
    return [rng.randrange(n) for _ in range(n)]


def j_interval(pairs: list[tuple[int, int]], draws: int) -> list[float]:
    """J's interval: the pairs resampled."""
    return boot(lambda rng: j_of([pairs[i] for i in resample(rng, len(pairs))]), draws)


def contrast_interval(
    a: list[tuple[int, int]], b: list[tuple[int, int]], draws: int
) -> list[float]:
    """J_a − J_b on the same pairs, resampled jointly."""
    if len(a) != len(b):
        raise TallyError("a contrast needs the same pairs in both arms")

    def stat(rng: random.Random) -> float:
        idx = resample(rng, len(a))
        return j_of([a[i] for i in idx]) - j_of([b[i] for i in idx])

    return boot(stat, draws)


def drop_interval(
    before: list[tuple[int, int]], after: list[tuple[int, int]], draws: int
) -> list[float]:
    """J_before − J_after over two sets, each resampled on its own."""

    def stat(rng: random.Random) -> float:
        x = [before[i] for i in resample(rng, len(before))]
        y = [after[i] for i in resample(rng, len(after))]
        return j_of(x) - j_of(y)

    return boot(stat, draws)


def figures(
    items: list[dict[str, Any]],
    r_key: str,
    a_key: str,
    draws: int,
    r_open: str | None = None,
    a_open: str | None = None,
    unscored: str | None = None,
) -> dict[str, Any]:
    """R, A and J of one layer over its pairs, with their intervals and the §4.4 columns.

    ``r_open``/``a_open`` name the per-item flag of an injected or twin review with no verdict;
    ``unscored`` names the flag of an unscored injected item.
    """
    n = len(items)
    if n == 0:
        return {"n": 0}
    pairs = [(int(bool(p[r_key])), int(bool(p[a_key]))) for p in items]
    r, a = sum(x for x, _ in pairs), sum(y for _, y in pairs)
    out: dict[str, Any] = {
        "n": n,
        "R": r,
        "A": a,
        "J": round(r / n + a / n - 1, 4),
        "R_wilson95": wilson(r, n),
        "A_wilson95": wilson(a, n),
        "J_bootstrap95": j_interval(pairs, draws),
    }
    if r_open and a_open:
        ro = [p for p in items if p[r_open]]
        ao = [p for p in items if p[a_open]]
        rv, av = n - len(ro), n - len(ao)
        r_in = sum(int(bool(p[r_key])) for p in items if not p[r_open])
        a_in = sum(int(bool(p[a_key])) for p in items if not p[a_open])
        out["no_verdict"] = {"injected": len(ro), "twins": len(ao)}
        out["among_verdicts_only"] = {
            "R": [r_in, rv],
            "A": [a_in, av],
            "J": round((r_in / rv if rv else 0) + (a_in / av if av else 0) - 1, 4),
        }
        out["range_if_each_no_verdict_went_either_way"] = {
            "R": [r, r + len(ro)],
            "A": [a, a + len(ao)],
            "J": [round((r + a) / n - 1, 4), round((r + len(ro) + a + len(ao)) / n - 1, 4)],
        }
    if unscored:
        u = sum(1 for p in items if p[unscored])
        out["unscored"] = u
        out["R_with_unscored_dropped"] = [r, n - u]
    return out


# ---------------------------------------------------------------- one run, item by item


def per_item(run: Run, facts: SetFacts, kind: str) -> list[dict[str, Any]]:
    """Every pair of one run, with its review, its twin's review and the gate on both."""
    out = []
    for row in run.rows:
        aid, rid, cid = row["artefact"], row["review_id"], row["control_id"]
        if rid not in run.injected.role or rid not in run.injected.gate:
            raise TallyError(f"{aid}: no planned line or gate line in the injected log")
        if cid not in run.controls.gate:
            raise TallyError(f"{aid}: no gate line for its twin in the controls log")
        role = run.injected.role[rid]
        line, twin_line = run.injected.review.get(rid), run.controls.review.get(cid)
        verdict, cause = outcome(line)
        twin_verdict, twin_cause = outcome(twin_line)
        if verdict != row["reviewer_verdict"]:
            raise TallyError(f"{aid}: the log's review outcome disagrees with the row")
        if row.get("control_reviewer_verdict") not in (None, twin_verdict):
            raise TallyError(f"{aid}: the log's twin review outcome disagrees with the row")
        gate = gate_item(run.injected.gate[rid], facts.changed[aid])
        if gate["caught"] != (row["gate_verdict"] == "fail"):
            raise TallyError(f"{aid}: failing records disagree with the row's verdict")
        twin_fails = [r for r in run.controls.gate[cid].get("checks", ()) if r["outcome"] == "fail"]
        stated = bool(twin_fails) and all(
            is_stated_headroom(r, facts.continuous_limits.get(aid, frozenset())) for r in twin_fails
        )
        review_items, twin_items = cited(line), cited(twin_line)
        name = naming(cell(kind, role, row["error_class"]), review_items, twin_items)
        sheet = twin_verdict == "fail" and any(
            names_pair(failing_evidence(twin_line), n, q) for n, q in facts.sheet_pairs.get(aid, ())
        )
        record = run.records.get(rid, {})
        twin_record = run.records.get(cid, {})
        out.append(
            {
                "artefact": aid,
                "class": row["error_class"],
                "role": role,
                "expected_check": row["expected_check"],
                "lane": record.get("lane"),
                "review": verdict,
                "review_cause": cause,
                "twin_review": twin_verdict,
                "twin_review_cause": twin_cause,
                "cited_by_review": sorted(review_items),
                "cited_by_twin_review": sorted(twin_items),
                **name,
                "unscored": name["named"] is None,
                "R_rev": verdict == "fail" and name["named"] is True,
                "A_rev": twin_verdict == "pass",
                "rev_open": verdict in NO_VERDICT,
                "twin_open": twin_verdict in NO_VERDICT,
                "raw_reject": verdict == "fail",
                "sheet_flaw_rejection": sheet,
                **{f"gate_{k}": v for k, v in gate.items()},
                "expected_check_caught": row["expected_check"] in row.get("gate_blocking", ()),
                "twin_gate_failing_records": len(twin_fails),
                "A_gate_strict": not twin_fails,
                "A_gate": not twin_fails or stated,
                "twin_refused_under_stated_limit": stated,
                "gate_unchecked_records": sum(
                    r["outcome"] == "unchecked" for r in run.injected.gate[rid].get("checks", ())
                ),
                "tokens": int(record.get("tokens", row.get("reviewer_tokens", 0)))
                + int(twin_record.get("tokens", 0)),
                "r_pg_01_named": naming(
                    R_PG_01_ITEMS.get(role, {}).get(row["expected_check"], ()),
                    review_items,
                    twin_items,
                )["named"],
            }
        )
    return out


def reviewer_layer(items: list[dict[str, Any]], draws: int) -> dict[str, Any]:
    """The reviewers' R, A and J, with the sheet-flaw figures beside (§4.2)."""
    out = figures(items, "R_rev", "A_rev", draws, "rev_open", "twin_open", "unscored")
    n = len(items)
    sf = sum(p["sheet_flaw_rejection"] for p in items)
    a = out.get("A", 0)
    out["raw_reject"] = sum(p["raw_reject"] for p in items)
    out["sheet_flaw_rejections"] = sf
    out["without_sheet_flaw_rejections"] = {
        "A": [a, n - sf],
        "J": round(out.get("R", 0) / n + (a / (n - sf) if n - sf else 0) - 1, 4) if n else None,
    }
    out["named_without_twin_condition"] = sum(p["cited_at_all"] is True for p in items)
    return out


def gate_layer(items: list[dict[str, Any]], draws: int) -> dict[str, Any]:
    """The gate's R, A and J, with the strict acceptance and the any-record catch beside."""
    out = figures(items, "gate_right_reason", "A_gate", draws)
    out["raw_reject"] = sum(p["gate_caught"] for p in items)
    out["caught_any_record"] = sum(p["gate_caught"] for p in items)
    out["caught_elsewhere"] = sum(p["gate_caught_elsewhere"] for p in items)
    out["expected_check_among_caught"] = [
        sum(p["expected_check_caught"] for p in items if p["gate_caught"]),
        sum(p["gate_caught"] for p in items),
    ]
    out["A_gate_strict"] = sum(p["A_gate_strict"] for p in items)
    out["twins_refused_under_the_stated_headroom_limit"] = sorted(
        p["artefact"] for p in items if p["twin_refused_under_stated_limit"]
    )
    return out


def split_by(
    items: list[dict[str, Any]],
    key: str,
    values: Iterable[Any],
    fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    return {str(v): fn([p for p in items if p[key] == v]) for v in values}


def lists(items: list[dict[str, Any]]) -> dict[str, Any]:
    """§8 item 3: every review with no verdict, by role, artefact and twin, with its cause."""
    out: dict[str, Any] = {}
    for role in ROLES:
        mine = [p for p in items if p["role"] == role]
        out[role] = {
            "injected": [
                [p["artefact"], p["review"], p["review_cause"]] for p in mine if p["rev_open"]
            ],
            "twins": [
                [p["artefact"], p["twin_review"], p["twin_review_cause"]]
                for p in mine
                if p["twin_open"]
            ],
        }
    return out


def instrument_figures(run: Run) -> dict[str, Any]:
    """§8 items 3 and 7: repair resumes, schema refusals, retries, pauses and the wall clock."""
    lines = run.injected.reviews + run.controls.reviews
    ran = [x for x in lines if x["kind"] == "review_ran"]
    tries = [t for rec in run.records.values() for t in rec.get("tries", ())]
    starts = [t["started_at"] for t in tries if t.get("started_at")]
    ends = [t["ended_at"] for t in tries if t.get("ended_at")]
    return {
        "repair_resumes_used": sum(x["result"].get("repair_resumes") or 0 for x in ran),
        "verdicts_after_a_repair_resume": sum(
            (x["result"].get("repair_resumes") or 0) > 0 for x in ran
        ),
        "invalid_verdict_lines": sum(
            x["kind"] == "review_unavailable" and x["cause"] == "invalid_verdict" for x in lines
        ),
        "schema_refusals": sum(x["result"].get("schema_refusals") or 0 for x in ran),
        "reviews_with_schema_refusals": sum(
            (x["result"].get("schema_refusals") or 0) > 0 for x in ran
        ),
        "retries": sum(1 for t in tries if t.get("delay_before_s", 0) > 0),
        "retry_delays_s": dict(
            sorted(
                Counter(
                    str(t["delay_before_s"]) for t in tries if t.get("delay_before_s", 0) > 0
                ).items()
            )
        ),
        "lane_pauses": run.pauses,
        "wall_clock": [min(starts) if starts else None, max(ends) if ends else None],
    }


def cost(run: Run) -> dict[str, Any]:
    """§8 item 8: tokens of every class from the review lines, every try's total, and USD."""
    from importlib.resources import files

    sheet = json.loads(
        files("physgate.evaluation.observe").joinpath("prices", f"{PRICE_SHEET}.json").read_text()
    )
    seen: set[str] = set()
    tokens = Counter()
    by_model: dict[str, Counter[str]] = {}
    for line in run.injected.reviews + run.controls.reviews:
        if line["kind"] != "review_ran":
            continue
        model = line["result"]["reviewer_model"]
        for message in line["result"].get("usage", ()):
            if message["message_id"] in seen:
                continue
            seen.add(message["message_id"])
            u = message["usage"]
            c = by_model.setdefault(model, Counter())
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                tokens[k] += u[k]
                c[k] += u[k]
    usd = Fraction(0)
    for model, c in by_model.items():
        price = sheet["usd_per_mtok"].get(model)
        if price is None:
            raise TallyError(f"the price sheet does not price {model}")
        usd += (
            c["input_tokens"] * Fraction(price["input"])
            + c["output_tokens"] * Fraction(price["output"])
            + c["cache_read_input_tokens"] * Fraction(price["cache_read"])
            + c["cache_creation_input_tokens"] * Fraction(price["cache_write_1h"])
        ) / 1_000_000
    every_try = sum(int(r.get("tokens", 0)) for r in run.records.values())
    reviews = len(run.records)
    return {
        "tokens_of_verdict_lines": dict(tokens),
        "tokens_every_try": every_try,
        "reviews": reviews,
        "tokens_per_review": round(every_try / reviews) if reviews else None,
        "usd_list_price_equivalent": round(float(usd), 2),
        "price_sheet": PRICE_SHEET,
        "basis": "subscription: list-price equivalent, cache writes at the one-hour rate; "
        "a lower bound where a review ended with no verdict",
    }


def per_lane(items: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = sorted({p["lane"] for p in items if p["lane"] is not None})
    return {
        str(k): {
            "pairs": sum(p["lane"] == k for p in items),
            "R_rev": sum(p["R_rev"] for p in items if p["lane"] == k),
            "A_rev": sum(p["A_rev"] for p in items if p["lane"] == k),
            "no_verdict": sum(p["rev_open"] + p["twin_open"] for p in items if p["lane"] == k),
        }
        for k in lanes
    }


def two_by_two(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Named against caught (R-PG-01's secondary result 10 in form)."""
    c = Counter()
    for p in items:
        if p[key] is None:
            c["no_error_item"] += 1
        elif p[key] and p["gate_caught"]:
            c["named_and_caught"] += 1
        elif p[key]:
            c["named_not_caught"] += 1
        elif p["gate_caught"]:
            c["caught_not_named"] += 1
        else:
            c["neither"] += 1
    keys = ("named_and_caught", "named_not_caught", "caught_not_named", "neither", "no_error_item")
    return {k: c[k] for k in keys}


def run_figures(run: Run, facts: SetFacts, draws: int, gate: bool) -> dict[str, Any]:
    """Every figure of one run: its reviewers, and its gate where ``gate``."""
    items = per_item(run, facts, run.kind)
    out: dict[str, Any] = {
        "reviewer_kind": run.kind,
        "seed": run.config.get("seed"),
        "lanes": run.config.get("lanes"),
        "account_sha256": run.config.get("account_sha256"),
        "reviewers": reviewer_layer(items, draws),
        "reviewers_per_class": split_by(
            items, "class", CLASSES, lambda x: reviewer_layer(x, draws)
        ),
        "reviewers_per_role": split_by(items, "role", ROLES, lambda x: reviewer_layer(x, draws)),
        "no_verdict_by_role": lists(items),
        "instrument": instrument_figures(run),
        "per_lane": per_lane(items),
        "cost": cost(run),
        "r_pg_01_sense": {
            "approved": sum(p["review"] == "pass" for p in items),
            "caught_any_record": sum(p["gate_caught"] for p in items),
            "named_against_caught": two_by_two(items, "r_pg_01_named"),
        },
        "named_against_caught": two_by_two(items, "named"),
        "per_item": items,
    }
    if gate:
        injected = [run.injected.gate[r["review_id"]] for r in run.rows]
        twins = [run.controls.gate[r["control_id"]] for r in run.rows]
        out["gate"] = gate_layer(items, draws)
        out["gate_per_class"] = split_by(items, "class", CLASSES, lambda x: gate_layer(x, draws))
        out["gate_per_role"] = split_by(items, "role", ROLES, lambda x: gate_layer(x, draws))
        out["gate_checks"] = {"injected": check_counts(injected), "twins": check_counts(twins)}
        out["gate_unchecked_per_class"] = {
            c: sum(p["gate_unchecked_records"] for p in items if p["class"] == c) for c in CLASSES
        }
        out["uncatalogued_names_unchecked"] = unknown_names(injected + twins)
    return out


def pairs_of(items: list[dict[str, Any]], r_key: str, a_key: str) -> dict[str, tuple[int, int]]:
    return {p["artefact"]: (int(bool(p[r_key])), int(bool(p[a_key]))) for p in items}


# ---------------------------------------------------------------- the practice set


def practice_gate_items(corpus_dir: Path, facts: SetFacts) -> list[dict[str, Any]]:
    """The practice set gated at this commit: each injected patch and each twin, once."""
    import tempfile

    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate
    from physgate.gate.runner import PhysicsGate

    corpus = load_corpus(corpus_dir.resolve())
    gate = PhysicsGate()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for a in corpus.artefacts:
            inj = _gate(
                gate, materialise(corpus.base, a.injected, Path(tmp) / f"i-{a.id}"), f"i{a.id}"
            )
            twin = _gate(
                gate, materialise(corpus.base, a.clean, Path(tmp) / f"t-{a.id}"), f"t{a.id}"
            )
            g = gate_item(inj.model_dump(mode="json"), facts.changed[a.id])
            twin_fails = [
                r for r in twin.model_dump(mode="json")["checks"] if r["outcome"] == "fail"
            ]
            out.append(
                {"artefact": a.id, "gate_right_reason": g["right_reason"], "A_gate": not twin_fails}
            )
    return out


# ---------------------------------------------------------------- the whole tally


def tally(
    a_fresh: Path,
    b_fresh: Path,
    a_old: Path,
    fresh_corpus: Path,
    old_corpus: Path,
    practice_run: Path | None = None,
    practice_corpus: Path | None = None,
    any_count: bool = False,
    draws: int = BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    """Every figure of CRITERIA.md §4, §6, §7 and §8 from the three runs."""
    fresh, old = set_facts(fresh_corpus), set_facts(old_corpus)
    runs = {
        "a-fresh": Run.read(a_fresh, any_count),
        "b-fresh": Run.read(b_fresh, any_count),
        "a-old": Run.read(a_old, any_count),
    }
    want = {"a-fresh": "paired", "b-fresh": "generalist", "a-old": "paired"}
    for name, run in runs.items():
        if run.kind != want[name]:
            raise TallyError(f"{name} is a {run.kind} run, not a {want[name]} one")
    af = run_figures(runs["a-fresh"], fresh, draws, gate=True)
    bf = run_figures(runs["b-fresh"], fresh, draws, gate=False)
    ao = run_figures(runs["a-old"], old, draws, gate=True)
    pa = pairs_of(af["per_item"], "R_rev", "A_rev")
    pb = pairs_of(bf["per_item"], "R_rev", "A_rev")
    if pa.keys() != pb.keys():
        raise TallyError("the two fresh arms did not review the same items")
    order = sorted(pa)
    contrast = round(af["reviewers"]["J"] - bf["reviewers"]["J"], 4)
    contrast_ci = contrast_interval([pa[k] for k in order], [pb[k] for k in order], draws)
    gate_fresh = list(pairs_of(af["per_item"], "gate_right_reason", "A_gate").values())
    tokens_a = {p["artefact"]: p["tokens"] for p in af["per_item"]}
    tokens_b = {p["artefact"]: p["tokens"] for p in bf["per_item"]}
    ratios = sorted(tokens_a[k] / tokens_b[k] for k in order if tokens_b.get(k))
    criteria: dict[str, Any] = {
        "P1_gate_accepts_every_old_twin": {
            "A_gate_old": [ao["gate"]["A"], ao["gate"]["n"]],
            "A_gate_old_strict": [ao["gate"]["A_gate_strict"], ao["gate"]["n"]],
            "met": ao["gate"]["A"] == ao["gate"]["n"],
        },
        "P2_gate_right_reason_fresh": {
            "R_gate_fresh": [af["gate"]["R"], af["gate"]["n"]],
            "floor": P2_FLOOR,
            "met": af["gate"]["R"] >= P2_FLOOR,
        },
        "P3_paired_discriminate": {
            "J_paired": af["reviewers"]["J"],
            "interval": af["reviewers"]["J_bootstrap95"],
            "met": af["reviewers"]["J_bootstrap95"][0] > 0,
        },
        "P4_pairing_adds_value": {
            "J_paired_minus_J_generalist": contrast,
            "interval": contrast_ci,
            "met": contrast_ci[0] > 0,
        },
        "P5_not_tailored": None,
    }
    practice: dict[str, Any] | None = None
    if practice_run is not None and practice_corpus is not None:
        pfacts = set_facts(practice_corpus)
        prun = Run.read(practice_run, any_count=True)
        pitems = per_item(prun, pfacts, prun.kind)
        pgate = practice_gate_items(practice_corpus, pfacts)
        layers = {
            "paired": (list(pairs_of(pitems, "R_rev", "A_rev").values()), list(pa.values())),
            "gate": (list(pairs_of(pgate, "gate_right_reason", "A_gate").values()), gate_fresh),
        }
        p5 = {}
        for layer, (before, after) in layers.items():
            drop = round(j_of(before) - j_of(after), 4)
            ci = drop_interval(before, after, draws)
            tailoring = ci[0] > 0
            p5[layer] = {
                "J_practice": round(j_of(before), 4),
                "J_fresh": round(j_of(after), 4),
                "drop": drop,
                "interval": ci,
                "tailoring": tailoring,
                "possible_tailoring": (not tailoring) and drop > POSSIBLE_TAILORING,
            }
        criteria["P5_not_tailored"] = p5
        practice = {
            "reviewers": reviewer_layer(pitems, draws),
            "gate_at_this_commit": figures(pgate, "gate_right_reason", "A_gate", draws),
            "label": "PRACTICE, never a result",
        }
    row_a = sum(p["review"] == "pass" for p in af["per_item"])
    row_c = sum(p["review"] == "pass" and p["gate_caught"] for p in af["per_item"])
    return {
        "primary_fresh": {
            "paired": af["reviewers"],
            "generalist": bf["reviewers"],
            "gate": af["gate"],
            "contrast_paired_minus_generalist": {"J": contrast, "interval": contrast_ci},
            "cost_ratio_paired_to_generalist_per_item": {
                "median": round(ratios[len(ratios) // 2], 4) if ratios else None,
                "of_totals": round(sum(tokens_a.values()) / sum(tokens_b.values()), 4)
                if sum(tokens_b.values())
                else None,
            },
        },
        "criteria": criteria,
        "s7_risk_row_fresh": {
            "A": row_a,
            "C": row_c,
            "thresholds": {"C": ROW_C_THRESHOLD, "A": ROW_A_THRESHOLD},
            "verdict": "reported only",
        },
        "old_set": {
            "paired": ao["reviewers"],
            "gate": ao["gate"],
            "source_check_mismatched_twins": list(old.mismatched_twins),
        },
        "practice": practice,
        "differences": {
            "old_minus_fresh_J": {
                "paired": round(ao["reviewers"]["J"] - af["reviewers"]["J"], 4),
                "gate": round(ao["gate"]["J"] - af["gate"]["J"], 4),
            },
        },
        "fresh_set": {"current_limit_values_citing_a_continuous_rating": fresh.continuous_count},
        "old_set_facts": {"current_limit_values_citing_a_continuous_rating": old.continuous_count},
        "runs": {"a-fresh": af, "b-fresh": bf, "a-old": ao},
        "rules": {
            "bootstrap": {"draws": draws, "seed": BOOTSTRAP_SEED},
            "error_items": ERROR_ITEMS,
            "generalist_items": GENERALIST_ITEMS,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("--a-fresh", "--b-fresh", "--a-old", "--fresh-corpus", "--old-corpus"):
        parser.add_argument(name, required=True, type=Path)
    parser.add_argument("--practice-run", type=Path)
    parser.add_argument("--practice-corpus", type=Path)
    parser.add_argument("--any-count", action="store_true", help="a test corpus only")
    parser.add_argument("--draws", type=int, default=BOOTSTRAP_DRAWS)
    args = parser.parse_args(argv)
    if (args.practice_run is None) != (args.practice_corpus is None):
        parser.error("--practice-run and --practice-corpus go together")
    try:
        out = tally(
            args.a_fresh.resolve(),
            args.b_fresh.resolve(),
            args.a_old.resolve(),
            args.fresh_corpus,
            args.old_corpus,
            args.practice_run,
            args.practice_corpus,
            args.any_count,
            args.draws,
        )
    except TallyError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(out, indent=1, sort_keys=True, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
