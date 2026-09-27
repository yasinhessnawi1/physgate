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

The runs measured together must be repeats of one configuration: their
``run.json`` files equal in everything but the run id, so the seed, the brief,
every pinned model, the binary, the endpoint and the harness commit are shared.
``measure_variance`` reads recorded runs; ``repeat_run`` makes the repeats as
reruns of one recorded run, and measures them with it.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.observe.exceptions import VarianceError
from physgate.evaluation.observe.manifest import read_manifest, read_run_events
from physgate.evaluation.observe.rerun import Driver, rerun
from physgate.orchestrator.run_config import RunConfig

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


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RunDecisions(_Frozen):
    """One run's ordering and merge decisions, with the manifest they come from."""

    manifest_id: str
    run_id: str
    dispatch: tuple[tuple[str, int], ...]
    #: Each attempt's end, keyed ``<subtask>/<attempt>``.
    ends: dict[str, End]


class VarianceReport(_Frozen):
    """The two numbers over n runs of one configuration, with every run they were read from."""

    n: Annotated[int, Field(ge=1)]
    runs: tuple[RunDecisions, ...]
    #: As an exact fraction, e.g. ``"2/3"``; ``None`` below two runs.
    ordering_variance: str | None
    merge_decision_variance: str | None
    ordering_variance_value: float | None
    merge_decision_variance_value: float | None
    distinct_orderings: int
    distinct_decisions: int


def _group(config: RunConfig) -> dict[str, Any]:
    group: dict[str, Any] = config.model_dump(mode="json", exclude={"run_id"})
    return group


def measure_variance(run_dirs: Sequence[Path]) -> VarianceReport:
    """Ordering and merge-decision variance over runs of one configuration.

    Raises:
        VarianceError: no run was given, one was given twice, or two runs differ in
            anything but their run id: they are not repeats of one configuration.
        ManifestError: a directory does not hold a complete run.
    """
    if not run_dirs:
        msg = "a variance needs at least one run"
        raise VarianceError(msg)
    runs: list[RunDecisions] = []
    first: dict[str, Any] | None = None
    for run_dir in run_dirs:
        manifest = read_manifest(run_dir)
        group = _group(manifest.config)
        if first is None:
            first = group
        elif group != first:
            changed = sorted(k for k in first if first[k] != group.get(k))
            msg = "the runs are not repeats of one configuration"
            raise VarianceError(msg, run_id=manifest.config.run_id, changed=",".join(changed))
        if any(r.manifest_id == manifest.manifest_id for r in runs):
            msg = "a run is given twice"
            raise VarianceError(msg, manifest_id=manifest.manifest_id)
        events = [e.model_dump(mode="json") for e in read_run_events(run_dir)]
        runs.append(
            RunDecisions(
                manifest_id=manifest.manifest_id,
                run_id=manifest.config.run_id,
                dispatch=dispatch_order(events),
                ends={f"{s}/{a}": end for (s, a), end in attempt_ends(events).items()},
            )
        )
    orders = ordering_variance([r.dispatch for r in runs])
    ends = merge_decision_variance(
        [
            {(k.rsplit("/", 1)[0], int(k.rsplit("/", 1)[1])): v for k, v in r.ends.items()}
            for r in runs
        ]
    )
    return VarianceReport(
        n=len(runs),
        runs=tuple(runs),
        ordering_variance=None if orders is None else str(orders),
        merge_decision_variance=None if ends is None else str(ends),
        ordering_variance_value=None if orders is None else float(orders),
        merge_decision_variance_value=None if ends is None else float(ends),
        distinct_orderings=len({r.dispatch for r in runs}),
        distinct_decisions=len({tuple(sorted(r.ends.items())) for r in runs}),
    )


def repeat_run(
    recorded: Path,
    *,
    n: int,
    brief: Path,
    target: Path,
    install: Path,
    runs_dir: Path,
    driver: Driver | None = None,
) -> VarianceReport:
    """Make the recorded run ``n - 1`` more times and measure the variance over all ``n``.

    Each repeat is a rerun, under ``<run id>-repeat-<k>`` in ``runs_dir``, so it is
    refused on anything a rerun is refused on: the seed and brief are the recorded
    run's by construction.

    Raises:
        VarianceError: ``n`` is below two.
        RerunError: a repeat could not be made from the recorded run.
    """
    if n < 2:
        msg = "a variance needs at least two runs"
        raise VarianceError(msg, n=str(n))
    base = read_manifest(recorded).config.run_id
    repeats = []
    for k in range(1, n):
        run_id = f"{base}-repeat-{k}"
        rerun(
            recorded,
            brief=brief,
            run_id=run_id,
            run_dir=Path(runs_dir) / run_id,
            target=target,
            install=install,
            driver=driver,
        )
        repeats.append(Path(runs_dir) / run_id)
    return measure_variance([Path(recorded), *repeats])
