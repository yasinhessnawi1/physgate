"""One trial record for the report, assembled from what a finished arm left.

The harness arm leaves a run directory: its events, its configuration and its cost line,
and the answer extracted from its run branch. Its events and configuration are read from
that directory here, never taken from the caller. The raw arm leaves its session's record and
stream. Each has the answer's score, unless the trial left no answer to score.

**A trial whose record says not to take it is excluded, never scored.** Before anything is
scored, each arm's own records are read for what makes its answer untrustworthy:

- the raw arm: a held-out canary showed in its stream (or it cannot say whether one
  did, on a held-out task), its token watch failed, stalled or found no stream, its
  end check refused the session, its stream was written to after its result, or its
  record holds a value the arm never writes (a canary field that is not a bool, an end
  outside the ends it takes);
- the harness arm: its event log is empty or ends in a cut-off line, where an incident
  may have been; the run recorded a held-out read; or, on a held-out task, the run
  could not have recorded one, by the raw arm's rule: it did not look for the task's
  canary, a stream of the run was never scanned (a session that never ended, a leftover
  whose stream was gone at a resume, a session whose stream is gone), or a fresh scan of
  every stream of the run finds the task's canary;
- either arm: the answer's score holds a verdict that is not a bool, which the scorer
  never writes.

Such a trial is an :class:`ExcludedTrial` with its reason: counted as excluded, never as a
pass, a fail or unscored, and never re-run in place of the answer it made.

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

The two arms do not class every end alike: a harness decomposition call that ends with no
result or an unexpected exit is the harness's own fail, while a raw session that ends so
is the machine's. Unscored trials stay in the pass rate's denominator, so the pass rate is
the same either way; the unscored and fail columns are not.

A trial whose answer exists and whose records do not exclude it is scored, however the run
ended after the answer was written.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.observe.cost import CostLine, DatedSheet
from physgate.evaluation.per_role.arms.raw import WATCH_FAILURES
from physgate.evaluation.per_role.report import (
    Arm,
    ControlFlags,
    Outcome,
    ReportError,
    TrialRecord,
)
from physgate.evaluation.per_role.trials import (
    ScoreError,
    control_trial,
    cost_of_line,
    gate_and_reviews,
    raw_cost,
)
from physgate.evaluation.tiers.task import Task
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.catches import parse_time
from physgate.orchestrator.dispatch import read_captured, review_material_seen
from physgate.orchestrator.events import (
    Event,
    Halted,
    Incident,
    LeftoverRead,
    SessionEnded,
    SessionSpawned,
    parse_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.run_config import RunConfig, load_run_config

#: The run halts that are the machine's, not the design's.
INFRASTRUCTURE_HALTS = frozenset(
    {"infrastructure_exhausted", "credential_refused", "os_layer_unavailable"}
)
#: The causes, of a session or of the decomposition call, that are the machine's.
INFRASTRUCTURE_CAUSES = frozenset({"api_error", "credential_refused", "sandbox_unavailable"})
#: A raw session's ends that are the arm's own spending, never the machine's.
OWN_ENDS = frozenset({"budget_exhausted", "wall_clock"})
#: Every end the raw arm writes for a session whose result may be taken: its own, or its
#: cap's or its wall clock's. Any other end (a watch failure, a checkpoint's stop reason)
#: excludes the trial.
RAW_ENDS = frozenset({"ended", *OWN_ENDS})


#: A field the record does not carry, told apart from one it carries as ``None``.
_MISSING = object()

#: Where a harness run's streams lie beneath its run directory: its role sessions' and its
#: decomposition call's. Its reviewers' lie beneath the review root, outside the run
#: directory; the loop scans each with the run's canaries as the review ends.
STREAM_ROOTS = ("sessions", "decomposition")
STREAM_NAME = "stdout.jsonl"


class ExcludedTrial(BaseModel):
    """A trial whose own records say its answer is not to be taken, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    suite: str
    task: str
    arm: Arm
    trial: int
    #: The record's field that excludes it, then what that field says; no held-out content.
    reason: str


class TrialExcludedError(ReportError):
    """A trial's own records exclude it: there is nothing to decide about how it ended."""


