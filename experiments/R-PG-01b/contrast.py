"""R-PG-01b, CRITERIA.md §5 (with R6 and §12's tally stops): every run's figures and the contrasts.

Usage, in the run checkout, after every valid run has ended and never before::

    contrast.py --run I1=<run dir>,<review root> --run F1=<run dir>,<review root>
                [--run I2=... --run F2=...] --out <file>

Each ``--run`` names one valid run by arm and round. With both rounds the analysis is R = 2; with
one round only (§12), R = 1, labelled, and Newcombe's interval replaces the bootstrap.

**Per run** (§5.1), through R-PG-01's frozen scripts at their pinned blobs, unchanged:
``tally_rows.py``'s own ``tally`` gives A, C, the kill reading, results 1 to 10 and every
artefact's row (approved, caught, named, the twin's outcome); nothing here re-implements a rule.
The figures are held to ``tally_rows.py``'s and ``read_catches.py``'s printed totals, and a
difference stops the tally (§12). Every review line's ``rubric_sha256`` is held to its role's
pinned digest; a difference stops the tally (§12).

**R6.** The gate's records are compared across every run (each subtask's ``gate_ran`` result,
both logs), and ``regate_r6.py``'s second pass is run on each into a fresh directory; its count
of differing records must be 0. A difference is a deviation: C is not computed and the primary
contrast is not taken (§12). Results 2, 3, 4 and 6 must be identical in every run, and are
printed once.

**The contrasts** (§5.2 to §5.4), each paired per (artefact, round), arm F minus arm I:

- ΔC = C̄(F) − C̄(I) = Σᵢ g(i)·d(i); the share −ΔC / C̄(I), printed when C̄(I) ≥ 1 and the floor
  of §7 does not hold;
- ΔA; ΔT; Δnamed with the twin condition and without it; ΔCNN, caught not named; ΔC among the
  rejected (result 5: a review that came to ``fail``); per class and per role ΔA and ΔC as counts;
  ``blocked`` and ``review_unavailable`` per arm and role with causes, and every review session's
  turns and wall clock (median, maximum, and how many ended at the 80-turn or 4,500 s bound);
  the sensitivity reading without any pair holding a ``blocked`` or ``review_unavailable``
  review; the noise floor (counts and Cohen's κ, within each arm across rounds and between the
  arms within each round, on the injected approval and on the twin's).
- **Intervals:** a 95 % percentile bootstrap over the 40 artefacts, 10,000 draws drawn once with
  ``random.Random(13)`` and used for every statistic (a resampled artefact carries all its
  reviews, twins' included); beside it, for each round alone, Newcombe's (1998) method 10
  interval for a difference of paired proportions, scaled to counts. Each arm's Ā and C̄ get
  the same bootstrap, or a Wilson interval with one round.
- **Test:** the exact two-sided McNemar test on the discordant (artefact, round) pairs, pooled
  over rounds; for ΔC and ΔCNN only the gate-caught artefacts' pairs.
- **"Shown"**: the interval excludes 0 and the exact p is below 0.05.

**Readings** (§5.1, §7): each arm's kill reading on its means (C̄ < 10 or Ā < 4) and each
round's; whether arm F's and arm I's rounds agree; the floor (C̄(I) < 3 and C̄(F) < 3); D2's
sentence. D1's sentence needs R-PG-01's reading and is the last step's (``compare_r_pg_01.py``).

It writes the full output to ``--out`` (never over an existing file) and prints its sha256 and
the counts of runs and rows only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

R_PG_01 = C.REPO / "experiments" / "R-PG-01"
Z = 1.959963984540054  # the 97.5th percentile of the standard normal
TURN_BOUND = 80
WALL_BOUND_S = 4500.0


class TallyStop(Exception):
    """§12: the tally stops (a total differs, a rubric digest differs, an input is missing)."""


# ---- the frozen scripts, at their pins ----


def frozen(name: str) -> Path:
    """R-PG-01's script ``name``, held to its pinned blob (§2.2)."""
    path = R_PG_01 / name
    blob = subprocess.run(
        ["git", "hash-object", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()
    if blob != C.R_PG_01_SCRIPTS[name]:
        raise TallyStop(f"{name} is not at its pinned blob")
    return path


def tally_module() -> ModuleType:
    """``tally_rows.py`` as a module, at its pin: its ``tally`` is the rules, used as they are."""
    spec = importlib.util.spec_from_file_location("tally_rows", frozen("tally_rows.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- one run ----


def run_figures(
    tally: ModuleType, run: Path, corpus: Path | None, any_count: bool = False
) -> dict[str, Any]:
    """One run's figures by ``tally_rows``'s ``tally``, held to its printed totals."""
    out = tally.tally(run, corpus, any_count)
    argv = [sys.executable, "-I", str(frozen("tally_rows.py")), str(run)]
    if corpus is not None:
        argv += ["--corpus", str(corpus)]
    if any_count:
        argv.append("--any-count")
    printed = subprocess.run(argv, capture_output=True, text=True, check=False)
    if printed.returncode != 0:
        raise TallyStop(f"tally_rows.py refused {run}: {printed.stdout.strip()[-300:]}")
    shown = json.loads(printed.stdout)
    for key in ("A_approved", "C_caught_among_approved", "kill_criterion_fires", "rows"):
        if shown[key] != out[key]:
            raise TallyStop(f"{run}: {key} differs from tally_rows.py's printed total")
    per = out["per_artefact"]
    if (
        sum(p["approved"] for p in per) != shown["A_approved"]
        or sum(p["approved"] and p["caught"] for p in per) != shown["C_caught_among_approved"]
    ):
        raise TallyStop(f"{run}: the rows do not add up to tally_rows.py's totals")
    if sum(p["named"] is True for p in per) != shown["s6_10_named_against_caught"]["named"]:
        raise TallyStop(f"{run}: named differs from tally_rows.py's printed total")
    return out


def catches(run: Path) -> dict[str, Any]:
    """``read_catches.py`` on one run, unchanged: it must hold (§12)."""
    done = subprocess.run(
        [sys.executable, "-I", str(frozen("read_catches.py")), str(run)],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = done.stdout.strip().splitlines()
    last = json.loads(lines[-1]) if lines else {}
    if done.returncode != 0 or not last.get("holds"):
        raise TallyStop(f"{run}: read_catches.py does not hold: {done.stdout.strip()[-300:]}")
    return {"rows": lines[:-1], "holds": True, **{k: last[k] for k in last if k != "holds"}}


def rubric_lines(run: Path) -> tuple[int, int]:
    """Every review line and how many carry another digest than their role's pin (§5.1)."""
    bad = seen = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        lines = C.read_jsonl(log)
        role = {
            x["subtask_id"]: x["assigned_role"] for x in lines if x.get("kind") == "subtask_planned"
        }
        for x in lines:
            if x.get("kind") == "review_ran":
                seen += 1
                digest = (x.get("result") or {}).get("rubric_sha256")
                bad += digest != C.RUBRIC_SHA256.get(role.get(x["subtask_id"], ""))
    return seen, bad


def gate_records(run: Path) -> dict[str, str]:
    """Each subtask's gate result, canonical, from both logs."""
    out = {}
    for side, log in (("i", run / "events.jsonl"), ("t", run / "controls" / "events.jsonl")):
        for x in C.read_jsonl(log):
            if x.get("kind") == "gate_ran":
                out[f"{side}:{x['subtask_id']}"] = json.dumps(x["result"], sort_keys=True)
    return out


def regate(run: Path, corpus: Path) -> int:
    """``regate_r6.py``'s count of differing records, its second pass in a fresh directory."""
    with tempfile.TemporaryDirectory(prefix="rpb-regate-") as tmp:
        done = subprocess.run(
            [
                sys.executable, "-I", str(frozen("regate_r6.py")), str(corpus), str(run),
                str(C.SEED), str(Path(tmp) / "again"),
            ],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
    if done.returncode != 0:
        raise TallyStop(f"regate_r6.py failed on {run}: {done.stderr.strip()[-300:]}")
    return int(json.loads(done.stdout.strip().splitlines()[-1])["differ"])


def sessions(run: Path, root: Path | None) -> list[dict[str, Any]]:
    """Every review session of a run: its turns, wall clock and whether it hit a bound."""
    if root is None:
        return []
    out = []
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        for x in C.read_jsonl(log):
            if x.get("kind") not in ("review_ran", "review_unavailable"):
                continue
            sid = (
                (x.get("result") or {}).get("session_id")
                if x["kind"] == "review_ran"
                else x.get("session_id")
            )
            d = root / str(sid) / "session"
            result: dict[str, Any] = {}
            stream = d / "stdout.jsonl"
            if sid and stream.is_file():
                for line in stream.read_text(errors="replace").splitlines():
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(e, dict) and e.get("type") == "result":
                        result = e
            ended = (
                json.loads((d / "ended.json").read_text()) if (d / "ended.json").is_file() else {}
            )
            turns = result.get("num_turns")
            out.append(
                {
                    "turns": turns,
                    "wall_s": (result.get("duration_ms") or 0) / 1000 if result else None,
                    "at_turn_bound": isinstance(turns, int) and turns >= TURN_BOUND,
                    "at_wall_bound": bool(ended.get("timed_out")),
                    "stream": bool(result),
                }
            )
    return out


def gate_parts(figures: dict[str, Any]) -> dict[str, Any]:
    """Results 2, 3, 4 and 6 as they belong to the gate and the corpus alone (§5.1).

    ``tally_rows.py`` puts the reviewers' A and C beside two of them (result 2's share among C,
    result 4's A and C per domain pair); those parts are a run's own and are left out here.
    """
    s2 = {k: v for k, v in figures["s6_2_expected_check"].items() if k not in ("among_C", "C")}
    edges = figures["s6_4_propagation_edges_by_domain_pair"]
    s4 = None if edges is None else {k: v["artefacts"] for k, v in edges.items()}
    return {
        "s6_2_expected_check": s2,
        "s6_3_unchecked": figures["s6_3_unchecked"],
        "s6_4_propagation_edges_by_domain_pair": s4,
        "s6_6_gate_events_and_records": figures["s6_6_gate_events_and_records"],
    }


# ---- statistics ----


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q`` quantile of ``values``, linearly interpolated between order statistics."""
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def draws(n: int, count: int = C.BOOT_DRAWS, seed: int = C.BOOT_SEED) -> list[list[int]]:
    """The bootstrap's resamples of ``n`` artefacts, drawn once with ``random.Random(seed)``."""
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(count)]


def boot(stat: Callable[[list[int]], float | None], resamples: list[list[int]]) -> dict[str, Any]:
    """A 95 % percentile interval of ``stat`` over the resamples (undefined draws counted apart)."""
    values = [v for idx in resamples if (v := stat(idx)) is not None]
    if not values:
        return {"low": None, "high": None, "undefined_draws": len(resamples)}
    return {
        "low": percentile(values, 0.025),
        "high": percentile(values, 0.975),
        "undefined_draws": len(resamples) - len(values),
    }


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """Wilson's score interval for ``k`` of ``n``."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_paired(pairs: Sequence[tuple[int, int]]) -> dict[str, Any]:
    """Newcombe's (1998) method 10 for a difference of paired proportions, first minus second.

    ``pairs`` holds (first, second) per unit, each 0 or 1. Scaled to counts (times the units).
    """
    n = len(pairs)
    a = sum(1 for x, y in pairs if x and y)
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if not x and y)
    d = n - a - b - c
    if n == 0:
        return {"low": None, "high": None, "difference": None}
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n)
    l2, u2 = wilson(a + c, n)
    denominator = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(denominator) if denominator > 0 else 0.0
    delta = math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    eps = math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    diff = p1 - p2
    return {"difference": diff * n, "low": (diff - delta) * n, "high": (diff + eps) * n}


def mcnemar_exact(b: int, c: int) -> float:
    """The exact two-sided McNemar p: twice the smaller binomial tail at p = 1/2, at most 1."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def kappa(x: Sequence[int], y: Sequence[int]) -> float | None:
    """Cohen's κ of two binary ratings of the same units."""
    n = len(x)
    if n == 0:
        return None
    po = sum(a == b for a, b in zip(x, y, strict=True)) / n
    px, py = sum(x) / n, sum(y) / n
    pe = px * py + (1 - px) * (1 - py)
    return None if pe == 1 else (po - pe) / (1 - pe)


# ---- the contrasts ----


class Design:
    """The per-artefact indicators of every run, by arm and round, in one artefact order."""

    def __init__(self, runs: dict[str, dict[str, Any]], rounds: list[int]) -> None:
        self.rounds = rounds
        self.R = len(rounds)
        first = runs[f"I{rounds[0]}"]["per_artefact"]
        self.artefacts = [p["artefact"] for p in first]
        self.n = len(self.artefacts)
        self.row: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
        for key, figures in runs.items():
            arm, r = key[0], int(key[1:])
            rows = {p["artefact"]: p for p in figures["per_artefact"]}
            if sorted(rows) != sorted(self.artefacts):
                raise TallyStop(f"run {key} does not hold the same artefacts")
            self.row[(arm, r)] = rows
        self.g = [int(first_row["caught"]) for first_row in first]
        for key in runs:
            caught = [int(self.row[(key[0], int(key[1:]))][a]["caught"]) for a in self.artefacts]
            if caught != self.g:
                raise TallyStop("the gate's catches differ between runs (R6)")

    def ind(self, name: str, arm: str, r: int, i: int) -> int:
        """One indicator for artefact ``i`` in (arm, round)."""
        p = self.row[(arm, r)][self.artefacts[i]]
        g = self.g[i]
        if name == "A":
            return int(p["approved"])
        if name == "C":
            return int(p["approved"] and g)
        if name == "T":
            return int(p["twin_review"] == "pass")
        if name == "named":
            return int(p["named"] is True)
        if name == "cited":
            return int(p["cited_at_all"] is True)
        if name == "CNN":
            return int(bool(g) and p["named"] is False)
        if name == "C_rejected":
            return int(bool(g) and p["review"] == "fail")
        if name == "unjudged":
            # The injected artefact's review in this arm: §5.3 item 8's pair is the two arms'.
            return int(p["review"] in ("blocked", "review_unavailable", "missing"))
        raise ValueError(name)

    def total(
        self, name: str, arm: str, idx: Sequence[int], keep: Callable[[int], bool] | None = None
    ) -> float:
        """The mean over rounds of the summed indicator over ``idx``."""
        return (
            sum(
                self.ind(name, arm, r, i)
                for r in self.rounds
                for i in idx
                if keep is None or keep(i)
            )
            / self.R
        )

    def delta(
        self, name: str, idx: Sequence[int], keep: Callable[[int], bool] | None = None
    ) -> float:
        """F minus I, mean over rounds, summed over ``idx``."""
        return self.total(name, "F", idx, keep) - self.total(name, "I", idx, keep)

    def pairs(
        self, name: str, caught_only: bool, sensitivity: bool = False
    ) -> list[tuple[int, int]]:
        """Every (artefact, round) pair's (F, I) indicators, pooled over rounds."""
        out = []
        for r in self.rounds:
            for i in range(self.n):
                if caught_only and not self.g[i]:
                    continue
                if sensitivity and (
                    self.ind("unjudged", "F", r, i) or self.ind("unjudged", "I", r, i)
                ):
                    continue
                out.append((self.ind(name, "F", r, i), self.ind(name, "I", r, i)))
        return out


def contrast(
    d: Design,
    name: str,
    resamples: list[list[int]] | None,
    caught_only: bool = False,
    sensitivity: bool = False,
) -> dict[str, Any]:
    """One paired contrast: its value, intervals, exact test and whether it is shown."""
    every = list(range(d.n))

    def keep(r: int, i: int) -> bool:
        return not (sensitivity and (d.ind("unjudged", "F", r, i) or d.ind("unjudged", "I", r, i)))

    def value(idx: Sequence[int]) -> float:
        return (
            sum(
                d.ind(name, "F", r, i) - d.ind(name, "I", r, i)
                for r in d.rounds
                for i in idx
                if keep(r, i)
            )
            / d.R
        )

    pooled = d.pairs(name, caught_only, sensitivity)
    b = sum(1 for f, i in pooled if f and not i)
    c = sum(1 for f, i in pooled if not f and i)
    p = mcnemar_exact(b, c)
    per_round = {}
    for r in d.rounds:
        pr = [(d.ind(name, "F", r, i), d.ind(name, "I", r, i)) for i in every if keep(r, i)]
        per_round[str(r)] = newcombe_paired(pr)
    found: dict[str, Any] = {
        "value": value(every),
        "discordant_F_not_I": b,
        "discordant_I_not_F": c,
        "pairs_tested": len(pooled),
        "exact_p": p,
        "newcombe_per_round": per_round,
    }
    if resamples is not None and d.R > 1:
        found["bootstrap"] = boot(value, resamples)
        interval = found["bootstrap"]
    else:
        interval = per_round[str(d.rounds[0])]
        found["interval_is"] = "newcombe (one round)"
    low, high = interval.get("low"), interval.get("high")
    excludes = low is not None and high is not None and (low > 0 or high < 0)
    found["shown"] = bool(excludes and p < 0.05)
    found["largest_effects_not_excluded"] = None if found["shown"] else [low, high]
    return found


def level(d: Design, name: str, arm: str, resamples: list[list[int]] | None) -> dict[str, Any]:
    """An arm's mean level (Ā or C̄) with its bootstrap interval, or Wilson's with one round."""
    every = list(range(d.n))
    value = d.total(name, arm, every)
    if resamples is not None and d.R > 1:
        return {"value": value, "bootstrap": boot(lambda idx: d.total(name, arm, idx), resamples)}
    lo, hi = wilson(round(value), d.n)
    return {"value": value, "wilson": {"low": lo * d.n, "high": hi * d.n}}


def kill(a: float, c: float) -> bool:
    """R-PG-01 §5's rule: C < 10 or A < 4."""
    return c < 10 or a < 4


def noise_floor(d: Design) -> dict[str, Any]:
    """§5.3 item 9: within each arm across rounds, and between the arms within each round."""
    out: dict[str, Any] = {}
    for name in ("A", "T"):
        part: dict[str, Any] = {}
        if d.R > 1:
            r1, r2 = d.rounds
            for arm in C.ARMS:
                x = [d.ind(name, arm, r1, i) for i in range(d.n)]
                y = [d.ind(name, arm, r2, i) for i in range(d.n)]
                part[f"arm {arm}, round {r1} against {r2}"] = {
                    "disagree": sum(a != b for a, b in zip(x, y, strict=True)),
                    "kappa": kappa(x, y),
                }
        for r in d.rounds:
            x = [d.ind(name, "F", r, i) for i in range(d.n)]
            y = [d.ind(name, "I", r, i) for i in range(d.n)]
            part[f"round {r}, arm F against arm I"] = {
                "disagree": sum(a != b for a, b in zip(x, y, strict=True)),
                "kappa": kappa(x, y),
            }
        out["injected_approval" if name == "A" else "twin_approval"] = part
    return out


def by_group(d: Design, key: str, values: Sequence[str]) -> dict[str, Any]:
    """Per class or per role: ΔA and ΔC as counts, with no interval."""
    out = {}
    for v in values:
        idx = [i for i in range(d.n) if d.row[("I", d.rounds[0])][d.artefacts[i]][key] == v]
        out[v] = {
            "artefacts": len(idx),
            "delta_A": d.delta("A", idx),
            "delta_C": d.delta("C", idx),
        }
    return out


def unjudged(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """``blocked`` and ``review_unavailable`` per run and role, each with its cause (result 9)."""
    return {key: figures["s6_9_not_judged_per_role"] for key, figures in runs.items()}


def analyse(
    specs: dict[str, tuple[Path, Path | None]],
    corpora: dict[str, Path | None],
    any_count: bool = False,
    resample_count: int = C.BOOT_DRAWS,
) -> dict[str, Any]:
    """The whole of §5 over the named runs."""
    tally = tally_module()
    rounds = sorted({int(k[1:]) for k in specs})
    if sorted(specs) != sorted(f"{a}{r}" for a in C.ARMS for r in rounds):
        raise TallyStop("each round needs both arms' runs")
    runs: dict[str, dict[str, Any]] = {}
    checks: dict[str, Any] = {}
    gates: dict[str, dict[str, str]] = {}
    for key, (run, root) in sorted(specs.items()):
        corpus = corpora[key[0]]
        seen, bad = rubric_lines(run)
        if bad:
            raise TallyStop(f"run {key}: {bad} review lines carry another rubric digest (§12)")
        runs[key] = run_figures(tally, run, corpus, any_count)
        checks[key] = {
            "rubric_lines": seen,
            "read_catches": catches(run) if not any_count else None,
            "regate_differ": regate(run, corpus) if corpus is not None else None,
            "sessions": sessions(run, root),
        }
        gates[key] = gate_records(run)
    first = next(iter(gates.values()))
    r6_cross = all(g == first for g in gates.values())
    regate_differ = sum(c["regate_differ"] or 0 for c in checks.values())
    gate_only = gate_parts(runs[next(iter(runs))])
    same_gate_only = all(gate_parts(figures) == gate_only for figures in runs.values())
    r6_holds = r6_cross and regate_differ == 0 and same_gate_only
    d = Design(runs, rounds)
    resamples = draws(d.n, resample_count) if d.R > 1 else None
    every = list(range(d.n))
    per_run = {
        key: {
            "A": figures["A_approved"],
            "C": figures["C_caught_among_approved"],
            "kill": figures["kill_criterion_fires"],
            "secondary": {
                k: v for k, v in figures.items() if k.startswith("s6_") and k not in gate_only
            },
            "listed_not_approved_without_a_verdict": figures[
                "listed_not_approved_without_a_verdict"
            ],
            "per_artefact": figures["per_artefact"],
        }
        for key, figures in runs.items()
    }
    arms = {}
    for arm in C.ARMS:
        a = level(d, "A", arm, resamples)
        c = level(d, "C", arm, resamples)
        rounds_kill = {str(r): per_run[f"{arm}{r}"]["kill"] for r in rounds}
        arms[arm] = {
            "A_mean": a,
            "C_mean": c,
            "kill_on_means": kill(a["value"], c["value"]),
            "kill_per_round": rounds_kill,
            "rounds_agree_on_kill": len(set(rounds_kill.values())) == 1,
        }
    c_i, c_f = arms["I"]["C_mean"]["value"], arms["F"]["C_mean"]["value"]
    floor = c_i < 3 and c_f < 3
    found: dict[str, Any] = {
        "R": d.R,
        "rounds": rounds,
        "one_round_form": d.R == 1,
        "artefacts": d.n,
        "R6": {
            "gate_records_identical_across_runs": r6_cross,
            "regate_differ_total": regate_differ,
            "results_2_3_4_6_identical": same_gate_only,
            "holds": r6_holds,
        },
        "per_run": per_run,
        "results_2_3_4_6_printed_once": gate_only,
        "checks": checks,
        "arms": arms,
        "floor": floor,
    }
    if not r6_holds:
        found["primary"] = "not taken: the gate's records differ (§12)"
        return found
    primary = contrast(d, "C", resamples, caught_only=True)
    if c_i >= 1 and not floor:

        def share(idx: Sequence[int]) -> float | None:
            ci = d.total("C", "I", idx)
            return None if ci == 0 else -(d.total("C", "F", idx) - ci) / ci

        primary["share"] = {
            "value": share(every),
            "bootstrap": boot(share, resamples) if resamples is not None else None,
        }
    found["primary_delta_C"] = primary
    found["secondary"] = {
        "delta_A": contrast(d, "A", resamples),
        "delta_T": contrast(d, "T", resamples),
        "delta_named": contrast(d, "named", resamples),
        "delta_cited_without_the_twin_condition": contrast(d, "cited", resamples),
        "delta_CNN": contrast(d, "CNN", resamples, caught_only=True),
        "delta_C_among_rejected": contrast(d, "C_rejected", resamples),
        "per_class": by_group(d, "class", tally.CLASSES),
        "per_role": by_group(d, "role", tally.ROLES),
        "blocked_and_unavailable": unjudged(runs),
        "sessions": {key: _session_summary(c["sessions"]) for key, c in checks.items()},
        "sensitivity": {
            "delta_C": contrast(d, "C", resamples, caught_only=True, sensitivity=True),
            "delta_A": contrast(d, "A", resamples, sensitivity=True),
        },
        "noise_floor": noise_floor(d),
    }
    if floor:
        d2 = "not measurable at this approval rate"
    elif primary["shown"]:
        d2 = "the incomplete sheet changed the gate's added catches by ΔC (interval)"
    else:
        d2 = "no change was shown at this size; the interval excludes changes beyond its bounds"
    found["D2_sentence"] = d2
    found["D1"] = {
        "arm_F_kill_on_means": arms["F"]["kill_on_means"],
        "arm_F_rounds_agree": arms["F"]["rounds_agree_on_kill"],
        "label": None if arms["F"]["rounds_agree_on_kill"] else "not stable at this size",
        "arm_I_rounds_agree": arms["I"]["rounds_agree_on_kill"],
        "sentence": "the last step's (compare_r_pg_01.py): it reads R-PG-01's reading",
    }
    return found


def _session_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [r["turns"] for r in rows if isinstance(r["turns"], int)]
    wall = [r["wall_s"] for r in rows if isinstance(r["wall_s"], (int, float))]
    return {
        "sessions": len(rows),
        "without_a_stream": sum(not r["stream"] for r in rows),
        "turns_median": statistics.median(turns) if turns else None,
        "turns_max": max(turns) if turns else None,
        "wall_s_median": statistics.median(wall) if wall else None,
        "wall_s_max": max(wall) if wall else None,
        "at_turn_bound": sum(r["at_turn_bound"] for r in rows),
        "at_wall_bound": sum(r["at_wall_bound"] for r in rows),
    }


def main(argv: list[str] | None = None) -> int:
    """Write §5's output; print its sha256 and counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--run", action="append", required=True, help="I1=<run dir>,<review root>")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--any-count", action="store_true", help="invented fixtures only")
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; an output is never written over")
    specs: dict[str, tuple[Path, Path | None]] = {}
    for spec in args.run:
        key, _, paths = spec.partition("=")
        run, _, root = paths.partition(",")
        specs[key] = (Path(run).resolve(), Path(root).resolve() if root else None)
    corpora: dict[str, Path | None] = {
        "I": C.REPO / C.ARM_I_CORPUS,
        "F": C.REPO / C.ARM_F_CORPUS,
    }
    if args.any_count:
        corpora = {"I": None, "F": None}
    try:
        found = analyse(specs, corpora, args.any_count)
    except TallyStop as exc:
        print(json.dumps({"tally_stopped": str(exc)}))
        return 1
    text = json.dumps(found, indent=1, sort_keys=True) + "\n"
    args.out.write_text(text)
    print(
        json.dumps(
            {"out": str(args.out), "sha256": C.sha256_bytes(text.encode()), "runs": len(specs)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
