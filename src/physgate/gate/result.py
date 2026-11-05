"""What one check reports to the runner, before the runner stamps it into a record.

A check says what it saw and nothing about where it ran or in which mode: the
runner knows both, and is the only place that turns an observation into a
:class:`~physgate.orchestrator.protocols.CheckRecord`. So no record can leave the
gate without the mode on it, and a check cannot decide for itself whether its
failure blocks: that is the architecture's table, applied by the runner.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physgate.orchestrator.protocols import CheckDetails, NumericOutput, QuantityRef

_Text = Annotated[str, Field(min_length=1)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class Observation(_Frozen):
    """Something wrong, or something no check could judge, at one place in the graph.

    A pass is not an observation: a check that observed nothing wrong has passed,
    and the runner records that with the number of things it looked at.
    """

    outcome: Literal["fail", "unchecked"]
    node: _Text | None
    module: _Text | None
    value: NumericOutput | None
    expected: _Text | None
    message: _Text
    details: CheckDetails
    #: The quantities the finding is about, most relevant first, for the repair
    #: instruction and the approval queue.
    quantities: tuple[QuantityRef, ...] = ()


class LawCount(_Frozen):
    """How many instances of one law the laws check evaluated at one scope."""

    law_id: _Text
    evaluated: Annotated[int, Field(ge=0)]


class CheckRun(_Frozen):
    """What one check reported at one scope.

    The laws check also reports each law's own count, every law it holds listed once, so the
    runner can state each law's reach even where another law failed. Their sum is its count.
    """

    tool: _Text
    evaluated: Annotated[int, Field(ge=0)]
    observations: tuple[Observation, ...]
    law_evaluated: tuple[LawCount, ...] = ()

    @model_validator(mode="after")
    def _the_laws_add_up(self) -> CheckRun:
        ids = [c.law_id for c in self.law_evaluated]
        if len(set(ids)) != len(ids):
            msg = "a law is counted twice"
            raise ValueError(msg)
        if self.law_evaluated and sum(c.evaluated for c in self.law_evaluated) != self.evaluated:
            msg = "the laws' counts do not add up to the check's"
            raise ValueError(msg)
        return self
