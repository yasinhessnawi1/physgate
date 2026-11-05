"""A stall above the current limit on its own node is refused as that node's.

The finding says the limit is on the node's own, and names the node once among those that
contribute; a stall above a supply's limit is still refused naming the supply and the motor.
"""

from __future__ import annotations

from pathlib import Path

from gate_fixtures import graph, node

from physgate.gate import check_power
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import PowerDetails


def test_the_finding_says_the_limit_is_on_its_own_node_and_names_it_once(tmp_path: Path) -> None:
    graph(
        tmp_path / "g",
        node(
            "electrical.drive",
            quantities={"stall_current": (2.1, "A"), "current_limit": (1.8, "A")},
        ),
    )
    view = GraphView.read(tmp_path / "g", base_revision=0)
    (finding,) = check_power.run(
        CheckContext(view=view, scope="system", bounds=load_bounds())
    ).observations
    assert "current limit on its own node" in finding.message
    assert isinstance(finding.details, PowerDetails)
    assert finding.details.contributing == ("electrical.drive",)


def test_a_supply_s_limit_is_still_named_as_the_supply_s(tmp_path: Path) -> None:
    graph(
        tmp_path / "g",
        node("electrical.driver", quantities={"current_limit": (1.8, "A")}),
        node(
            "electrical.motor",
            quantities={"stall_current": (2.1, "A")},
            constrains=["electrical.driver"],
        ),
    )
    view = GraphView.read(tmp_path / "g", base_revision=0)
    (finding,) = check_power.run(
        CheckContext(view=view, scope="system", bounds=load_bounds())
    ).observations
    assert "current limit of electrical.driver" in finding.message
    assert isinstance(finding.details, PowerDetails)
    assert finding.details.contributing == ("electrical.driver", "electrical.motor")
