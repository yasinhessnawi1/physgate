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
  whose stream was gone at a resume, a session or decomposition stream that is gone, or a
  run that never ended, which may have been killed during a review), or a fresh scan of
  every stream of the run finds the task's canary;
- either arm: the answer's score holds a verdict that is not a bool, which the scorer
  never writes.

Such a trial is an :class:`ExcludedTrial` with its reason: counted as excluded, never as a
pass, a fail or unscored, and never re-run in place of the answer it made.

**Whether a trial was ended by the infrastructure** is read from the arm's own records,
never from the answer, and only where no answer exists; such a trial is run once more
after the registered delay, and if it ends so again it is ``unscored``, a fail for its
arm in a column of its own:

- the harness arm, judged by the run's last end: the run stands halted because the
  infrastructure was exhausted or the OS layer was unavailable, or its one decomposition call
  ended on an API error or an unavailable sandbox. A run that halted so, was resumed, and then
  ended on its own is the harness's own end, not the machine's. The account's usage limit and
  a refused credential are among the machine's halts and causes too, but they are never a
  trial's end: a round never assembles a run that stands at one, and resumes it, or decomposes
  the trial afresh, once the limit resets or a person replaces the credential;
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
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from physgate.evaluation.observe.cost import CostLine, DatedSheet
from physgate.evaluation.per_role.arms.compare import ENDED_STEPS, next_step
from physgate.evaluation.per_role.arms.raw import WATCH_FAILURES
from physgate.evaluation.per_role.report import (
    AblationMark,
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
from physgate.orchestrator.design_rounds import decomposition_streams
from physgate.orchestrator.dispatch import read_captured, review_material_seen, review_streams
from physgate.orchestrator.events import (
    Event,
    Halted,
    Incident,
    LeftoverRead,
    SessionSpawned,
    parse_events,
)
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.replay import replay
from physgate.orchestrator.review_root_record import recorded_review_root
from physgate.orchestrator.run_config import ABLATION_ONLY, RunConfig, load_run_config
from physgate.orchestrator.session_ends import open_sessions, spawn_kind
from physgate.reviewers.places import SESSION_DIRNAME

#: The run halts that are the machine's, not the design's: the account's usage limit among them.
INFRASTRUCTURE_HALTS = frozenset(
    {"infrastructure_exhausted", "credential_refused", "os_layer_unavailable", "usage_limit"}
)
#: The causes, of a session or of the decomposition call, that are the machine's: the account's
#: usage limit among them, where a cause names it (a raw session is classified without it, so a
#: limit that ended one is an ``api_error`` here, the machine's all the same).
INFRASTRUCTURE_CAUSES = frozenset(
    {"api_error", "credential_refused", "sandbox_unavailable", "usage_limit"}
)
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
    #: An ablation trial's own mark, as a trial record carries it (:data:`.report.AblationMark`);
    #: left out where there is none, so every such record keeps its bytes.
    ablation: AblationMark | None = Field(default=None, exclude_if=lambda v: v is None)


def ablation_mark(config: RunConfig) -> str | None:
    """What an ablation run took away, as its trial's record says it; ``None`` for any other run.

    Read from the run's own configuration, so whoever assembles the record (the round, the
    record audit) writes the same mark: each switch at a value only an ablation run takes, and a
    gate that does not block, as ``flag=value``, sorted; an ablation run that took none of them
    away is marked ``ablation=true``.
    """
    if not config.ablation:
        return None
    parts = [
        f"{name}={value}"
        for name, arms in ABLATION_ONLY.items()
        if (value := getattr(config, name)) in arms
    ]
    if config.gate_mode != "on":
        parts.append(f"gate_mode={config.gate_mode}")
    return ",".join(sorted(parts)) or "ablation=true"


def read_arm_records(lines: Iterable[str]) -> list[TrialRecord | ExcludedTrial]:
    """An ablation arm's records, for the arm's own analysis: each one an ablation trial's.

    The one reader of an arm's records: a line that is not an ablation trial's record (a
    measured arm's, or one with no mark) is refused, so a measured arm's records are never read
    as the arm's, as the arm's are never read as a measured arm's.

    Raises:
        ReportError: a line is not a trial record, or carries no ablation mark.
    """
    records: list[TrialRecord | ExcludedTrial] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            model = ExcludedTrial if "reason" in raw and "outcome" not in raw else TrialRecord
            record = model.model_validate_json(line)
        except (ValueError, TypeError, ValidationError):
            msg = f"line {number} is not a trial record"
            raise ReportError(msg, refused_because="trials_unreadable") from None
        if record.ablation is None:
            msg = f"line {number} is not an ablation trial's record: it carries no ablation mark"
            raise ReportError(msg, refused_because="not_an_ablation_record")
        records.append(record)
    return records


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


def harness_exclusion(
    config: RunConfig, events: Sequence[Event], run_dir: Path, task: Task
) -> str | None:
    """Why a harness trial is excluded, or ``None``.

    The run recorded a held-out read. Or the run did not end: a run that did not end is not a
    measurement in any tier. Or the task is held out and the run could not have recorded one:
    the loop writes that incident only when one of the run's canaries shows in a stream it
    scanned, so a canary it did not look for, or a stream it never scanned, leaves
    an exposed trial looking like a clean one. The raw arm is held to the same rule.

    Raises:
        CorruptEventLogError: the log does not replay as a run, so whether it ended cannot be
            said.
    """
    for event in events:
        if isinstance(event, Incident) and event.cause == "held_out_read":
            # The incident's detail is not repeated: it may name what was read.
            return f"incident: the run recorded a held-out read (event {event.seq})"
    if task.canary is None:
        return _unended(events)
    if task.canary not in config.held_out_canaries:
        return "held_out_canaries: the task is held out and the run did not look for its canary"
    for event in events:
        if isinstance(event, LeftoverRead) and event.scan != "scanned":
            return f"leftover_read: session {event.session_id}'s stream was never scanned"
    for left in open_sessions(events, run_dir):
        return f"session: {left} never ended, so its stream was never scanned"
    for session_id in dict.fromkeys(e.session_id for e in events if isinstance(e, SessionSpawned)):
        gone = _stream_gone(session_id, events, run_dir)
        if gone is not None:
            return f"stream: {gone}"
    for place in decomposition_streams(events):
        if not (run_dir / place).is_file():
            return f"stream: {place}, which the log names, is gone"
    for stream in _streams(run_dir):
        if review_material_seen(stream, frozenset({task.canary})) is not None:
            return "canary: the task's own canary showed in a stream of the run"
    # Last, once every stream the run left beneath its directory is held: a reviewer's lies
    # outside it, beneath the review root, and is scanned only as its review ends, or by a
    # resume. A run killed during a review, and never resumed, has neither: its review's spawn
    # is left open above, and the run's own end says the rest of what it owed ended too.
    return _unended(events)


def _stream_gone(session_id: str, events: Sequence[Event], run_dir: Path) -> str | None:
    """Why a spawned session's streams are not all where its kind keeps them, or ``None``.

    A role session's is beneath the run directory. A module review's are beneath the review root
    the run recorded, in the review's session directory: its first stream and one per repair
    resume, each a spawn of its own. A session whose kind the records do not tell has no place to
    look, and is never taken as held.
    """
    kind = spawn_kind(session_id, events)
    if kind == "role session":
        if not (run_dir / "sessions" / session_id / STREAM_NAME).is_file():
            return f"session {session_id}'s stream is gone"
        return None
    if kind != "module review":
        return f"session {session_id} is of no kind the records tell, so its stream is not found"
    try:
        root = recorded_review_root(run_dir)
    except RunStateError:
        return f"review session {session_id}'s stream: the run's review root record is unreadable"
    if root is None:
        return f"review session {session_id}'s stream: the run recorded no review root"
    spawns = sum(1 for e in events if isinstance(e, SessionSpawned) and e.session_id == session_id)
    where = root / session_id / SESSION_DIRNAME
    for name in review_streams(spawns):
        if not (where / name).is_file():
            return f"review session {session_id}'s stream {name} is gone"
    return None


def _unended(events: Sequence[Event]) -> str | None:
    """Why a run that did not end is excluded, or ``None`` for one that ended.

    Raises:
        CorruptEventLogError: the log does not replay as a run.
    """
    step = next_step(events)
    if step not in ENDED_STEPS:
        return (
            f"run: the run has not ended (its next step is {step}): it is no measurement, "
            "and a stream of it may be unscanned"
        )
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
    return machine_end(events) is not None


def machine_end(events: Sequence[Event]) -> Halted | None:
    """The machine's halt the run ended on, judged by its last end; ``None`` if it ended otherwise.

    A run that halted on the machine and was resumed past that halt ended on whatever ended it
    after: a resume clears the halt as the loop replays it. So the halt that counts is the one
    the run stands at now, never an earlier one in its log: one of :data:`INFRASTRUCTURE_HALTS`,
    or a failed decomposition whose cause is one of :data:`INFRASTRUCTURE_CAUSES`.

    Raises:
        CorruptEventLogError: the log does not replay as a run.
    """
    state = replay(events)
    halt = state.halted
    if state.next_step().kind != "halted" or halt is None:
        return None
    if halt.reason in INFRASTRUCTURE_HALTS:
        return halt
    if halt.reason == "decomposition_failed" and decomposition_cause(halt) in INFRASTRUCTURE_CAUSES:
        return halt
    return None


def decomposition_cause(halt: Halted) -> str:
    """The cause a failed decomposition's halt names: the words of its detail before the colon."""
    return halt.detail.split(":", 1)[0].strip()


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
    mark = ablation_mark(config)
    if excluded is not None:
        return ExcludedTrial(
            suite=suite, task=task.id, arm=arm, trial=trial, reason=excluded, ablation=mark
        )
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
            **({} if mark is None else {"ablation": mark}),
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
