"""A declared node keeps its edges, so the module's relations still count its declared value.

ARCH-122 with the gate's relations. A module's mass, power and loads read their members through
the members' ``constrains`` edges. A role that could take a declared part's edge away would take
the declared value out of its module's balance, and a balance that failed on it would pass. The
store refuses that write (``declared_fixed``); over the real store and the real gate, the module's
mass sum still reads the declared member after the refused attempt, and still fails on it. The
same graph with the edge never written passes the sum: the refusal is what keeps the finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from physgate.gate.graph import GraphView
from physgate.gate.relations import TermRef, instances
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import GateResult
from physgate.state.store import Store

MODULE = "electrical.drive"
WHEEL = "electrical.motor_right"
MOTOR = "electrical.motor_left"


def _plain(value: float) -> dict[str, Any]:
    return {"value": value, "unit": "kg", "source": "datasheet", "written_by": "electrical"}


def _declared(value: float) -> dict[str, Any]:
    return {
        "value": value,
        "unit": "kg",
        "source": "declared by the person",
        "written_by": "electrical",
        "declared": {
            "item_id": "run-1-parts-1",
            "decision_sha256": "a" * 64,
            "operator": "operator",
        },
    }


def _node(node_id: str, quantities: dict[str, Any], **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "id": node_id,
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-11-15T12:00:00.000000Z",
    } | fields


def _graph(root: Path, *, joined: bool) -> Store:
    """A module whose mass leaves out the person's motor; the motor joined to it or not."""
    store = Store(root)
    module = _node(MODULE, {"mass": _plain(0.3)}, kind="module")
    assert store.write_node(module, "electrical").accepted
    wheel = _node(WHEEL, {"mass": _plain(0.3)}, constrains=[MODULE])
    assert store.write_node(wheel, "electrical").accepted
    motor = _node(MOTOR, {"mass": _declared(0.2)})
    assert store.declare(motor, ["run-1-parts-1"]).accepted
    if joined:
        assert store.write_node({**motor, "constrains": [MODULE]}, "electrical").accepted
    return store


def _gate(root: Path) -> GateResult:
    return PhysicsGate().run(GraphView.read(root, 0), ("system",), "on")


def _failing(result: GateResult) -> set[str]:
    return {r.name for r in result.checks if r.outcome == "fail" and r.blocking}


def _members(root: Path) -> tuple[TermRef, ...]:
    found = [
        i
        for i in instances(GraphView.read(root, 0))
        if i.relation.name == "mass_sum" and i.subject == MODULE
    ]
    assert len(found) == 1, found
    return tuple(t for t in found[0].right if isinstance(t, TermRef))


def test_after_a_refused_attempt_to_unjoin_it_the_module_s_mass_still_counts_the_declared_part(
    tmp_path: Path,
) -> None:
    root = tmp_path / "g"
    store = _graph(root, joined=True)
    try:
        before = store.head_revision()
        unjoined = _node(MOTOR, {"mass": _declared(0.2)})
        refused = store.write_node(unjoined, "electrical")
        assert (refused.accepted, refused.reason) == (False, "declared_fixed")
        assert store.head_revision() == before
        assert store.read_node(MOTOR)["constrains"] == [MODULE]
    finally:
        store.close()
    assert TermRef(MOTOR, "mass") in _members(root)
    result = _gate(root)
    assert "conservation" in _failing(result)
    held = [r for r in result.checks if r.name == "conservation" and r.outcome == "fail"]
    assert [r.node for r in held] == [MODULE]


def test_the_same_graph_with_the_edge_never_written_passes_the_sum(tmp_path: Path) -> None:
    root = tmp_path / "g"
    _graph(root, joined=False).close()
    assert TermRef(MOTOR, "mass") not in _members(root)
    assert "conservation" not in _failing(_gate(root))
