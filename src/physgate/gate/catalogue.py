"""The gate's vocabulary: what each quantity name means, and the relations between them.

Relations are not declared on the node. They follow from the ``constrains``
edges a node already carries and from this catalogue, which lives inside the
protected gate: an agent cannot opt out of a relation by not declaring it, and
cannot weaken one from inside a session. The catalogue says

- the **kind** of each quantity name (a current, a torque, an absolute
  temperature), which fixes the unit it must be written in; and
- the **relations** the checks evaluate: a supply against the consumers that
  constrain it, a module's mass against its members, a component's temperature
  against its limit.

A quantity whose name is not here is checked for a unit that parses and nothing
else, and every gate run records it as unchecked. Where its name ends in a word with
one meaning in mechatronics (``SUFFIXES``), the record also says whether its unit and
sign are that word's: a mismatch is recorded, never refused, because the suffix is a
reading of the name and not the catalogue's. A name that ends in words saying which value
of a quantity it is (``QUALIFIERS``: ``stall_current_max``, ``computation_delay_budget``)
is read, once those words are taken off, as the catalogued name or the suffix that is left,
in the same way: its kind, its sign and its kind's definitional envelope, a mismatch recorded
and never refused, and no relation formed. Coverage is a number, not an assumption.

Every kind, every name and every relation names its source. An entry without one
fails when this module is imported, so a gate with an unsourced entry cannot be
built at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if TYPE_CHECKING:
    from physgate.gate.laws import LawTable

_Text = Annotated[str, StringConstraints(min_length=1)]

#: Read through search results and the passage pint's documentation quotes, not
#: in full (26.09.2026); the citation says so wherever it is recorded.
SI_BROCHURE = (
    "The International System of Units (SI), 9th edition, 2019 (NIST SP 330-2019), "
    "section 2.3.4 and the notes to Table 4 (read via search, not in full, 26.09.2026)"
)
WORKLOAD = "the name as the design-state graph's reference workload uses it"
#: The two kinds whose span is a definition, not a product class (D-A2-38): each is a
#: fraction, so the cross-domain table bounds it from 0 to 1 in every domain.
EFFICIENCY = (
    "the power a stage delivers over the power it takes in, a quantity of dimension one; at "
    "steady state the first law (the energy_balance relation's source) holds a passive "
    "stage's from 0 to 1"
)
DUTY_CYCLE = (
    "the time a periodic signal is on in each period over the period, a quantity of dimension "
    "one, from 0 to 1"
)
#: Why each kind the catalogue widening added (04.11.2026) has the sign it has: each from a
#: definition or a law, never from a product class.
_SIGN_SOURCES = {
    "resistance": (
        "never negative: a passive resistor dissipates P = I**2 R >= 0 (Joule's first law), so "
        "R >= 0; V/A converts"
    ),
    "moment_of_inertia": "never negative: J is the integral of r**2 dm, with dm >= 0",
    "area": "never negative: an area is the measure of a surface",
    "extent": (
        "never negative: a diameter or a thickness is a distance between two points; a "
        "position, which may be negative, stays a length"
    ),
    "duration": (
        "never negative: a period is the least T > 0 with f(t + T) = f(t), and a latency or "
        "an age cannot precede its cause; a delay or a time, which may be negative (a filter's "
        "group delay), stays a time"
    ),
    "velocity": "a linear velocity, signed by its direction: its unit is read, not its sign",
    "torque_constant": (
        "a motor's torque per ampere, Kt = torque / current, signed by convention: its unit is "
        "read, not its sign; in SI it is the same number as the back-EMF constant Ke in V*s/rad, "
        "so it is read at the radian's power 0 or -1"
    ),
    "modulus": (
        "never negative: a norm, a modulus or a ratio of two magnitudes (a peak of a "
        "sensitivity function, a spectral radius, a gain margin as a factor, a utilisation); "
        "no upper bound holds by definition"
    ),
    "temperature": (
        "never negative: a thermodynamic temperature, in kelvin above absolute zero (section 2.3.1)"
    ),
    "frequency": (
        "never negative: cycles or events per unit time; a signed frequency offset is another "
        "quantity and needs its own name"
    ),
    # The law library's kind (07.11.2026).
    "charge_capacity": (
        "never negative: a store's rated charge is the integral of its discharge current over a "
        "full discharge, the integral of I dt with I >= 0; a signed charge (a capacitor plate's) "
        "is another quantity and needs its own kind; A*h converts (2200 mA*h = 7920 C)"
    ),
}


def _signed(kind: str) -> str:
    """The SI brochure for a widened kind's unit, and the definition that fixes its sign."""
    return f"{SI_BROCHURE}; {_SIGN_SOURCES[kind]}"


