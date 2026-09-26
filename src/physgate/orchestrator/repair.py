"""Repair instructions, written by code from the finding that rejected an attempt.

No model phrases a repair instruction: that would be a model deciding what the
next attempt is told, which is routing. The wording is a fixed template per
attempt (ARCH-030). The first rejection returns the finding. The second returns
the finding, the check that failed and the number it computed, with its unit.
The third is not repaired at all: it goes to the approval queue.

The text is what an agent reads, so it carries reasons and never identifiers
from the process that built this harness.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.budget import REPAIR_BUDGET, require_within_budget
from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.exceptions import RepairBudgetExhaustedError
from physgate.orchestrator.protocols import GateResult, NumericOutput, QuantityRef, ReviewResult

#: What rejected an attempt.
FindingSource = Literal["gate", "review", "write_scope", "proposal", "reading"]

_WHO = {
    "gate": "the physics gate",
    "review": "the reviewer",
    "write_scope": "the write-scope check (an attempt may change only its own module)",
    "proposal": "the design-state store, which refused a proposed node",
    "reading": "the reading check (the required reading was not completed)",
}


class Finding(BaseModel):
    """Why an attempt was rejected, in the fields a repair instruction draws on."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: FindingSource
    text: NonEmptyStr
    #: What the finding is about: the offending paths or node id, or for the gate
    #: the nodes its quantities name. Part of the finding's key, never phrased.
    subject: NonEmptyStr | None = None
    failing_check: NonEmptyStr | None = None
    numeric_output: NumericOutput | None = None
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)] = ()

    @classmethod
    def from_gate(cls, result: GateResult) -> Finding:
        """The finding a failing gate verdict carries."""
        return cls(
            source="gate",
            text=result.finding,
            subject=",".join(sorted({q.node_id for q in result.quantities})) or None,
            failing_check=result.failing_check,
            numeric_output=result.numeric_output,
            quantities=result.quantities,
        )

    @classmethod
    def from_review(cls, result: ReviewResult) -> Finding:
        """The finding a rejecting reviewer carries."""
        return cls(source="review", text=result.finding)

    def key(self) -> str:
        """A stable key for what was found: who refused, about what, by which check.

        Two attempts rejected for the same unfixed thing have the same key, so a
        run can show an agent spending its budget on one finding without anyone
        comparing prose.
        """
        return f"{self.source}|{self.subject or '-'}|{self.failing_check or '-'}"


def _number(output: NumericOutput) -> str:
    return f"{output.value:g} {output.unit}"


def repair_instruction(attempt: int, finding: Finding) -> str:
    """The instruction the next attempt starts from, after ``attempt`` was rejected.

    Raises:
        RepairBudgetExhaustedError: ``attempt`` was the last one; it escalates and
            is not repaired.
    """
    require_within_budget(attempt)
    if attempt == REPAIR_BUDGET:
        msg = "the last attempt is escalated, not repaired"
        raise RepairBudgetExhaustedError(msg, attempt=str(attempt))
    lines = [
        f"Attempt {attempt} of {REPAIR_BUDGET} was rejected by {_WHO[finding.source]}.",
        "",
        f"Finding: {finding.text}",
    ]
    if attempt >= 2:
        check = finding.failing_check or "none named; the rejection came from outside the gate"
        lines.append(f"Failing check: {check}")
        number = (
            _number(finding.numeric_output)
            if finding.numeric_output
            else "none; the check reported no number"
        )
        lines.append(f"Computed value: {number}")
        lines += [
            f"Quantity: {q.node_id} {q.name} = {q.value:g} {q.unit}" for q in finding.quantities
        ]
    remaining = REPAIR_BUDGET - attempt
    lines += [
        "",
        f"Fix what the finding names. {remaining} "
        f"{'attempts remain' if remaining != 1 else 'attempt remains'} "
        "before this goes to a person for a decision.",
    ]
    return "\n".join(lines)
