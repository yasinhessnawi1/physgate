"""M-198: the decomposition prompt gains the widened catalogue's names and kinds, and no more.

The prompt's catalogue sentence is generated from the catalogue: every catalogued name, grouped by
its kind with the kind's unit. The widening adds five names (``torque_constant``,
``motor_resistance``, ``update_rate``, ``sensitivity_peak``, ``gain_margin``) and moves
``bore_diameter`` from a length to an extent, so the sentence gains four kind labels (a torque
constant, a resistance, a modulus and an extent) and ``update_rate`` among the frequencies. The
suffixes, the qualifiers and the signs never reach the prompt, and no envelope or range is added,
so the bounds and relations sentences, and every other byte of the prompt, stay as they were sent
at a64e805f. The new kinds with no catalogued name (an area, a moment of inertia, a duration, a
velocity), reached by suffixes only, get no label.

One more sentence moves, with the check round (04.11.2026, finding C3): the sentence after the
groups said that a name adding words to a catalogued one "is another quantity to the gate and goes
unchecked". With the qualifier words that is untrue: ``duty_cycle_max`` = 1.5 is refused by its
duty cycle's envelope, and ``stall_current_max`` has its unit and sign read. The sentence now says
what the gate does: such a name joins no relation and no range by name, and where the added words
are the closed qualifier list, generated from the catalogue, its unit, its sign and its kind's
definitional bound are read as the quantity's. So the qualifier words reach the prompt; the
suffixes and the signs still do not.

The order of the groups follows the catalogue's kinds, and of the names its entries: where the fix
puts a row is its choice, so the groups are compared as sets here, and the new prompt digests are
pinned with the fix.
"""

from __future__ import annotations

import hashlib

import pytest

from physgate import roles
from physgate.gate.catalogue import QUALIFIERS
from physgate.orchestrator.decompose import (
    bounds_sentence,
    catalogue_sentence,
    prompt_for,
    relations_sentence,
)

#: The bytes pinned here are the prompt with no law in the table: a promoted law adds its
#: own paragraph, which the law prompt's tests pin against the table in this checkout.
pytestmark = pytest.mark.usefixtures("no_law_table")

BRIEF = "Build a robot."

#: The catalogue sentence's frame: the words around the groups.
HEAD = (
    "The physics gate checks a quantity only under its catalogue name, in a unit of its kind. "
    "Wherever a node holds one of these quantities, and wherever a specification names one, it "
    "is named so: "
)
#: The words after the groups at a64e805f.
BASE_TAIL = (
    ". A name that adds words to one of them is another quantity to the gate and goes unchecked; "
    "where a node holds two values of one (a rating and the value the design runs at), the one it "
    "runs at takes the catalogue name."
)
#: The closed qualifier list, in the catalogue's order.
QUALIFIER_WORDS = (
    "_max, _min, _nominal, _measured, _applied, _bound, _budget, _typical, _lower, _upper, "
    "_implied, _estimated, _indicative"
)
#: The words after the groups since the check round (C3).
TAIL = (
    ". A name that adds words to one of them is not that quantity to the gate: it joins no "
    "relation and no range by name. Where the added words end the name and only say which value "
    f"of the quantity it is ({QUALIFIER_WORDS}), its unit, its sign and any bound its kind has by "
    "definition are still read as that quantity's; where a node holds two values of one (a rating "
    "and the value the design runs at), the one it runs at takes the catalogue name."
)

#: The groups at a64e805f in the order the sentence gave them, for rebuilding its bytes.
BASE_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("current (A)", ("stall_current", "current_draw", "current_limit")),
    ("voltage (V)", ("supply_voltage", "rated_voltage")),
    (
        "power (W)",
        (
            "power_draw",
            "power_supply",
            "input_power",
            "output_power",
            "heat_dissipation",
            "heat_rejection_capacity",
            "max_discharge_power",
            "rated_output_power",
        ),
    ),
    ("energy (J)", ("energy_capacity",)),
    ("mass (kg)", ("mass", "supported_mass")),
    ("length (m)", ("step_peak", "support_position", "mount_position", "bore_diameter")),
    ("force (N)", ("reaction_force", "load_force")),
    ("torque (N*m)", ("reaction_moment", "stall_torque", "torque_peak")),
    ("frequency (Hz)", ("sample_rate", "output_data_rate")),
    ("angular velocity (rad/s)", ("gain_crossover_frequency", "no_load_speed")),
    ("angle (rad)", ("phase_margin",)),
    ("time (s)", ("delay_margin",)),
    ("temperature (K)", ("max_temperature", "ambient_temperature")),
    ("temperature difference (K)", ("thermal_margin",)),
    ("thermal resistance (K/W)", ("thermal_resistance",)),
    ("dimensionless", ("gear_ratio", "external_gear_ratio", "loop_gain")),
    ("efficiency", ("efficiency",)),
    ("duty cycle", ("duty_cycle",)),
)

