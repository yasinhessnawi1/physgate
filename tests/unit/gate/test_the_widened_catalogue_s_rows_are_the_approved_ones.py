"""M-198, the table rows: the catalogue widened by definitions alone, and by nothing else.

The owner approved the widening on 04.11.2026, in the scope of the research's section 6
(``CATALOGUE_WIDEN_research.md``), as ruled at the red rows' review the same day: eight new
kinds, each sign from a definition or a law and never from a product class, and each reached by
a name or a suffix; temperature and frequency never negative; five new exact names, and
``bore_diameter`` read as an extent; the new suffixes that reach a value G11 run 4 wrote, and
``_utilization``, the spelling twin of ``_utilisation`` (one meaning, so no new reach). Held
back, and pinned here as held back: the inductance and capacitance kinds (no name or suffix
would reach them, so they would only move the digest), the ``max_duty`` name, the suffixes no
run-4 value reaches (``_inductance``, ``_capacitance``, ``_winding_resistance``,
``_terminal_resistance``, ``_armature_resistance``), the ``_diameter`` and ``_thickness``
re-kinds, a kind with the radian to the power -1, an alias, and any new envelope or range.

Every row is pinned against the catalogue at a64e805f (digest ``3da50073...``), so a row that is
added, dropped or changed without a ruling turns this red. The rules for an envelope kind's
suffixes are here too: a suffix reaches a kind whose span is a definition only where its words
leave the name one meaning, which one word rarely does (``_duty`` would have read run 4's
``stall_current_full_duty`` as a duty cycle).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import (
    KINDS,
    QUANTITIES,
    SUFFIXES,
    Kind,
    catalogue_digest,
    kind_of,
)
from physgate.gate.laws import load_laws
from physgate.state.vocabulary import QUANTITY_NAMES

#: The catalogue's digest at a64e805f, before the widening, and with it: the rows below, the
#: closed qualifier list and, since the check round (04.11.2026), what is read at either power of
#: the radian (EITHER_ANGLE: _frequency, and torque_constant for Ke). At 470b3f34, without
#: EITHER_ANGLE: 87ff47377cf8....
BASE_DIGEST = "3da500738f1e5a3fe3e523bf1e9fcd6fb689f1a3fe6ec1870d1cda6acf4324f7"
WIDENED_DIGEST = "0ec405db80746115a88db9676f737661030b62ef6a080c8e444746a63ebd4edd"

#: Every kind at a64e805f: (canonical unit, radian power, shape, absolute, sign).
BASE_KINDS: dict[str, tuple[str, int, str | None, bool, str]] = {
    "current": ("A", 0, None, False, "any"),
    "voltage": ("V", 0, None, False, "any"),
    "power": ("W", 0, None, False, "nonnegative"),
    "energy": ("J", 0, "energy", False, "positive"),
    "mass": ("kg", 0, None, False, "nonnegative"),
    "length": ("m", 0, None, False, "any"),
    "force": ("N", 0, None, False, "any"),
    "torque": ("N*m", 0, "force*length", False, "any"),
    "frequency": ("Hz", 0, None, False, "any"),
    "angular_velocity": ("rad/s", 1, None, False, "any"),
    "angle": ("rad", 1, None, False, "any"),
    "time": ("s", 0, None, False, "any"),
    "temperature": ("K", 0, None, True, "any"),
    "temperature_difference": ("K", 0, None, False, "any"),
    "thermal_resistance": ("K/W", 0, None, False, "positive"),
    "dimensionless": ("dimensionless", 0, None, False, "any"),
    "efficiency": ("dimensionless", 0, None, False, "nonnegative"),
    "duty_cycle": ("dimensionless", 0, None, False, "nonnegative"),
}

#: The eight new kinds (research section 3a, without the inductance and the capacitance), in the
#: same form.
NEW_KINDS: dict[str, tuple[str, int, str | None, bool, str]] = {
    "resistance": ("ohm", 0, None, False, "nonnegative"),
    "moment_of_inertia": ("kg*m**2", 0, None, False, "nonnegative"),
    "area": ("m**2", 0, None, False, "nonnegative"),
    "extent": ("m", 0, None, False, "nonnegative"),
    "duration": ("s", 0, None, False, "nonnegative"),
    "velocity": ("m/s", 0, None, False, "any"),
    "torque_constant": ("N*m/A", 0, None, False, "any"),
    "modulus": ("dimensionless", 0, None, False, "nonnegative"),
}

#: The two sign edits: a thermodynamic temperature and a frequency are never negative.
SIGN_EDITS = {"temperature": "nonnegative", "frequency": "nonnegative"}

#: Every catalogued name at a64e805f, and its kind.
BASE_ENTRIES: dict[str, str] = {
    "stall_current": "current",
    "current_draw": "current",
    "current_limit": "current",
    "supply_voltage": "voltage",
    "rated_voltage": "voltage",
    "power_draw": "power",
    "power_supply": "power",
    "input_power": "power",
    "output_power": "power",
    "heat_dissipation": "power",
    "heat_rejection_capacity": "power",
    "energy_capacity": "energy",
    "max_discharge_power": "power",
    "rated_output_power": "power",
    "mass": "mass",
    "supported_mass": "mass",
    "gear_ratio": "dimensionless",
    "external_gear_ratio": "dimensionless",
    "phase_margin": "angle",
    "gain_crossover_frequency": "angular_velocity",
    "delay_margin": "time",
    "step_peak": "length",
    "support_position": "length",
    "mount_position": "length",
    "bore_diameter": "length",
    "reaction_force": "force",
    "load_force": "force",
    "reaction_moment": "torque",
    "stall_torque": "torque",
    "torque_peak": "torque",
    "sample_rate": "frequency",
    "output_data_rate": "frequency",
    "efficiency": "efficiency",
    "duty_cycle": "duty_cycle",
    "no_load_speed": "angular_velocity",
    "max_temperature": "temperature",
    "ambient_temperature": "temperature",
    "thermal_margin": "temperature_difference",
    "thermal_resistance": "thermal_resistance",
    "loop_gain": "dimensionless",
}

#: The five new exact names (``max_duty`` is held back), and the one name that changes kind.
NEW_ENTRIES = {
    "torque_constant": "torque_constant",
    "motor_resistance": "resistance",
    "update_rate": "frequency",
    "sensitivity_peak": "modulus",
    "gain_margin": "modulus",
}
ENTRY_KIND_CHANGES = {"bore_diameter": "extent"}

#: The suffixes at a64e805f. ``_diameter`` and ``_thickness`` stay lengths (their re-kind is held
#: back), and ``_radius`` stays a length because a radius of curvature is signed.
BASE_SUFFIXES = {
    "_voltage": "voltage",
    "_mass": "mass",
    "_force": "force",
    "_torque": "torque",
    "_frequency": "frequency",
    "_diameter": "length",
    "_radius": "length",
    "_thickness": "length",
    "_efficiency": "efficiency",
    "_duty_cycle": "duty_cycle",
}

#: The 24 new suffixes: each one but ``_utilization`` reaches at least one of run 4's values, as
#: the name's last words or once its qualifiers are stripped (the run-4 test holds that);
#: ``_utilization`` is ``_utilisation``'s spelling twin, one meaning in two spellings.
NEW_SUFFIXES = {
    "_period": "duration",
    "_duration": "duration",
    "_latency": "duration",
    "_age": "duration",
    "_delay": "time",
    "_lateness": "time",
    "_time": "time",
    "_delay_margin": "time",
    "_phase_margin": "angle",
    "_inertia": "moment_of_inertia",
    "_area": "area",
    "_ground_speed": "velocity",
    "_stall_current": "current",
    "_no_load_current": "current",
    "_motor_current": "current",
    "_no_load_speed": "angular_velocity",
    "_gain_crossover_frequency": "angular_velocity",
    "_gear_ratio": "dimensionless",
    "_output_data_rate": "frequency",
    "_sensitivity_peak": "modulus",
    "_spectral_radius": "modulus",
    "_gain_margin": "modulus",
    "_utilisation": "modulus",
    "_utilization": "modulus",
}

#: Suffixes that stay out: no run-4 value reaches them (held back by the ruling), they were
#: tried and refuted by a run-4 value (``_duty``, ``_angle``, ``_tilt``), or the 19.10 rule
#: excludes them as words with more than one meaning.
HELD_BACK_SUFFIXES = (
    "_inductance",
    "_capacitance",
    "_winding_resistance",
    "_terminal_resistance",
    "_armature_resistance",
    "_duty",
    "_angle",
    "_tilt",
    "_resistance",
    "_current",
    "_rate",
    "_ratio",
    "_fraction",
)

#: The one suffix of one word under an envelope kind, and why it stands although the rule below
#: would not admit it: it was approved on 03.11.2026, a day before the rule was written, with its
#: limit named then. An efficiency is a fraction by definition, but the last word is not always
#: the quantity: a forced-induction engine's volumetric efficiency is correctly above 1, and the
#: envelope refuses it under this suffix. The exception is named here, so no other one-word suffix
#: can join an envelope kind without this test going red.
ONE_WORD_ENVELOPE_SUFFIXES_BEFORE_THE_RULE = frozenset({"_efficiency"})

#: Kinds the research proposed and the ruling held back: no name or suffix in the set reaches
#: them, so each would move the digest and check nothing.
HELD_BACK_KINDS = ("inductance", "capacitance", "back_emf_constant")


def _row(kind: Kind) -> tuple[str, int, str | None, bool, str]:
    return (kind.canonical, kind.angle, kind.shape, kind.absolute, kind.sign)


def test_the_eight_new_kinds_are_the_approved_ones_each_with_a_source() -> None:
    added = {name: _row(kind) for name, kind in KINDS.items() if name not in BASE_KINDS}
    assert added == NEW_KINDS
    assert all(KINDS[name].source for name in NEW_KINDS)


def test_a_temperature_and_a_frequency_are_never_negative() -> None:
    assert {name: KINDS[name].sign for name in SIGN_EDITS} == SIGN_EDITS
    # An absolute temperature stays the one kind an offset unit may be written in.
    assert KINDS["temperature"].absolute


def test_no_other_kind_changes() -> None:
    # Guard: only the two sign edits touch a kind that was there.
    for name, row in BASE_KINDS.items():
        got = _row(KINDS[name])
        # A sign edit's sign is the test above's; the rest of its row stays.
        assert (got[:4] if name in SIGN_EDITS else got) == (row[:4] if name in SIGN_EDITS else row)


def test_the_five_new_names_and_bore_diameter_s_new_kind() -> None:
    assert {name: QUANTITIES[name].kind for name in NEW_ENTRIES if name in QUANTITIES} == (
        NEW_ENTRIES
    )
    assert QUANTITIES["bore_diameter"].kind == "extent"
    assert all(QUANTITIES[name].source for name in NEW_ENTRIES)


def test_the_catalogue_s_names_are_the_base_ones_and_the_new_ones_and_nothing_else() -> None:
    assert {name: entry.kind for name, entry in QUANTITIES.items()} == {
        **BASE_ENTRIES,
        **ENTRY_KIND_CHANGES,
        **NEW_ENTRIES,
    }


@pytest.mark.parametrize(
    "name", ["max_duty", "back_emf_constant", "duty_cycle_max", "max_duty_cycle"]
)
def test_the_held_back_names_are_not_catalogued(name: str) -> None:
    # Guard: max_duty goes into the standards as duty_cycle; the radian -1 kind is held back.
    assert name not in QUANTITIES and name not in QUANTITY_NAMES


@pytest.mark.parametrize("kind", HELD_BACK_KINDS)
def test_a_held_back_kind_is_not_in_the_catalogue(kind: str) -> None:
    # Guard.
    assert kind not in KINDS


def test_every_new_kind_is_reached_by_a_name_or_a_suffix() -> None:
    # A kind nothing reaches checks nothing and only moves the digest.
    reached = {e.kind for e in QUANTITIES.values()} | {s.kind for s in SUFFIXES}
    assert set(NEW_KINDS) <= set(KINDS)
    assert set(NEW_KINDS) - reached == set()


def test_utilization_reads_as_utilisation_does() -> None:
    assert kind_of("cpu_utilization") is kind_of("cpu_utilisation") is KINDS.get("modulus")
    assert kind_of("cpu_utilization") is not None


def test_the_suffix_list_is_the_approved_closed_list() -> None:
    assert {s.suffix: s.kind for s in SUFFIXES} == {**BASE_SUFFIXES, **NEW_SUFFIXES}
    assert len(SUFFIXES) == len({s.suffix for s in SUFFIXES}) == 34
    assert all(s.kind in KINDS and s.source for s in SUFFIXES)


@pytest.mark.parametrize("suffix", HELD_BACK_SUFFIXES)
def test_a_held_back_suffix_is_not_in_the_list(suffix: str) -> None:
    # Guard.
    assert suffix not in {s.suffix for s in SUFFIXES}


def test_an_envelope_kind_is_reached_only_by_exact_names_or_suffixes_of_two_or_more_words() -> None:
    # Guard (research section 5, risk 1): a one-word suffix under a kind whose span refuses
    # would refuse a correct value of another quantity that ends in the same word.
    envelopes = set(load_bounds().envelopes)
    assert envelopes, "the rule is vacuous without an envelope"
    short = {
        s.suffix
        for s in SUFFIXES
        if s.kind in envelopes and len(s.suffix.strip("_").split("_")) < 2
    }
    assert short <= ONE_WORD_ENVELOPE_SUFFIXES_BEFORE_THE_RULE


def test_no_new_envelope_and_no_new_or_aliased_range() -> None:
    # Guard: no product-class span, and no alias reads a name under another's range.
    bounds = load_bounds()
    assert set(bounds.envelopes) == {"efficiency", "duty_cycle"}
    assert {d: sorted(t.ranges) for d, t in bounds.tables.items() if t.ranges} == {
        "electrical": ["output_data_rate", "sample_rate"],
        "firmware": ["output_data_rate"],
    }


def test_a_kind_with_the_radian_to_the_power_minus_one_is_still_refused() -> None:
    # Guard: the back-EMF constant's kind (V*s/rad) is held back.
    with pytest.raises(ValidationError):
        Kind(name="back_emf_constant", canonical="V*s/rad", angle=-1, source="a test")  # type: ignore[arg-type]
    assert kind_of("back_emf_constant") is None


def test_the_hook_s_vocabulary_holds_the_new_names() -> None:
    assert set(NEW_ENTRIES) <= set(QUANTITY_NAMES)
    assert tuple(sorted(QUANTITIES)) == QUANTITY_NAMES


def test_the_catalogue_digest_moves_off_a64e805f_s() -> None:
    assert catalogue_digest(load_laws()) != BASE_DIGEST
    assert catalogue_digest(load_laws()) == WIDENED_DIGEST
