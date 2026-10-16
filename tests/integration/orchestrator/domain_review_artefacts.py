"""Six small electrical and mechanical artefacts for validating the two new reviewers.

Written for this purpose alone, from the published sources named in each quantity, by the
person building the reviewers. They are not modelled on any other set of artefacts, and an
independent check read every number against its source. They show that each reviewer reads its
material and judges it, and which verdict each form draws. They are not a measurement: there are
six, and they carry no rate.

**Two input forms.**

- **A proposed revision of the design, issued with no specification** (``REVISIONS``). This
  is the injected-error instrument's form: a given design is written first, then one revision
  over it, and the reviewer gets the worktree and the fixed account the instrument writes.
  For each domain there is a revision written to be consistent, and a twin that adds one
  decisive error. The twin also differs where the error needs it (the part, the thickness).
- **An attempt at a subtask** (``ATTEMPTS``): an issued specification and the attempt's commit,
  plus a stand-in of the implementing session's stream. The stand-in is written by hand in the
  binary's stream format, and the reviewer is not told it is one. Each specification leaves out
  an input that its acceptance criteria need and that cannot be derived. The attempt records
  everything else it can.

**What each is expected to draw** is in ``EXPECTED``: the verdict, and for a twin the rubric
items that must carry its rejection, because a rejection alone does not show the error was
found. A reviewer is never shown any of it. The check found that the rubrics, read as written,
leave ``accept`` out of reach for the two consistent revisions: each touches items whose inputs
no public source gives (a board-level junction-to-ambient figure, a printed part's allowable
with its specimen settings). Their expectation says so rather than claim an accept.

**The numbers and their sources.**

- *Pololu*, 50:1 Micro Metal Gearmotor MP 6V (#2365) and HP 6V (#998) product pages, and the
  Micro Metal Gearmotor datasheet rev 6.2: stall current at 6 V 0.67 A and 1.6 A, extrapolated
  (theoretical); 50:1 MP extrapolated stall torque 0.54 kg·cm.
- *TI DRV8838* (SLVSBA4F): IOUT motor peak current 1.8 A (§6.3); IOCP minimum 1.9 A at
  TA = 25 °C (§6.5); VM 0 to 11 V (§6.3); rDS(on) 330 mΩ maximum at TJ = 25 °C (§6.5);
  RθJA 60.9 °C/W, JEDEC board (§6.4); TSD minimum 150 °C (§6.5).
- *Balboa 32U4 user's guide* (§3.6): six AA cells; the board's VIN limited to 10.8 V by the
  DRV8838.
- *Energizer NiMH Handbook*: an open-circuit voltage of approximately 1.4 V per cell.
- *BASF Forward AM*, Spring 2023, Mechanical Properties Comparison: Ultrafuse PLA, ISO 527
  tensile strength XY 34.7 MPa and ZX 21.2 MPa, typical values.

Stall current and stall torque scale with the applied voltage, a derivation from AN905's p. 2
(current linear with torque) and p. 6 (back-EMF proportional to speed); each scaled value says
it is derived.

**One difference from the instrument's corpus format.** That format writes every source as a
URL or as arithmetic over rows of a parts sheet the reviewer is not shown. These artefacts cite
their sources in words, so a reviewer can check them by reading.
"""

from __future__ import annotations

from typing import Any

_GEOMETRY = "sha256:" + "6b1f0c2e94d7a3581e0f4c7d2a9b6e3f8c1d5a7e9b2f4c6d8e0a1b3c5d7e9f1a"

POLOLU_MP = (
    "Pololu item #2365, 50:1 Micro Metal Gearmotor MP 6V, product page and Micro Metal "
    "Gearmotor datasheet rev 6.2, read 16.10.2026"
)
POLOLU_HP = (
    "Pololu item #998, 50:1 Micro Metal Gearmotor HP 6V, product page and Micro Metal "
    "Gearmotor datasheet rev 6.2, read 16.10.2026"
)
DRV8838 = "TI DRV8838 datasheet SLVSBA4F"
BALBOA = "Pololu Balboa 32U4 Balancing Robot User's Guide"
FORWARD_AM = (
    "BASF Forward AM, 3D Printing Materials & Solutions, Spring 2023, Mechanical Properties "
    "Comparison table"
)
SCALING = (
    "stall current scales with the applied voltage: derived from Microchip AN905 p. 2 (current "
    "linear with torque) and p. 6 (back-EMF proportional to speed)"
)


