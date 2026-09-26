"""Graphs for the gate's tests, written through the real store so the journal is real."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from physgate.gate.context import CheckContext
from physgate.gate.registry import RegisteredCheck
from physgate.gate.result import CheckRun, Observation
from physgate.orchestrator.protocols import (
    CheckName,
    NumericOutput,
    QuantityRef,
    ThermalDetails,
    UncheckedDetails,
)
from physgate.state.store import Store

OWNER = {"electrical": "electrical", "mechanical": "mechanical", "cross": "integration"}


def node(
    node_id: str,
    *,
    kind: str = "component",
    domain: str = "electrical",
    quantities: Mapping[str, tuple[float | int, str]] | None = None,
    constrains: Sequence[str] = (),
) -> dict[str, Any]:
    """A whole node payload, the shape the frozen workload's nodes have."""
    owner = OWNER.get(domain, domain)
    return {
        "id": node_id,
        "kind": kind,
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            name: {"value": value, "unit": unit, "source": "datasheet", "written_by": owner}
            for name, (value, unit) in (quantities or {}).items()
        },
        "requirements": [],
        "constrains": list(constrains),
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-09-26T12:00:00Z",
    }


def graph(root: Path, *payloads: dict[str, Any]) -> int:
    """Write ``payloads`` through a store at ``root``, in order; return the head revision."""
    store = Store(root)
    try:
        for payload in payloads:
            result = store.write_node(payload, str(payload["owner_role"]))
            assert result.accepted, result
        return store.head_revision()
    finally:
        store.close()


def fixed(
    name: CheckName, observations: Sequence[Observation] = (), evaluated: int = 1
) -> RegisteredCheck:
    """A registered check that reports ``observations`` wherever it runs."""
    found = tuple(observations)
    return RegisteredCheck(
        name=name,
        run=lambda ctx: CheckRun(tool="test tool", evaluated=evaluated, observations=found),
    )


def recording(name: CheckName, seen: list[CheckContext]) -> RegisteredCheck:
    """A registered check that passes and remembers every context it was run with."""

    def run(ctx: CheckContext) -> CheckRun:
        seen.append(ctx)
        return CheckRun(tool="test tool", evaluated=len(ctx.view.nodes), observations=())

    return RegisteredCheck(name=name, run=run)


def thermal_failure(node_id: str = "electrical.driver", margin: int = -4) -> Observation:
    """A negative thermal margin, the shape check 6 reports, with its quantity."""
    kelvin = NumericOutput(value=margin, unit="K")
    return Observation(
        outcome="fail",
        node=node_id,
        module="electrical.drive",
        value=kelvin,
        expected="a margin of at least 0 K",
        message=f"{node_id} runs {-margin} K above its limit",
        details=ThermalDetails(margin=kelvin),
        quantities=(QuantityRef(node_id=node_id, name="max_temperature", value=85, unit="degC"),),
    )


def unchecked(*names: str) -> Observation:
    """Quantities no check could judge."""
    return Observation(
        outcome="unchecked",
        node="electrical.motor_left",
        module=None,
        value=None,
        expected=None,
        message="the catalogue does not know " + ", ".join(names),
        details=UncheckedDetails(quantities=names),
    )
