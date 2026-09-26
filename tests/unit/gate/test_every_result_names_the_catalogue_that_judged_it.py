"""Every gate result names the catalogue that judged it, by the digest of its content."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest
from gate_fixtures import graph, node

from physgate.gate import catalogue
from physgate.gate.catalogue import QUANTITIES, Entry, catalogue_digest
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate


@pytest.fixture
def view(tmp_path: Path) -> GraphView:
    graph(tmp_path / "g", node("electrical.motor_left", quantities={"stall_current": (2.4, "A")}))
    return GraphView.read(tmp_path / "g", base_revision=0)


def test_the_result_carries_the_digest_of_the_catalogue_in_use(view: GraphView) -> None:
    result = PhysicsGate().run(view, ["subtask"], "on")
    assert result.catalogue_sha256 == catalogue_digest()
    assert len(result.catalogue_sha256) == 64


def test_changing_one_catalogue_entry_changes_the_digest_on_the_result(
    view: GraphView, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = PhysicsGate().run(view, ["subtask"], "on").catalogue_sha256
    changed = dict(QUANTITIES)
    changed["loop_gain"] = Entry(name="loop_gain", kind="dimensionless", source="another source")
    monkeypatch.setattr(catalogue, "QUANTITIES", MappingProxyType(changed))
    after = PhysicsGate().run(view, ["subtask"], "on").catalogue_sha256
    assert after != before


def test_the_digest_is_of_content_and_stable() -> None:
    assert catalogue_digest() == catalogue_digest()
