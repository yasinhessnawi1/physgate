"""A reviewed run's one round, journalled as ``decompose`` journals it, for rigs that start a run.

A rig that starts a reviewing run without the command writes what the rounds would have: round
1's start and end lines, its plan file, and the terminal line naming what followed. It gets the
round's proposal back, for the run's opening. The run then opens as one ``decompose`` started:
each round's call spent what the rig's opening records it spending, and round 1 names the run's
``design_review`` mode and its designer's model, as the run's configuration does.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from physgate.orchestrator.common import utc_now, utc_stamp
from physgate.orchestrator.design_rounds import (
    Elapsed,
    RoundEnded,
    RoundsEnded,
    RoundStarted,
    plan_path,
)
from physgate.orchestrator.endings import round_ending, what_follows
from physgate.orchestrator.protocols import MessageUsage
from physgate.orchestrator.record import Proposal, RoundReview

JOURNAL = ("decomposition", "rounds.jsonl")


#: One round as a rig gives it: its call's session, plan bytes, review and what the call spent.
Given = tuple[str, bytes, RoundReview, tuple[MessageUsage, ...]]


def one_round(
    run_dir: Path,
    *,
    session: str,
    plan: bytes,
    reviewed: RoundReview,
    spent: tuple[MessageUsage, ...],
    design_review: str,
    holds: bool = True,
    model: str = "claude-sonnet-5",
) -> tuple[Proposal, ...]:
    """Journal round 1 with ``plan``'s bytes as its plan file and ``reviewed`` as its review."""
    return rounds(
        run_dir,
        [(session, plan, reviewed, spent)],
        design_review=design_review,
        holds=holds,
        model=model,
    )


def rounds(
    run_dir: Path,
    given: Sequence[Given],
    *,
    design_review: str,
    holds: bool = True,
    model: str = "claude-sonnet-5",
    decomposition_model: str = "claude-sonnet-5",
) -> tuple[Proposal, ...]:
    """Journal each round, in order: its call's session, its plan file's bytes and its review.

    Each plan is named by the sha256 of its bytes. Every round but the last is re-planned, so
    its review is one a re-plan follows.
    """
    now = utc_stamp(utc_now())
    lines: list[RoundStarted | RoundEnded | RoundsEnded] = []
    proposals: list[Proposal] = []
    for k, (session, plan, reviewed, spent) in enumerate(given, 1):
        digest = hashlib.sha256(plan).hexdigest()
        path = plan_path(run_dir, k)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plan)
        cause = (
            reviewed.result.verdict
            if reviewed.result
            else reviewed.unavailable.cause
            if reviewed.unavailable
            else "held_out_exposed"
        )
        ending = round_ending(None, cause, budget_set=False)
        review = RoundReview(**{n: getattr(reviewed, n) for n in RoundReview.model_fields})
        lines += [
            RoundStarted.model_validate(
                {
                    "round": k,
                    "session_id": session,
                    "started": now,
                    "design_review": design_review if k == 1 else None,
                    "decomposition_model": decomposition_model if k == 1 else None,
                }
            ),
            RoundEnded(
                round=k,
                ending=ending,
                session_id=session,
                model=model,
                num_turns=1,
                usage=spent,
                plan_sha256=digest,
                detail="a plan",
                review=review,
                started=now,
                ended=now,
                call_ended=now,
                review_started=now,
                elapsed=Elapsed(started=k, call_ended=k, review_started=k, ended=k),
            ),
        ]
        proposals.append(
            Proposal(
                round=k,
                session_id=session,
                model=model,
                num_turns=1,
                plan_sha256=digest,
                cause=None,
                started=now,
                ended=now,
                review_started=now,
                review_ended=now,
            )
        )
    lines.append(
        RoundsEnded(
            round=len(given),
            follows=what_follows(ending, last=True, holds=holds),  # type: ignore[arg-type]
            ending_class=ending.review_class or ending.plan_class,
            cause=cause,
            detail="a plan",
        )
    )
    run_dir.joinpath(*JOURNAL).write_text("".join(line.model_dump_json() + "\n" for line in lines))
    return tuple(proposals)


def plan_digest(plan: bytes) -> str:
    """The digest a rig's plan is named by: its bytes' sha256."""
    return hashlib.sha256(plan).hexdigest()
