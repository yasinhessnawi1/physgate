"""R-PG-03: every block's runs to §4's R, A and J per arm, Q1-Q4, §6.4, the class rule and §8's row.

Usage, after the last block has ended and passed its stream check, and never before (§5 R8)::

    python -I tally3.py --records <~/runs/rpg03> --sets <the corpora's directory>
        --practice round-1=<dir> --practice a-fresh=<dir> --practice repeat-K=<dir>
        [--reading <reading.json>] [--root <arm>:<block>=<scratch> ...] [--draws N] --out <file>

Read-only over the runs and the sets. It writes one JSON document to ``--out`` (never over a file)
and prints its sha256 and counts only. Every rule is closed and mechanical: no model reads a
review.

**R-PG-02's frozen tally, unedited.** ``tally.py`` is imported as it stands (``set_facts``,
``Run``, ``per_item``, ``naming``, ``names_pair``, ``wilson``, ``j_of``, ``contrast_interval``,
``drop_interval``, and the functions they are built from). The frozen ``per_item`` refuses the
class ``standard`` (``TallyError``), so ``fresh-v2-s`` is scored by a path of its own, built from
the module's other functions (``outcome``, ``cited``, ``naming``, ``names_pair``); the module is
never patched.

**The rules (§4.1).** An injected item counts in R when its review is a ``fail``, it cites
(``unmet`` or ``confirmed``, or as its failing item) an item of the cell, and its twin's review
does not cite that item:

- **common** (primary): the role's error cell for the class (R-PG-02's table, paired column) with
  the role's Section 1 line (A7, EA-9, AC-9, MA-10); for B the Section 1 line alone, so B's
  common R is its R-PG-02 R; for the ``standard`` class, the role's Section 2 items, all of them,
  with the Section 1 line;
- **strict** (secondary): R-PG-02's paired rule, the error cell alone, for A1 and A2; B unchanged;
- **locating** (descriptive): the review is a ``fail``; some rejecting line's evidence holds a
  changed node's id as a whole word, or a changed quantity's name with its node (R-PG-02's
  ``names_pair``); and no rejecting line of the twin's review does. Rejecting lines are R-LAW-01
  §2.2's (every ``unmet`` or ``confirmed`` entry, and the failing item's); changed nodes are
  R-PG-02's (``set_facts``), changed quantities R-LAW-01 §2.3's changed pairs.

A twin counts in A when its review is a ``pass``. ``blocked`` and ``review_unavailable`` count
against the arm in both directions (§4.4), with the figures among verdicts and the ranges beside.
J = R + A - 1.

**The intervals.** Wilson 95 % for R and A; J and every contrast by a bootstrap over pairs, 10,000
draws at seed 13, a fresh stream for each interval (the frozen ``boot``), **stratified** for the
primary and its contrasts: in each draw X's 40 pairs, then Y's, then Z's are each resampled within
themselves, every stratum in line order (its two corpora in §7's order, then item id), and one draw
serves all three arms. Q4 and the readings beside it are unstratified (the frozen
``drop_interval``, and its order for the joint readings: the tuning set's pairs first, then
fresh-v2's).

**What it checks first, and refuses on.** Every block has a valid attempt that ended and passed
its stream check, or (``s``, ``p1``, ``p2`` alone) is recorded as not run with its cause (R8). Each
run's rows are its block's items; its seed, kind, lanes, account digest and corpus manifest are
its block's and arm's; every review line's rubric digest is its arm's for its role (§3.1), and,
where the review roots are named, every packet's knowledge digests are the pinned trees' for its
arm and role. The practice runs are held to R-LAW-01's recorded digests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def _load(name: str, path: Path) -> ModuleType:
    """A frozen script of another experiment, unedited, under a name of its own."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path.name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass reads its module while the module loads
    spec.loader.exec_module(module)
    return module


#: R-PG-02's frozen tally, unedited.
T = _load("rpg02_tally", common.REPO / "experiments" / "R-PG-02" / "tally.py")
#: R-LAW-01's frozen extractor, unedited: the rejecting-line rule and the changed pairs.
LX = _load("rlaw01_extract", common.REPO / "experiments" / "R-LAW-01" / "law_extract.py")

TallyError = T.TallyError
CLASSES = T.CLASSES
STANDARD = "standard"
SECTION1 = T.GENERALIST_ITEMS
Q3_MARGIN = -0.15
POSSIBLE_TAILORING = T.POSSIBLE_TAILORING
#: Q1's guard on R: at most this many pairs (5 % of 120) below A1, under either rule.
R_GUARD = 6
#: The class rule (§8, §14 item 9a).
CLASS_CATCH_D = 3
CLASS_ACCEPT_GAP = 2
#: §6.2: run-to-run noise measured in practice, at 40 pairs, and its churn.
NOISE_BAND_40 = 0.175
PRACTICE_CHURN = {"twins_changed": [8, 40], "injected_strict": [7, 40], "injected_common": [3, 40]}
#: The kept round's practice figure on the tuning set, J under the common rule (§6.3).
KEPT_ROUND_J = 0.775
PRACTICE_RUNS = ("round-1", "a-fresh", "repeat-K")


class RefusedError(Exception):
    """The records, runs or sets are not ones this script can read faithfully."""


# ---------------------------------------------------------------- the cells


@dataclass(frozen=True)
class Cells:
    """Each role's Section 2 items, from the rubric, for the ``standard`` class's common cell."""

    section2: dict[str, frozenset[str]]

    @classmethod
    def at(cls, repo: Path) -> Cells:
        """Section 2's ids of each role's fixed and K's rubric, which must be the same ids.

        Raises:
            RefusedError: the two rubrics of a role hold different Section 2 ids.
        """
        from physgate.reviewers.rubric import parse_rubric

        found = {}
        for role in common.ROLES:
            sets = []
            for commit in (common.FIX_COMMIT, common.K_COMMIT):
                text = (
                    common.git(repo, "show", f"{commit}:knowledge/reviewers/{role}/rubric.md")
                    + "\n"
                )
                items = parse_rubric(text)
                sets.append(frozenset(i.id for i in items if i.section == "domain_standards"))
            if sets[0] != sets[1]:
                raise RefusedError(
                    f"the {role} rubrics' Section 2 ids differ between K and the fix"
                )
            found[role] = sets[0]
        return cls(found)


def common_cell(kind: str, role: str, error_class: str, cells: Cells | None) -> tuple[str, ...]:
    """§4.1's common cell: the error cell with the Section 1 line; B's is the line alone."""
    line: tuple[str, ...] = tuple(SECTION1[role])
    if kind == "generalist":
        return line
    if error_class == STANDARD:
        if cells is None:
            raise RefusedError("the standard class's cell needs the rubrics' Section 2 items")
        return tuple(sorted(cells.section2[role])) + line
    return tuple(str(i) for i in T.ERROR_ITEMS[role][error_class]) + line


def strict_cell(kind: str, role: str, error_class: str) -> tuple[str, ...]:
    """R-PG-02's paired rule: the error cell alone; B's is unchanged (its Section 1 line)."""
    if kind == "generalist":
        return tuple(str(i) for i in SECTION1[role])
    return tuple(str(i) for i in T.ERROR_ITEMS[role][error_class])


# ---------------------------------------------------------------- the locating rule