#: The groups at a64e805f, label to names.
BASE_GROUPS: dict[str, set[str]] = {label: set(names) for label, names in BASE_ORDER}

#: The groups the widening gives.
WIDENED_GROUPS: dict[str, set[str]] = {
    **BASE_GROUPS,
    "length (m)": {"step_peak", "support_position", "mount_position"},
    "extent (m)": {"bore_diameter"},
    "frequency (Hz)": {"sample_rate", "output_data_rate", "update_rate"},
    "resistance (ohm)": {"motor_resistance"},
    "torque constant (N*m/A)": {"torque_constant"},
    "modulus": {"sensitivity_peak", "gain_margin"},
}

#: The catalogue sentence at a64e805f, and its digest.
BASE_SENTENCE_SHA256 = "51d1c3cfde75a685101a218d9edbe8a16766cbc8ebc6435f6f8ca03ca1de91c9"
#: The bounds and relations sentences at a64e805f: the widening adds no bound and no relation.
BOUNDS_SENTENCE_SHA256 = "734a3fa97a18af153fa3c00b5d5ebfff79834308e21d9ac41bb99b597932ab20"
RELATIONS_SENTENCE_SHA256 = "1bdb67adb3a55d9d8c239bb451e48f82264b08b5c5942a44dbcbe06159f7ebe5"
#: The prompt for ``BRIEF`` at a64e805f, per set of roles (the pins of
#: test_without_the_cross_cutting_roles_the_decomposition_is_sent_as_before at a64e805f).
BASE_PROMPT_SHA256 = {
    ("control", "firmware"): "dd56ee830053b0132c75fbcef564b9faa67c8adc3f346dc3a632d2b408c86f8d",
    ("electrical",): "eefd8ba42c142622f94f59d3c2cd41f4ec77b8e6c9d68b82978a402f354e2528",
    (
        "control",
        "electrical",
        "firmware",
        "mechanical",
    ): "a0d39189207269a4faf7e1fa644d4dd8c91a2fa8feffbfb280f84d1ceb6fef5c",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _base_sentence() -> str:
    """The catalogue sentence at a64e805f, rebuilt from its groups in the order it had."""
    groups = "; ".join(f"{label}: {', '.join(names)}" for label, names in BASE_ORDER)
    return f"{HEAD}{groups}{BASE_TAIL}"


def _groups(sentence: str, tail: str = TAIL) -> dict[str, set[str]]:
    assert sentence.startswith(HEAD) and sentence.endswith(tail), sentence
    body = sentence[len(HEAD) : -len(tail)]
    groups: dict[str, set[str]] = {}
    for group in body.split("; "):
        label, _, names = group.partition(": ")
        assert label not in groups, label
        groups[label] = set(names.split(", "))
    return groups


@pytest.fixture
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register with sizing in it, as it ships."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def test_the_base_sentence_is_rebuilt_byte_for_byte() -> None:
    # Guard: the rebuild below is a64e805f's sentence, so the comparisons stand on it.
    assert _sha(_base_sentence()) == BASE_SENTENCE_SHA256
    assert _groups(_base_sentence(), BASE_TAIL) == BASE_GROUPS


def test_the_catalogue_sentence_gains_the_new_names_and_kind_labels_and_nothing_else() -> None:
    assert _groups(catalogue_sentence()) == WIDENED_GROUPS


def test_the_added_words_sentence_says_what_the_gate_reads_of_such_a_name() -> None:
    sentence = catalogue_sentence()
    assert sentence.endswith(TAIL), sentence[-700:]
    assert "goes unchecked" not in sentence


def test_the_qualifier_words_in_the_prompt_are_the_catalogue_s_own() -> None:
    # Generated from the catalogue, so the prompt names exactly the words the gate strips.
    assert ", ".join(QUALIFIERS) == QUALIFIER_WORDS
    assert f"({QUALIFIER_WORDS})" in catalogue_sentence()


def test_the_bounds_and_relations_sentences_are_unchanged() -> None:
    # Guard: no envelope, range or relation is added.
    assert _sha(bounds_sentence()) == BOUNDS_SENTENCE_SHA256
    assert _sha(relations_sentence()) == RELATIONS_SENTENCE_SHA256


@pytest.mark.parametrize("run_roles", sorted(BASE_PROMPT_SHA256), ids=", ".join)
def test_every_other_byte_of_the_prompt_is_as_it_was(
    run_roles: tuple[str, ...], sizing_registered: None
) -> None:
    # Guard: with the catalogue sentence put back as it was, the prompt is a64e805f's.
    prompt = prompt_for(BRIEF, run_roles)
    assert prompt.count(catalogue_sentence()) == 1
    assert (
        _sha(prompt.replace(catalogue_sentence(), _base_sentence()))
        == (BASE_PROMPT_SHA256[run_roles])
    )
