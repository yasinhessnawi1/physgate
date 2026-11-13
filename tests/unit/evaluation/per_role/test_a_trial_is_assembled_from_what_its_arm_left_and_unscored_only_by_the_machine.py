from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from harness_rig import loop_run
from task_fixtures import own_task

from physgate.evaluation.observe.cost import CostLine, load_price_sheet
from physgate.evaluation.per_role.assemble import (
    ExcludedTrial,
    TrialExcludedError,
    harness_ended_by_infrastructure,
    harness_trial,
    raw_ended_by_infrastructure,
    raw_trial,
)
from physgate.evaluation.per_role.report import ReportError, TrialRecord
from physgate.evaluation.tiers.task import parse_task
from physgate.orchestrator.design_rounds import decomposition_streams
from physgate.orchestrator.events import (
    Decomposed,
    DecompositionRetried,
    Event,
    Halted,
    Incident,
    LeftoverRead,
    PlanProposed,
    ReviewRan,
    RunStarted,
    SessionEnded,
    SessionSpawned,
    SubtaskPlanned,
)
from physgate.orchestrator.protocols import ReviewResult
from physgate.orchestrator.run_config import RunConfig

TASK = parse_task(json.dumps(own_task()).encode())
ENV = {"run_id": "r", "gate_mode": "on"}
EXAMPLES = Path(__file__).parents[4] / "src/physgate/orchestrator/examples"
T0 = "2026-10-19T10:00:00.000000Z"


def _config(**changes: Any) -> RunConfig:
    """A harness run's recorded configuration, for ``TASK``'s brief."""
    params = json.loads((EXAMPLES / "params.subscription.json").read_text())
    params.update(
        run_id="r",
        seed=1,
        brief_sha256=hashlib.sha256(TASK.brief.encode()).hexdigest(),
        target_head="b" * 40,
        claude_version="2.1.301",
        endpoint="default",
        harness={"commit": None, "clean": False, "uncommitted_sha256": None},
        git_binary=None,
        os_layer=None,
        network_enforced=None,
    )
    params.update(changes)
    return RunConfig.model_validate_json(json.dumps(params))


def _start() -> RunStarted:
    return RunStarted(seq=0, ts=T0, config_sha256="0" * 64, **ENV)  # type: ignore[arg-type]


def _planned(seq: int) -> SubtaskPlanned:
    return SubtaskPlanned(
        seq=seq,
        ts=T0,
        subtask_id="s",
        spec_path="specs/s.md",
        assigned_role="control",
        module_dir="modules/s",
        **ENV,  # type: ignore[arg-type]
    )