def rejecting_texts(line: dict[str, Any] | None) -> list[str]:
    """The evidence of every rejecting line of a review (R-LAW-01 §2.2's entries)."""
    if line is None or line.get("kind") != "review_ran":
        return []
    return [str(it.get("evidence") or "") for _, it in LX.rejecting_entries(line["result"])]


def locates(text: str, nodes: Iterable[str], pairs: Iterable[tuple[str, str]]) -> bool:
    """A changed node's id as a whole word, or a changed quantity's name with its node."""
    low = text.casefold()
    for node in nodes:
        if re.search(rf"(?<![\w.]){re.escape(node.casefold())}(?![\w])", low):
            return True
    return any(T.names_pair(text, n, q) for n, q in pairs)


def set_data(corpus_dir: Path) -> Any:  # noqa: ANN401 - R-LAW-01's SetData
    """A corpus as R-LAW-01's ``SetData``, for its changed pairs (§2.3 there)."""
    base = json.loads((corpus_dir / "base.json").read_text())["nodes"]
    arts = {}
    for path in sorted((corpus_dir / "artefacts").glob("*.json")):
        a = json.loads(path.read_text())
        arts[a["id"]] = a
    return LX.SetData(corpus_dir.name, 0, base, arts, b"")


# ---------------------------------------------------------------- one run, item by item


@dataclass
class Block:
    """One block's three runs and its set's facts."""

    name: str
    corpus: Path
    runs: dict[str, Any]
    facts: Any
    law: Any
    scratch: dict[str, Path | None] = field(default_factory=dict)


def _consistent(run: Any, aid: str, rid: str, cid: str) -> None:
    """The log and the row agree, as the frozen ``per_item`` holds them (its own checks)."""
    if rid not in run.injected.role or rid not in run.injected.gate:
        raise TallyError(f"{aid}: no planned line or gate line in the injected log")
    if cid not in run.controls.gate:
        raise TallyError(f"{aid}: no gate line for its twin in the controls log")


def standard_items(run: Any, facts: Any, kind: str) -> list[dict[str, Any]]:
    """The ``standard`` class's items, by a path of their own built from the frozen functions.

    ``per_item`` refuses this class; this gives the same fields it gives, but for the cell rule,
    which :func:`score` applies, and the gate fields, which the class does not need.
    """
    out = []
    for row in run.rows:
        aid, rid, cid = row["artefact"], row["review_id"], row["control_id"]
        _consistent(run, aid, rid, cid)
        if row["error_class"] != STANDARD:
            raise TallyError(f"{aid}: a class other than standard in the standard block")
        role = run.injected.role[rid]
        line, twin_line = run.injected.review.get(rid), run.controls.review.get(cid)
        verdict, cause = T.outcome(line)
        twin_verdict, twin_cause = T.outcome(twin_line)
        if verdict != row["reviewer_verdict"]:
            raise TallyError(f"{aid}: the log's review outcome disagrees with the row")
        if row.get("control_reviewer_verdict") not in (None, twin_verdict):
            raise TallyError(f"{aid}: the log's twin review outcome disagrees with the row")
        record = run.records.get(rid, {})
        twin_record = run.records.get(cid, {})
        out.append(
            {
                "artefact": aid,
                "class": STANDARD,
                "role": role,
                "expected_check": row["expected_check"],
                "lane": record.get("lane"),
                "review": verdict,
                "review_cause": cause,
                "twin_review": twin_verdict,
                "twin_review_cause": twin_cause,
                "cited_by_review": sorted(T.cited(line)),
                "cited_by_twin_review": sorted(T.cited(twin_line)),
                "A_rev": twin_verdict == "pass",
                "rev_open": verdict in T.NO_VERDICT,
                "twin_open": twin_verdict in T.NO_VERDICT,
                "raw_reject": verdict == "fail",
                "sheet_flaw_rejection": twin_verdict == "fail"
                and any(
                    T.names_pair(T.failing_evidence(twin_line), n, q)
                    for n, q in facts.sheet_pairs.get(aid, ())
                ),
                "tokens": int(record.get("tokens", row.get("reviewer_tokens", 0)))
                + int(twin_record.get("tokens", 0)),
            }
        )
    return out


def score(block: Block, arm: str, cells: Cells | None) -> list[dict[str, Any]]:
    """Every pair of one arm's run in a block, under the common, strict and locating rules."""
    run = block.runs[arm]
    kind = common.ARM_KIND[arm]
    items = (
        standard_items(run, block.facts, kind)
        if block.name == "s"
        else T.per_item(run, block.facts, kind)
    )
    rows = {r["artefact"]: r for r in run.rows}
    out = []
    for p in items:
        aid = p["artefact"]
        row = rows[aid]
        line = run.injected.review.get(row["review_id"])
        twin_line = run.controls.review.get(row["control_id"])
        review_items = frozenset(p["cited_by_review"])
        twin_items = frozenset(p["cited_by_twin_review"])
        com = T.naming(common_cell(kind, p["role"], p["class"], cells), review_items, twin_items)
        nodes = block.facts.changed[aid]
        pairs = block.law.changed_pairs(aid)
        injected_locates = any(locates(t, nodes, pairs) for t in rejecting_texts(line))
        twin_locates = any(locates(t, nodes, pairs) for t in rejecting_texts(twin_line))
        record = {
            "corpus": common.BLOCK_CORPUS[block.name],
            "block": block.name,
            "author_pair": common.AUTHOR_PAIR.get(block.name),
            "item": aid,
            "arm": arm,
            "class": p["class"],
            "role": p["role"],
            "review": p["review"],
            "review_cause": p["review_cause"],
            "twin_review": p["twin_review"],
            "twin_review_cause": p["twin_review_cause"],
            "cited_by_review": p["cited_by_review"],
            "cited_by_twin_review": p["cited_by_twin_review"],
            "common_deciding": com["deciding"],
            "R_common": p["review"] == "fail" and com["named"] is True,
            "R_locating": p["review"] == "fail" and injected_locates and not twin_locates,
            "A": p["A_rev"],
            "rev_open": p["rev_open"],
            "twin_open": p["twin_open"],
            "raw_reject": p["raw_reject"],
            "sheet_flaw_rejection": p["sheet_flaw_rejection"],
            "tokens": p["tokens"],
            "lane": p.get("lane"),
        }
        if p["class"] != STANDARD:
            strict = T.naming(strict_cell(kind, p["role"], p["class"]), review_items, twin_items)
            record["R_strict"] = p["review"] == "fail" and strict["named"] is True
            # The frozen record's own fields beside, the gate's among them, as it gave them.
            record.update({k: v for k, v in p.items() if k not in record})
        out.append(record)
    return out


# ---------------------------------------------------------------- the checks of each run


