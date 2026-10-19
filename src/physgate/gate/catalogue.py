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
reading of the name and not the catalogue's. Coverage is a number, not an assumption.

Every kind, every name and every relation names its source. An entry without one
fails when this module is imported, so a gate with an unsourced entry cannot be
built at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date
from fractions import Fraction
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_Text = Annotated[str, StringConstraints(min_length=1)]

#: Read through search results and the passage pint's documentation quotes, not
#: in full (26.09.2026); the citation says so wherever it is recorded.
SI_BROCHURE = (
    "The International System of Units (SI), 9th edition, 2019 (NIST SP 330-2019), "
    "section 2.3.4 and the notes to Table 4 (read via search, not in full, 26.09.2026)"
)
WORKLOAD = "the name as the design-state graph's reference workload uses it"


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
    Kind(name="power", canonical="W", sign="nonnegative", source=SI_BROCHURE),
    Kind(name="energy", canonical="J", shape="energy", sign="positive", source=SI_BROCHURE),
    Kind(name="mass", canonical="kg", sign="nonnegative", source=SI_BROCHURE),
    Kind(name="length", canonical="m", source=SI_BROCHURE),
    Kind(name="force", canonical="N", source=SI_BROCHURE),
    Kind(name="torque", canonical="N*m", shape="force*length", source=SI_BROCHURE),
    Kind(name="frequency", canonical="Hz", angle=0, source=SI_BROCHURE),
    Kind(name="angular_velocity", canonical="rad/s", angle=1, source=SI_BROCHURE),
    Kind(name="angle", canonical="rad", angle=1, source=SI_BROCHURE),
    Kind(name="time", canonical="s", source=SI_BROCHURE),
    Kind(name="temperature", canonical="K", absolute=True, source=SI_BROCHURE),
    Kind(name="temperature_difference", canonical="K", source=SI_BROCHURE),
    Kind(name="thermal_resistance", canonical="K/W", sign="positive", source=SI_BROCHURE),
    Kind(name="dimensionless", canonical="dimensionless", source=SI_BROCHURE),
)


def _entries(*entries: Entry) -> Mapping[str, Entry]:
    for entry in entries:
        if entry.kind not in KINDS:
            msg = f"catalogue entry {entry.name!r} names an unknown kind {entry.kind!r}"
            raise ValueError(msg)
    return MappingProxyType({entry.name: entry for entry in entries})


FIXTURES = "named for the physics gate's checks, 26.09.2026"
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

QUANTITIES: Mapping[str, Entry] = _entries(
    Entry(name="stall_current", kind="current", source=WORKLOAD),
    Entry(name="current_draw", kind="current", source=FIXTURES),
    Entry(name="current_limit", kind="current", source=CURRENT_LIMIT),
    Entry(name="supply_voltage", kind="voltage", source=WORKLOAD),
    Entry(name="rated_voltage", kind="voltage", source=FIXTURES),
    Entry(name="power_draw", kind="power", source=FIXTURES),
    Entry(name="power_supply", kind="power", source=FIXTURES),
    Entry(name="input_power", kind="power", source=FIXTURES),
    Entry(name="output_power", kind="power", source=FIXTURES),
    Entry(name="heat_dissipation", kind="power", source=FIXTURES),
    Entry(name="heat_rejection_capacity", kind="power", source=FIXTURES),
    Entry(name="energy_capacity", kind="energy", source=FIXTURES),
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
    # The control quantities the series layer's published extractors read off a record
    # (``physgate.series.extract``), each in the unit the extractor publishes.
    Entry(name="phase_margin", kind="angle", source=EXTRACTORS),
    Entry(name="gain_crossover_frequency", kind="angular_velocity", source=EXTRACTORS),
    Entry(name="delay_margin", kind="time", source=EXTRACTORS),
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
    Entry(name="bore_diameter", kind="length", source=WORKLOAD),
    Entry(name="reaction_force", kind="force", source=FIXTURES),
    Entry(name="load_force", kind="force", source=FIXTURES),
    Entry(name="reaction_moment", kind="torque", source=FIXTURES),
    Entry(name="stall_torque", kind="torque", source=FIXTURES),
    Entry(name="torque_peak", kind="torque", source=WORKLOAD),
    Entry(name="sample_rate", kind="frequency", source=WORKLOAD),
    Entry(name="no_load_speed", kind="angular_velocity", source=FIXTURES),
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
                statement="a consumer's stall current is at most its supply's current limit",
                judged_by=4,
                source=HEADROOM,
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
    "_power, _rate, _ratio, _capacity, _resistance, _limit, _draw) is not here"
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
)


