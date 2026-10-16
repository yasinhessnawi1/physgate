"""Six small electrical and mechanical artefacts for validating the two new reviewers.

Written for this purpose alone, from the published sources named in each quantity, by the
person building the reviewers. They are not modelled on any other set of artefacts. They show
that each reviewer reads its material, judges it and can return each verdict form. They are
not a measurement: there are six, and they carry no rate.

**Two input forms.**

- **A proposed revision of the design, issued with no specification** (``REVISIONS``). This
  is the injected-error instrument's form. A given design is written first, then one
  revision over it, and the reviewer gets the worktree and the fixed account the instrument
  writes. For each domain there is a revision expected to be consistent, and its twin with
  one error added.
- **An attempt at a subtask** (``ATTEMPTS``): an issued specification and the attempt's
  commit, plus a hand-written stand-in of the implementing session's stream. The stand-in is
  in the binary's stream format, and its file says it is a stand-in. Each specification omits
  an input that one of its own acceptance criteria needs and that cannot be derived. The
  expected verdict is ``blocked``.

The expected verdict of each, and the one-line reason, are in ``EXPECTED``. A reviewer is never
shown them.

**The numbers and their sources.**

- *Pololu micro metal gearmotors* (pololu.com/category/60, read 16.10.2026): stall current at
  6 V of 0.67 A (MP) and 1.6 A (HP); 50:1 extrapolated stall torque 0.54 kg·cm (MP).
- *TI DRV8838* (SLVSBA4F): IOUT motor peak current 1.8 A (§6.3); IOCP minimum 1.9 A (§6.5);
  VM 0 to 11 V (§6.3).
- *Energizer NiMH Handbook*: an open-circuit voltage of approximately 1.4 V per cell.
- *BASF Forward AM*, Spring 2023: PLA ISO 527 tensile strength, XY 34.7 MPa and ZX 21.2 MPa.
- *Balboa 32U4 user's guide*: six AA cells.

Stall current and stall torque scale with the applied voltage (Microchip AN905, p. 6), so
each scaled value says it is derived.
"""

from __future__ import annotations

from typing import Any

#: One node's fixed fields; a revision writes a node whole.
_UPDATED = "2026-10-16T12:00:00Z"
_GEOMETRY = "sha256:" + "0" * 64

POLOLU_MOTORS = "Pololu, Micro Metal Gearmotors, pololu.com/category/60, read 16.10.2026"
DRV8838 = "TI DRV8838 datasheet SLVSBA4F"
FORWARD_AM = "BASF Forward AM, 3D Printing Materials & Solutions, Spring 2023"


def _q(value: float, unit: str, source: str, role: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source, "written_by": role}


def _node(
    node_id: str,
    domain: str,
    quantities: dict[str, tuple[float, str, str]],
    *,
    constrains: tuple[str, ...] = (),
    justified: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": domain,
        "owner_role": domain,
        "quantities": {k: _q(v, u, s, domain) for k, (v, u, s) in quantities.items()},
        "requirements": [],
        "constrains": list(constrains),
        "model": None,
        "geometry_hash": _GEOMETRY,
        "updated": _UPDATED,
    }
    if justified:
        payload["no_change_justified"] = justified
    return payload


# --- Electrical: the given design and one revision of the left drive motor --------------------

BATTERY = _node(
    "electrical.battery",
    "electrical",
    {
        "supply_voltage": (
            7.2,
            "V",
            "six AA NiMH cells (Balboa 32U4 user's guide, power section) at 1.2 V nominal each",
        ),
        "supply_voltage_max": (
            8.4,
            "V",
            "derived: 6 cells x approximately 1.4 V open-circuit per cell "
            "(Energizer NiMH Handbook)",
        ),
    },
)
DRIVER_LEFT = _node(
    "electrical.motor_driver_left",
    "electrical",
    {
        "current_limit": (1.8, "A", f"{DRV8838} §6.3: IOUT motor peak current, max 1.8 A"),
        "overcurrent_trip_min": (1.9, "A", f"{DRV8838} §6.5: IOCP overcurrent trip, min 1.9 A"),
        "rated_voltage": (11, "V", f"{DRV8838} §6.3: VM motor power supply voltage, max 11 V"),
    },
)
MOTOR_LEFT_LP = _node(
    "electrical.motor_left",
    "electrical",
    {
        "stall_current": (0.36, "A", f"{POLOLU_MOTORS}: LP 6V, 0.36 A stall at 6 V"),
        "stall_current_at_supply_max": (
            0.5,
            "A",
            "derived: 0.36 A x 8.4 V / 6 V; stall current scales with applied voltage (AN905 p. 6)",
        ),
    },
    constrains=("electrical.motor_driver_left",),
)
ELECTRICAL_BASE = (BATTERY, DRIVER_LEFT, MOTOR_LEFT_LP)