def check_run(
    block: Block, arm: str, fills: dict[str, Any] | None, any_count: bool = False
) -> dict[str, Any]:
    """One run held to its block and arm (§3, §5 R6, §11).

    Raises:
        RefusedError: anything differs.
    """
    run = block.runs[arm]
    cfg = run.config
    found: dict[str, Any] = {"rows": len(run.rows)}
    want = common.BLOCK_ITEMS[block.name]
    if len(run.rows) != want and not any_count:
        raise RefusedError(f"block {block.name}, arm {arm}: {len(run.rows)} rows, not {want}")
    expect = {
        "seed": common.BLOCK_SEED[block.name],
        "reviewer_kind": common.ARM_KIND[arm],
        "lanes": common.LANES[arm],
        "account_sha256": common.ACCOUNT_SHA256,
    }
    for key, value in expect.items():
        if cfg.get(key, "paired" if key == "reviewer_kind" else None) != value:
            raise RefusedError(f"block {block.name}, arm {arm}: {key} is not the block's and arm's")
    models = set((cfg.get("reviewer_models") or {}).values())
    if models != {common.REVIEWER_MODEL}:
        raise RefusedError(f"block {block.name}, arm {arm}: a reviewer model is not the pinned one")
    if fills is not None:
        manifests = (fills.get("sets") or {}).get("manifests") or {}
        name = common.BLOCK_CORPUS[block.name]
        if cfg.get("corpus_manifest_sha256") != manifests.get(name):
            raise RefusedError(f'block {block.name}, arm {arm}: the corpus is not "Set filled"\'s')
    bad = seen = 0
    for log in (run.injected, run.controls):
        for line in log.reviews:
            if line.get("kind") != "review_ran":
                continue
            seen += 1
            role = log.role.get(line["subtask_id"], "")
            bad += line["result"].get("rubric_sha256") != common.RUBRIC_SHA256[arm].get(role)
    found["review_lines"] = seen
    if bad:
        raise RefusedError(
            f"block {block.name}, arm {arm}: {bad} review line(s) carry another arm's rubric "
            "digest; the block is void and re-run (§11)"
        )
    return found


def expected_knowledge(repo: Path, arm: str, role: str) -> dict[str, str]:
    """The knowledge digests a review of this arm and role is given: its pinned tree's files."""
    from physgate.knowledge import loader

    domain = loader.CROSS if common.ARM_KIND[arm] == "generalist" else role
    out = {}
    for relative in loader.always_loaded(domain):
        rel = relative.as_posix()
        tree_path, _, name = rel.rpartition("/")
        tree = common.KNOWLEDGE_TREES.get(tree_path)
        if tree is None:
            raise RefusedError(f"{rel} lies in no pinned knowledge tree")
        out[rel] = common.sha256_bytes(common.git_bytes(repo, "cat-file", "blob", f"{tree}:{name}"))
    return out


def check_knowledge(repo: Path, block: Block, arm: str) -> dict[str, Any]:
    """Every packet's knowledge digests against its arm and role, where its record is kept."""
    scratch = block.scratch.get(arm)
    if scratch is None:
        return {"checked": 0, "rests_on_the_launch_tree_pins": True}
    run = block.runs[arm]
    roots = common.lane_roots(scratch)
    checked = missing = bad = 0
    want: dict[str, dict[str, str]] = {}
    for log in (run.injected, run.controls):
        for line in log.reviews:
            if line.get("kind") != "review_ran":
                continue
            sid = line["result"].get("session_id")
            role = log.role.get(line["subtask_id"], "")
            data = None
            for root in roots:
                if sid and common.SESSION_ID.fullmatch(sid):
                    data = common.read_inside(root, root / sid / "packet.json")
                if data is not None:
                    break
            if data is None:
                missing += 1
                continue
            checked += 1
            if role not in want:
                want[role] = expected_knowledge(repo, arm, role)
            if json.loads(data).get("knowledge_sha256") != want[role]:
                bad += 1
    if bad:
        raise RefusedError(
            f"block {block.name}, arm {arm}: {bad} packet(s) carry another arm's knowledge; the "
            "block is void and re-run (§11)"
        )
    return {
        "checked": checked,
        "packets_missing": missing,
        "rests_on_the_launch_tree_pins": checked == 0,
    }


# ---------------------------------------------------------------- statistics


def pairs_of(items: list[dict[str, Any]], r_key: str, a_key: str = "A") -> list[tuple[int, int]]:
    """Each item's (rejected for the right reason, accepted), as 0 or 1."""
    return [(int(bool(p[r_key])), int(bool(p[a_key]))) for p in items]


def strat_draw(rng: random.Random, strata: list[list[int]]) -> list[int]:
    """One stratified draw: each stratum, in order, resampled within itself."""
    return [s[i] for s in strata for i in T.resample(rng, len(s))]


def j_strat(pairs: list[tuple[float, float]], strata: list[list[int]], draws: int) -> list[float]:
    """J's interval, the pairs resampled within each stratum."""
    return list(T.boot(lambda rng: T.j_of([pairs[i] for i in strat_draw(rng, strata)]), draws))


def contrast_strat(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
    strata: list[list[int]],
    draws: int,
) -> list[float]:
    """J_a - J_b on the same pairs, one stratified draw serving both arms."""
    if len(a) != len(b):
        raise TallyError("a contrast needs the same pairs in both arms")

    def stat(rng: random.Random) -> float:
        idx = strat_draw(rng, strata)
        return float(T.j_of([a[i] for i in idx]) - T.j_of([b[i] for i in idx]))

    return list(T.boot(stat, draws))


def pair_against_rest(
    a: list[tuple[float, float]],
    b: list[tuple[float, float]],
    strata: list[list[int]],
    k: int,
    draws: int,
) -> list[float]:
    """§6.4 item 1: the contrast on stratum ``k`` less the contrast on the other two, pooled."""

    def stat(rng: random.Random) -> float:
        drawn = [[s[i] for i in T.resample(rng, len(s))] for s in strata]
        mine = drawn[k]
        rest = [i for j, d in enumerate(drawn) if j != k for i in d]
        here = T.j_of([a[i] for i in mine]) - T.j_of([b[i] for i in mine])
        there = T.j_of([a[i] for i in rest]) - T.j_of([b[i] for i in rest])
        return float(here - there)

    return list(T.boot(stat, draws))


def joint_drop_difference(
    before_x: list[tuple[float, float]],
    before_y: list[tuple[float, float]],
    after_x: list[tuple[float, float]],
    after_y: list[tuple[float, float]],
    draws: int,
) -> list[float]:
    """(x's drop) - (y's drop) over two sets, each set's pairs drawn once per draw for both arms.

    In the frozen ``drop_interval``'s order: the earlier set's pairs first, then the later set's.
    """

    def stat(rng: random.Random) -> float:
        i = T.resample(rng, len(before_x))
        k = T.resample(rng, len(after_x))
        dx = T.j_of([before_x[n] for n in i]) - T.j_of([after_x[n] for n in k])
        dy = T.j_of([before_y[n] for n in i]) - T.j_of([after_y[n] for n in k])
        return float(dx - dy)

    return list(T.boot(stat, draws))


def noise_band(n: int) -> float:
    """§6.2's band: +-0.175 at 40 pairs, scaled by the square root of the pair count."""
    return round(NOISE_BAND_40 * math.sqrt(40 / n), 4) if n else 0.0


