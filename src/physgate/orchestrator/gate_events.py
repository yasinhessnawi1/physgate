"""The catch-accounting events: one per gate check, derived from the run-event log.

The architecture asks every gate event to log the check, the value, the node, the
module, and whether the paired reviewer had passed the work (ARCH-083). The gate
writes all of one call's checks inside one line, so a killed process can never
leave half of them on the record; this module derives one event per check from
those lines, the way the task ledger is derived from the same log. Nothing here
writes, so a later reader changes what it derives, never what was recorded.

**Whether a reviewer had passed the work** is filled here, never by the gate,
which runs before any reviewer and cannot know. It comes from a review line of
the same run, and every event says which one (``review_seq``) and on what basis:

- ``same_attempt``: the review of the same subtask's same attempt, on the same
  artefact. The loop reviews after the gate, so it is the first review that
  follows the gate line before the attempt is gated again, resumed or given a new
  session. The injected-error instrument reviews first and blind, so where no
  review follows, it is the last one that precedes the gate line under the same
  bound. Under ``on`` the loop never reviews work the gate refused (ARCH-031),
  so a blocked attempt is honestly ``None``: the field says something about a
  refusal only in ``observe`` runs and in the instrument.
- ``last_writer_of_node``: for the integration call, which no reviewer reviews,
  the review of the merged attempt that last wrote the record's node. A
  propagation failure names the node that changed, so it is stamped from the
  review that approved the change.

A record that names no node, a node only the given design wrote, or an attempt
no reviewer ran on, is ``None``, with no basis.

**Every event also carries the run's manifest id.** A log's lines carry their
own ``run_id``, but not the digest of the configuration the run started under;
that digest is ``RunConfig.sha256()``, the same one ``physgate run``/``resume``
print and the evaluation layer's ``manifest_id_of`` holds every number to. The
caller passes it in rather than this module recomputing it a second way, so a
line printed here ties back to the run it came from exactly as every other
number in this codebase already does.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.common import NonEmptyStr, Timestamp
from physgate.orchestrator.events import (
    Event,
    GateRan,
    IntegrationGateRan,
    Resumed,
    ReviewRan,
    SessionEnded,
    WriteDone,
)
from physgate.orchestrator.protocols import (
    CheckName,
    Count,
    NumericOutput,
    Outcome,
    PassDetails,
    RunningGateMode,
    Scope,
)
from physgate.orchestrator.queue import INTEGRATION

#: How a gate event found the review it was stamped from.
ReviewerBasis = Literal["same_attempt", "last_writer_of_node"]


class GateEvent(BaseModel):
    """One check of one gate call, with the fields catch accounting counts."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: NonEmptyStr
    #: The run's manifest id (``RunConfig.sha256()``): ties this line back to the
    #: run it came from, the same digest every other command's printed number does.
    manifest_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    #: The sequence number of the gate line this event came from.
    seq: Annotated[int, Field(ge=0)]
    ts: Timestamp
    gate_mode: RunningGateMode
    #: The subtask, or ``integration`` for the integration call.
    subtask_id: NonEmptyStr
    attempt: Annotated[int, Field(ge=1)] | None
    check: Annotated[int, Field(ge=1, le=7)]
    name: CheckName
    scope: Scope
    outcome: Outcome
    blocking: bool
    value: NumericOutput | None
    node: NonEmptyStr | None
    module: NonEmptyStr | None
    #: For a pass, how many things the check looked at: a pass over nothing and a
    #: pass over fifty are different evidence. ``None`` for any other outcome.
    evaluated: Count | None
    catalogue_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    #: Whether the paired reviewer passed the artefact this check judged: ``True``,
    #: ``False``, or ``None`` where no review of it exists.
    reviewer_had_passed: bool | None
    #: Which review the verdict comes from, and why that one.
    reviewer_basis: ReviewerBasis | None
    review_seq: Annotated[int, Field(ge=0)] | None
    #: The attempt that review reviewed.
    reviewed_subtask: NonEmptyStr | None
    reviewed_attempt: Annotated[int, Field(ge=1)] | None

    @model_validator(mode="after")
    def _a_verdict_names_its_review(self) -> GateEvent:
        named = (self.reviewer_basis, self.review_seq, self.reviewed_subtask, self.reviewed_attempt)
        present = [x is not None for x in named]
        if all(present) if self.reviewer_had_passed is not None else not any(present):
            return self
        msg = "a reviewer verdict names its review, its basis and its attempt, and only then"
        raise ValueError(msg)