#: The inertial sensor's rate, under its own name: the electrical and firmware tables hold it
#: to the six makers' data sheets' range.
OUTPUT_DATA_RATE = (
    "the rate at which an inertial sensor (a gyroscope, an accelerometer) delivers samples, "
    "as its data sheet sets it; not a control or firmware loop's rate"
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Kind(_Frozen):
    """What a quantity is, which fixes how it may be written.

    ``angle`` is the power of the radian in the unit's root units: 0 for a
    frequency, 1 for an angular velocity. Unit arithmetic treats the radian as
    dimensionless, so only this tells 1 Hz from 1 rad/s. ``shape`` is the factor
    structure a unit must have where the dimension alone cannot say: a torque is a
    force times a length, an energy is an energy unit or a power times a time.
    ``absolute`` marks an absolute temperature, the one kind an offset unit such
    as the degree Celsius may be written in. ``sign`` is what the kind's values
    may be, in its canonical unit: a mass or a power is never negative, and a
    thermal resistance is never zero or negative; a kind that may take either
    sign (a force, a position, a current) says ``any``.
    """

    name: _Text
    canonical: _Text
    angle: Literal[0, 1] = 0
    shape: Literal["force*length", "energy"] | None = None
    absolute: bool = False
    sign: Literal["any", "nonnegative", "positive"] = "any"
    source: _Text


class Entry(_Frozen):
    """A quantity name the gate knows, and its kind."""

    name: _Text
    kind: _Text
    source: _Text


def _kinds(*kinds: Kind) -> Mapping[str, Kind]:
    return MappingProxyType({kind.name: kind for kind in kinds})


KINDS: Mapping[str, Kind] = _kinds(
    Kind(name="current", canonical="A", source=SI_BROCHURE),
    Kind(name="voltage", canonical="V", source=SI_BROCHURE),
    Kind(name="resistance", canonical="ohm", sign="nonnegative", source=_signed("resistance")),
    Kind(name="power", canonical="W", sign="nonnegative", source=SI_BROCHURE),
    Kind(name="energy", canonical="J", shape="energy", sign="positive", source=SI_BROCHURE),
    Kind(
        name="charge_capacity",
        canonical="C",
        sign="nonnegative",
        source=_signed("charge_capacity"),
    ),
    Kind(name="mass", canonical="kg", sign="nonnegative", source=SI_BROCHURE),
    Kind(
        name="moment_of_inertia",
        canonical="kg*m**2",
        sign="nonnegative",
        source=_signed("moment_of_inertia"),
    ),
    Kind(name="length", canonical="m", source=SI_BROCHURE),
    Kind(name="extent", canonical="m", sign="nonnegative", source=_signed("extent")),
    Kind(name="area", canonical="m**2", sign="nonnegative", source=_signed("area")),
    Kind(name="velocity", canonical="m/s", source=_signed("velocity")),
    Kind(name="force", canonical="N", source=SI_BROCHURE),
    Kind(name="torque", canonical="N*m", shape="force*length", source=SI_BROCHURE),
    Kind(name="torque_constant", canonical="N*m/A", source=_signed("torque_constant")),
    Kind(
        name="frequency", canonical="Hz", angle=0, sign="nonnegative", source=_signed("frequency")
    ),
    Kind(name="angular_velocity", canonical="rad/s", angle=1, source=SI_BROCHURE),
    Kind(name="angle", canonical="rad", angle=1, source=SI_BROCHURE),
    Kind(name="time", canonical="s", source=SI_BROCHURE),
    Kind(name="duration", canonical="s", sign="nonnegative", source=_signed("duration")),
    Kind(
        name="temperature",
        canonical="K",
        absolute=True,
        sign="nonnegative",
        source=_signed("temperature"),
    ),
    Kind(name="temperature_difference", canonical="K", source=SI_BROCHURE),
    Kind(name="thermal_resistance", canonical="K/W", sign="positive", source=SI_BROCHURE),
    Kind(name="dimensionless", canonical="dimensionless", source=SI_BROCHURE),
    Kind(name="modulus", canonical="dimensionless", sign="nonnegative", source=_signed("modulus")),
    Kind(name="efficiency", canonical="dimensionless", sign="nonnegative", source=EFFICIENCY),
    Kind(name="duty_cycle", canonical="dimensionless", sign="nonnegative", source=DUTY_CYCLE),
)


def _entries(*entries: Entry) -> Mapping[str, Entry]:
    for entry in entries:
        if entry.kind not in KINDS:
            msg = f"catalogue entry {entry.name!r} names an unknown kind {entry.kind!r}"
            raise ValueError(msg)
    return MappingProxyType({entry.name: entry for entry in entries})


FIXTURES = "named for the physics gate's checks, 26.09.2026"
#: The names the catalogue widening added (04.11.2026), each a name a real plan wrote, read by
#: its definition.
TORQUE_CONSTANT = "a motor's torque per ampere of its current, as its data sheet states it"
MOTOR_RESISTANCE = "a motor's terminal resistance, as its data sheet states it"
UPDATE_RATE = (
    "the rate at which a control or firmware loop updates; not an inertial sensor's output "
    "data rate"
)
SENSITIVITY_PEAK = (
    "the peak magnitude of a feedback loop's sensitivity function, the largest |S| over "
    "frequency, a ratio of magnitudes"
)
GAIN_MARGIN = (
    "a feedback loop's gain margin as a factor: the loop gain's increase that brings it to "
    "instability, a ratio of magnitudes (a decibel figure is refused as a logarithmic unit)"
)
EXTRACTORS = (
    "the series layer's published extractors (physgate.series.extract), which read the value "
    "off a sealed record in this unit"
)
#: What ``current_limit`` means, because the current-headroom relation is judged against it:
#: the most a driver or supply is rated to deliver, its peak output current, never a
#: continuous rating. A continuous rating below a motor's stall current is a design that
#: needs current limiting; a peak rating below it is a stall the driver cannot carry.
#: Named limit: a writer who puts a continuous rating under this name is refused where
#: the stall exceeds it; the evaluation scores such a refusal, by the author's cited
#: row, as this stated limit and not as a false alarm.
CURRENT_LIMIT = (
    "a driver's or supply's maximum output current: the peak output current its datasheet "
    "rates (for example TI DRV8838, SLVSBA4F section 6.3, IOUT motor peak current 1.8 A), "
    "not a continuous rating"
)

#: The names the law library added (07.11.2026), each the quantity a law drafted for it reads,
#: defined so a writer and a law read one thing, with the source its definition rests on. Each was
#: drafted from its source, reviewed twice on another model and approved by the owner.
RATED_STALL_CURRENT = (
    "the current a DC motor's data sheet states it draws with its shaft held, at its rated "
    "voltage (rated_voltage on the same node), written beside stall_current and never instead "
    "of it; a data sheet's stall is an extrapolation, not exactly the rated voltage over the "
    "terminal resistance (Pololu, Micro Metal Gearmotors data sheet, Rev 6.2, February 2026, "
    "items #3063 and #3073, performance at 6 V; maxon, A-max 22 part 352989, values at nominal "
    "voltage)"
)
#: The pair the owner settled: one motor's stall, at the supply's highest voltage, under two
#: names. ``stall_current`` is the stall at the command limit's duty, the current the design
#: sizes for; this is the stall at full duty, the most the motor can draw.
PEAK_STALL_CURRENT = (
    "the current at a DC motor's terminals with its shaft held, at full duty and the supply's "
    "highest voltage, that voltage over the motor's terminal resistance: the largest stall the "
    "motor can draw, the one a driver's peak rating and a fuse are judged against. It is "
    "stall_current's pair on the same node: stall_current is the stall at the command limit's "
    "duty times that same highest voltage, and the two are never written one for the other; "
    "where no duty limit is fixed they are one figure (a brushed motor at stall has no "
    "back-EMF, so V = I R: Precision Microdrives 104-10L data sheet, rated 3.7 V, stall 0.114 A, "
    "terminal resistance 32.4 ohm; TI DRV8838, SLVSBA4F, section 6.3, IOUT motor peak current "
    "1.8 A)"
)
NO_LOAD_CURRENT = (
    "the current a DC motor draws turning with nothing on its shaft, as its data sheet states it "
    "at its rated voltage unless the node's source states another voltage; it depends on "
    "friction and varies only slightly with speed (maxon, DC motor catalogue, April 1998, "
    "'Comments regarding motor data', p. 36; Pololu, Micro Metal Gearmotors data sheet, Rev 6.2, "
    "150 mA at 6 V)"
)
STALL_VOLTAGE = (
    "the average voltage across a motor's terminals at which the stall_current on the same node "
    "is stated: the largest the drive can apply, the command limit's duty times the top of the "
    "supply range, or that top where no limit is fixed; not a voltage at which a motor starts "
    "or stalls (the average of a switched voltage is the duty times the voltage switched: "
    "Erickson and Maksimovic, Fundamentals of Power Electronics, chapter 2 slides, section 2.1)"
)
ABSOLUTE_MAXIMUM_VOLTAGE = (
    "the absolute maximum voltage a part's data sheet rates for the named terminal, the stress "
    "beyond which it may be damaged; never its recommended operating maximum (TI DRV8837/DRV8838, "
    "SLVSBA4F, revised April 2021, section 6.1 and its footnote 1, against section 6.3)"
)
PLANT_MASS = (
    "the actual mass of the body whose motion a control model describes, not an effective mass "
    "that adds a reflected inertia (M + J/r**2) (Astrom and Murray, Feedback Systems, draft "
    "v2.4a, 2006, section 7.3)"
)
OVERALL_GEAR_RATIO = (
    "a whole gear train's ratio from the motor shaft (the armature) to its last output, any "
    "built-in gearbox included: the product of every stage's input speed over its output speed, "
    "above 1 for a reduction (the reciprocal of Shigley's train value), and output torque over "
    "input torque for a lossless train (maxon, DC motor catalogue, April 1998, 'maxon gear', "
    "p. 102; Pololu, Micro Metal Gearmotors data sheet, Rev 6.2, exact gear ratios, p. 3; "
    "C. Bagci, Gear Technology, July/August 1990)"
)
COUNTS_PER_MOTOR_REVOLUTION = (
    "the encoder counts the firmware registers per revolution of the shaft the encoder reads (on "
    "a gearmotor with a rear encoder, the motor shaft, not the gearbox output), counting the "
    "edges the firmware counts (Pololu, Micro Metal Gearmotors data sheet, Rev 6.2, February "
    "2026, p. 2: 12 counts per revolution of the motor shaft when counting both edges of both "
    "channels)"
)
COUNTS_PER_WHEEL_REVOLUTION = (
    "the encoder counts the firmware registers per revolution of the drive's wheel, the last "
    "output of its train, counting the same edges as counts_per_motor_revolution: that figure "
    "times the ratio between the encoder's shaft and the wheel, which is overall_gear_ratio only "
    "for an encoder on the armature; not a whole number in general (Pololu, Micro Metal "
    "Gearmotors data sheet, Rev 6.2, p. 2: the gearbox output's counts are 12 times the gearbox "
    "reduction)"
)
NO_LOAD_SPEED_WHEEL = (
    "the no-load speed of a drive's wheel, the last output of its train: the no_load_speed at "
    "the output shaft of the motor as bought divided by the ratio of the stages the design adds "
    "after it, or the armature's speed divided by overall_gear_ratio (maxon, DC motor "
    "catalogue, April 1998, 'maxon gear', p. 102: the motor speed is divided by the reduction "
    "ratio)"
)
CHARGE_CAPACITY = (
    "the charge an energy store is rated to deliver from full charge to its cut-off voltage at "
    "the stated discharge rate, in A*h or C, never in W*h, which is energy_capacity (Energizer, "
    "NH15 engineering data sheet, form EBC-7102L: rated capacity 2500 mAh to 1.0 volts, based "
    "on a 500 mA discharge rate)"
)
DISCHARGE_TIME = (
    "the time a design states a battery or cell runs it, from full charge to its cut-off "
    "voltage, at the draw the design states; never a capacitor's bleed-down time (Energizer, "
    "NH15 engineering data sheet, form EBC-7102L: discharge curves against hours of discharge)"
)

QUANTITIES: Mapping[str, Entry] = _entries(
    #: The current at a DC motor's terminals with its shaft held, at the largest average voltage
    #: the drive can apply across it: the command limit's duty times the supply's highest
    #: voltage, with that voltage under stall_voltage on the same node. Its pair is
    #: peak_stall_current, the stall at full duty and the same highest voltage, which a driver's
    #: peak rating and a fuse are judged against; the two are never written one for the other.
    #: It is a motor-side current: the bus feeding a PWM driver carries about the duty times it,
    #: so held to the current limit of each supply its edges name, it over-states that supply's
    #: load by the inverse of the duty.
    Entry(name="stall_current", kind="current", source=WORKLOAD),
    Entry(name="rated_stall_current", kind="current", source=RATED_STALL_CURRENT),
    Entry(name="peak_stall_current", kind="current", source=PEAK_STALL_CURRENT),
    Entry(name="no_load_current", kind="current", source=NO_LOAD_CURRENT),
    Entry(name="current_draw", kind="current", source=FIXTURES),
    Entry(name="current_limit", kind="current", source=CURRENT_LIMIT),
    #: The nominal DC voltage of the rail a node is connected to. For a load it is taken at the
    #: load's power input; for a motor behind a driver, the driver's supply (the voltage the
    #: bridge switches), never the average it applies. On a node that supplies others (one that
    #: declares power_supply, energy_capacity or rated_output_power), it is the voltage at its
    #: output.
    Entry(name="supply_voltage", kind="voltage", source=WORKLOAD),
    #: The voltage a motor's data sheet states its figures at (its nominal voltage), not a
    #: maximum.
    Entry(name="rated_voltage", kind="voltage", source=FIXTURES),
    Entry(name="stall_voltage", kind="voltage", source=STALL_VOLTAGE),
    Entry(name="absolute_maximum_voltage", kind="voltage", source=ABSOLUTE_MAXIMUM_VOLTAGE),
    Entry(name="motor_resistance", kind="resistance", source=MOTOR_RESISTANCE),
    Entry(name="power_draw", kind="power", source=FIXTURES),
    Entry(name="power_supply", kind="power", source=FIXTURES),
    Entry(name="input_power", kind="power", source=FIXTURES),
    Entry(name="output_power", kind="power", source=FIXTURES),
    Entry(name="heat_dissipation", kind="power", source=FIXTURES),
    Entry(name="heat_rejection_capacity", kind="power", source=FIXTURES),
    Entry(name="energy_capacity", kind="energy", source=FIXTURES),
    Entry(name="charge_capacity", kind="charge_capacity", source=CHARGE_CAPACITY),
    Entry(
        name="max_discharge_power",
        kind="power",
        source=(
            "a battery's maximum continuous discharge power, as its datasheet states it "
            "(its maximum continuous discharge current at its nominal voltage)"
        ),
    ),
    Entry(
        name="rated_output_power",
        kind="power",
        source="a bench or mains power supply's rated output, as its datasheet states it",
    ),
    Entry(name="mass", kind="mass", source=WORKLOAD),
    Entry(name="plant_mass", kind="mass", source=PLANT_MASS),
    Entry(
        name="supported_mass",
        kind="mass",
        source=(
            "the mass a carrier declares it carries: held to the weighted parts whose edges "
            "name it, by the equilibrium check's carrier readings"
        ),
    ),
    Entry(
        name="gear_ratio",
        kind="dimensionless",
        source="a gear train's ratio, output over input; read by the torque-unit readings",
    ),
    Entry(
        name="external_gear_ratio",
        kind="dimensionless",
        source="an external gear stage's ratio, output over input; read by the torque readings",
    ),
    Entry(name="overall_gear_ratio", kind="dimensionless", source=OVERALL_GEAR_RATIO),
    Entry(
        name="counts_per_motor_revolution", kind="dimensionless", source=COUNTS_PER_MOTOR_REVOLUTION
    ),
    Entry(
        name="counts_per_wheel_revolution", kind="dimensionless", source=COUNTS_PER_WHEEL_REVOLUTION
    ),
    # The control quantities the series layer's published extractors read off a record
    # (``physgate.series.extract``), each in the unit the extractor publishes.
    Entry(name="phase_margin", kind="angle", source=EXTRACTORS),
    Entry(name="gain_crossover_frequency", kind="angular_velocity", source=EXTRACTORS),
    Entry(name="delay_margin", kind="time", source=EXTRACTORS),
    Entry(name="discharge_time", kind="duration", source=DISCHARGE_TIME),
    Entry(name="sensitivity_peak", kind="modulus", source=SENSITIVITY_PEAK),
    Entry(name="gain_margin", kind="modulus", source=GAIN_MARGIN),
    Entry(
        name="step_peak",
        kind="length",
        source=(
            "the control stand-in's step response: the largest position the trace reaches, "
            "read off its record by the series layer's max_abs extractor"
        ),
    ),
    Entry(name="support_position", kind="length", source=FIXTURES),
    Entry(name="mount_position", kind="length", source=FIXTURES),
    Entry(name="bore_diameter", kind="extent", source=WORKLOAD),
    Entry(name="reaction_force", kind="force", source=FIXTURES),
    Entry(name="load_force", kind="force", source=FIXTURES),
    Entry(name="reaction_moment", kind="torque", source=FIXTURES),
    #: At the output shaft of the motor as bought: on a gearmotor, its gearbox's output shaft,
    #: not the motor shaft inside it. The voltage it is taken at is the one its source gives (the
    #: brief's or the nominal value), so on one node it is not at the voltage of stall_current.
    Entry(name="stall_torque", kind="torque", source=FIXTURES),
    Entry(name="torque_peak", kind="torque", source=WORKLOAD),
    Entry(name="torque_constant", kind="torque_constant", source=TORQUE_CONSTANT),
    Entry(name="sample_rate", kind="frequency", source=WORKLOAD),
    Entry(name="output_data_rate", kind="frequency", source=OUTPUT_DATA_RATE),
    Entry(name="update_rate", kind="frequency", source=UPDATE_RATE),
    Entry(name="efficiency", kind="efficiency", source=EFFICIENCY),
    Entry(name="duty_cycle", kind="duty_cycle", source=DUTY_CYCLE),
    #: At the output shaft of the motor as bought: on a gearmotor, its gearbox's output shaft,
    #: not the motor shaft inside it. The voltage it is taken at is the one its source gives (the
    #: brief's or the nominal value), so on one node it is not at the voltage of stall_current.
    Entry(name="no_load_speed", kind="angular_velocity", source=FIXTURES),
    Entry(name="no_load_speed_wheel", kind="angular_velocity", source=NO_LOAD_SPEED_WHEEL),
    Entry(name="max_temperature", kind="temperature", source=FIXTURES),
    Entry(name="ambient_temperature", kind="temperature", source=FIXTURES),
    Entry(name="thermal_margin", kind="temperature_difference", source=WORKLOAD),
    Entry(name="thermal_resistance", kind="thermal_resistance", source=FIXTURES),
    Entry(name="loop_gain", kind="dimensionless", source=WORKLOAD),
)

#: What multiplying two kinds gives, where a relation multiplies. Anything else is
#: refused: a product the catalogue does not name has no kind to be checked against.
PRODUCTS: Mapping[tuple[str, str], str] = MappingProxyType(
    {("thermal_resistance", "power"): "temperature_difference"}
)


class StoreClass(_Frozen):
    """A class of energy store, and the fastest discharge a maker rates one of them for.

    ``per_hour`` is the part's maximum continuous discharge power over the energy it stores
    (its C-rate), rounded up to the next whole number, so the bound built from it is never
    tighter than the source and never looser than that rounding: the figure the source's own
    arithmetic shows, and nothing else. For the lead-acid class it is the shortest
    constant-current discharge the maker tabulates (two minutes), above any continuous
    rating; for the ultracapacitor class it is the most power any cell can deliver into any
    load, from the smallest confirmed time constant. ``confirmed`` is the date the figure was
    read in the maker's own document, with that document's number and revision in
    ``source``; a class without it cannot be built, so no unconfirmed figure refuses a design.
    """

    name: _Text
    per_hour: Annotated[int, Field(gt=0)]
    source: _Text
    confirmed: date


#: The store classes whose fastest rating bounds a store's declared discharge. A node
#: declares no chemistry, so the relation takes the largest of them: it can refuse only a
#: rating that no store of any listed class is made to give. Every figure was fetched and
#: read in the maker's document named, on the date given; the arithmetic is shown.
STORE_CLASSES: tuple[StoreClass, ...] = (
    StoreClass(
        name="nickel-metal hydride cell",
        per_hour=10,
        source=(
            "GP Batteries GP330SCH sub-C NiMH data sheet, ZRS1161 rev.02 (undated): "
            "recommended discharge current 330 mA to 30 A, nominal capacity 3300 mAh; "
            "30 A / 3.3 A h = 9.1 per hour (the GP330SCHR sheet ZRS1162 could not be found; "
            "the GP catalogue lists the SCHR at 3300 mAh typical with no discharge column)"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="valve-regulated lead-acid battery",
        per_hour=9,
        source=(
            "EnerSys ODYSSEY Application Manual, SLI Drycell Battery Guide, sixth edition "
            "(US-ODY-AM-001, April 2006), PC680 performance data at 25 C: 143.0 A for 2 min to "
            "10.02 V (a two-minute rating, not a continuous one, so above any continuous "
            "figure; no edition states a maximum continuous current), specifications table "
            "PC680 17 A h at the 20-hour rate (its performance table's 20-hour row reads "
            "16.0 A h, which would give 9.0); 143 A / 17 A h = 8.4 per hour"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="lithium-ion cylindrical power cell",
        per_hour=12,
        source=(
            "Samsung SDI INR21700-30T specification, version V0.0 (2015-12-29), section 3.6: "
            "maximum continuous discharge 35 A at 25 C, section 3.1 typical capacity 3000 mAh; "
            "35 A / 3.0 A h = 11.7 per hour"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="lithium iron phosphate power cell",
        per_hour=28,
        source=(
            "A123 Systems ANR26650M1-B data sheet MD100113-01 (2011): maximum continuous "
            "discharge 70 A, nominal capacity 2.5 A h; 70 A / 2.5 A h = 28 per hour (the later "
            "MD100113-02 reportedly states 50 A, which would give 20: the earlier, looser "
            "figure is kept, so the bound is never tighter than a maker's sheet)"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="lithium-polymer hobby pack",
        per_hour=150,
        source=(
            "Tattu R-Line Version 5.0 1400 mAh 6S pack, maker's product page (genstattu.com, "
            "undated): discharge rate 150C, maximum burst discharge rate 260C stated "
            "separately; the maker's own continuous figure, the highest found on any pack"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="lithium-ion capacitor",
        per_hour=311,
        source=(
            "Musashi Energy Solutions hybrid supercapacitor prismatic cells data sheet, "
            "Rv 250615 (June 2025), CPQ3300SD: 3300 F from 3.8 V to 2.2 V, continuous charge "
            "and discharge current 360 A (per UL 810A; the maker's web page still says 200 A); "
            "stored energy 3300 F x (3.8^2 - 2.2^2) V^2 / 2 = 4.40 W h, and 360 A x 3.8 V / "
            "4.40 W h = 311 per hour"
        ),
        confirmed=date(2026, 10, 19),
    ),
    StoreClass(
        name="electric double-layer capacitor",
        per_hour=10910,
        source=(
            "the most power any capacitor cell can deliver into any load, V^2 / (4 ESR) "
            "(maximum power transfer), over the energy it stores, C V^2 / 2: 1 / (2 ESR C), "
            "from the smallest confirmed time constant ESR x C in a maker's catalogue: "
            "Maxwell Technologies BCAP0003 P270 S01, data sheet 3001957-EN.4 (2019): 3 F, "
            "typical initial ESR(DC) 55 mOhm (rated maximum 70 mOhm), 0.165 s; 1 / (2 x 0.165 s) "
            "= 3.03 per second = 10909.1 per hour. Its thermal continuous rating (2.9 A at a "
            "40 C rise, product comparison matrix 3000489-EN.8, 2019: 2577.8 per hour) is far "
            "below that, so this bound is above every maker's continuous figure; no cell with "
            "a smaller time constant was confirmed (Eaton HV0810-2R7105-R 0.20 s; Maxwell "
            "BCAP0003 P300 X11 0.186 s typical)"
        ),
        confirmed=date(2026, 10, 19),
    ),
)
#: The fastest class, whose rate is the discharge relation's bound.
FASTEST: StoreClass = max(STORE_CLASSES, key=lambda c: c.per_hour)
MAX_DISCHARGE_PER_HOUR = Fraction(FASTEST.per_hour)

#: Why a stall current is held to its supply's current limit.
HEADROOM = (
    "a brushed motor at stall has no back-EMF, so V = I R gives its stall current, the most "
    "it draws (Precision Microdrives 104-10L, 4 mm coreless motor, data sheet "
    "104-10J-104-008-104-10L V1, maker's product page read 19.10.2026: rated 3.7 V, stall "
    "0.114 A, terminal resistance 32.4 ohm); a driver's peak output current is the most it is "
    "rated to deliver (TI DRV8838, SLVSBA4F, revised April 2021, read 19.10.2026: section 6.3 "
    "I_OUT motor peak current 1.8 A; section 6.5 overcurrent protection trip 1.9 A minimum), "
    "so a stall above it is beyond the driver's rating at every start and reversal"
)
#: Why a motor's peak stall is held to the same limit: the owner's basis for a driver's and a
#: fuse's ratings (07.11.2026), the stall at full duty and the supply's highest voltage.
PEAK_HEADROOM = (
    f"{HEADROOM}; a driver's peak rating and a fuse are judged at the motor's peak stall, at full "
    "duty and the supply's highest voltage, the current it draws if the command limit's duty is "
    "bypassed and during each PWM on-time, while the design sizes for the stall at that duty"
)
#: Why a store's discharge rating is held to what it stores.
DISCHARGE = (
    "a store's discharge is bounded by its class: no part of any class in the catalogue's "
    "store classes is rated to discharge faster than the fastest of them, each figure read in "
    "its maker's document on the date the class records; for a capacitor the bound is the "
    "most power any confirmed cell can deliver into any load"
)


class Relation(_Frozen):
    """A relation between quantities that the checks evaluate over the graph.

    ``judged_by`` is the check that decides whether it holds; the unit check makes
    sure its two sides can be compared. Every relation has a judge: a relation whose
    units alone were checked would be a comparison the gate states and never makes.
    """

    name: _Text
    statement: _Text
    judged_by: Literal[3, 4, 5, 6]
    source: _Text


RELATIONS: Mapping[str, Relation] = MappingProxyType(
    {
        r.name: r
        for r in (
            Relation(
                name="power_budget",
                statement=(
                    "the power drawn by the nodes that constrain a supply is at most the "
                    "power it supplies"
                ),
                judged_by=4,
                source="conservation of energy at steady state: a supply's output covers its loads",
            ),
            Relation(
                name="supply_covered",
                statement=(
                    "the power a node supplies to what draws from it is at most the power it "
                    "draws from its own supply"
                ),
                judged_by=4,
                source=(
                    "conservation of energy at steady state: a stage that passes power on "
                    "cannot hand out more than it takes in"
                ),
            ),
            Relation(
                name="source_rating",
                statement=(
                    "the power a declared source supplies is at most its declared output "
                    "rating plus whatever it draws from upstream"
                ),
                judged_by=4,
                source="a source's datasheet rating bounds its continuous output",
            ),
            Relation(
                name="current_limit",
                statement=(
                    "a consumer's stall current is at most the current limit on its own node, "
                    "and at most that of each supply its constrains edges name"
                ),
                judged_by=4,
                source=HEADROOM,
            ),
            Relation(
                name="peak_current_limit",
                statement=(
                    "a consumer's peak stall current, at full duty and its supply's highest "
                    "voltage, is at most the current limit on its own node, and at most that of "
                    "each supply its constrains edges name"
                ),
                judged_by=4,
                source=PEAK_HEADROOM,
            ),
            Relation(
                name="discharge_rate",
                statement=(
                    "an energy store's maximum continuous discharge power is at most its stored "
                    "energy times the highest continuous discharge rate any store class is "
                    "rated for"
                ),
                judged_by=4,
                source=DISCHARGE,
            ),
            Relation(
                name="mass_sum",
                statement="a module's declared mass is the sum of its members' masses",
                judged_by=5,
                source="conservation of mass: a whole weighs what its parts weigh",
            ),
            Relation(
                name="energy_balance",
                statement=(
                    "the power a node takes in is the power it delivers plus the heat it dissipates"
                ),
                judged_by=5,
                source="the first law of thermodynamics for a component at steady state",
            ),
            Relation(
                name="heat_budget",
                statement=(
                    "the heat dissipated by a module's members is at most the heat the module "
                    "can reject"
                ),
                judged_by=6,
                source="steady-state energy balance of a control volume",
            ),
            Relation(
                name="junction_limit",
                statement=(
                    "ambient temperature plus thermal resistance times dissipated power is at "
                    "most the component's maximum temperature"
                ),
                judged_by=6,
                source=(
                    "the junction-to-ambient thermal resistance, (TJ - TA) / P, as in Texas "
                    "Instruments application note SPRA953 (wording from a secondary source, "
                    "26.09.2026)"
                ),
            ),
        )
    }
)


#: What makes a node a declared source of power, and the rating that bounds it.
#: A node that supplies power is one of these, or it draws what it supplies from a
#: supply upstream; otherwise any module could become a source by dropping its
#: upstream edge and its draw. Declaring a source does not exempt a node from a
#: bound: its supply is held to its rating (plus anything it draws upstream), and
#: a source with no rating is recorded as unchecked, never passed.
#:
#: - ``energy_capacity``: a battery declares the energy it stores, and is bounded
#:   by ``max_discharge_power``, its maximum continuous discharge;
#: - ``rated_output_power``: a bench or mains supply declares its rated output,
#:   which is its bound.
SOURCES: Mapping[str, str] = MappingProxyType(
    {
        "energy_capacity": "max_discharge_power",
        "rated_output_power": "rated_output_power",
    }
)


class Suffix(_Frozen):
    """A word that ends a quantity name and has one SI meaning, so it fixes the name's kind."""

    suffix: _Text
    kind: _Text
    source: _Text


SUFFIX_RULE = (
    "a closed list, 19.10.2026: a name the catalogue lacks whose last word has one meaning "
    "in mechatronics (the dimension of the word's quantity in the SI brochure, 9th edition, "
    "2019, section 2.3) is read against that dimension and sign, and a mismatch is recorded "
    "as unchecked, never refused; a word with more than one meaning there (_current, which "
    "is also a loss in watts; _position, _length, _width and _height, which are also counts, "
    "pulses and ratios; _temperature, which is also a colour or a difference; _energy, "
    "_power, _rate, _ratio, _capacity, _resistance, _limit, _draw) is not here; "
    "_efficiency and _duty_cycle added 03.11.2026, each a fraction by its definition"
)
#: The suffixes the catalogue widening added. Each was held to every value a real run wrote
#: before it was added, and reaches one of them; _utilization is _utilisation's spelling.
WIDENED_SUFFIX_RULE = (
    "the same closed rule, widened 04.11.2026 by definitions alone: each suffix is a word or "
    "words with one meaning as the noun of what the quantity is, held to every value a real "
    "run wrote before it was added; a period, a duration, a latency and an age are never "
    "negative, while a delay, a lateness and a time may be signed (a filter's group delay); a "
    "spectral radius, a sensitivity peak, a gain margin and a utilisation are moduli, never "
    "negative; a suffix of one word never reaches a kind whose span refuses (the one before "
    "this rule is _efficiency); _resistance alone stays out (thermal, electrical and rolling)"
)


def _suffixes(*suffixes: Suffix) -> tuple[Suffix, ...]:
    for s in suffixes:
        if s.kind not in KINDS:
            msg = f"the suffix {s.suffix!r} names an unknown kind {s.kind!r}"
            raise ValueError(msg)
    return suffixes


#: Each suffix is written with its leading underscore: the word must end the name and
#: be a whole word of it. Longer suffixes are matched first. The suffix alone is not a name.
SUFFIXES: tuple[Suffix, ...] = _suffixes(
    Suffix(suffix="_voltage", kind="voltage", source=SUFFIX_RULE),
    Suffix(suffix="_mass", kind="mass", source=SUFFIX_RULE),
    Suffix(suffix="_force", kind="force", source=SUFFIX_RULE),
    Suffix(suffix="_torque", kind="torque", source=SUFFIX_RULE),
    Suffix(suffix="_frequency", kind="frequency", source=SUFFIX_RULE),
    Suffix(suffix="_diameter", kind="length", source=SUFFIX_RULE),
    Suffix(suffix="_radius", kind="length", source=SUFFIX_RULE),
    Suffix(suffix="_thickness", kind="length", source=SUFFIX_RULE),
    Suffix(suffix="_efficiency", kind="efficiency", source=SUFFIX_RULE),
    Suffix(suffix="_duty_cycle", kind="duty_cycle", source=SUFFIX_RULE),
    Suffix(suffix="_period", kind="duration", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_duration", kind="duration", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_latency", kind="duration", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_age", kind="duration", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_delay", kind="time", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_lateness", kind="time", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_time", kind="time", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_delay_margin", kind="time", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_phase_margin", kind="angle", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_inertia", kind="moment_of_inertia", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_area", kind="area", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_ground_speed", kind="velocity", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_stall_current", kind="current", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_no_load_current", kind="current", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_motor_current", kind="current", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_no_load_speed", kind="angular_velocity", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_gain_crossover_frequency", kind="angular_velocity", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_gear_ratio", kind="dimensionless", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_output_data_rate", kind="frequency", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_sensitivity_peak", kind="modulus", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_spectral_radius", kind="modulus", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_gain_margin", kind="modulus", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_utilisation", kind="modulus", source=WIDENED_SUFFIX_RULE),
    Suffix(suffix="_utilization", kind="modulus", source=WIDENED_SUFFIX_RULE),
)

#: The words that, ending a name, say which value of a quantity it is and not what it is: a
#: maximum, a bound or a measured value of a current is a current. A closed list (04.11.2026).
#: A word that says where or in which case a quantity is taken (_wheel, _armature, _full_duty,
#: _reflected) changes what it is, and is not here.
QUALIFIERS: tuple[str, ...] = (
    "_max",
    "_min",
    "_nominal",
    "_measured",
    "_applied",
    "_bound",
    "_budget",
    "_typical",
    "_lower",
    "_upper",
    "_implied",
    "_estimated",
    "_indicative",
)

#: The suffixes and names read at more than one power of the radian, each with its powers,
#: because one quantity is written both ways: "frequency" names both f, in hertz, and the
#: angular frequency omega, in radians per second; a motor's torque constant Kt, in N*m/A, is in
#: SI the same number as its back-EMF constant Ke, in V*s/rad. The dimension and the sign are
#: still read; every other catalogued name keeps its kind's one power. No relation and no range
#: takes a name read so (a guard row holds that): pint takes the radian as one, so a frequency
#: in rad/s is converted to hertz without its factor 2 pi.
EITHER_ANGLE: Mapping[str, tuple[int, ...]] = MappingProxyType(
    {"_frequency": (0, 1), "torque_constant": (0, -1)}
)


@dataclass(frozen=True)
class Reading:
    """How the gate reads a name the catalogue lacks, and the kind that reading gives it.

    ``base`` is what the name is read as: a suffix that ends it (``_delay``), or, once the
    ``qualifiers`` that end it are taken off, the catalogued name (``stall_current``) or the
    suffix (``_delay``) that is left. ``qualifiers`` are in the order they stand in the name.
    """

    name: str
    base: str
    kind: str
    qualifiers: tuple[str, ...] = ()

    @property
    def rule(self) -> str:
        """The reading as a record names it: ``_voltage``, ``stall_current + _max``."""
        return f"{self.base} + {''.join(self.qualifiers)}" if self.qualifiers else self.base

    @property
    def angles(self) -> tuple[int, ...]:
        """The powers of the radian the reading accepts in the name's unit."""
        return EITHER_ANGLE.get(self.base, (KINDS[self.kind].angle,))


def _suffix_of(name: str) -> Suffix | None:
    """The longest suffix that ends ``name`` and leaves something before it, or ``None``."""
    for suffix in sorted(SUFFIXES, key=lambda s: -len(s.suffix)):
        if name.endswith(suffix.suffix) and len(name) > len(suffix.suffix):
            return suffix
    return None


def _qualifier_of(name: str) -> str | None:
    """The qualifier word that ends ``name`` and leaves something before it, or ``None``."""
    return next((q for q in QUALIFIERS if name.endswith(q) and len(name) > len(q)), None)


def inferred_by(name: str) -> Reading | None:
    """How the gate reads an uncatalogued ``name``, or ``None`` if nothing gives it a kind.

    A catalogued name is never inferred: its entry says what it is. A suffix of the name
    reads it first; the suffix must end the name and leave something before it, so the bare
    word is not a name. Only where none does are its qualifier words taken off its end, one
    at a time and each leaving something before it, and what is left read as a catalogued
    name or by its own suffix. A qualifier alone, or a rest the catalogue cannot read, gives
    nothing.
    """
    if name in QUANTITIES:
        return None
    suffix = _suffix_of(name)
    if suffix is not None:
        return Reading(name=name, base=suffix.suffix, kind=suffix.kind)
    rest = name
    taken: tuple[str, ...] = ()
    while (word := _qualifier_of(rest)) is not None:
        rest, taken = rest[: -len(word)], (word, *taken)
    if not taken:
        return None
    entry = QUANTITIES.get(rest)
    if entry is not None:
        return Reading(name=name, base=rest, kind=entry.kind, qualifiers=taken)
    suffix = _suffix_of(rest)
    if suffix is not None:
        return Reading(name=name, base=suffix.suffix, kind=suffix.kind, qualifiers=taken)
    return None


def unknown_names(names: Iterable[str]) -> tuple[str, ...]:
    """The names among ``names`` the catalogue lacks, sorted, each once.

    A suffix or a qualifier that gives the gate a kind does not make a name known: the
    reading is the gate's, of a corpus written outside the hooks, not a licence for a writer.
    """
    return tuple(sorted({n for n in names if n not in QUANTITIES}))


#: The quantity names a relation, one of check 3's readings, or a law reads by name: the names a
#: writer steps out of by renaming. Every one is catalogued. The relations' names are read
#: off :mod:`physgate.gate.relations`; the statics names off :mod:`physgate.gate.check_equilibrium`
#: and its load readings; a law's off its row, those of every law in the table and of every law
#: card staged for a person to promote, so a law's names are guarded before it is promoted; and the
#: names the owner approved for the laws drafted next (07.11.2026), guarded before any card for them
#: is written: the law library's new names, and rated_voltage, duty_cycle and no_load_speed.
#: Every name a relation reads is one, the source rating's rated_output_power included.
#: Spelled again for the hooks in :mod:`physgate.state.vocabulary`, held equal by a test.
RELATION_NAMES: tuple[str, ...] = (
    "absolute_maximum_voltage",
    "ambient_temperature",
    "charge_capacity",
    "counts_per_motor_revolution",
    "counts_per_wheel_revolution",
    "current_draw",
    "current_limit",
    "discharge_time",
    "duty_cycle",
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
    "no_load_current",
    "no_load_speed",
    "no_load_speed_wheel",
    "output_data_rate",
    "output_power",
    "overall_gear_ratio",
    "peak_stall_current",
    "plant_mass",
    "power_draw",
    "power_supply",
    "rated_output_power",
    "rated_stall_current",
    "rated_voltage",
    "reaction_force",
    "reaction_moment",
    "sample_rate",
    "stall_current",
    "stall_voltage",
    "supply_voltage",
    "support_position",
    "supported_mass",
    "thermal_resistance",
    "torque_peak",
    "update_rate",
)


def _edits(a: str, b: str) -> int:
    """The insertions and deletions that turn ``a`` into ``b`` (a substitution counts two)."""
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, ca in enumerate(a, 1):
        for j, cb in enumerate(b, 1):
            rows[i][j] = rows[i - 1][j - 1] + 1 if ca == cb else max(rows[i - 1][j], rows[i][j - 1])
    return len(a) + len(b) - 2 * rows[-1][-1]


def _levenshtein(a: str, b: str) -> int:
    """The insertions, deletions and substitutions that turn ``a`` into ``b``."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


#: A relation quantity of this many characters or fewer, underscores aside, is a short word.
SHORT_WORD = 5


def _shadows(flat: str, quantity: str) -> int | None:
    """How far ``flat`` is from a relation quantity's flat spelling, if it shadows it.

    Two clauses, and a name shadows the quantity under either. The first is the rule as it
    stood: within one insertion or deletion for a name of five characters or fewer, two for
    a longer one (a substitution counting two). The second, for a short quantity only
    (``mass``): within one edit by Levenshtein, a substitution counting one, because a short
    word is one substitution from another word (``mess``, ``moss``, ``mask``). The second
    clause only adds to what the first refuses, so nothing once refused is written.
    """
    if abs(len(flat) - len(quantity)) > 2:
        return None
    edits = _edits(flat, quantity)
    if edits <= (1 if len(flat) <= SHORT_WORD else 2):
        return edits
    if len(quantity) <= SHORT_WORD and _levenshtein(flat, quantity) <= 1:
        return 1
    return None


def shadowing_names(names: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """The uncatalogued names among ``names`` that shadow a relation's quantity, each once.

    A name shadows a quantity a relation reads when its spelling, underscores aside, is
    a misspelling of the quantity's by ``_shadows`` (``stall_currnt``, ``currentlimit``,
    ``supported_mas``; ``mas``, ``mess``, ``moss``, ``mask``): one that steps out of the
    headroom relation, or the mass sum, without saying so. A different name
    (``idle_current``, ``motor_current_draw``, ``max``, ``dry_mass``) is written, and the gate
    records it as unchecked. Each pair is the name and the nearest relation quantity it
    shadows, then the shortest.
    """
    found: dict[str, str] = {}
    for name in sorted(set(names)):
        if name in QUANTITIES:
            continue
        flat = name.replace("_", "")
        near = [
            (distance, len(r), r)
            for r in RELATION_NAMES
            if (distance := _shadows(flat, r.replace("_", ""))) is not None
        ]
        if near:
            found[name] = min(near)[2]
    return tuple(found.items())


def kind_of(name: str) -> Kind | None:
    """The kind of the quantity called ``name``: its catalogue entry's, else its reading's.

    ``None`` if the catalogue does not know the name and no suffix, after any qualifiers,
    gives it a kind.
    """
    entry = QUANTITIES.get(name)
    if entry is not None:
        return KINDS[entry.kind]
    reading = inferred_by(name)
    return KINDS[reading.kind] if reading is not None else None


def angles_of(name: str) -> tuple[int, ...] | None:
    """The powers of the radian the unit of the quantity called ``name`` may have.

    A catalogued name's are its kind's, unless ``EITHER_ANGLE`` lists the name; an uncatalogued
    name's are its reading's. ``None`` if no reading gives the name a kind.
    """
    entry = QUANTITIES.get(name)
    if entry is not None:
        return EITHER_ANGLE.get(name, (KINDS[entry.kind].angle,))
    reading = inferred_by(name)
    return reading.angles if reading is not None else None


def catalogue_digest(laws: LawTable) -> str:
    """The sha256 of the catalogue's content and of the law table ``laws``.

    The catalogue's content is every kind, name, relation, product and reading.
    Taken over a canonical serialisation of what the catalogue and the table say, not over
    their files, so a comment changes nothing and one changed entry, one changed law or one
    changed law status changes the digest. Every gate result carries it: the catalogue and the
    laws decide what gets checked at all, so a result that does not name them cannot be
    reproduced. An empty table adds nothing, so the digest of a gate with no law is the
    catalogue's alone, as it was before laws existed; any law moves it.
    """
    content: dict[str, Any] = {
        "kinds": [KINDS[k].model_dump() for k in sorted(KINDS)],
        "quantities": [QUANTITIES[q].model_dump() for q in sorted(QUANTITIES)],
        "relations": [RELATIONS[r].model_dump() for r in sorted(RELATIONS)],
        "products": sorted([*pair, kind] for pair, kind in PRODUCTS.items()),
        "sources": sorted(SOURCES.items()),
        "store_classes": [c.model_dump(mode="json") for c in STORE_CLASSES],
        "suffixes": [s.model_dump() for s in SUFFIXES],
        "qualifiers": list(QUALIFIERS),
        "either_angle": [[key, list(powers)] for key, powers in sorted(EITHER_ANGLE.items())],
    }
    if laws.laws:
        content["laws"] = laws.content()
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
