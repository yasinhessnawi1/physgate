"""One trial record for the report, assembled from what a finished arm left.

The harness arm leaves a run directory: its events, its configuration and its cost line,
and the answer extracted from its run branch. The raw arm leaves its session's record and
stream. Each has the answer's score, unless the trial left no answer to score.

**Whether a trial was ended by the infrastructure** is read from the arm's own records,
never from the answer, and only where no answer exists; such a trial is run once more
after the registered delay, and if it ends so again it is ``unscored``, a fail for its
arm in a column of its own:

- the harness arm: the run halted because the infrastructure was exhausted, the
  credential was refused or the OS layer was unavailable, or its one decomposition call
  ended on an API error, a refused credential or an unavailable sandbox;
- the raw arm: its session ended on an API error, a refused credential, an unavailable
  sandbox, or without a result or with an unexpected exit, unless the session was stopped
  by its own token cap or wall clock, which are the arm's spending, not the machine's.

A trial whose answer exists is scored, however the run ended after it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from physgate.evaluation.observe.cost import CostLine, DatedSheet
from physgate.evaluation.per_role.report import ControlFlags, Outcome, TrialRecord
from physgate.evaluation.per_role.task import Task
from physgate.evaluation.per_role.trials import (
    control_trial,
    cost_of_line,
    gate_and_reviews,
    raw_cost,
)
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.catches import parse_time
from physgate.orchestrator.dispatch import read_captured
from physgate.orchestrator.events import Event, Halted
from physgate.orchestrator.gate_events import gate_events

#: The run halts that are the machine's, not the design's.
INFRASTRUCTURE_HALTS = frozenset(
    {"infrastructure_exhausted", "credential_refused", "os_layer_unavailable"}
)
#: The causes, of a session or of the decomposition call, that are the machine's.
INFRASTRUCTURE_CAUSES = frozenset({"api_error", "credential_refused", "sandbox_unavailable"})
#: A raw session's ends that are the arm's own spending, never the machine's.
OWN_ENDS = frozenset({"budget_exhausted", "wall_clock"})


def harness_ended_by_infrastructure(events: Sequence[Event], answer_found: bool) -> bool:
    """Whether the infrastructure ended a harness trial before an answer existed."""
    if answer_found:
        return False
    for event in events:
        if not isinstance(event, Halted):
            continue
        if event.reason in INFRASTRUCTURE_HALTS:
            return True
        if event.reason == "decomposition_failed":
            cause = event.detail.split(":", 1)[0].strip()
            if cause in INFRASTRUCTURE_CAUSES:
                return True
    return False


def raw_ended_by_infrastructure(record: Mapping[str, Any], stream: Path) -> bool:
    """Whether the infrastructure ended a raw session before it wrote an answer."""
    if record.get("answer") == "found" or record.get("end") in OWN_ENDS:
        return False
    end = classify_session_end(
        read_captured(stream).result,
        exit_code=record.get("exit_code"),
        stopped_at_wall_clock=False,
    )
    return end.cause in (*INFRASTRUCTURE_CAUSES, "no_result", "unexpected_exit")


def _outcome(
    task: Task, score: Mapping[str, Any] | None, unscored: bool
) -> tuple[Outcome, ControlFlags]:
    if unscored:
        views = any(s.counts == "secondary" for s in task.specs)
        return "unscored", ControlFlags(
            no_gain_crossover=False,
            full_view_ratio=False if views else None,
            full_view_db=False if views else None,
        )
    if score is None:
        # No answer, and not the machine's doing: the arm's own fail.
        return _outcome(task, {"passed": False, "flags": {}, "specs": []}, False)
    return control_trial(task, score)


def _span_s(events: Sequence[Event]) -> float:
    if not events:
        return 0.0
    first, last = parse_time(events[0].ts), parse_time(events[-1].ts)
    return max(0.0, (last - first).total_seconds())


def harness_trial(
    *,
    suite: str,
    task: Task,
    trial: int,
    events: Sequence[Event],
    manifest_id: str,
    cost: CostLine,
    score: Mapping[str, Any] | None,
    unscored: bool,
    arm: str = "harness",
) -> TrialRecord:
    """The record of one harness trial (``arm`` ``observe`` for the gate-observing arm).

    ``score`` is the answer's score, ``None`` where the run left no answer; ``unscored``
    is the runner's verdict after the trial's re-run (:func:`harness_ended_by_infrastructure`
    on both runs).
    """
    outcome, flags = _outcome(task, score, unscored)
    gate, review = gate_and_reviews(gate_events(events, manifest_id), events)
    return TrialRecord.model_validate(
        {
            "suite": suite,
            "task": task.id,
            "arm": arm,
            "trial": trial,
            "outcome": outcome,
            "cost": cost_of_line(cost),
            "wall_clock_s": _span_s(events),
            "gate": gate,
            "review": review,
            "control": flags,
        }
    )


def raw_trial(
    *,
    suite: str,
    task: Task,
    trial: int,
    record: Mapping[str, Any],
    stream: Path,
    prices: DatedSheet,
    subscription: bool,
    score: Mapping[str, Any] | None,
    unscored: bool,
) -> TrialRecord:
    """The record of one raw trial, priced from its stream at the run's price sheet."""
    outcome, flags = _outcome(task, score, unscored)
    return TrialRecord.model_validate(
        {
            "suite": suite,
            "task": task.id,
            "arm": "raw",
            "trial": trial,
            "outcome": outcome,
            "cost": raw_cost(
                stream,
                str(record["session_id"]),
                str(record["pins"]["model"]),
                prices,
                subscription=subscription,
            ),
            "wall_clock_s": float(record["wall_clock_s"]),
            "control": flags,
        }
    )