def arm_figures(
    items: list[dict[str, Any]],
    r_key: str,
    draws: int,
    strata: list[list[int]] | None,
    a_key: str = "A",
) -> dict[str, Any]:
    """R, A and J of one arm over its pairs, with their intervals and §4.4's columns."""
    n = len(items)
    if n == 0:
        return {"n": 0}
    pairs = pairs_of(items, r_key, a_key)
    r, a = sum(x for x, _ in pairs), sum(y for _, y in pairs)
    interval = (
        j_strat([(float(x), float(y)) for x, y in pairs], strata, draws)
        if strata is not None
        else list(T.boot(lambda rng: T.j_of([pairs[i] for i in T.resample(rng, n)]), draws))
    )
    ro = sum(1 for p in items if p["rev_open"])
    ao = sum(1 for p in items if p["twin_open"])
    r_in = sum(int(bool(p[r_key])) for p in items if not p["rev_open"])
    a_in = sum(int(bool(p[a_key])) for p in items if not p["twin_open"])
    rv, av = n - ro, n - ao
    sf = sum(1 for p in items if p["sheet_flaw_rejection"])
    return {
        "n": n,
        "R": r,
        "A": a,
        "J": round(T.j_of(pairs), 4),
        "R_wilson95": T.wilson(r, n),
        "A_wilson95": T.wilson(a, n),
        "J_bootstrap95": interval,
        "raw_reject": sum(1 for p in items if p["raw_reject"]),
        "no_verdict": {"injected": ro, "twins": ao},
        "among_verdicts_only": {
            "R": [r_in, rv],
            "A": [a_in, av],
            "J": round((r_in / rv if rv else 0) + (a_in / av if av else 0) - 1, 4),
        },
        "range_if_each_no_verdict_went_either_way": {
            "R": [r, r + ro],
            "A": [a, a + ao],
            "J": [round((r + a) / n - 1, 4), round((r + ro + a + ao) / n - 1, 4)],
        },
        "unscored": 0,
        "sheet_flaw_rejections": sf,
        "without_sheet_flaw_rejections": {
            "A": [a, n - sf],
            "J": round(r / n + (a / (n - sf) if n - sf else 0) - 1, 4),
        },
    }


def contrast_figure(
    a: list[dict[str, Any]],
    b: list[dict[str, Any]],
    r_key: str,
    draws: int,
    strata: list[list[int]] | None,
    a_key: str = "A",
) -> dict[str, Any]:
    """J_a - J_b on the same pairs, its interval, and the noise band beside it."""
    if [p["item"] for p in a] != [p["item"] for p in b] or [p["corpus"] for p in a] != [
        p["corpus"] for p in b
    ]:
        raise TallyError("the arms did not review the same items in the same order")
    pa = [(float(x), float(y)) for x, y in pairs_of(a, r_key, a_key)]
    pb = [(float(x), float(y)) for x, y in pairs_of(b, r_key, a_key)]
    point = round(T.j_of(pa) - T.j_of(pb), 4)
    interval = (
        contrast_strat(pa, pb, strata, draws)
        if strata is not None
        else list(T.contrast_interval(pa, pb, draws))
    )
    band = noise_band(len(pa))
    return {
        "J": point,
        "interval": interval,
        "noise_band": band,
        "within_run_to_run_noise": abs(point) <= band,
    }


# ---------------------------------------------------------------- the decisions


def row_of(interval: list[float]) -> str:
    """§8's row from J_A2 - J_B's interval: 1, 2, 3a or 3b (2a and 2b are chosen apart)."""
    lo, hi = interval
    if lo > 0:
        return "1"
    if lo > Q3_MARGIN:
        return "2"
    return "3a" if hi < 0 else "3b"


def fix_sentence(interval: list[float], guards: dict[str, bool]) -> dict[str, Any]:
    """§8's sentence for Q1, and every guard that failed."""
    lo, hi = interval
    failed = [k for k, v in guards.items() if not v]
    if lo > 0 and not failed:
        which = "met"
    elif lo > 0:
        which = "a guard failed"
    elif hi < 0:
        which = "worse"
    else:
        which = "not shown"
    return {"sentence": which, "guards_failed": failed}


def q1_guards(a2: dict[str, Any], a1: dict[str, Any], a_key: str = "A") -> dict[str, bool]:
    """Q1's guards: A_A2 >= A_A1, and R_A2 at most 6 pairs below R_A1 under each rule."""
    return {
        "A": a2[a_key] >= a1[a_key],
        "R under the common rule": a1["R_common"] - a2["R_common"] <= R_GUARD,
        "R under the strict rule": a1["R_strict"] - a2["R_strict"] <= R_GUARD,
    }


def q4(
    before: list[tuple[float, float]], after: list[tuple[float, float]], draws: int
) -> dict[str, Any]:
    """P5's form (R-PG-02 §6): tailoring, possible tailoring, or neither."""
    drop = round(T.j_of(before) - T.j_of(after), 4)
    interval = list(T.drop_interval(before, after, draws))
    tailoring = interval[0] > 0
    return {
        "J_before": round(T.j_of(before), 4),
        "J_after": round(T.j_of(after), 4),
        "drop": drop,
        "interval": interval,
        "tailoring": tailoring,
        "possible_tailoring": (not tailoring) and drop > POSSIBLE_TAILORING,
    }


def corrected_a(status: str, verdict: str, own_confirmed: bool, way: int) -> bool:
    """§7's corrected A for one arm's review of one twin, in way 1 or way 2."""
    if status == "unflawed" or (status == "undecided" and way == 1):
        return verdict == "pass"
    if status == "undecided":
        return verdict == "fail"
    return verdict == "fail" and own_confirmed


# ---------------------------------------------------------------- reading the records


def blocks_record(records: Path) -> dict[str, Any]:
    """The launch's record of every block attempt, held to R8: nothing tallied before the end.

    Raises:
        RefusedError: a block has no valid attempt that ended and passed its stream check, and
            is not recorded as not run; or one of the primary blocks is recorded as not run.
    """
    data = common.read_own(records / "blocks.json")
    if data is None:
        raise RefusedError(
            "no block record: nothing is tallied before the last block has ended (R8)"
        )
    rec = json.loads(data)
    not_run = rec.get("not_run") or {}
    if set(not_run) - {"s", "p1", "p2"}:
        raise RefusedError("a primary block is recorded as not run: the primary is not measured")
    chosen: dict[str, Any] = {}
    for block in common.BLOCKS:
        valid = [
            a
            for a in rec.get("attempts", [])
            if a.get("block") == block
            and a.get("valid") is True
            and a.get("ended_utc")
            and (a.get("stream_check") or {}).get("cut") == 0
        ]
        if block in not_run:
            if valid:
                raise RefusedError(f"block {block} is recorded both as run and as not run")
            continue
        if len(valid) != 1:
            raise RefusedError(
                f"block {block} has {len(valid)} valid attempt(s) that ended and passed the stream "
                "check: nothing is tallied before the last block has ended (R8)"
            )
        chosen[block] = valid[0]
    return {"chosen": chosen, "not_run": not_run}


def read_block(
    name: str, attempt: dict[str, Any], sets: Path, scratch: dict[str, Path | None]
) -> Block:
    """One block's three runs and its corpus's facts."""
    corpus = sets / common.BLOCK_CORPUS[name]
    runs = {arm: T.Run.read(Path(attempt["runs"][arm]), any_count=True) for arm in common.ARMS}
    return Block(name, corpus, runs, T.set_facts(corpus), set_data(corpus), scratch)


