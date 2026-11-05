"""The widened catalogue, held to every value G11 run 4 wrote, and its coverage counted.

``run4/values.json`` holds run 4's 203 values: one row per distinct node, name, value and unit
across the run's 124 node files (its store, each attempt's graph, the worktrees' interfaces and
proposals, the plan's interface nodes, and the target's git history), kept as name, value and
unit only. Each value is a correct figure of a real design or one the run's own gate refused
for its unit, so a check that refuses one of them is a check that fails a correct design.

Two things are held here:

- **No regression.** Every value the catalogue gives a kind passes that kind's unit and sign
  rules, and its envelope where it has one, in every domain; the only refusals are the four
  units no name can save (``count/update`` three times, and ``rad/(s*count)``), which run 4's
  own gate refused (seq 182 and seq 403). At a64e805f three values are mis-kinded by the
  ``_radius`` and ``_frequency`` suffixes (gate seq 271), so this is red until the fix.
- **The coverage the fix must reach**, counted by the research's own script with the approved
  row set (``classify.py`` narrowed to research section 6 as ruled on 04.11.2026):

  ===================================  ==========  =====================
  of 203 values                        a64e805f    approved row set
  ===================================  ==========  =====================
  a kind                               38          106
  - by exact name (a mismatch refuses) 22          27
  - by suffix (recorded only)          16          47
  - by qualifier (recorded only)       0           32
  a sign check                         5           37
  a definitional envelope (0 to 1)     1           2
  unchecked: the unit parses, no kind  161         93
  unit refused by parse                4           4
  a kind the unit disagrees with       3           0
  ===================================  ==========  =====================

  By name, of 174: 25 have a kind at a64e805f, 86 after. The research's own figures (110, 31, 40, 5,
  89) include ``max_duty`` (3 values), the radian -1 kind (1) and the alias (1), all held back.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

import physgate.gate.catalogue as catalogue
from physgate.gate import check_magnitude, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import QUANTITIES, SUFFIXES, kind_of
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.units import UnitRefusedError, parse

VALUES = json.loads((Path(__file__).parent / "run4" / "values.json").read_text())

#: The four values whose unit fails under any name, as run 4's own gate refused them.
PARSE_REFUSED = {
    ("cruise_drive_increment", "count/update"),
    ("cruise_drive_increment_applied", "count/update"),
    ("proposed_cruise_drive_increment", "count/update"),
    ("gyro_sensitivity", "rad/(s*count)"),
}

#: Every run-4 name the approved row set gives a kind, and the kind. Every other run-4 name stays
#: without one on purpose (research section 4, "leave").
EXPECTED_KINDS: dict[str, str] = {
    "angle_decay_one_count_spectral_radius": "modulus",
    "body_inertia": "moment_of_inertia",
    "cell_mass": "mass",
    "com_020_phase_margin": "angle",
    "com_040_phase_margin": "angle",
    "complementary_sensitivity_peak": "modulus",
    "computation_delay_budget": "time",
    "computation_delay_measured": "time",
    "computation_delay_measured_nominal": "time",
    "cpu_utilisation_bound": "modulus",
    "cruise_final_ground_speed": "velocity",
    "cruise_wheel_torque": "torque",
    "current_limit": "current",
    "delay_margin": "time",
    "drag_area": "area",
    "external_gear_ratio": "dimensionless",
    "external_stage_efficiency": "efficiency",
    "gain_crossover_frequency": "angular_velocity",
    "gain_crossover_frequency_nominal": "angular_velocity",
    "gain_margin_lower": "modulus",
    "gain_margin_upper": "modulus",
    "gear_ratio": "dimensionless",
    "gearbox_efficiency_implied": "efficiency",
    "gyro_delay": "time",
    "gyro_output_data_rate": "frequency",
    "gyro_sample_age_max": "duration",
    "input_delay": "time",
    "mass": "mass",
    "max_average_motor_voltage": "voltage",
    "max_average_motor_voltage_max": "voltage",
    "max_average_motor_voltage_min": "voltage",
    "max_ground_speed": "velocity",
    "max_ground_speed_max": "velocity",
    "max_ground_speed_min": "velocity",
    "max_update_lateness": "time",
    "motor_off_latency_bound": "duration",
    "motor_off_latency_max": "duration",
    "motor_off_latency_measured": "duration",
    "motor_resistance": "resistance",
    "no_load_ground_speed": "velocity",
    "no_load_speed": "angular_velocity",
    "no_load_speed_max": "angular_velocity",
    "no_load_speed_min": "angular_velocity",
    "overall_gear_ratio": "dimensionless",
    "phase_margin": "angle",
    "phase_margin_nominal": "angle",
    "proposed_complementary_sensitivity_peak": "modulus",
    "proposed_cruise_final_ground_speed": "velocity",
    "proposed_cruise_ramp_time": "time",
    "proposed_delay_margin": "time",
    "proposed_gain_crossover_frequency": "angular_velocity",
    "proposed_gain_margin_lower": "modulus",
    "proposed_gain_margin_upper": "modulus",
    "proposed_phase_margin": "angle",
    "proposed_push_max_abs_motor_current": "current",
    "proposed_sensitivity_peak": "modulus",
    "proposed_sizing_motor_phase_margin": "angle",
    "push_wheel_torque_indicative": "torque",
    "pwm_frequency": "frequency",
    "rated_no_load_current": "current",
    "rated_no_load_speed": "angular_velocity",
    "rated_stall_current": "current",
    "rated_stall_torque": "torque",
    "rated_voltage": "voltage",
    "running_mass": "mass",
    "sample_period": "duration",
    "sample_rate": "frequency",
    "sensitivity_peak": "modulus",
    "sensitivity_peak_lower_bound": "modulus",
    "sensitivity_peak_nominal": "modulus",
    "sizing_motor_phase_margin": "angle",
    "stall_current": "current",
    "stall_current_max": "current",
    "stall_torque": "torque",
    "supply_voltage": "voltage",
    "supply_voltage_max": "voltage",
    "supply_voltage_min": "voltage",
    "tilt_mode_natural_frequency": "frequency",
    "torque_constant": "torque_constant",
    "update_duration_max": "duration",
    "update_lateness_measured": "time",
    "update_period_max": "duration",
    "update_period_min": "duration",
    "update_rate": "frequency",
    "wheel_pair_mass": "mass",
    "wheel_radius": "length",
}

#: The new suffixes, each of which must decide the kind of at least one run-4 name. The 24th,
#: ``_utilization``, is ``_utilisation``'s spelling twin and reaches none; the rows test holds it.
NEW_SUFFIXES = (
    "_period", "_duration", "_latency", "_age", "_delay", "_lateness", "_time", "_delay_margin",
    "_phase_margin", "_inertia", "_area", "_ground_speed", "_stall_current", "_no_load_current",
    "_motor_current", "_no_load_speed", "_gain_crossover_frequency", "_gear_ratio",
    "_output_data_rate", "_sensitivity_peak", "_spectral_radius", "_gain_margin", "_utilisation",
)  # fmt: skip

#: The domains a value is judged in: every table the gate loads, and one with no table.
DOMAINS = sorted({*load_bounds().tables, "control"})


def _qualifiers() -> tuple[str, ...]:
    words = getattr(catalogue, "QUALIFIERS", None)
    if words is None:
        pytest.fail("the catalogue has no closed QUALIFIERS list yet (the widening's first change)")
    return tuple(words)


def _suffix_of(name: str) -> str | None:
    """The longest suffix that ends ``name`` and leaves something before it."""
    for suffix in sorted((s.suffix for s in SUFFIXES), key=len, reverse=True):
        if name.endswith(suffix) and len(name) > len(suffix):
            return suffix
    return None


def _stripped(name: str, qualifiers: tuple[str, ...]) -> str:
    """``name`` with its trailing qualifier words taken off, repeatedly."""
    changed = True
    while changed:
        changed = False
        for word in qualifiers:
            if name.endswith(word) and len(name) > len(word):
                name, changed = name[: -len(word)], True
                break
    return name


def _parses(row: dict[str, Any]) -> bool:
    try:
        parse(row["value"], row["unit"])
    except UnitRefusedError:
        return False
    return True


def _packs() -> list[dict[str, tuple[float | int, str]]]:
    """Run 4's distinct values, as few nodes as hold each name at most once."""
    packs: list[dict[str, tuple[float | int, str]]] = []
    for name, value, unit in sorted({(r["name"], r["value"], r["unit"]) for r in VALUES}, key=repr):
        pack = next((p for p in packs if name not in p), None)
        if pack is None:
            packs.append(pack := {})
        pack[name] = (value, unit)
    return packs


