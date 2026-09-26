"""The gate's view of the graph: read from the journal alone, and nothing written."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from gate_fixtures import graph, node

from physgate.gate.graph import GraphView
from physgate.state.exceptions import CorruptRecordError

DRIVE = node("electrical.drive", kind="module", quantities={"power_supply": (15, "W")})
MOTOR = node(
    "electrical.motor_left",
    quantities={"power_draw": (9, "W")},
    constrains=["electrical.drive", "mechanical.chassis"],
)
CHASSIS = node("mechanical.chassis", kind="module", domain="mechanical")
BATTERY = node("electrical.battery", quantities={"power_supply": (24, "W")})


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_the_view_holds_every_node_at_its_latest_payload(tmp_path: Path) -> None:
    root = tmp_path / "g"
    graph(root, DRIVE, CHASSIS, MOTOR)
    changed = dict(MOTOR, quantities={**MOTOR["quantities"]})
    changed["quantities"]["power_draw"] = dict(changed["quantities"]["power_draw"], value=10)
    graph(root, changed)
    view = GraphView.read(root, base_revision=0)
    assert list(view.nodes) == ["electrical.drive", "electrical.motor_left", "mechanical.chassis"]
    assert view.nodes["electrical.motor_left"].quantities["power_draw"].value == 10
    assert view.revisions["electrical.motor_left"] == 4


def test_the_attempt_s_own_nodes_are_those_above_the_base_revision(tmp_path: Path) -> None:
    root = tmp_path / "g"
    base = graph(root, DRIVE, CHASSIS)
    graph(root, MOTOR)
    view = GraphView.read(root, base_revision=base)
    assert view.own() == ("electrical.motor_left",)
    assert GraphView.read(root, base_revision=0).own() == (
        "electrical.drive",
        "electrical.motor_left",
        "mechanical.chassis",
    )


def test_modules_are_read_off_the_constrains_edges(tmp_path: Path) -> None:
    root = tmp_path / "g"
    base = graph(root, DRIVE, CHASSIS, BATTERY)
    graph(root, MOTOR)
    view = GraphView.read(root, base_revision=base)
    assert view.modules() == ("electrical.drive", "mechanical.chassis")
    assert view.modules_touched() == ("electrical.drive", "mechanical.chassis")
    assert view.module_of("electrical.motor_left") == "electrical.drive"
    assert view.module_of("electrical.drive") == "electrical.drive"
    assert view.module_of("electrical.battery") is None
    assert view.constrained_by("electrical.drive") == ("electrical.motor_left",)
    assert view.constrained_by("electrical.battery") == ()


def test_reading_the_graph_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "g"
    graph(root, DRIVE, CHASSIS, MOTOR)
    # A node file changed on disk: a store's open would repair it; the gate's read may not.
    node_file = next((root / "nodes").glob("*.json"))
    node_file.write_bytes(node_file.read_bytes() + b" ")
    before = snapshot(root)
    GraphView.read(root, base_revision=0)
    assert snapshot(root) == before


def test_an_empty_graph_is_an_empty_view(tmp_path: Path) -> None:
    view = GraphView.read(tmp_path / "missing", base_revision=0)
    assert dict(view.nodes) == {} and view.own() == () and view.modules() == ()


def test_a_journal_line_the_store_could_not_have_written_fails_the_read(tmp_path: Path) -> None:
    root = tmp_path / "g"
    graph(root, DRIVE)
    journal = next(p for p in root.iterdir() if p.is_file() and p.suffix == ".jsonl")
    with journal.open("ab") as handle:
        handle.write(b'{"rev": 1, "op": "create"}\n')
    with pytest.raises(CorruptRecordError):
        GraphView.read(root, base_revision=0)
