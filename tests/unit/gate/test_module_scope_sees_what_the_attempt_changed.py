"""Module scope sees everything an attempt changed, including what it took away.

An attempt that rewrites a node can change a mount or a module it never wrote:
removing a support's edge leaves the plate with one support fewer, and moving a
member out of a module leaves the module's declared mass counting a member it no
longer has. Both are refused at the attempt's own module scope. So is an energy
balance broken on a node that belongs to no module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gate_fixtures import graph, node

from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import GateResult

M = "mechanical"


def attempt(tmp_path: Path, base: list[dict[str, Any]], written: list[dict[str, Any]]) -> GraphView:
    root = tmp_path / "g"
    head = graph(root, *base) if base else 0
    graph(root, *written)
    return GraphView.read(root, base_revision=head)


def gated(view: GraphView) -> GateResult:
    return PhysicsGate().run(view, ("subtask", "module"), "on")


def standoff(name: str, x: float, *, attached: bool = True) -> dict[str, Any]:
    return node(
        f"{M}.{name}",
        domain=M,
        quantities={"support_position": (x, "m"), "reaction_force": (4.903325, "N")},
        constrains=[f"{M}.plate"] if attached else [],
    )


def two_pin_plate() -> list[dict[str, Any]]:
    return [
        node(f"{M}.plate", domain=M, kind="module"),
        standoff("standoff0", 0),
        standoff("standoff1", 0.2),
        node(
            f"{M}.board",
            domain=M,
            quantities={"mount_position": (0.1, "m"), "mass": (1, "kg")},
            constrains=[f"{M}.plate"],
        ),
    ]


def test_an_attempt_that_removes_a_support_s_edge_is_refused_for_the_mount_it_left(
    tmp_path: Path,
) -> None:
    view = attempt(tmp_path, two_pin_plate(), [standoff("standoff1", 0.2, attached=False)])
    assert view.own() == (f"{M}.standoff1",)
    assert f"{M}.plate" in view.affected()
    result = gated(view)
    assert result.verdict == "fail" and result.failing_check == "equilibrium"


def test_the_same_plate_left_intact_passes(tmp_path: Path) -> None:
    view = attempt(tmp_path, two_pin_plate(), [standoff("standoff1", 0.2)])
    assert gated(view).verdict == "pass"


def chassis(*, b_attached: bool) -> list[dict[str, Any]]:
    member = [f"{M}.chassis"]
    return [
        node(f"{M}.chassis", domain=M, kind="module", quantities={"mass": (2, "kg")}),
        node(f"{M}.a", domain=M, quantities={"mass": (1, "kg")}, constrains=member),
        node(
            f"{M}.b",
            domain=M,
            quantities={"mass": (1, "kg")},
            constrains=member if b_attached else [],
        ),
    ]


def test_an_attempt_that_moves_a_member_out_of_a_module_is_refused_for_its_mass(
    tmp_path: Path,
) -> None:
    detached = chassis(b_attached=False)[2]
    result = gated(attempt(tmp_path, chassis(b_attached=True), [detached]))
    assert result.verdict == "fail" and result.failing_check == "conservation"
    (finding,) = [r for r in result.checks if r.name == "conservation" and r.outcome == "fail"]
    assert finding.node == f"{M}.chassis"


def test_an_energy_balance_is_checked_on_a_node_that_belongs_to_no_module(
    tmp_path: Path,
) -> None:
    # 10 W in, 2 W out, 1 W of heat: 7 W unaccounted for, on a node with no edges.
    regulator = node(
        "electrical.regulator",
        quantities={
            "input_power": (10, "W"),
            "output_power": (2, "W"),
            "heat_dissipation": (1, "W"),
        },
    )
    result = gated(attempt(tmp_path, [], [regulator]))
    assert result.verdict == "fail" and result.failing_check == "conservation"


def test_the_affected_set_names_the_edges_before_and_after_the_attempt(tmp_path: Path) -> None:
    base = [
        node(f"{M}.plate", domain=M, kind="module"),
        node(f"{M}.arm", domain=M, kind="module"),
        node(f"{M}.clip", domain=M, constrains=[f"{M}.plate"]),
    ]
    moved = node(f"{M}.clip", domain=M, constrains=[f"{M}.arm"])
    view = attempt(tmp_path, base, [moved])
    assert view.affected() == (f"{M}.arm", f"{M}.clip", f"{M}.plate")
    assert view.modules_touched() == (f"{M}.arm", f"{M}.plate")
