"""The gate's and the reviewer's result shapes, the mode rule and model separation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orch_helpers import ticking_clock
from pydantic import ValidationError

from physgate.orchestrator.common import GateMode
from physgate.orchestrator.events import (
    EventLog,
    GateRan,
    GateSkipped,
    RunStarted,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import GateContractError, ModelSeparationError
from physgate.orchestrator.protocols import (
    Artefact,
    Gate,
    GateResult,
    NumericOutput,
    QuantityRef,
    Reviewer,
    ReviewResult,
    require_mode,
    require_separate_models,
)


def gate_result(**overrides: Any) -> GateResult:
    fields: dict[str, Any] = {
        "verdict": "fail",
        "mode": "on",
        "finding": "the motor's stall current exceeds the driver's rating",
        "failing_check": "bounds",
        "numeric_output": NumericOutput(value=3.1, unit="A"),
        "quantities": (
            QuantityRef(node_id="motor.left", name="stall_current", value=3.1, unit="A"),
        ),
    }
    fields.update(overrides)
    return GateResult(**fields)


def test_a_failing_verdict_names_its_check_and_a_pass_names_none() -> None:
    assert gate_result().failing_check == "bounds"
    with pytest.raises(ValidationError, match="names the check"):
        gate_result(failing_check=None)
    with pytest.raises(ValidationError, match="names the check"):
        gate_result(verdict="pass")
    assert gate_result(verdict="pass", failing_check=None).verdict == "pass"


def test_a_numeric_output_without_a_unit_is_refused() -> None:
    with pytest.raises(ValidationError):
        NumericOutput(value=3.1, unit="")
    with pytest.raises(ValidationError):
        NumericOutput.model_validate({"value": 3.1})
    with pytest.raises(ValidationError):
        NumericOutput(value=float("nan"), unit="A")


def test_at_most_three_quantities_travel_with_a_finding() -> None:
    q = QuantityRef(node_id="motor.left", name="stall_current", value=3.1, unit="A")
    with pytest.raises(ValidationError):
        gate_result(quantities=(q, q, q, q))


def test_a_gate_result_exists_only_for_the_modes_in_which_a_gate_runs() -> None:
    with pytest.raises(ValidationError):
        gate_result(mode="off")


def test_a_reviewer_on_an_alias_is_refused() -> None:
    with pytest.raises(ValidationError, match="full model string"):
        ReviewResult(verdict="pass", finding="fine", reviewer_model="opus", usage=())


def test_a_reviewer_on_the_implementers_model_is_refused() -> None:
    with pytest.raises(ModelSeparationError) as caught:
        require_separate_models(implementer="claude-sonnet-4-5", reviewer="claude-sonnet-4-5")
    assert caught.value.context == {
        "implementer": "claude-sonnet-4-5",
        "reviewer": "claude-sonnet-4-5",
    }
    require_separate_models(implementer="claude-sonnet-4-5", reviewer="claude-opus-5")


def test_a_gate_that_reports_another_mode_breaks_its_contract() -> None:
    assert require_mode(gate_result(), "on").mode == "on"
    with pytest.raises(GateContractError):
        require_mode(gate_result(mode="observe"), "on")


class _TestGate:
    def check(self, artefact: Artefact, *, mode: str) -> GateResult:
        return gate_result(mode=mode)


class _TestReviewer:
    model = "claude-opus-5"

    def review(self, artefact: Artefact) -> ReviewResult:
        return ReviewResult(verdict="pass", finding="ok", reviewer_model=self.model, usage=())


def test_the_protocols_are_structural_so_the_later_specs_register_without_subclassing() -> None:
    assert isinstance(_TestGate(), Gate)
    assert isinstance(_TestReviewer(), Reviewer)
    assert not isinstance(object(), Gate)


def _log(path: Path, mode: GateMode) -> EventLog:
    log = EventLog(path, run_id="run-1", gate_mode=mode, clock=ticking_clock())
    log.emit(RunStarted, config_sha256="c" * 64)
    log.emit(SubtaskPlanned, subtask_id="s1", spec_path="p", assigned_role="r", module_dir="m")
    return log


def test_under_gate_mode_off_no_gate_result_can_be_recorded(tmp_path: Path) -> None:
    log = _log(tmp_path / "e.jsonl", "off")
    for mode in ("on", "observe"):
        with pytest.raises(ValueError, match="gate mode is 'off'"):
            log.emit(GateRan, subtask_id="s1", attempt=1, result=gate_result(mode=mode))
    log.emit(GateSkipped, subtask_id="s1", attempt=1, reason="gate_mode=off")
    log.close()
    assert [e.kind for e in read_events(tmp_path / "e.jsonl")][-1] == "gate_skipped"


@pytest.mark.parametrize("mode", ["on", "observe"])
def test_a_gate_that_runs_cannot_be_recorded_as_skipped_or_in_another_mode(
    tmp_path: Path, mode: GateMode
) -> None:
    log = _log(tmp_path / "e.jsonl", mode)
    with pytest.raises(ValueError, match="skipped"):
        log.emit(GateSkipped, subtask_id="s1", attempt=1, reason="gate_mode=off")
    other = "observe" if mode == "on" else "on"
    with pytest.raises(ValueError, match="gate result in mode"):
        log.emit(GateRan, subtask_id="s1", attempt=1, result=gate_result(mode=other))
    log.emit(GateRan, subtask_id="s1", attempt=1, result=gate_result(mode=mode))
    log.close()