def harness_run(run_dir: Path) -> tuple[RunConfig, list[Event], str | None]:
    """A harness run's recorded configuration and its event log, read from ``run_dir``.

    The third value says why the log cannot be taken whole, or is ``None``. An empty log
    holds no record of the run, and a cut-off last line is never dropped silently: an
    incident halts the run, so the last line is where a killed orchestrator's would be.

    Raises:
        RunConfigError: the run recorded no valid configuration.
        CorruptEventLogError: a line of the log is not one the loop could have written.
    """
    config = load_run_config(run_dir / "run.json")
    log = run_dir / "events.jsonl"
    data = log.read_bytes()
    if not data:
        return config, [], "events: the run's event log is empty"
    if not data.endswith(b"\n"):
        return config, [], "events: the run's event log ends in a cut-off line"
    return config, parse_events(data, log=str(log)), None


def _streams(run_dir: Path) -> list[Path]:
    """Every stream beneath the run directory's stream roots, no link followed."""
    found = []
    for root in STREAM_ROOTS:
        for here, _dirs, files in os.walk(run_dir / root):
            if STREAM_NAME in files:
                found.append(Path(here) / STREAM_NAME)
    return sorted(found)


def decomposition_streams(events: Sequence[Event]) -> list[str]:
    """The decomposition streams the log names, by their place beneath the run directory."""
    return []


def harness_exclusion(
    config: RunConfig, events: Sequence[Event], run_dir: Path, task: Task
) -> str | None:
    """Why a harness trial is excluded, or ``None``.

    The run recorded a held-out read. Or the task is held out and the run could not have
    recorded one: the loop writes that incident only when one of the run's canaries shows in
    a stream it scanned, so a canary it did not look for, or a stream it never scanned, leaves
    an exposed trial looking like a clean one. The raw arm is held to the same rule.
    """
    for event in events:
        if isinstance(event, Incident) and event.cause == "held_out_read":
            # The incident's detail is not repeated: it may name what was read.
            return f"incident: the run recorded a held-out read (event {event.seq})"
    if task.canary is None:
        return None
    if task.canary not in config.held_out_canaries:
        return "held_out_canaries: the task is held out and the run did not look for its canary"
    for event in events:
        if isinstance(event, LeftoverRead) and event.scan != "scanned":
            return f"leftover_read: session {event.session_id}'s stream was never scanned"
    ended = {e.session_id for e in events if isinstance(e, SessionEnded | LeftoverRead)}
    for event in events:
        if not isinstance(event, SessionSpawned):
            continue
        if event.session_id not in ended:
            return f"session: {event.session_id} never ended, so its stream was never scanned"
        if not (run_dir / "sessions" / event.session_id / STREAM_NAME).is_file():
            return f"stream: session {event.session_id}'s stream is gone"
    for stream in _streams(run_dir):
        if review_material_seen(stream, frozenset({task.canary})) is not None:
            return "canary: the task's own canary showed in a stream of the run"
    return None


def raw_exclusion(record: Mapping[str, Any], stream: Path, task: Task) -> str | None:
    """Why a raw trial is excluded, or ``None``.

    Each signal is read as the raw arm writes it, and only so: a field it always writes
    and that is missing, or that holds anything it never writes (a number where a bool
    belongs, an end it does not write), excludes the trial too, since the record cannot
    then say the trial is sound.
    """
    seen = record.get("held_out_seen", _MISSING)
    if seen is _MISSING:
        return "held_out_seen: the record does not say whether a held-out canary showed"
    if seen is not False and seen is not None:
        return "held_out_seen: a held-out canary showed in the stream, or the record cannot say"
    if task.canary is not None and seen is None:
        return "held_out_seen: the task is held out and no canary was looked for"
    if task.canary is not None and review_material_seen(stream, frozenset({task.canary})):
        return "canary: the task's own canary showed in the session's stream"
    end = record.get("end")
    if not isinstance(end, str):
        return "end: the record holds no end"
    if end in WATCH_FAILURES:
        return f"end: {end}; the watch could not hold the session to its cap"
    if end not in RAW_ENDS:
        return f"end: {end!r} is not an end the raw arm writes for a session it takes"
    after = record.get("sentinel_after_stop", _MISSING)
    if after is _MISSING:
        return "sentinel_after_stop: the record does not say what the end check found"
    if after is not None:
        return "sentinel_after_stop: the end check refused the session"
    tampered = read_captured(stream).tampered
    if tampered is not None:
        return f"stream: {tampered}"
    return None


