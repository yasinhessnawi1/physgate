"""A review whose session showed held-out material is an exposure: recorded, and the run halts.

The reviewer raises it before concluding anything else from its session. The loop records
what the review spent, records a ``held_out_read`` incident naming the review session (never
the canary), and halts: the tier counts as exposed (ARCH-141), and no verdict is taken.
"""

from __future__ import annotations

from pathlib import Path

from loop_fakes import FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    Halted,
    Incident,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import HeldOutExposedError
from physgate.orchestrator.protocols import MessageUsage, Usage


def test_an_exposed_review_is_a_held_out_read_incident_and_the_run_halts(
    tmp_path: Path,
) -> None:
    spent = MessageUsage(
        message_id="m-exposed",
        usage=Usage(
            input_tokens=5,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    exposure = HeldOutExposedError(
        "held-out material in the stream of review session rev-x",
        session_id="rev-x",
        reviewer_model="claude-opus-5-5",
        usage=(spent,),
    )
    reviewer = FakeReviewer(unavailable={1: exposure})  # type: ignore[dict-item]
    rig = Rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "held_out_read" and "rev-x" in incident.detail
    assert [e for e in events if isinstance(e, TokensUsed) and e.message_id == "m-exposed"]
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert "held_out_read" in (halted.detail or "")
    assert events.index(halted) > events.index(incident)
    assert not [e for e in events if isinstance(e, (ReviewRan, ReviewUnavailable, Merged))]
    assert len(reviewer.seen) == 1, "an exposed review is never retried"
