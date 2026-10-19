"""Check 1, names the catalogue lacks: a closed list of suffixes gives a reading, never a refusal.

A writer can step out of every relation and range by inventing a name (``battery_voltage``
for ``supply_voltage``). The catalogue cannot know every name, but a name ending in a word
with one meaning in mechatronics (``_voltage``, ``_mass``, ``_force``, ``_torque``,
``_frequency``, ``_diameter``, ``_radius``, ``_thickness``) is read against that word's
dimension and sign, and the record says whether they agree. The suffix is a reading of the
name, not the catalogue's, so a mismatch is recorded as **unchecked, naming the suffix, and
never refused**: a ``spring_force`` in newtons, a ``braking_torque`` written negative and a
``boost_voltage`` all pass through unrefused, and so does a ``pack_mass`` in watts, with the
mismatch on record. No relation forms from such a name and no range applies to it by name. A
word with more than one meaning (``_current``, which is also a loss in watts; ``_position``,
``_length``, ``_width`` and ``_height``, which are also counts, pulses and ratios;
``_temperature``, which is also a colour; ``_rate``, ``_power``, ``_ratio``, ``_capacity``)
infers nothing, so the list is closed and pinned here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import (
    KINDS,
    QUANTITIES,
    SUFFIXES,
    catalogue_digest,
    inferred_by,
    kind_of,
)
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import UncheckedDetails

NODE = "electrical.pack"


def run(tmp_path: Path, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))


def outcomes(ran: Any) -> list[str]:
    return [o.outcome for o in ran.observations]


def test_the_list_is_closed_and_every_suffix_has_one_kind_and_a_source() -> None:
    assert {s.suffix: s.kind for s in SUFFIXES} == {
        "_voltage": "voltage",
        "_mass": "mass",
        "_force": "force",
        "_torque": "torque",
        "_frequency": "frequency",
        "_diameter": "length",
        "_radius": "length",
        "_thickness": "length",
    }
    assert all(s.kind in KINDS and s.source for s in SUFFIXES)


@pytest.mark.parametrize(
    "name",
    [
        "loop_rate",
        "specific_power",
        "reduction_ratio",
        "charge_capacity",
        "winding_resistance",
        "eddy_current",
        "motor_current_draw",
        "servo_position",
        "word_length",
        "line_height",
        "pulse_width",
        "color_temperature",
        "delta_temperature",
        "stored_energy",
    ],
)
def test_a_word_with_more_than_one_meaning_infers_nothing(name: str) -> None:
    assert inferred_by(name) is None and kind_of(name) is None


def test_a_catalogued_name_keeps_its_entry_and_is_not_inferred() -> None:
    assert "supply_voltage" in QUANTITIES
    assert inferred_by("supply_voltage") is None
    assert kind_of("supply_voltage") is KINDS["voltage"]


def test_the_suffix_alone_is_not_a_name_and_the_word_must_end_the_name() -> None:
    assert kind_of("_voltage") is None
    assert kind_of("voltage") is None
    assert kind_of("voltage_divider_ratio") is None  # the word is inside, not at the end
    # The underscored word inside the name, with another word ending it: still nothing.
    assert kind_of("max_supply_voltage_drop") is None
    assert kind_of("pack_mass_fraction") is None
    assert kind_of("wheel_diameter_tolerance") is None


def test_a_suffix_word_inside_the_name_holds_it_to_nothing(tmp_path: Path) -> None:
    # A mass fraction is dimensionless and a voltage drop is small: a rule that matched
    # ``_mass`` or ``_voltage`` anywhere in the name would read both by the wrong kind.
    ran = run(
        tmp_path,
        node(
            NODE,
            quantities={
                "pack_mass_fraction": (0.3, "dimensionless"),
                "max_supply_voltage_drop": (0.5, "V"),
            },
        ),
    )
    (unknown,) = ran.observations
    assert unknown.outcome == "unchecked" and "does not know" in unknown.message
    assert isinstance(unknown.details, UncheckedDetails)
    assert unknown.details.quantities == ("max_supply_voltage_drop", "pack_mass_fraction")


def test_the_suffixes_are_part_of_the_catalogue_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    import physgate.gate.catalogue as catalogue

    before = catalogue_digest()
    monkeypatch.setattr(catalogue, "SUFFIXES", SUFFIXES[:-1])
    assert catalogue_digest() != before


def test_a_battery_voltage_written_in_watts_is_recorded_unchecked_naming_the_suffix(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, node(NODE, quantities={"battery_voltage": (2.4, "W")}))
    assert outcomes(ran) == ["unchecked", "unchecked"]
    mismatch = next(o for o in ran.observations if "is not what its suffix" in o.message)
    assert mismatch.node == NODE and "battery_voltage" in mismatch.message
    assert "_voltage" in mismatch.message and "refuses nothing" in mismatch.message
    assert isinstance(mismatch.details, UncheckedDetails)
    assert mismatch.details.quantities == ("battery_voltage",)


def test_a_board_thickness_in_kilograms_is_unchecked_and_one_in_millimetres_is_read(
    tmp_path: Path,
) -> None:
    wrong = run(tmp_path / "a", node(NODE, quantities={"board_thickness": (2, "kg")}))
    assert outcomes(wrong) == ["unchecked", "unchecked"]
    assert any("board_thickness" in o.message and "suffix" in o.message for o in wrong.observations)
    clean = run(tmp_path / "b", node(NODE, quantities={"board_thickness": (1.6, "mm")}))
    assert outcomes(clean) == ["unchecked"]
    assert "a mismatch is recorded as unchecked" in clean.observations[0].message


def test_a_negative_mass_under_an_invented_name_is_unchecked_not_refused(tmp_path: Path) -> None:
    ran = run(tmp_path, node(NODE, quantities={"pack_mass": (-0.2, "kg")}))
    assert outcomes(ran) == ["unchecked", "unchecked"]
    mismatch = next(o for o in ran.observations if "pack_mass of" in o.message)
    assert "never negative" in mismatch.message and "refuses nothing" in mismatch.message


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [
        ("spring_force", 5, "N"),
        ("braking_torque", -2, "N*m"),
        ("boost_voltage", 48, "V"),
        ("mains_voltage", 230, "V"),
        ("wheel_diameter", 70, "mm"),
        ("clock_frequency", 16, "MHz"),
    ],
)
def test_a_correct_figure_under_an_inferred_name_is_recorded_and_refused_by_nothing(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    ran = run(tmp_path, node(NODE, quantities={name: (value, unit)}))
    assert outcomes(ran) == ["unchecked"]
    assert name in ran.observations[0].message and "suffix" in ran.observations[0].message


def test_an_inferred_name_is_recorded_as_unchecked_for_everything_but_dimension_and_sign(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path, node(NODE, quantities={"coil_voltage": (0.5, "V"), "loop_rate": (50, "Hz")})
    )
    by_message = {o.message: o for o in ran.observations}
    inferred = next(o for m, o in by_message.items() if "coil_voltage" in m)
    unknown = next(o for m, o in by_message.items() if "loop_rate" in m)
    assert inferred is not unknown
    assert inferred.outcome == "unchecked" and "_voltage" in inferred.message
    assert "no relation" in inferred.message and "range" in inferred.message
    assert isinstance(inferred.details, UncheckedDetails)
    assert inferred.details.quantities == ("coil_voltage",)
    assert unknown.outcome == "unchecked" and "does not know" in unknown.message
    assert isinstance(unknown.details, UncheckedDetails)
    assert unknown.details.quantities == ("loop_rate",)


def test_the_whole_gate_passes_an_invented_voltage_in_watts_with_the_mismatch_on_record(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", node(NODE, quantities={"battery_voltage": (2.4, "W")}))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "pass"
    units = [c for c in result.checks if c.name == "units"]
    assert units and not any(c.outcome == "fail" for c in units)
    unchecked = [c for c in units if c.outcome == "unchecked"]
    assert any("battery_voltage" in c.message and "suffix" in c.message for c in unchecked)


@pytest.mark.parametrize(
    ("name", "value", "unit"),
    [("supply_voltage", 2.4, "W"), ("mass", -0.2, "kg"), ("torque_peak", 2, "N"), ("mass", 2, "N")],
)
def test_a_catalogued_name_s_unit_or_sign_mismatch_is_still_refused(
    tmp_path: Path, name: str, value: float, unit: str
) -> None:
    # Only a mismatch under an inferred kind goes unchecked; the catalogue's own kinds refuse.
    ran = run(tmp_path, node(NODE, quantities={name: (value, unit)}))
    assert outcomes(ran) == ["fail"] and name in ran.observations[0].message


def test_an_inferred_name_forms_no_relation(tmp_path: Path) -> None:
    # A 6 kg "pack_mass" beside a module mass sum: the kind is a mass, and nothing more: the
    # mass sum reads ``mass`` by name, so the conservation check sees no instance of it.
    from physgate.gate import check_conservation

    module = node(f"{M}.robot", kind="module", domain=M, quantities={"mass": (1, "kg")})
    part = node(
        f"{M}.pack", domain=M, quantities={"pack_mass": (6, "kg")}, constrains=[f"{M}.robot"]
    )
    graph(tmp_path / "g", module, part)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_conservation.run(CheckContext(view=view, scope="system", bounds=load_bounds()))
    assert not any(o.outcome == "fail" for o in ran.observations)


M = "mechanical"
