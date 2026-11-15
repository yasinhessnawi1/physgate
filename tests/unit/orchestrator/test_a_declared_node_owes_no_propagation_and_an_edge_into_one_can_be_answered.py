"""The propagation check and a person's declared parts, over the real store and the real gate.

ARCH-082 with ARCH-122. The system-scope call is told a history whose baseline is past the parts
writes, as decomposition's interface nodes are below it: a declared node is given design, and its
own edges owe no propagation. An edge from a role's changed node into a declared node is judged as
any edge is: left unwritten it fails, naming the edge; the declared node's owner can answer it by
writing the node again with every declared quantity as it stands and its reason in
``no_change_justified``, which the store accepts and the check records as a justified edge.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.change_sets import integration_history
from physgate.orchestrator.events import Decomposed, Event, PartsWriteDone, RunStarted, WriteDone
from physgate.orchestrator.protocols import ChangeSet, GateResult, IntegrationArtefact
from physgate.state.store import Store

TS = "2026-11-15T12:00:00.000000Z"
DRIVER = "electrical.driver"
MOTOR = "control.motor_left"
CROSS = "sizing.control_motor_left"
REASON = "the part is the person's own; a stall torque budget does not change its mass"


def env(seq: int) -> dict[str, Any]:
    return {"seq": seq, "ts": TS, "run_id": "run-1", "gate_mode": "on"}


def _plain(value: float, unit: str, by: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "datasheet", "written_by": by}


def _declared(value: float, unit: str, by: str, item: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "source": "declared by the person",
        "written_by": by,
        "declared": {"item_id": item, "decision_sha256": "a" * 64, "operator": "operator"},
    }


def _node(
    node_id: str,
    owner: str,
    domain: str,
    quantities: dict[str, Any],
    **fields: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": domain,
        "owner_role": owner,
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-15T12:00:00.000000Z",
    } | fields


MOTOR_DECLARED = {"mass": _declared(0.0095, "kg", "control", "run-1-parts-1")}
CROSS_DECLARED = {"stall_current": _declared(1.6, "A", "sizing", "run-1-parts-1")}


def _motor(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return _node(MOTOR, "control", "control", dict(MOTOR_DECLARED), **fields)


def _cross(quantities: dict[str, Any] | None = None) -> dict[str, Any]:
    return _node(
        CROSS, "sizing", "cross", {**CROSS_DECLARED, **(quantities or {})}, constrains=[MOTOR]
    )


def _given(root: Path) -> list[Event]:
    """Decomposition's head, then the motor's part declared on its node and on sizing's."""
    store = Store(root)
    try:
        driver = _node(DRIVER, "electrical", "electrical", {})
        assert store.write_node(driver, "electrical").accepted
        assert store.declare(_motor(), ["run-1-parts-1"]).accepted
        assert store.declare(_cross(), ["run-1-parts-1"]).accepted
    finally:
        store.close()
    return [
        RunStarted(**env(0), config_sha256="a" * 64),
        Decomposed(
            **env(1),
            session_id="decomp",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=2,
            interface_nodes=("iface.power_bus",),
            spec_commit="a" * 40,
            head_revision=1,
        ),
        PartsWriteDone(**env(2), node_id=MOTOR, revision=2),
        PartsWriteDone(**env(3), node_id=CROSS, revision=3),
    ]


def _attempt(
    root: Path, events: list[Event], subtask: str, payload: dict[str, Any], role: str
) -> None:
    """``role``'s attempt ``subtask`` writes ``payload``, merged: its write in the log."""
    store = Store(root)
    try:
        written = store.write_node(payload, role)
    finally:
        store.close()
    assert written.accepted and written.revision is not None, written
    events.append(
        WriteDone(
            **env(len(events)),
            subtask_id=subtask,
            attempt=1,
            node_id=str(payload["id"]),
            revision=written.revision,
        )
    )


def _call(root: Path, history: tuple[int, Sequence[ChangeSet]]) -> GateResult | Exception:
    baseline, change_sets = history
    artefact = IntegrationArtefact(
        run_id="run-1",
        graph_root=str(root),
        run_head="b" * 40,
        baseline_revision=baseline,
        change_sets=tuple(change_sets),
    )
    return _outcome(lambda: PhysicsGate().check_integration(artefact, mode="on"))


def _outcome(how: Callable[[], GateResult]) -> GateResult | Exception:
    try:
        return how()
    except Exception as exc:  # noqa: BLE001 - a refused call is what a row asserts against
        return exc


def _propagation(result: GateResult | Exception) -> list[tuple[str, str]]:
    assert isinstance(result, GateResult), f"the call was refused: {result!r}"
    return [
        (record.outcome, record.message)
        for record in result.checks
        if record.name == "propagation" and record.outcome != "pass"
    ]


def test_a_declared_node_s_own_edge_owes_no_propagation(tmp_path: Path) -> None:
    root = tmp_path / "store"
    events = _given(root)
    _attempt(root, events, "s1", _node(DRIVER, "electrical", "electrical", {}), "electrical")
    result = _call(root, integration_history(events))
    assert _propagation(result) == []
    assert isinstance(result, GateResult), result
    assert result.verdict == "pass", result.finding
    # Named as change sets of their own, the parts writes would owe sizing's edge to the motor.
    named = (1, (ChangeSet(subtask_id="m", attempt=1, revisions=(2,)),
                 ChangeSet(subtask_id="c", attempt=1, revisions=(3,)),
                 ChangeSet(subtask_id="s1", attempt=1, revisions=(4,))))  # fmt: skip
    assert [o for o, m in _propagation(_call(root, named)) if CROSS in m and MOTOR in m] == ["fail"]


def test_a_role_s_change_into_a_declared_node_fails_until_its_owner_answers_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    events = _given(root)
    # Sizing writes a value of its own beside the declared one; its edge reaches the motor.
    _attempt(root, events, "s1", _cross({"stall_torque": _plain(0.17, "N*m", "sizing")}), "sizing")
    unanswered = _propagation(_call(root, integration_history(events)))
    assert unanswered == [
        (
            "fail",
            f"{CROSS} changed (stall_torque) and the nodes it constrains were not rewritten "
            f"after it and give no reason why not: {MOTOR}",
        )
    ]
    # The motor's owner writes the node again, the declared mass as it stands, with its reason.
    _attempt(root, events, "s2", _motor(no_change_justified={CROSS: REASON}), "control")
    answered = _call(root, integration_history(events))
    found = _propagation(answered)
    assert [outcome for outcome, _ in found] == ["unchecked"]
    assert REASON in found[0][1]
    assert isinstance(answered, GateResult), answered
    assert answered.verdict == "pass", answered.finding