def _q(value: float, unit: str, source: str, role: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source, "written_by": role}


def _node(
    node_id: str,
    domain: str,
    quantities: dict[str, tuple[float, str, str]],
    *,
    updated: str,
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
        "updated": updated,
    }
    if justified:
        payload["no_change_justified"] = justified
    return payload


# --- Electrical: the given design and one revision of the left drive motor --------------------

BATTERY = _node(
    "electrical.battery",
    "electrical",
    {
        "supply_voltage": (7.2, "V", f"{BALBOA} §3.6: six AA cells; 1.2 V nominal per NiMH cell"),
        "supply_voltage_max": (
            8.4,
            "V",
            "derived: 6 cells x approximately 1.4 V open-circuit per fully charged NiMH cell "
            "(Energizer NiMH Handbook)",
        ),
    },
    updated="2026-10-02T09:14:00Z",
)
_DRIVER_RATINGS: dict[str, tuple[float, str, str]] = {
    "current_limit": (
        1.8,
        "A",
        f"{DRV8838} §6.3 Recommended Operating Conditions: IOUT motor peak current, max 1.8 A",
    ),
    "overcurrent_trip_min": (
        1.9,
        "A",
        f"{DRV8838} §6.5 Electrical Characteristics, TA = 25 C: IOCP overcurrent trip, min 1.9 A",
    ),
    "rated_voltage": (
        10.8,
        "V",
        f"the stricter of two: {BALBOA} §3.6, the board's VIN is limited to 10.8 V by the "
        f"DRV8838; the chip's own VM maximum is 11 V ({DRV8838} §6.3)",
    ),
}
DRIVER_LEFT = _node(
    "electrical.motor_driver_left",
    "electrical",
    _DRIVER_RATINGS,
    updated="2026-10-02T09:20:00Z",
)
MOTOR_LEFT_LP = _node(
    "electrical.motor_left",
    "electrical",
    {
        "stall_current": (
            0.36,
            "A",
            "Pololu 50:1 Micro Metal Gearmotor LP 6V: 0.36 A at 6 V, extrapolated (theoretical)",
        ),
        "stall_current_at_supply_max": (
            0.5,
            "A",
            f"derived: 0.36 A x 8.4 V / 6 V; {SCALING}",
        ),
    },
    updated="2026-10-02T09:31:00Z",
    constrains=("electrical.motor_driver_left",),
)
ELECTRICAL_BASE = (BATTERY, DRIVER_LEFT, MOTOR_LEFT_LP)


def _motor(source: str, stall_6v: float, stall_max: float, how_max: str) -> dict[str, Any]:
    """The left motor node as a revision writes it: the part, its ratings with their conditions."""
    return _node(
        "electrical.motor_left",
        "electrical",
        {
            "stall_current": (
                stall_6v,
                "A",
                f"{source}: stall current {stall_6v} A at 6 V, extrapolated (theoretical)",
            ),
            "stall_current_at_supply_max": (stall_max, "A", how_max),
            "continuous_current_max": (
                0.25 * stall_max,
                "A",
                "rule of thumb: Pololu's general recommendation of 25% or less of the stall "
                f"current for brushed DC motors ({source}), applied to the stall current at the "
                "maximum supply",
            ),
            "stall_duration_max": (
                1.0,
                "s",
                "the design's limit, handed to the firmware role: a stall is ended by cutting "
                "the drive after 1 s; Pololu warns that stalls can cause thermal damage to the "
                f"windings and brushes 'potentially on the order of seconds' ({source})",
            ),
            "supply_voltage_max_applied": (
                8.4,
                "V",
                "the given battery's maximum; the 6 V motor runs above its rated voltage, which "
                f"Pololu notes could start affecting the motor's life ({source})",
            ),
        },
        updated="2026-10-14T15:02:00Z",
        constrains=("electrical.motor_driver_left",),
    )


