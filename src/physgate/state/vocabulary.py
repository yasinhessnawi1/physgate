"""The quantity names the gate reads, spelled where a hook can read them.

A role session's proposal is refused at write time when a quantity's name shadows one a
relation reads (``stall_currnt``, ``currentlimit``): a misspelling that steps out of a
relation without saying so. Every other name the catalogue lacks is written, and the gate
records it as unchecked. The names are the gate's catalogue
(physgate.gate.catalogue.QUANTITIES and RELATION_NAMES); they are listed again here because
a hook may not load the gate (pint, sympy and the gate's own modules are not code a hook is
allowed to pull in), and the sentinel's record of what a hook may load covers this package.
A test holds both lists equal to the catalogue, so they cannot drift.
"""

from __future__ import annotations

#: Every quantity name the catalogue knows, sorted. Held equal to the catalogue by a test.
QUANTITY_NAMES: tuple[str, ...] = (
    "ambient_temperature",
    "bore_diameter",
    "current_draw",
    "current_limit",
    "delay_margin",
    "energy_capacity",
    "external_gear_ratio",
    "gain_crossover_frequency",
    "gear_ratio",
    "heat_dissipation",
    "heat_rejection_capacity",
    "input_power",
    "load_force",
    "loop_gain",
    "mass",
    "max_discharge_power",
    "max_temperature",
    "mount_position",
    "no_load_speed",
    "output_power",
    "phase_margin",
    "power_draw",
    "power_supply",
    "rated_output_power",
    "rated_voltage",
    "reaction_force",
    "reaction_moment",
    "sample_rate",
    "stall_current",
    "stall_torque",
    "step_peak",
    "supply_voltage",
    "support_position",
    "supported_mass",
    "thermal_margin",
    "thermal_resistance",
    "torque_peak",
)


#: The names a relation, or one of the equilibrium check's readings, reads by name. Held
#: equal to the catalogue's RELATION_NAMES by a test.
RELATION_QUANTITY_NAMES: tuple[str, ...] = (
    "ambient_temperature",
    "current_limit",
    "energy_capacity",
    "external_gear_ratio",
    "gear_ratio",
    "heat_dissipation",
    "heat_rejection_capacity",
    "input_power",
    "load_force",
    "mass",
    "max_discharge_power",
    "max_temperature",
    "mount_position",
    "output_power",
    "power_draw",
    "power_supply",
    "reaction_force",
    "reaction_moment",
    "stall_current",
    "support_position",
    "supported_mass",
    "thermal_resistance",
    "torque_peak",
)


def _edits(a: str, b: str) -> int:
    """The insertions and deletions that turn a into b (a substitution counts two)."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, ca in enumerate(a, 1):
        for j, cb in enumerate(b, 1):
            rows[i][j] = rows[i - 1][j - 1] + 1 if ca == cb else max(rows[i - 1][j], rows[i][j - 1])
    return len(a) + len(b) - 2 * rows[-1][-1]


def _shadow_bound(flat: str) -> int:
    """One edit for a name of five characters or fewer, two for a longer one (no underscores)."""
    return 1 if len(flat) <= 5 else 2


def shadowing_quantity_names(names: object) -> tuple[tuple[str, str], ...]:
    """The unlisted names among names that shadow a relation's quantity, each once.

    A name shadows a relation's quantity when its spelling, underscores aside, is within the
    bound's insertions or deletions of the quantity's (stall_currnt, currentlimit, mas); a
    different name (idle_current, max, mask) is written. Each pair is the name and the nearest
    quantity it shadows, then the shortest, sorted by name; the catalogue's shadowing_names
    gives the same pairs.
    """
    if not isinstance(names, dict | list | tuple | set):
        return ()
    found: dict[str, str] = {}
    for name in sorted({str(n) for n in names}):
        if name in QUANTITY_NAMES:
            continue
        flat = name.replace("_", "")
        near = sorted(
            (
                r
                for r in RELATION_QUANTITY_NAMES
                if _edits(flat, r.replace("_", "")) <= _shadow_bound(flat)
            ),
            key=lambda r: (_edits(flat, r.replace("_", "")), len(r), r),
        )
        if near:
            found[name] = near[0]
    return tuple(found.items())


def unknown_quantity_names(names: object) -> tuple[str, ...]:
    """The names among names (a mapping's keys, or any iterable of strings) not listed here."""
    if not isinstance(names, dict | list | tuple | set):
        return ()
    return tuple(sorted({str(n) for n in names if str(n) not in QUANTITY_NAMES}))


def nearest_quantity_names(name: str, count: int = 3) -> tuple[str, ...]:
    """Listed names that share a word with name, the last word first; no library needed."""
    words = [w for w in name.split("_") if w]
    if not words:
        return ()
    last = words[-1]
    ranked = sorted(
        (n for n in QUANTITY_NAMES if any(w in n.split("_") for w in words)),
        key=lambda n: (0 if n.split("_")[-1] == last else 1, n),
    )
    return tuple(ranked[:count])