def inferred_by(name: str) -> Suffix | None:
    """The suffix that gives an uncatalogued ``name`` its kind, or ``None``.

    A catalogued name is never inferred: its entry says what it is. The suffix must end
    the name and leave something before it, so the bare word is not a name.
    """
    if name in QUANTITIES:
        return None
    for suffix in sorted(SUFFIXES, key=lambda s: -len(s.suffix)):
        if name.endswith(suffix.suffix) and len(name) > len(suffix.suffix):
            return suffix
    return None


def unknown_names(names: Iterable[str]) -> tuple[str, ...]:
    """The names among ``names`` the catalogue lacks, sorted, each once.

    A suffix that gives the gate a kind does not make a name known: the suffix rule is the
    gate's reading of a corpus written outside the hooks, not a licence for a writer.
    """
    return tuple(sorted({n for n in names if n not in QUANTITIES}))


#: The quantity names a relation, or one of check 3's readings, reads by name: the names a
#: writer steps out of by renaming. Every one is catalogued. The relations' names are read
#: off :mod:`physgate.gate.relations`; the statics names off :mod:`physgate.gate.check_equilibrium`
#: and its load readings. Spelled again for the hooks in :mod:`physgate.state.vocabulary`,
#: held equal by a test.
RELATION_NAMES: tuple[str, ...] = (
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


#: How far a misspelling may be from a relation's quantity and still shadow it.
_SHADOW_EDITS = 2


def _edit_distance(a: str, b: str) -> int:
    """The Levenshtein distance between ``a`` and ``b``: insertions, deletions, substitutions."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def shadowing_names(names: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """The uncatalogued names among ``names`` that shadow a relation's quantity, each once.

    A name shadows a quantity a relation reads when it ends in that quantity's last word
    (``motor_current`` for ``stall_current``, ``pack_mass`` for ``mass``), or when its
    spelling, underscores aside, is within two edits of the quantity's
    (``stall_currnt``, ``currentlimit``): the ways a writer steps out of the headroom
    relation, or the mass sum, without saying so. Every other uncatalogued name is written,
    and the gate records it as unchecked. Each pair is the name and the relation quantity
    it shadows: by last word, the one sharing most words with it, then the shortest; else
    the nearest spelling.
    """
    found: dict[str, str] = {}
    for name in sorted(set(names)):
        if name in QUANTITIES:
            continue
        words = name.split("_")
        shadowed = sorted(
            (r for r in RELATION_NAMES if r.rsplit("_", 1)[-1] == words[-1]),
            key=lambda r: (-len(set(r.split("_")) & set(words)), len(r), r),
        )
        if not shadowed:
            flat = name.replace("_", "")
            near = sorted(
                (
                    r
                    for r in RELATION_NAMES
                    if _edit_distance(flat, r.replace("_", "")) <= _SHADOW_EDITS
                ),
                key=lambda r: (_edit_distance(flat, r.replace("_", "")), len(r), r),
            )
            shadowed = near
        if shadowed:
            found[name] = shadowed[0]
    return tuple(found.items())


def kind_of(name: str) -> Kind | None:
    """The kind of the quantity called ``name``: its catalogue entry's, else its suffix's.

    ``None`` if the catalogue does not know the name and no suffix gives it a kind.
    """
    entry = QUANTITIES.get(name)
    if entry is not None:
        return KINDS[entry.kind]
    suffix = inferred_by(name)
    return KINDS[suffix.kind] if suffix is not None else None


def catalogue_digest() -> str:
    """The sha256 of the catalogue's content: every kind, name, relation and product.

    Taken over a canonical serialisation of what the catalogue says, not over this
    file, so a comment changes nothing and one changed entry changes the digest.
    Every gate result carries it: the catalogue decides what gets checked at all,
    so a result that does not name its catalogue cannot be reproduced.
    """
    content = {
        "kinds": [KINDS[k].model_dump() for k in sorted(KINDS)],
        "quantities": [QUANTITIES[q].model_dump() for q in sorted(QUANTITIES)],
        "relations": [RELATIONS[r].model_dump() for r in sorted(RELATIONS)],
        "products": sorted([*pair, kind] for pair, kind in PRODUCTS.items()),
        "sources": sorted(SOURCES.items()),
        "store_classes": [c.model_dump(mode="json") for c in STORE_CLASSES],
        "suffixes": [s.model_dump() for s in SUFFIXES],
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
