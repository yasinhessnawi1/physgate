"""A review that compacted says so on its line, and a review that did not keeps its bytes.

A verdict given after a compaction is a verdict (ARCH-060): its ``review_ran`` line carries the
result whole, the number of compactions and the context size before each among it. A review
that compacted and still reached no verdict goes to a person with no attempt spent, and its
``review_unavailable`` line carries how many compactions came first. A review with none writes
neither field, so every line written before them is written as it was.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from loop_fakes import FakeReviewer, Rig, plan
from test_a_review_with_no_verdict_goes_to_a_person_without_spending_an_attempt import (
    _unavailable,
)

from physgate.orchestrator.events import Escalated, ReviewUnavailable, read_events
from physgate.orchestrator.exceptions import ReviewUnavailableError


def _carries_compactions() -> None:
    assert "compactions" in inspect.signature(ReviewUnavailableError.__init__).parameters, (
        "a review with no verdict cannot say how many compactions came first"
    )


def _run(tmp_path: Path, reviewer: FakeReviewer) -> list[object]:
    rig = Rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return list(read_events(tmp_path / "events.jsonl"))


def test_the_no_verdict_line_says_how_many_compactions_came_first(tmp_path: Path) -> None:
    _carries_compactions()
    reviewer = FakeReviewer(unavailable={1: _unavailable("context_exceeded", compactions=2)})
    events = _run(tmp_path, reviewer)
    (line,) = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert getattr(line, "compactions", None) == 2
    assert line.retry is False
    assert [e for e in events if isinstance(e, Escalated)]
    raw = (tmp_path / "events.jsonl").read_text().splitlines()
    (written,) = [json.loads(r) for r in raw if '"review_unavailable"' in r]
    assert written["compactions"] == 2


def test_a_no_verdict_line_without_a_compaction_keeps_its_bytes(tmp_path: Path) -> None:
    _carries_compactions()
    reviewer = FakeReviewer(unavailable={1: _unavailable("context_exceeded")})
    _run(tmp_path, reviewer)
    raw = (tmp_path / "events.jsonl").read_text().splitlines()
    (written,) = [json.loads(r) for r in raw if '"review_unavailable"' in r]
    assert "compactions" not in written


def test_the_line_refuses_a_count_that_is_not_one() -> None:
    assert "compactions" in ReviewUnavailable.model_fields
    for bad in (0, -1, 1.5, "2", True):
        line = {
            "seq": 0,
            "ts": "2026-11-15T12:00:00.000000Z",
            "run_id": "run-1",
            "gate_mode": "on",
            "kind": "review_unavailable",
            "subtask_id": "s1",
            "attempt": 1,
            "cause": "context_exceeded",
            "detail": "the review outgrew the model's context window",
            "retry": False,
            "session_id": "rev",
            "reviewer_model": "claude-sonnet-5",
            "compactions": bad,
        }
        try:
            ReviewUnavailable.model_validate_json(json.dumps(line))
        except ValueError:
            continue
        raise AssertionError(f"a compaction count of {bad!r} was taken")
