"""A gate finding on declared values alone goes to the person, spending no repair attempt.

ARCH-122, ARCH-131. The recorded gate line keeps only the first three blocking quantities, not
each observation's, so a blocking result is read as all-declared only when it names fewer than
three quantities (none was cut), every one is declared at the head, and no blocking record is a
units failure (the units check names no quantity). Such an attempt end is a forced route to the
queue; every other case routes as it did, and a repair names a declared value as fixed.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from parts_rig import body, decide, log_of, started
from plan_hold_rig import again
from release_rig import failing, ref

from physgate.orchestrator.escalation import forced
from physgate.orchestrator.escalation_state import GatePart
from physgate.orchestrator.queue import QueueResolution

MOTOR = "control.motor_left"
IMU = "control.imu"
DECLARED = {(MOTOR, "mass"), (IMU, "mass"), ("sizing.control_motor_left", "stall_current")}


def all_declared(result: Any, declared: Any) -> bool:  # noqa: ANN401
    module = importlib.import_module("physgate.orchestrator.escalation_state")
    found = getattr(module, "all_declared", None)
    if found is None:
        pytest.fail("escalation_state.all_declared is not built yet")
    answer: bool = found(result, declared)
    return answer


@pytest.mark.parametrize(
    ("records", "quantities", "expected"),
    [
        ([("magnitude", MOTOR)], [ref(MOTOR, "mass")], True),
        ([("magnitude", MOTOR), ("magnitude", IMU)], [ref(MOTOR, "mass"), ref(IMU, "mass")], True),
        (
            [("magnitude", MOTOR), ("magnitude", IMU), ("magnitude", "sizing.control_motor_left")],
            [
                ref(MOTOR, "mass"),
                ref(IMU, "mass"),
                ref("sizing.control_motor_left", "stall_current"),
            ],
            False,
        ),
        ([("magnitude", MOTOR)], [ref(MOTOR, "mass"), ref(MOTOR, "torque")], False),
        ([("magnitude", MOTOR), ("units", MOTOR)], [ref(MOTOR, "mass")], False),
        ([("units", MOTOR)], [], False),
        ([("magnitude", MOTOR)], [], False),
    ],
    ids=[
        "one-declared",
        "two-declared",
        "exactly-three-named-all-declared",
        "one-undeclared",
        "a-units-failure-among-them",
        "a-units-failure-alone",
        "no-quantity-named",
    ],
)
def test_a_blocking_result_is_all_declared_only_inside_what_the_record_can_say(
    records: list[tuple[str, str]], quantities: list[Any], expected: bool
) -> None:
    assert all_declared(failing("on", records, quantities), DECLARED) is expected


def test_a_passing_result_and_no_result_are_never_all_declared() -> None:
    from release_rig import passing

    assert all_declared(passing("on"), DECLARED) is False
    assert all_declared(None, DECLARED) is False


def test_the_gate_part_leaves_the_mark_out_when_it_is_not_set() -> None:
    fields = {"ran": True, "mode": "on", "verdict": "fail", "failing_check": "magnitude"}
    plain = GatePart.model_validate({**fields, "checks": ()})
    assert "all_declared" not in plain.model_dump()
    marked = GatePart.model_validate({**fields, "checks": (), "all_declared": True})
    assert marked.model_dump()["all_declared"] is True


@pytest.mark.parametrize(("marked", "expected"), [(True, True), (False, False)])
def test_an_all_declared_first_rejection_is_forced_and_any_other_is_not(
    marked: bool, expected: bool
) -> None:
    state = SimpleNamespace(attempt_end="rejected", attempt_count=1, all_declared=marked)
    assert forced(state) is expected


# --- the loop ---------------------------------------------------------------------------------


def _released(tmp_path: Path, attempt_one: Any) -> Any:  # noqa: ANN401
    """A run whose motor's mass is declared, released; its first attempt's gate answer set."""
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    the_rig.gate.results = {1: attempt_one}
    run_dir = the_rig.run_dir
    stated = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")})
    assert isinstance(decide(run_dir, "run-1-parts-1", "have", stated), QueueResolution)
    assert isinstance(decide(run_dir, "run-1-parts-2", "find"), QueueResolution)
    assert isinstance(decide(run_dir, "run-1-parts-3", "find"), QueueResolution)
    return the_rig


def _decided(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [one for one in log if one["kind"] == "escalation_decided"]


def test_an_all_declared_finding_goes_to_the_queue_after_the_first_attempt(
    tmp_path: Path,
) -> None:
    the_rig = _released(
        tmp_path,
        lambda mode: failing(mode, [("magnitude", MOTOR)], [ref(MOTOR, "mass", 0.4, "kg")]),
    )
    again(the_rig)
    log = log_of(the_rig.run_dir)
    first = _decided(log)[0]
    assert first["subtask_id"] == "s1" and first["attempt"] == 1
    assert first["decision"]["forced"] is True
    assert first["state"]["gate"]["all_declared"] is True
    s1 = [r for r in the_rig.dispatcher.requests if r.subtask_id == "s1"]
    assert [r.attempt for r in s1] == [1]


def test_a_mixed_finding_goes_back_to_the_role_marking_the_declared_value_fixed(
    tmp_path: Path,
) -> None:
    mixed = [ref(MOTOR, "mass", 0.4, "kg"), ref(MOTOR, "torque", 9.0, "N*m")]
    the_rig = _released(tmp_path, lambda mode: failing(mode, [("magnitude", MOTOR)], mixed))
    again(the_rig)
    log = log_of(the_rig.run_dir)
    first = _decided(log)[0]
    assert first["decision"]["forced"] is False
    assert "all_declared" not in first["state"]["gate"]
    s1 = [r for r in the_rig.dispatcher.requests if r.subtask_id == "s1"]
    assert [r.attempt for r in s1][:2] == [1, 2]
    repair = s1[1].repair_instruction or ""
    mass_line = next(line for line in repair.splitlines() if f"{MOTOR} mass" in line)
    torque_line = next(line for line in repair.splitlines() if f"{MOTOR} torque" in line)
    assert "declared by the person" in mass_line and "fixed" in mass_line
    assert "declared" not in torque_line


def test_a_finding_on_an_undeclared_value_routes_as_it_always_did(tmp_path: Path) -> None:
    the_rig = _released(
        tmp_path,
        lambda mode: failing(mode, [("magnitude", "control.board")], [ref("control.board", "x")]),
    )
    again(the_rig)
    first = _decided(log_of(the_rig.run_dir))[0]
    assert first["decision"]["forced"] is False
    assert "all_declared" not in first["state"]["gate"]
    s1 = [r for r in the_rig.dispatcher.requests if r.subtask_id == "s1"]
    assert [r.attempt for r in s1][:2] == [1, 2]
    assert "declared" not in (s1[1].repair_instruction or "")
