"""A log written before a blocked review was a review line still reads, as written.

Logs of earlier real runs recorded a blocked review as one with no verdict, under
the cause ``blocking_spec_defect``. Those logs are evidence: every reader reads such
a line as it was written, a review with no verdict, routed then as now to a person,
with no reviewer verdict stamped. No writer can emit the cause any more: the log
refuses the line before it is written, wherever the line comes from.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest
from loop_fakes import FakeReviewer, KilledError, Rig, plan

from physgate.orchestrator.events import (
    EventLog,
    ReviewRan,
    ReviewUnavailable,
    RunStarted,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import SpecDefect
from physgate.orchestrator.replay import RunState

LEGACY: Final = "blocking_spec_defect"
BLOCKING = SpecDefect(finding="no unstable pole is given", blocking=True, item="DS-4")


def _no_verdict(cause: str) -> ReviewUnavailableError:
    return ReviewUnavailableError(
        "the review reached no verdict",
        cause=cause,  # type: ignore[arg-type]
        session_id="rev-1",
        reviewer_model="claude-opus-5-5",
    )


def _rewrite(tmp_path: Path) -> None:
    """Rewrite the no-verdict line as an earlier writer wrote it."""
    path = tmp_path / "events.jsonl"
    lines = []
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record["kind"] == "review_unavailable":
            record["cause"] = LEGACY
            record["spec_defects"] = [BLOCKING.model_dump(mode="json")]
        lines.append(json.dumps(record, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n")


def _legacy_log(tmp_path: Path) -> Rig:
    """A finished run whose no-verdict line an earlier writer wrote."""
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _no_verdict("invalid_verdict")}))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    _rewrite(tmp_path)
    return rig


def test_the_legacy_line_is_read_as_written(tmp_path: Path) -> None:
    _legacy_log(tmp_path)
    events = read_events(tmp_path / "events.jsonl")
    (line,) = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert (line.kind, line.cause, line.retry) == ("review_unavailable", LEGACY, False)
    assert line.spec_defects == (BLOCKING,)
    assert not [e for e in events if isinstance(e, ReviewRan)]  # never turned into a review


def test_the_replay_and_every_derived_record_take_it_as_they_did(tmp_path: Path) -> None:
    rig = _legacy_log(tmp_path)
    events = read_events(tmp_path / "events.jsonl")
    state = RunState()
    for event in events:
        state.record(event)
    assert state.subtasks["s1"].status == "escalated"
    assert state.next_step().kind == "done"
    stamped = gate_events(events, "d" * 64)
    assert stamped and {e.reviewer_had_passed for e in stamped} == {None}
    reopened = rig.open()  # the one writer reads it back through its own checks
    (item,) = reopened.queue.open_items()
    reopened.close()
    assert item.source == "review_unavailable"


def test_the_log_refuses_to_write_the_legacy_cause(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on")
    log.append(RunStarted(**log.envelope(), config_sha256="c" * 64))
    log.append(
        SubtaskPlanned(
            **log.envelope(),
            subtask_id="s1",
            spec_path="specs/s1.md",
            assigned_role="electrical",
            module_dir="modules/s1",
        )
    )
    line = ReviewUnavailable(
        **log.envelope(),
        subtask_id="s1",
        attempt=1,
        cause=LEGACY,
        detail="blocked",
        retry=False,
        session_id="rev-1",
        reviewer_model="claude-opus-5-5",
    )
    with pytest.raises(ValueError, match="written as a review line"):
        log.append(line)
    log.close()
    assert [e.kind for e in read_events(tmp_path / "events.jsonl")] == [
        "run_started",
        "subtask_planned",
    ]


def test_a_reviewer_raising_it_cannot_get_it_onto_the_log(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _no_verdict(LEGACY)}))
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(ValueError, match="written as a review line"):
        loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not [e for e in events if isinstance(e, ReviewUnavailable)]


def test_a_legacy_line_not_yet_escalated_escalates_as_it_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A killed run resumed from such a line sends a no-verdict item, not a blocked one."""
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: _no_verdict("invalid_verdict")}))
    loop = rig.open()
    loop.start(plan("s1"))

    def killed(self: Loop, subtask_id: str, unavailable: ReviewUnavailable) -> None:
        raise KilledError

    with monkeypatch.context() as patch:
        patch.setattr(Loop, "_escalate_unavailable", killed)
        with pytest.raises(KilledError):
            loop.run()
    loop.close()
    _rewrite(tmp_path)
    again = rig.open()
    again.run()
    (item,) = again.queue.open_items()
    again.close()
    assert item.source == "review_unavailable"
    assert "no unstable pole is given" in item.decision_required
    assert len(rig.reviewer.seen) == 1
