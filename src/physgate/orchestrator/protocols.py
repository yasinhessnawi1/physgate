"""The gate and the reviewer, as the loop calls them, and what each hands back.

The loop calls a ``Gate`` and then a ``Reviewer``, in that order, and ships no
implementation of either. A gate that passes everything "for now" would make
every downstream test green while enforcing nothing, so there is none: until the
physics gate registers one, the loop refuses to run past the gate stage in any
mode that needs a gate.

The result shapes are frozen here because two later pieces of work implement
them: the physics gate returns a ``GateResult`` and the reviewer a
``ReviewResult``. A repair instruction and an approval-queue item are built from
their fields by code, never phrased by a model.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.common import ModelString, NonEmptyStr
from physgate.orchestrator.exceptions import GateContractError, ModelSeparationError

Count = Annotated[int, Field(ge=0)]

#: The gate modes in which a gate runs. Under ``off`` no gate runs and no result
#: exists at all; the loop records that the stage was skipped and why.
RunningGateMode = Literal["on", "observe"]
Verdict = Literal["pass", "fail"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class NumericOutput(_Frozen):
    """A number a check computed, with its unit. A bare number is not an output."""

    value: float | int
    unit: NonEmptyStr


class QuantityRef(_Frozen):
    """One quantity of one graph node, as a finding cites it."""

    node_id: NonEmptyStr
    name: NonEmptyStr
    value: float | int
    unit: NonEmptyStr


class Usage(_Frozen):
    """Token counts for one model message. Cache reads and writes are separate."""

    input_tokens: Count
    output_tokens: Count
    cache_read_input_tokens: Count
    cache_creation_input_tokens: Count

    def total(self) -> int:
        """Every token the message was charged for."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class MessageUsage(_Frozen):
    """One message's usage, keyed by its id so a repeated message is counted once."""

    message_id: NonEmptyStr
    usage: Usage


class Artefact(_Frozen):
    """What an attempt produced, as the gate and the reviewer receive it."""

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    assigned_role: NonEmptyStr
    attempt_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    worktree: NonEmptyStr
    graph_root: NonEmptyStr
    trajectory: NonEmptyStr
    #: The trajectory's seal from the end of its session, for a reader to hold it to.
    trajectory_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    trajectory_length: Annotated[int, Field(ge=0)] | None = None


