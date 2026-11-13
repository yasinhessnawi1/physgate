"""The plant's parameters are each sourced or an assumption with a range, and derive as checked.

The derived figures are the independent parameter check's of 11.11 (D1-D11) and the fall
figures the independent semantics-and-fall check's of 13.11, to the digits each gave; this
test holds the module to them, not to its own arithmetic.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MODULE = "physgate.evaluation.whole.plant"
_DRAFT = Path(__file__).resolve().parents[4] / "src/physgate/evaluation/whole/plant_v0_draft.json"

#: This test's own statement of the parameters no source gives.
ASSUMED = {
    "com_height",
    "body_inertia",
    "wheel_inertia_factor",
    "rotor_inertia",
    "gearbox_friction",
}


def _plant() -> ModuleType:
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return importlib.import_module(_MODULE)


def _draft() -> dict[str, Any]:
    assert _DRAFT.is_file(), f"no draft parameter file at {_DRAFT}"
    loaded: dict[str, Any] = json.loads(_DRAFT.read_text())
    return loaded


def _parse(doc: dict[str, Any]) -> Any:
    return _plant().parse_plant(json.dumps(doc).encode())


def _refused(doc: dict[str, Any], says: str) -> None:
    plant = _plant()
    try:
        plant.parse_plant(json.dumps(doc).encode())
    except plant.PlantError as exc:
        assert says in str(exc), str(exc)
        return
    pytest.fail(f"the plant file was taken; it should be refused for {says!r}")


def _values(**over: float) -> dict[str, float]:
    values: dict[str, float] = _plant().nominal(_parse(_draft()))
    values.update(over)
    return values


def test_the_draft_names_every_parameter_once_in_its_unit_and_is_a_draft() -> None:
    plant = _parse(_draft())
    assert plant.status == "draft"
    assert set(plant.parameters) == set(_plant().PLANT_UNITS)
    for name, p in plant.parameters.items():
        assert p.unit == _plant().PLANT_UNITS[name]


def test_the_assumptions_are_exactly_the_unpublished_parameters_each_with_a_measurement() -> None:
    plant = _parse(_draft())
    assumed = dict(_plant().assumptions(plant))
    assert set(assumed) == ASSUMED
    for name, p in assumed.items():
        assert p.measure_by, name
        assert p.low < p.high, name
        assert "PROPOSED" in p.reason, name


def test_every_sourced_parameter_cites_its_source() -> None:
    for name, p in _parse(_draft()).parameters.items():
        if name in ASSUMED:
            continue
        assert any(s in p.source for s in ("brief criterion", "parts sheet", "Pololu item")), name


def _cased_unmeasured(doc: dict[str, Any]) -> None:
    doc["parameters"]["com_height"].update(source="Assumption")
    doc["parameters"]["com_height"].pop("measure_by")


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda d: d["parameters"].pop("com_height"), "lacks"),
        (lambda d: d["parameters"].update(extra=d["parameters"]["kit_mass"]), "no use"),
        (lambda d: d["parameters"]["kit_mass"].update(unit="g"), "'kg'"),
        (lambda d: d["parameters"]["kit_mass"].update(value=0.3), "low first"),
        (lambda d: d["parameters"]["kit_mass"].update(low=0.25), "low first"),
        (lambda d: d["parameters"]["kit_mass"].update(value=0.0, low=0.0), "positive"),
        (lambda d: d["parameters"]["com_height"].pop("measure_by"), "measurement"),
        (_cased_unmeasured, "measurement"),
        (lambda d: d.update(status="final"), "plant parameter file"),
        (lambda d: d["parameters"]["kit_mass"].update(value="0.2"), "plant parameter file"),
    ],
    ids=[
        "missing",
        "unknown",
        "unit",
        "above_range",
        "range_reversed",
        "zero",
        "assumption_unmeasured",
        "assumption_cased_unmeasured",
        "status",
        "string",
    ],
)
def test_a_plant_file_off_its_schema_is_refused(change: Any, says: str) -> None:
    doc = copy.deepcopy(_draft())
    change(doc)
    _refused(doc, says)


def test_nan_in_a_plant_file_is_refused() -> None:
    text = json.dumps(_draft()).replace('"value": 0.2,', '"value": NaN,', 1)
    assert "NaN" in text
    plant = _plant()
    with pytest.raises(plant.PlantError):
        plant.parse_plant(text.encode())


def test_the_motor_derives_as_the_parameter_check_recomputed_it() -> None:
    motor = _plant().motor(_values())
    assert motor.resistance == pytest.approx(4.0, rel=1e-12)  # D1
    assert motor.torque_constant / (45 / 21) == pytest.approx(0.053755, rel=2e-5)  # D2
    assert motor.back_emf_constant / (45 / 21) == pytest.approx(0.079332, rel=2e-5)  # D3
    assert motor.torque_constant == pytest.approx(0.11519, rel=5e-5)  # D5
    assert motor.back_emf_constant == pytest.approx(0.17000, rel=5e-5)  # D6
    assert motor.wheel_stall_torque == pytest.approx(0.19006, rel=5e-5)  # D7
    assert motor.wheel_no_load_speed == pytest.approx(38.82, rel=2e-4)  # D8
    assert motor.wheel_no_load_speed * 0.040 == pytest.approx(1.553, rel=5e-4)
    at_limit = (0.75 * 7.2 - 0.15 * motor.resistance) / motor.back_emf_constant
    assert at_limit == pytest.approx(28.24, rel=2e-4)  # D9


def test_the_bodies_derive_as_the_parameter_check_recomputed_them() -> None:
    bodies = _plant().bodies(_values())
    assert bodies.body_mass == pytest.approx(0.32530, rel=2e-5)  # D10
    assert bodies.body_mass + bodies.wheels_mass == pytest.approx(0.36499, rel=2e-5)
    assert bodies.wheels_inertia / 2 == pytest.approx(1.5876e-5, rel=1e-4)  # D11


def test_the_exact_gear_ratio_is_within_the_brief_s_half_percent() -> None:
    ratio = _values()["gear_ratio"]
    assert ratio == pytest.approx(110.242, abs=5e-4)
    assert abs(ratio - 110.25) / 110.25 < 0.005


def test_the_stall_current_at_the_kit_s_limit_is_the_brief_s_reading() -> None:
    assert _plant().stall_current(_values(), 0.75) == pytest.approx(1.35, rel=1e-12)
    assert _plant().stall_current(_values(), 1.0) == pytest.approx(1.8, rel=1e-12)


def _checked_body(**over: float) -> dict[str, float]:
    """The body the fall check used: 0.057 m above the axle, k = 0.0412 m, its own masses."""
    values = _values()
    mass = _plant().bodies(values).body_mass
    values.update(com_height=0.057, body_inertia=mass * 0.0412**2, **over)
    return values


def test_the_fall_s_three_readings_are_the_fall_check_s() -> None:
    reflected = 1.215e-3 / (2 * _values()["gear_ratio"] ** 2)
    fall = _plant().fall(_checked_body(rotor_inertia=reflected))
    assert fall.locked == pytest.approx(0.1428, rel=1e-3)
    assert fall.free == pytest.approx(0.0627, rel=2e-3)
    assert fall.geared == pytest.approx(0.1219, rel=1e-3)
    assert fall.free < fall.geared < fall.locked


@pytest.mark.parametrize(("scale", "tau"), [(0.5, 0.1100), (2.0, 0.1306)])
def test_the_geared_fall_moves_with_the_rotor_s_inertia_as_the_check_found(
    scale: float, tau: float
) -> None:
    reflected = scale * 1.215e-3 / (2 * _values()["gear_ratio"] ** 2)
    assert _plant().fall(_checked_body(rotor_inertia=reflected)).geared == pytest.approx(
        tau, rel=1e-3
    )


@pytest.mark.parametrize(
    ("friction", "degrees"),
    # The check's half, nominal and double of 0.01728 N*m, which its table rounds.
    [(0.01728 / 2, 14.9), (0.01728, 29.8), (0.01728 * 2, 59.5)],
)
def test_the_lock_holds_below_the_angle_the_check_found(friction: float, degrees: float) -> None:
    fall = _plant().fall(_checked_body(gearbox_friction=friction))
    assert fall.lock_torque_per_rad == pytest.approx(0.0666, rel=2e-3)
    assert math.degrees(fall.lock_angle) == pytest.approx(degrees, rel=5e-3)


def test_corners_vary_only_the_ranged_parameters_named() -> None:
    plant_module = _plant()
    plant = _parse(_draft())
    names = ("pack_voltage", "wheel_radius", "com_height")
    found = list(plant_module.corners(plant, names))
    assert len(found) == 4
    assert {(c["wheel_radius"], c["com_height"]) for c in found} == {
        (0.039, 0.005),
        (0.039, 0.078),
        (0.041, 0.005),
        (0.041, 0.078),
    }
    base = plant_module.nominal(plant)
    for corner in found:
        assert corner["pack_voltage"] == 7.2
        assert {k: v for k, v in corner.items() if k not in names} == {
            k: v for k, v in base.items() if k not in names
        }


def test_with_no_ranged_parameter_the_one_corner_is_the_nominal_set() -> None:
    plant_module = _plant()
    plant = _parse(_draft())
    assert list(plant_module.corners(plant, plant_module.STALL_INPUTS)) == [
        plant_module.nominal(plant)
    ]


@pytest.mark.parametrize(
    ("function", "inputs"),
    [("motor", "ELECTRICAL_INPUTS"), ("bodies", "MECHANICAL_INPUTS"), ("fall", "FALL_INPUTS")],
)
def test_each_derivation_reads_only_the_inputs_it_declares(function: str, inputs: str) -> None:
    plant = _plant()
    names = getattr(plant, inputs)
    only = {k: v for k, v in _values().items() if k in names}
    assert getattr(plant, function)(only) == getattr(plant, function)(_values())


def test_the_stall_current_reads_only_its_declared_inputs() -> None:
    plant = _plant()
    only = {k: v for k, v in _values().items() if k in plant.STALL_INPUTS}
    assert plant.stall_current(only, 0.75) == plant.stall_current(_values(), 0.75)


def test_the_loop_reads_every_parameter_but_the_gearbox_friction() -> None:
    plant = _plant()
    assert set(plant.LOOP_INPUTS) == set(plant.PLANT_UNITS) - {"gearbox_friction"}
    assert set(plant.FALL_INPUTS) >= set(plant.MECHANICAL_INPUTS) | {"gearbox_friction"}
