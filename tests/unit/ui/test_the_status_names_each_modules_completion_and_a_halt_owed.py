"""The status route names each module's completion, or what withholds it, and a halt owed.

Over runs the real loop made with integration's declaration: every module of the plan is served
complete, withheld with the precondition registry's own open entries and their reasons, or not
declared, beside whether the run has a subtask that declares completion and whether the module is
sizing's, told by the role name the register gives sizing. A run whose log ends at an incident with
no halt after it is served the halt it owes, with the incident's cause, never as a run in progress.
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
import test_a_completion_rests_on_a_declaration_and_a_system_scope_result_the_record_still_gives as holds  # noqa: E402, E501
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as runner  # noqa: E402
from loop_fakes import FakeGate  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.orchestrator.completion import open_preconditions  # noqa: E402
from physgate.orchestrator.events import Halted, Incident, read_events  # noqa: E402
from physgate.orchestrator.replay import replay  # noqa: E402

BUDGET, DRIVE, FW, INTEG = runner.BUDGET, runner.DRIVE, runner.FW, runner.INTEG

#: Each run: the rig's fields, and how integration declared.
RUNS: dict[str, dict[str, Any]] = {
    "complete": {"sizing": True, "declared": (BUDGET, DRIVE, FW)},
    "failed-pair": {"declared": (DRIVE, FW), "fw_volts": 11},
    "observe-failed": {
        "declared": (DRIVE, FW),
        "gate_mode": "observe",
        "gate": FakeGate(integration_verdict="fail"),
    },
    "gate-off": {"declared": (DRIVE, FW), "gate_mode": "off"},
    "one-declared": {"declared": (DRIVE,)},
}


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    base = tmp_path_factory.mktemp("status")
    root = base / "runs"
    root.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        for name, kw in RUNS.items():
            rig, _ = runner.finished(base / name, monkeypatch, **kw)
            shutil.copytree(rig.run_dir, root / name)
        # A run whose process died between an incident and its halt.
        rig = holds.rig_for(base / "owed")
        holds.killed(rig, holds.at_a_completion())
        runner.rewritten(rig.run_dir / "events.jsonl", holds.rewrite_declaration(modules=[DRIVE]))
        assert holds.take_over(rig, lambda e, _: isinstance(e, Halted)).startswith("raised")
        shutil.copytree(rig.run_dir, root / "owed-halt")
    yield {"root": root, "ui": fake_ui(base / "checkout")}


@pytest.fixture(scope="module")
def live(world: dict[str, Path]) -> Iterator[Live]:
    with serving(context_over(world["root"], ui_root=world["ui"])) as server:
        yield server


def served(live: Live, run: str) -> Any:  # noqa: ANN401 - a JSON answer of any shape
    status, _, body = live.request("GET", f"/api/runs/0/{run}/status")
    assert status == 200, body[:300]
    found = json.loads(body)
    assert {"completion", "owed_halt"} <= found.keys(), sorted(found)
    return found


def module(found: dict[str, Any], subtask: str) -> dict[str, Any]:
    (one,) = [m for m in found["completion"]["modules"] if m["subtask_id"] == subtask]
    return one


def registry(world: dict[str, Path], run: str, subtask: str) -> list[dict[str, str]]:
    """What the precondition registry says is open for ``subtask``, read from the log here."""
    state = replay(read_events(world["root"] / run / "events.jsonl"))
    return [{"name": n, "reason": r} for n, r in open_preconditions(state, subtask)]


def test_the_status_names_each_declared_modules_completion_or_what_withholds_it(
    world: dict[str, Path], live: Live
) -> None:
    found = served(live, "complete")
    assert found["completion"] == {
        "owner": True,
        "modules": [
            {"subtask_id": BUDGET, "sizing": True, "state": "complete", "open": []},
            {"subtask_id": DRIVE, "sizing": False, "state": "complete", "open": []},
            {"subtask_id": FW, "sizing": False, "state": "complete", "open": []},
        ],
    }
    pair = served(live, "failed-pair")
    for subtask in (DRIVE, FW):
        withheld = module(pair, subtask)
        assert (withheld["state"], withheld["sizing"]) == ("withheld", False)
        assert withheld["open"] == registry(world, "failed-pair", subtask)
        (entry,) = withheld["open"]
        assert entry["name"] == "contract" and "contract result failed" in entry["reason"]
    one = served(live, "one-declared")
    assert (module(one, DRIVE)["state"], module(one, FW)["state"]) == ("complete", "not_declared")


def test_under_observe_a_failed_system_scope_result_withholds_completion(
    world: dict[str, Path], live: Live
) -> None:
    found = served(live, "observe-failed")
    for subtask in (DRIVE, FW):
        withheld = module(found, subtask)
        assert withheld["state"] == "withheld"
        assert withheld["open"] == registry(world, "observe-failed", subtask)
        assert [e["name"] for e in withheld["open"]] == ["system_scope"]
        assert "system-scope result failed" in withheld["open"][0]["reason"]


def test_under_off_completion_has_no_system_scope_precondition(live: Live) -> None:
    found = served(live, "gate-off")
    assert [(m["state"], m["open"]) for m in found["completion"]["modules"]] == [
        ("complete", []),
        ("complete", []),
    ]


def test_a_run_owing_a_halt_says_so(world: dict[str, Path], live: Live) -> None:
    events = read_events(world["root"] / "owed-halt" / "events.jsonl")
    assert isinstance(events[-1], Incident)
    found = served(live, "owed-halt")
    assert found["next_step"]["kind"] == "halt" and found["halted"] is None
    assert found["owed_halt"] == {
        "cause": "declaration_mismatch",
        "subtask_id": None,
        "detail": events[-1].detail,
    }
    for run in RUNS:
        assert served(live, run)["owed_halt"] is None
