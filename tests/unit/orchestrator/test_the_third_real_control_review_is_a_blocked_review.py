"""The third real control review, replayed: a blocked verdict, on the log as a review.

The real control reviewer read everything, answered every rubric item, and found
that the issued brief, a stand-in that dictates one literal node, gives none of the
inputs its safety-critical checks need. It submitted ``blocked`` with its blocking
specification defects (``replayed/``, as the model sent it, inside its wrapper).
That is the right verdict under the rubric. Here it is judged as the harness judges
it, becomes the review result, and runs through the loop: a review line with its
verdict, its model and its defects, the subtask sent to a person, no repair attempt
spent, and no reviewer verdict stamped for catch accounting.
"""

from __future__ import annotations

import json
from pathlib import Path

from loop_fakes import FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    Merged,
    ReviewRan,
    ReviewUnavailable,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import ReviewResult
from physgate.reviewers.rubric import load_rubric, not_evaluable_needs
from physgate.reviewers.verdict import Answered, judge, to_result
from physgate.state.task_ledger import TaskLedger

REPO = Path(__file__).resolve().parents[3]
SUBMITTED = REPO / "tests" / "integration" / "orchestrator" / "replayed"
SUBMISSION = SUBMITTED / "review_submission_v3_control.json"


def _result() -> ReviewResult:
    submitted = json.loads(SUBMISSION.read_text())
    rubric = load_rubric(REPO / "knowledge", "control")
    # The stand-in brief numbers no criterion, so its lines are held to at least one.
    outcome = judge(
        submitted, (), rubric.items, criteria=None, not_evaluable=not_evaluable_needs("control")
    )
    assert isinstance(outcome, Answered), outcome
    return to_result(
        outcome,
        reviewer_model="claude-opus-5-5",
        session_id="f2f25a35-dc37-484b-a9ce-52de0ce5a05a",
        usage=(),
        rubric_sha256=rubric.sha256,
        rubric_kind="paired",
        packet_sha256="b" * 64,
        reading_verified=True,
        peak_context_tokens=1,
        schema_refusals=0,
    )


def test_the_real_submission_is_a_blocked_verdict() -> None:
    result = _result()
    submitted = json.loads(SUBMISSION.read_text())
    assert result.verdict == "blocked" and result.failing_item is None
    assert result.finding == submitted["finding"]
    assert len(result.items) == len(submitted["items"])
    assert len(result.criteria) == len(submitted["acceptance_criteria"])
    blocking = [d for d in result.spec_defects if d.blocking]
    assert len(result.spec_defects) == len(submitted["spec_defects"])
    assert len(blocking) == sum(d["blocking"] for d in submitted["spec_defects"]) > 0


def test_it_is_logged_as_a_review_and_routed_to_the_queue(tmp_path: Path) -> None:
    result = _result()
    rig = Rig(tmp_path, reviewer=FakeReviewer(results={1: result}), gate_mode="observe")
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    (item,) = loop.queue.open_items()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (ran,) = [e for e in events if isinstance(e, ReviewRan)]
    assert ran.result == result
    assert not [e for e in events if isinstance(e, ReviewUnavailable | AttemptRejected | Merged)]
    assert [e for e in events if isinstance(e, Escalated)]
    assert item.source == "review_blocked"
    assert "No repair attempt was spent" in item.decision_required
    assert len(rig.dispatcher.requests) == 1
    line = TaskLedger(tmp_path / "ledger.jsonl").find("s1")
    assert line is not None and line.review_result == "blocked" and line.attempt_count == 1
    stamped = gate_events(events, "d" * 64)
    assert stamped and {e.reviewer_had_passed for e in stamped} == {None}
