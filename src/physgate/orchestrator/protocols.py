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


class GateResult(_Frozen):
    """What the physics gate hands back for one artefact."""

    verdict: Verdict
    mode: RunningGateMode
    finding: NonEmptyStr
    failing_check: NonEmptyStr | None
    numeric_output: NumericOutput | None
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]

    @model_validator(mode="after")
    def _a_failure_names_its_check(self) -> GateResult:
        if (self.verdict == "fail") != (self.failing_check is not None):
            msg = "a failing verdict names the check that failed, and a pass names none"
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
