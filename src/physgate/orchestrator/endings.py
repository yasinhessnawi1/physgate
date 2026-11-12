"""How each round of a reviewed decomposition ends, classified in code, plan and review apart.

A round is one decomposition call, the start check its plan meets, and the design review of a plan
that passes it. Its plan ends in a plan, in a no-plan outcome (the designer's: the call gave no
usable plan, or one the run cannot start for its own content), or in infrastructure (the
instrument's: the endpoint, the binary, the library, the target repository). Its review, recorded
apart from the plan's ending, ends in a verdict, in no verdict (the review's own outcome), in
infrastructure (a session that could not run or be prepared, a reviewer on the designer's model),
or in a held-out exposure. An experiment freezes one table of these classes; the code is held to
it cause by cause, so no ending is classed by whoever reads the run.

A canary found in a non-pass verdict's findings is no ending of its own: the verdict stands, and
the round records that its findings carried marked material, which no prompt may then carry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from physgate.orchestrator.decompose import FailureCause
from physgate.orchestrator.protocols import ReviewVerdict, UnavailableCause

#: Every cause a round's plan call or its start check ends with but a plan.
PlanCause = FailureCause | Literal["plan_refused", "library_refused"]
#: What a round's plan came to: a plan, the designer's no-plan outcome, or the instrument's failure.
PlanClass = Literal["plan", "no_plan", "infrastructure"]
#: Every way a round's review ends: a verdict, why there is none, or why it never ran as a review.
ReviewCause = (
    ReviewVerdict
    | UnavailableCause
    | Literal["invocation_error", "model_separation", "held_out_exposed"]
)
#: What a round's review came to.
ReviewClass = Literal["verdict", "unavailable", "infrastructure", "exposure"]
#: Which marked material a non-pass verdict's findings carried.
Canary = Literal["held_out", "review_material"]
#: The run-level voids, outside any round's table: a result whose totals are not its usage (on
#: either call), a decomposition killed mid-loop, a plan file whose digest is not its line's, a
#: record that is missing. Each is the instrument's, never the designer's or the reviewer's.
RunVoidCause = Literal["accounting_mismatch", "killed", "plan_digest_mismatch", "record_missing"]
RUN_VOIDS: frozenset[str] = frozenset(get_args(RunVoidCause))

#: The causes that are the designer's. ``wall_clock`` is among them: the designer ran out of time.
_NO_PLAN: frozenset[str] = frozenset(
    {
        "no_structured_output",
        "invalid_plan",
        "schema_refused",
        "wall_clock",
        "turn_limit",
        "malformed_output",
        "context_exceeded",
        "refused",
        "plan_refused",
    }
)
#: A spent budget is the designer's only where the run set the budget on it.
_BUDGET = "budget_exhausted"

#: Each review cause's class. ``unprepared`` (the plan's packet could not be built or checked) is
#: the instrument's, never the designer's or the reviewer's.
REVIEW_CLASSES: Mapping[str, ReviewClass] = {
    **dict.fromkeys(get_args(ReviewVerdict), "verdict"),
    **dict.fromkeys(
        (
            "refused",
            "no_verdict",
            "invalid_verdict",
            "reading_incomplete",
            "compacted",
            "context_exceeded",
        ),
        "unavailable",
    ),
    **dict.fromkeys(
        ("infrastructure", "unprepared", "invocation_error", "model_separation"),
        "infrastructure",
    ),
    "held_out_exposed": "exposure",
}


def plan_class(cause: PlanCause | None, *, budget_set: bool) -> PlanClass:
    """The class of a round's plan ending: ``None`` is a plan.

    ``budget_set``: the run set a spending budget on the designer's call, so a spent one is the
    designer's; without one it can only be the instrument's.
    """
    if cause is None:
        return "plan"
    if cause == _BUDGET:
        return "no_plan" if budget_set else "infrastructure"
    return "no_plan" if cause in _NO_PLAN else "infrastructure"


def review_class(cause: ReviewCause) -> ReviewClass:
    """The class of a round's review ending."""
    return REVIEW_CLASSES[cause]


class RoundEnding(BaseModel):
    """How one round ended: its plan's ending and its review's, each with its cause and class.

    Only a round that has a plan has a review, and it always ends one way or another; a canary is
    recorded only on findings a re-plan would carry, a verdict that is not a pass.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    plan_cause: PlanCause | None
    plan_class: PlanClass
    review_cause: ReviewCause | None
    review_class: ReviewClass | None
    canary: Canary | None = None

    @model_validator(mode="after")
    def _as_the_table_classes_it(self) -> RoundEnding:
        allowed = (
            {"no_plan", "infrastructure"}
            if self.plan_cause == _BUDGET
            else {plan_class(self.plan_cause, budget_set=False)}
        )
        if self.plan_class not in allowed:
            msg = f"a plan that ended {self.plan_cause} is not of class {self.plan_class}"
            raise ValueError(msg)
        if (self.plan_class == "plan") != (self.review_cause is not None):
            msg = "a round's review ends exactly when the round has a plan"
            raise ValueError(msg)
        expected = None if self.review_cause is None else review_class(self.review_cause)
        if self.review_class != expected:
            msg = f"a review that ended {self.review_cause} is not of class {self.review_class}"
            raise ValueError(msg)
        if self.canary is not None and self.review_cause not in ("fail", "blocked"):
            msg = "a canary is looked for only in a non-pass verdict's findings"
            raise ValueError(msg)
        return self


def round_ending(
    plan_cause: PlanCause | None,
    review_cause: ReviewCause | None = None,
    *,
    budget_set: bool,
    canary: Canary | None = None,
) -> RoundEnding:
    """A round's ending, each side classified by the table.

    Raises:
        ValueError: the two sides are not an ending a round can have.
    """
    return RoundEnding(
        plan_cause=plan_cause,
        plan_class=plan_class(plan_cause, budget_set=budget_set),
        review_cause=review_cause,
        review_class=None if review_cause is None else review_class(review_cause),
        canary=canary,
    )


#: What follows a round: another round, the run started from it (held or not, as its review and
#: the run's mode say), the run recorded as a failed decomposition, or no run at all.
Follows = Literal["replan", "start", "fail_run", "void"]
#: The review's endings that are no review at all: void in every mode that reviews its plan.
_NEVER_A_REVIEW = frozenset({"invocation_error", "model_separation"})


def what_follows(ending: RoundEnding, *, last: bool, holds: bool) -> Follows:
    """What follows a round, from its ending and whether it is the last its run may have alone.

    ``holds``: the run holds a plan its review did not pass (every reviewing mode but
    ``observe``), where the instrument's failure is never recorded as a review. A verdict other
    than a pass is re-planned while a round remains and no canary is in its findings; every
    other review ending starts the run, which holds or halts as its record says.
    """
    if ending.plan_class == "infrastructure":
        return "void" if holds or ending.plan_cause == "library_refused" else "fail_run"
    if ending.plan_class == "no_plan":
        return "fail_run"
    if ending.review_class == "infrastructure":
        return "void" if holds or ending.review_cause in _NEVER_A_REVIEW else "start"
    replan = ending.review_cause in ("fail", "blocked") and ending.canary is None and not last
    return "replan" if replan else "start"
