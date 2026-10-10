"""The routing rule is the interface's, whatever backend answers (ARCH-131).

A confidence below 0.8 goes to the approval queue whatever the answer, and three
attempt ends go there whatever the backend says: the third rejection, a blocked
review, a review with no verdict. Every case here asks a stand-in backend that is
not ``rules``, so a floor or a forced route that lives in ``rules`` instead of the
interface cannot pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import count

import pytest
from pydantic import ValidationError

from physgate.orchestrator.escalation import (
    CONFIDENCE_FLOOR,
    REGISTER,
    TO_THE_QUEUE,
    AttemptEnd,
    BackendAnswer,
    BackendRow,
    Decision,
    EndOfAttempt,
    EscalationInterface,
    Question,
)
from physgate.orchestrator.exceptions import EscalationBackendError

ROW = BackendRow(
    name="stand_in",
    status="ships",
    entry_condition="a test's stand-in, never in the register",
    evidence=(),
    version="stand_in/1",
)


@dataclass(frozen=True)
class End:
    attempt_end: AttemptEnd
    attempt_count: int


@dataclass
class Answers:
    """A backend that answers what it is told to, and is not ``rules``."""

    answer: str
    confidence: float
    asked: list[EndOfAttempt]

    def decide(self, question: Question, state: EndOfAttempt) -> BackendAnswer:
        self.asked.append(state)
        return BackendAnswer.model_validate({"answer": self.answer, "confidence": self.confidence})


def ask(answer: str, confidence: float, end: End) -> Decision:
    backend = Answers(answer, confidence, [])
    return EscalationInterface(backend, ROW).decide(TO_THE_QUEUE, end)


def test_the_floor_is_arch_131_s() -> None:
    assert CONFIDENCE_FLOOR == 0.8


@pytest.mark.parametrize(
    ("answer", "confidence", "basis"),
    [
        ("no", 0.79, "floor"),
        ("no", 0.0, "floor"),
        ("no", 0.8, None),
        ("no", 0.81, None),
        ("no", 1.0, None),
        ("yes", 0.79, "answer"),
        ("yes", 1.0, "answer"),
    ],
)
def test_below_the_floor_goes_to_the_queue_whatever_the_answer(
    answer: str, confidence: float, basis: str | None
) -> None:
    decision = ask(answer, confidence, End("rejected", 1))
    assert decision.basis == basis
    assert decision.routed is (basis is not None)
    assert decision.forced is False


@pytest.mark.parametrize(
    "end",
    [End("rejected", 3), End("review_blocked", 1), End("review_unavailable", 2)],
    ids=["third_rejection", "blocked", "unavailable"],
)
@pytest.mark.parametrize(("answer", "confidence"), [("no", 1.0), ("no", 0.0), ("yes", 1.0)])
def test_a_forced_route_goes_to_the_queue_whatever_the_backend_says(
    end: End, answer: str, confidence: float
) -> None:
    decision = ask(answer, confidence, end)
    assert decision.forced is True
    assert decision.basis == "forced"
    assert decision.routed is True


@pytest.mark.parametrize("attempt", [1, 2])
def test_a_rejection_with_budget_left_is_the_backend_s_to_decide(attempt: int) -> None:
    assert ask("no", 1.0, End("rejected", attempt)).routed is False
    assert ask("yes", 1.0, End("rejected", attempt)).routed is True


def test_the_record_carries_what_arch_131_names_and_the_backend_is_asked_once() -> None:
    backend = Answers("no", 0.9, [])
    ticks = count(start=1_000_000, step=2_500_000)
    interface = EscalationInterface(backend, ROW, clock=lambda: next(ticks))
    end = End("rejected", 2)
    decision = interface.decide(TO_THE_QUEUE, end)
    assert backend.asked == [end]
    assert (decision.answer, decision.confidence) == ("no", 0.9)
    assert (decision.backend_id, decision.backend_version) == ("stand_in", "stand_in/1")
    assert decision.latency_ms == 2.5
    assert decision.question == TO_THE_QUEUE
    assert interface.backend_id == "stand_in"


def test_a_backend_answering_with_something_else_is_refused() -> None:
    class Loose:
        def decide(self, question: Question, state: EndOfAttempt) -> BackendAnswer:
            return {"answer": "no", "confidence": 1.0}  # type: ignore[return-value]

    with pytest.raises(EscalationBackendError):
        EscalationInterface(Loose(), ROW).decide(TO_THE_QUEUE, End("rejected", 1))


def test_a_clock_that_runs_backwards_is_refused() -> None:
    ticks = iter([5, 4])
    interface = EscalationInterface(Answers("no", 1.0, []), ROW, clock=lambda: next(ticks))
    with pytest.raises(EscalationBackendError):
        interface.decide(TO_THE_QUEUE, End("rejected", 1))


@pytest.mark.parametrize("confidence", [math.nan, math.inf, -0.01, 1.01])
def test_a_confidence_outside_zero_to_one_is_not_an_answer(confidence: float) -> None:
    with pytest.raises(ValidationError):
        BackendAnswer(answer="no", confidence=confidence)


def test_a_decision_whose_route_breaks_the_rule_cannot_be_recorded() -> None:
    fields = {
        "question": TO_THE_QUEUE,
        "answer": "no",
        "confidence": 0.5,
        "backend_id": "rules",
        "backend_version": "rules/1",
        "latency_ms": 0.0,
        "forced": False,
    }
    assert Decision(**fields, basis="floor").routed  # type: ignore[arg-type]
    for wrong in (None, "answer", "forced"):
        with pytest.raises(ValidationError):
            Decision(**fields, basis=wrong)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Decision(**{**fields, "forced": True}, basis="floor")  # type: ignore[arg-type]


def test_an_interface_refuses_a_row_that_does_not_ship() -> None:
    for name in ("llm", "tsetlin", "laya"):
        with pytest.raises(EscalationBackendError):
            EscalationInterface(Answers("no", 1.0, []), REGISTER.row(name))