#: The architecture's physics checks, by name, with their numbers (ARCH-080).
CheckName = Literal[
    "units", "magnitude", "equilibrium", "power", "conservation", "thermal", "propagation"
]
CHECK_NUMBERS: dict[str, int] = {
    "units": 1,
    "magnitude": 2,
    "equilibrium": 3,
    "power": 4,
    "conservation": 5,
    "thermal": 6,
    "propagation": 7,
}
#: Where a check ran: on one attempt's own nodes, on a module, or on the whole system.
Scope = Literal["subtask", "module", "system"]
#: What one check found. ``unchecked`` is never a pass: it names what no check could judge.
Outcome = Literal["pass", "fail", "warn", "unchecked"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class PassDetails(_Frozen):
    """A check that ran and found nothing wrong, and how many things it looked at."""

    form: Literal["pass"] = "pass"
    evaluated: Count


class UncheckedDetails(_Frozen):
    """The quantities no check could judge beyond what the record says."""

    form: Literal["unchecked"] = "unchecked"
    quantities: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class UnitDetails(_Frozen):
    """Check 1: the offending expression and both unit sides."""

    form: Literal["units"] = "units"
    expression: NonEmptyStr
    left_unit: NonEmptyStr
    right_unit: NonEmptyStr


class MagnitudeDetails(_Frozen):
    """Check 2: the value, its expected range, and where the range comes from."""

    form: Literal["magnitude"] = "magnitude"
    value: NumericOutput
    low: NumericOutput
    high: NumericOutput
    source: NonEmptyStr
    table_sha256: Sha256


class ReactionValue(_Frozen):
    """One support's reaction: a force, and a moment where the support resists one."""

    support: NonEmptyStr
    force: NumericOutput
    moment: NumericOutput | None


class EquilibriumDetails(_Frozen):
    """Check 3: reaction forces and the unbalanced residual."""

    form: Literal["equilibrium"] = "equilibrium"
    solved: tuple[ReactionValue, ...]
    declared: tuple[ReactionValue, ...]
    residual_force: NumericOutput
    residual_moment: NumericOutput
    solver: NonEmptyStr


class PowerDetails(_Frozen):
    """Check 4: the deficit in watts and the nodes that contribute to it."""

    form: Literal["power"] = "power"
    deficit: NumericOutput
    contributing: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class Term(_Frozen):
    """One term of a balance: a node's quantity."""

    node_id: NonEmptyStr
    name: NonEmptyStr
    value: NumericOutput


class ConservationDetails(_Frozen):
    """Check 5: the imbalance and the terms of the balance."""

    form: Literal["conservation"] = "conservation"
    imbalance: NumericOutput
    terms: Annotated[tuple[Term, ...], Field(min_length=1)]


class ThermalDetails(_Frozen):
    """Check 6: the margin, in kelvin or in watts."""

    form: Literal["thermal"] = "thermal"
    margin: NumericOutput


class PropagationDetails(_Frozen):
    """Check 7: the constrained edges a change left unwritten."""

    form: Literal["propagation"] = "propagation"
    unwritten: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


CheckDetails = Annotated[
    PassDetails
    | UncheckedDetails
    | UnitDetails
    | MagnitudeDetails
    | EquilibriumDetails
    | PowerDetails
    | ConservationDetails
    | ThermalDetails
    | PropagationDetails,
    Field(discriminator="form"),
]


class CheckRecord(_Frozen):
    """What one check found at one place, in one gate call (ARCH-080, ARCH-083).

    The gate builds these and the loop carries them in the gate's event line, so
    every check that ran is on the record with what it saw. ``reviewer_had_passed``
    is present and always empty here: the gate runs before any reviewer, and the
    catch-accounting reader fills it from the same attempt's review line, never by
    rewriting this one.
    """

    check: Annotated[int, Field(ge=1, le=7)]
    name: CheckName
    scope: Scope
    outcome: Outcome
    #: Whether a failure of this check blocks at this scope, whatever the run's mode.
    blocking: bool
    node: NonEmptyStr | None
    module: NonEmptyStr | None
    value: NumericOutput | None
    expected: NonEmptyStr | None
    tool: NonEmptyStr
    message: NonEmptyStr
    gate_mode: RunningGateMode
    reviewer_had_passed: None = None
    details: CheckDetails

    @model_validator(mode="after")
    def _consistent(self) -> CheckRecord:
        if CHECK_NUMBERS[self.name] != self.check:
            msg = f"check {self.check} is not the {self.name} check"
            raise ValueError(msg)
        if self.outcome == "warn" and self.blocking:
            msg = "a warning never blocks"
            raise ValueError(msg)
        expected = {"pass": "pass", "unchecked": "unchecked"}.get(self.outcome, self.name)
        if self.details.form != expected:
            msg = f"a {self.outcome} record of the {self.name} check carries {self.details.form}"
            raise ValueError(msg)
        return self


class GateResult(_Frozen):
    """What the physics gate hands back for one artefact.

    ``checks`` holds every check's record, and the verdict follows from them: it
    fails exactly when some check failed where a failure blocks, and
    ``failing_check`` names the first such check. The rule is the same under
    ``observe``: the verdict says what the gate would have refused, and the loop
    decides not to refuse it.
    """

    verdict: Verdict
    mode: RunningGateMode
    finding: NonEmptyStr
    failing_check: NonEmptyStr | None
    numeric_output: NumericOutput | None
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]
    checks: Annotated[tuple[CheckRecord, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _a_failure_names_its_check(self) -> GateResult:
        if (self.verdict == "fail") != (self.failing_check is not None):
            msg = "a failing verdict names the check that failed, and a pass names none"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _the_verdict_is_what_the_records_say(self) -> GateResult:
        if any(record.gate_mode != self.mode for record in self.checks):
            msg = "every check record carries the mode the gate ran in"
            raise ValueError(msg)
        blocking = [r for r in self.checks if r.outcome == "fail" and r.blocking]
        if (self.verdict == "fail") != bool(blocking):
            msg = "the verdict fails exactly when a check failed where its failure blocks"
            raise ValueError(msg)
        if blocking and self.failing_check != blocking[0].name:
            msg = "the failing check is the first check whose failure blocks"
            raise ValueError(msg)
        return self


class ReviewResult(_Frozen):
    """What a reviewer hands back, with the tokens it spent doing it."""

    verdict: Verdict
    finding: NonEmptyStr
    reviewer_model: ModelString
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    usage: tuple[MessageUsage, ...]


@runtime_checkable
class Gate(Protocol):
    """The physics gate: deterministic tooling, never a model (ARCH-004)."""

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        """Check ``artefact`` and say whether it passes."""
        ...


@runtime_checkable
class Reviewer(Protocol):
    """A paired reviewer, on a different model from the implementer (ARCH-060)."""

    @property
    def model(self) -> str:
        """The pinned model string this reviewer runs on."""
        ...

    def review(self, artefact: Artefact) -> ReviewResult:
        """Review ``artefact`` and its full trajectory."""
        ...


def require_separate_models(*, implementer: str, reviewer: str) -> None:
    """Refuse to run a reviewer on the implementer's model string.

    Enforced here, at invocation, rather than trusted to configuration: a judge
    that shares a model with what it judges is the self-preference the
    architecture separates them to avoid.

    Raises:
        ModelSeparationError: the two strings are equal.
    """
    if implementer == reviewer:
        msg = "a reviewer may not run on the implementer's model"
        raise ModelSeparationError(msg, implementer=implementer, reviewer=reviewer)


def require_mode(result: GateResult, mode: RunningGateMode) -> GateResult:
    """Return ``result`` if it is for the mode the gate was asked to run in.

    Raises:
        GateContractError: it reports another mode.
    """
    if result.mode != mode:
        msg = "the gate reported a mode it was not asked to run in"
        raise GateContractError(msg, asked=mode, reported=result.mode)
    return result
