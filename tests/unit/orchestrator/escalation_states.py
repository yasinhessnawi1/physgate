"""Small, valid escalation states for the interface's and the backends' tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from physgate.orchestrator.escalation import (
    REGISTER,
    BackendAnswer,
    BackendRow,
    EscalationInterface,
    Question,
    Register,
)
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


#: A backend that ships, for the tests that need a route the rules never give. A stand-in
#: answering as told cannot pass as the rules, whose every answer the replay recomputes, so
#: it is registered under a name of its own for the length of a test.
STAND_IN = BackendRow(
    name="stand_in", status="ships", entry_condition="a test's", evidence=(), version="s/1"
)


def register_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the stand-in in the register as the configuration and the replay read it."""
    register = Register(rows=(*REGISTER.rows, STAND_IN))
    monkeypatch.setattr("physgate.orchestrator.run_config.REGISTER", register)
    monkeypatch.setattr("physgate.orchestrator.replay.REGISTER", register)


@dataclass
class Answering:
    """A backend that answers what it is told and records what it was shown."""

    answer: str = "no"
    confidence: float = 1.0
    shown: list[EscalationState] = field(default_factory=list)

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        self.shown.append(state)
        return BackendAnswer.model_validate({"answer": self.answer, "confidence": self.confidence})


def stand_in(answer: str, confidence: float) -> EscalationInterface:
    """The interface over the registered stand-in, answering ``answer`` at ``confidence``."""
    return EscalationInterface(Answering(answer, confidence), STAND_IN)
