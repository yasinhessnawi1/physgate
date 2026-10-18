"""Check 4, discharge rate: a store's rated discharge against the energy it stores.

A node declares no chemistry, so the bound is the weakest one still true of every store
class: the highest continuous discharge rate any class's sourced datasheet states. It can
refuse only a rating that no store of any class is made to give.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_power, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import (
    FASTEST,
    MAX_DISCHARGE_PER_HOUR,
    RELATIONS,
    STORE_CLASSES,
    catalogue_digest,
)
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import PowerDetails, Scope

STORE = "electrical.battery"


def store(watt_hours: float | int, rating: float | int, rating_unit: str = "W") -> dict[str, Any]:
    return node(
        STORE,
        quantities={
            "energy_capacity": (watt_hours, "W*h"),
            "max_discharge_power": (rating, rating_unit),
        },
    )


def run(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    return check_power.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


def test_the_bound_is_the_fastest_sourced_store_class() -> None:
    assert RELATIONS["discharge_rate"].judged_by == 4
    assert len(STORE_CLASSES) >= 5
    assert all(c.source and c.per_hour > 0 for c in STORE_CLASSES)
    assert max(c.per_hour for c in STORE_CLASSES) == MAX_DISCHARGE_PER_HOUR == FASTEST.per_hour


def test_the_store_classes_are_part_of_the_catalogue_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import physgate.gate.catalogue as catalogue

    before = catalogue_digest()
    monkeypatch.setattr(catalogue, "STORE_CLASSES", STORE_CLASSES[:-1])
    assert catalogue_digest() != before


@pytest.mark.parametrize("scope", ["module", "system"])
def test_a_1_milliwatt_hour_store_rated_1_megawatt_is_refused(tmp_path: Path, scope: Scope) -> None:
    ran = run(tmp_path, scope, store(0.001, 1_000_000))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == STORE
    assert isinstance(finding.details, PowerDetails)
    assert finding.value is not None and finding.value.unit == "W"
    bound = MAX_DISCHARGE_PER_HOUR * Fraction("0.001")
    assert Fraction(repr(finding.value.value)) == 1_000_000 - bound
    assert "no class of energy store" in finding.message and FASTEST.name in finding.message
    assert ran.evaluated == 1


def test_a_rating_at_the_bound_passes_and_just_above_it_is_refused(tmp_path: Path) -> None:
    at = MAX_DISCHARGE_PER_HOUR * 10  # watts from 10 W*h
    assert run(tmp_path / "at", "system", store(10, int(at))).observations == ()
    (finding,) = run(tmp_path / "above", "system", store(10, int(at) + 1)).observations
    assert finding.outcome == "fail"


def test_a_small_robot_s_battery_passes(tmp_path: Path) -> None:
    # Six AA NiMH cells, about 2 A h at 7.2 V, discharged at 1 C.
    assert run(tmp_path, "system", store(14.4, 14.4)).observations == ()


def test_the_comparison_is_made_in_one_unit(tmp_path: Path) -> None:
    joules = 3600 * 10  # 10 W*h, written in joules
    ran = run(
        tmp_path,
        "system",
        node(
            STORE,
            quantities={
                "energy_capacity": (joules, "J"),
                "max_discharge_power": (int(MAX_DISCHARGE_PER_HOUR * 10) + 1, "W"),
            },
        ),
    )
    assert [o.outcome for o in ran.observations] == ["fail"]


def test_a_rating_the_unit_check_refuses_is_unchecked_here(tmp_path: Path) -> None:
    ran = run(tmp_path, "system", store(10, 5, "W*h"))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and "unit the unit check refuses" in record.message


def test_the_unit_check_reads_the_relation_s_two_sides_as_powers(tmp_path: Path) -> None:
    graph(tmp_path / "g", store(10, 1_000_000))
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ran = check_units.run(CheckContext(view=view, scope="subtask", bounds=load_bounds()))
    assert ran.observations == ()


def test_a_store_with_no_rating_gets_no_discharge_relation(tmp_path: Path) -> None:
    only = node(STORE, quantities={"energy_capacity": (10, "W*h")})
    assert run(tmp_path, "system", only).observations == ()
