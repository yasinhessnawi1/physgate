from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import external_task, own_task

from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.report import ReportError
from physgate.evaluation.per_role.task import parse_task
from physgate.evaluation.per_role.trials import (
    control_trial,
    firmware_trial,
    gate_and_reviews,
    raw_cost,
)
from physgate.orchestrator.events import ReviewRan
from physgate.orchestrator.gate_events import GateEvent
from physgate.orchestrator.protocols import ReviewResult

SECONDARY = [
    {
        "name": "gain_margin_as_ratio",
        "metric": "gain_margin_ratio",
        "op": ">=",
        "bound": {"value": 2, "unit": "1"},
        "counts": "secondary",
        "composes": ["as_recorded"],
    },
    {
        "name": "gain_margin_as_db",
        "metric": "gain_margin_db",
        "op": ">=",
        "bound": {"value": 2, "unit": "dB"},
        "counts": "secondary",
        "composes": ["as_recorded"],
    },
    {
        "name": "overshoot",
        "metric": "overshoot",
        "op": "<=",
        "bound": {"value": 20, "unit": "percent"},
        "counts": "secondary",
        "composes": ["as_recorded"],
    },
]


def _benchmark_task() -> Any:
    raw = external_task()
    raw["specs"] = [*raw["specs"], *SECONDARY]
    return parse_task(json.dumps(raw).encode())


def _score(passed: bool, held: dict[str, bool], *, crossed: bool = True) -> dict[str, Any]:
    rows = [{"name": "stable", "passed": passed}]
    rows += [{"name": name, "passed": value} for name, value in held.items()]
    return {"passed": passed, "flags": {"no_gain_crossover": not crossed}, "specs": rows}


def test_the_secondary_view_is_read_with_the_gain_margin_as_a_ratio_and_in_db() -> None:
    task = _benchmark_task()
    held = {"gain_margin_as_ratio": True, "gain_margin_as_db": False, "overshoot": True}
    outcome, flags = control_trial(task, _score(True, held))
    assert outcome == "pass"
    assert (flags.full_view_ratio, flags.full_view_db) == (True, False)


def test_a_secondary_view_never_passes_where_the_headline_fails() -> None:
    task = _benchmark_task()
    held = dict.fromkeys(("gain_margin_as_ratio", "gain_margin_as_db", "overshoot"), True)
    outcome, flags = control_trial(task, _score(False, held))
    assert outcome == "fail"
    assert (flags.full_view_ratio, flags.full_view_db) == (False, False)


def test_an_answer_that_is_no_controller_fails_both_views_and_flags_nothing() -> None:
    task = _benchmark_task()
    outcome, flags = control_trial(task, {"passed": False, "flags": {}, "specs": []})
    assert outcome == "fail"
    assert flags.model_dump() == {
        "no_gain_crossover": False,
        "full_view_ratio": False,
        "full_view_db": False,
    }


def test_an_own_task_has_no_secondary_view_and_keeps_the_crossover_flag() -> None:
    task = parse_task(json.dumps(own_task()).encode())
    outcome, flags = control_trial(task, _score(True, {}, crossed=False))
    assert outcome == "pass"
    assert flags.full_view_ratio is None
    assert flags.no_gain_crossover is True


def test_a_firmware_trial_counts_its_sandbox_s_error_output_and_its_limit_hits() -> None:
    executions = [
        {"limit": None, "sandbox_stderr_bytes": 0},
        {"limit": "cpu", "sandbox_stderr_bytes": 0},
        {"limit": None, "sandbox_stderr_bytes": 31},
    ]
    outcome, runs = firmware_trial("flaky", executions, infrastructure_ends=1)
    assert outcome == "flaky"
    assert runs.model_dump() == {
        "executions": 3,
        "sandbox_failed": 1,
        "limit_hits": 1,
        "infrastructure_ends": 1,
    }


def test_an_answer_still_to_be_retried_is_not_reported() -> None:
    with pytest.raises(ReportError, match="not final"):
        firmware_trial("retry", [], infrastructure_ends=1)


def test_an_execution_that_did_not_record_its_sandbox_s_error_output_is_refused() -> None:
    with pytest.raises(ReportError, match="sandbox_stderr_bytes"):
        firmware_trial("pass", [{"limit": None}], infrastructure_ends=0)


def _gate(seq: int, subtask: str, *, fails: bool, reviewer: bool | None) -> GateEvent:
    review = (
        {
            "reviewer_basis": "same_attempt",
            "review_seq": seq + 1,
            "reviewed_subtask": subtask,
            "reviewed_attempt": 1,
        }
        if reviewer is not None
        else dict.fromkeys(("reviewer_basis", "review_seq", "reviewed_subtask", "reviewed_attempt"))
    )
    return GateEvent.model_validate(
        {
            "run_id": "r",
            "manifest_id": "e" * 64,
            "seq": seq,
            "ts": "2026-10-18T10:00:00.000000Z",
            "gate_mode": "on",
            "subtask_id": subtask,
            "attempt": 1,
            "check": 2,
            "name": "magnitude",
            "scope": "subtask",
            "outcome": "fail" if fails else "pass",
            "blocking": True,
            "value": None,
            "node": None,
            "module": None,
            "evaluated": None if fails else 3,
            "catalogue_sha256": "c" * 64,
            "reviewer_had_passed": reviewer,
            **review,
        }
    )