def _run(tmp_path: Path, *events: Event, config: RunConfig | None = None) -> Path:
    """A harness run directory: its configuration and its event log, as the loop writes them."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text((config or _config()).model_dump_json())
    (run_dir / "events.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in events))
    return run_dir


def _halt(
    reason: str, detail: str = "x", seq: int = 1, ts: str = "2026-10-19T10:30:00.000000Z"
) -> Halted:
    return Halted(seq=seq, ts=ts, reason=reason, detail=detail, **ENV)  # type: ignore[arg-type]


def _review(seq: int, ts: str) -> ReviewRan:
    result = ReviewResult.model_validate(
        {
            "verdict": "fail",
            "finding": "f",
            "reviewer_model": "claude-sonnet-5",
            "session_id": "rev",
            "usage": (),
        }
    )
    return ReviewRan(seq=seq, ts=ts, subtask_id="s", attempt=1, result=result, **ENV)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reason", "detail", "machine"),
    [
        ("infrastructure_exhausted", "x", True),
        ("credential_refused", "x", True),
        ("os_layer_unavailable", "x", True),
        ("decomposition_failed", "api_error: 529 overloaded", True),
        ("decomposition_failed", "sandbox_unavailable: no bubblewrap", True),
        ("decomposition_failed", "invalid_plan: no module", False),
        ("incident", "merge_conflict", False),
    ],
)
def test_a_harness_trial_is_the_machine_s_only_by_the_machine_s_halts(
    tmp_path: Path, reason: str, detail: str, machine: bool
) -> None:
    run = _run(tmp_path, _start(), _halt(reason, detail))
    assert harness_ended_by_infrastructure(run, TASK, answer_found=False) is machine
    # An answer that exists is scored, however the run ended after it.
    assert harness_ended_by_infrastructure(run, TASK, answer_found=True) is False


def _stream(path: Path, result: dict[str, Any] | None) -> Path:
    lines = [
        {
            "type": "assistant",
            "message": {
                "id": "m",
                "model": "x",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        }
    ]
    if result is not None:
        lines.append({"type": "result", "session_id": "s-1", **result})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
DONE = {"is_error": False, "terminal_reason": "completed"}


def _raw(of: Any = None, **changes: Any) -> dict[str, Any]:
    """A raw record as the raw arm writes one, for task ``of``, sound unless ``changes`` say not."""
    task = of or TASK
    record: dict[str, Any] = {
        "session_id": "s-1",
        "task": task.id,
        "end": "ended",
        "exit_code": 0,
        "answer": "found",
        "wall_clock_s": 42.5,
        "held_out_seen": None,
        "sentinel_after_stop": None,
        "pins": {
            "model": "claude-opus-5-5",
            "auth": "subscription",
            "brief_sha256": hashlib.sha256(task.brief.encode()).hexdigest(),
            "answer": task.answer.model_dump(mode="json"),
        },
    }
    record.update(changes)
    return record


@pytest.mark.parametrize(
    ("record", "result", "machine"),
    [
        ({"end": "ended", "exit_code": 1, "answer": "no_answer"}, API_ERROR, True),
        ({"end": "ended", "exit_code": None, "answer": "no_answer"}, None, True),
        ({"end": "budget_exhausted", "exit_code": None, "answer": "no_answer"}, None, False),
        ({"end": "wall_clock", "exit_code": None, "answer": "no_answer"}, None, False),
        ({"end": "ended", "exit_code": 0, "answer": "no_answer"}, DONE, False),
        ({"end": "ended", "exit_code": 1, "answer": "found"}, API_ERROR, False),
    ],
    ids=[
        "api error",
        "no result",
        "own token cap",
        "own wall clock",
        "finished, no answer",
        "answer written",
    ],
)
def test_a_raw_trial_is_the_machine_s_only_when_the_machine_ended_it_before_an_answer(
    tmp_path: Path, record: dict[str, Any], result: dict[str, Any] | None, machine: bool
) -> None:
    stream = _stream(tmp_path / "stdout.jsonl", result)
    assert raw_ended_by_infrastructure(_raw(**record), stream, TASK) is machine


def _cost_line(usd: str = "3.50") -> CostLine:
    return CostLine.model_validate_json(
        json.dumps(
            {
                "manifest_id": "e" * 64,
                "run_id": "r",
                "started": "2026-10-19T10:00:00.000000Z",
                "auth": "subscription",
                "endpoint": "default",
                "basis": "list_price_estimate",
                "prices_date": "2026-10-16",
                "prices_sha256": "a" * 64,
                "usd_to_nok": "9.5",
                "usd_to_nok_date": "2026-10-16",
                "rows": [
                    {
                        "model": "claude-opus-5-5",
                        "tokens": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_input_tokens": 1000,
                            "cache_creation_input_tokens": 10,
                        },
                        "usd": usd,
                    }
                ],
                "usd": usd,
                "nok": "33.25",
                "partial": False,
            }
        )
    )


SCORED = {"passed": True, "flags": {"no_gain_crossover": True}, "specs": []}


def test_a_harness_trial_carries_its_score_cost_span_and_reviews(tmp_path: Path) -> None:
    run = _run(tmp_path, _start(), _planned(1), _review(2, T0), _halt("incident", seq=3))
    record = harness_trial(
        suite="control_visible",
        task=TASK,
        trial=2,
        run_dir=run,
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=False,
    )
    assert isinstance(record, TrialRecord)
    assert record.outcome == "pass" and record.trial == 2 and record.arm == "harness"
    assert record.control is not None and record.control.no_gain_crossover
    assert record.cost.tokens == 1160 and record.cost.usd == Decimal("3.50")
    assert record.wall_clock_s == 1800.0
    assert record.review is not None and record.review.failed == 1
    assert record.gate is not None and record.gate.checks_run == 0


def test_a_trial_the_machine_ended_twice_is_unscored_whatever_score_was_passed(
    tmp_path: Path,
) -> None:
    record = harness_trial(
        suite="s",
        task=TASK,
        trial=0,
        run_dir=_run(tmp_path, _start()),
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=True,
    )
    assert isinstance(record, TrialRecord)
    assert record.outcome == "unscored"


def test_a_trial_with_no_answer_that_the_machine_did_not_end_is_the_arm_s_fail(
    tmp_path: Path,
) -> None:
    record = harness_trial(
        suite="s",
        task=TASK,
        trial=0,
        run_dir=_run(tmp_path, _start()),
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=None,
        unscored=False,
    )
    assert isinstance(record, TrialRecord)
    assert record.outcome == "fail"


def test_a_raw_trial_is_priced_from_its_stream_and_keeps_its_wall_clock(tmp_path: Path) -> None:
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    record = _raw_trial(stream, _raw(), passed=False)
    assert isinstance(record, TrialRecord)
    assert record.outcome == "fail" and record.arm == "raw" and record.gate is None
    assert record.cost.tokens == 15 and record.wall_clock_s == 42.5
    assert record.cost.basis == "list_price_estimate"


def _raw_trial(
    stream: Path, record: dict[str, Any], task: Any = None, *, passed: bool = True
) -> TrialRecord | ExcludedTrial:
    return raw_trial(
        suite="s",
        task=task or TASK,
        trial=1,
        record=record,
        stream=stream,
        prices=load_price_sheet("2026-10-16"),
        score={"passed": passed, "flags": {}, "specs": []},
        unscored=False,
    )


#: A fixture canary, built here; it stands for no real task.
CANARY = hashlib.sha256(b"a fixture task's canary").hexdigest()[:32]
HELD_OUT = TASK.model_copy(update={"canary": CANARY, "tier": "held_out"})


@pytest.mark.parametrize(
    ("task", "changes", "field"),
    [
        (TASK, {"held_out_seen": True}, "held_out_seen"),
        (TASK, {"held_out_seen": "a canary"}, "held_out_seen"),
        (HELD_OUT, {"held_out_seen": None}, "held_out_seen"),
        (TASK, {"end": "watch_failed"}, "end"),
        (TASK, {"end": "watch_stalled"}, "end"),
        (TASK, {"end": "no_stream"}, "end"),
        (TASK, {"end": None}, "end"),
        (TASK, {"sentinel_after_stop": "refused"}, "sentinel_after_stop"),
        (HELD_OUT, {"held_out_seen": 0}, "held_out_seen"),
        (TASK, {"held_out_seen": 0}, "held_out_seen"),
        (TASK, {"end": "no_task_held"}, "end"),
        (TASK, {"end": "Ended"}, "end"),
    ],
    ids=[
        "canary seen",
        "canary named",
        "held out, nothing looked for",
        "watch failed",
        "watch stalled",
        "no stream",
        "no end",
        "end check refused",
        "held out, a number where a bool belongs",
        "a number where a bool belongs",
        "a checkpoint's stop reason as the end",
        "an end the raw arm never writes",
    ],
)
def test_a_raw_trial_whose_record_says_not_to_take_it_is_excluded_with_its_reason(
    tmp_path: Path, task: Any, changes: dict[str, Any], field: str
) -> None:
    """Even with a passing answer: a canary seen, an uncounted session, a refused end check."""
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    record = _raw(task, **changes)
    trial = _raw_trial(stream, record, task)
    assert isinstance(trial, ExcludedTrial)
    assert trial.reason.startswith(f"{field}:") and trial.arm == "raw" and trial.trial == 1
    with pytest.raises(TrialExcludedError, match=f"^{field}:"):
        raw_ended_by_infrastructure(record, stream, task)


@pytest.mark.parametrize("field", ["held_out_seen", "sentinel_after_stop"])
def test_a_raw_record_missing_a_field_the_arm_always_writes_is_excluded(
    tmp_path: Path, field: str
) -> None:
    record = _raw()
    del record[field]
    trial = _raw_trial(_stream(tmp_path / "stdout.jsonl", DONE), record)
    assert isinstance(trial, ExcludedTrial)
    assert trial.reason.startswith(f"{field}: the record does not say")


def test_a_raw_trial_whose_stream_shows_its_own_task_s_canary_is_excluded(tmp_path: Path) -> None:
    """The stream is read for the task's own canary, whatever the record says it saw."""
    stream = _stream(tmp_path / "stdout.jsonl", None)
    stream.write_text(
        json.dumps({"type": "user", "message": {"content": f"tool output {CANARY}"}})
        + "\n"
        + stream.read_text()
        + json.dumps({"type": "result", "session_id": "s-1", **DONE})
        + "\n"
    )
    trial = _raw_trial(stream, _raw(HELD_OUT, held_out_seen=False), HELD_OUT)
    assert isinstance(trial, ExcludedTrial) and trial.reason.startswith("canary:")


