"""A sampled law is judged by the same loop analysis as the named structures, and gives the same.

The equivalence row is the guard that the new path changes nothing old: each named structure
of the closed list, written as a law (the same numbers, the wheel radius folded into the
gains as the law's signals are in radians), gives the same margins to 1e-9 at the plant's
nominal values and at every corner of the ranges it reads, the leak-free incremental form
(whose held offset the loop sets aside) included. Then the recorded design's law is scored
whole, and a version 2 answer with its old name and a version 3 answer with the catalogue's
name give the same metric.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import parse_answer
from physgate.evaluation.whole.convert import ScaleFactor, SiLoop, to_si
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal, parse_plant
from physgate.evaluation.whole.scenario import WholeDesignScenario, WholeDesignTask

_ROOT = Path(__file__).resolve().parents[2]
_DRAFT = _ROOT / "src/physgate/evaluation/whole/plant_v0_draft.json"
_RECORDED = _ROOT / "tests/unit/evaluation/whole/recorded_law/law.json"
TOLERANCE = 1e-9
GOOD_GAINS = (1.6643, 0.191, 0.2853, 1.3421)


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _timing(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
    }
    doc.update(over)
    return doc


def _feedback() -> dict[str, Any]:
    return {
        "structure": "state_feedback",
        **_timing(),
        "angle_gain": _m(GOOD_GAINS[0], "1/rad"),
        "rate_gain": _m(GOOD_GAINS[1], "s/rad"),
        "distance_gain": _m(GOOD_GAINS[2], "1/m"),
        "speed_gain": _m(GOOD_GAINS[3], "s/m"),
    }


def _incremental(decay: float | None) -> dict[str, Any]:
    """The reference kit's balancing example in SI, which balances the draft plant."""
    doc = {
        "structure": "incremental_rising_offset",
        **_timing(),
        "rate_ratio": _m(0.14, "s"),
        "angle_gain": _m(0.13984913700800736, "1/rad"),
        "distance_gain": _m(0.17308404749760797, "1/m"),
        "speed_gain": _m(0.07824347352631594, "s/m"),
    }
    if decay is not None:
        doc["angle_decay_per_update"] = _m(decay, "1")
    return doc


def _native() -> dict[str, Any]:
    return {
        "structure": "native_incremental_rising_offset",
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "update_time": _m(10, "ms"),
        "motor_speed_limit": _m(300, "count"),
        "angle_rate_ratio": _m(140, "ms"),
        "angle_response": _m(11, "1"),
        "distance_response": _m(73, "1"),
        "speed_response": _m(3300, "1"),
        "response_divisor": _m(100, "1"),
        "gear_ratio_coefficient": _m(111, "1"),
        "gyro_divisor": _m(29, "count*s/deg"),
        "angle_decay_numerator": _m(999, "1"),
        "angle_decay_denominator": _m(1000, "1"),
    }


SETTINGS = {
    "update_rate": _m(100, "Hz"),
    "gyro_full_scale": _m(1000, "deg/s"),
    "pwm_frequency": _m(20000, "Hz"),
    "pwm_full_scale": _m(400, "count"),
    "encoder_counts_per_wheel_revolution": _m(1322.9, "count"),
    "gyro_sensitivity": _m(28.571, "count*s/deg"),
}


def _answer(controller: dict[str, Any], version: int = 3) -> bytes:
    name = "output_data_rate" if version == 3 else "gyro_output_data_rate"
    return json.dumps(
        {
            "form": "whole_run",
            "version": version,
            "controller": controller,
            "parameters": {**SETTINGS, name: _m(208, "Hz")},
        }
    ).encode()


def _radius(value: float) -> ScaleFactor:
    return ScaleFactor("wheel_radius", value, "m", "this test's plant")


def _si(controller: dict[str, Any], radius: float, version: int = 2) -> SiLoop:
    answer = parse_answer(_answer(controller, version))
    return to_si(answer.controller, answer.parameters, wheel_radius=_radius(radius))


