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
else, and every gate run records it as unchecked. Coverage is a number, not an
assumption.

Every kind, every name and every relation names its source. An entry without one
fails when this module is imported, so a gate with an unsourced entry cannot be
built at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

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
    Kind(name="energy", canonical="J", shape="energy", source=SI_BROCHURE),
    Kind(name="mass", canonical="kg", sign="nonnegative", source=SI_BROCHURE),
    Kind(name="length", canonical="m", source=SI_BROCHURE),
    Kind(name="force", canonical="N", source=SI_BROCHURE),
    Kind(name="torque", canonical="N*m", shape="force*length", source=SI_BROCHURE),
    Kind(name="frequency", canonical="Hz", angle=0, source=SI_BROCHURE),
    Kind(name="angular_velocity", canonical="rad/s", angle=1, source=SI_BROCHURE),
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

QUANTITIES: Mapping[str, Entry] = _entries(
    Entry(name="stall_current", kind="current", source=WORKLOAD),
    Entry(name="current_draw", kind="current", source=FIXTURES),
    Entry(name="current_limit", kind="current", source=FIXTURES),
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
        name="rated_output_power",
        kind="power",
        source="a bench or mains power supply's rated output, as its datasheet states it",
    ),
    Entry(name="mass", kind="mass", source=WORKLOAD),
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


class Relation(_Frozen):
    """A relation between quantities that the checks evaluate over the graph.

    ``judged_by`` is the check that decides whether it holds; ``None`` means the
    unit check makes sure its two sides can be compared and no check among the
    gate's judges the comparison itself.
    """

    name: _Text
    statement: _Text
    judged_by: Literal[3, 4, 5, 6] | None
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
                name="current_limit",
                statement="a consumer's stall current is at most its supply's current limit",
                judged_by=None,
                source="a driver's rated output current bounds the load it can carry",
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


#: What makes a node a declared source of power, and why. A node that supplies
#: power is one of these, or it draws what it supplies from a supply upstream;
#: otherwise any module could become a source by dropping its upstream edge and
#: its draw.
SOURCES: Mapping[str, str] = MappingProxyType(
    {
        "energy_capacity": "a battery: it declares the energy it stores",
        "rated_output_power": "a bench or mains supply: it declares its rated output",
    }
)


def kind_of(name: str) -> Kind | None:
    """The kind of the quantity called ``name``, or ``None`` if the catalogue does not know it."""
    entry = QUANTITIES.get(name)
    return KINDS[entry.kind] if entry is not None else None


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
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
