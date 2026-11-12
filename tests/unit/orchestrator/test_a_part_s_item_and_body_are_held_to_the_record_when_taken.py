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
from parts_rig import decide, log_of, rig, started
from plan_hold_rig import again, dispatched

from physgate.orchestrator.queue import QueueItem, QueueResolution
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
