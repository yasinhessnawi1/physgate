"""Injected errors: one wrong artefact per check, refused at the right stage and no earlier.

Each artefact is otherwise sound and breaks one check. It goes through the gate
the ``physgate`` command registers, at each of the three points the architecture
checks at, narrowest first: an attempt's own nodes (subtask), its complete module
(module), and the integrated design (system). It must pass every point before
the one where its check runs, and be refused there by that check (ARCH-080). A
thermal margin is a warning at module scope and is refused only at integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import (
    CONSERVATION,
    EQUILIBRIUM,
    JOINT_POWER,
    MAGNITUDE,
    POWER,
    THERMAL,
    UNITS,
    graph,
)

from physgate.gate.graph import GraphView
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.protocols import GateResult, IntegrationArtefact, Scope

pytestmark = pytest.mark.injected

CASES: list[tuple[str, tuple[dict[str, Any], ...], Scope]] = [
    ("units", UNITS, "subtask"),
    ("magnitude", MAGNITUDE, "subtask"),
    ("equilibrium", EQUILIBRIUM, "module"),
    ("power", POWER, "module"),
    ("power", JOINT_POWER, "system"),
    ("conservation", CONSERVATION, "module"),
    ("thermal", THERMAL, "system"),
]
IDS = [
    "units at subtask",
    "magnitude at subtask",
    "equilibrium at module",
    "a module's power at module",
    "the joint power budget at integration",
    "conservation at module",
    "thermal at integration",
]
ORDER: tuple[Scope, ...] = ("subtask", "module", "system")


def at(root: Path, scope: Scope) -> GateResult:
    gate = default_registrations().gate
    assert gate is not None
    if scope == "system":
        artefact = IntegrationArtefact(run_id="run-1", graph_root=str(root), run_head="b" * 40)
        return gate.check_integration(artefact, mode="on")
    scopes: list[Scope] = ["subtask"] if scope == "subtask" else ["subtask", "module"]
    return gate.run(GraphView.read(root, base_revision=0), scopes, "on")  # type: ignore[attr-defined, no-any-return]


@pytest.mark.parametrize(("check", "payloads", "where"), CASES, ids=IDS)
def test_a_wrong_artefact_is_refused_by_its_check_where_the_architecture_runs_it(
    tmp_path: Path, check: str, payloads: tuple[dict[str, Any], ...], where: Scope
) -> None:
    root = tmp_path / "g"
    graph(root, *payloads)
    for scope in ORDER[: ORDER.index(where)]:
        earlier = at(root, scope)
        assert earlier.verdict == "pass", (scope, earlier.finding)
    refused = at(root, where)
    assert refused.verdict == "fail" and refused.failing_check == check, refused.finding
    assert [r.gate_mode for r in refused.checks] == ["on"] * len(refused.checks)


def test_a_thermal_margin_is_a_warning_at_module_scope_before_it_is_refused(
    tmp_path: Path,
) -> None:
    root = tmp_path / "g"
    graph(root, *THERMAL)
    module = at(root, "module")
    assert module.verdict == "pass"
    assert [(r.name, r.outcome) for r in module.checks if r.outcome == "warn"] == [
        ("thermal", "warn")
    ]
