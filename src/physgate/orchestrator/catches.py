"""The catch count: blocking gate failures on work a reviewer had approved (ARCH-083).

The architecture's headline research quantity is the number of physical errors
the gate caught where the paired reviewer had already passed the work. This
module counts it from the per-check events the run logs yield, per gate mode and
per check, over any set of runs and any window of time, so "weekly" is a query
and not a second record.

**The unit of the headline is the artefact, not the event.** One wrong number
is refused at subtask scope and again over the whole graph at integration, so
counting events would count it twice. An artefact is the attempt a verdict
belongs to: the attempt itself for its own gate lines, and for the integration
call the attempt whose review the event was stamped from. Events are counted
beside it, split by what the reviewer had said.

**The denominator is checks run**, one per gate call, check and scope, not
instances passed: a pass over nothing and a pass over fifty are one check run
each, and the events say how much each looked at.

Rows are split by gate mode because the count means different things in each:
under ``on`` a refused attempt is never reviewed, so its verdict is empty; the
count is interpretable against a run where the gate only observes (ARCH-140).
They are split by the runs' ablation arms too, and name each arm that differs from the
full harness: under ``reviewers: off`` no reviewer passed anything, under ``generalist`` the
reviewer is not the paired one, and under ``skills: off`` or ``hooks: off`` the work was made
by a smaller harness, so a row summing such runs with the full harness's would be about neither.
A row of full-harness runs names no arm, and reads as it always did.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.gate_events import GateEvent
from physgate.orchestrator.protocols import LAST_CHECK, CheckName, RunningGateMode

Count = Annotated[int, Field(ge=0)]
#: One attempt, in one run, that a verdict belongs to.
ArtefactKey = tuple[str, str, int | None]


class CatchRow(BaseModel):
    """The count for one check, or for every check (``all``), in one gate mode."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    gate_mode: RunningGateMode
    check: Annotated[int, Field(ge=1, le=LAST_CHECK)] | None
    name: CheckName | Literal["all"]
    #: Gate calls in which this check ran, one per scope it ran at.
    checks_run: Count
    #: Events: records whose failure blocks at their scope.
    blocking_failures: Count
    #: Of those, the ones whose reviewer had passed, had failed, or had not reviewed.
    reviewer_had_passed: Count
    reviewer_had_failed: Count
    no_review: Count
    #: Distinct artefacts with a blocking failure of this check.
    artefacts_caught: Count
    #: The headline: distinct artefacts caught whose reviewer had passed them.
    caught_after_reviewer_passed: Count
    #: The ablation arms of the runs counted, each left out where they kept that component.
    reviewers: Literal["generalist", "off"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    skills: Literal["off"] | None = Field(default=None, exclude_if=lambda v: v is None)
    hooks: Literal["off"] | None = Field(default=None, exclude_if=lambda v: v is None)


def artefact(event: GateEvent) -> ArtefactKey:
    """The attempt ``event``'s verdict belongs to."""
    if event.reviewer_basis == "last_writer_of_node" and event.reviewed_subtask is not None:
        return (event.run_id, event.reviewed_subtask, event.reviewed_attempt)
    return (event.run_id, event.subtask_id, event.attempt)


def within(event: GateEvent, since: datetime | None, until: datetime | None) -> bool:
    """Whether the gate line ``event`` came from was written in ``[since, until)``."""
    at = parse_time(event.ts)
    return (since is None or at >= since) and (until is None or at < until)


def parse_time(text: str) -> datetime:
    """An ISO date or date-time, in UTC; a bare date is its midnight.

    Raises:
        ValueError: ``text`` is neither.
    """
    stamp = text.removesuffix("Z")
    if "T" not in stamp:
        stamp += "T00:00:00"
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is not None:
        msg = "give the time in UTC, without an offset"
        raise ValueError(msg)
    return parsed


def catches(
    events: Iterable[GateEvent],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[CatchRow]:
    """The count per gate mode, arms and check, then over every check, for ``events`` in the window.

    A mode, set of arms or check with no event in the window has no row, so a run with no gate
    events yields no rows at all. Full-harness rows come first in each mode.
    """
    chosen = [e for e in events if within(e, since, until)]
    rows: list[CatchRow] = []
    for mode in sorted({e.gate_mode for e in chosen}):
        in_mode = [e for e in chosen if e.gate_mode == mode]
        for arm in sorted({_arms(e) for e in in_mode}, key=lambda a: [v or "" for v in a]):
            in_arm = [e for e in in_mode if _arms(e) == arm]
            for check in sorted({e.check for e in in_arm}):
                of_check = [e for e in in_arm if e.check == check]
                rows.append(_row(mode, check, of_check[0].name, of_check))
            rows.append(_row(mode, None, "all", in_arm))
    return rows


def _arms(event: GateEvent) -> tuple[str | None, str | None, str | None]:
    return (event.reviewers, event.skills, event.hooks)


def _row(
    mode: RunningGateMode,
    check: int | None,
    name: CheckName | Literal["all"],
    events: list[GateEvent],
) -> CatchRow:
    blocking = [e for e in events if e.outcome == "fail" and e.blocking]
    caught = {artefact(e) for e in blocking}
    approved = {artefact(e) for e in blocking if e.reviewer_had_passed is True}
    return CatchRow(
        gate_mode=mode,
        check=check,
        name=name,
        checks_run=len({(e.run_id, e.seq, e.check, e.scope) for e in events}),
        blocking_failures=len(blocking),
        reviewer_had_passed=sum(e.reviewer_had_passed is True for e in blocking),
        reviewer_had_failed=sum(e.reviewer_had_passed is False for e in blocking),
        no_review=sum(e.reviewer_had_passed is None for e in blocking),
        artefacts_caught=len(caught),
        caught_after_reviewer_passed=len(approved),
        # One set of arms per row, by the grouping above: the first event's.
        reviewers=events[0].reviewers,
        skills=events[0].skills,
        hooks=events[0].hooks,
    )
