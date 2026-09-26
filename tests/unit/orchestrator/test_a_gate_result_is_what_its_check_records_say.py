"""Per-check records: every one stamped with the mode, and the verdict read off them."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from physgate.orchestrator.protocols import (
    CheckRecord,
    GateResult,
    NumericOutput,
    PassDetails,
    ThermalDetails,
    UncheckedDetails,
)


def record(**overrides: Any) -> CheckRecord:
    fields: dict[str, Any] = {
        "check": 6,
        "name": "thermal",
        "scope": "system",
        "outcome": "fail",
        "blocking": True,
        "node": "electrical.driver",
        "module": "electrical.drive",
        "value": NumericOutput(value=-4, unit="K"),
        "expected": "a margin of at least 0 K",
        "tool": "graph arithmetic",
        "message": "the driver runs 4 K above its limit",
        "gate_mode": "on",
        "details": ThermalDetails(margin=NumericOutput(value=-4, unit="K")),
    }
    fields.update(overrides)
    return CheckRecord(**fields)


def result(*checks: CheckRecord, **overrides: Any) -> GateResult:
    fields: dict[str, Any] = {
        "verdict": "fail",
        "mode": "on",
        "finding": "the driver runs 4 K above its limit",
        "failing_check": "thermal",
        "numeric_output": None,
        "quantities": (),
        "checks": checks,
        "catalogue_sha256": "c" * 64,
    }
    fields.update(overrides)
    return GateResult(**fields)


def test_a_record_carries_the_mode_and_an_empty_reviewer_field() -> None:
    dumped = record().model_dump()
    assert dumped["gate_mode"] == "on"
    assert "reviewer_had_passed" in dumped and dumped["reviewer_had_passed"] is None


def test_a_record_without_a_mode_is_refused() -> None:
    fields = record().model_dump()
    del fields["gate_mode"]
    with pytest.raises(ValidationError):
        CheckRecord.model_validate(fields)


def test_a_record_in_a_mode_no_gate_runs_in_is_refused() -> None:
    with pytest.raises(ValidationError):
        record(gate_mode="off")


def test_the_gate_cannot_claim_a_reviewer_verdict() -> None:
    with pytest.raises(ValidationError):
        record(reviewer_had_passed=True)


def test_a_record_whose_number_is_not_its_check_is_refused() -> None:
    with pytest.raises(ValidationError, match="is not the thermal check"):
        record(check=4)


def test_a_warning_never_blocks() -> None:
    assert record(outcome="warn", blocking=False).outcome == "warn"
    with pytest.raises(ValidationError, match="never blocks"):
        record(outcome="warn", blocking=True)


def test_a_record_carries_the_details_of_its_outcome_and_its_check() -> None:
    with pytest.raises(ValidationError, match="carries pass"):
        record(details=PassDetails(evaluated=3))
    with pytest.raises(ValidationError, match="carries thermal"):
        record(outcome="pass")
    assert record(outcome="pass", details=PassDetails(evaluated=3)).outcome == "pass"
    unchecked = record(outcome="unchecked", details=UncheckedDetails(quantities=("gizmo",)))
    assert unchecked.outcome == "unchecked"


def test_a_result_fails_exactly_when_a_check_failed_where_it_blocks() -> None:
    assert result(record()).verdict == "fail"
    with pytest.raises(ValidationError, match="fails exactly when"):
        result(record(), verdict="pass", failing_check=None)
    passed = record(outcome="pass", details=PassDetails(evaluated=1))
    assert result(passed, verdict="pass", failing_check=None).verdict == "pass"
    with pytest.raises(ValidationError, match="fails exactly when"):
        result(passed)


def test_a_failure_that_does_not_block_here_does_not_fail_the_result() -> None:
    warned = record(outcome="warn", blocking=False, scope="module")
    unblocking = record(blocking=False, scope="module")
    assert result(warned, unblocking, verdict="pass", failing_check=None).verdict == "pass"


def test_the_failing_check_is_the_first_blocking_failure() -> None:
    with pytest.raises(ValidationError, match="first check whose failure blocks"):
        result(record(), failing_check="power")


def test_every_record_is_in_the_mode_of_its_result() -> None:
    with pytest.raises(ValidationError, match="carries the mode"):
        result(record(gate_mode="observe"))
    observed = record(gate_mode="observe")
    assert result(observed, mode="observe").verdict == "fail"


def test_a_result_with_no_records_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(verdict="pass", failing_check=None)


def test_a_result_names_the_catalogue_that_judged_it() -> None:
    assert result(record()).catalogue_sha256 == "c" * 64
    with pytest.raises(ValidationError):
        result(record(), catalogue_sha256="not a digest")
    fields = result(record()).model_dump()
    del fields["catalogue_sha256"]
    with pytest.raises(ValidationError):
        GateResult.model_validate(fields)
