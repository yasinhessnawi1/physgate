"""The statistics both gaps are read with: Wilson intervals and a task-cluster bootstrap.

A rate is printed with its Wilson 95 % interval and with a percentile interval from a
bootstrap that resamples tasks whole, because the trials of one task are not independent.
A gap between two tiers resamples each tier's tasks on its own. Each bootstrap draws from
its own generator, seeded by a seed and a label, so the same inputs always give the same
interval in every process.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence

#: The two-sided 95 % normal quantile, ``NormalDist().inv_cdf(0.975)``.
Z95 = 1.959963984540054


def wilson(passed: int, n: int) -> tuple[float, float]:
    """The Wilson score 95 % interval of ``passed`` in ``n``, as fractions.

    Raises:
        ValueError: ``n`` is not positive or ``passed`` is outside ``[0, n]``.
    """
    if n <= 0 or not 0 <= passed <= n:
        msg = f"no interval for {passed} of {n}"
        raise ValueError(msg)
    p = passed / n
    z2 = Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _generator(seed: int, label: str) -> random.Random:
    # A string seed is hashed with SHA-512, so it is the same in every process.
    return random.Random(f"{seed}:{label}")


def _interval(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    count = len(ordered)
    return ordered[math.floor(0.025 * count)], ordered[math.ceil(0.975 * count) - 1]


def cluster_bootstrap(
    groups: Sequence[Sequence[float]],
    statistic: Callable[[Sequence[Sequence[float]]], float],
    *,
    seed: int,
    label: str,
    draws: int,
) -> tuple[float, float]:
    """A 95 % percentile interval of ``statistic``, each group's tasks resampled whole.

    ``groups`` holds one list of per-task values per independent sample (one for a rate or
    a paired difference, two for a gap between tiers); each is resampled with replacement
    at its own size, from one generator seeded by ``seed`` and ``label``.
    """
    rng = _generator(seed, label)
    values = []
    for _ in range(draws):
        sample = [[group[rng.randrange(len(group))] for _ in group] for group in groups]
        values.append(statistic(sample))
    return _interval(values)


def _mean_of_first(sample: Sequence[Sequence[float]]) -> float:
    return statistics.fmean(sample[0])


def _gap(sample: Sequence[Sequence[float]]) -> float:
    return statistics.fmean(sample[0]) - statistics.fmean(sample[1])
