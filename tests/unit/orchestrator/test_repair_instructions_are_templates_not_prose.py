"""Repair instructions: attempt 1 the finding, attempt 2 plus check and number, 3 none."""

from __future__ import annotations

import re

import pytest

from physgate.orchestrator.exceptions import RepairBudgetExhaustedError
from physgate.orchestrator.protocols import GateResult, NumericOutput, QuantityRef, ReviewResult
from physgate.orchestrator.repair import Finding, repair_instruction

GATE = Finding.from_gate(
    GateResult(
        verdict="fail",
        mode="on",
        finding="the power budget does not balance",
        failing_check="power_balance",
        numeric_output=NumericOutput(value=-1.25, unit="W"),
        quantities=(QuantityRef(node_id="power.budget", name="margin", value=-1.25, unit="W"),),
    )
)
REVIEW = Finding.from_review(
    ReviewResult(
        verdict="fail",
        finding="the loop gain was changed without saying why",
        reviewer_model="claude-opus-5-5",
        session_id="rev-1",
        usage=(),
    )
)


def test_the_first_rejection_returns_the_finding_and_nothing_more() -> None:
    text = repair_instruction(1, GATE)
    assert "the power budget does not balance" in text
    assert "the physics gate" in text
    assert "power_balance" not in text
    assert "-1.25 W" not in text
    assert "2 attempts remain" in text


def test_the_second_rejection_adds_the_failing_check_and_its_number_with_unit() -> None:
    text = repair_instruction(2, GATE)
    assert "Finding: the power budget does not balance" in text
    assert "Failing check: power_balance" in text
    assert "Computed value: -1.25 W" in text
    assert "Quantity: power.budget margin = -1.25 W" in text
    assert "1 attempt remains" in text


def test_a_reviewers_rejection_says_there_was_no_check() -> None:
    text = repair_instruction(2, REVIEW)
    assert "the reviewer" in text
    assert "Failing check: none named" in text
    assert "Computed value: none" in text


@pytest.mark.parametrize("attempt", [3, 4, 0])
def test_the_last_attempt_is_escalated_and_never_repaired(attempt: int) -> None:
    with pytest.raises(RepairBudgetExhaustedError):
        repair_instruction(attempt, GATE)


def test_the_same_finding_always_gives_the_same_words() -> None:
    assert repair_instruction(2, GATE) == repair_instruction(2, GATE)


PROCESS_WORDS = re.compile(
    r"spec_[A-Z][0-9]|\bD-[A-Z0-9]+-[0-9]|\bRQ-|\bM-[0-9]{1,3}\b|\bV-[0-9]|\.docs",
    re.IGNORECASE,
)


@pytest.mark.parametrize("source", ["gate", "review", "write_scope", "proposal", "reading"])
def test_what_an_agent_reads_carries_reasons_not_process_identifiers(source: str) -> None:
    finding = Finding(source=source, text="a reason")  # type: ignore[arg-type]
    for attempt in (1, 2):
        assert not PROCESS_WORDS.search(repair_instruction(attempt, finding))
