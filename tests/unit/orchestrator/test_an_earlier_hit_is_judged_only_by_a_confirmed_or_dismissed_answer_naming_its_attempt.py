"""An earlier attempt's hit is judged only by an answer that names its attempt and decides it.

A later review is given the hits of an earlier attempt no review judged, to confirm or dismiss
each with its reason. So an earlier attempt is judged only where:

- every one of its hits is answered by an answer that names that attempt and that hit's
  evidence: two attempts can carry the same evidence id, and an answer to one is not an
  answer to the other;
- every answer naming it confirms or dismisses with a reason that is not blank: ``noted`` does
  not judge an earlier hit, and leaves it, as an unanswered one, for an approve to record only.

The review line records the earlier hits it was shown. Replay holds the attempts it names as
judged to those hits and the answers on the same line, and refuses a line where they disagree:
one that claims an attempt whose shown hit it left unanswered, or a hit no scan recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeChanges, FakeDispatcher, FakeReviewer
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    LONG_LINE,
    _dismissed_then_blocked,
    _item,
    _marked,
    _of,
    _resume,
    _review_judged,
    _rig,
    _run,
    decide,
    hit,
    result,
)

from physgate.orchestrator.events import DecisionTaken, Event, ReviewRan, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import IndicatorReport
from physgate.orchestrator.replay import replay
from physgate.orchestrator.trajectory import seal

REASON = "the skip marks a test of hardware the run does not have"
SHARED = "toolu_shared"


def answer(
    evidence: str,
    attempt: int | None = None,
    disposition: str = "dismissed",
    reason: str = REASON,
) -> IndicatorReport:
    """An answer to one hit: to an earlier attempt's, naming that attempt."""
    data: dict[str, Any] = {
        "kind": "disabled_checks",
        "evidence": evidence,
        "disposition": disposition,
        "reason": reason,
    }
    if attempt is not None:
        assert "attempt" in IndicatorReport.model_fields, "an answer names no attempt"
        data["attempt"] = attempt
    return IndicatorReport.model_validate(data)


# -- only a confirmed or dismissed answer, with a reason, judges an earlier hit -------------------


@pytest.mark.parametrize(
    ("disposition", "reason"),
    [("noted", REASON), ("dismissed", "   ")],
    ids=["noted", "dismissed with a blank reason"],
)
def test_an_earlier_hit_noted_or_dismissed_without_a_reason_stays_unjudged(
    tmp_path: Path, disposition: str, reason: str
) -> None:
    run_dir = tmp_path / "run"
    earlier = answer(hit("sess-1"), 1, disposition, reason)
    reviewer = FakeReviewer(results={1: result("blocked", 1, earlier, answer(hit("sess-2")))})
    rig = _rig(run_dir, reviewer=reviewer)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, ())]
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert _marked(item) == [(hit("sess-1"), 1)]
    decide(run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []


# -- an answer judges the hit of the attempt it names, not another's of the same id ---------------


@dataclass
class SharedIdDispatcher(FakeDispatcher):
    """Attempts 1 and 2 each switch a test off by a call of one id; attempt 3 by one of its own."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        if report.trajectory is None or self.trajectories is None:
            return report
        call = SHARED if request.attempt < 3 else hit(report.session_id)  # noqa: PLR2004
        use: dict[str, Any] = {"type": "tool_use", "id": call, "name": "Write"}
        use["input"] = {"file_path": "t.py", "content": "@pytest.mark.skip\n"}
        written = {"type": "assistant", "message": {"role": "assistant", "content": [use]}}
        path = Path(report.trajectory)
        path.write_bytes(json.dumps(written).encode() + b"\n" + path.read_bytes())
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


def test_an_answer_judges_the_hit_of_the_attempt_it_names_not_another_s_of_the_same_id(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    reviewer = FakeReviewer(
        results={1: result("blocked", 1, answer(SHARED, 1), answer(hit("sess-3")))}
    )
    rig = _rig(
        run_dir,
        dispatcher=SharedIdDispatcher(trajectories=run_dir / "sessions"),
        changes=FakeChanges(refuse={1: LONG_LINE, 2: LONG_LINE}),
        reviewer=reviewer,
    )
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(3, (1,))]
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert _marked(item) == [(SHARED, 2)]


# -- replay holds a review line's judged attempts to the hits it was shown ------------------------


def _review_line(run_dir: Path) -> tuple[list[Event], int, dict[str, Any]]:
    """The run's events, the index of its last review line, and that line as data."""
    assert "earlier_hits" in ReviewRan.model_fields, "a review line records no hit it was shown"
    events = list(read_events(run_dir / "events.jsonl"))
    last = max(n for n, e in enumerate(events) if isinstance(e, ReviewRan))
    return events, last, json.loads(events[last].model_dump_json())


def test_a_review_line_records_the_earlier_hits_it_was_shown(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _run(_dismissed_then_blocked(run_dir), "s1")
    events, last, data = _review_line(run_dir)
    assert [(h["evidence"], h["attempt"]) for h in data.get("earlier_hits", [])] == [
        (hit("sess-1"), 1)
    ]
    assert data.get("judged_earlier") == [1]
    replay(events)


@pytest.mark.parametrize(
    "change",
    [
        "leave a shown hit unanswered",
        "answer a hit no scan recorded",
        "name an attempt judged with no hit shown",
        "leave out an attempt it judged whole",
    ],
)
def test_replay_refuses_a_review_line_whose_judged_attempts_its_answers_do_not_bear_out(
    tmp_path: Path, change: str
) -> None:
    run_dir = tmp_path / "run"
    _run(_dismissed_then_blocked(run_dir), "s1")
    events, last, data = _review_line(run_dir)
    answers = data["result"]["indicators"]
    if change == "leave a shown hit unanswered":
        data["result"]["indicators"] = [a for a in answers if a.get("attempt") != 1]
    elif change == "answer a hit no scan recorded":
        answers.append(json.loads(answer("toolu_never_scanned", 1).model_dump_json()))
    elif change == "name an attempt judged with no hit shown":
        data.pop("earlier_hits")
    else:
        data.pop("judged_earlier")
    events[last] = ReviewRan.model_validate_json(json.dumps(data))
    with pytest.raises((ValueError, CorruptEventLogError)):
        replay(events)