def practice_items(
    runs: dict[str, Path], tuning: Path, pinned: bool
) -> dict[str, list[dict[str, Any]]]:
    """The tuning set's three practice runs under the common rule, held to R-LAW-01's digests.

    Raises:
        RefusedError: a run is not at its recorded digests, or not of its pinned kind and set.
    """
    if set(runs) != set(PRACTICE_RUNS):
        raise RefusedError("the practice runs are round-1, a-fresh and repeat-K, each named once")
    if pinned:
        digests = json.loads(LX.INPUTS.read_text())
        pins = {p.label: p for p in LX.FROZEN.runs}
        for label, path in runs.items():
            try:
                LX.load_run(LX.FROZEN, pins[label], path, digests)
            except LX.Refused as exc:
                raise RefusedError(f"practice run {label}: {exc}") from exc
    facts = T.set_facts(tuning)
    out = {}
    for label, path in runs.items():
        run = T.Run.read(path, any_count=not pinned)
        items = []
        for p in T.per_item(run, facts, "paired"):
            com = T.naming(
                common_cell("paired", p["role"], p["class"], None),
                frozenset(p["cited_by_review"]),
                frozenset(p["cited_by_twin_review"]),
            )
            items.append(
                {
                    "item": p["artefact"],
                    "R_common": p["review"] == "fail" and com["named"] is True,
                    "A": p["A_rev"],
                }
            )
        out[label] = sorted(items, key=lambda x: x["item"])
    return out


# ---------------------------------------------------------------- the whole tally


def strata_of(items: list[dict[str, Any]]) -> list[list[int]]:
    """The indices of X's, Y's and Z's pairs, in that order."""
    return [[i for i, p in enumerate(items) if p["author_pair"] == pair] for pair in common.PAIRS]


def by_corpus_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items in §7's line order: corpus, then item id."""
    return sorted(items, key=lambda p: (common.CORPUS_ORDER.index(p["corpus"]), p["item"]))