def test_the_fixture_is_run_4_s_203_values_as_name_value_and_unit_only() -> None:
    # Guard.
    assert len(VALUES) == 203
    assert len({r["name"] for r in VALUES}) == 174
    assert all(set(r) == {"name", "value", "unit"} for r in VALUES)
    assert {(r["name"], r["unit"]) for r in VALUES if not _parses(r)} == PARSE_REFUSED
    assert sum(not _parses(r) for r in VALUES) == 4


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_run_4_value_passes_its_kind_and_its_bound_in_every_domain(
    tmp_path: Path, domain: str
) -> None:
    graph(
        tmp_path / "g",
        *(node(f"run4.values_{i}", domain=domain, quantities=p) for i, p in enumerate(_packs(), 1)),
    )
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="subtask", bounds=load_bounds())
    try:
        units, magnitude = check_units.run(ctx), check_magnitude.run(ctx)
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the gate raised on run 4's values: {type(exc).__name__}: {exc}")
    refused = {
        (q.name, q.unit)
        for o in (*units.observations, *magnitude.observations)
        if o.outcome == "fail"
        for q in o.quantities
    }
    assert refused == PARSE_REFUSED
    assert not any(o.outcome == "fail" for o in magnitude.observations)
    # A kind the unit disagrees with is a mis-kind: the record says so, and there is none. Every
    # reading's mismatch record, a suffix's or a qualified name's, says it refuses nothing.
    mis_kinds = [o.message for o in units.observations if "refuses nothing" in o.message]
    assert mis_kinds == []