def test_a_raw_trial_whose_stream_was_written_after_its_result_is_excluded(tmp_path: Path) -> None:
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    stream.write_text(stream.read_text() + json.dumps({"type": "assistant", "x": 1}) + "\n")
    trial = _raw_trial(stream, _raw())
    assert isinstance(trial, ExcludedTrial) and trial.reason.startswith("stream:")


def test_a_sound_raw_trial_with_a_passing_answer_is_a_pass(tmp_path: Path) -> None:
    trial = _raw_trial(_stream(tmp_path / "stdout.jsonl", DONE), _raw(held_out_seen=False))
    assert isinstance(trial, TrialRecord) and trial.outcome == "pass"


def _incident(seq: int) -> Incident:
    return Incident(
        seq=seq,
        ts="2026-10-19T10:10:00.000000Z",
        subtask_id=None,
        cause="held_out_read",
        detail="x",
        **ENV,  # type: ignore[arg-type]
    )


def test_a_harness_trial_whose_run_recorded_a_held_out_read_is_excluded(tmp_path: Path) -> None:
    run = _run(tmp_path, _start(), _planned(1), _review(2, T0), _incident(3))
    trial = harness_trial(
        suite="s",
        task=TASK,
        trial=0,
        run_dir=run,
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=False,
    )
    assert isinstance(trial, ExcludedTrial) and trial.reason.startswith("incident:")
    assert trial.arm == "harness"
    with pytest.raises(TrialExcludedError, match="^incident:"):
        harness_ended_by_infrastructure(run, TASK, answer_found=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"task": "another-task"},
        {"pins": {**_raw()["pins"], "brief_sha256": "0" * 64}},
        {"pins": {**_raw()["pins"], "answer": {"path": "other.json", "format": "lti_tf"}}},
        {"pins": {**_raw()["pins"], "auth": None}},
    ],
    ids=["another task", "another brief", "another answer", "no auth mode"],
)
def test_a_raw_record_filed_under_another_task_is_refused(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    with pytest.raises(ReportError, match="raw record"):
        _raw_trial(stream, _raw(**changes))
    with pytest.raises(ReportError, match="raw record"):
        raw_ended_by_infrastructure(_raw(**changes), stream, TASK)


@pytest.mark.parametrize(("run_id", "manifest_id"), [("other", "e" * 64), ("r", "f" * 64)])
def test_a_harness_trial_with_another_run_s_cost_line_is_refused(
    tmp_path: Path, run_id: str, manifest_id: str
) -> None:
    cost = _cost_line().model_copy(update={"run_id": run_id})
    with pytest.raises(ReportError, match="cost line"):
        harness_trial(
            suite="s",
            task=TASK,
            trial=0,
            run_dir=_run(tmp_path, _start(), _planned(1), _review(2, T0)),
            manifest_id=manifest_id,
            cost=cost,
            score=SCORED,
            unscored=False,
        )


def test_a_firmware_task_is_refused_rather_than_scored_as_a_control_trial(tmp_path: Path) -> None:
    firmware = TASK.model_copy(update={"role": "firmware"})
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    with pytest.raises(ReportError, match="control tasks only"):
        _raw_trial(stream, _raw(firmware), firmware)
    with pytest.raises(ReportError, match="control tasks only"):
        harness_trial(
            suite="s",
            task=firmware,
            trial=0,
            run_dir=_run(tmp_path, _start()),
            manifest_id="e" * 64,
            cost=_cost_line(),
            score=SCORED,
            unscored=False,
        )


@pytest.mark.parametrize(
    ("auth", "basis"), [("subscription", "list_price_estimate"), ("api_key", "list_price")]
)
def test_a_raw_trial_s_cost_basis_follows_the_auth_mode_it_recorded(
    tmp_path: Path, auth: str, basis: str
) -> None:
    record = _raw(pins={**_raw()["pins"], "auth": auth})
    trial = _raw_trial(_stream(tmp_path / "stdout.jsonl", DONE), record)
    assert isinstance(trial, TrialRecord) and trial.cost.basis == basis


#: Another held-out task's canary, built here; it stands for no real task.
OTHER_CANARY = hashlib.sha256(b"another fixture task's canary").hexdigest()[:32]


def _spawned(seq: int, session_id: str) -> SessionSpawned:
    return SessionSpawned(seq=seq, ts=T0, session_id=session_id, pid=7, started="x", **ENV)  # type: ignore[arg-type]


def _ended(seq: int, session_id: str) -> SessionEnded:
    return SessionEnded(
        seq=seq,
        ts=T0,
        subtask_id="s",
        attempt=1,
        session_id=session_id,
        outcome="completed",
        cause=None,
        attempt_commit="a" * 40,
        trajectory=f"sessions/{session_id}/stdout.jsonl",
        worktree="worktrees/s",
        reading_verified=True,
        **ENV,  # type: ignore[arg-type]
    )


def _leftover(seq: int, session_id: str, scan: str) -> LeftoverRead:
    return LeftoverRead(
        seq=seq,
        ts=T0,
        session_id=session_id,
        stopped=True,
        complete=True,
        trajectory_seal=None,
        quarantine="operator: the stream was lost with the disk",
        scan=scan,  # type: ignore[arg-type]
        **ENV,  # type: ignore[arg-type]
    )


def _held_out_run(
    tmp_path: Path,
    *more: Event,
    canaries: tuple[str, ...] = (CANARY,),
    streams: dict[str, str] | None = None,
) -> Path:
    """A harness run on ``HELD_OUT`` that looked for its canary in every stream it wrote.

    One role session spawned, ended and reviewed; ``more`` follows it. ``streams`` are the
    run's streams by their place under the run directory, each a line of tool output.
    """
    events: list[Event] = [
        _start(),
        _planned(1),
        _spawned(2, "role-1"),
        _ended(3, "role-1"),
        _review(4, T0),
        *more,
    ]
    run = _run(tmp_path, *events, config=_config(held_out_canaries=list(canaries)))
    if streams is None:
        streams = {"sessions/role-1/stdout.jsonl": "tool output"}
    for place, text in streams.items():
        stream = run / place
        stream.parent.mkdir(parents=True, exist_ok=True)
        line = {"type": "user", "message": {"content": text}}
        stream.write_text(json.dumps(line) + "\n")
    return run


def _harness_trial(run: Path, task: Any = None) -> TrialRecord | ExcludedTrial:
    return harness_trial(
        suite="s",
        task=task or HELD_OUT,
        trial=0,
        run_dir=run,
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=False,
    )


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda p: _held_out_run(p, canaries=()), "held_out_canaries"),
        (lambda p: _held_out_run(p, canaries=(OTHER_CANARY,)), "held_out_canaries"),
        (
            lambda p: _held_out_run(
                p, _spawned(5, "role-2"), _leftover(6, "role-2", "unscanned (stream gone)")
            ),
            "leftover_read",
        ),
        (
            lambda p: _held_out_run(
                p,
                _spawned(5, "role-2"),
                streams={
                    "sessions/role-1/stdout.jsonl": "tool output",
                    "sessions/role-2/stdout.jsonl": "tool output",
                },
            ),
            "session",
        ),
        (lambda p: _held_out_run(p, streams={}), "stream"),
        (
            lambda p: _held_out_run(
                p, streams={"sessions/role-1/stdout.jsonl": f"tool output {CANARY}"}
            ),
            "canary",
        ),
        (
            lambda p: _held_out_run(
                p,
                streams={
                    "sessions/role-1/stdout.jsonl": "tool output",
                    "decomposition/stdout.jsonl": f"read {CANARY}",
                },
            ),
            "canary",
        ),
    ],
    ids=[
        "no canary looked for",
        "another task's canary looked for",
        "a leftover's stream never scanned",
        "a session never ended, its stream never scanned",
        "a session's stream gone",
        "its canary in a role session's stream",
        "its canary in the decomposition's stream",
    ],
)
def test_a_held_out_harness_trial_whose_run_could_not_have_seen_a_held_out_read_is_excluded(
    tmp_path: Path, build: Callable[[Path], Path], field: str
) -> None:
    """The raw arm's rule, held to the harness run's records.

    Held out, the run must have looked for the task's canary in every stream, across
    resumes, and a fresh scan of every stream must not find it.
    """
    run = build(tmp_path)
    trial = _harness_trial(run)
    assert isinstance(trial, ExcludedTrial), trial
    assert trial.reason.startswith(f"{field}:") and trial.arm == "harness"
    with pytest.raises(TrialExcludedError, match=f"^{field}:"):
        harness_ended_by_infrastructure(run, HELD_OUT, answer_found=True)