def _driver_kept(reason: str) -> dict[str, Any]:
    """The driver, its ratings unchanged, with its owner's reason for leaving it as it is."""
    return _node(
        "electrical.motor_driver_left",
        "electrical",
        _DRIVER_RATINGS,
        updated="2026-10-14T15:05:00Z",
        justified={"electrical.motor_left": reason},
    )


ELECTRICAL_CONSISTENT = (
    _motor(
        POLOLU_MP,
        0.67,
        0.94,
        f"derived: 0.67 A x 8.4 V / 6 V = 0.94 A; {SCALING}; series resistances of the driver, "
        "wiring and battery would only lower it",
    ),
    _driver_kept(
        "the MP motor at the 8.4 V maximum supply against this driver. Current: its 0.94 A "
        "stall current is 0.52 of the 1.8 A recommended peak current and 0.49 of the 1.9 A "
        "minimum overcurrent trip (TA = 25 C). Voltage: 8.4 V is 0.78 of the board's 10.8 V. "
        "Basis: the maker's recommended operating conditions. The datasheet's recommended "
        "operating table gives no separate continuous rating. Nothing here changes."
    ),
)
#: The twin. The HP motor, its stall current taken at 6 V and not carried to the 8.4 V maximum.
#: Carried, it is about 2.24 A, above the 1.8 A peak rating and the 1.9 A minimum trip. The
#: part changes too, since an MP motor's stall current would pass even uncarried.
ELECTRICAL_WITH_ERROR = (
    _motor(POLOLU_HP, 1.6, 1.6, f"{POLOLU_HP}: stall current 1.6 A"),
    _driver_kept(
        "the HP motor at the 8.4 V maximum supply against this driver. Current: its 1.6 A "
        "stall current is 0.89 of the 1.8 A recommended peak current and 0.84 of the 1.9 A "
        "minimum overcurrent trip (TA = 25 C). Voltage: 8.4 V is 0.78 of the board's 10.8 V. "
        "Basis: the maker's recommended operating conditions. The datasheet's recommended "
        "operating table gives no separate continuous rating. Nothing here changes."
    ),
)


# --- Mechanical: the given design and one revision of the left motor-mount tab ----------------

KG_CM = 0.0980665  # N·m per kg·cm (standard gravity)
#: MP 50:1 stall torque, 0.54 kg·cm at 6 V, carried to 8.4 V: 0.0741 N·m.
STALL_TORQUE_AT_SUPPLY_MAX = round(0.54 * KG_CM * 8.4 / 6, 4)

DRIVE_LEFT = _node(
    "mechanical.drive_left",
    "mechanical",
    {
        "stall_torque": (
            STALL_TORQUE_AT_SUPPLY_MAX,
            "N*m",
            f"derived: 0.54 kg·cm extrapolated stall torque ({POLOLU_MP}) x 9.80665 N/kg x "
            "0.01 m/cm x 8.4 V / 6 V; stall torque scales with stall current, and "
            f"{SCALING}",
        )
    },
    updated="2026-10-03T11:40:00Z",
    constrains=("mechanical.mount_tab_left",),
)
#: The tab reacts the stall torque as a couple of two tabs 10 mm apart; each is a cantilever.
TAB_SPACING_M = 0.010
TAB_LENGTH_M = 0.008
TAB_WIDTH_M = 0.006
_PLA = "BASF Ultrafuse PLA, FDM"
_BUILD = (
    f"{_PLA}; the tab is printed with its 8 mm length along the build (Z) axis, so the root "
    "bending stress crosses the layers"
)


