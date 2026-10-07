"""Catch accounting reads a review's verdict, and a specification defect changes nothing in it.

A non-blocking defect of the issued specification is a note for the
decomposition. The gate event stamped from such a review says the reviewer
passed the work, exactly as it would without the note, and the headline count
is the same.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orch_helpers import gate_records

from physgate.orchestrator.catches import catches
from physgate.orchestrator.events import (
    EventLog,
    GateRan,
    ReviewRan,
    RunStarted,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.gate_events import gate_events
from physgate.orchestrator.protocols import GateResult, NumericOutput, ReviewResult, SpecDefect

NOTE = SpecDefect(finding="the gain allowance's reason cites nothing", blocking=False, item="DS-4")


def _count(tmp_path: Path, review: ReviewResult) -> tuple[list[bool | None], int]:
    log = EventLog(tmp_path / "events.jsonl", run_id="r", gate_mode="observe")
    log.append(RunStarted(**log.envelope(), config_sha256="c" * 64))
    planned = SubtaskPlanned(
        **log.envelope(),
        subtask_id="s1",
        spec_path="specs/s1.md",
        assigned_role="control",
        module_dir="modules/s1",
    )
    log.append(planned)
    log.append(ReviewRan(**log.envelope(), subtask_id="s1", attempt=1, result=review))
    gate = GateResult(
        verdict="fail",
        mode="observe",
        finding="the stall current exceeds the driver's rating",
        failing_check="magnitude",
        numeric_output=NumericOutput(value=3.4, unit="A"),
        quantities=(),
        checks=gate_records("observe", "magnitude"),
        catalogue_sha256="c" * 64,
    )
    log.append(GateRan(**log.envelope(), subtask_id="s1", attempt=1, result=gate))
    log.close()
    events = gate_events(read_events(tmp_path / "events.jsonl"), "d" * 64)
    stamped = [e.reviewer_had_passed for e in events if e.outcome == "fail"]
    (total,) = [row for row in catches(events) if row.check is None]
    return stamped, total.caught_after_reviewer_passed


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_a_defect_note_leaves_the_stamp_and_the_count_as_they_were(
    tmp_path: Path, verdict: str
) -> None:
    plain = ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="judged",
        reviewer_model="claude-sonnet-5",
        session_id="s1",
        usage=(),
    )
    noted = plain.model_copy(update={"spec_defects": (NOTE,)})
    without = _count(tmp_path / "a", plain)
    with_note = _count(tmp_path / "b", noted)
    assert without == with_note
    assert without[0] == [verdict == "pass"]
    assert without[1] == (1 if verdict == "pass" else 0)
