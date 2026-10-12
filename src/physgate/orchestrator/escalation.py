"""The escalation decision: does this subtask go to the approval queue (ARCH-131, ARCH-132).

The question is asked through one interface, ``decide(question, state)``, which
answers with the backend's answer and confidence, the backend's id and the time it
took. What a backend may decide is bounded here, not in the backend:

- **Forced routes.** Three attempt ends leave the loop nothing else to do: the third
  rejection (a fourth attempt cannot exist, ARCH-030), a blocked review (a repair
  cannot supply what the issued specification lacks) and a review with no verdict
  (there is nothing to merge and no finding to repair). These go to the queue
  whatever a backend answers, so a backend can add an escalation and never remove
  one.
- **The confidence floor.** A confidence below 0.8 goes to the queue whatever the
  answer. The floor belongs to the interface, so every backend is judged by the same
  routing rule.

A backend enters only by name, through the register, with a status and an entry
condition. Only a row that ships can be bound. ``rules`` is the one that does: the
loop's own conditions expressed through the interface, at confidence 1.0, so with it
the queue receives exactly what it received before the interface existed.

No backend may read or write the design-state graph, spend a token on the decision,
or be chosen from the environment. This module therefore imports nothing that reads
the graph or the environment and nothing that can reach a model, and a test holds
its imports to a list. A backend sees only the state it is handed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.budget import after_rejection
from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.escalation_state import AttemptEnd, EscalationState
from physgate.orchestrator.exceptions import EscalationBackendError

#: ARCH-131's routing threshold: a confidence below it goes to a person.
CONFIDENCE_FLOOR: Final = 0.8

#: The question kinds ARCH-131 names; only ``yes_no`` is asked in the first slice.
QuestionKind = Literal["yes_no"]
Answer = Literal["yes", "no"]
#: Why a decision routes to the queue: a forced route, the answer, or the floor.
RouteBasis = Literal["forced", "answer", "floor"]
#: A register row's standing (ARCH-132).
Status = Literal["ships", "off", "parked"]
BackendName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class Question(_Frozen):
    """What is asked."""

    kind: QuestionKind
    asks: Literal["approval_queue"]


#: The one question the loop asks.
TO_THE_QUEUE: Final = Question(kind="yes_no", asks="approval_queue")


class EndOfAttempt(Protocol):
    """What the interface itself reads from the state: how the attempt ended, and which it was."""

    @property
    def attempt_end(self) -> AttemptEnd:
        """How the attempt ended."""
        ...

    @property
    def attempt_count(self) -> int:
        """The attempt's number."""
        ...


class BackendAnswer(_Frozen):
    """What a backend answers."""

    answer: Answer
    confidence: Confidence


class Backend(Protocol):
    """An escalation backend: answers the question from the state alone."""

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        """Answer ``question`` for ``state``."""
        ...


def forced(state: EndOfAttempt) -> bool:
    """Whether the attempt end leaves the loop nothing to do but ask a person.

    The third rejection is read off the repair budget's own rule, so the budget is
    stated once.
    """
    if state.attempt_end == "rejected":
        return after_rejection(state.attempt_count) is None
    return True


def route(*, forced: bool, answer: Answer, confidence: float) -> RouteBasis | None:
    """Why the decision goes to the queue, or ``None`` if it does not."""
    if forced:
        return "forced"
    if answer == "yes":
        return "answer"
    if confidence < CONFIDENCE_FLOOR:
        return "floor"
    return None


class Decision(_Frozen):
    """One call's record: ARCH-131's answer, confidence, backend id and latency, and the route."""

    question: Question
    answer: Answer
    confidence: Confidence
    backend_id: BackendName
    backend_version: NonEmptyStr
    latency_ms: Annotated[float, Field(ge=0.0)]
    forced: bool
    basis: RouteBasis | None

    @property
    def routed(self) -> bool:
        """Whether the subtask goes to the approval queue."""
        return self.basis is not None

    @model_validator(mode="after")
    def _the_route_follows_the_rule(self) -> Decision:
        expected = route(forced=self.forced, answer=self.answer, confidence=self.confidence)
        if self.basis != expected:
            msg = f"a decision routed by {self.basis!r} where the rule gives {expected!r}"
            raise ValueError(msg)
        return self


class BackendRow(_Frozen):
    """One register row (ARCH-132): a name, a status, an entry condition and its evidence."""

    name: BackendName
    status: Status
    entry_condition: NonEmptyStr
    #: The experiments the row's status rests on.
    evidence: tuple[NonEmptyStr, ...]
    #: The version a run records with each decision; ``None`` while nothing is built.
    version: NonEmptyStr | None

    @model_validator(mode="after")
    def _a_shipping_row_has_a_version(self) -> BackendRow:
        if self.status == "ships" and self.version is None:
            msg = "a backend that ships names the version a run records"
            raise ValueError(msg)
        return self