def _tab(
    thickness_m: float, allowable_mpa: float, allowable_source: str, updated: str
) -> dict[str, Any]:
    """The tab node with its geometry, bending stress and margin, from the given torque."""
    force = STALL_TORQUE_AT_SUPPLY_MAX / TAB_SPACING_M
    stress_mpa = 6 * force * TAB_LENGTH_M / (TAB_WIDTH_M * thickness_m**2) / 1e6
    factor = 2.0
    margin = allowable_mpa / (factor * stress_mpa) - 1
    beam = (
        "Euler-Bernoulli cantilever, sigma = 6 F L / (b h^2) (Roylance, MIT 3.11, Stresses in "
        "Beams); a short tab, so shear and the root fillet's stress concentration are not "
        "included"
    )
    return _node(
        "mechanical.mount_tab_left",
        "mechanical",
        {
            "spacing": (TAB_SPACING_M, "m", "the design's choice: the two tabs' centre distance"),
            "length": (TAB_LENGTH_M, "m", f"the design's choice; {_BUILD}"),
            "width": (TAB_WIDTH_M, "m", "the design's choice"),
            "thickness": (thickness_m, "m", "the design's choice"),
            "load_force": (
                round(force, 2),
                "N",
                f"derived: stall-torque reaction as a couple, F = T / s = "
                f"{STALL_TORQUE_AT_SUPPLY_MAX} N·m / {TAB_SPACING_M} m per tab",
            ),
            "bending_stress": (
                round(stress_mpa, 2),
                "MPa",
                f"derived: 6 x {force:.2f} N x {TAB_LENGTH_M} m / ({TAB_WIDTH_M} m x "
                f"({thickness_m} m)^2); {beam}",
            ),
            "allowable_stress": (allowable_mpa, "MPa", allowable_source),
            "factor_of_safety": (
                factor,
                "dimensionless",
                "the design's stated factor on ultimate: no published factor covers printed "
                "plastic, so it takes 2.0, ECSS-E-ST-32-10C Rev.2 Corr.1 Table 4-3's ultimate "
                "factor for metallic, FRP and other structural parts of spaceflight hardware "
                "verified by analysis only, as a reference from a stricter class, not as physics. "
                "Ultimate only: the across-layer PLA breaks at 1.2% elongation (Forward AM), with "
                "no separate yield to check.",
            ),
            "margin_of_safety": (
                round(margin, 3),
                "dimensionless",
                "derived: MS = allowable / (FS x stress) - 1 (NASA-STD-5001B §3.2)",
            ),
        },
        updated=updated,
    )


