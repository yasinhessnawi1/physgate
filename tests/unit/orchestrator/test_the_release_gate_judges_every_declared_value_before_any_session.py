"""The release is gated: every declared value is judged before any session is spawned.

ARCH-122. Once the parts writes land, one gate call at subtask scope judges a view whose base is
the journal's head before the first parts write, so exactly the declared nodes are its own. It
runs in the run's gate mode and is recorded on a line that belongs to no attempt. A blocking
result under ``on`` raises the item of every part a blocking record names again, as a new
round quoting the finding, and the hold continues; nothing is dispatched and no review is
spent. A later round is judged from the same base, so a node declared in round one and not
written again is judged again. Under ``observe`` the run releases on the record; under ``off``
the call is skipped and the skip is recorded. A run that writes no declared value calls no gate.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import refusal
from gate_fixtures import graph, node
from parts_rig import body, decide, log_of, parts_items, started
from plan_hold_rig import again, dispatched, kinds
from release_rig import failing

from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.queue import QueueResolution
from physgate.state.schema import DECLARED_SOURCE
from physgate.state.store import Store

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]
STATED = {"mass": (0.4, "kg"), "stall_current": (2.4, "A")}
MOTOR = "control.motor_left"
SIZING_NODE = "sizing.control_motor_left"


def _of(log: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in log if one["kind"] == kind]


def _decided(tmp_path: Path, *, gate_mode: str = "on", results: tuple[Any, ...] = ()) -> Any:  # noqa: ANN401
    """A run whose parts are decided as have, make and find, its release's answers scripted."""
    the_rig = started(tmp_path / "run", gate_mode=gate_mode)
    assert again(the_rig) == "wait"
    if the_rig.gate is not None:
        the_rig.gate.release_results = list(results)
    run_dir = the_rig.run_dir
    assert isinstance(decide(run_dir, IDS[0], "have", body(STATED)), QueueResolution)
    made = body({"mass": (0.1, "kg")}, texts=("printed in PETG",))
    assert isinstance(decide(run_dir, IDS[1], "make", made), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    return the_rig


def _blocked_at(where: str) -> Any:  # noqa: ANN401
    return lambda mode: failing(mode, [("magnitude", where)])


# --- the loop ---------------------------------------------------------------------------------


def test_the_release_is_judged_once_from_the_head_before_the_first_parts_write(
    tmp_path: Path,
) -> None:
    the_rig = _decided(tmp_path)
    assert again(the_rig) == "done"
    (artefact,) = the_rig.gate.releases
    assert artefact.base_revision == 1
    assert artefact.scopes == ("subtask",)
    assert artefact.graph_root == str(the_rig.diff.root)
    order = kinds(the_rig.run_dir)
    assert order.count("parts_gate_ran") == 1
    last_write = max(i for i, k in enumerate(order) if k == "parts_write_done")
    assert last_write < order.index("parts_gate_ran") < order.index("parts_released")
    (ran,) = _of(log_of(the_rig.run_dir), "parts_gate_ran")
    assert (ran["gate_mode"], ran["base_revision"], ran["result"]["verdict"]) == ("on", 1, "pass")


def test_a_blocking_release_raises_the_named_part_again_and_nothing_is_dispatched(
    tmp_path: Path,
) -> None:
    the_rig = _decided(tmp_path, results=(_blocked_at(MOTOR),))
    assert again(the_rig) == "wait"
    log = log_of(the_rig.run_dir)
    (ran,) = _of(log, "parts_gate_ran")
    assert ran["result"]["verdict"] == "fail"
    (raised,) = _of(log, "parts_raised_again")
    assert raised["cause"] == "gate"
    assert [(p["item_id"], p["node"]) for p in raised["parts"]] == [(IDS[0] + "-r2", MOTOR)]
    assert "efficiency 1.5 on control.motor_left" in raised["parts"][0]["why"]
    assert _of(log, "parts_released") == []
    assert dispatched(the_rig.run_dir) == []
    assert the_rig.reviewer.seen == []
    again_item = next(i for i in parts_items(the_rig.run_dir) if i.item_id == IDS[0] + "-r2")
    assert "efficiency 1.5 on control.motor_left" in again_item.decision_required
    assert IDS[0] + "-r2" in {i.item_id for i in _open(the_rig.run_dir)}


def _open(run_dir: Path) -> list[Any]:
    from physgate.orchestrator.queue import read_queue

    return list(read_queue(run_dir).open_items())


def test_a_blocking_record_on_a_part_s_cross_node_raises_that_part_again(tmp_path: Path) -> None:
    the_rig = _decided(tmp_path, results=(_blocked_at(SIZING_NODE),))
    assert again(the_rig) == "wait"
    (raised,) = _of(log_of(the_rig.run_dir), "parts_raised_again")
    assert [p["item_id"] for p in raised["parts"]] == [IDS[0] + "-r2"]


def test_a_later_round_judges_every_declared_node_again_from_the_same_base(
    tmp_path: Path,
) -> None:
    the_rig = _decided(tmp_path, results=(_blocked_at(MOTOR),))
    assert again(the_rig) == "wait"
    restated = body({"mass": (0.5, "kg"), "stall_current": (2.0, "A")})
    assert isinstance(decide(the_rig.run_dir, IDS[0] + "-r2", "have", restated), QueueResolution)
    assert again(the_rig) == "done"
    first, second = the_rig.gate.releases
    # The IMU's node was declared in round one and is not written again in round two: with the
    # base still the head before the first parts write, it stays among the view's own nodes.
    assert first.base_revision == second.base_revision == 1
    log = log_of(the_rig.run_dir)
    round_two = [p for p in _of(log, "parts_write_intended") if p["item_id"].endswith("-r2")]
    assert [p["node_id"] for p in round_two] == [MOTOR, SIZING_NODE]
    assert "control.imu" not in {p["node_id"] for p in round_two}
    assert len(_of(log, "parts_gate_ran")) == 2
    (released,) = _of(log, "parts_released")
    assert released["components"][0]["item_id"] == IDS[0] + "-r2"
    assert "stage_entered" in kinds(the_rig.run_dir)


def test_under_observe_a_failing_release_is_recorded_and_the_run_released(tmp_path: Path) -> None:
    the_rig = _decided(tmp_path, gate_mode="observe", results=(_blocked_at(MOTOR),))
    assert again(the_rig) == "done"
    log = log_of(the_rig.run_dir)
    (ran,) = _of(log, "parts_gate_ran")
    assert (ran["gate_mode"], ran["result"]["verdict"]) == ("observe", "fail")
    assert _of(log, "parts_raised_again") == []
    assert len(_of(log, "parts_released")) == 1


def test_under_off_the_release_s_gate_is_skipped_and_the_skip_recorded(tmp_path: Path) -> None:
    the_rig = _decided(tmp_path, gate_mode="off")
    assert again(the_rig) == "done"
    log = log_of(the_rig.run_dir)
    (ran,) = _of(log, "parts_gate_ran")
    assert (ran["gate_mode"], ran["result"]) == ("off", None)
    assert the_rig.gate.releases == []
    assert len(_of(log, "parts_released")) == 1


def test_a_run_that_declares_nothing_calls_no_gate_at_its_release(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    for item_id in IDS:
        assert isinstance(decide(the_rig.run_dir, item_id, "find"), QueueResolution)
    assert again(the_rig) == "done"
    assert _of(log_of(the_rig.run_dir), "parts_gate_ran") == []
    assert the_rig.gate.releases == []


# --- the person's decision on a part raised again -----------------------------------------------


def _raised(tmp_path: Path) -> Path:
    the_rig = _decided(tmp_path, results=(_blocked_at(MOTOR),))
    assert again(the_rig) == "wait"
    return the_rig.run_dir


def test_a_part_raised_again_cannot_be_found_instead(tmp_path: Path) -> None:
    said = decide(_raised(tmp_path), IDS[0] + "-r2", "find")
    assert not isinstance(said, QueueResolution)
    assert "find" in str(said) and "raised again" in str(said)


def test_a_part_raised_again_must_state_every_name_it_declared_before(tmp_path: Path) -> None:
    said = decide(_raised(tmp_path), IDS[0] + "-r2", "have", body({"mass": (0.5, "kg")}))
    assert not isinstance(said, QueueResolution)
    assert "stall_current" in str(said)


def test_a_part_raised_again_may_change_its_values_and_add_a_name(tmp_path: Path) -> None:
    restated = body({"mass": (0.5, "kg"), "stall_current": (2.0, "A"), "torque": (0.2, "N*m")})
    said = decide(_raised(tmp_path), IDS[0] + "-r2", "make", restated)
    assert isinstance(said, QueueResolution), said


def test_a_first_round_part_may_still_be_found(tmp_path: Path) -> None:
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    assert isinstance(decide(the_rig.run_dir, IDS[0], "find"), QueueResolution)


# --- the replay ---------------------------------------------------------------------------------


def test_replay_refuses_a_part_raised_again_that_the_gate_did_not_name(tmp_path: Path) -> None:
    run_dir = _raised(tmp_path)
    log = log_of(run_dir)
    assert refusal(tmp_path, log) == ""
    at = next(i for i, one in enumerate(log) if one["kind"] == "parts_raised_again")
    forged = dict(log[at])
    forged["parts"] = [{**forged["parts"][0], "item_id": IDS[1] + "-r2", "node": "control.imu"}]
    assert "raised again" in refusal(tmp_path, [*log[:at], forged])


def test_replay_refuses_a_release_after_a_blocking_gate_line(tmp_path: Path) -> None:
    run_dir = _raised(tmp_path)
    log = log_of(run_dir)
    at = next(i for i, one in enumerate(log) if one["kind"] == "parts_raised_again")
    done = log_of(_released(tmp_path / "other"))
    released = next(one for one in done if one["kind"] == "parts_released")
    assert refusal(tmp_path, [*log[:at], {**released, "ts": log[at]["ts"]}]) != ""


def _released(tmp_path: Path) -> Path:
    the_rig = _decided(tmp_path)
    assert again(the_rig) == "done"
    return the_rig.run_dir


# --- the gate itself, over a real store ---------------------------------------------------------


def _release_artefact(**fields: Any) -> Any:  # noqa: ANN401
    module = importlib.import_module("physgate.orchestrator.parts_write")
    build = getattr(module, "release_artefact", None)
    if build is None:
        pytest.fail("parts_write.release_artefact is not built yet")
    return build(**fields)


def _declare(root: Path, node_id: str, name: str, value: float, unit: str) -> int:
    payload = node(node_id, domain="electrical")
    payload["quantities"] = {
        name: {
            "value": value,
            "unit": unit,
            "source": DECLARED_SOURCE,
            "written_by": payload["owner_role"],
            "declared": {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "x"},
        }
    }
    store = Store(root)
    try:
        result = store.declare(payload, ("run-1-parts-1",))
        assert result.accepted, result
        return store.head_revision()
    finally:
        store.close()


def test_a_declared_efficiency_of_one_and_a_half_is_blocked_at_the_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "graph"
    head = graph(root, node("electrical.supply", quantities={"voltage": (12, "V")}))
    _declare(root, "electrical.motor", "efficiency", 1.5, "dimensionless")
    artefact = _release_artefact(
        graph_root=str(root), base_revision=head, run_dir=tmp_path, commit="0" * 40
    )
    result = PhysicsGate().check(artefact, mode="on")
    assert result.verdict == "fail"
    blocking = [r for r in result.checks if r.outcome == "fail" and r.blocking]
    assert [(r.name, r.node) for r in blocking] == [("magnitude", "electrical.motor")]


def test_the_same_efficiency_within_its_envelope_passes_at_the_release(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    head = graph(root, node("electrical.supply", quantities={"voltage": (12, "V")}))
    _declare(root, "electrical.motor", "efficiency", 0.8, "dimensionless")
    artefact = _release_artefact(
        graph_root=str(root), base_revision=head, run_dir=tmp_path, commit="0" * 40
    )
    assert PhysicsGate().check(artefact, mode="on").verdict == "pass"