class Register(_Frozen):
    """The backend register: every backend that may ever be named, by name."""

    rows: tuple[BackendRow, ...]

    @model_validator(mode="after")
    def _names_are_unique(self) -> Register:
        names = [row.name for row in self.rows]
        if len(set(names)) != len(names):
            msg = "a backend is named twice in the register"
            raise ValueError(msg)
        return self

    def row(self, name: str) -> BackendRow:
        """The row for ``name``.

        Raises:
            EscalationBackendError: the register has no such row.
        """
        for row in self.rows:
            if row.name == name:
                return row
        msg = "the escalation backend register has no row for this name"
        raise EscalationBackendError(msg, backend=name)


#: The register as ARCH-132 states it. Only ``rules`` ships.
REGISTER: Final = Register(
    rows=(
        BackendRow(
            name="rules",
            status="ships",
            entry_condition=(
                "none: the loop's own conditions through the interface (the repair budget, "
                "ARCH-030, and a review that is blocked or reaches no verdict), at confidence 1.0"
            ),
            evidence=(),
            version="rules/1",
        ),
        BackendRow(
            name="llm",
            status="off",
            entry_condition=(
                "cannot be enabled while ARCH-131 admits only a binding that spends no tokens on "
                "the decision; a model call per decision is exactly such a spend"
            ),
            evidence=(),
            version=None,
        ),
        BackendRow(
            name="tsetlin",
            status="parked",
            entry_condition=(
                "a pre-registered experiment with a generator and a novelty type no earlier run "
                "has seen, judged on calibration paired with humility off distribution; the "
                "evidence so far was gathered on a generated state, not the system's own"
            ),
            evidence=("R-TM-01", "R-LAYA-01"),
            version=None,
        ),
        BackendRow(
            name="laya",
            status="parked",
            entry_condition=(
                "a pre-registered experiment's pass on calibration, humility off distribution, "
                "selective accuracy and latency together; it answered every state at confidence "
                "1.0 and failed humility on both unseen sets, on a generated state"
            ),
            evidence=("R-LAYA-01",),
            version=None,
        ),
    )
)


class RulesBackend:
    """The default binding: escalate exactly when the loop has nothing else to do."""

    def decide(self, question: Question, state: EscalationState) -> BackendAnswer:
        """Yes on a forced route, no otherwise, always at confidence 1.0."""
        return BackendAnswer(answer="yes" if forced(state) else "no", confidence=1.0)


#: How each backend that ships is built. A name with no entry here cannot be bound.
IMPLEMENTATIONS: Final[dict[str, Callable[[], Backend]]] = {"rules": RulesBackend}


class EscalationInterface:
    """The one place the question is asked: the backend's answer, timed, under the routing rule."""

    def __init__(
        self,
        backend: Backend,
        row: BackendRow,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        """Ask ``backend``, recorded under ``row``; ``clock`` reads monotonic nanoseconds.

        Raises:
            EscalationBackendError: the row does not ship.
        """
        if row.status != "ships" or row.version is None:
            msg = "only a backend whose register row ships can be asked"
            raise EscalationBackendError(msg, backend=row.name, status=row.status)
        self._backend = backend
        self._row = row
        self._version: str = row.version
        self._clock = clock

    @property
    def backend_id(self) -> str:
        """The register name of the backend this interface asks."""
        return self._row.name

    def decide(self, question: Question, state: EscalationState) -> Decision:
        """Ask the backend, and route by the forced routes, the answer and the floor.

        Raises:
            EscalationBackendError: the backend answered with something that is not an
                answer, or the clock ran backwards.
        """
        start = self._clock()
        answered = self._backend.decide(question, state)
        end = self._clock()
        if not isinstance(answered, BackendAnswer):
            msg = "an escalation backend answered with something that is not an answer"
            raise EscalationBackendError(msg, backend=self._row.name)
        if end < start:
            msg = "the latency clock ran backwards"
            raise EscalationBackendError(msg, backend=self._row.name)
        must = forced(state)
        return Decision(
            question=question,
            answer=answered.answer,
            confidence=answered.confidence,
            backend_id=self._row.name,
            backend_version=self._version,
            latency_ms=(end - start) / 1_000_000,
            forced=must,
            basis=route(forced=must, answer=answered.answer, confidence=answered.confidence),
        )


def bind(
    name: str,
    *,
    register: Register = REGISTER,
    implementations: dict[str, Callable[[], Backend]] = IMPLEMENTATIONS,
) -> EscalationInterface:
    """The interface over the backend a run names.

    Whether the row ships is checked once, by the interface itself, so a backend built
    some other way is held to the same rule.

    Raises:
        EscalationBackendError: the register has no row for ``name``, nothing implements
            it, or its row does not ship.
    """
    row = register.row(name)
    build = implementations.get(name)
    if build is None:
        msg = "no implementation exists for this escalation backend"
        raise EscalationBackendError(msg, backend=name)
    return EscalationInterface(build(), row)