TAB_LEFT_GIVEN = _tab(
    0.004,
    21.2,
    f"{FORWARD_AM}: Ultrafuse PLA ISO 527 tensile strength ZX, 21.2 MPa, typical value, "
    "unverified until tested",
    "2026-10-03T11:52:00Z",
)
MECHANICAL_BASE = (DRIVE_LEFT, TAB_LEFT_GIVEN)
#: The consistent revision: a 3.0 mm tab, bending across its layers, held to the ZX value.
MECHANICAL_CONSISTENT = (
    _tab(
        0.003,
        21.2,
        f"{FORWARD_AM}: Ultrafuse PLA ISO 527 tensile strength ZX, 21.2 MPa, typical value, "
        "unverified until tested; the root stress crosses the layers",
        "2026-10-15T08:21:00Z",
    ),
)
#: The twin: a 2.0 mm tab, bending across its layers, held to the flat (XY) value. With the ZX
#: value its margin is about -0.29, not +0.17. The thickness changes too, since a 3.0 mm tab
#: would pass even with the XY value.
MECHANICAL_WITH_ERROR = (
    _tab(
        0.002,
        34.7,
        f"{FORWARD_AM}: Ultrafuse PLA ISO 527 tensile strength XY, 34.7 MPa, typical value, "
        "unverified until tested",
        "2026-10-15T08:21:00Z",
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

Choose the left drive motor of a two-wheeled balancing robot from Pololu's 50:1 micro metal
gearmotors, and record it as the node `electrical.motor_left` in
`.physgate/proposals/electrical.motor_left.json`. The robot's battery and its motor driver are
not yet chosen.

## Acceptance criteria

1. The node records the chosen motor's stall current at the robot's maximum supply voltage, with
   its source.
2. That stall current is within the motor driver's peak current rating and its minimum
   overcurrent trip level.
"""
MECHANICAL_SPEC = """# Left motor-mount tab

Size the printed PLA tab that holds the left drive motor of a two-wheeled balancing robot, and
record it as the node `mechanical.mount_tab_left` in
`.physgate/proposals/mechanical.mount_tab_left.json`. The drive motor is not yet chosen.

## Acceptance criteria

1. The node records the tab's margin of safety for the fall case, with the load, the material
   value for the tab's load direction and the factor of safety, each with its source.
2. That margin of safety is at least 0.
"""

#: Each attempt records everything it can without the input its specification leaves out:
#: electrical, the robot's maximum supply voltage and the driver (criteria 1 and 2);
#: mechanical, the fall height, the floor and the motor (criteria 1 and 2).
ELECTRICAL_PROPOSAL = _node(
    "electrical.motor_left",
    "electrical",
    {
        "stall_current": (
            0.67,
            "A",
            f"{POLOLU_MP}: stall current 0.67 A at 6 V, extrapolated (theoretical)",
        ),
        "continuous_current_max": (
            0.1675,
            "A",
            "rule of thumb: Pololu's general recommendation of 25% or less of the stall current "
            f"for brushed DC motors ({POLOLU_MP}), at the 6 V rating; to be carried to the "
            "maximum supply once the battery is chosen",
        ),
        "stall_duration_max": (
            1.0,
            "s",
            "the design's limit, handed to the firmware role: a stall is ended by cutting the "
            "drive after 1 s; Pololu warns that stalls can cause thermal damage to the windings "
            f"and brushes 'potentially on the order of seconds' ({POLOLU_MP})",
        ),
    },
    updated="2026-10-15T10:12:00Z",
)
MECHANICAL_PROPOSAL = _node(
    "mechanical.mount_tab_left",
    "mechanical",
    {
        "length": (TAB_LENGTH_M, "m", f"the design's choice; {_BUILD}"),
        "width": (TAB_WIDTH_M, "m", "the design's choice"),
        "thickness": (0.003, "m", "the design's choice"),
        "allowable_stress": (
            21.2,
            "MPa",
            f"{FORWARD_AM}: Ultrafuse PLA ISO 527 tensile strength ZX, 21.2 MPa, typical value, "
            "unverified until tested; the root stress crosses the layers",
        ),
    },
    updated="2026-10-15T10:40:00Z",
)
ELECTRICAL_SUMMARY = (
    "Chose the MP 6V 50:1 gearmotor (#2365) and recorded its 0.67 A stall current at 6 V, with "
    "a 1 s stall limit for firmware and the continuous-current guidance at 6 V. The battery and "
    "the driver are not chosen yet, so the stall current at the maximum supply and the "
    "comparison with the driver's limits wait for them."
)
MECHANICAL_SUMMARY = (
    "Chose a 3.0 mm Ultrafuse PLA tab printed with its length along Z, and recorded the "
    "across-layer strength, 21.2 MPa. The fall height and the floor are not given, and the motor "
    "is not chosen, so the fall-case load, the static and stall cases and the margin wait for "
    "them."
)

#: The attempts, by artefact id: role, specification, proposal and the session's last words.
ATTEMPTS: dict[str, tuple[str, str, dict[str, Any], str]] = {
    "e-attempt": ("electrical", ELECTRICAL_SPEC, ELECTRICAL_PROPOSAL, ELECTRICAL_SUMMARY),
    "m-attempt": ("mechanical", MECHANICAL_SPEC, MECHANICAL_PROPOSAL, MECHANICAL_SUMMARY),
}

#: What each artefact is expected to draw: the verdict, the rubric items that must carry a
#: twin's rejection (any one of them), and why. Never shown to a reviewer.
EXPECTED: dict[str, tuple[str, tuple[str, ...], str]] = {
    "e-consistent": (
        "reject",
        (),
        "not accept: the change raises the driver's current, and its junction-temperature "
        "items need a board figure no public source gives (an independent check, E1)",
    ),
    "e-with-error": (
        "reject",
        ("ES-14", "ES-15", "EP-5"),
        "HP motor's stall current not carried to 8.4 V: about 2.24 A, above 1.8 A and 1.9 A",
    ),
    "m-consistent": (
        "reject",
        (),
        "not accept: a typical catalogue value used as the allowable of a printed part, and no "
        "static-weight case (an independent check, M1 and M3)",
    ),
    "m-with-error": (
        "reject",
        ("MS-12", "MP-2", "MS-8"),
        "2.0 mm tab bending across layers held to the XY value: margin -0.29, not +0.17",
    ),
    "e-attempt": ("blocked", (), "no battery and no driver given for criteria 1 and 2"),
    "m-attempt": ("blocked", (), "no fall height, floor or motor given for criteria 1 and 2"),
}
