"""R-LAW-01, CRITERIA.md §6: the calibration slice, and the bank rule after round 1.

Usage (from the repository root):

    python -I experiments/R-LAW-01/law_slice.py draw <work dir>
    python -I experiments/R-LAW-01/law_slice.py bank <work dir> <prompts out dir>

- ``draw``: before any coding, with ``random.Random(23)``: error classes sorted by name and pairs
  by id; in the fresh set one pair of each class, then in the practice set two classes drawn with
  ``sample(classes, 2)`` and one pair of each, in the order drawn; a pair is eligible if it has at
  least one finding line. Refused unless the sets' error classes are the frozen four
  (:data:`CLASSES`) and :data:`FRESH_PER_CLASS` is the one pair the draw takes. Writes
  ``slice.json``; prints the six ids and the slice's line and flaw counts (the "Slice filled"
  fact).
- ``bank``: after calibration round 1, counts the slice lines on which coder 1's and coder 2's
  codes after §5.5 form each unordered pair, takes every bank item of Appendix D whose pair has 2
  or more, and writes the prompts of version 1 (or says there is no round 2). No person chooses.
  Prints the counts per pair and the items taken: the slice is the one part a person may read.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402
import law_packets as P  # noqa: E402

SEED = 23
FRESH_PER_CLASS = 1
PRACTICE_CLASSES = 2
BANK_BAR = 2
CLASSES = ("equilibrium", "magnitude", "propagation", "unit")


def draw(lines: list[dict[str, Any]], sets: dict[str, X.SetData]) -> dict[str, list[str]]:
    rng = random.Random(SEED)
    with_lines = {(x["set"], x["pair"]) for x in lines}

    def eligible(st: str, cls: str) -> list[str]:
        found = sorted(
            p
            for p, a in sets[st].artefacts.items()
            if a["error_class"] == cls and (st, p) in with_lines
        )
        if not found:
            raise X.Refused(f"no eligible {st} pair of class {cls}: the slice cannot be drawn")
        return found

    classes = sorted({a["error_class"] for sd in sets.values() for a in sd.artefacts.values()})
    # Held to the frozen draw before the generator is used: a fifth or misspelled class, or
    # another number per class, would change the seeded draw silently, so it is refused.
    if FRESH_PER_CLASS != 1:
        raise X.Refused("the draw takes one fresh pair per class (one rng.choice); no other number")
    if tuple(classes) != CLASSES:
        raise X.Refused(f"the sets' error classes {classes} are not the frozen {list(CLASSES)}")
    out: dict[str, list[str]] = {"fresh": [], "practice": []}
    for cls in classes:
        out["fresh"].append(rng.choice(eligible("fresh", cls)))
    for cls in rng.sample(classes, PRACTICE_CLASSES):
        out["practice"].append(rng.choice(eligible("practice", cls)))
    return out


def slice_counts(
    pairs: dict[str, list[str]], lines: list[dict[str, Any]], flaws: list[dict[str, Any]]
) -> dict[str, Any]:
    in_slice = {(s, p) for s, ps in pairs.items() for p in ps}
    sl = {x["line_id"] for x in lines if (x["set"], x["pair"]) in in_slice}
    spanning = [f for f in flaws if (set(f["lines"]) & sl) and (set(f["lines"]) - sl)]
    return {
        "slice_lines": len(sl),
        "measured_lines": len(lines) - len(sl),
        "flaws_touching_slice": sum(1 for f in flaws if set(f["lines"]) & sl),
        "measured_flaws": sum(1 for f in flaws if set(f["lines"]) - sl),
        "base_flaws_spanning_slice_and_measured": sum(1 for f in spanning if f["base"]),
        "flaws_spanning_slice_and_measured": len(spanning),
    }


def disagreements(codes: list[dict[str, Any]], step: str) -> dict[str, int]:
    """Slice lines per unordered pair of the two coders' codes after §5.5 (differing only)."""
    by: dict[str, dict[str, Any]] = {}
    for r in codes:
        if r["step"] == step and r["who"] in ("c1", "c2"):
            by.setdefault(r["line_id"], {})[r["who"]] = r["code"]
    c: Counter[str] = Counter()
    for w in by.values():
        a, b = w.get("c1"), w.get("c2")
        if a is None or b is None or a == b:
            continue
        c["–".join(sorted((a, b)))] += 1
    return dict(c)


def taken(counts: dict[str, int], items: dict[str, dict[str, Any]]) -> list[str]:
    """Every bank item whose unordered pair has at least two disagreements, in bank order."""
    return [i for i in P.BANK_ORDER if counts.get("–".join(items[i]["pair"]), 0) >= BANK_BAR]


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["draw"] and len(argv) == 2:
            work = Path(argv[1])
            if (work / "slice.json").exists():
                raise X.Refused("slice.json exists; the slice is drawn once")
            lines = X.read_jsonl(work / "lines.jsonl")
            flaws = X.read_jsonl(work / "flaws.jsonl")
            sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
            pairs = draw(lines, sets)
            out = {"seed": SEED, "pairs": pairs, **slice_counts(pairs, lines, flaws)}
            (work / "slice.json").write_text(json.dumps(out, indent=1, sort_keys=True))
            print(json.dumps(out, sort_keys=True))
            return 0
        if argv[:1] == ["bank"] and len(argv) == 3:
            work, out_dir = Path(argv[1]), Path(argv[2])
            codes = X.read_jsonl(work / "codes.jsonl")
            counts = disagreements(codes, "slice-r1")
            items = P.bank(P.criteria_text())
            take = taken(counts, items)
            res: dict[str, Any] = {"disagreements": counts, "taken": take, "round_2": bool(take)}
            if take:
                res["prompts"] = P.write_prompts(out_dir, tuple(take))
            (work / "bank.json").write_text(json.dumps(res, indent=1, sort_keys=True))
            print(json.dumps(res, sort_keys=True))
            return 0
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
