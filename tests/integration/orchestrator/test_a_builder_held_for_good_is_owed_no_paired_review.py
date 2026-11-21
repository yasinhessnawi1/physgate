"""A builder held for good never ran, so the paired run's checks owe it no review.

In a run whose designer ended without a merge, the builder of its design is held and never
dispatched: no session of it ends and no review of it runs. Of the paired run's four checks on
its reviews, three range over the reviews that ran (each ends in a verdict, is well formed, is on
the ledger) and are unchanged by it; the fourth, that every subtask was reviewed, asks it of
every planned subtask but such a builder. A builder held and let go, or one that ran, is owed its
review as before.
"""

from __future__ import annotations

from typing import Any

import real_domain_roles as base
import real_paired_reviewers as paired

from physgate.orchestrator.events import BuilderHeld, BuilderHeldWhy, BuilderReleased, Event

FW, CONTROL = base.FIRMWARE_ID, base.CONTROL_ID


def envelope(seq: int) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": f"2026-11-21T09:00:{seq:02d}.000000Z",
        "run_id": base.RUN_ID,
        "gate_mode": "on",
    }


def held(seq: int, why: BuilderHeldWhy, item: str | None = None) -> BuilderHeld:
    return BuilderHeld(
        **envelope(seq),
        subtask_id=FW,
        designer=CONTROL,
        nodes=("control.loop_gain",),
        why=why,
        item_id=item,
    )


def test_a_builder_held_for_good_is_owed_no_review() -> None:
    events: list[Event] = [held(0, "escalated", "r-control-3"), held(1, "ended_unmerged")]
    assert paired.held_never_run(events) == {FW}


def test_a_builder_held_and_let_go_is_owed_its_review() -> None:
    released = BuilderReleased(**envelope(2), subtask_id=FW, designer=CONTROL, nodes=("x.y",))
    events: list[Event] = [held(0, "escalated", "r-control-3"), released]
    assert paired.held_never_run(events) == set()


def test_a_run_with_no_hold_owes_every_planned_subtask_its_review() -> None:
    assert paired.held_never_run([]) == set()
    assert set(paired.ROLES) == {FW, CONTROL}