def _raw_belongs(record: Mapping[str, Any], task: Task) -> None:
    """Refuse a raw record that is not of ``task``: a runner filing it under another task.

    Raises:
        ReportError: the record names another task, another brief or another answer, or no
            auth mode its cost could be priced by.
    """
    pins = record.get("pins")
    if record.get("task") != task.id or not isinstance(pins, Mapping):
        msg = "the raw record is not of the task it is assembled for"
        raise ReportError(msg, task=task.id, record_task=str(record.get("task")))
    if pins.get("brief_sha256") != hashlib.sha256(task.brief.encode()).hexdigest():
        msg = "the raw record's brief is not the task's"
        raise ReportError(msg, task=task.id)
    if pins.get("answer") != task.answer.model_dump(mode="json"):
        msg = "the raw record's answer contract is not the task's"
        raise ReportError(msg, task=task.id)
    if pins.get("auth") not in ("subscription", "api_key"):
        msg = "the raw record does not say how the session was paid for"
        raise ReportError(msg, task=task.id)


def _control_only(task: Task) -> None:
    """Refuse a task this assembly cannot score: only control tasks have a path here.

    Raises:
        ReportError: the task is not a control task.
    """
    if task.role != "control":
        msg = "a trial record is assembled here for control tasks only"
        raise ReportError(msg, task=task.id, role=str(task.role))


def harness_ended_by_infrastructure(run_dir: Path, task: Task, answer_found: bool) -> bool:
    """Whether the infrastructure ended a harness trial before an answer existed.

    ``run_dir`` is the harness run's directory, whose records are read; ``task`` is the
    trial's task.

    Raises:
        TrialExcludedError: the run's records exclude the trial.
    """
    config, events, unread = harness_run(run_dir)
    excluded = unread or harness_exclusion(config, events, run_dir, task)
    if excluded is not None:
        raise TrialExcludedError(excluded)
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


def raw_ended_by_infrastructure(record: Mapping[str, Any], stream: Path, task: Task) -> bool:
    """Whether the infrastructure ended a raw session before it wrote an answer.

    Raises:
        ReportError: the record is not of ``task``.
        TrialExcludedError: the session's records exclude the trial.
    """
    _raw_belongs(record, task)
    excluded = raw_exclusion(record, stream, task)
    if excluded is not None:
        raise TrialExcludedError(excluded)
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


def score_exclusion(task: Task, score: Mapping[str, Any] | None, unscored: bool) -> str | None:
    """Why the answer's score is not taken, or ``None``: a verdict in it is not a bool.

    The scorer writes bools only; anything else (the string ``"false"``, a number) is
    never read as a pass or a fail. An unscored trial's score is not read at all.
    """
    if unscored or score is None:
        return None
    try:
        control_trial(task, score)
    except ScoreError as exc:
        return f"score: {exc}"
    return None


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
    run_dir: Path,
    manifest_id: str,
    cost: CostLine,
    score: Mapping[str, Any] | None,
    unscored: bool,
    arm: Arm = "harness",
) -> TrialRecord | ExcludedTrial:
    """The record of one harness trial (``arm`` ``observe`` for the gate-observing arm).

    ``run_dir`` is the harness run's directory, whose configuration and events are read.
    ``score`` is the answer's score, ``None`` where the run left no answer; ``unscored`` is
    the runner's verdict after the trial's re-run (:func:`harness_ended_by_infrastructure` on
    both runs). A run whose records exclude it (:func:`harness_exclusion`) is excluded.

    Raises:
        ReportError: the task is not a control task, or the cost line is not this run's.
    """
    _control_only(task)
    config, events, unread = harness_run(run_dir)
    if cost.manifest_id != manifest_id or any(e.run_id != cost.run_id for e in events):
        msg = "the cost line is not of the run whose events it is assembled with"
        raise ReportError(msg, task=task.id, cost_run=cost.run_id)
    excluded = (
        unread
        or harness_exclusion(config, events, run_dir, task)
        or score_exclusion(task, score, unscored)
    )
    if excluded is not None:
        return ExcludedTrial(suite=suite, task=task.id, arm=arm, trial=trial, reason=excluded)
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
    score: Mapping[str, Any] | None,
    unscored: bool,
) -> TrialRecord | ExcludedTrial:
    """The record of one raw trial, priced from its stream at the run's price sheet.

    The cost basis follows the auth mode the session recorded: a subscription session's
    cost is a list-price estimate. A session whose records exclude it is excluded.

    Raises:
        ReportError: the task is not a control task, or the record is not of ``task``.
    """
    _control_only(task)
    _raw_belongs(record, task)
    excluded = raw_exclusion(record, stream, task) or score_exclusion(task, score, unscored)
    if excluded is not None:
        return ExcludedTrial(suite=suite, task=task.id, arm="raw", trial=trial, reason=excluded)
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
                subscription=record["pins"].get("auth") == "subscription",
            ),
            "wall_clock_s": float(record["wall_clock_s"]),
            "control": flags,
        }
    )