def _motor(
    item: str, version: str, stall_6v: float, stall_max: float, how_max: str
) -> dict[str, Any]:
    """The left motor node as a revision writes it: the part, its ratings with their conditions."""
    return _node(
        "electrical.motor_left",
        "electrical",
        {
            "stall_current": (
                stall_6v,
                "A",
                f"Pololu item #{item}, 50:1 Micro Metal Gearmotor {version} 6V: stall current "
                f"{stall_6v} A at 6 V, as the maker's table states it ({POLOLU_MOTORS})",
            ),
            "stall_current_at_supply_max": (stall_max, "A", how_max),
            "continuous_current_max": (
                0.25 * stall_max,
                "A",
                f"rule of thumb: Pololu's general recommendation of 25% or less of the stall "
                f"current for brushed DC motors ({POLOLU_MOTORS}), applied to the stall current "
                "at the maximum supply",
            ),
            "stall_duration_max": (
                1.0,
                "s",
                "the design's limit, handed to the firmware role: a stall is ended by cutting "
                "the drive after 1 s; Pololu warns that stalls can cause thermal damage to the "
                f"windings and brushes 'potentially on the order of seconds' ({POLOLU_MOTORS})",
            ),
        },
        constrains=("electrical.motor_driver_left",),
    )


def _driver_kept(reason: str) -> dict[str, Any]:
    """The driver, unchanged, with its owner's reason for leaving it as it is."""
    return {**DRIVER_LEFT, "no_change_justified": {"electrical.motor_left": reason}}


ELECTRICAL_CONSISTENT = (
    _motor(
        "2365",
        "MP",
        0.67,
        0.94,
        "derived: 0.67 A x 8.4 V / 6 V = 0.94 A; at stall only resistance limits the current, "
        "so it scales with the applied voltage (Microchip AN905, p. 6); series resistances of "
        "the driver, wiring and battery would only lower it",
    ),
    _driver_kept(
        "the MP motor's stall current at the 8.4 V maximum supply, 0.94 A, against this "
        "driver: 0.52 of its 1.8 A recommended peak current (§6.3) and 0.49 of its 1.9 A "
        "minimum overcurrent trip (§6.5). The datasheet's recommended operating table gives "
        "no separate continuous rating. The continuous limit is thermal: at 0.94 A the "
        "dissipation is 0.94^2 x 0.33 ohm = 0.29 W (rDS(on) maximum, 330 mOhm at TJ = 25 C, "
        "§6.5), 18 C above ambient with the 60.9 C/W RthetaJA of the JEDEC board (§6.4), and "
        "the motor's 0.235 A continuous current dissipates under 0.02 W. Nothing here changes."
    ),
)
#: The twin: the HP motor, its stall current taken at 6 V and not carried to the 8.4 V maximum.
#: Carried, it is about 2.24 A, above the 1.8 A peak rating and the 1.9 A minimum trip.
ELECTRICAL_WITH_ERROR = (
    _motor(
        "998",
        "HP",
        1.6,
        1.6,
        f"Pololu item #998, 50:1 Micro Metal Gearmotor HP 6V: 1.6 A stall ({POLOLU_MOTORS})",
    ),
    _driver_kept(
        "the HP motor's stall current, 1.6 A, against this driver: 0.89 of its 1.8 A "
        "recommended peak current (§6.3) and 0.84 of its 1.9 A minimum overcurrent trip "
        "(§6.5). The datasheet's recommended operating table gives no separate continuous "
        "rating. The continuous limit is thermal: at 1.6 A the dissipation is 1.6^2 x 0.33 ohm "
        "= 0.84 W (rDS(on) maximum, 330 mOhm at TJ = 25 C, §6.5), 51 C above ambient with the "
        "60.9 C/W RthetaJA of the JEDEC board (§6.4), and the motor's 0.4 A continuous current "
        "dissipates 0.05 W. Nothing here changes."
    ),
)


