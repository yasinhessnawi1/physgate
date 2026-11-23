"""The status route names each builder held until the design it implements merges, and why.

Over runs the real loop made: a builder held while its designer is with a person is served under
``held`` with the designer, the design's node, why and the item a person can act on, and the next
step is the wait on it; once a person's reject ends the designer unmerged, the builder is served
held for that reason, with no item. A run recorded without design pairs serves an empty list.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ui_rig import Live, context_over, fake_ui, serving

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import test_a_builder_is_held_until_the_design_it_implements_merges as held  # noqa: E402
from accounted import reaccount  # noqa: E402
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (  # noqa: E402
    lines,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (  # noqa: E402
    DRIVE,
    FW,
)
from test_a_queue_decision_acts_at_a_boundary import decide  # noqa: E402

from physgate import roles  # noqa: E402

LAW = held.LAW


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base = tmp_path_factory.mktemp("held")
    root = base / "runs"
    root.mkdir()
    items: dict[str, str] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        rig = held.rigged(base / "escalated")
        assert held.first_run(rig, monkeypatch) == "wait"
        items["escalated"] = held.drive_item(lines(rig))
        shutil.copytree(rig.run_dir, root / "escalated")
        rig = held.rigged(base / "ended")
        assert held.first_run(rig, monkeypatch) == "wait"
        decide(rig.run_dir, "reject", "no attempt is left", item_id=held.drive_item(lines(rig)))
        reaccount(rig.run_dir)
        assert held.resumed(rig, monkeypatch) == "unrun"
        shutil.copytree(rig.run_dir, root / "ended")
        rig = held.rigged(base / "no-pairs")
        held.first_run(rig, monkeypatch, design=False)
        shutil.copytree(rig.run_dir, root / "no-pairs")
    yield {"root": root, "ui": fake_ui(base / "checkout"), "items": items}


@pytest.fixture(scope="module")
def live(world: dict[str, Any]) -> Iterator[Live]:
    with serving(context_over(world["root"], ui_root=world["ui"])) as server:
        yield server


def served(live: Live, run: str) -> Any:  # noqa: ANN401 - a JSON answer of any shape
    status, _, body = live.request("GET", f"/api/runs/0/{run}/status")
    assert status == 200, body[:300]
    return json.loads(body)


def test_a_builder_whose_designer_is_with_a_person_is_served_held_and_waited_on(
    world: dict[str, Any], live: Live
) -> None:
    found = served(live, "escalated")
    assert found["held"] == [
        {
            "subtask_id": FW,
            "designer": DRIVE,
            "nodes": [LAW],
            "why": "escalated",
            "item_id": world["items"]["escalated"],
        }
    ]
    assert (found["next_step"]["kind"], found["next_step"]["subtask_id"]) == ("wait", FW)


def test_a_builder_whose_designer_ended_unmerged_is_served_held_with_no_item(live: Live) -> None:
    found = served(live, "ended")
    assert found["held"] == [
        {"subtask_id": FW, "designer": DRIVE, "nodes": [LAW], "why": "ended_unmerged"}
    ]
    assert found["next_step"]["kind"] == "unrun"
    # The list of what never ran is served only once the run has ended so.
    assert [n["subtask_id"] for n in found["never_ran"]] == [FW]


def test_a_run_still_waiting_serves_no_list_of_what_never_ran(live: Live) -> None:
    found = served(live, "escalated")
    assert found["next_step"]["kind"] == "wait"
    assert found["never_ran"] == []


def test_a_run_recorded_without_design_pairs_serves_no_hold(live: Live) -> None:
    assert served(live, "no-pairs")["held"] == []