def test_each_run_4_name_reads_as_its_approved_kind() -> None:
    names = sorted({r["name"] for r in VALUES})
    got = {n: kind.name for n in names if (kind := kind_of(n)) is not None}
    assert got == EXPECTED_KINDS


def test_the_coverage_on_run_4_is_the_approved_row_set_s() -> None:
    envelopes = set(load_bounds().envelopes)
    tally: Counter[str] = Counter()
    for row in VALUES:
        name = row["name"]
        if not _parses(row):
            tally["unit refused by parse"] += 1
            continue
        kind = kind_of(name)
        if kind is None:
            tally["unchecked"] += 1
            continue
        tally["kind"] += 1
        if name in QUANTITIES:
            tally["by exact name"] += 1
        elif _suffix_of(name) is not None:
            tally["by suffix"] += 1
        else:
            tally["by qualifier"] += 1
        if kind.sign != "any":
            tally["sign check"] += 1
        if kind.name in envelopes:
            tally["envelope"] += 1
    assert dict(tally) == {
        "kind": 106,
        "by exact name": 27,
        "by suffix": 47,
        "by qualifier": 32,
        "sign check": 37,
        "envelope": 2,
        "unchecked": 93,
        "unit refused by parse": 4,
    }
    assert len({r["name"] for r in VALUES if kind_of(r["name"]) is not None}) == 86


def test_only_sample_rate_has_a_range_by_name_and_no_alias_adds_one() -> None:
    # Guard: gyro_output_data_rate gets a kind by its suffix, never output_data_rate's range.
    ranged = {name for t in load_bounds().tables.values() for name in t.ranges}
    assert {r["name"] for r in VALUES if r["name"] in ranged} == {"sample_rate"}


@pytest.mark.parametrize("suffix", NEW_SUFFIXES)
def test_every_new_suffix_decides_the_kind_of_a_run_4_name(suffix: str) -> None:
    qualifiers = _qualifiers()
    assert suffix in {s.suffix for s in SUFFIXES}
    deciding = {
        n
        for n in {r["name"] for r in VALUES}
        if n not in QUANTITIES
        and (_suffix_of(n) or _suffix_of(_stripped(n, qualifiers))) == suffix
        and kind_of(n) is not None
    }
    assert deciding, f"{suffix} reaches no value run 4 wrote"
