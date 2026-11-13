"""The gate the command registers fires every one of its six checks (ARCH-080).

A check that is not in the registry does not run, and nothing else would notice.
So the gate the ``physgate`` command actually registers is run on one graph that
breaks every check, each by its own wrong artefact, at every scope an attempt and
the integration call ask for, and every check must be seen failing. This is also
what refuses a gate that passes everything: the registered one must fail here.

The closed-form laws check is registered too, after propagation, and runs at module and system
scope. Its laws are data, which a person promotes into the tracked table: with no law in the
table the laws check runs on the registered gate, records that it judged nothing, and cannot
fire; with the tracked table as it stands, whatever laws it holds, the six still fire and a law
at warn never fails a design. That the laws check fires is shown on the same graph by the same
gate built with a table of test laws, one of which the graph breaks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gate_fixtures import all_six, given, graph
from law_fixtures import cleared, load, sound_law

from physgate.gate.graph import GraphView
from physgate.gate.laws import load_laws
from physgate.gate.registry import REGISTRY
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.cli import default_registrations
from physgate.orchestrator.protocols import CHECK_NUMBERS, Artefact, CheckRecord

SIX = {"units", "magnitude", "equilibrium", "power", "conservation", "thermal"}
#: Checks that have their number and their row in the architecture's table but no evaluator
#: yet, so they are not registered and never run. Each one is listed here by name, so its
#: absence from the registry is a stated fact and not an oversight. None is left.
UNREGISTERED: set[str] = set()
#: The checks whose consequence is data the tracked checkout does not hold yet: the laws check
#: runs on the registered gate and judges nothing until a law is promoted.
NO_CONTENT_YET = {"laws"}


def test_every_check_is_registered_in_the_architecture_s_order() -> None:
    assert [entry.name for entry in REGISTRY] == [
        "units",
        "magnitude",
        "equilibrium",
        "power",
        "conservation",
        "thermal",
        "propagation",
        "laws",
    ]
    assert [entry.number for entry in REGISTRY] == sorted(
        number for name, number in CHECK_NUMBERS.items() if name not in UNREGISTERED
    )
    assert set(CHECK_NUMBERS) - SIX - UNREGISTERED == {"propagation", "laws"}


def _registered_run(tmp_path: Path) -> list[CheckRecord]:
    """Every record of the registered gate's attempt and integration calls on the six's graph."""
    gate = default_registrations().gate
    assert isinstance(gate, PhysicsGate)
    root = tmp_path / "g"
    graph(root, *all_six())
    attempt = gate.run(GraphView.read(root, base_revision=0), ["subtask", "module"], "on")
    integrated = gate.check_integration(given(root), mode="on")
    return [*attempt.checks, *integrated.checks]


def test_the_registered_gate_with_the_tracked_law_table_fires_the_six_and_no_law_at_warn_fails(
    tmp_path: Path,
) -> None:
    statuses = load_laws().statuses()
    checks = _registered_run(tmp_path)
    fired = {r.name for r in checks if r.outcome in ("fail", "warn")}
    assert fired - {"laws"} == SIX
    laws = [r for r in checks if r.name == "laws"]
    assert {r.scope for r in laws} == {"module", "system"}
    at_warn = {law_id for law_id, status in statuses.items() if status == "warn"}
    assert [
        r for r in laws if r.outcome == "fail" and getattr(r.details, "law_id", None) in at_warn
    ] == []
    # A law at warn that a design breaks is a warning that never blocks.
    assert [r for r in laws if r.outcome == "warn" and r.blocking] == []


@pytest.mark.usefixtures("no_law_table")
def test_the_registered_gate_fires_all_six_checks_on_a_graph_that_breaks_them_all(
    tmp_path: Path,
) -> None:
    gate = default_registrations().gate
    assert isinstance(gate, PhysicsGate)
    root = tmp_path / "g"
    graph(root, *all_six())
    attempt = gate.run(GraphView.read(root, base_revision=0), ["subtask", "module"], "on")
    integrated = gate.check_integration(given(root), mode="on")
    fired = {
        r.name
        for result in (attempt, integrated)
        for r in result.checks
        if r.outcome in ("fail", "warn")
    }
    assert fired == SIX
    assert attempt.verdict == integrated.verdict == "fail"
    blocking_at_system = {r.name for r in integrated.checks if r.outcome == "fail" and r.blocking}
    # Power and thermal by the architecture's table; the other four because the
    # gate also runs them over the whole graph at integration.
    assert blocking_at_system == SIX
    # The laws check ran where the architecture's table says, judged nothing, and said so.
    laws = [r for result in (attempt, integrated) for r in result.checks if r.name == "laws"]
    assert {(r.scope, r.outcome) for r in laws} == {("module", "pass"), ("system", "pass")}
    assert {r.message for r in laws} == {"the laws check found nothing wrong (0 evaluated)"}


def test_the_same_gate_with_a_law_it_breaks_fires_the_laws_check_too(tmp_path: Path) -> None:
    # The motor on the power artefact draws 15 W; at 12 V and 2 A it should draw 24 W.
    table = load(
        tmp_path / "t",
        [sound_law(status="block", cleared=cleared())],
    )
    gate = PhysicsGate(laws=table)
    root = tmp_path / "g"
    payloads = list(all_six())
    for payload in payloads:
        if payload["id"] == "electrical.motor_left":
            payload["quantities"] = {
                **payload["quantities"],
                "supply_voltage": {
                    "value": 12,
                    "unit": "V",
                    "source": "datasheet",
                    "written_by": "electrical",
                },
                "current_draw": {
                    "value": 2,
                    "unit": "A",
                    "source": "datasheet",
                    "written_by": "electrical",
                },
            }
    graph(root, *payloads)
    attempt = gate.run(GraphView.read(root, base_revision=0), ["subtask", "module"], "on")
    integrated = gate.check_integration(given(root), mode="on")
    fired = {
        (r.name, r.scope)
        for result in (attempt, integrated)
        for r in result.checks
        if r.outcome == "fail" and r.blocking
    }
    assert {("laws", "module"), ("laws", "system")} <= fired
    assert {name for name, _ in fired} == SIX | NO_CONTENT_YET


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
    integrated = gate.check_integration(given(root), mode="on")
    assert attempt.verdict == "fail" and integrated.verdict == "fail"
    fired = {
        r.name
        for result in (attempt, integrated)
        for r in result.checks
        if r.outcome in ("fail", "warn")
    }
    assert fired == SIX
