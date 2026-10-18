"""Check 1, names the catalogue lacks: a closed list of suffixes gives a kind, and only a kind.

A writer can step out of every relation and range by inventing a name (``battery_current``
for ``stall_current``). The catalogue cannot know every name, but a name ending in a word that
has one SI meaning (``_current``, ``_voltage``, ``_mass``, ``_width``, ...) has that word's
dimension and sign whatever comes before it. Such a name is judged for its unit's dimension
and its sign by the suffix's kind, and for nothing else: no relation forms from it and no range
applies to it by name. A suffix with more than one meaning (``_rate``, ``_power``, ``_ratio``,
``_capacity``) infers nothing, so the list is closed and pinned here.
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


def test_the_list_is_closed_and_every_suffix_has_one_kind_and_a_source() -> None:
    assert {s.suffix: s.kind for s in SUFFIXES} == {
        "_current": "current",
        "_current_draw": "current",
        "_voltage": "voltage",
        "_mass": "mass",
        "_force": "force",
        "_torque": "torque",
        "_energy": "energy",
        "_frequency": "frequency",
        "_temperature": "temperature",
        "_position": "length",
        "_length": "length",
        "_diameter": "length",
        "_radius": "length",
        "_height": "length",
        "_width": "length",
        "_thickness": "length",
        "_power_draw": "power",
    }
    assert all(s.kind in KINDS and s.source for s in SUFFIXES)


@pytest.mark.parametrize(
    "name", ["loop_rate", "specific_power", "reduction_ratio", "charge_capacity", "winding_resistance"]
)
def test_an_ambiguous_suffix_infers_nothing(name: str) -> None:
    assert inferred_by(name) is None and kind_of(name) is None


def test_a_catalogued_name_keeps_its_entry_and_is_not_inferred() -> None:
    assert "stall_current" in QUANTITIES
    assert inferred_by("stall_current") is None
    assert kind_of("stall_current") is KINDS["current"]


def test_the_suffix_alone_is_not_a_name_and_the_word_must_end_the_name() -> None:
    assert kind_of("_current") is None
    assert kind_of("current") is None
    assert kind_of("current_limit_margin") is None  # the word is inside, not at the end
    assert kind_of("voltage_divider_ratio") is None


def test_the_suffixes_are_part_of_the_catalogue_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    import physgate.gate.catalogue as catalogue

    before = catalogue_digest()
    monkeypatch.setattr(catalogue, "SUFFIXES", SUFFIXES[:-1])
    assert catalogue_digest() != before


def test_a_battery_current_written_in_watts_is_refused_by_its_suffix(tmp_path: Path) -> None:
    ran = run(tmp_path, node(NODE, quantities={"battery_current": (2.4, "W")}))
    refusals = [o for o in ran.observations if o.outcome == "fail"]
    (finding,) = refusals
    assert finding.node == NODE and "battery_current" in finding.message
    assert "_current" in finding.message and "suffix" in finding.message


def test_a_board_width_written_in_kilograms_is_refused_and_one_in_millimetres_is_not(
    tmp_path: Path,
) -> None:
    (finding,) = [
        o
        for o in run(tmp_path / "a", node(NODE, quantities={"board_width": (2, "kg")})).observations
        if o.outcome == "fail"
    ]
    assert "board_width" in finding.message
    clean = run(tmp_path / "b", node(NODE, quantities={"board_width": (80, "mm")}))
    assert [o.outcome for o in clean.observations] == ["unchecked"]


def test_a_negative_mass_under_an_invented_name_is_refused_by_the_kind_s_sign(
    tmp_path: Path,
) -> None:
    (finding,) = [
        o
        for o in run(tmp_path, node(NODE, quantities={"pack_mass": (-0.2, "kg")})).observations
        if o.outcome == "fail"
    ]
    assert "pack_mass" in finding.message and "never negative" in finding.message


def test_an_inferred_name_is_recorded_as_unchecked_for_everything_but_dimension_and_sign(
    tmp_path: Path,
) -> None:
    ran = run(
        tmp_path, node(NODE, quantities={"coil_current": (0.5, "A"), "loop_rate": (50, "Hz")})
    )
    by_message = {o.message: o for o in ran.observations}
    inferred = next(o for m, o in by_message.items() if "coil_current" in m)
    unknown = next(o for m, o in by_message.items() if "loop_rate" in m)
    assert inferred is not unknown
    assert inferred.outcome == "unchecked" and "_current" in inferred.message
    assert "no relation" in inferred.message and "range" in inferred.message
    assert isinstance(inferred.details, UncheckedDetails)
    assert inferred.details.quantities == ("coil_current",)
    assert unknown.outcome == "unchecked" and "does not know" in unknown.message
    assert isinstance(unknown.details, UncheckedDetails)
    assert unknown.details.quantities == ("loop_rate",)


def test_the_whole_gate_blocks_an_invented_current_in_watts_at_subtask_scope(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", node(NODE, quantities={"battery_current": (2.4, "W")}))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "fail" and result.failing_check == "units"


def test_an_inferred_name_forms_no_relation(tmp_path: Path) -> None:
    # A 6 A "motor_current" on a 1 A driver: the kind is a current, and nothing more: the
    # headroom relation reads stall_current by name, so the power check sees no instance.
    from physgate.gate import check_power

    driver = node("electrical.driver", quantities={"current_limit": (1, "A")})
    motor = node(
        "electrical.motor", quantities={"motor_current": (6, "A")}, constrains=["electrical.driver"]
    )
    graph(tmp_path / "g", driver, motor)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_power.run(CheckContext(view=view, scope="system", bounds=load_bounds()))
    assert ran.observations == () and ran.evaluated == 0
