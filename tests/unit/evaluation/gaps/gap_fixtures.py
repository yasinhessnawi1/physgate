"""Stand-ins for the gaps rows: a store of one version, harness runs on its tasks, trial records.

The store is the baseline round's stand-in (twenty-four fixture tasks split into one version).
A harness run is laid out as the loop leaves one, its first line naming the configuration beside
it, so its manifest id reads. A trial record is the trial layer's: one per run, by task and trial.
Protected trial records lie beneath the role's withheld root, as the trial layer must keep them.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import (  # noqa: E402
    StandInStore,
    api,
    config,
    harness_run,
    stand_in_store,
)

from physgate.evaluation.tiers.store import withheld_root  # noqa: E402
from physgate.evaluation.tiers.task import Task  # noqa: E402
from physgate.orchestrator.events import EventLog, RunStarted  # noqa: E402

__all__ = [
    "Measured",
    "StandInStore",
    "api",
    "config",
    "design",
    "measured",
    "record",
    "run_on",
    "stand_in_store",
    "write_records",
    "write_runs",
]

#: Which (task index, trial) pairs pass, per tier: the visible tier is easier.
PASSES: dict[str, Callable[[int, int], bool]] = {
    "visible": lambda i, t: (i + t) % 3 != 2,
    "validation": lambda i, t: (i + t) % 2 == 0,
    "held_out": lambda i, t: i == 0 and t == 0,
}


def run_on(root: Path, task: Task, made: StandInStore, **changes: Any) -> Path:  # noqa: ANN401
    """A harness run on ``task`` whose first line names its configuration, as the loop's does."""
    run_dir = harness_run(root, task, made, **changes)
    digest = hashlib.sha256((run_dir / "run.json").read_bytes()).hexdigest()
    events = run_dir / "events.jsonl"
    rest = events.read_text().splitlines(keepends=True)[1:]
    events.unlink()
    log = EventLog(events, run_id="r", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256=digest))
    log.close()
    with events.open("a") as out:
        out.writelines(rest)
    return run_dir


def record(task: str, trial: int, outcome: str, *, arm: str = "harness") -> dict[str, Any]:
    """One trial record of the trial layer, a control trial of a harness arm."""
    body: dict[str, Any] = {
        "suite": "s",
        "task": task,
        "arm": arm,
        "trial": trial,
        "outcome": outcome,
        "cost": {"tokens": 1000, "usd": "1.00", "basis": "list_price", "lower_bound": False},
        "wall_clock_s": 60.0,
        "control": {"no_gain_crossover": False},
    }
    if arm != "raw":
        body["gate"] = {"checks_run": 1, "artefacts_caught": 0, "caught_after_reviewer_passed": 0}
        body["review"] = {"reviews": 1, "failed": 0, "blocked": 0}
    return body


def write_runs(path: Path, runs: Sequence[tuple[Path, int]]) -> Path:
    """The run set naming each run by its directory and trial number."""
    trials = [{"run_dir": str(r), "trial": t} for r, t in runs]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": 1, "trials": trials}))
    return path


def write_records(path: Path, records: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


@dataclass(frozen=True)
class Measured:
    """One tier's runs and records, laid out: the run set's and the records' paths."""

    runs: Path
    trials: Path
    run_dirs: tuple[Path, ...]
    tasks: tuple[Task, ...]


def _as_run(made: StandInStore) -> list[str]:
    """Each root's digest as a run made now records it, the role's withheld root among them.

    Nothing is pinned: every write beneath the withheld root changes its digest, and runs are
    compared on the protected tiers' digests only, so runs made at any point compare.
    """
    from physgate.evaluation.tiers.heldout import tier_digest

    return [tier_digest(Path(root)) for root in made.held_out]


def measured(
    made: StandInStore,
    tier: str,
    where: Path,
    *,
    tasks: int = 2,
    trials: int = 2,
    outcome: Callable[[int, int], bool] | None = None,
    **changes: Any,  # noqa: ANN401
) -> Measured:
    """``tasks`` of ``tier``, each run ``trials`` times, and the records of those runs.

    Protected records and run sets lie beneath the role's withheld root; visible ones in
    ``where``.
    """
    passes = PASSES[tier] if outcome is None else outcome
    changes.setdefault("held_out_sha256", _as_run(made))
    chosen = made.tasks[tier][:tasks]
    entries: list[tuple[Path, int]] = []
    records = []
    for i, task in enumerate(chosen):
        for t in range(trials):
            run_dir = run_on(where / "runs", task, made, **changes)
            entries.append((run_dir, t))
            records.append(record(task.id, t, "pass" if passes(i, t) else "fail"))
    place = (
        where / tier
        if tier == "visible"
        else withheld_root(made.store, "control") / "trials" / where.name / tier
    )
    return Measured(
        write_runs(place / "runs.json", entries),
        write_records(place / "trials.jsonl", records),
        tuple(r for r, _ in entries),
        tuple(chosen),
    )


def design(made: StandInStore, visible: Measured, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    """The gaps design for the control role's harness arm on ``made``'s version."""
    body: dict[str, Any] = {
        "format": 1,
        "seed": 7,
        "draws": 1000,
        "store": str(made.store),
        "role": "control",
        "version": made.version,
        "arm": "harness",
        "trials": 2,
        "visible": [t.id for t in visible.tasks],
        "held_out_tasks": 2,
        "validation_tasks": 2,
    }
    body.update(changes)
    return body
