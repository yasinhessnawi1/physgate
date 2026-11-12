"""A part's item is held to the record the loop builds it from when its decision is taken.

ARCH-122, ARCH-130. A person decides a part on the view of the item they were shown. The loop
takes that decision only where the item is the one the run's record builds for the part, as it
does for the plan's item: where the record builds another, the run halts and nothing is
dispatched. The items file is written by the run's own account, which the loop holds to, so the
record is made to build another item here, not the file to hold one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parts_rig import decide, decisions_bytes, log_of, rig, started
from plan_hold_rig import again, dispatched

from physgate.orchestrator.queue import QueueItem, QueueResolution, read_queue
from physgate.orchestrator.record import RunRecord

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]


def _taken(run_dir: Path) -> list[str]:
    return [one["item_id"] for one in log_of(run_dir) if one["kind"] == "decision_taken"]


def test_where_the_record_builds_another_item_the_run_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    for one in IDS:
        assert isinstance(decide(run_dir, one, "find"), QueueResolution)
    built = RunRecord.parts_item_of

    def other(self: RunRecord, item_id: str) -> QueueItem | None:
        found = built(self, item_id)
        if found is None or item_id != IDS[0]:
            return found
        return found.model_copy(update={"artefact_diff": "The plan of another digest."})

    monkeypatch.setattr(RunRecord, "parts_item_of", other)
    assert again(rig(run_dir)) == "halted"
    assert dispatched(run_dir) == []
    incident = next(one for one in log_of(run_dir) if one["kind"] == "incident")
    assert incident["cause"] == "queue_item_mismatch"
    assert IDS[0] not in _taken(run_dir)


def test_where_the_record_builds_the_item_it_is_taken(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    for one in IDS:
        assert isinstance(decide(the_rig.run_dir, one, "find"), QueueResolution)
    assert again(rig(the_rig.run_dir)) == "done"
    assert _taken(the_rig.run_dir) == IDS


def test_a_choice_taken_on_another_view_than_the_item_s_line_halts_the_run(tmp_path: Path) -> None:
    # A line appended by hand, in the writer's form, that names a view the item never had: the
    # writer binds a choice to the view it was taken on, and the loop holds it to the line.
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    for one in IDS[1:]:
        assert isinstance(decide(run_dir, one, "find"), QueueResolution)
    assert read_queue(run_dir).digests[IDS[0]] != "a" * 64
    line = QueueResolution(
        item_id=IDS[0],
        ts="2026-11-12T10:00:00.000000Z",
        decision="choose find",
        resolved_by="yasin",
        verb="choose",
        position="find",
        shown_sha256="a" * 64,
    )
    with (run_dir / "queue_decisions.jsonl").open("ab") as handle:
        handle.write(line.model_dump_json().encode() + b"\n")
    assert decisions_bytes(run_dir).count(b"\n") == 3
    assert again(rig(run_dir)) == "halted"
    assert dispatched(run_dir) == []
    incident = next(one for one in log_of(run_dir) if one["kind"] == "incident")
    assert incident["cause"] == "queue_item_mismatch"
    assert IDS[0] not in _taken(run_dir)
