"""Checks 1 to 7 write the same records, byte for byte, whatever law table the gate holds.

The laws are an eighth check with records of their own. They read the graph, never write it,
and change nothing the other checks see or say. So the same graph, judged by a gate built with
a table of laws and by one built with the tracked table, which holds none, gives records for
checks 1 to 7 that are identical in every byte, at every scope; only the catalogue digest, which
names the table, and the laws check's own records differ.

The graphs are every graph the gate's record of its earlier verdicts holds (every graph the unit
and injected-error suites build, and the designs kept in the fixtures), with the test laws
binding wherever their names occur, and the graph that breaks every check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import all_six, node
from law_cases import every_case, table
from law_fixtures import laws_module

from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import GateResult
from physgate.state.store import Store

RECORD = Path(__file__).parent / "gate_before" / "record.json"
SCOPES = ("subtask", "module", "system")


#: A graph that breaks every test law, each on its own node.
BROKEN = [
    node(
        "electrical.imu",
        quantities={
            "power_draw": (19.5, "mW"),
            "supply_voltage": (3.3, "V"),
            "current_draw": (3.9, "mA"),
            "current_limit": (2, "mA"),
            "output_data_rate": (200, "Hz"),
        },
    ),
    node(
        "firmware.estimator",
        domain="firmware",
        quantities={"update_rate": (400, "Hz")},
        constrains=["electrical.imu"],
    ),
    node(
        "electrical.motor",
        quantities={
            "stall_current": (3, "A"),
            "rated_voltage": (12, "V"),
            "motor_resistance": (6, "ohm"),
            "heat_dissipation": (5, "W"),
            "current_draw": (1, "A"),
            "rated_output_power": (8, "W"),
            "output_power": (10, "W"),
        },
    ),
]


def graphs() -> list[tuple[str, list[dict[str, Any]]]]:
    """Every graph the record holds, the graph breaking every check, and one breaking every law."""
    cases = json.loads(RECORD.read_bytes())["cases"]
    held = [(str(c["id"]), list(c["nodes"])) for c in cases if c.get("nodes")]
    return [*held, ("all-six", list(all_six())), ("broken-laws", BROKEN)]


def write(root: Path, payloads: list[dict[str, Any]]) -> GraphView:
    store = Store(root)
    try:
        for payload in payloads:
            assert store.write_node(dict(payload), str(payload["owner_role"])).accepted
    finally:
        store.close()
    return GraphView.read(root, base_revision=0)


def others(result: GateResult) -> list[str]:
    """Checks 1 to 7's records as the lines a gate event writes, in order."""
    return [r.model_dump_json() for r in result.checks if r.name != "laws"]


@pytest.fixture(scope="module")
def judged(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, GateResult, GateResult]]:
    """(the graph's id, the gate with laws, the gate without), over every graph."""
    root = tmp_path_factory.mktemp("graphs")
    with_laws = PhysicsGate(laws=table(root / "table", every_case()))
    without = PhysicsGate(laws=laws_module().load_laws())
    found = []
    for k, (cid, payloads) in enumerate(graphs()):
        view = write(root / str(k), payloads)
        found.append((cid, with_laws.run(view, SCOPES, "on"), without.run(view, SCOPES, "on")))
    return found


def test_checks_1_to_7_are_byte_identical_with_and_without_the_law_table(
    judged: list[tuple[str, GateResult, GateResult]],
) -> None:
    assert len(judged) > 700
    differing = [cid for cid, laws, none in judged if others(laws) != others(none)]
    assert differing == []


def test_laws_on_probation_change_no_verdict_and_the_digest_names_the_table(
    judged: list[tuple[str, GateResult, GateResult]],
) -> None:
    for _, laws, none in judged:
        assert laws.catalogue_sha256 != none.catalogue_sha256
        assert (laws.verdict, laws.failing_check, laws.quantities) == (
            none.verdict,
            none.failing_check,
            none.quantities,
        )


def test_the_laws_judged_something_on_these_graphs_so_the_comparison_means_something(
    judged: list[tuple[str, GateResult, GateResult]],
) -> None:
    outcomes = {r.outcome for _, laws, _ in judged for r in laws.checks if r.name == "laws"}
    assert {"pass", "warn", "unchecked"} <= outcomes
    judged_count = sum(
        getattr(r.details, "evaluated", 0)
        for _, laws, _ in judged
        for r in laws.checks
        if r.name == "laws" and r.outcome in ("pass", "warn")
    )
    assert judged_count > 0