def _as_law(legacy: SiLoop, radius: float) -> dict[str, Any]:
    """The loop ``legacy`` as a law over the signals: the gains of metres in radians of wheel."""
    timing = {
        "period": _m(legacy.period, "s"),
        "command_limit": _m(legacy.command_limit, "1"),
        "sensor_delay": _m(legacy.sensor_delay, "s"),
        "compute_delay": _m(legacy.compute_delay, "s"),
    }
    wheel = {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}
    speed = {"sign": 1, "coefficients": ["speed_gain"], "of": "wheel_speed"}
    coefficients = {
        "angle_gain": _m(legacy.angle, "1/rad"),
        "rate_gain": _m(legacy.rate, "s/rad"),
        "distance_gain": _m(legacy.distance * radius, "1/rad"),
        "speed_gain": _m(legacy.speed * radius, "s/rad"),
    }
    if not legacy.incremental:
        return {
            "structure": "sampled_law",
            **timing,
            "coefficients": coefficients,
            "memory": [],
            "lines": [
                {
                    "name": "command",
                    "unit": "1",
                    "terms": [
                        {"sign": 1, "coefficients": ["angle_gain"], "of": "tilt"},
                        {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
                        wheel,
                        speed,
                    ],
                }
            ],
            "command": "command",
        }
    coefficients["decay"] = _m(legacy.decay, "1")
    return {
        "structure": "sampled_law",
        **timing,
        "coefficients": coefficients,
        "memory": [
            {"name": "angle", "unit": "rad", "next": "angle_now"},
            {"name": "applied", "unit": "1", "next": "command", "applied": True},
        ],
        "lines": [
            {
                "name": "angle_now",
                "unit": "rad",
                "terms": [
                    {"sign": 1, "coefficients": ["decay"], "of": "previous.angle"},
                    {"sign": 1, "coefficients": ["decay", "period"], "of": "tilt_rate"},
                ],
            },
            {
                "name": "command",
                "unit": "1",
                "terms": [
                    {"sign": 1, "of": "previous.applied"},
                    {"sign": 1, "coefficients": ["angle_gain"], "of": "line.angle_now"},
                    {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
                    wheel,
                    speed,
                ],
            },
        ],
        "command": "command",
    }


def _plant() -> Any:
    doc = json.loads(_DRAFT.read_text())
    for p in doc["parameters"].values():
        p.pop("bounded", None)
        p["low"] = p["high"] = p["value"]
    for name in ("wheel_radius", "com_height", "body_inertia", "motor_no_load_current"):
        p = doc["parameters"][name]
        if name == "wheel_radius":
            p["low"], p["high"] = 0.039, 0.041
        else:
            p["low"], p["high"] = p["value"] * 0.5, p["value"] * 1.5
    return parse_plant(json.dumps(doc).encode())


def _same(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is second
    return first == second or abs(first - second) <= TOLERANCE


STRUCTURES = {
    "state_feedback": _feedback,
    "incremental_with_a_leak": lambda: _incremental(0.999),
    "incremental_without_a_leak": lambda: _incremental(None),
    "native_incremental": _native,
}


@pytest.mark.parametrize("name", sorted(STRUCTURES))
def test_a_named_structure_written_as_a_law_gives_the_same_margins_to_1e_9(name: str) -> None:
    plant = _plant()
    points = [nominal(plant), *corners(plant, LOOP_INPUTS)]
    assert len(points) == 1 + 2**4
    judged = 0
    worst = 0.0
    for values in points:
        radius = values["wheel_radius"]
        legacy = _si(STRUCTURES[name](), radius)
        law = _si(_as_law(legacy, radius), radius, version=3)
        assert law.law is not None
        old = loop_module.margins(values, legacy)
        new = loop_module.margins(values, law)
        assert new.stable == old.stable, (name, values["wheel_radius"])
        assert new.crossed == old.crossed
        for field in ("phase_margin", "upward", "downward"):
            first, second = getattr(old, field), getattr(new, field)
            assert _same(first, second), (name, field, first, second)
            if first is not None and second is not None and math.isfinite(first):
                worst = max(worst, abs(first - second))
        judged += old.stable
    assert judged > 0, f"{name} is stable at no point: the row proves nothing"
    assert worst <= TOLERANCE


def test_the_leak_free_form_has_its_held_offset_set_aside_by_the_law_as_by_the_named_form() -> None:
    values = nominal(_plant())
    legacy = _si(_incremental(None), values["wheel_radius"])
    law = _si(_as_law(legacy, values["wheel_radius"]), values["wheel_radius"], version=3)
    assert loop_module.system(values, legacy).neutral is not None
    held = loop_module.system(values, law).held
    assert held is not None
    assert held.shape[1] == 1


def test_a_law_with_nothing_held_has_no_mode_set_aside() -> None:
    values = nominal(_plant())
    legacy = _si(_incremental(0.999), values["wheel_radius"])
    law = _si(_as_law(legacy, values["wheel_radius"]), values["wheel_radius"], version=3)
    assert loop_module.system(values, law).held is None


def test_a_law_with_no_distance_gain_does_not_have_the_plant_s_travel_set_aside() -> None:
    values = nominal(_plant())
    controller = _incremental(None)
    controller["distance_gain"] = _m(0.0, "1/m")
    legacy = _si(controller, values["wheel_radius"])
    law = _si(_as_law(legacy, values["wheel_radius"]), values["wheel_radius"], version=3)
    assert loop_module.margins(values, legacy).stable is False
    assert loop_module.margins(values, law).stable is False


def test_the_work_bound_counts_the_law_s_memory_states() -> None:
    values = nominal(_plant())
    radius = values["wheel_radius"]
    legacy = _si(_incremental(0.999), radius)
    law = _si(_as_law(legacy, radius), radius, version=3)
    assert loop_module.states(law) == loop_module.states(legacy)
    feedback = _si(_feedback(), radius)
    stateless = _si(_as_law(feedback, radius), radius, version=3)
    assert loop_module.states(stateless) == loop_module.states(feedback)
    recorded = _recorded(radius)
    assert loop_module.states(recorded) == loop_module.states(stateless) + 3


def _recorded_controller() -> dict[str, Any]:
    body = json.loads(_RECORDED.read_text())
    coefficients = {
        "k_phi": _m(-0.0054505, "1/rad"),
        "k_theta": _m(-1.03529, "1/rad"),
        "k_w": _m(-0.038326, "s/rad"),
        "k_rate": _m(-0.0625146, "s/rad"),
        "k_u": _m(-0.346975, "1"),
        "leak": _m(0.999, "1"),
    }
    return {
        "structure": "sampled_law",
        **{key: body[key] for key in ("memory", "lines", "command")},
        "coefficients": coefficients,
        **_timing(
            command_limit=_m(0.9425, "1"),
            sensor_delay=_m(1 / 208, "s"),
            compute_delay=_m(0.004, "s"),
        ),
    }


def _recorded(radius: float) -> SiLoop:
    return _si(_recorded_controller(), radius, version=3)


def test_the_recorded_design_s_law_is_judged_on_the_frozen_plant_s_draft() -> None:
    values = nominal(_plant())
    margins = loop_module.margins(values, _recorded(values["wheel_radius"]))
    assert margins.stable
    assert margins.crossed
    assert margins.phase_margin == pytest.approx(50.64, abs=0.01)
    assert margins.upward == pytest.approx(5.166, abs=0.001)
    assert margins.downward == pytest.approx(0.4262, abs=0.0001)


def _scenario(tmp_path: Path, specs: list[dict[str, Any]]) -> tuple[WholeDesignScenario, Path]:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    task = WholeDesignTask.model_validate_json(
        json.dumps({"id": "whole.fixture", "requirements": ["c5", "c15"], "specs": specs})
    )
    plant = json.dumps(_plant_doc()).encode()
    return WholeDesignScenario(task, plant, root=root, draft=True), root


def _plant_doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(_DRAFT.read_text())
    for p in doc["parameters"].values():
        p.pop("bounded", None)
        p["low"] = p["high"] = p["value"]
    return doc


SPECS: list[dict[str, Any]] = [
    {
        "name": "odr",
        "metric": "gyro_output_data_rate",
        "op": "in",
        "composes": ["c11"],
        "bound": [_m(208, "Hz"), _m(208, "Hz")],
    },
    {
        "name": "rate",
        "metric": "update_rate",
        "op": "in",
        "composes": ["c9"],
        "bound": [_m(99, "Hz"), _m(101, "Hz")],
    },
    {
        "name": "pm",
        "metric": "phase_margin",
        "op": ">=",
        "composes": ["c15"],
        "bound": _m(30, "deg"),
    },
    {
        "name": "up",
        "metric": "gain_margin_upward",
        "op": ">=",
        "composes": ["c16"],
        "bound": _m(2, "1"),
    },
    {
        "name": "same",
        "metric": "coefficient_difference",
        "op": "<=",
        "composes": ["c19"],
        "bound": _m(0, "1"),
    },
    {
        "name": "limit",
        "metric": "command_limit",
        "op": "in",
        "composes": ["c5"],
        "bound": [_m(0.9425, "1"), _m(0.9425, "1")],
    },
    {
        "name": "period",
        "metric": "controller_rate",
        "op": "in",
        "composes": ["c9"],
        "bound": [_m(100, "Hz"), _m(100, "Hz")],
    },
]


def test_the_old_name_in_version_2_and_the_catalogue_s_in_version_3_give_the_same_metric(
    tmp_path: Path,
) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    records = []
    for version in (2, 3):
        path = root / f"v{version}.json"
        path.write_bytes(_answer(_feedback(), version))
        records.append(scenario.record(path))
    old, new = records
    assert old["answer_valid"] and new["answer_valid"]
    assert old["specs"] == new["specs"]
    assert old["outcome"] == new["outcome"]
    odr = next(row for row in new["specs"] if row["metric"] == "gyro_output_data_rate")
    assert odr["measured"]["value"] == 208
    assert odr["verdict"] == "pass"


def test_a_sampled_law_is_scored_whole_and_its_record_names_its_structure(tmp_path: Path) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    path = root / "law.json"
    path.write_bytes(_answer(_recorded_controller(), 3))
    record = scenario.record(path)
    assert record["answer_valid"] is True
    assert record["structure"] == "sampled_law"
    assert "refusal" not in record
    rows = {row["name"]: row for row in record["specs"]}
    assert rows["pm"]["verdict"] == "pass"
    assert rows["up"]["verdict"] == "pass"
    # No analysed law is stated, so there is nothing to compare the firmware's with.
    assert rows["same"]["verdict"] == "unscored"
    assert rows["limit"]["verdict"] == "pass"
    assert rows["limit"]["measured"]["value"] == 0.9425
    assert rows["period"]["verdict"] == "pass"
    assert record["work"]["states"]["value"] == 8
    # Scored again, the record is the same: nothing in the law's path is random or timed.
    assert scenario.record(path) == record


def test_two_laws_naming_different_coefficients_are_not_compared(tmp_path: Path) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    controller = _recorded_controller()
    other = copy.deepcopy(controller)
    other["coefficients"]["extra"] = _m(1.0, "1")
    document = json.loads(_answer(controller, 3))
    document["analysed_controller"] = other
    path = root / "two.json"
    path.write_text(json.dumps(document))
    row = {r["name"]: r for r in scenario.record(path)["specs"]}["same"]
    assert row["verdict"] == "unscored"
    assert "different coefficients" in row["reason"]


def test_a_law_of_its_own_analysed_twin_differs_by_nothing(tmp_path: Path) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    document = json.loads(_answer(_recorded_controller(), 3))
    document["analysed_controller"] = copy.deepcopy(document["controller"])
    path = root / "twin.json"
    path.write_text(json.dumps(document))
    row = {r["name"]: r for r in scenario.record(path)["specs"]}["same"]
    assert row["verdict"] == "pass"
    document["analysed_controller"]["coefficients"]["k_u"]["value"] = -0.3
    path.write_text(json.dumps(document))
    row = {r["name"]: r for r in scenario.record(path)["specs"]}["same"]
    assert row["verdict"] == "fail"
    document["analysed_controller"]["coefficients"]["k_u"]["value"] = -0.346975
    document["analysed_controller"]["command_limit"]["value"] = 0.9
    path.write_text(json.dumps(document))
    row = {r["name"]: r for r in scenario.record(path)["specs"]}["same"]
    assert row["verdict"] == "fail"


def test_an_unstable_law_says_it_is_unstable_and_never_blames_a_distance_gain_it_has_not(
    tmp_path: Path,
) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    controller = _recorded_controller()
    controller["coefficients"]["k_theta"]["value"] = 1.0  # the wrong sign: it falls over
    path = root / "unstable.json"
    path.write_bytes(_answer(controller, 3))
    rows = {r["name"]: r for r in scenario.record(path)["specs"]}
    assert rows["pm"]["verdict"] == "fail"
    assert "unstable" in rows["pm"]["reason"]
    assert "distance gain" not in rows["pm"]["reason"]