# --- Mechanical: the given design and one revision of the left motor-mount tab ----------------

KG_CM = 0.0980665  # N·m per kg·cm (standard gravity), exact by definition
#: MP 50:1 stall torque, 0.54 kg·cm at 6 V, carried to 8.4 V: 0.0741 N·m.
STALL_TORQUE_AT_SUPPLY_MAX = round(0.54 * KG_CM * 8.4 / 6, 4)

DRIVE_LEFT = _node(
    "mechanical.drive_left",
    "mechanical",
    {
        "stall_torque": (
            STALL_TORQUE_AT_SUPPLY_MAX,
            "N*m",
            "derived: 0.54 kg·cm extrapolated stall torque of the MP 6V 50:1 "
            f"({POLOLU_MOTORS}) x 9.80665 N/kg x 0.01 m/cm x 8.4 V / 6 V; stall torque scales "
            "with stall current, which scales with applied voltage (AN905 p. 6)",
        )
    },
    constrains=("mechanical.mount_tab_left",),
)
#: The tab reacts the stall torque as a couple of two tabs 10 mm apart; each is a cantilever.
TAB_SPACING_M = 0.010
TAB_LENGTH_M = 0.008
TAB_WIDTH_M = 0.006


def _tab(thickness_m: float, allowable_mpa: float, allowable_source: str) -> dict[str, Any]:
    """The tab node with its bending stress and margin, computed from the given torque."""
    force = STALL_TORQUE_AT_SUPPLY_MAX / TAB_SPACING_M
    stress_mpa = 6 * force * TAB_LENGTH_M / (TAB_WIDTH_M * thickness_m**2) / 1e6
    factor = 2.0
    margin = allowable_mpa / (factor * stress_mpa) - 1
    how = (
        f"derived: F = T / s = {STALL_TORQUE_AT_SUPPLY_MAX} N·m / 0.010 m = {force:.2f} N per "
        f"tab; sigma = 6 F L / (b h^2), L = 8 mm, b = 6 mm, h = {thickness_m * 1000:.1f} mm "
        "(cantilever, Roylance MIT 3.11 beam stresses)"
    )
    return _node(
        "mechanical.mount_tab_left",
        "mechanical",
        {
            "load_force": (round(force, 2), "N", how.split(";")[0]),
            "thickness": (thickness_m, "m", "the design's choice; FDM PLA, tab printed upright"),
            "bending_stress": (round(stress_mpa, 2), "MPa", how),
            "allowable_stress": (allowable_mpa, "MPa", allowable_source),
            "factor_of_safety": (
                factor,
                "dimensionless",
                "the design's stated factor for printed PLA: no published factor covers printed "
                "plastic, so it takes the 2.0 ultimate factor of ECSS-E-ST-32-10C Table 4-3 "
                "(analysis only), with the load case and material value stated",
            ),
            "margin_of_safety": (
                round(margin, 3),
                "dimensionless",
                "derived: MS = allowable / (FS x stress) - 1 (NASA-STD-5001B §3.2)",
            ),
        },
    )


TAB_LEFT_GIVEN = _tab(0.004, 21.2, f"{FORWARD_AM}: PLA ISO 527 tensile strength ZX, 21.2 MPa")
MECHANICAL_BASE = (DRIVE_LEFT, TAB_LEFT_GIVEN)
#: The consistent revision: a 3.0 mm tab, bending across its layers, with the ZX value.
MECHANICAL_CONSISTENT = (
    _tab(
        0.003,
        21.2,
        f"{FORWARD_AM}: PLA ISO 527 tensile strength ZX, 21.2 MPa; the upright tab bends "
        "across its layers",
    ),
)
#: The twin: a 2.0 mm tab, bending across its layers, held to the flat (XY) value.
#: With the ZX value its margin is about -0.29, not +0.17.
MECHANICAL_WITH_ERROR = (
    _tab(
        0.002,
        34.7,
        f"{FORWARD_AM}: PLA ISO 527 tensile strength XY, 34.7 MPa",
    ),
)