def group(
    items: list[dict[str, Any]],
    key: str,
    values: Iterable[Any],
    fn: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    """Figures per value of one key."""
    return {str(v): fn([p for p in items if p[key] == v]) for v in values}


def per_item_table(a2: list[dict[str, Any]], a1: list[dict[str, Any]]) -> dict[str, Any]:
    """§6.4 item 5: A2 against A1, gained and lost per side, with practice's churn beside."""
    rows = []
    for x, y in zip(a2, a1, strict=True):
        rows.append(
            {
                "corpus": x["corpus"],
                "item": x["item"],
                "injected": [int(y["R_common"]), int(x["R_common"])],
                "twin": [int(y["A"]), int(x["A"])],
            }
        )
    return {
        "rows": rows,
        "injected_gained": sum(r["injected"] == [0, 1] for r in rows),
        "injected_lost": sum(r["injected"] == [1, 0] for r in rows),
        "twins_gained": sum(r["twin"] == [0, 1] for r in rows),
        "twins_lost": sum(r["twin"] == [1, 0] for r in rows),
        "practice_churn": PRACTICE_CHURN,
    }


def no_verdicts(
    runs: dict[str, list[Any]], items: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """§6.4 item 4: per arm, no verdicts by role and side with causes.

    Beside them, each run's repair resumes and schema refusals, from its review lines.
    """
    out: dict[str, Any] = {}
    for arm in common.ARMS:
        by_role: dict[str, Any] = {}
        for role in common.ROLES:
            mine = [p for p in items[arm] if p["role"] == role]
            by_role[role] = {
                "injected": dict(
                    Counter(f"{p['review']}:{p['review_cause']}" for p in mine if p["rev_open"])
                ),
                "twins": dict(
                    Counter(
                        f"{p['twin_review']}:{p['twin_review_cause']}"
                        for p in mine
                        if p["twin_open"]
                    )
                ),
            }
        out[arm] = {
            "by_role": by_role,
            "instrument": [T.instrument_figures(run) for run in runs[arm]],
        }
    return out


def item_times(block: Block) -> dict[str, Any]:
    """§6.4 item 11: each item's review start and end, its retries and its lane, per arm."""
    out: dict[str, Any] = {}
    for arm in common.ARMS:
        run = block.runs[arm]
        rows = []
        for r in run.rows:
            for side, sid in (("injected", r["review_id"]), ("twin", r["control_id"])):
                rec = run.records.get(sid, {})
                tries = rec.get("tries", [])
                rows.append(
                    {
                        "item": r["artefact"],
                        "side": side,
                        "lane": rec.get("lane"),
                        "started": tries[0].get("started_at") if tries else None,
                        "ended": tries[-1].get("ended_at") if tries else None,
                        "retries": sum(1 for x in tries if x.get("delay_before_s", 0) > 0),
                    }
                )
        out[arm] = {"items": rows, "span": T.instrument_figures(run)["wall_clock"]}
    return out


def standard_class(
    items: dict[str, list[dict[str, Any]]],
    reading: dict[str, Any] | None,
    draws: int,
) -> dict[str, Any]:
    """§6.4 item 9 and §8's class rule: A2 against B on the class's 10 pairs."""
    a2, b = items["A2"], items["B"]
    out: dict[str, Any] = {
        arm: {
            "common": arm_figures(items[arm], "R_common", draws, None),
            "locating": arm_figures(items[arm], "R_locating", draws, None),
        }
        for arm in common.ARMS
    }
    halves: dict[str, Any] = {}
    for rule, key in (("common", "R_common"), ("locating", "R_locating")):
        n_a2 = sum(1 for x, y in zip(a2, b, strict=True) if x[key] and not y[key])
        n_b = sum(1 for x, y in zip(a2, b, strict=True) if y[key] and not x[key])
        a1_only = sum(1 for x, y in zip(items["A1"], b, strict=True) if x[key] and not y[key])
        b_not_a1 = sum(1 for x, y in zip(items["A1"], b, strict=True) if y[key] and not x[key])
        halves[rule] = {
            "n_A2": n_a2,
            "n_B": n_b,
            "d": n_a2 - n_b,
            "A1_names_B_misses": a1_only,
            "B_names_A1_misses": b_not_a1,
        }
    catch = all(halves[r]["d"] >= CLASS_CATCH_D for r in ("common", "locating"))
    raw = {arm: sum(1 for p in items[arm] if p["A"]) for arm in ("A2", "B")}
    accept: dict[str, Any] = {"raw_of_10": raw}
    reliable = reading is not None and reading.get("reliability") == "reliable"
    if reliable and reading is not None:
        status = {t["item"]: t["status"] for t in reading.get("standard_twins", [])}
        ways = {}
        for way, kept in ((1, ("unflawed", "undecided")), (2, ("unflawed",))):
            twins = [p["item"] for p in a2 if status.get(p["item"]) in kept]
            got = {
                arm: sum(1 for p in items[arm] if p["item"] in twins and p["A"])
                for arm in ("A2", "B")
            }
            ways[f"way {way}"] = {
                "k": len(twins),
                "accepted": got,
                "holds": got["B"] - got["A2"] <= CLASS_ACCEPT_GAP,
            }
        accept.update(counted="in both ways", ways=ways)
        accept_holds = all(w["holds"] for w in ways.values())
    else:
        accept.update(counted="raw, on all 10 twins (the reading is not reliable)")
        accept_holds = raw["B"] - raw["A2"] <= CLASS_ACCEPT_GAP
    out["halves"] = halves
    out["catch_half_holds"] = catch
    out["acceptance"] = accept
    out["acceptance_half_holds"] = accept_holds
    out["class_rule_holds"] = catch and accept_holds
    out["note"] = "a count on 10 pairs, not a tested effect"
    return out


def class_clause(cls: dict[str, Any] | None) -> str:
    """§8's class clause, printed after the sentence of every row."""
    if cls is None:
        return "On the domain-standard class (10 pairs, secondary), the class was not measured."
    h = cls["halves"]
    acc = cls["acceptance"]
    raw = acc["raw_of_10"]
    head = (
        "On the domain-standard class (10 pairs, secondary), the fixed specialists credited "
        f"{h['common']['n_A2']} of its errors that the generalist missed, and the generalist "
        f"{h['common']['n_B']} that they missed (under the locating rule, {h['locating']['n_A2']} "
        f"and {h['locating']['n_B']}); "
    )
    if acc.get("ways"):
        parts = []
        for way, w in acc["ways"].items():
            parts.append(
                f"{way}: of its {w['k']} correct twins that the reading does not mark flawed, "
                f"they accepted {w['accepted']['A2']} against the generalist's {w['accepted']['B']}"
            )
        body = "; ".join(parts) + f", and of all 10, {raw['A2']} against {raw['B']}. "
    else:
        body = (
            f"of its 10 correct twins, they accepted {raw['A2']} against the generalist's "
            f"{raw['B']}. "
        )
    return head + body + "A count, not a tested effect."


def row_sentence(
    row: str, contrast: dict[str, Any], cost: float | None, bracket: bool, specialists_test: bool
) -> str:
    """§8's sentence for the row, its figures filled in."""
    j = f"J_A2 - J_B = {contrast['J']} ({contrast['interval'][0]}, {contrast['interval'][1]})"
    times = "an unknown multiple of" if cost is None else f"{cost}x"
    if row == "1":
        return (
            "After the fix, paired specialists discriminate better than a role-aware generalist on "
            f"new material: {j}, at {times} the tokens."
        )
    if row in ("2a", "2b"):
        extra = ", and are shown worse by less than the margin" if bracket else ""
        return (
            "After the fix, paired specialists are not shown worse than a role-aware generalist by "
            f"the margin (0.15){extra}, and cost {times} as much; on the four generic classes no "
            "gain is shown."
        )
    if row == "3a":
        return (
            "On this design class (one stand-in self-balancing robot and its parts sheet) and "
            "these four error classes, a role-aware generalist reviewer with the shared verdict "
            f"policy suffices; paired specialists cost about {times} with no measured gain."
        )
    worse = "" if specialists_test else "not "
    return (
        "On this design class (one stand-in self-balancing robot and its parts sheet) and these "
        "four error classes, paired specialists were not shown to be at least as good as a "
        "role-aware generalist reviewer with the shared verdict policy (margin 0.15), and cost "
        f"about {times} as much. This does not show the two equal: {j}. Beside it: the generalist "
        f"is {worse}shown worse than the specialists (margin 0.15)."
    )


def fix_text(s: dict[str, Any], contrast: dict[str, Any]) -> str:
    """§8's fix sentence, its figures filled in."""
    j = f"J_A2 - J_A1 = {contrast['J']} ({contrast['interval'][0]}, {contrast['interval'][1]})"
    if s["sentence"] == "met":
        return f"The calibration fix worked on new material: {j}."
    if s["sentence"] == "a guard failed":
        return (
            f"J rose on new material: {j}. But Q1's guard on "
            f"[{' | '.join(s['guards_failed'])}] failed, so the gain is not counted."
        )
    if s["sentence"] == "worse":
        return "The fix made the specialists worse on new material."
    return f"The fix's gain was not shown on new material: {j}."


def cost_ratio(runs: dict[str, list[Any]]) -> dict[str, Any]:
    """The cost ratio of A2 to B and of A1 to B: tokens and USD per review, binary totals."""
    per: dict[str, Any] = {}
    for arm, rs in runs.items():
        costs = [T.cost(r) for r in rs]
        reviews = sum(c["reviews"] for c in costs)
        tokens = sum(c["tokens_every_try"] for c in costs)
        usd = sum(c["usd_list_price_equivalent"] for c in costs)
        per[arm] = {
            "reviews": reviews,
            "tokens_every_try": tokens,
            "usd_list_price_equivalent": round(usd, 2),
            "tokens_per_review": tokens / reviews if reviews else None,
            "usd_per_review": usd / reviews if reviews else None,
            "tokens_of_verdict_lines": dict(
                sum((Counter(c["tokens_of_verdict_lines"]) for c in costs), Counter())
            ),
        }

    def ratio(a: str, key: str) -> float | None:
        x, y = per[a][key], per["B"][key]
        return round(x / y, 4) if x is not None and y else None

    return {
        "per_arm": per,
        "A2_to_B": {
            "tokens": ratio("A2", "tokens_per_review"),
            "usd": ratio("A2", "usd_per_review"),
        },
        "A1_to_B": {
            "tokens": ratio("A1", "tokens_per_review"),
            "usd": ratio("A1", "usd_per_review"),
        },
        "price_sheet": T.PRICE_SHEET,
    }


def reading_pairs(
    items: list[dict[str, Any]], reading: dict[str, Any], way: int
) -> list[tuple[float, float]]:
    """Each pair's (R common, corrected A) for one arm, in one way of §7's reading."""
    twins = {(t["corpus"], t["item"]): t for t in reading["twins"]}
    out = []
    for p in items:
        t = twins.get((p["corpus"], p["item"]))
        if t is None:
            raise RefusedError(f"the reading has no status for twin {p['corpus']} {p['item']}")
        own = bool((t.get("confirmed_by_arm") or {}).get(p["arm"]))
        out.append(
            (float(p["R_common"]), float(corrected_a(t["status"], p["twin_review"], own, way)))
        )
    return out


def tally(
    records: Path,
    sets: Path,
    practice: dict[str, Path],
    reading_path: Path | None,
    scratch: dict[str, dict[str, Path]],
    draws: int = common.BOOT_DRAWS,
    *,
    practice_pinned: bool = True,
    fills: dict[str, Any] | None = None,
    repo: Path = common.REPO,
    any_count: bool = False,
    tuning: Path | None = None,
) -> dict[str, Any]:
    """Every figure of §4, §6 and §8.

    Raises:
        RefusedError: R8, or any check of the runs, sets or records.
    """
    rec = blocks_record(records)
    cells = Cells.at(repo)
    blocks: dict[str, Block] = {}
    checks: dict[str, Any] = {}
    for name, attempt in rec["chosen"].items():
        sc = {arm: scratch.get(arm, {}).get(name) for arm in common.ARMS}
        blocks[name] = read_block(name, attempt, sets, sc)
        checks[name] = {
            arm: {
                **check_run(blocks[name], arm, fills, any_count),
                "knowledge": check_knowledge(repo, blocks[name], arm),
            }
            for arm in common.ARMS
        }
    scored = {
        name: {arm: score(b, arm, cells) for arm in common.ARMS} for name, b in blocks.items()
    }
    reading = json.loads(reading_path.read_text()) if reading_path is not None else None
    # ---- the primary: 120 pairs, X, Y and Z ----
    primary = {
        arm: by_corpus_order([p for b in common.PRIMARY_BLOCKS for p in scored[b][arm]])
        for arm in common.ARMS
    }
    strata = strata_of(primary["A2"])
    figs = {
        arm: {
            rule: arm_figures(primary[arm], f"R_{rule}", draws, strata)
            for rule in ("common", "strict", "locating")
        }
        for arm in common.ARMS
    }
    contrasts = {
        rule: {
            "A2_minus_A1": contrast_figure(
                primary["A2"], primary["A1"], f"R_{rule}", draws, strata
            ),
            "A2_minus_B": contrast_figure(primary["A2"], primary["B"], f"R_{rule}", draws, strata),
            "A1_minus_B": contrast_figure(primary["A1"], primary["B"], f"R_{rule}", draws, strata),
        }
        for rule in ("common", "strict", "locating")
    }
    fix = contrasts["common"]["A2_minus_A1"]
    pair = contrasts["common"]["A2_minus_B"]
    r_counts = {
        arm: {
            "R_common": figs[arm]["common"]["R"],
            "R_strict": figs[arm]["strict"]["R"],
            "A": figs[arm]["common"]["A"],
        }
        for arm in ("A2", "A1")
    }
    guards = q1_guards(r_counts["A2"], r_counts["A1"])
    q1 = {
        "interval": fix["interval"],
        "guards": guards,
        "met": fix["interval"][0] > 0 and all(guards.values()),
    }
    q2 = {"interval": pair["interval"], "met": pair["interval"][0] > 0}
    q3 = {"interval": pair["interval"], "margin": Q3_MARGIN, "met": pair["interval"][0] > Q3_MARGIN}
    # ---- Q4 and the readings beside it ----
    tuning = repo / common.TUNING_SET if tuning is None else tuning
    prac = practice_items(practice, tuning, practice_pinned)
    kept = [(float(p["R_common"]), float(p["A"])) for p in prac["round-1"]]
    k_mean = [
        ((float(x["R_common"]) + float(y["R_common"])) / 2, (float(x["A"]) + float(y["A"])) / 2)
        for x, y in zip(prac["a-fresh"], prac["repeat-K"], strict=True)
    ]
    if [p["item"] for p in prac["a-fresh"]] != [p["item"] for p in prac["repeat-K"]]:
        raise RefusedError("K's two practice runs did not review the same items")
    a2_pairs = [(float(x), float(y)) for x, y in pairs_of(primary["A2"], "R_common")]
    a1_pairs = [(float(x), float(y)) for x, y in pairs_of(primary["A1"], "R_common")]
    q4_main = q4(kept, a2_pairs, draws)
    q4_main["practice_figure_is_the_criteria_s"] = round(T.j_of(kept), 4) == KEPT_ROUND_J
    adj_point = round((T.j_of(kept) - T.j_of(a2_pairs)) - (T.j_of(k_mean) - T.j_of(a1_pairs)), 4)
    adj = {
        "point": adj_point,
        "interval": joint_drop_difference(kept, k_mean, a2_pairs, a1_pairs, draws),
    }
    flags = q4_main["tailoring"] or q4_main["possible_tailoring"]
    adj["label"] = (
        "a shift of the set, not shown to be tailoring"
        if flags
        and adj["interval"][0] <= 0 <= adj["interval"][1]
        and adj_point <= POSSIBLE_TAILORING
        else None
    )
    sheet_matched: dict[str, Any] | None = None
    if "p1" in scored and "p2" in scored:
        p_items = {arm: scored["p1"][arm] + scored["p2"][arm] for arm in common.ARMS}
        pa2 = [(float(x), float(y)) for x, y in pairs_of(p_items["A2"], "R_common")]
        pa1 = [(float(x), float(y)) for x, y in pairs_of(p_items["A1"], "R_common")]
        sheet_matched = {
            "q4": q4(pa2, a2_pairs, draws),
            "set_adjusted": {
                "point": round(
                    (T.j_of(pa2) - T.j_of(a2_pairs)) - (T.j_of(pa1) - T.j_of(a1_pairs)), 4
                ),
                "interval": joint_drop_difference(pa2, pa1, a2_pairs, a1_pairs, draws),
            },
        }
    # ---- §6.4 ----
    author_pairs = {}
    for name in common.PAIRS:
        mine = {arm: [p for p in primary[arm] if p["author_pair"] == name] for arm in common.ARMS}
        author_pairs[name] = {
            "figures": {
                arm: arm_figures(mine[arm], "R_common", draws, None) for arm in common.ARMS
            },
            "A2_minus_A1": contrast_figure(mine["A2"], mine["A1"], "R_common", draws, None),
            "A2_minus_B": contrast_figure(mine["A2"], mine["B"], "R_common", draws, None),
        }
    comparisons = {}
    for label, other in (("A2_minus_A1", "A1"), ("A2_minus_B", "B")):
        pa = [(float(x), float(y)) for x, y in pairs_of(primary["A2"], "R_common")]
        pb = [(float(x), float(y)) for x, y in pairs_of(primary[other], "R_common")]
        per = {
            name: pair_against_rest(pa, pb, strata, k, draws) for k, name in enumerate(common.PAIRS)
        }
        comparisons[label] = {
            "intervals": per,
            "the_author_pairs_differ": any(not (lo <= 0 <= hi) for lo, hi in per.values()),
            "comparisons": "3 per contrast, 6 in all, uncorrected",
        }
    per_block = {
        name: {arm: arm_figures(scored[name][arm], "R_common", draws, None) for arm in common.ARMS}
        for name in scored
    }
    per_class = {
        arm: group(
            primary[arm], "class", CLASSES, lambda x: arm_figures(x, "R_common", draws, None)
        )
        for arm in common.ARMS
    }
    per_role = {
        arm: group(
            primary[arm], "role", common.ROLES, lambda x: arm_figures(x, "R_common", draws, None)
        )
        for arm in common.ARMS
    }
    runs_by_arm = {arm: [blocks[b].runs[arm] for b in common.PRIMARY_BLOCKS] for arm in common.ARMS}
    gate = {
        "layer": T.gate_layer([_gate_view(p) for p in primary["A2"]], draws),
        "per_class": group(
            [_gate_view(p) for p in primary["A2"]],
            "class",
            CLASSES,
            lambda x: T.gate_layer(x, draws),
        ),
        "per_role": group(
            [_gate_view(p) for p in primary["A2"]],
            "role",
            common.ROLES,
            lambda x: T.gate_layer(x, draws),
        ),
        "checks": {
            "injected": T.check_counts(
                [
                    blocks[b].runs["A2"].injected.gate[r["review_id"]]
                    for b in common.PRIMARY_BLOCKS
                    for r in blocks[b].runs["A2"].rows
                ]
            ),
            "twins": T.check_counts(
                [
                    blocks[b].runs["A2"].controls.gate[r["control_id"]]
                    for b in common.PRIMARY_BLOCKS
                    for r in blocks[b].runs["A2"].rows
                ]
            ),
        },
        "note": "the gate's acceptance of the twins is 100 % by construction, and is not a result",
    }
    cost = cost_ratio(runs_by_arm)
    standard: dict[str, Any] | None = None
    if "s" in scored:
        standard = standard_class(scored["s"], reading, draws)
    # ---- §8 ----
    cls_holds = bool(standard and standard["class_rule_holds"])
    row = row_of(pair["interval"])
    if row == "2":
        row = "2a" if cls_holds else "2b"
    bracket = row in ("2a", "2b") and pair["interval"][1] < 0
    specialists_test = pair["interval"][1] < 0.15
    ratio = cost["A2_to_B"]["tokens"]
    fix_s = fix_sentence(fix["interval"], guards)
    robust: dict[str, Any] = {
        "row": {"locating": row_of(contrasts["locating"]["A2_minus_B"]["interval"])},
        "fix": {
            "strict": fix_sentence(contrasts["strict"]["A2_minus_A1"]["interval"], guards)[
                "sentence"
            ]
        },
    }
    reliability = (reading or {}).get("reliability", "unchecked")
    if reading is not None and reliability == "reliable":
        for way in (1, 2):
            p2 = reading_pairs(primary["A2"], reading, way)
            pb = reading_pairs(primary["B"], reading, way)
            p1 = reading_pairs(primary["A1"], reading, way)
            row_iv = contrast_strat(p2, pb, strata, draws)
            fix_iv = contrast_strat(p2, p1, strata, draws)
            a_corr = {"A": sum(int(y) for _, y in p2) >= sum(int(y) for _, y in p1)}
            robust["row"][f"corrected-A way {way}"] = row_of(row_iv)
            robust["fix"][f"corrected-A way {way}"] = fix_sentence(fix_iv, {**guards, **a_corr})[
                "sentence"
            ]
    base_row = "2" if row in ("2a", "2b") else row
    robust["row_is_robust"] = all(v == base_row for v in robust["row"].values())
    robust["row_readings_that_differ"] = [k for k, v in robust["row"].items() if v != base_row]
    robust["fix_is_robust"] = all(v == fix_s["sentence"] for v in robust["fix"].values())
    robust["fix_readings_that_differ"] = [
        k for k, v in robust["fix"].items() if v != fix_s["sentence"]
    ]
    robust["corrected_a_used"] = reliability == "reliable"
    q4_clean = not (q4_main["tailoring"] or q4_main["possible_tailoring"])
    decision = {
        "row": row,
        "row_sentence": row_sentence(row, pair, ratio, bracket, specialists_test),
        "claim_shift_applies": row in ("3a", "3b"),
        "class_clause": class_clause(standard),
        "fix_sentence": fix_s,
        "fix_text": fix_text(fix_s, fix),
        "success": q1["met"] and q3["met"] and q4_clean,
        "q4_clean": q4_clean,
        "robustness": robust,
    }
    return {
        "blocks": {
            k: {"attempt": v.get("attempt"), "checks": checks[k]} for k, v in rec["chosen"].items()
        },
        "not_run": rec["not_run"],
        "primary": {
            "figures": figs,
            "contrasts": contrasts,
            "cost": cost,
        },
        "criteria": {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4_main},
        "q4_set_adjusted": adj,
        "q4_sheet_matched": sheet_matched,
        "secondary": {
            "per_author_pair": author_pairs,
            "author_pairs_compared": comparisons,
            "per_block": per_block,
            "per_class": per_class,
            "per_role": per_role,
            "k_against_generalist": contrasts["common"]["A1_minus_B"],
            "no_verdicts": no_verdicts(runs_by_arm, primary),
            "a2_against_a1": per_item_table(primary["A2"], primary["A1"]),
            "gate": gate,
            "standard": standard,
            "blocks_p1_p2": _p_blocks(scored, draws),
            "wall_clock": {name: item_times(blocks[name]) for name in blocks},
        },
        "reading": {"reliability": reliability, "used": reading is not None},
        "decision": decision,
        "per_item": {arm: primary[arm] for arm in common.ARMS},
        "rules": {
            "bootstrap": {"draws": draws, "seed": common.BOOT_SEED, "strata": "X, Y, Z"},
            "error_items": T.ERROR_ITEMS,
            "section1": SECTION1,
            "practice_pinned": practice_pinned,
        },
    }


def _gate_view(p: dict[str, Any]) -> dict[str, Any]:
    """An item as the frozen ``gate_layer`` reads it."""
    return {**p, "artefact": p["item"]}


def _p_blocks(
    scored: dict[str, dict[str, list[dict[str, Any]]]], draws: int
) -> dict[str, Any] | None:
    """§6.4 item 10: blocks p1 and p2, never deciding."""
    if "p1" not in scored or "p2" not in scored:
        return None
    out: dict[str, Any] = {
        "label": "the sheet together with tree and day, not the sheet alone",
        "decides": False,
    }
    for arm in common.ARMS:
        items = scored["p1"][arm] + scored["p2"][arm]
        out[arm] = arm_figures(items, "R_common", draws, None)
    published = {}
    for name in ("a-fresh", "b-fresh"):
        path = common.REPO / "experiments" / "R-PG-02" / "evidence" / f"rows_{name}.jsonl"
        rows = {r["artefact"]: r for r in T.read_lines(path)}
        published[name] = rows
    per_item = []
    for arm, other in (("A1", "a-fresh"), ("B", "b-fresh"), ("A2", "a-fresh")):
        for p in scored["p1"][arm] + scored["p2"][arm]:
            r = published[other].get(p["item"])
            if r is None:
                continue
            per_item.append(
                {
                    "arm": arm,
                    "against": other,
                    "item": p["item"],
                    "review": [r["reviewer_verdict"], p["review"]],
                    "twin_review": [r["control_reviewer_verdict"], p["twin_review"]],
                }
            )
    out["per_item_against_r_pg_02"] = per_item
    return out


def main(argv: list[str] | None = None) -> int:
    """Write the tally; print its sha256 and counts only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--sets", type=Path, required=True)
    parser.add_argument("--practice", action="append", default=[])
    parser.add_argument("--reading", type=Path)
    parser.add_argument("--root", action="append", default=[], help="<arm>:<block>=<scratch>")
    parser.add_argument("--draws", type=int, default=common.BOOT_DRAWS)
    parser.add_argument("--fills", type=Path, help="a fills record (else master's)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--practice-unpinned", action="store_true", help="test fixtures only")
    parser.add_argument("--any-count", action="store_true", help="test fixtures only")
    parser.add_argument("--tuning", type=Path, help="a test's tuning set; with --practice-unpinned")
    args = parser.parse_args(argv)
    if args.tuning is not None and not args.practice_unpinned:
        parser.error("--tuning names a test's tuning set, with --practice-unpinned only")
    if args.out.exists():
        print(json.dumps({"refused": "the output exists; a tally is never written over"}))
        return 1
    practice = {}
    for spec in args.practice:
        label, _, path = spec.partition("=")
        practice[label] = Path(path).resolve()
    scratch: dict[str, dict[str, Path]] = {}
    for spec in args.root:
        head, _, path = spec.partition("=")
        arm, _, block = head.partition(":")
        if arm not in common.ARMS or block not in common.BLOCKS:
            parser.error(f"--root takes <arm>:<block>=<dir>, not {spec!r}")
        scratch.setdefault(arm, {})[block] = Path(path).resolve()
    try:
        fills = (
            common.fills_from(args.fills.read_text())
            if args.fills is not None
            else common.fills_on(common.REPO, "origin/master")
        )
        test = args.practice_unpinned or args.any_count
        if not test:
            common.need_fill(fills, "sets")
        found = tally(
            args.records.resolve(),
            args.sets.resolve(),
            practice,
            args.reading,
            scratch,
            args.draws,
            practice_pinned=not args.practice_unpinned,
            fills=fills or None,
            any_count=args.any_count,
            tuning=args.tuning,
        )
    except (RefusedError, TallyError, common.RefusedError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    if args.practice_unpinned or args.any_count:
        found["label"] = "A TEST ON FIXTURES: never a result"
    text = json.dumps(found, indent=1, sort_keys=True, default=list) + "\n"
    args.out.write_text(text)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "sha256": common.sha256_bytes(text.encode()),
                "blocks": sorted(found["blocks"]),
                "not_run": sorted(found["not_run"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
