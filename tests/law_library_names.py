"""The catalogue rows the owner approved for the law library's second batch, pinned for the tests.

Twelve names and one kind, approved on 07.11.2026 after a drafting agent's research and two
adversarial reviews on another model: eleven rows, each by its definition with its source, and
one more name the owner asked for when he settled the stall's basis as "both, named apart".
``stall_current`` stays the stall at the command limit's duty times the supply's highest
voltage, the current the design sizes for; ``peak_stall_current`` is the stall at full duty and
that same voltage, the most the motor can draw, which a driver's peak rating and a fuse are
judged against.

What the rows add, and what they leave out on purpose, is listed here once, so the catalogue's
own tests, the prompt's and the hooks' read the same pins.
"""

from __future__ import annotations

#: The approved names and their kinds.
NAMES: dict[str, str] = {
    "rated_stall_current": "current",
    "peak_stall_current": "current",
    "no_load_current": "current",
    "stall_voltage": "voltage",
    "absolute_maximum_voltage": "voltage",
    "plant_mass": "mass",
    "overall_gear_ratio": "dimensionless",
    "counts_per_motor_revolution": "dimensionless",
    "counts_per_wheel_revolution": "dimensionless",
    "no_load_speed_wheel": "angular_velocity",
    "charge_capacity": "charge_capacity",
    "discharge_time": "duration",
}

#: The new kind, as (canonical unit, radian power, shape, absolute, sign): a store's rated
#: charge, in coulombs, never negative. Named apart from a charge, which is signed (a capacitor
#: plate's), so ``charge`` stays free for that kind.
KIND = "charge_capacity"
KIND_ROW: tuple[str, int, str | None, bool, str] = ("C", 0, None, False, "nonnegative")

#: The names the laws drafted next read, require or are excused by, guarded by the hooks before
#: any card for them is staged: every new name, and the three catalogued ones the approved rows
#: say a law reads (the stall law's ``rated_voltage`` and its excuse ``duty_cycle``, and the
#: gear kinematics' ``no_load_speed``).
FOR_LAWS: frozenset[str] = frozenset({*NAMES, "rated_voltage", "duty_cycle", "no_load_speed"})

#: Names the drafts proposed and the reviews and the owner left out: dropped (another name
#: already holds the quantity, or a suffix does) or deferred (no law reads it yet), and the first
#: drafts' spellings each renamed row replaced.
LEFT_OUT = (
    "max_duty_cycle",
    "output_torque",
    "nominal_voltage",
    "chopping_current",
    "regulated_current_limit",
    "peak_current_draw",
    "voltage_margin",
    "rated_stall_torque",
    "rated_no_load_speed",
    "rated_no_load_current",
    "applied_voltage",
    "output_no_load_speed",
    "counts_per_revolution",
    "counts_per_output_revolution",
    "max_voltage",
    "runtime",
    "charge",
)

#: The real values written under the new exact names, by the practice set and G11 run 4 (its
#: committed fixtures), each (name, value, unit): every one must pass its new kind.
REAL_VALUES: tuple[tuple[str, float | int, str], ...] = (
    ("charge_capacity", 2200, "mA*h"),
    ("counts_per_motor_revolution", 12, "dimensionless"),
    ("counts_per_wheel_revolution", 1010, "dimensionless"),
    ("counts_per_wheel_revolution", 1030, "dimensionless"),
    ("counts_per_wheel_revolution", 1150, "dimensionless"),
    ("counts_per_wheel_revolution", 1320, "dimensionless"),
    ("counts_per_wheel_revolution", 1530, "dimensionless"),
    ("counts_per_wheel_revolution", 1780, "dimensionless"),
    ("counts_per_wheel_revolution", 2620, "dimensionless"),
    ("no_load_current", 0.15, "A"),
    ("no_load_speed_wheel", 28.5885, "rad/s"),
    ("overall_gear_ratio", 110.2418, "1"),
    ("overall_gear_ratio", 110.242, "1"),
    ("rated_stall_current", 1.5, "A"),
    ("rated_stall_current", 1.6, "A"),
)

#: Spellings near a new name that a writer could use for another quantity, or for the same one in
#: other words, none of which the hooks may refuse once the names are guarded: different words
#: are read as unchecked, not refused.
NEAR_SPELLINGS_WRITTEN = (
    "run_time",
    "runtime",
    "charge_time",
    "discharge_rate",
    "battery_run_time",
    "absolute_max_voltage",
    "abs_max_voltage",
    "no_load_wheel_speed",
    "wheel_no_load_speed",
    "counts_per_wheel_rev",
    "counts_per_motor_rev",
    "start_voltage",
    "static_voltage",
    "stable_voltage",
    "breakaway_voltage",
    "min_start_voltage",
    "stall_current_turbo_charged",
    "stall_current_at_max_voltage",
    "stall_current_full_duty",
    "stall_torque_wheel",
    "max_average_motor_voltage",
)

#: The accepted hazard: a spelling refused as a misspelling of a new name, each with that name.
#: ``stalled_voltage`` means what ``stall_voltage`` means, so its refusal is a correct redirect
#: to the catalogued spelling; it costs a writer a retry, not a halted plan.
REFUSED_AS_MISSPELLINGS = (
    ("stalled_voltage", "stall_voltage"),
    ("peak_stall_currents", "peak_stall_current"),
    ("dischargetime", "discharge_time"),
)
