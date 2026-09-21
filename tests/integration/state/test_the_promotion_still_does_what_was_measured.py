"""The promoted store replays the frozen workload and still behaves as measured.

Correctness is asserted hard: every mandated rejection rejected, every legal
write accepted, nothing mutated by a rejection, no rejection for the wrong
reason. Those counts are deterministic and must match the published ones exactly.

Latency is asserted against the **published** figures, because that is what the
criterion was frozen against and a frozen criterion is scored as written. It is a
clock assertion, which this suite otherwise avoids, and it is here deliberately:
the criterion is about the clock. It carries the caveat that goes with any such
assertion — a heavily loaded machine can fail it without anything having
regressed — which is one reason it is excluded from the routine run.

**The published figure is not the number that tells you whether the promotion
cost anything.** It decayed: the identical frozen code measured 0.427 ms for the
change-list percentile when published, 0.287 ms the next day, and lower again
since. A bound of twice the first would let a replacement two and a half times
slower than what it replaces sit comfortably inside it. The number that answers
the real question is the same-day control — the frozen store replayed on the same
machine in the same session — and it is produced by ``replay_runner.py`` and
reported beside this, rather than being asserted here where a threshold for it
would be a threshold nobody froze.
"""

from __future__ import annotations

import statistics

import pytest
from replay_runner import (
    BOUND_FACTOR,
    PUBLISHED_C2_P95_MS,
    PUBLISHED_C3_P95_MS,
    SEEDS,
    one_run,
)

from physgate.state.store import Store

pytestmark = pytest.mark.integration

#: Totals across the five seeds, from the published correctness table.
PUBLISHED_C1 = {
    "cross_role_attempted": 750,
    "cross_role_rejected": 750,
    "interface_attempted": 100,
    "interface_rejected": 100,
    "missing_unit_attempted": 250,
    "missing_unit_rejected": 250,
    "legal_attempted": 3900,
    "legal_accepted": 3900,
    "creates_attempted": 1000,
    "creates_accepted": 1000,
    "rollbacks_attempted": 150,
    "rollbacks_completed": 150,
    "rejected_writes_that_mutated_the_graph": 0,
    "wrong_rejection_reason": 0,
}


@pytest.fixture(scope="module")
def promoted_runs() -> list[dict[str, object]]:
    """One replay of each seed against the promoted store."""
    return [one_run(Store, seed) for seed in SEEDS]


def test_correctness_matches_the_published_table_exactly(
    promoted_runs: list[dict[str, object]],
) -> None:
    totals: dict[str, int] = {}
    for run in promoted_runs:
        counters = run["c1"]
        assert isinstance(counters, dict)
        for key, value in counters.items():
            totals[key] = totals.get(key, 0) + value

    assert totals, "the replay produced no counters at all"
    assert totals == PUBLISHED_C1


def test_no_seed_reported_a_failure(promoted_runs: list[dict[str, object]]) -> None:
    for run in promoted_runs:
        assert run["failure_count"] == 0, run["failures"]


def test_every_seed_replayed_the_whole_workload(
    promoted_runs: list[dict[str, object]],
) -> None:
    """A replay that stopped early would make the counters above meaningless."""
    for run in promoted_runs:
        counts = run["workload_counts"]
        assert isinstance(counts, dict)
        assert counts["nodes"] == 200
        assert counts["interface_nodes"] == 50
        assert counts["writes"] == 1000


def test_the_change_list_percentile_is_inside_the_published_bound(
    promoted_runs: list[dict[str, object]],
) -> None:
    per_seed = [run["c2_diff_ms"]["p95"] for run in promoted_runs]  # type: ignore[index]
    mean = statistics.mean(per_seed)
    assert mean <= BOUND_FACTOR * PUBLISHED_C2_P95_MS, (
        f"change-list p95 mean {mean:.4f} ms exceeds {BOUND_FACTOR} x {PUBLISHED_C2_P95_MS} ms"
    )


def test_the_traversal_percentile_is_inside_the_published_bound(
    promoted_runs: list[dict[str, object]],
) -> None:
    per_seed = [run["c3_traverse_ms"]["p95"] for run in promoted_runs]  # type: ignore[index]
    mean = statistics.mean(per_seed)
    assert mean <= BOUND_FACTOR * PUBLISHED_C3_P95_MS, (
        f"traversal p95 mean {mean:.3f} ms exceeds {BOUND_FACTOR} x {PUBLISHED_C3_P95_MS} ms"
    )


def test_the_percentiles_were_taken_from_the_sample_sizes_that_were_published(
    promoted_runs: list[dict[str, object]],
) -> None:
    """A percentile over the wrong number of samples is a different percentile."""
    for run in promoted_runs:
        assert run["c2_diff_ms"]["n"] == 1000  # type: ignore[index]
        assert run["c3_traverse_ms"]["n"] == 100  # type: ignore[index]
