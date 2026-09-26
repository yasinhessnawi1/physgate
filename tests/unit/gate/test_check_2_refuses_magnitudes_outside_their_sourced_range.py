"""Check 2: a value against its sourced range, read from the table file and nowhere else."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude
from physgate.gate.bounds_table import BOUNDS_DIR, BoundsTableError, load_bounds, load_table
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import MagnitudeDetails, UncheckedDetails

TABLE = BOUNDS_DIR / "electrical.toml"


def motor(value: float | int, unit: str = "A", domain: str = "electrical") -> dict[str, Any]:
    return node(f"{domain}.motor_left", domain=domain, quantities={"stall_current": (value, unit)})


def check(tmp_path: Path, *payloads: dict[str, Any], bounds_dir: Path = BOUNDS_DIR) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="subtask", bounds=load_bounds(bounds_dir))
    return check_magnitude.run(ctx)


def test_a_stall_current_of_240_amperes_on_a_hobby_motor_is_refused_with_its_range_and_source(
    tmp_path: Path,
) -> None:
    ran = check(tmp_path, motor(240))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.motor_left"
    details = finding.details
    assert isinstance(details, MagnitudeDetails)
    assert (details.value.value, details.value.unit) == (240, "A")
    assert (details.low.value, details.high.value, details.high.unit) == (0.36, 6.5, "A")
    assert "Pololu" in details.source
    assert details.table_sha256 == hashlib.sha256(TABLE.read_bytes()).hexdigest()
    assert "brushed DC metal gearmotor" in finding.message


def test_a_stall_current_of_2_4_amperes_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, motor(2.4))
    assert ran.observations == () and ran.evaluated == 1


def test_the_range_is_compared_after_unit_conversion(tmp_path: Path) -> None:
    assert check(tmp_path / "a", motor(2400, "mA")).observations == ()
    (finding,) = check(tmp_path / "b", motor(240000, "mA")).observations
    assert finding.outcome == "fail"


def test_the_bounds_are_exact_and_no_rounding_is_credited(tmp_path: Path) -> None:
    assert check(tmp_path / "edge", motor(6.5)).observations == ()
    (finding,) = check(tmp_path / "past", motor(6.5000001)).observations
    assert finding.outcome == "fail"
    (below,) = check(tmp_path / "under", motor(0.3599999)).observations
    assert below.outcome == "fail"


def test_a_quantity_with_no_range_in_its_domain_is_unchecked_never_passed(tmp_path: Path) -> None:
    ran = check(tmp_path, motor(240, domain="mechanical"))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("stall_current",)


def test_the_range_comes_from_the_table_file_not_the_code(tmp_path: Path) -> None:
    widened = tmp_path / "tables"
    widened.mkdir()
    text = TABLE.read_text().replace("high = 6.5\n", "high = 300\n", 1)
    assert text != TABLE.read_text()
    (widened / "electrical.toml").write_text(text)
    assert check(tmp_path / "g", motor(240), bounds_dir=widened).observations == ()


def test_the_real_gate_refuses_240_amperes_at_subtask_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", motor(240))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "fail" and result.failing_check == "magnitude"
    assert result.numeric_output is not None and result.numeric_output.value == 240


# --- the table: a range without a source does not load -------------------------------

GOOD = """
[meta]
domain = "electrical"
curated_by = "a test"

[[range]]
quantity = "stall_current"
low = 0.36
high = 6.5
unit = "A"
class = "a motor"
source = "a datasheet"
retrieved = 2026-09-26
note = "a note"
"""


def write(tmp_path: Path, text: str, name: str = "electrical.toml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_the_real_tables_load_and_every_range_is_sourced_and_dated() -> None:
    bounds = load_bounds()
    ranges = [r for t in bounds.tables.values() for r in t.ranges.values()]
    assert ranges
    assert all(r.source.strip() and r.note.strip() and r.retrieved for r in ranges)


def test_a_well_formed_table_loads(tmp_path: Path) -> None:
    table = load_table(write(tmp_path, GOOD))
    assert list(table.ranges) == ["stall_current"]


@pytest.mark.parametrize(
    ("broken", "where"),
    [
        (GOOD.replace('source = "a datasheet"\n', ""), "source"),
        (GOOD.replace('source = "a datasheet"', 'source = "  "'), "source"),
        (GOOD.replace("retrieved = 2026-09-26\n", ""), "retrieved"),
        (GOOD.replace("retrieved = 2026-09-26", 'retrieved = "recently"'), "retrieved"),
        (GOOD.replace('note = "a note"\n', ""), "note"),
        (GOOD.replace('class = "a motor"\n', ""), "class"),
        (GOOD.replace("low = 0.36", "low = 7"), "range"),
        (GOOD.replace('unit = "A"', 'unit = "V"'), "range"),
        (GOOD.replace('quantity = "stall_current"', 'quantity = "gizmo"'), "range"),
        (GOOD + 'extra = "field"\n', "extra"),
    ],
    ids=[
        "no source",
        "blank source",
        "no date",
        "not a date",
        "no note",
        "no class",
        "low above high",
        "a unit its kind refuses",
        "a quantity the catalogue does not know",
        "an unknown field",
    ],
)
def test_a_range_missing_what_makes_it_traceable_does_not_load(
    tmp_path: Path, broken: str, where: str
) -> None:
    with pytest.raises(BoundsTableError) as caught:
        load_table(write(tmp_path, broken))
    assert where in caught.value.context["where"]


def test_a_table_named_for_another_domain_or_repeating_a_quantity_does_not_load(
    tmp_path: Path,
) -> None:
    with pytest.raises(BoundsTableError, match="another domain"):
        load_table(write(tmp_path, GOOD, "mechanical.toml"))
    doubled = GOOD + GOOD.split("[meta]")[1].split("\n\n", 1)[1]
    with pytest.raises(BoundsTableError, match="two ranges"):
        load_table(write(tmp_path, doubled))


def test_no_table_or_a_file_that_is_not_toml_stops_the_gate_being_built(tmp_path: Path) -> None:
    with pytest.raises(BoundsTableError, match="no bounds table"):
        load_bounds(tmp_path)
    write(tmp_path, "this is = = not toml")
    with pytest.raises(BoundsTableError, match="not TOML"):
        load_bounds(tmp_path)
