"""The physics gate's stand-in drive-power plan: the brief, the interface node, the proposals.

One source for every test that runs it: the physics gate's three-mode test drives it through
the command with the real binary on the scripted endpoint, and the operator UI's browser tests
rebuild it with stand-in sessions. **It is a stand-in, not the reference design's brief.** Its
proposals carry two deliberate errors: 15 W drawn from a 10 W module (blocking at module and
system scope), and a driver at 145 degC against its 125 degC limit (a warning at module scope,
blocking at system scope).
"""

from __future__ import annotations

from typing import Any

from gate_fixtures import node

#: The interface node the plan's decomposition writes.
POWER_BUS: dict[str, Any] = {
    "id": "iface.power_bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}

STAND_IN_BRIEF = (
    "STAND-IN BRIEF, written for the physics gate's three-mode test; not the reference "
    "design's brief.\n\n"
    "Size the drive power module of a two-wheeled self-balancing robot: two brushed DC "
    "gearmotors on one motor driver, fed from the module's power supply, which is fed "
    "from a battery.\n"
)

DRIVE_MODULE: tuple[dict[str, Any], ...] = (
    # A declared source: a battery declares the energy it stores.
    node(
        "electrical.battery",
        quantities={"power_supply": (20, "W"), "energy_capacity": (20, "W*h")},
    ),
    # The module draws what it supplies from the battery.
    node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (10, "W"), "power_draw": (10, "W"), "mass": (0.4, "kg")},
        constrains=["electrical.battery"],
    ),
    *(
        node(
            f"electrical.motor_{side}",
            quantities={"power_draw": (7.5, "W"), "stall_current": (2.4, "A"), "mass": (0.2, "kg")},
            constrains=["electrical.drive", "electrical.driver"],
        )
        for side in ("left", "right")
    ),
    node(
        "electrical.driver",
        quantities={
            "current_limit": (3, "A"),
            "thermal_resistance": (40, "K/W"),
            "heat_dissipation": (3, "W"),
            "ambient_temperature": (25, "degC"),
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.drive"],
    ),
)
