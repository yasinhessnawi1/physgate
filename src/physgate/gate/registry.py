"""The checks the gate runs, in order, and where each one runs and what its failure does.

**A check that is not in** :data:`REGISTRY` **does not run.** Nothing else in the
gate discovers checks, so a check module left out of this list is code that can
never fire, and the test that runs the real gate on an artefact violating every
check is what notices.

Where each check runs and what its failure does is the architecture's own
table (ARCH-080), written once here as :data:`ARCH_080`, with the scopes the
gate adds beyond it in :data:`TIGHTENED`; the runner reads the two together as
:data:`CADENCE`. A
check cannot soften its own consequence: it reports what it saw, and this table
decides whether that blocks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from physgate.gate import (
    check_conservation,
    check_equilibrium,
    check_magnitude,
    check_power,
    check_thermal,
    check_units,
)
from physgate.gate.context import CheckContext
from physgate.gate.result import CheckRun
from physgate.orchestrator.protocols import CHECK_NUMBERS, CheckName, Scope

OnFailure = Literal["block", "warn"]

#: ARCH-080's "runs at" and "on failure" columns: units and magnitude per subtask;
#: equilibrium, power, conservation and thermal per module; power, thermal and
#: propagation per run (the system). Thermal warns at module and blocks at
#: integration. Propagation is the catch-accounting spec's check and is listed so
#: the table is the architecture's whole table.
ARCH_080: Mapping[CheckName, Mapping[Scope, OnFailure]] = MappingProxyType(
    {
        "units": MappingProxyType({"subtask": "block"}),
        "magnitude": MappingProxyType({"subtask": "block"}),
        "equilibrium": MappingProxyType({"module": "block"}),
        "power": MappingProxyType({"module": "block", "system": "block"}),
        "conservation": MappingProxyType({"module": "block"}),
        "thermal": MappingProxyType({"module": "warn", "system": "block"}),
        "propagation": MappingProxyType({"system": "block"}),
    }
)

#: Where the gate runs a check beyond ARCH-080's table. Each entry only adds a
#: scope at which a failure blocks; none changes or removes a scope the table
#: gives. Equilibrium and conservation run over the whole graph at integration
#: because module scope is reached only through the nodes an attempt wrote: a
#: mount or a balance broken by writes from several attempts, or by an edge no
#: attempt's nodes still name, is caught there if nowhere earlier.
TIGHTENED: Mapping[CheckName, Mapping[Scope, OnFailure]] = MappingProxyType(
    {
        "equilibrium": MappingProxyType({"system": "block"}),
        "conservation": MappingProxyType({"system": "block"}),
    }
)

#: Where each check runs and what its failure does: the table, with the tightenings.
CADENCE: Mapping[CheckName, Mapping[Scope, OnFailure]] = MappingProxyType(
    {
        name: MappingProxyType({**scopes, **TIGHTENED.get(name, {})})
        for name, scopes in ARCH_080.items()
    }
)


@dataclass(frozen=True)
class RegisteredCheck:
    """One check the gate runs: its name and the function that runs it at one scope."""

    name: CheckName
    run: Callable[[CheckContext], CheckRun]

    @property
    def number(self) -> int:
        """The check's number in the architecture's table."""
        return CHECK_NUMBERS[self.name]


#: Every check the gate runs, in the architecture's order.
REGISTRY: tuple[RegisteredCheck, ...] = (
    RegisteredCheck(name="units", run=check_units.run),
    RegisteredCheck(name="magnitude", run=check_magnitude.run),
    RegisteredCheck(name="equilibrium", run=check_equilibrium.run),
    RegisteredCheck(name="power", run=check_power.run),
    RegisteredCheck(name="conservation", run=check_conservation.run),
    RegisteredCheck(name="thermal", run=check_thermal.run),
)
