"""The gate is built with the law table in the checkout, or it is not built.

The gate loads the law table once, when it is built, as it loads the bounds table: each law's
probation state comes from that table and nowhere else, and every result names the table by the
catalogue digest. A table that does not load stops the gate from being built, so a run never
starts on a gate that read half its laws. The tracked table loads, and the evaluation instrument
names the digest of the gate it runs, never one computed apart from it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gate_fixtures import fixed, graph, node
from law_fixtures import laws_module, sound_law, table_of, write_table

from physgate.gate import catalogue
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate

ROOT = Path(__file__).resolve().parents[3]


def test_the_tracked_law_table_loads(tmp_path: Path) -> None:
    module = laws_module()
    assert module.LAWS_PATH == ROOT / "knowledge" / "laws" / "laws.toml"
    table = module.load_laws()
    assert table.path == str(module.LAWS_PATH)


def test_the_gate_names_the_digest_of_the_table_it_was_built_with(tmp_path: Path) -> None:
    graph(tmp_path / "g", node("electrical.imu", quantities={"current_draw": (4, "mA")}))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    tracked = PhysicsGate((fixed("units"),))
    assert (
        tracked.run(view, ["subtask"], "on").catalogue_sha256
        == catalogue.catalogue_digest(laws_module().load_laws())
        == tracked.catalogue_sha256
    )
    table = table_of(tmp_path / "t", {"electrical_power": "warn"})
    built = PhysicsGate((fixed("units"),), laws=table)
    assert built.run(view, ["subtask"], "on").catalogue_sha256 == catalogue.catalogue_digest(table)
    assert built.catalogue_sha256 != tracked.catalogue_sha256


def test_a_table_that_does_not_load_stops_the_gate_from_being_built(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = laws_module()
    table, lines = write_table(tmp_path, [sound_law(expression="P == V")])
    monkeypatch.setattr(module, "LAWS_PATH", table)
    monkeypatch.setattr(module, "PROMOTIONS_PATH", lines)
    try:
        PhysicsGate((fixed("units"),))
    except module.LawTableError as exc:
        assert "dimension" in str(exc)
        return
    raise AssertionError("a gate was built on a table that does not load")
