"""The status route names sizing's closing pass while it is held, and the modules it waits for.

Over a run the real loop made: control's review ended blocked and its item waits for a person,
firmware is held on it, and the closing pass is served under ``closing_waits`` with both modules
it waits for, and the next step is the wait on it. A run whose closing pass is not held, and one
recorded before the rule, serve an empty list.
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
import test_sizing_s_closing_pass_waits_for_the_domain_modules_it_closes_over as closing  # noqa: E402
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (  # noqa: E402
    CLOSING,
    DRIVE,
    FW,
)

from physgate import roles  # noqa: E402


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base = tmp_path_factory.mktemp("closing")
    root = base / "runs"
    root.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        rig = closing.rigged(base / "held")
        assert closing.run_until_it_waits(rig, monkeypatch) == "wait"
        shutil.copytree(rig.run_dir, root / "held")
        monkeypatch.setattr("physgate.orchestrator.record.CLOSING_WAIT", None)
        rig = closing.rigged(base / "before")
        closing.run_until_it_waits(rig, monkeypatch)
        shutil.copytree(rig.run_dir, root / "before")
    yield {"root": root, "ui": fake_ui(base / "checkout")}


@pytest.fixture(scope="module")
def live(world: dict[str, Any]) -> Iterator[Live]:
    with serving(context_over(world["root"], ui_root=world["ui"])) as server:
        yield server


def served(live: Live, run: str) -> Any:  # noqa: ANN401 - a JSON answer of any shape
    status, _, body = live.request("GET", f"/api/runs/0/{run}/status")
    assert status == 200, body[:300]
    return json.loads(body)


def test_a_held_closing_pass_is_served_with_the_modules_it_waits_for(live: Live) -> None:
    found = served(live, "held")
    assert found["closing_waits"] == [{"subtask_id": CLOSING, "pending": [DRIVE, FW]}]
    assert (found["next_step"]["kind"], found["next_step"]["subtask_id"]) == ("wait", CLOSING)


def test_a_run_recorded_before_the_rule_serves_none(live: Live) -> None:
    assert served(live, "before")["closing_waits"] == []
