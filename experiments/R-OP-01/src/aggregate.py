"""Mean and standard deviation across seeds. Shared scaffolding."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

METRICS = Path(__file__).resolve().parent.parent / "metrics"
IMPLS = ("baseline", "openpersona")
SEEDS = (1, 2, 3, 4, 5)


def _ms(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "sd": None, "per_seed": []}
    return {
        "mean": round(statistics.fmean(values), 4),
        "sd": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "per_seed": [round(v, 4) for v in values],
    }


def main() -> None:
    summary: dict = {"impls": {}}
    for impl in IMPLS:
        runs = [json.loads((METRICS / f"{impl}-seed{s}.json").read_text()) for s in SEEDS]
        crashes = [json.loads((METRICS / f"{impl}-seed{s}-crash.json").read_text()) for s in SEEDS]
        c1_total: dict[str, int] = {}
        for r in runs:
            for k, v in r["c1"].items():
                c1_total[k] = c1_total.get(k, 0) + v
        summary["impls"][impl] = {
            "c1_totals_over_5_seeds": c1_total,
            "c1_failure_count": sum(r["failure_count"] for r in runs),
            "c1_perfect": (
                sum(r["failure_count"] for r in runs) == 0
                and c1_total["cross_role_attempted"] == c1_total["cross_role_rejected"]
                and c1_total["interface_attempted"] == c1_total["interface_rejected"]
                and c1_total["missing_unit_attempted"] == c1_total["missing_unit_rejected"]
                and c1_total["legal_attempted"] == c1_total["legal_accepted"]
                and c1_total["rejected_writes_that_mutated_the_graph"] == 0
            ),
            "c2_diff_p50_ms": _ms([r["c2_diff_ms"]["p50"] for r in runs]),
            "c2_diff_p95_ms": _ms([r["c2_diff_ms"]["p95"] for r in runs]),
            "c3_traverse_p50_ms": _ms([r["c3_traverse_ms"]["p50"] for r in runs]),
            "c3_traverse_p95_ms": _ms([r["c3_traverse_ms"]["p95"] for r in runs]),
            "write_p50_ms": _ms([r["write_ms"]["p50"] for r in runs]),
            "write_p95_ms": _ms([r["write_ms"]["p95"] for r in runs]),
            "rollback_p50_ms": _ms([r["rollback_ms"]["p50"] for r in runs]),
            "wall_s": _ms([r["wall_s"] for r in runs]),
            "c4_consistent_seeds": sum(1 for c in crashes if c.get("consistent")),
            "c4_open_and_recover_ms": _ms(
                [c["open_and_recover_ms"] for c in crashes if "open_and_recover_ms" in c]
            ),
            "c4_verify_ms": _ms([c["verify_ms"] for c in crashes if "verify_ms" in c]),
            "c4_acknowledged_ops": _ms(
                [float(c["acknowledged_ops"]) for c in crashes if c.get("acknowledged_ops")]
            ),
            "c4_aborted_seeds": [
                c["seed"] for c in crashes if "open_and_recover_ms" not in c
            ],
            "c4_lost_after_last_ack": [c.get("lost_after_last_ack") for c in crashes],
            "c4_unacknowledged_extra": [c.get("unacknowledged_extra") for c in crashes],
            "c4_problems": [p for c in crashes for p in c.get("problems", [])][:10],
        }

    base = summary["impls"]["baseline"]
    op = summary["impls"]["openpersona"]
    summary["ratios_openpersona_over_baseline"] = {
        "c2_diff_p95": round(op["c2_diff_p95_ms"]["mean"] / base["c2_diff_p95_ms"]["mean"], 2),
        "c3_traverse_p95": round(
            op["c3_traverse_p95_ms"]["mean"] / base["c3_traverse_p95_ms"]["mean"], 2
        ),
        "write_p50": round(op["write_p50_ms"]["mean"] / base["write_p50_ms"]["mean"], 2),
    }
    summary["c5"] = json.loads((METRICS / "c5_loc.json").read_text())
    (METRICS / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["ratios_openpersona_over_baseline"], indent=2))


if __name__ == "__main__":
    main()
