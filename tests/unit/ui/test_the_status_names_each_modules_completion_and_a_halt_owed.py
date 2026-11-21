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
from loop_fakes import FakeGate, Rig  # noqa: E402
from sign_off_rig import declaring  # noqa: E402

from physgate import roles  # noqa: E402
from physgate.orchestrator.completion import open_preconditions  # noqa: E402
from physgate.orchestrator.declaration import Declaration  # noqa: E402
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
    "one-declared": {"declared": (FW,)},
}


def _finished(run_dir: Path, *, declared: tuple[str, ...], **fields: Any) -> Rig:  # noqa: ANN401
    """A run driven to its end, integration declaring ``declared``.

    Told that the control module's sign-off is owed, its next attempt declares every other module.
    """
    sizing = fields.pop("sizing", False)
    rig = runner.rig_for(run_dir, **fields)
    loop = rig.open()
    declaring(loop, declared, tuple(m for m in declared if m != DRIVE))
    runner.start(loop, sizing=sizing, pairs=True)
    loop.run()
    loop.close()
    return rig


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Path]]:
    base = tmp_path_factory.mktemp("status")
    root = base / "runs"
    root.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        for name, kw in RUNS.items():
            rig = _finished(base / name, **kw)
            shutil.copytree(rig.run_dir, root / name)
        # A run whose process died between an incident and its halt.
        rig = runner.rig_for(base / "owed")
        # The control module's sign-off is owed, so a declaration naming it is refused and the
        # record cannot be made to name it: the line is rewritten to drop the budget instead.
        rig.changes.declares[INTEG] = Declaration(modules=(BUDGET, FW), sha256="d" * 64)
        holds.killed(rig, holds.at_a_completion(), sizing=True)
        runner.rewritten(rig.run_dir / "events.jsonl", holds.rewrite_declaration(modules=[FW]))
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
    modules: list[dict[str, Any]] = found["completion"]["modules"]
    (one,) = [m for m in modules if m["subtask_id"] == subtask]
    return one


def registry(world: dict[str, Path], run: str, subtask: str) -> list[dict[str, str]]:
    """What the precondition registry says is open for ``subtask``, read from the log here."""
    state = replay(read_events(world["root"] / run / "events.jsonl"))
    return [{"name": n, "reason": r} for n, r in open_preconditions(state, subtask)]


def names(one: dict[str, Any]) -> list[str]:
    return [entry["name"] for entry in one["open"]]


def test_the_status_names_each_declared_modules_completion_or_what_withholds_it(
    world: dict[str, Path], live: Live
) -> None:
    found = served(live, "complete")
    # The control module owes a person's sign-off, so integration's declaration leaves it out:
    # it is not complete, its state says the sign-off is owed, and the sign-off is what is open.
    drive = module(found, DRIVE)
    assert (drive["state"], drive["sizing"]) == ("sign_off_owed", False)
    assert drive["open"] == registry(world, "complete", DRIVE)
    assert names(drive) == ["sign_off"]
    assert "owes a person's sign-off" in drive["open"][0]["reason"]
    assert found["completion"]["owner"] is True
    assert [m for m in found["completion"]["modules"] if m["subtask_id"] != DRIVE] == [
        {"subtask_id": BUDGET, "sizing": True, "state": "complete", "open": []},
        {"subtask_id": FW, "sizing": False, "state": "complete", "open": []},
    ]
    pair = served(live, "failed-pair")
    withheld = module(pair, FW)
    assert (withheld["state"], withheld["sizing"]) == ("withheld", False)
    assert withheld["open"] == registry(world, "failed-pair", FW)
    # The failed pair withholds the module, and so does its item, on which no decision is
    # taken yet.
    contract, item = withheld["open"]
    assert contract["name"] == "contract" and "contract result failed" in contract["reason"]
    assert item["name"] == "open_item" and "has no decision taken" in item["reason"]
    # The control module is withheld by the pair as well, and by its sign-off besides.
    assert module(pair, DRIVE)["open"] == registry(world, "failed-pair", DRIVE)
    assert names(module(pair, DRIVE)) == ["contract", "open_item", "sign_off"]
    assert module(pair, DRIVE)["state"] == "sign_off_owed"
    one = served(live, "one-declared")
    assert (module(one, FW)["state"], module(one, DRIVE)["state"]) == ("complete", "sign_off_owed")


def test_under_observe_a_failed_system_scope_result_withholds_completion(
    world: dict[str, Path], live: Live
) -> None:
    found = served(live, "observe-failed")
    withheld = module(found, FW)
    assert withheld["state"] == "withheld"
    assert withheld["open"] == registry(world, "observe-failed", FW)
    assert names(withheld) == ["system_scope"]
    assert "system-scope result failed" in withheld["open"][0]["reason"]
    # The control module is not declared, and its sign-off is open beside the system scope.
    drive = module(found, DRIVE)
    assert drive["open"] == registry(world, "observe-failed", DRIVE)
    assert names(drive) == ["system_scope", "sign_off"]
    assert drive["state"] == "sign_off_owed"


def test_under_off_completion_has_no_system_scope_precondition(live: Live) -> None:
    found = served(live, "gate-off")
    assert [(m["subtask_id"], m["state"], names(m)) for m in found["completion"]["modules"]] == [
        (DRIVE, "sign_off_owed", ["sign_off"]),
        (FW, "complete", []),
    ]


@pytest.mark.parametrize("run", ["complete", "one-declared"])
def test_the_status_says_the_run_records_decisions_and_names_each_sign_off_owed(
    live: Live, run: str
) -> None:
    # The runs record decisions: none acts, and the control module's sign-off stays owed.
    found = served(live, run)
    assert found["acts"] is False
    assert found["sign_offs_owed"] == [DRIVE]
    # Its item is open, but no decision on it acts in such a run: none is open to decide.
    assert found["sign_offs_open_to_decide"] == []
    assert found["next_step"]["kind"] == "escalated"


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


_RECORDED = Path(__file__).resolve().parents[1] / "evaluation" / "whole" / "recorded_runs"


@pytest.mark.parametrize(
    ("recorded", "open_to_decide"),
    [
        # Waiting before the call: the person's decision on the item is what the run waits for.
        ("acts_waiting_on_a_sign_off", ["c1"]),
        # Rejected, then the fix's item rejected too: owed, with nothing left that can sign it.
        ("acts_rejected_a_sign_off_owed", []),
        # Signed: nothing is owed.
        ("acts_signed", []),
        # Records decisions: a decision on the item signs nothing, so none is open to decide.
        ("records_a_sign_off_owed", []),
    ],
)
def test_a_sign_off_owed_is_open_to_decide_only_while_its_latest_item_is_undecided(
    recorded: str, open_to_decide: list[str]
) -> None:
    from physgate.ui.readers import sign_offs_open_to_decide

    state = replay(read_events(_RECORDED / f"{recorded}.jsonl"))
    assert sign_offs_open_to_decide(state) == open_to_decide
    assert set(open_to_decide) <= set(state.sign_offs_open())


@pytest.mark.parametrize(
    ("recorded", "alone"),
    [
        # Ended escalated with the sign-offs alone owed.
        ("acts_rejected_a_sign_off_owed", True),
        # Ended escalated with integration's own item open as well.
        ("acts_rejected_and_integration_escalated", False),
    ],
)
def test_an_escalated_end_says_whether_the_sign_offs_alone_are_what_is_owed(
    recorded: str, alone: bool
) -> None:
    state = replay(read_events(_RECORDED / f"{recorded}.jsonl"))
    assert state.next_step().kind == "escalated"
    assert state.ends_on_sign_offs_alone() is alone
