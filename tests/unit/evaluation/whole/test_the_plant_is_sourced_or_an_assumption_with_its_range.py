"""The plant's parameters are each sourced or an assumption with a range, and derive as checked.

The derived figures are the independent parameter check's (D1-D11) and the fall figures the
independent semantics-and-fall check's, to the digits each gave; this
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
    plant = _plant()
    try:
        return plant.parse_plant(json.dumps(doc).encode())
    except plant.PlantError as exc:
        pytest.fail(f"the plant file was refused; it should be taken: {exc}")


def _refused(doc: dict[str, Any], says: str) -> None:
    plant = _plant()
    try:
        plant.parse_plant(json.dumps(doc).encode())
    except plant.PlantError as exc:
        assert says in str(exc), str(exc)
        return
    except Exception as exc:  # a refusal is a PlantError with its reason, never a crash
        pytest.fail(f"the plant file was refused by a crash, not a PlantError: {exc!r}")
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
        assert p.reason.startswith("Assumed (accepted 14.11.2026): "), name


def test_every_sourced_parameter_cites_its_source() -> None:
    for name, p in _parse(_draft()).parameters.items():
        if name in ASSUMED:
            continue
        assert any(
            s in p.source for s in ("brief criterion", "parts sheet", "Pololu", "Panasonic")
        ), name


def test_every_sourced_parameter_says_where_in_its_source_the_number_is_read() -> None:
    for name, p in _parse(_draft()).parameters.items():
        if name in ASSUMED:
            continue
        assert getattr(p, "locator", None), f"{name} names no locator"


#: The sourced or bounded values, as the sourcing gives them: (value, low, high).
SOURCED = {
    "rotor_inertia": (1e-8, 3e-9, 2e-8),
    "gearbox_friction": (0.0173, 0.009, 0.036),
    "cell_mass": (0.027, 0.027, 0.027640785046875),
    "kit_mass": (0.2, 0.19, 0.21),
    "motor_no_load_current": (0.15, 0.075, 0.225),
}


@pytest.mark.parametrize("name", sorted(SOURCED))
def test_the_draft_holds_the_sourced_value_and_range(name: str) -> None:
    p = _parse(_draft()).parameters[name]
    value, low, high = SOURCED[name]
    assert (p.value, p.low, p.high) == pytest.approx((value, low, high), rel=1e-9)


def test_the_cell_s_figure_is_marked_as_read_from_a_third_party_copy() -> None:
    p = _parse(_draft()).parameters["cell_mass"]
    assert "Panasonic" in p.source
    assert "third-party copy" in p.source


def test_the_robot_as_built_weighs_what_the_sourcing_sums() -> None:
    bodies = _plant().bodies(_values())
    assert bodies.body_mass == pytest.approx(0.3223, abs=5e-5)
    assert bodies.body_mass + bodies.wheels_mass == pytest.approx(0.362, abs=5e-4)


def test_the_body_s_assumed_inertia_is_the_envelope_box_at_the_sourced_mass() -> None:
    p = _parse(_draft()).parameters["body_inertia"]
    box = _plant().bodies(_values()).body_mass * (0.118**2 + 0.080**2) / 12
    assert (p.value, p.low, p.high) == pytest.approx((box, box / 2, 1.5 * box), rel=1e-9)


def _cased_unmeasured(doc: dict[str, Any]) -> None:
    doc["parameters"]["com_height"].update(source="Assumption")
    doc["parameters"]["com_height"].pop("measure_by")


def _frozen_assumption_at_a_point(doc: dict[str, Any]) -> None:
    doc.update(status="frozen")
    p = doc["parameters"]["com_height"]
    p.update(low=p["value"], high=p["value"])


def test_a_draft_may_hold_an_assumption_at_a_point_for_a_fixture() -> None:
    plant = _plant()
    doc = copy.deepcopy(_draft())
    p = doc["parameters"]["com_height"]
    p.update(low=p["value"], high=p["value"])
    try:
        taken = plant.parse_plant(json.dumps(doc).encode())
    except plant.PlantError as exc:
        pytest.fail(f"a draft holding an assumption at a point was refused: {exc}")
    assert taken.status == "draft"
    assert taken.parameters["com_height"].low == p["value"]
    # The same file, frozen, is refused, and for that reason.
    doc.update(status="frozen")
    _refused(doc, "an assumption held at a point in a frozen plant")


def test_a_frozen_plant_with_every_assumption_ranged_is_taken() -> None:
    doc = copy.deepcopy(_draft())
    doc.update(status="frozen")
    assert _parse(doc).status == "frozen"


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
        (lambda d: d["parameters"]["kit_mass"].update(source="   "), "names no source"),
        (lambda d: d["parameters"]["kit_mass"].pop("locator", None), "names no locator"),
        (lambda d: d["parameters"]["kit_mass"].update(locator="  "), "names no locator"),
        (_frozen_assumption_at_a_point, "a point"),
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
        "source_blank",
        "cited_without_locator",
        "cited_with_blank_locator",
        "frozen_assumption_point",
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


#: The parts sheet's cell (R5.07, 0.97 oz), which the parameter check and the fall check used.
PARTS_SHEET_CELL = 0.02749903743125


def test_the_bodies_derive_as_the_parameter_check_recomputed_them() -> None:
    bodies = _plant().bodies(_values(cell_mass=PARTS_SHEET_CELL))
    assert bodies.body_mass == pytest.approx(0.32530, rel=2e-5)  # D10
    assert bodies.body_mass + bodies.wheels_mass == pytest.approx(0.36499, rel=2e-5)
    assert bodies.wheels_inertia / 2 == pytest.approx(1.5876e-5, rel=1e-4)  # D11


def test_the_wheels_inertia_is_the_factor_the_plant_states_times_m_w_r_squared() -> None:
    # The draft's factor is 0.5 (a disc); at 1.0 (a ring) the wheels' inertia is m_w·r².
    for factor in (1.0, 0.75):
        values = _values(wheel_inertia_factor=factor)
        bodies = _plant().bodies(values)
        want = factor * 2 * values["wheel_mass"] * values["wheel_radius"] ** 2
        assert bodies.wheels_inertia == pytest.approx(want, rel=1e-12), factor


def test_the_exact_gear_ratio_is_within_the_brief_s_half_percent() -> None:
    ratio = _values()["gear_ratio"]
    assert ratio == pytest.approx(110.242, abs=5e-4)
    assert abs(ratio - 110.25) / 110.25 < 0.005


def test_the_stall_current_at_the_kit_s_limit_is_the_brief_s_reading() -> None:
    assert _plant().stall_current(_values(), 0.75) == pytest.approx(1.35, rel=1e-12)
    assert _plant().stall_current(_values(), 1.0) == pytest.approx(1.8, rel=1e-12)


def _checked_body(**over: float) -> dict[str, float]:
    """The body the fall check used: 0.057 m above the axle, k = 0.0412 m, its own masses."""
    values = _values(cell_mass=PARTS_SHEET_CELL)
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
    doc = copy.deepcopy(_draft())
    for p in doc["parameters"].values():
        p.pop("bounded", None)
    plant = _parse(doc)
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


#: This test's own statement of the draft's ranged parameters the powered loop reads.
LOOP_RANGED = (
    "wheel_radius",
    "kit_mass",
    "wheel_mass",
    "cell_mass",
    "com_height",
    "body_inertia",
    "wheel_inertia_factor",
    "rotor_inertia",
    "motor_no_load_speed",
    "motor_no_load_current",
)


def test_the_draft_s_corners_number_two_to_the_ranged_parameters_read() -> None:
    plant_module = _plant()
    try:
        plant = _parse(_draft())
    except plant_module.PlantError as exc:
        pytest.fail(f"the draft was refused: {exc}")
    # Which parameters range is stated here, so a count can never agree with a wrong list.
    assert plant_module.ranged(plant, plant_module.LOOP_INPUTS) == LOOP_RANGED
    assert plant_module.ranged(plant, plant_module.STALL_INPUTS) == ()
    assert sum(1 for _ in plant_module.corners(plant, plant_module.STALL_INPUTS)) == 1
    assert sum(1 for _ in plant_module.corners(plant, plant_module.LOOP_INPUTS)) == 2**10
    every = tuple(plant_module.PLANT_UNITS)
    assert sum(1 for _ in plant_module.corners(plant, every)) == 2**11


#: This test's own statement of the most parameters a plant may range.
MOST_RANGED = 12


def _ranging(extra: tuple[str, ...]) -> dict[str, Any]:
    """The draft with ``extra`` (each a point in the draft) given a range about its value."""
    doc = copy.deepcopy(_draft())
    for name in extra:
        p = doc["parameters"][name]
        assert p["low"] == p["high"], name
        p.update(low=p["value"] * 0.99, high=p["value"] * 1.01)
    return doc


def test_the_cap_on_ranged_parameters_is_stated_as_data() -> None:
    assert getattr(_plant(), "MAX_RANGED", None) == MOST_RANGED


def test_a_plant_ranging_as_many_parameters_as_the_cap_is_taken() -> None:
    plant_module = _plant()
    plant = _parse(_ranging(("pack_voltage",)))
    assert len(plant_module.ranged(plant, tuple(plant_module.PLANT_UNITS))) == MOST_RANGED


def test_a_plant_ranging_more_parameters_than_the_cap_is_refused() -> None:
    _refused(_ranging(("pack_voltage", "motor_rated_voltage")), f"at most {MOST_RANGED}")


def test_corners_refuse_more_ranged_parameters_than_the_cap_before_any_corner() -> None:
    # A plant built without parse_plant: corners() holds the cap itself, and refuses before
    # it yields, so no caller can enumerate 2**13 corners.
    plant_module = _plant()
    raw = json.dumps(_ranging(("pack_voltage", "motor_rated_voltage")))
    unchecked = plant_module.PlantFile.model_validate_json(raw)
    with pytest.raises(plant_module.PlantError, match=f"at most {MOST_RANGED}"):
        next(plant_module.corners(unchecked, tuple(plant_module.PLANT_UNITS)))


@pytest.mark.parametrize(
    ("function", "inputs"),
    [("motor", "ELECTRICAL_INPUTS"), ("bodies", "MECHANICAL_INPUTS"), ("fall", "FALL_INPUTS")],
)
def test_each_derivation_reads_only_the_inputs_it_declares(function: str, inputs: str) -> None:
    plant = _plant()
    names = getattr(plant, inputs)
    only = {k: v for k, v in _values().items() if k in names}
    try:
        from_declared = getattr(plant, function)(only)
    except KeyError as exc:
        pytest.fail(f"{function} reads {exc}, which {inputs} does not declare")
    assert from_declared == getattr(plant, function)(_values())


def test_the_stall_current_reads_only_its_declared_inputs() -> None:
    plant = _plant()
    only = {k: v for k, v in _values().items() if k in plant.STALL_INPUTS}
    try:
        from_declared = plant.stall_current(only, 0.75)
    except KeyError as exc:
        pytest.fail(f"the stall current reads {exc}, which STALL_INPUTS does not declare")
    assert from_declared == plant.stall_current(_values(), 0.75)


def test_the_loop_reads_every_parameter_but_the_gearbox_friction() -> None:
    plant = _plant()
    assert set(plant.LOOP_INPUTS) == set(plant.PLANT_UNITS) - {"gearbox_friction"}
    assert set(plant.FALL_INPUTS) >= set(plant.MECHANICAL_INPUTS) | {"gearbox_friction"}
