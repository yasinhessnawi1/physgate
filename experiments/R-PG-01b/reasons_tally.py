"""R-PG-01b, CRITERIA.md §6 and §7 D4: every rejection's class, the two controls and their bars.

Usage, in the run checkout, after the reality sessions (``reasons_sessions.sh``)::

    reasons_tally.py <work dir> <packets dir> <sessions dir> <controls dir>
        <control sessions dir> <ledger> --out <file>

**Verdicts.** Each finding line's verdict and origin is its packet's first try's valid form, else
the retry's; a line with neither is ``missing``, which is neither ``true_flaw`` nor
``not_a_flaw``. Control verdicts are never reality verdicts.

**The counting rule** (§6): one class per review whose outcome is ``fail`` or ``blocked``, the
first that holds:

1. **B**: a ``blocked`` review (listed with its cause; its lines are not adjudicated);
2. **P**: an injected artefact's review that names its error (R-PG-01 §6 item 10, twin condition);
3. **O**: a finding line is ``true_flaw``. **O-introduced**: a ``true_flaw`` line has origin
   ``introduced`` or ``both``; **O-base**: every ``true_flaw`` line is ``already_in_base``; a
   ``true_flaw`` line of origin ``n/a`` alone leaves the review **O-unsplit**, counted apart;
4. **N**: every finding line is ``not_a_flaw``;
5. **U**: the rest (a line ``undecidable`` or ``missing`` and none ``true_flaw``, or no line).

**The controls.** Calibration: a P review is calibrated if one of its error-item lines is
``true_flaw`` with origin ``introduced`` or ``both``; the bar is 70 % of P reviews. Rejection
control: the bar is 70 % of control lines ``not_a_flaw``. Each needs at least 10 cases, else it
is **not checked**. The O/N split is **unreliable** if a checked bar is missed, else **unchecked**
if a control is not checked, else **reliable**.

**Reported** per arm and round, for injected artefacts and twins: B, P, O (split), N and U; the
paired change in N between the arms; the twins' corrected refusal rate (twins in N over 40, with
N + U as its upper bound), D4's figure, labelled when the split is not reliable. Descriptive:
the tagged share of finding lines per arm, and the P reviews' error-item lines judged
``not_a_flaw``. If the ledger's guard voided the reading (``VOID``), §6's counts are not reported
and D4 is not taken (§12).

It writes the output to ``--out`` (never over a file) and prints its sha256 and counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import reasons_packets as P  # noqa: E402

BAR = 0.70
MIN_CASES = 10
CLASSES = ("B", "P", "O-introduced", "O-base", "O-unsplit", "N", "U")


def classify(
    review: dict[str, Any], lines: list[dict[str, Any]], got: dict[str, Any]
) -> str | None:
    """§6's class of one review, or ``None`` if it is no rejection."""
    if review["outcome"] == "blocked":
        return "B"
    if review["outcome"] != "fail":
        return None
    if review["side"] == "injected" and review["named"] is True:
        return "P"
    found = [got.get(x["line_id"]) or {"verdict": "missing", "origin": None} for x in lines]
    verdicts = [v["verdict"] for v in found]
    true = [v for v in found if v["verdict"] == "true_flaw"]
    if true:
        if any(v["origin"] in ("introduced", "both") for v in true):
            return "O-introduced"
        if all(v["origin"] == "already_in_base" for v in true):
            return "O-base"
        return "O-unsplit"
    if lines and all(v == "not_a_flaw" for v in verdicts):
        return "N"
    return "U"


def bar(hit: int, cases: int) -> dict[str, Any]:
    """A control's bar: met, missed, or not checked under 10 cases."""
    if cases < MIN_CASES:
        return {"cases": cases, "hit": hit, "status": "not checked"}
    return {"cases": cases, "hit": hit, "status": "met" if hit / cases >= BAR else "missed"}


def label(calibration: dict[str, Any], rejection: dict[str, Any]) -> str:
    """The O/N split's label."""
    if "missed" in (calibration["status"], rejection["status"]):
        return "unreliable"
    if "not checked" in (calibration["status"], rejection["status"]):
        return "unchecked"
    return "reliable"