def _empty(run: Path) -> None:
    (run / "events.jsonl").write_bytes(b"")


def _cut_off(run: Path) -> None:
    # Where a killed orchestrator's incident would be: the last line, cut mid-write.
    line = _incident(3).model_dump_json().encode()
    with (run / "events.jsonl").open("ab") as log:
        log.write(line[: len(line) // 2])


@pytest.mark.parametrize(
    ("damage", "says"),
    [(_empty, "is empty"), (_cut_off, "ends in a cut-off line")],
    ids=["empty log", "cut-off incident line"],
)
def test_a_harness_trial_whose_event_log_cannot_be_read_whole_is_excluded(
    tmp_path: Path, damage: Callable[[Path], None], says: str
) -> None:
    """No line is dropped silently: an incident is what a torn last line may have been."""
    run = _run(tmp_path, _start(), _planned(1), _review(2, T0))
    damage(run)
    trial = _harness_trial(run, TASK)
    assert isinstance(trial, ExcludedTrial), trial
    assert trial.reason == f"events: the run's event log {says}"
    with pytest.raises(TrialExcludedError, match="^events:"):
        harness_ended_by_infrastructure(run, TASK, answer_found=False)


@pytest.mark.parametrize("end", ["watch_failed", "watch_stalled", "no_stream"])
def test_a_raw_trial_whose_watch_failed_is_excluded_as_uncounted(tmp_path: Path, end: str) -> None:
    """Named as the watch's failure, not only as an end the arm does not take."""
    trial = _raw_trial(_stream(tmp_path / "stdout.jsonl", DONE), _raw(end=end))
    assert isinstance(trial, ExcludedTrial)
    assert trial.reason == f"end: {end}; the watch could not hold the session to its cap"


def _scored(trial: Callable[[], TrialRecord | ExcludedTrial]) -> TrialRecord | ExcludedTrial | None:
    """The trial's record, or ``None`` where the assembly refused it instead."""
    try:
        return trial()
    except ReportError:
        return None


@pytest.mark.parametrize("passed", ["false", 0, None], ids=["a string", "a number", "none"])
def test_a_trial_whose_score_says_passed_in_anything_but_a_bool_is_excluded(
    tmp_path: Path, passed: Any
) -> None:
    """Excluded, never scored as a pass nor refused late: the scorer writes a bool."""
    score = {"passed": passed, "flags": {}, "specs": []}
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    raw = _scored(
        lambda: raw_trial(
            suite="s",
            task=TASK,
            trial=1,
            record=_raw(),
            stream=stream,
            prices=load_price_sheet("2026-10-16"),
            score=score,
            unscored=False,
        )
    )
    assert isinstance(raw, ExcludedTrial) and raw.reason.startswith("score:"), raw
    run = _run(tmp_path, _start(), _planned(1), _review(2, T0))
    harness = _scored(
        lambda: harness_trial(
            suite="s",
            task=TASK,
            trial=0,
            run_dir=run,
            manifest_id="e" * 64,
            cost=_cost_line(),
            score=score,
            unscored=False,
        )
    )
    assert isinstance(harness, ExcludedTrial) and harness.reason.startswith("score:"), harness


@pytest.mark.parametrize("end", [None, 3], ids=["none", "a number"])
def test_a_raw_record_whose_end_is_not_a_string_is_excluded_as_holding_no_end(
    tmp_path: Path, end: Any
) -> None:
    trial = _raw_trial(_stream(tmp_path / "stdout.jsonl", DONE), _raw(end=end))
    assert isinstance(trial, ExcludedTrial)
    assert trial.reason == "end: the record holds no end"


def _loop_run(tmp_path: Path, **how: Any) -> Path:
    """A run on ``HELD_OUT``'s canary, made by the loop: see :func:`harness_rig.loop_run`."""
    return loop_run(tmp_path / "run", held_out_canaries=(CANARY,), **how)


def test_a_sound_held_out_harness_trial_with_a_passing_answer_is_a_pass(tmp_path: Path) -> None:
    """Its canary looked for, every stream scanned and none showing it, and the run ended.

    A run the loop itself made and let end: the counterpart of the rows that exclude.
    """
    run = _loop_run(tmp_path)
    trial = _harness_trial(run)
    assert isinstance(trial, TrialRecord) and trial.outcome == "pass", trial
    assert harness_ended_by_infrastructure(run, HELD_OUT, answer_found=True) is False


@pytest.mark.parametrize("kill", ["review", "session"])
def test_a_held_out_harness_trial_of_a_run_that_never_ended_is_excluded(
    tmp_path: Path, kill: str
) -> None:
    """A run killed and never resumed may have a stream nothing scanned.

    A reviewer's stream lies outside the run directory and is scanned only as its review
    ends, or by a resume; a run killed during the review has neither, and spawned no session
    whose missing end would show it. So a held-out trial is taken only from a run that ended.
    """
    run = _loop_run(tmp_path, kill=kill)
    trial = _harness_trial(run)
    assert isinstance(trial, ExcludedTrial), trial
    assert trial.reason.startswith("run: the run has not ended"), trial.reason
    with pytest.raises(TrialExcludedError, match="^run: the run has not ended"):
        harness_ended_by_infrastructure(run, HELD_OUT, answer_found=False)


@pytest.mark.parametrize("kill", ["review", "session"])
def test_a_visible_harness_trial_of_a_run_that_never_ended_is_excluded(
    tmp_path: Path, kill: str
) -> None:
    """A run that did not end is not a measurement in any tier: excluded, with its reason.

    The same run let end is taken (the counterpart below), so the run's end is what excludes.
    """
    assert TASK.tier == "visible" and TASK.canary is None
    run = _loop_run(tmp_path, kill=kill)
    trial = _harness_trial(run, TASK)
    assert isinstance(trial, ExcludedTrial), trial
    assert trial.reason.startswith("run: the run has not ended"), trial.reason
    with pytest.raises(TrialExcludedError, match="^run: the run has not ended"):
        harness_ended_by_infrastructure(run, TASK, answer_found=False)


def test_a_visible_harness_trial_of_a_run_that_ended_is_taken(tmp_path: Path) -> None:
    trial = _harness_trial(_loop_run(tmp_path), TASK)
    assert isinstance(trial, TrialRecord) and trial.outcome == "pass", trial


def _decomposed(seq: int) -> Decomposed:
    return Decomposed(
        seq=seq,
        ts=T0,
        session_id="d1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=1,
        interface_nodes=("iface.bus",),
        spec_commit="a" * 40,
        head_revision=1,
        **ENV,  # type: ignore[arg-type]
    )


def _proposed(seq: int, round_: int, call: int = 1) -> PlanProposed:
    return PlanProposed(
        seq=seq,
        ts=T0,
        round=round_,
        session_id=f"p{round_}-{call}",
        model="claude-sonnet-5",
        num_turns=1,
        plan_sha256="f" * 64,
        started=T0,
        ended=T0,
        call=call,  # type: ignore[arg-type]
        **ENV,  # type: ignore[arg-type]
    )


def _retried(seq: int) -> DecompositionRetried:
    return DecompositionRetried(
        seq=seq,
        ts=T0,
        session_id="d0",
        cause="schema_refused",
        detail="x",
        **ENV,  # type: ignore[arg-type]
    )


def test_a_decomposed_run_with_its_decomposition_stream_is_taken(tmp_path: Path) -> None:
    run = _loop_run(tmp_path, decomposed=True)
    (run / "decomposition").mkdir()
    (run / "decomposition" / "stdout.jsonl").write_text('{"type": "result"}\n')
    trial = _harness_trial(run)
    assert isinstance(trial, TrialRecord) and trial.outcome == "pass", trial


def test_a_decomposed_held_out_run_whose_decomposition_stream_is_gone_is_excluded(
    tmp_path: Path,
) -> None:
    """The loop never scans the decomposition's stream; this layer's scan is its only one.

    A stream that is missing is no stream scanned, never a clean one.
    """
    trial = _harness_trial(_loop_run(tmp_path, decomposed=True))
    assert isinstance(trial, ExcludedTrial), trial
    assert trial.reason == "stream: decomposition/stdout.jsonl, which the log names, is gone"


@pytest.mark.parametrize(
    ("events", "named"),
    [
        ([_decomposed(5)], ["decomposition/stdout.jsonl"]),
        ([_proposed(5, 1)], ["decomposition/stdout.jsonl"]),
        ([_proposed(5, 2)], ["decomposition/round-2/stdout.jsonl"]),
        ([_proposed(5, 2, call=2)], ["decomposition/round-2/retry/stdout.jsonl"]),
        (
            [_retried(5), _decomposed(6)],
            ["decomposition/retry/stdout.jsonl", "decomposition/stdout.jsonl"],
        ),
        ([], []),
    ],
    ids=["decomposed", "round 1", "round 2", "round 2's second call", "retried", "none"],
)
def test_each_decomposition_stream_the_log_names_must_be_present(
    tmp_path: Path, events: list[Event], named: list[str]
) -> None:
    """Every call the log records left its stream where the loop puts it; one gone excludes."""
    run = _held_out_run(tmp_path, *events)
    assert decomposition_streams(events) == named
    if named:
        trial = _harness_trial(run)
        assert isinstance(trial, ExcludedTrial), trial
        assert trial.reason == f"stream: {named[0]}, which the log names, is gone"
