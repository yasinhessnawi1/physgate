from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
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
from physgate.orchestrator.events import (
    Event,
    Halted,
    Incident,
    ReviewRan,
    RunStarted,
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
