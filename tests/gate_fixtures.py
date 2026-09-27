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


# One wrong artefact per check, each otherwise sound: the unit, the range, the
# mount, the module's budget, the module's mass, the component's temperature.
# The comment on each says what is wrong and where the architecture refuses it.

#: Check 1, at subtask scope: a stall current compared with a limit in volts.
UNITS = (
    node("electrical.driver", quantities={"current_limit": (2.4, "V")}),
    node(
        "electrical.motor_left",
        quantities={"stall_current": (2.4, "A")},
        constrains=["electrical.driver"],
    ),
)
#: Check 2, at subtask scope: an IMU sampled at 50 kHz, above the register's 8 kHz.
MAGNITUDE = (node("electrical.imu", quantities={"sample_rate": (50_000, "Hz")}),)
#: Check 3, at module scope: a 1 kg wheel at 0.1 m on a bearing declaring no moment.
EQUILIBRIUM = (
    node("mechanical.wheel_mount", domain="mechanical", kind="module"),
    node(
        "mechanical.bearing",
        domain="mechanical",
        quantities={
            "support_position": (0, "m"),
            "reaction_force": (9.80665, "N"),
            "reaction_moment": (0, "N*m"),
        },
        constrains=["mechanical.wheel_mount"],
    ),
    node(
        "mechanical.wheel",
        domain="mechanical",
        quantities={"mount_position": (0.1, "m"), "mass": (1, "kg")},
        constrains=["mechanical.wheel_mount"],
    ),
)
#: Check 4, at module scope: 15 W drawn from a module that supplies 10 W.
POWER = (
    node("electrical.drive", kind="module", quantities={"power_supply": (10, "W")}),
    node(
        "electrical.motor_left",
        quantities={"power_draw": (15, "W")},
        constrains=["electrical.drive"],
    ),
)
#: Check 4, at system scope only: two modules that each balance, over a 20 W battery.
JOINT_POWER = (
    node(
        "electrical.battery",
        quantities={
            "power_supply": (20, "W"),
            "energy_capacity": (20, "W*h"),
            "max_discharge_power": (20, "W"),
        },
    ),
    node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (15, "W"), "power_draw": (15, "W")},
        constrains=["electrical.battery"],
    ),
    node(
        "electrical.control",
        kind="module",
        quantities={"power_supply": (10, "W"), "power_draw": (10, "W")},
        constrains=["electrical.battery"],
    ),
)
#: Check 5, at module scope: a module declared at 1 kg whose one member weighs 0.2 kg.
CONSERVATION = (
    node("electrical.drive", kind="module", quantities={"mass": (1, "kg")}),
    node(
        "electrical.motor_left",
        quantities={"mass": (0.2, "kg")},
        constrains=["electrical.drive"],
    ),
)
#: Check 6, a warning at module scope and a block at system scope: 145 degC against 125.
THERMAL = (
    node("electrical.drive", kind="module"),
    node(
        "electrical.driver",
        quantities={
            "thermal_resistance": (40, "K/W"),
            "heat_dissipation": (3, "W"),
            "ambient_temperature": (25, "degC"),
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.drive"],
    ),
)


def all_six() -> tuple[dict[str, Any], ...]:
    """One graph that breaks every check, each by its own wrong artefact."""
    merged: dict[str, dict[str, Any]] = {}
    for group in (UNITS, MAGNITUDE, EQUILIBRIUM, POWER, CONSERVATION, THERMAL):
        for payload in group:
            if payload["id"] in merged:
                into = merged[payload["id"]]
                into["quantities"] = {**into["quantities"], **payload["quantities"]}
                into["constrains"] = sorted({*into["constrains"], *payload["constrains"]})
            else:
                merged[payload["id"]] = {**payload, "quantities": dict(payload["quantities"])}
    return tuple(merged.values())


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
