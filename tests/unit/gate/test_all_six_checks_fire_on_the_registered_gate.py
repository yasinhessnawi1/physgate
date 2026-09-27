"""The gate the command registers fires every one of its six checks (ARCH-080).

A check that is not in the registry does not run, and nothing else would notice.
So the gate the ``physgate`` command actually registers is run on one graph that
breaks every check, each by its own wrong artefact, at every scope an attempt and
the integration call ask for, and every check must be seen failing. This is also
what refuses a gate that passes everything: the registered one must fail here.
"""

from __future__ import annotations

from pathlib import Path

from gate_fixtures import all_six, graph

from physgate.gate.graph import GraphView
from physgate.gate.registry import REGISTRY
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.protocols import CHECK_NUMBERS, Artefact, IntegrationArtefact

SIX = {"units", "magnitude", "equilibrium", "power", "conservation", "thermal"}


def test_every_check_but_propagation_is_registered_in_order() -> None:
    assert [entry.name for entry in REGISTRY] == [
        "units",
        "magnitude",
        "equilibrium",
        "power",
        "conservation",
        "thermal",
    ]
    assert set(CHECK_NUMBERS) - SIX == {"propagation"}


def test_the_registered_gate_fires_all_six_checks_on_a_graph_that_breaks_them_all(
    tmp_path: Path,
) -> None:
    gate = default_registrations().gate
    assert isinstance(gate, PhysicsGate)
    root = tmp_path / "g"
    graph(root, *all_six())
    attempt = gate.run(GraphView.read(root, base_revision=0), ["subtask", "module"], "on")
    integrated = gate.check_integration(
        IntegrationArtefact(run_id="run-1", graph_root=str(root), run_head="b" * 40), mode="on"
    )
    fired = {
        r.name
        for result in (attempt, integrated)
        for r in result.checks
        if r.outcome in ("fail", "warn")
    }
    assert fired == SIX
    assert attempt.verdict == integrated.verdict == "fail"
    blocking_at_system = {r.name for r in integrated.checks if r.outcome == "fail" and r.blocking}
    # Power and thermal by the architecture's table; equilibrium and conservation
    # because the gate also runs them over the whole graph at integration.
    assert blocking_at_system == {"power", "thermal", "equilibrium", "conservation"}


def test_the_registered_gate_refuses_through_the_calls_the_loop_makes(tmp_path: Path) -> None:
    # The loop calls check(artefact) at an attempt's scopes and check_integration at
    # the end. A gate whose check() passed everything would pass every test that
    # drives run() directly, so this drives the two calls the loop makes.
    gate = default_registrations().gate
    assert gate is not None
    root = tmp_path / "g"
    graph(root, *all_six())
    attempt = gate.check(
        Artefact(
            subtask_id="s1",
            attempt=1,
            assigned_role="electrical",
            attempt_commit="a" * 40,
            worktree="/w",
            graph_root=str(root),
            trajectory="/t",
            scopes=("subtask", "module"),
            base_revision=0,
        ),
        mode="on",
    )
    integrated = gate.check_integration(
        IntegrationArtefact(run_id="run-1", graph_root=str(root), run_head="b" * 40), mode="on"
    )
    assert attempt.verdict == "fail" and integrated.verdict == "fail"
    fired = {
        r.name
        for result in (attempt, integrated)
        for r in result.checks
        if r.outcome in ("fail", "warn")
    }
    assert fired == SIX