#: The revisions issued with no specification, by artefact id: the role, the given design and
#: the revision's nodes.
REVISIONS: dict[str, tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]] = {
    "e-consistent": ("electrical", ELECTRICAL_BASE, ELECTRICAL_CONSISTENT),
    "e-with-error": ("electrical", ELECTRICAL_BASE, ELECTRICAL_WITH_ERROR),
    "m-consistent": ("mechanical", MECHANICAL_BASE, MECHANICAL_CONSISTENT),
    "m-with-error": ("mechanical", MECHANICAL_BASE, MECHANICAL_WITH_ERROR),
}


# --- Attempts at a subtask whose issued specification lacks an input -------------------------

ELECTRICAL_SPEC = """# Left drive motor

Choose the left drive motor of the two-wheeled balancing robot from Pololu's 50:1 micro metal
gearmotors, and record it as the node `electrical.motor_left` in
`.physgate/proposals/electrical.motor_left.json`.

## Acceptance criteria

1. The node records the chosen motor's stall current at the robot's maximum supply voltage, with
   its source.
2. That stall current is within the motor driver's peak current rating and its minimum
   overcurrent trip level.
"""
MECHANICAL_SPEC = """# Left motor-mount tab

Size the printed PLA tab that holds the left drive motor, and record it as the node
`mechanical.mount_tab_left` in `.physgate/proposals/mechanical.mount_tab_left.json`.

## Acceptance criteria

1. The node records the tab's margin of safety for the fall case, with the load, the material
   value for the tab's load direction and the factor of safety, each with its source.
2. That margin of safety is at least 0.
"""

#: What each attempt writes: the issued specification lacks the input its criterion 2 (electrical:
#: which motor driver and what supply voltage) or criterion 1 (mechanical: the fall height and the
#: floor) needs, and nothing it gives derives it.
ELECTRICAL_PROPOSAL = _node(
    "electrical.motor_left",
    "electrical",
    {
        "stall_current": (0.67, "A", f"{POLOLU_MOTORS}: MP 6V, 0.67 A stall at 6 V"),
    },
)
MECHANICAL_PROPOSAL = _node(
    "mechanical.mount_tab_left",
    "mechanical",
    {
        "thickness": (0.003, "m", "the design's choice; FDM PLA, tab printed upright"),
        "allowable_stress": (
            21.2,
            "MPa",
            f"{FORWARD_AM}: PLA ISO 527 tensile strength ZX, 21.2 MPa; the upright tab bends "
            "across its layers",
        ),
    },
)
ELECTRICAL_SUMMARY = (
    "I chose the MP 6V 50:1 motor and recorded its 0.67 A stall current at 6 V from Pololu's "
    "table. The specification names neither the robot's maximum supply voltage nor the motor "
    "driver, so I could not carry the stall current to the maximum supply or compare it with a "
    "driver's limits. Both are needed and are not mine to choose."
)
MECHANICAL_SUMMARY = (
    "I chose a 3.0 mm upright PLA tab and recorded the across-layer (ZX) strength, 21.2 MPa. The "
    "specification asks for the fall case but gives no fall height and no floor, and no impact "
    "load is published for the robot, so I could not compute the fall load or the margin. That "
    "input is the specification's to give."
)

#: The attempts, by artefact id: role, specification, proposal and the session's last words.
ATTEMPTS: dict[str, tuple[str, str, dict[str, Any], str]] = {
    "e-attempt": ("electrical", ELECTRICAL_SPEC, ELECTRICAL_PROPOSAL, ELECTRICAL_SUMMARY),
    "m-attempt": ("mechanical", MECHANICAL_SPEC, MECHANICAL_PROPOSAL, MECHANICAL_SUMMARY),
}

#: What each artefact is expected to come to, and why. Never shown to a reviewer.
EXPECTED: dict[str, tuple[str, str]] = {
    "e-consistent": ("accept", "MP motor: 0.94 A at 8.4 V, below 1.8 A peak and 1.9 A trip"),
    "e-with-error": (
        "reject",
        "HP motor's stall current not carried to 8.4 V: about 2.24 A, above 1.8 A and 1.9 A",
    ),
    "m-consistent": ("accept", "3.0 mm tab with the ZX value: margin about +0.61"),
    "m-with-error": (
        "reject",
        "2.0 mm tab bending across layers held to the XY value: margin -0.29, not +0.17",
    ),
    "e-attempt": ("blocked", "no supply voltage and no driver given for criteria 1 and 2"),
    "m-attempt": ("blocked", "no fall height or floor given for criterion 1"),
}
