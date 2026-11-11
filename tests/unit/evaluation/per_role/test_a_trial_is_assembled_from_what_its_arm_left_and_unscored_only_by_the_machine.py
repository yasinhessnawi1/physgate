from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.observe.cost import CostLine, load_price_sheet
from physgate.evaluation.per_role.assemble import (
    harness_ended_by_infrastructure,
    harness_trial,
    raw_ended_by_infrastructure,
    raw_trial,
)
from physgate.evaluation.per_role.task import parse_task
from physgate.orchestrator.events import Halted, ReviewRan
from physgate.orchestrator.protocols import ReviewResult

TASK = parse_task(json.dumps(own_task()).encode())
ENV = {"run_id": "r", "gate_mode": "on"}


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
    reason: str, detail: str, machine: bool
) -> None:
    assert harness_ended_by_infrastructure([_halt(reason, detail)], answer_found=False) is machine
    # An answer that exists is scored, however the run ended after it.
    assert harness_ended_by_infrastructure([_halt(reason, detail)], answer_found=True) is False


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
    assert raw_ended_by_infrastructure(record, stream) is machine


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


def test_a_harness_trial_carries_its_score_cost_span_and_reviews() -> None:
    events = [_review(0, "2026-10-19T10:00:00.000000Z"), _halt("incident", seq=1)]
    record = harness_trial(
        suite="control_visible",
        task=TASK,
        trial=2,
        events=events,
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=False,
    )
    assert record.outcome == "pass" and record.trial == 2 and record.arm == "harness"
    assert record.control is not None and record.control.no_gain_crossover
    assert record.cost.tokens == 1160 and record.cost.usd == Decimal("3.50")
    assert record.wall_clock_s == 1800.0
    assert record.review is not None and record.review.failed == 1
    assert record.gate is not None and record.gate.checks_run == 0


def test_a_trial_the_machine_ended_twice_is_unscored_whatever_score_was_passed() -> None:
    record = harness_trial(
        suite="s",
        task=TASK,
        trial=0,
        events=[],
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=SCORED,
        unscored=True,
    )
    assert record.outcome == "unscored"


def test_a_trial_with_no_answer_that_the_machine_did_not_end_is_the_arm_s_fail() -> None:
    record = harness_trial(
        suite="s",
        task=TASK,
        trial=0,
        events=[],
        manifest_id="e" * 64,
        cost=_cost_line(),
        score=None,
        unscored=False,
    )
    assert record.outcome == "fail"


def test_a_raw_trial_is_priced_from_its_stream_and_keeps_its_wall_clock(tmp_path: Path) -> None:
    stream = _stream(tmp_path / "stdout.jsonl", DONE)
    record = raw_trial(
        suite="s",
        task=TASK,
        trial=1,
        record={"session_id": "s-1", "pins": {"model": "claude-opus-5-5"}, "wall_clock_s": 42.5},
        stream=stream,
        prices=load_price_sheet("2026-10-16"),
        subscription=True,
        score={"passed": False, "flags": {}, "specs": []},
        unscored=False,
    )
    assert record.outcome == "fail" and record.arm == "raw" and record.gate is None
    assert record.cost.tokens == 15 and record.wall_clock_s == 42.5
    assert record.cost.basis == "list_price_estimate"
