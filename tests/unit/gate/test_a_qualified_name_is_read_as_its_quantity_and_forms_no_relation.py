"""A qualifier word after a quantity's name keeps the quantity's kind.

A maximum, a bound or a measured value of a quantity is a value of that quantity, so
``stall_current_max`` is a current and ``gearbox_efficiency_implied`` an efficiency. The
catalogue strips a closed list of trailing qualifier words, repeatedly, and reads what is left
as an exact name or by its suffix. The reading keeps the kind, its sign and its definitional
envelope, and nothing else:

- it is the gate's reading of a name, not the catalogue's, so a unit or sign that disagrees is
  **recorded, never refused**, as a suffix's is;
- **no relation forms** from it: ``stall_current_max`` is not held to a ``current_limit``, and
  ``mass_max`` joins no mass sum; the record keeps saying so;
- the hooks still count the name as one the catalogue lacks.

The list is closed. A word that says where or in which case a quantity is taken (``_wheel``,
``_armature``, ``_full_duty``, ``_turbo_charged``, ``_reflected``) changes what the quantity
is, so it is never stripped: run 4's ``stall_current_full_duty`` is not a duty cycle, and a
dimensionless one above 1 is never refused as one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

import physgate.gate.catalogue as catalogue
from physgate.gate import check_conservation, check_magnitude, check_power, check_units
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import (
    KINDS,
    QUANTITIES,
    catalogue_digest,
    kind_of,
    shadowing_names,
    unknown_names,
)
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import UncheckedDetails
from physgate.state.vocabulary import shadowing_quantity_names, unknown_quantity_names

NODE = "electrical.motor"

#: The approved qualifier words (research section 3b, change 1).
QUALIFIERS = frozenset(
    {
        "_max",
        "_min",
        "_nominal",
        "_measured",
        "_applied",
        "_bound",
        "_budget",
        "_typical",
        "_lower",
        "_upper",
        "_implied",
        "_estimated",
        "_indicative",
    }
)


def _qualifiers() -> tuple[str, ...]:
    words = getattr(catalogue, "QUALIFIERS", None)
    if words is None:
        pytest.fail("the catalogue has no closed QUALIFIERS list yet (the widening's first change)")
    return tuple(words)


def _view(tmp_path: Path, *payloads: dict[str, Any]) -> GraphView:
    graph(tmp_path / "g", *payloads)
    return GraphView.read(tmp_path / "g", base_revision=0)


def _ctx(view: GraphView, scope: str = "subtask") -> CheckContext:
    return CheckContext(view=view, scope=scope, bounds=load_bounds())  # type: ignore[arg-type]


def _units(tmp_path: Path, quantities: dict[str, tuple[float | int, str]]) -> Any:
    view = _view(tmp_path, node(NODE, quantities=quantities))
    try:
        return check_units.run(_ctx(view))
    except Exception as exc:  # noqa: BLE001 - a crash is the finding
        pytest.fail(f"the unit check raised on {quantities}: {type(exc).__name__}: {exc}")


def _naming(ran: Any, name: str) -> list[Any]:
    return [
        o
        for o in ran.observations
        if isinstance(o.details, UncheckedDetails) and name in o.details.quantities
    ]


def test_the_qualifier_list_is_closed_and_is_the_approved_one() -> None:
    words = _qualifiers()
    assert len(words) == len(set(words))
    assert set(words) == QUALIFIERS


def test_the_qualifier_list_is_part_of_the_catalogue_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    words = _qualifiers()
    before = catalogue_digest()
    monkeypatch.setattr(catalogue, "QUALIFIERS", words[:-1])
    assert catalogue_digest() != before


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        # a catalogued name, then a qualifier
        ("stall_current_max", "current"),
        ("supply_voltage_min", "voltage"),
        ("no_load_speed_max", "angular_velocity"),
        ("phase_margin_nominal", "angle"),
        ("gain_margin_upper", "modulus"),
        ("stall_current_applied", "current"),
        ("ambient_temperature_typical", "temperature"),
        ("duty_cycle_max", "duty_cycle"),
        ("mass_estimated", "mass"),
        # two qualifiers, stripped in turn
        ("sensitivity_peak_lower_bound", "modulus"),
        ("computation_delay_measured_nominal", "time"),
        # a suffix, then a qualifier
        ("computation_delay_budget", "time"),
        ("gearbox_efficiency_implied", "efficiency"),
        ("cpu_utilisation_bound", "modulus"),
        ("cpu_utilization_bound", "modulus"),
        ("motor_off_latency_measured", "duration"),
        ("push_wheel_torque_indicative", "torque"),
        ("proposed_gain_margin_lower", "modulus"),
        ("pack_mass_estimated", "mass"),
    ],
)
def test_a_qualified_name_has_its_quantity_s_kind(name: str, kind: str) -> None:
    assert name not in QUANTITIES
    found = kind_of(name)
    assert found is not None and found is KINDS.get(kind), name


@pytest.mark.parametrize(
    "name",
    [
        # where or in which case: these change what the quantity is
        "stall_current_full_duty",
        "stall_torque_full_duty",
        "stall_current_turbo_charged",
        "torque_constant_wheel",
        "torque_constant_armature",
        "no_load_speed_wheel",
        "rotor_inertia_reflected",
        "mass_without_cells",
        "proposed_push_max_abs_tilt_nominal_fwd",
        # a qualifier word inside the name, another word ending it
        "stall_current_max_wheel",
        "supply_voltage_max_drop",
        # what is left after stripping is no name and has no suffix
        "overcurrent_trip_min",
        "command_max_measured",
        "coefficient_relative_difference_max",
        # a qualifier alone is not a name
        "max",
        "_max",
        "nominal_max",
        "max_min",
    ],
)
def test_a_word_outside_the_list_is_never_stripped(name: str) -> None:
    # Guard.
    assert kind_of(name) is None


@pytest.mark.parametrize("value", [1.8, 2.5, -0.4])
def test_a_full_duty_value_is_never_refused_as_a_duty_cycle(tmp_path: Path, value: float) -> None:
    # Guard: the withdrawn ``_duty`` suffix, or a ``_full_duty`` qualifier, would refuse these.
    view = _view(
        tmp_path,
        node(
            NODE,
            quantities={
                "stall_current_full_duty": (value, "1"),
                "stall_torque_full_duty": (value, "1"),
            },
        ),
    )
    ran = [check_units.run(_ctx(view)), check_magnitude.run(_ctx(view))]
    assert not any(o.outcome == "fail" for r in ran for o in r.observations)


def test_a_qualified_name_is_recorded_as_read_with_no_relation(tmp_path: Path) -> None:
    ran = _units(tmp_path, {"stall_current_max": (1.575, "A")})
    assert not any(o.outcome == "fail" for o in ran.observations)
    records = _naming(ran, "stall_current_max")
    assert records and all(o.outcome == "unchecked" for o in records)
    # The record is the reading's: its dimension and sign were read, and no relation forms.
    assert any("read against" in o.message and "no relation forms" in o.message for o in records), [
        o.message for o in records
    ]


@pytest.mark.parametrize(
    ("name", "value", "unit", "said"),
    [
        ("stall_current_max", 2, "V", "pint cannot convert 'volt' ([mass] * [length]**2"),
        ("supply_voltage_min", 5.4, "A", "pint cannot convert 'ampere' ([current]) to 'volt'"),
        ("motor_off_latency_max", -0.06, "s", "never negative"),
        ("sensitivity_peak_nominal", -2.0, "1", "never negative"),
        ("gearbox_efficiency_implied", -0.5, "1", "never negative"),
    ],
)
def test_a_qualified_name_s_mismatch_is_recorded_and_refuses_nothing(
    tmp_path: Path, name: str, value: float, unit: str, said: str
) -> None:
    ran = _units(tmp_path, {name: (value, unit)})
    assert not any(o.outcome == "fail" for o in ran.observations)
    mismatch = [o for o in _naming(ran, name) if "refuses nothing" in o.message]
    assert mismatch and said in mismatch[0].message and name in mismatch[0].message


def test_a_qualified_name_of_an_envelope_kind_keeps_its_definitional_envelope(
    tmp_path: Path,
) -> None:
    # A maximum duty cycle above 1 is not a duty cycle: the span is the definition's, so it
    # holds for a qualified name as for a suffix name (research section 3b, change 1).
    inside = check_magnitude.run(
        _ctx(
            _view(
                tmp_path / "a",
                node(
                    NODE,
                    quantities={
                        "duty_cycle_max": (0.9, "1"),
                        "gearbox_efficiency_implied": (0.6776, "1"),
                    },
                ),
            )
        )
    )
    assert inside.evaluated == 2 and not any(o.outcome == "fail" for o in inside.observations)
    outside = check_magnitude.run(
        _ctx(_view(tmp_path / "b", node(NODE, quantities={"duty_cycle_max": (1.5, "1")})))
    )
    assert [o.outcome for o in outside.observations] == ["fail"]


def _headroom(tmp_path: Path, stall_name: str) -> Any:
    view = _view(
        tmp_path,
        node("electrical.driver", quantities={"current_limit": (1, "A")}),
        node(NODE, quantities={stall_name: (5, "A")}, constrains=["electrical.driver"]),
    )
    return check_power.run(_ctx(view, "system"))


def test_a_qualified_stall_current_is_held_to_no_current_limit(tmp_path: Path) -> None:
    # Guard, with its control: the same graph with the catalogue's name is refused.
    assert any(o.outcome == "fail" for o in _headroom(tmp_path / "a", "stall_current").observations)
    assert not any(
        o.outcome == "fail" for o in _headroom(tmp_path / "b", "stall_current_max").observations
    )


def _mass_sum(tmp_path: Path, part_name: str) -> Any:
    m = "mechanical"
    view = _view(
        tmp_path,
        node(f"{m}.robot", kind="module", domain=m, quantities={"mass": (1, "kg")}),
        node(f"{m}.pack", domain=m, quantities={part_name: (6, "kg")}, constrains=[f"{m}.robot"]),
    )
    return check_conservation.run(_ctx(view, "system"))


def test_a_qualified_mass_joins_no_mass_sum(tmp_path: Path) -> None:
    # Guard, with its control: the same graph with the catalogue's name is refused.
    assert any(o.outcome == "fail" for o in _mass_sum(tmp_path / "a", "mass").observations)
    assert not any(o.outcome == "fail" for o in _mass_sum(tmp_path / "b", "mass_max").observations)


def test_the_hooks_still_count_a_qualified_name_as_one_the_catalogue_lacks() -> None:
    # Guard: the reading is the gate's, not a licence for a writer.
    names = {"stall_current_max": 1, "mass_max": 2, "supply_voltage_min": 3, "stall_current": 4}
    expected = ("mass_max", "stall_current_max", "supply_voltage_min")
    assert unknown_names(names) == unknown_quantity_names(names) == expected
    assert shadowing_names(names) == shadowing_quantity_names(names) == ()


def test_the_record_names_each_reading_with_its_qualifier_words_in_order(tmp_path: Path) -> None:
    # The record says how each name was read: the quantity or suffix that is left, and the
    # words taken off, in the order they stand. A suffix name keeps its own record.
    ran = _units(
        tmp_path,
        {
            "stall_current_max": (1.575, "A"),
            "computation_delay_measured_nominal": (0.0013765625, "s"),
            "gyro_delay": (0.00481, "s"),
        },
    )
    qualified = _naming(ran, "stall_current_max")
    assert [o.details.quantities for o in qualified] == [
        ("computation_delay_measured_nominal", "stall_current_max")
    ]
    (record,) = qualified
    assert "computation_delay_measured_nominal by _delay + _measured_nominal" in record.message
    assert "stall_current_max by stall_current + _max" in record.message
    assert "words that say which value of it they are" in record.message
    assert "their suffix suggests" not in record.message
    (suffix,) = _naming(ran, "gyro_delay")
    assert suffix.details.quantities == ("gyro_delay",)
    assert "gyro_delay by _delay" in suffix.message


def test_a_qualified_mismatch_names_the_reading_with_its_words_in_order(tmp_path: Path) -> None:
    ran = _units(tmp_path, {"computation_delay_measured_nominal": (3, "m")})
    (mismatch,) = [
        o
        for o in _naming(ran, "computation_delay_measured_nominal")
        if "refuses nothing" in o.message
    ]
    assert "(_delay + _measured_nominal)" in mismatch.message
    assert "once the words that say which value it is are taken off" in mismatch.message
