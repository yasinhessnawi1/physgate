"""The paired-versus-generalist ratio, and its line in the cost trend.

``Ratio`` is what ``physgate generalist`` measures and writes to its ``baseline.json``:
paired over generalist tokens and cost, on one attempt read under one seal, n = 1.

``RatioLine`` is that ratio as a line of the cost trend, the append-only, checked file
that already carries every run's cost and its review tokens by subtask
(:mod:`physgate.evaluation.observe.cost`). A line names the generalist review's run, the
paired run it measured, and the digest of the ``baseline.json`` it was read from. Its own
schema refuses a ratio its two reviews' figures do not give, so a line edited by hand,
or written by anything but the one writer, does not read.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physgate.evaluation.observe.manifest import Sha256
from physgate.orchestrator.common import ModelString, NonEmptyStr
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.trajectory import Seal

#: A ratio line's ``kind``: what tells it from a run's cost line in the trend.
RATIO_KIND: Literal["review_ratio"] = "review_ratio"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ReviewCost(_Frozen):
    """One review's spend, priced."""

    rubric_kind: Literal["paired", "generalist"]
    session_id: NonEmptyStr
    tokens: Usage
    usd: Decimal
    nok: Decimal
    peak_context_tokens: Annotated[int, Field(ge=0)] | None


class Ratio(_Frozen):
    """Paired over generalist, on one attempt read under one seal: n = 1."""

    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1, le=3)]
    trajectory_seal: Seal
    attempt_commit: NonEmptyStr
    reviewer_model: ModelString
    paired: ReviewCost
    generalist: ReviewCost
    token_ratio: Decimal
    usd_ratio: Decimal
    prices_date: NonEmptyStr
    prices_sha256: Sha256
    n: Literal[1] = 1


class RatioLine(_Frozen):
    """A ratio as a line of the cost trend, with where it was measured and read from."""

    kind: Literal["review_ratio"]
    #: The generalist review's own run id, and the paired run whose review it measured.
    run_id: NonEmptyStr
    paired_run_id: NonEmptyStr
    #: The ``baseline.json`` the ratio was read from, byte for byte.
    baseline_sha256: Sha256
    ratio: Ratio

    @model_validator(mode="after")
    def _the_ratio_is_its_reviews(self) -> RatioLine:
        r = self.ratio
        if (r.paired.rubric_kind, r.generalist.rubric_kind) != ("paired", "generalist"):
            msg = "a ratio line is one paired review over one generalist review"
            raise ValueError(msg)
        if r.generalist.tokens.total() == 0 or r.generalist.usd == 0:
            msg = "a ratio line's generalist review spent nothing"
            raise ValueError(msg)
        tokens = Decimal(r.paired.tokens.total()) / Decimal(r.generalist.tokens.total())
        if r.token_ratio != tokens or r.usd_ratio != r.paired.usd / r.generalist.usd:
            msg = "a ratio line's ratios are not its two reviews' figures"
            raise ValueError(msg)
        return self
