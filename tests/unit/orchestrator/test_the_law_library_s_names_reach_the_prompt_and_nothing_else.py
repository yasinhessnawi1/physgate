"""The decomposition prompt gains the law library's twelve names and two kind labels, and no more.

The prompt's catalogue sentence is generated from the catalogue: every catalogued name, grouped by
its kind with the kind's unit. The law library's rows (07.11.2026) add twelve names. Ten join
groups the sentence already has (three currents, two voltages, a mass, three dimensionless
counts and ratios, an angular velocity); two bring a kind label of their own: ``charge_capacity``
under the new charge capacity kind, in coulombs, and ``discharge_time`` under the duration kind,
which until now no catalogued name held. The rows add no relation, no bound and no qualifier, so
the bounds sentence, and every byte outside the catalogue and relations sentences, is as it was
(the widening's own test holds those against the sentence it sent). The relations sentence gains
one statement, the peak headroom check 4 judges where a node holds ``peak_stall_current``.

A name's definition does not reach the prompt: the sentence lists names and units only.
"""

from __future__ import annotations

import hashlib

import pytest
from law_library_names import NAMES

from physgate.orchestrator.decompose import bounds_sentence, catalogue_sentence, relations_sentence

pytestmark = pytest.mark.usefixtures("no_law_table")

#: The catalogue sentence's frame: the words before the groups, and the first words after them.
HEAD = "it is named so: "
AFTER = ". A name that adds words to one of them is not that quantity to the gate"

#: The groups the widened catalogue gave, label to names.
WIDENED: dict[str, set[str]] = {
    "current (A)": {"stall_current", "current_draw", "current_limit"},
    "voltage (V)": {"supply_voltage", "rated_voltage"},
    "resistance (ohm)": {"motor_resistance"},
    "power (W)": {
        "power_draw",
        "power_supply",
        "input_power",
        "output_power",
        "heat_dissipation",
        "heat_rejection_capacity",
        "max_discharge_power",
        "rated_output_power",
    },
    "energy (J)": {"energy_capacity"},
    "mass (kg)": {"mass", "supported_mass"},
    "length (m)": {"step_peak", "support_position", "mount_position"},
    "extent (m)": {"bore_diameter"},
    "force (N)": {"reaction_force", "load_force"},
    "torque (N*m)": {"reaction_moment", "stall_torque", "torque_peak"},
    "torque constant (N*m/A)": {"torque_constant"},
    "frequency (Hz)": {"sample_rate", "output_data_rate", "update_rate"},
    "angular velocity (rad/s)": {"gain_crossover_frequency", "no_load_speed"},
    "angle (rad)": {"phase_margin"},
    "time (s)": {"delay_margin"},
    "temperature (K)": {"max_temperature", "ambient_temperature"},
    "temperature difference (K)": {"thermal_margin"},
    "thermal resistance (K/W)": {"thermal_resistance"},
    "dimensionless": {"gear_ratio", "external_gear_ratio", "loop_gain"},
    "modulus": {"sensitivity_peak", "gain_margin"},
    "efficiency": {"efficiency"},
    "duty cycle": {"duty_cycle"},
}

#: What the law library's rows add, by group.
ADDED: dict[str, set[str]] = {
    "current (A)": {"rated_stall_current", "peak_stall_current", "no_load_current"},
    "voltage (V)": {"stall_voltage", "absolute_maximum_voltage"},
    "mass (kg)": {"plant_mass"},
    "dimensionless": {
        "overall_gear_ratio",
        "counts_per_motor_revolution",
        "counts_per_wheel_revolution",
    },
    "angular velocity (rad/s)": {"no_load_speed_wheel"},
    "charge capacity (C)": {"charge_capacity"},
    "duration (s)": {"discharge_time"},
}

#: The bounds sentence as the widened catalogue sent it, and the relations sentence since check 4
#: gained the peak headroom (07.11.2026): one statement more, the peak stall current against the
#: current limit. Before it: 1bdb67adb3a5....
BOUNDS_SENTENCE_SHA256 = "734a3fa97a18af153fa3c00b5d5ebfff79834308e21d9ac41bb99b597932ab20"
RELATIONS_SENTENCE_SHA256 = "4d5dacfd6a12b65e9da511d4e5295564971a012bb2dd2d41e531745b2a9612c4"


def _groups(sentence: str) -> dict[str, set[str]]:
    assert HEAD in sentence and AFTER in sentence, sentence
    body = sentence.split(HEAD, 1)[1].split(AFTER, 1)[0]
    groups: dict[str, set[str]] = {}
    for group in body.split("; "):
        label, _, names = group.partition(": ")
        assert label not in groups, label
        groups[label] = set(names.split(", "))
    return groups


def test_the_added_names_are_the_law_library_s_twelve() -> None:
    # Guard: the groups below spell every approved name once.
    assert {n for names in ADDED.values() for n in names} == set(NAMES)


def test_the_catalogue_sentence_gains_the_twelve_names_and_two_kind_labels() -> None:
    expected = {label: set(names) for label, names in WIDENED.items()}
    for label, names in ADDED.items():
        expected.setdefault(label, set()).update(names)
    assert _groups(catalogue_sentence()) == expected


def test_no_definition_reaches_the_prompt() -> None:
    # The sentence names and units only: a definition is the standards' to teach.
    assert "full duty" not in catalogue_sentence()
    assert "never written one for the other" not in catalogue_sentence()


def test_the_bounds_sentence_is_unchanged_and_the_relations_gain_the_peak_headroom() -> None:
    assert hashlib.sha256(bounds_sentence().encode()).hexdigest() == BOUNDS_SENTENCE_SHA256
    assert hashlib.sha256(relations_sentence().encode()).hexdigest() == RELATIONS_SENTENCE_SHA256