def tally(
    work: Path, packets: Path, sessions: Path, controls: Path, control_sessions: Path, ledger: Path
) -> dict[str, Any]:
    """The whole of §6 and D4."""
    ledger_dir = ledger.parent
    total = (
        sum(json.loads(x)["tokens"] for x in ledger.read_text().splitlines() if x.strip())
        if ledger.is_file()
        else 0
    )
    if (ledger_dir / "VOID").exists():
        return {
            "void": True,
            "tokens": total,
            "reading": (
                "void: the token guard was reached; §6's counts are not reported, "
                "and D4 is not taken"
            ),
        }
    lines = C.read_jsonl(work / "lines.jsonl")
    reviews = C.read_jsonl(work / "reviews.jsonl")
    got = P.verdicts(packets, sessions)
    ctl = P.verdicts(controls, control_sessions) if (controls / "key.json").is_file() else {}
    of: dict[tuple[int, str, str, str], list[dict[str, Any]]] = {}
    for x in lines:
        of.setdefault((x["round"], x["arm"], x["side"], x["artefact"]), []).append(x)
    classed: dict[tuple[int, str, str, str], str | None] = {}
    for rv in reviews:
        k = (rv["round"], rv["arm"], rv["side"], rv["artefact"])
        classed[k] = classify(rv, of.get(k, []), got)
    rounds = sorted({k[0] for k in classed})
    per: dict[str, Any] = {}
    for r in rounds:
        for arm in C.ARMS:
            for side in C.SIDES:
                counts = Counter(
                    c for (rr, a, s, _), c in classed.items() if (rr, a, s) == (r, arm, side) and c
                )
                per[f"round {r}, arm {arm}, {side}"] = {c: counts.get(c, 0) for c in CLASSES}
    paired_n: dict[str, Any] = {}
    refusal: dict[str, Any] = {}
    for r in rounds:
        for side in C.SIDES:
            arts = sorted({k[3] for k in classed if k[0] == r and k[2] == side})
            f_only = sum(
                classed.get((r, "F", side, a)) == "N" and classed.get((r, "I", side, a)) != "N"
                for a in arts
            )
            i_only = sum(
                classed.get((r, "I", side, a)) == "N" and classed.get((r, "F", side, a)) != "N"
                for a in arts
            )
            paired_n[f"round {r}, {side}"] = {
                "N in F, not in I": f_only,
                "N in I, not in F": i_only,
            }
        for arm in C.ARMS:
            twins = [c for (rr, a, s, _), c in classed.items() if (rr, a, s) == (r, arm, "twin")]
            n = sum(c == "N" for c in twins)
            u = sum(c == "U" for c in twins)
            refusal[f"round {r}, arm {arm}"] = {
                "N": n,
                "N_plus_U": n + u,
                "of": C.DENOMINATOR,
                "rate": n / C.DENOMINATOR,
                "upper_bound": (n + u) / C.DENOMINATOR,
            }
    # the calibration control: P reviews whose error-item lines include an introduced true flaw
    p_keys = [k for k, c in classed.items() if c == "P"]
    calibrated = 0
    p_not_a_flaw = 0
    for k in p_keys:
        err = [x for x in of.get(k, []) if x["error_item_line"]]
        calibrated += any(
            (got.get(x["line_id"]) or {}).get("verdict") == "true_flaw"
            and (got.get(x["line_id"]) or {}).get("origin") in ("introduced", "both")
            for x in err
        )
        p_not_a_flaw += sum(
            (got.get(x["line_id"]) or {}).get("verdict") == "not_a_flaw" for x in err
        )
    calibration = bar(calibrated, len(p_keys))
    rejection = bar(sum(v["verdict"] == "not_a_flaw" for v in ctl.values()), len(ctl))
    split = label(calibration, rejection)
    tags = {
        arm: {
            "lines": sum(x["arm"] == arm for x in lines),
            "tagged": sum(x["arm"] == arm and x["tag_missing_row"] for x in lines),
        }
        for arm in C.ARMS
    }
    for t in tags.values():
        t["share"] = t["tagged"] / t["lines"] if t["lines"] else None
    mean = {
        arm: sum(refusal[f"round {r}, arm {arm}"]["rate"] for r in rounds) / len(rounds)
        for arm in C.ARMS
    }
    return {
        "void": False,
        "tokens": total,
        "lines": len(lines),
        "lines_with_a_verdict": sum(1 for v in got.values() if v["verdict"] != "missing"),
        "line_verdicts": dict(Counter(v["verdict"] for v in got.values())),
        "classes": per,
        "blocked_listed": [
            {
                "round": rv["round"],
                "arm": rv["arm"],
                "side": rv["side"],
                "artefact": rv["artefact"],
                "cause": rv["cause"],
            }
            for rv in reviews
            if rv["outcome"] == "blocked"
        ],
        "paired_change_in_N": paired_n,
        "twins_corrected_refusal_rate": refusal,
        "controls": {"calibration": calibration, "rejection": rejection},
        "split": split,
        "D4": {
            "arm_F_rate_mean_over_rounds": mean["F"],
            "arm_I_rate_mean_over_rounds": mean["I"],
            "label": None if split == "reliable" else f"the O/N split is {split}",
        },
        "descriptive": {
            "tagged_share_per_arm": tags,
            "P_error_item_lines_not_a_flaw": p_not_a_flaw,
        },
        "per_line": [
            {"line_id": lid, **{k: v for k, v in got[lid].items() if k != "packet"}}
            for lid in sorted(got)
        ],
        "per_review": [
            {"round": k[0], "arm": k[1], "side": k[2], "artefact": k[3], "class": c}
            for k, c in sorted(classed.items())
            if c
        ],
        "control_lines": {lid: v["verdict"] for lid, v in sorted(ctl.items())},
    }


def main(argv: list[str] | None = None) -> int:
    """Write §6's output; print its sha256 and counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("work", type=Path)
    parser.add_argument("packets", type=Path)
    parser.add_argument("sessions", type=Path)
    parser.add_argument("controls", type=Path)
    parser.add_argument("control_sessions", type=Path)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; an output is never written over")
    found = tally(
        args.work, args.packets, args.sessions, args.controls, args.control_sessions, args.ledger
    )
    text = json.dumps(found, indent=1, sort_keys=True) + "\n"
    args.out.write_text(text)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "sha256": C.sha256_bytes(text.encode()),
                "lines": found.get("lines"),
                "tokens": found["tokens"],
                "void": found["void"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
