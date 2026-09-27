"""Ordering variance and merge-decision variance across repeated runs of one brief and seed.

ARCH-145 asks for the variance in task ordering and merge decisions across
repeated runs with the same seed and brief, as a number every run has. It is the
orchestrator ablation's primary measurement: under the deterministic binding
both numbers are expected to be zero, and that zero is the baseline the
model-in-loop binding is measured against. The definitions below were fixed
before any run was measured with them.

**A run's ordering** is its dispatch sequence: the subtask and attempt of every
``spawn`` stage line, in log order. It is who was sent to work, and when, which
is what an orchestrator decides.

**A run's merge decisions** are how each attempt it dispatched ended:

- ``merged``, when the attempt was merged into the run branch;
- ``rejected``, when the gate, the reviewer or a check refused it;
- ``infrastructure``, when its session ended on an infrastructure cause and
  nothing decided on it;
- ``open``, when the run stopped before anything decided on it.

**The two numbers**, over the n runs of one configuration, are means over all
n(n-1)/2 pairs of runs:

- **ordering variance**: the edit distance between the two dispatch sequences
  (insertions, deletions and substitutions, each counting one), divided by the
  longer sequence's length; 0 when both are empty;
- **merge-decision variance**: over the attempts either run dispatched, the
  share on which the two runs' ends differ, an attempt one run never dispatched
  counting as a difference; 0 when neither dispatched anything.

Each is 0 exactly when every run agrees with every other, and at most 1. With
fewer than two runs there is no pair, and the number is ``None``, never 0.

Both are exact rationals, computed as fractions and reported as fractions and
as floats.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from fractions import Fraction
from itertools import combinations
from typing import Any, Literal

End = Literal["merged", "rejected", "infrastructure", "open"]
Attempt = tuple[str, int]


def dispatch_order(events: Iterable[Mapping[str, Any]]) -> tuple[Attempt, ...]:
    """A run's ordering: the subtask and attempt of every spawn, in log order."""
    return tuple(
        (str(e["subtask_id"]), int(e["attempt"]))
        for e in events
        if e.get("kind") == "stage_entered" and e.get("stage") == "spawn"
    )


def attempt_ends(events: Iterable[Mapping[str, Any]]) -> dict[Attempt, End]:
    """A run's merge decisions: how each attempt it dispatched ended."""
    ends: dict[Attempt, End] = {}
    for e in events:
        kind = e.get("kind")
        if kind == "stage_entered" and e.get("stage") == "spawn":
            # A fresh session for the same attempt (an infrastructure retry, or a
            # resume) starts it over: what ended it before decided nothing.
            ends[(str(e["subtask_id"]), int(e["attempt"]))] = "open"
            continue
        key = (str(e.get("subtask_id")), int(e.get("attempt") or 0))
        if key not in ends:
            continue
        if kind == "merged":
            ends[key] = "merged"
        elif kind == "attempt_rejected":
            ends[key] = "rejected"
        elif kind == "session_ended" and e.get("outcome") == "infrastructure":
            ends[key] = "infrastructure"
    return ends


def edit_distance(a: Sequence[Hashable], b: Sequence[Hashable]) -> int:
    """Insertions, deletions and substitutions that turn ``a`` into ``b``, each counting one."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def ordering_distance(a: Sequence[Attempt], b: Sequence[Attempt]) -> Fraction:
    """How far apart two dispatch sequences are, from 0 (equal) to 1."""
    longer = max(len(a), len(b))
    return Fraction(edit_distance(a, b), longer) if longer else Fraction(0)


def decision_distance(a: Mapping[Attempt, End], b: Mapping[Attempt, End]) -> Fraction:
    """The share of the attempts either run dispatched on which their ends differ."""
    attempts = a.keys() | b.keys()
    if not attempts:
        return Fraction(0)
    differ = sum(1 for k in attempts if a.get(k) != b.get(k))
    return Fraction(differ, len(attempts))


def ordering_variance(orders: Sequence[Sequence[Attempt]]) -> Fraction | None:
    """The mean ordering distance over every pair of runs; ``None`` below two runs."""
    pairs = list(combinations(orders, 2))
    if not pairs:
        return None
    return sum((ordering_distance(a, b) for a, b in pairs), Fraction(0)) / len(pairs)


def merge_decision_variance(ends: Sequence[Mapping[Attempt, End]]) -> Fraction | None:
    """The mean decision distance over every pair of runs; ``None`` below two runs."""
    pairs = list(combinations(ends, 2))
    if not pairs:
        return None
    return sum((decision_distance(a, b) for a, b in pairs), Fraction(0)) / len(pairs)
