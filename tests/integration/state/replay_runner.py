"""Replay the frozen workload against both stores, interleaved, and record it.

The regression question is whether promoting the measured store changed what was
measured. There are two ways to ask it and they give different answers:

- against the **published figure**, which is what the criterion was frozen
  against and is scored exactly as written;
- against a **same-day control** — the frozen store replayed on this machine, in
  this session, alternating seed by seed with the promoted one.

The control exists because the published figure decayed. The identical frozen
code measured 0.427 ms for the change-list percentile when it was published,
0.287 ms the next day, and lower again since. A bound written as twice the first
of those permits a replacement two and a half times slower than what it replaces
while looking comfortably inside it. Scoring the criterion as written is right;
reporting only that number is not.

Runs alternate arm by arm within each seed so that a machine warming up, or a
background process arriving, lands on both arms rather than on one.

Usage: ``python replay_runner.py <output-directory> [reps]``
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import generator
import harness

HERE = Path(__file__).resolve().parent
FROZEN_SRC = HERE.parents[2] / "experiments" / "R-OP-01" / "src"
SEEDS = (1, 2, 3, 4, 5)

#: Published by the store comparison, and what the criterion is scored against.
PUBLISHED_C2_P95_MS = 0.427
PUBLISHED_C3_P95_MS = 45.6
BOUND_FACTOR = 2.0


def _store_factories() -> dict[str, Any]:
    """The two arms. The frozen one is imported from the measured tree, unmodified."""
    sys.path.insert(len(sys.path), str(FROZEN_SRC))

    # The control arm *is* the frozen code, so this reaches into the tree the
    # type checker is deliberately kept out of, at runtime, through a path it
    # cannot follow. One suppression, in the one place that needs it, rather
    # than widening the checker's reach into measured artefacts.
    from baseline_store import BaselineStore  # type: ignore[import-not-found] # noqa: PLC0415

    from physgate.state.store import Store  # noqa: PLC0415

    return {"frozen": BaselineStore, "promoted": Store}


def one_run(factory: Any, seed: int) -> dict[str, Any]:
    """Replay one seed against one store in a fresh directory."""
    root = Path(tempfile.mkdtemp())
    try:
        work = generator.build(seed)
        store = factory(root)
        metrics: dict[str, Any] = harness.run(store, work)
        store.close()
        return metrics
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    """Run every seed against both arms, ``reps`` times, and write the record."""
    out_dir = Path(sys.argv[1])
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    out_dir.mkdir(parents=True, exist_ok=True)
    factories = _store_factories()

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=True
    ).stdout.strip()

    runs: list[dict[str, Any]] = []
    for rep in range(reps):
        for seed in SEEDS:
            for arm, factory in factories.items():
                metrics = one_run(factory, seed)
                metrics["arm"] = arm
                metrics["rep"] = rep
                runs.append(metrics)
                print(
                    f"rep {rep} seed {seed} {arm:<8} "
                    f"c1_failures={metrics['failure_count']} "
                    f"c2_p95={metrics['c2_diff_ms']['p95']:.4f}ms "
                    f"c3_p95={metrics['c3_traverse_ms']['p95']:.3f}ms",
                    flush=True,
                )

    record = {
        "commit": sha,
        "reps": reps,
        "seeds": list(SEEDS),
        "published_c2_p95_ms": PUBLISHED_C2_P95_MS,
        "published_c3_p95_ms": PUBLISHED_C3_P95_MS,
        "bound_factor": BOUND_FACTOR,
        "runs": runs,
    }
    (out_dir / "replay_runs.json").write_text(json.dumps(record, indent=2, default=str))

    print("\n--- per seed, p95 median over reps ---")
    for seed in SEEDS:
        row = {}
        for arm in factories:
            these = [r for r in runs if r["seed"] == seed and r["arm"] == arm]
            row[arm] = (
                statistics.median(r["c2_diff_ms"]["p95"] for r in these),
                statistics.median(r["c3_traverse_ms"]["p95"] for r in these),
            )
        print(
            f"seed {seed}  c2 frozen {row['frozen'][0]:.4f}  promoted {row['promoted'][0]:.4f}"
            f"  ratio {row['promoted'][0] / row['frozen'][0]:.2f}   |"
            f"  c3 frozen {row['frozen'][1]:7.3f}  promoted {row['promoted'][1]:7.3f}"
            f"  ratio {row['promoted'][1] / row['frozen'][1]:.2f}"
        )


if __name__ == "__main__":
    main()
