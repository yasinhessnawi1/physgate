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
DECLARED = frozenset(
    {(MOTOR, "mass"), (IMU, "mass"), ("sizing.control_motor_left", "stall_current")}
)


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


# --- what the real checks name ----------------------------------------------------------------
# A check does not always name every value its failure rests on: the conservation check names a
# relation's first term only, and the loads reading of the equilibrium check names none. Only the
# magnitude check names exactly the one value it judged, so only a finding made of magnitude
# records alone can say it is about declared values and nothing else.

DRIVER = "electrical.driver"
IMU_RATE = ("electrical.imu", "sample_rate")


def _real(tmp_path: Path, *payloads: dict[str, Any]) -> Any:  # noqa: ANN401
    """The registered gate's result at system scope over ``payloads``, all given design."""
    from gate_fixtures import graph

    from physgate.gate.graph import GraphView
    from physgate.gate.runner import PhysicsGate

    graph(tmp_path / "g", *payloads)
    return PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ("system",), "on")


def _shape(result: Any) -> tuple[list[tuple[str, str]], list[str]]:  # noqa: ANN401
    named = [(q.node_id, q.name) for q in result.quantities]
    blocking = sorted({r.name for r in result.checks if r.outcome == "fail" and r.blocking})
    return named, blocking


def test_an_energy_balance_that_names_only_its_declared_first_term_is_not_all_declared(
    tmp_path: Path,
) -> None:
    from gate_fixtures import node

    # Power in is declared; power out and heat are a role's. The balance names power in alone.
    driver = node(
        DRIVER,
        quantities={
            "input_power": (10, "W"),
            "output_power": (9, "W"),
            "heat_dissipation": (0.5, "W"),
        },
        constrains=["electrical.drive"],
    )
    result = _real(tmp_path, node("electrical.drive", kind="module"), driver)
    assert _shape(result) == ([(DRIVER, "input_power")], ["conservation"])
    assert all_declared(result, frozenset({(DRIVER, "input_power")})) is False


def test_a_module_mass_that_names_only_its_declared_whole_is_not_all_declared(
    tmp_path: Path,
) -> None:
    from gate_fixtures import CONSERVATION

    result = _real(tmp_path, *CONSERVATION)
    named, blocking = _shape(result)
    assert blocking == ["conservation"] and len(named) == 1
    assert all_declared(result, frozenset(named)) is False


def test_a_loads_failure_naming_nothing_beside_a_declared_magnitude_is_not_all_declared(
    tmp_path: Path,
) -> None:
    from gate_fixtures import MAGNITUDE, node

    # A gearbox whose reaction moment was left at an old torque: the loads reading names no value.
    gearbox = node(
        "mechanical.gearboxes",
        domain="mechanical",
        quantities={"torque_peak": (0.38, "N*m"), "reaction_moment": (1.1, "N*m")},
    )
    result = _real(tmp_path, gearbox, *MAGNITUDE)
    assert _shape(result) == ([IMU_RATE], ["equilibrium", "magnitude"])
    assert all_declared(result, frozenset({IMU_RATE})) is False


def test_a_real_magnitude_failure_on_a_declared_value_alone_is_all_declared(
    tmp_path: Path,
) -> None:
    from gate_fixtures import MAGNITUDE

    result = _real(tmp_path, *MAGNITUDE)
    assert _shape(result) == ([IMU_RATE], ["magnitude"])
    assert all_declared(result, frozenset({IMU_RATE})) is True
    assert all_declared(result, frozenset()) is False


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


def _released(
    tmp_path: Path,
    attempt_one: Any,  # noqa: ANN401
    declared: dict[str, tuple[Any, Any]] | None = None,
) -> Any:  # noqa: ANN401
    """A run whose motor's mass is declared, released; its first attempt's gate answer set."""
    the_rig = started(tmp_path / "run")
    assert again(the_rig) == "wait"
    assert the_rig.gate is not None
    the_rig.gate.results = {1: attempt_one}
    run_dir = the_rig.run_dir
    stated = body(declared or {"mass": (0.4, "kg"), "stall_current": (2.4, "A")})
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
    from physgate.orchestrator.queue import read_queue

    item = next(i for i in read_queue(the_rig.run_dir).items if i.subtask_id == "s1")
    assert "declared" in item.decision_required
    assert f"{MOTOR} mass = 0.4 kg" in item.decision_required
    assert "no repair attempt was spent" in item.decision_required


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
    mass_lines = [line for line in repair.splitlines() if f"{MOTOR} mass" in line]
    assert len(mass_lines) == 1, repair
    mass_line = mass_lines[0]
    assert "declared by the person" in mass_line and "fixed" in mass_line
    # An undeclared quantity is named from the second repair on, as before, and never as fixed.
    torque_lines = [line for line in repair.splitlines() if f"{MOTOR} torque" in line]
    assert all("declared" not in line for line in torque_lines)


def test_a_real_balance_naming_only_a_declared_term_goes_to_the_role_s_repair(
    tmp_path: Path,
) -> None:
    from gate_fixtures import node

    # The motor's power in is declared; its power out and heat are the role's to repair. The
    # registered gate's own result names power in alone.
    motor = node(
        MOTOR,
        domain="control",
        quantities={
            "input_power": (10, "W"),
            "output_power": (9, "W"),
            "heat_dissipation": (0.5, "W"),
        },
    )
    real = _real(tmp_path / "gate", motor)
    assert _shape(real) == ([(MOTOR, "input_power")], ["conservation"])
    the_rig = _released(
        tmp_path,
        lambda mode: real,
        {"input_power": (10, "W"), "stall_current": (2.4, "A")},
    )
    again(the_rig)
    first = _decided(log_of(the_rig.run_dir))[0]
    assert first["subtask_id"] == "s1" and first["attempt"] == 1
    assert first["decision"]["forced"] is False
    assert "all_declared" not in first["state"]["gate"]
    s1 = [r for r in the_rig.dispatcher.requests if r.subtask_id == "s1"]
    assert [r.attempt for r in s1][:2] == [1, 2]


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


@pytest.mark.parametrize(
    ("kind", "by", "expected"),
    [("rejected", "gate", True), ("rejected", "review", False), ("review_blocked", None, False)],
    ids=["the-gate-rejected-it", "a-review-rejected-it", "a-blocked-review"],
)
def test_the_mark_forces_only_an_attempt_the_gate_rejected(
    kind: str, by: str | None, expected: bool
) -> None:
    from physgate.orchestrator.escalation_state import EndPart, EscalationState

    # Built without validation, from the two parts the mark reads: the rest is not read.
    ended: dict[str, Any] = {"kind": kind, "rejected_by": by}
    gate: dict[str, Any] = {"all_declared": True}
    parts: dict[str, Any] = {
        "ended": EndPart.model_construct(**ended),
        "gate": GatePart.model_construct(**gate),
    }
    state = EscalationState.model_construct(**parts)
    assert state.all_declared is expected