def _review(seq: int, verdict: str) -> ReviewRan:
    return ReviewRan(
        seq=seq,
        ts="2026-10-18T10:00:00.000000Z",
        run_id="r",
        gate_mode="on",
        subtask_id="s",
        attempt=1,
        result=ReviewResult.model_validate(
            {
                "verdict": verdict,
                "finding": "read",
                "reviewer_model": "claude-sonnet-5",
                "session_id": f"rev-{seq}",
                "usage": (),
                "spec_defects": (
                    ({"finding": "no input for a safety check", "blocking": True},)
                    if verdict == "blocked"
                    else ()
                ),
            }
        ),
    )


def test_the_gate_s_catches_and_the_reviews_are_counted_as_the_catch_accounting_counts() -> None:
    gate = [
        _gate(0, "s1", fails=True, reviewer=None),
        _gate(2, "s2", fails=True, reviewer=True),
        _gate(4, "s3", fails=False, reviewer=True),
    ]
    reviews = [_review(1, "pass"), _review(3, "fail"), _review(5, "blocked")]
    caught, reviewed = gate_and_reviews(gate, reviews)
    assert caught.model_dump() == {
        "checks_run": 3,
        "artefacts_caught": 2,
        "caught_after_reviewer_passed": 1,
    }
    assert reviewed.model_dump() == {"reviews": 3, "failed": 1, "blocked": 1}


def test_a_run_without_gate_lines_caught_nothing() -> None:
    caught, reviewed = gate_and_reviews([], [])
    assert caught.artefacts_caught == 0
    assert reviewed.reviews == 0


def _stream(path: Path, session: str, *, result: bool, writes: int = 1_000_000) -> None:
    usage = {
        "input_tokens": 1000,
        "cache_creation_input_tokens": writes,
        "cache_read_input_tokens": 0,
        "output_tokens": 1,
    }
    lines: list[dict[str, Any]] = [
        {
            "type": "stream_event",
            "event": {"type": "message_start", "message": {"id": "m1", "usage": usage}},
        },
        {"type": "assistant", "message": {"id": "m1", "model": "claude-opus-5-5", "usage": usage}},
        {
            "type": "stream_event",
            "event": {"type": "message_delta", "usage": {"output_tokens": 1000}},
        },
    ]
    if result:
        lines.append(
            {
                "type": "result",
                "session_id": session,
                "total_cost_usd": 8.024,
                "usage": {
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 0,
                        "ephemeral_1h_input_tokens": writes,
                    }
                },
            }
        )
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_the_raw_session_is_priced_at_the_sheet_with_its_cache_writes_split_as_recorded(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stdout.jsonl"
    _stream(stream, "s-1", result=True)
    sheet = load_price_sheet("2026-10-16")
    cost = raw_cost(stream, "s-1", "claude-opus-5-5", sheet, subscription=True)
    # 1,000 input at $4, 1,000,000 one-hour writes at $8, 1,000 output at $20, per million.
    assert cost.usd == Decimal("8.024")
    assert cost.tokens == 1_002_000
    assert cost.basis == "list_price_estimate"
    assert cost.lower_bound is False


def test_a_raw_session_with_no_result_is_priced_as_a_lower_bound(tmp_path: Path) -> None:
    stream = tmp_path / "stdout.jsonl"
    _stream(stream, "s-1", result=False)
    cost = raw_cost(
        stream, "s-1", "claude-opus-5-5", load_price_sheet("2026-10-16"), subscription=False
    )
    assert cost.lower_bound is True
    assert cost.basis == "list_price"
    # Every write at the five-minute rate, $5 a million.
    assert cost.usd == Decimal("5.024")


def test_a_raw_session_cut_off_before_its_result_is_a_lower_bound_even_with_no_writes(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stdout.jsonl"
    _stream(stream, "s-1", result=False, writes=0)
    cost = raw_cost(
        stream, "s-1", "claude-opus-5-5", load_price_sheet("2026-10-16"), subscription=True
    )
    assert cost.usd == Decimal("0.024")
    assert cost.lower_bound is True


def test_a_model_the_sheet_does_not_price_is_refused(tmp_path: Path) -> None:
    stream = tmp_path / "stdout.jsonl"
    _stream(stream, "s-1", result=True)
    with pytest.raises(ReportError, match="no price"):
        raw_cost(stream, "s-1", "another-model", load_price_sheet("2026-10-16"), subscription=True)
