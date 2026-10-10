"""Small, valid escalation states for the interface's and the backends' tests."""

from __future__ import annotations

from physgate.orchestrator.escalation_state import (
    AttemptEnd,
    ChangesPart,
    EndPart,
    EscalationState,
    LedgerPart,
)


def ended(kind: AttemptEnd, attempt: int) -> EscalationState:
    """The state of attempt ``attempt``, which ended as ``kind``, with nothing else recorded."""
    rejected = kind == "rejected"
    return EscalationState(
        ledger=LedgerPart(
            subtask_id="s1",
            assigned_role="electrical",
            attempt_count=attempt,
            gate_result="pass",
            review_result="fail" if rejected else "blocked" if kind == "review_blocked" else None,
        ),
        ended=EndPart(
            kind=kind,
            rejected_by="review" if rejected else None,
            repeats_previous=False if rejected else None,
            unavailable_cause="refused" if kind == "review_unavailable" else None,
            review_retried=False,
        ),
        changes=ChangesPart(refused_by=None, proposed=()),
        gate=None,
        review=None,
    )
