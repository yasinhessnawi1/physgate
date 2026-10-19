"""Check 2: a value against its sourced range, read from the table file and nowhere else."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude
from physgate.gate.bounds_table import (
    BOUNDS_NAME,
    KNOWLEDGE_DIR,
    BoundsTableError,
    load_bounds,
    load_table,
)
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import MagnitudeDetails, UncheckedDetails

TABLE = KNOWLEDGE_DIR / "electrical" / BOUNDS_NAME


def imu(value: float | int, unit: str = "Hz", domain: str = "electrical") -> dict[str, Any]:
    return node(f"{domain}.imu", domain=domain, quantities={"sample_rate": (value, unit)})


def motor(value: float | int, unit: str = "A") -> dict[str, Any]:
    return node("electrical.motor_left", quantities={"stall_current": (value, unit)})


def check(tmp_path: Path, *payloads: dict[str, Any], bounds_dir: Path = KNOWLEDGE_DIR) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="subtask", bounds=load_bounds(bounds_dir))
    return check_magnitude.run(ctx)


def test_an_imu_sampled_at_50_kilohertz_is_refused_with_its_range_and_source(
    tmp_path: Path,
) -> None:
    ran = check(tmp_path, imu(50_000))
    (finding,) = ran.observations
    assert finding.outcome == "fail" and finding.node == "electrical.imu"
    details = finding.details
    assert isinstance(details, MagnitudeDetails)
    assert (details.value.value, details.value.unit) == (50_000, "Hz")
    assert (details.low.value, details.high.value, details.high.unit) == (0.78, 32000, "Hz")
    assert "ICM-42688-P" in details.source and "BMI270" in details.source
    assert details.table_sha256 == hashlib.sha256(TABLE.read_bytes()).hexdigest()
    assert "MEMS inertial measurement unit" in finding.message


def test_an_imu_sampled_at_1_kilohertz_passes(tmp_path: Path) -> None:
    ran = check(tmp_path, imu(1000))
    assert ran.observations == () and ran.evaluated == 1


@pytest.mark.parametrize(
    ("rate", "maker"), [(32_000, "TDK ICM-42688-P"), (1.6, "ST LSM6DSO"), (0.78, "Bosch BMI270")]
)
def test_a_rate_another_maker_s_imu_is_set_to_is_not_refused(
    tmp_path: Path, rate: float, maker: str
) -> None:
    # One maker's register span refused these; each is a rate the named part can be set to.
    assert check(tmp_path, imu(rate)).observations == (), maker


def test_the_range_is_compared_after_unit_conversion(tmp_path: Path) -> None:
    assert check(tmp_path / "a", imu(32, "kHz")).observations == ()
    (finding,) = check(tmp_path / "b", imu(50, "kHz")).observations
    assert finding.outcome == "fail"


def test_the_bounds_are_exact_and_no_rounding_is_credited(tmp_path: Path) -> None:
    assert check(tmp_path / "edge", imu(32_000)).observations == ()
    (finding,) = check(tmp_path / "past", imu(32_000.001)).observations
    assert finding.outcome == "fail"
    (below,) = check(tmp_path / "under", imu(0.7799999)).observations
    assert below.outcome == "fail"


def test_a_quantity_with_no_range_in_its_domain_is_unchecked_never_passed(tmp_path: Path) -> None:
    ran = check(tmp_path, imu(50_000, domain="mechanical"))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("sample_rate",)


@pytest.mark.parametrize("amps", [0.05, 0.114, 6.0, 133, 483])
def test_a_stall_current_has_no_range_so_no_legitimate_motor_is_refused_by_one(
    tmp_path: Path, amps: float
) -> None:
    # From a coreless micro motor's 50 mA to a robot-competition motor's 483 A: no span
    # holds every motor and tells anything, so a stall current is judged by its relation
    # to its supply's current limit instead, and its magnitude is recorded as unchecked.
    ran = check(tmp_path, motor(amps))
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0
    assert "stall_current" not in load_bounds().tables["electrical"].ranges


def test_the_range_comes_from_the_table_file_not_the_code(tmp_path: Path) -> None:
    widened = tmp_path / "tables"
    (widened / "electrical").mkdir(parents=True)
    text = TABLE.read_text().replace("high = 32000\n", "high = 60000\n", 1)
    assert text != TABLE.read_text()
    (widened / "electrical" / BOUNDS_NAME).write_text(text)
    assert check(tmp_path / "g", imu(50_000), bounds_dir=widened).observations == ()


def test_the_real_gate_refuses_50_kilohertz_at_subtask_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", imu(50_000))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "fail" and result.failing_check == "magnitude"
    assert result.numeric_output is not None and result.numeric_output.value == 50_000


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
confirmed = 2026-10-19
note = "a note"
"""


def write(tmp_path: Path, text: str, domain: str = "electrical") -> Path:
    """Write ``text`` as ``<tmp_path>/<domain>/bounds.toml``, one domain directory per call."""
    directory = tmp_path / domain
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / BOUNDS_NAME
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
        (GOOD.replace("confirmed = 2026-10-19\n", ""), "confirmed"),
        (GOOD.replace("confirmed = 2026-10-19", 'confirmed = "soon"'), "confirmed"),
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
        "no confirmation date",
        "not a confirmation date",
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
        load_table(write(tmp_path, GOOD, "mechanical"))
    doubled = GOOD + GOOD.split("[meta]")[1].split("\n\n", 1)[1]
    with pytest.raises(BoundsTableError, match="two ranges"):
        load_table(write(tmp_path, doubled))


def test_no_table_or_a_file_that_is_not_toml_stops_the_gate_being_built(tmp_path: Path) -> None:
    with pytest.raises(BoundsTableError, match="no bounds table"):
        load_bounds(tmp_path)
    write(tmp_path, "this is = = not toml")
    with pytest.raises(BoundsTableError, match="not TOML"):
        load_bounds(tmp_path)


def test_an_adc_sampled_at_1_megahertz_on_an_electrical_node_is_refused_a_named_limit(
    tmp_path: Path,
) -> None:
    # The electrical sample_rate range is an inertial sensor's. An electrical node that
    # samples faster for another reason is refused by it; the evaluation scores that as
    # the stated limit, not as a false alarm.
    adc = node("electrical.adc", quantities={"sample_rate": (1_000_000, "Hz")})
    (finding,) = check(tmp_path, adc).observations
    assert finding.outcome == "fail" and "inertial" in finding.message


def test_a_range_without_a_confirmation_date_does_not_load(tmp_path: Path) -> None:
    # A figure nobody confirmed in the maker's own document may not refuse a design, so a
    # range without the date it was confirmed does not load at all.
    tables = tmp_path / "tables"
    (tables / "electrical").mkdir(parents=True)
    text = TABLE.read_text()
    assert text.count("confirmed = ") == 1
    (tables / "electrical" / BOUNDS_NAME).write_text(
        text.replace("confirmed = ", "unconfirmed = ", 1)
    )
    with pytest.raises(BoundsTableError):
        load_bounds(tables)