def gate_events(events: Iterable[Event], manifest_id: str) -> list[GateEvent]:
    """One event per check record in every gate line of ``events``, in log order.

    ``manifest_id`` is the run's manifest id (``RunConfig.sha256()``), stamped
    onto every event returned so a reader can tie a line back to its run.
    """
    log = list(events)
    found: list[GateEvent] = []
    for index, event in enumerate(log):
        if isinstance(event, GateRan):
            subtask, attempt = event.subtask_id, event.attempt
            same = _same_attempt_review(log, index, subtask, attempt)
        elif isinstance(event, IntegrationGateRan):
            subtask, attempt, same = INTEGRATION, None, None
        else:
            continue
        for record in event.result.checks:
            basis: ReviewerBasis
            if isinstance(event, IntegrationGateRan):
                review, basis = _last_writer_review(log, record.node), "last_writer_of_node"
            else:
                review, basis = same, "same_attempt"
            found.append(
                GateEvent(
                    run_id=event.run_id,
                    manifest_id=manifest_id,
                    seq=event.seq,
                    ts=event.ts,
                    gate_mode=event.result.mode,
                    subtask_id=subtask,
                    attempt=attempt,
                    check=record.check,
                    name=record.name,
                    scope=record.scope,
                    outcome=record.outcome,
                    blocking=record.blocking,
                    value=record.value,
                    node=record.node,
                    module=record.module,
                    evaluated=(
                        record.details.evaluated
                        if isinstance(record.details, PassDetails)
                        else None
                    ),
                    catalogue_sha256=event.result.catalogue_sha256,
                    reviewer_had_passed=None if review is None else review.result.verdict == "pass",
                    reviewer_basis=None if review is None else basis,
                    review_seq=None if review is None else review.seq,
                    reviewed_subtask=None if review is None else review.subtask_id,
                    reviewed_attempt=None if review is None else review.attempt,
                )
            )
    return found


def _bounds(event: Event, subtask: str, attempt: int) -> bool:
    """Whether ``event`` ends one judging of the attempt: a new gate, a resume, a session."""
    return (
        isinstance(event, GateRan | Resumed | SessionEnded)
        and event.subtask_id == subtask
        and event.attempt == attempt
    )


def _same_attempt_review(
    log: Sequence[Event], index: int, subtask: str, attempt: int
) -> ReviewRan | None:
    """The review of the artefact the gate line at ``index`` judged, if there is one."""
    for event in log[index + 1 :]:
        if _bounds(event, subtask, attempt):
            break
        if isinstance(event, ReviewRan) and (event.subtask_id, event.attempt) == (subtask, attempt):
            return event
    for event in reversed(log[:index]):
        if _bounds(event, subtask, attempt):
            break
        if isinstance(event, ReviewRan) and (event.subtask_id, event.attempt) == (subtask, attempt):
            return event
    return None


def _last_writer_review(log: Sequence[Event], node: str | None) -> ReviewRan | None:
    """The review that approved the attempt which last wrote ``node`` into the store."""
    if node is None:
        return None
    writes = [e for e in log if isinstance(e, WriteDone) and e.node_id == node]
    if not writes:
        return None
    last = max(writes, key=lambda e: e.revision)
    reviews = [
        e
        for e in log
        if isinstance(e, ReviewRan)
        and (e.subtask_id, e.attempt) == (last.subtask_id, last.attempt)
        and e.seq < last.seq
    ]
    return reviews[-1] if reviews else None
