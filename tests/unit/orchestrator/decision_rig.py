"""A run whose one subtask waits in the queue, and a decision taken on it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.decisions import item_consequence, source_of
from physgate.orchestrator.events import DecisionTaken
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import IndicatorReport, ReviewResult, SpecDefect

TS = "2026-10-21T12:00:00.000000Z"
DIGEST = "a" * 64

#: Why approve records only, as a decision taken says it.
WHY = {
    "gate": "last_rejection_automated",
    "change_check": "last_rejection_automated",
    "reading": "last_rejection_automated",
    "indicator_in_history": "indicator_in_history",
    "scan_hit": "scan_hit",
    "source": "record_only_source",
}


def review(verdict: str, n: int, **fields: Any) -> ReviewResult:
    return ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="the gain changed silently" if verdict != "blocked" else "no mass given",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=(),
        **fields,
    )


CONFIRMED = (
    IndicatorReport(
        kind="disabled_checks", evidence="toolu_1", disposition="confirmed", reason="a skip"
    ),
)
BLOCKED = review("blocked", 1, spec_defects=(SpecDefect(finding="no mass", blocking=True),))


def escalated(tmp_path: Path, scenario: str) -> Loop:
    """A loop over a run whose one subtask is waiting in the queue, as ``scenario`` sent it."""
    run = tmp_path / scenario
    run.mkdir(parents=True)
    rig = Rig(run, dispatcher=FakeDispatcher(trajectories=run / "sessions"))
    if scenario == "unavailable":
        rig.reviewer = FakeReviewer(
            unavailable={1: ReviewUnavailableError("no verdict", cause="invalid_verdict")}
        )
    elif scenario == "gate_exhausted":
        rig.gate = FakeGate(verdicts=["fail"] * 3)
    elif scenario == "review_exhausted":
        rig.reviewer = FakeReviewer(verdicts=["fail"] * 3)
    elif scenario == "indicator_then_unavailable":
        rig.reviewer = FakeReviewer(
            results={1: review("fail", 1, indicators=CONFIRMED)},
            unavailable={2: ReviewUnavailableError("no verdict", cause="invalid_verdict")},
        )
    elif scenario == "blocked":
        rig.reviewer = FakeReviewer(results={1: BLOCKED})
    else:
        raise AssertionError(scenario)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    assert loop.state.subtasks["s1"].status == "escalated"
    return loop


def decide(loop: Loop, verb: str, note: str | None = "because", **override: Any) -> DecisionTaken:
    """Take a decision as the record allows it, with any field forged."""
    sub = loop.state.subtasks["s1"]
    now = sub.attempts[-1]
    expected = item_consequence(loop.state, "s1", source=source_of(sub), scan_hits=())
    if verb == "approve":
        effect = "merge" if expected.on_approve == "merge_attempt" else "none"
    else:
        effect = expected.on_reject if expected.on_reject != "record_only" else "none"
    fields: dict[str, Any] = {
        "subtask_id": "s1",
        "item_id": sub.queue_item,
        "verb": verb,
        "note": note,
        "resolved_by": "yasin",
        "decided_ts": TS,
        "decision_offset": 0,
        "shown_sha256": DIGEST,
        "attempt": now.number,
        "attempt_commit": expected.attempt_commit,
        "effect": effect,
        "acts": effect != "none",
        "why_not": None
        if effect != "none"
        else WHY[str(expected.why_record_only)]
        if verb == "approve"
        else "record_only_source",
    }
    fields.update(override)
    event = DecisionTaken(**loop.record.envelope(), **fields)
    loop.record.emit(event)
    return event
