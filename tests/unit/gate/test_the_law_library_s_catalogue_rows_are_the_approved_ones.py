"""The law library's catalogue rows: the twelve names and the one kind the owner approved, no more.

The laws drafted next read names the catalogue lacked: a motor's rated stall and the voltage its
stall is stated at, a control model's plant mass, a train's overall ratio and its wheel's no-load
speed, encoder counts per shaft, a store's rated charge, a part's absolute maximum voltage, a
motor's no-load current and a battery's discharge time. Each was drafted from a source, reviewed
twice on another model and approved by the owner, by its definition. The owner also settled which
voltage a stall is taken at by keeping both, under two names: ``stall_current``, at the command
limit's duty times the supply's highest voltage, which the design sizes for, and
``peak_stall_current``, at full duty and the same voltage, which a driver's peak rating and a
fuse are judged against. Each name's definition states the other, so neither can drift.

A name's definition reaches no writer through the prompt, which lists names and units only, so
each one is written beside its row: in the new rows' sources, and as comments above the existing
names whose definitions the owner corrected (``stall_current``, ``supply_voltage``,
``no_load_speed``, ``stall_torque``, ``rated_voltage``), whose rows are unchanged.

Every row is pinned here, so a row added, dropped or changed without a ruling turns this red;
the names the reviews dropped or deferred, and the first drafts' spellings, stay out.
"""

from __future__ import annotations

import inspect
import re

import pytest
from law_library_names import FOR_LAWS, KIND, KIND_ROW, LEFT_OUT, NAMES
from pint.errors import DimensionalityError

import physgate.gate.catalogue as catalogue
from physgate.gate.catalogue import KINDS, QUANTITIES, RELATION_NAMES, Kind, catalogue_digest
from physgate.gate.laws import load_laws
from physgate.gate.units import UnitRefusedError, measure
from physgate.state.vocabulary import QUANTITY_NAMES, RELATION_QUANTITY_NAMES

#: The catalogue's digest with no law, before these rows (the widened catalogue's) and with them.
#: With the five laws the table held when the rows landed: a5351dcb... before, 201c855a... after.
#: Since check 4 gained the peak headroom relation (07.11.2026); with the rows alone, 3014ed68....
WIDENED_DIGEST = "0ec405db80746115a88db9676f737661030b62ef6a080c8e444746a63ebd4edd"
LAW_LIBRARY_DIGEST = "9d26cbdb61bfabf988ab6209a7acc4c25101716bfdad5f517c1e59df233f15e3"


def _new_kind() -> Kind:
    kind = KINDS.get(KIND)
    assert kind is not None, f"the catalogue has no {KIND} kind"
    return kind


def _comment_above(name: str) -> str:
    """The comment lines directly above the catalogue row for ``name``, joined."""
    lines = inspect.getsource(catalogue).splitlines()
    row = next((i for i, line in enumerate(lines) if f'Entry(name="{name}"' in line), None)
    assert row is not None, f"no catalogue row for {name}"
    above: list[str] = []
    for line in reversed(lines[:row]):
        stripped = line.strip()
        if not stripped.startswith("#"):
            break
        above.insert(0, stripped.lstrip("#:").strip())
    return " ".join(above)


def test_the_new_kind_is_a_charge_capacity_in_coulombs_never_negative() -> None:
    kind = _new_kind()
    assert (kind.canonical, kind.angle, kind.shape, kind.absolute, kind.sign) == KIND_ROW
    assert "never negative" in kind.source
    # Guard: a signed charge is another quantity, so the plain word stays free for it.
    assert "charge" not in KINDS


def test_each_approved_name_has_its_kind_and_its_definition() -> None:
    got = {name: QUANTITIES[name].kind for name in NAMES if name in QUANTITIES}
    assert got == NAMES
    assert all(len(QUANTITIES[name].source) > 80 for name in NAMES)


@pytest.mark.parametrize("name", LEFT_OUT)
def test_a_name_the_reviews_left_out_is_not_catalogued(name: str) -> None:
    # Guard: dropped, deferred, or the first drafts' spelling of a renamed row.
    assert name not in QUANTITIES and name not in QUANTITY_NAMES


def test_the_hook_s_vocabulary_holds_every_new_name() -> None:
    assert set(NAMES) <= set(QUANTITY_NAMES)
    assert tuple(sorted(QUANTITIES)) == QUANTITY_NAMES


def test_the_names_the_next_laws_read_are_guarded_by_the_gate_and_the_hooks() -> None:
    assert sorted(FOR_LAWS - set(RELATION_NAMES)) == []
    assert sorted(FOR_LAWS - set(RELATION_QUANTITY_NAMES)) == []


def test_the_two_stalls_each_state_the_other() -> None:
    peak = QUANTITIES["peak_stall_current"].source if "peak_stall_current" in QUANTITIES else ""
    # The peak's definition names its condition and its pair, stall_current itself.
    assert "full duty" in peak and "highest voltage" in peak, peak
    assert re.search(r"(?<!peak_)\bstall_current\b", peak), peak
    assert "never written one for the other" in peak, peak
    # stall_current's definition, beside its row, names its condition and the peak.
    operating = _comment_above("stall_current")
    assert "peak_stall_current" in operating, operating
    assert "duty" in operating and "highest voltage" in operating, operating
    assert "never written one for the other" in operating, operating


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("stall_current", "stall_voltage"),
        ("supply_voltage", "the rail a node is connected to"),
        ("no_load_speed", "the output shaft of the motor as bought"),
        ("stall_torque", "the output shaft of the motor as bought"),
        ("rated_voltage", "not a maximum"),
    ],
)
def test_a_corrected_definition_is_written_beside_its_row(name: str, words: str) -> None:
    assert words in _comment_above(name)


@pytest.mark.parametrize(
    ("value", "unit"),
    [(2200, "mA*h"), (2.2, "A*h"), (2200, "mAh"), (2.2, "Ah"), (7920, "C"), (0, "A*h")],
)
def test_a_store_s_rated_charge_is_read_in_amp_hours_or_coulombs(value: float, unit: str) -> None:
    measured = measure(_new_kind(), value, unit)
    assert measured.kind.name == KIND


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        # a negative charge capacity: the sign rule
        (-1, "A*h"),
        # an energy written for a charge, the slip no other check sees
        (15.8, "W*h"),
        (15.8, "J"),
    ],
)
def test_a_negative_charge_or_an_energy_is_refused_as_a_charge_capacity(
    value: float, unit: str
) -> None:
    kind = _new_kind()
    refused = False
    try:
        measure(kind, value, unit)
    except (UnitRefusedError, DimensionalityError):
        refused = True
    assert refused, f"{value} {unit} was read as a {KIND}"


@pytest.mark.usefixtures("no_law_table")
def test_the_catalogue_digest_moves_off_the_widened_catalogue_s() -> None:
    assert catalogue_digest(load_laws()) != WIDENED_DIGEST
    assert catalogue_digest(load_laws()) == LAW_LIBRARY_DIGEST
