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
    """The loop ``legacy`` as a law over the signals: the gains of metres in radians of wheel.

    ``radius`` is the wheel radius the gains are folded with. The equivalence rows pass each
    corner's own radius, which takes the radius as known; a firmware has one number for it, so a
    design written as a law and as a named structure score differently at a radius off the
    one folded in (the law being the more faithful), as the off-nominal row below states.
    """
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
        # The law's gains are re-folded with this corner's radius: the radius is taken as known,
        # which is the only condition under which the two paths agree (see the off-nominal row).
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
    system = loop_module.system(values, law)
    held = system.held
    assert held is not None
    assert held.shape[1] == 1
    # The mode is held at every gain, not only at 1: the closed loop returns it unchanged.
    for gain in (0.3, 1.0, 7.0):
        residual = loop_module.closed(system, gain) @ held - held
        assert float(abs(residual).max()) <= 1e-12
    # and it has the wheels' angle and the memory in it, as the named form's offset has.
    assert abs(held[loop_module.TRAVEL, 0]) > 0.0
    assert abs(held[system.ap.shape[0] :, 0]).max() > 0.0


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


@pytest.mark.parametrize(
    ("scale", "named", "written"),
    [
        # The same design (the good gains, in 1/m for the named form, in 1/rad for the law),
        # judged on a plant whose wheel radius is off the nominal one by 5 %: the margins
        # (phase margin in degrees, upward gain margin, downward gain margin) each way.
        (0.95, (69.5786, 4.0864, 0.4775), (68.5502, 4.3475, 0.4538)),
        (1.05, (66.9729, 4.0605, 0.4322), (67.5556, 3.8397, 0.4536)),
    ],
)
def test_a_design_written_as_a_law_and_as_a_named_structure_differ_at_an_off_nominal_radius(
    scale: float, named: tuple[float, float, float], written: tuple[float, float, float]
) -> None:
    """The equivalence above holds when the wheel radius is taken as known; here it is not.

    The row above re-folds the law's wheel gains with each corner's own radius, so the two paths
    agree to 1e-9 by construction. A law has one gain per radian of wheel, fixed by the firmware,
    while the plant's radius varies; the named structure's gain is per metre of the true travel,
    which is the same as a firmware that knows each corner's radius exactly. So at a radius off
    the nominal one the same design scores differently by how it is written. The law is the
    more faithful of the two (the firmware has one number for the wheel); the named form is the
    kinder to a design whose radius is uncertain. The scored margins at +-5 % (this file's timing,
    4.8 ms and 2 ms of delay) are those below: the upward gain margin differs by 0.26 at -5 % and
    by 0.22 at +5 %, the phase margin by 1.0 and 0.6 degrees. Written into the pre-registration.
    """
    plant = _plant()
    nominal_radius = nominal(plant)["wheel_radius"]
    values = {**nominal(plant), "wheel_radius": nominal_radius * scale}
    as_named = loop_module.margins(values, _si(_feedback(), values["wheel_radius"]))
    legacy = _si(_feedback(), nominal_radius)
    as_law = loop_module.margins(values, _si(_as_law(legacy, nominal_radius), nominal_radius, 3))
    for got, expected in ((as_named, named), (as_law, written)):
        assert got.stable
        assert got.phase_margin == pytest.approx(expected[0], abs=0.001)
        assert got.upward == pytest.approx(expected[1], abs=0.0001)
        assert got.downward == pytest.approx(expected[2], abs=0.0001)
    assert as_named.upward is not None and as_law.upward is not None
    assert abs(as_named.upward - as_law.upward) > 0.1


# ── a mode is set aside only if the law itself holds it at exactly 1 ─────────────────────────


def _law(
    terms: list[dict[str, Any]],
    coefficients: dict[str, Any],
    memory: list[dict[str, Any]] | None = None,
    lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A law over the nominal timing: ``terms`` are the command's, ``lines`` are the others."""
    return {
        "structure": "sampled_law",
        **_timing(),
        "coefficients": coefficients,
        "memory": memory or [],
        "lines": [*(lines or []), {"name": "command", "unit": "1", "terms": terms}],
        "command": "command",
    }


def _no_travel_terms() -> list[dict[str, Any]]:
    """The good gains on the tilt, its rate and the wheel speed, and nothing on the wheel angle."""
    return [
        {"sign": 1, "coefficients": ["angle_gain"], "of": "tilt"},
        {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
        {"sign": 1, "coefficients": ["speed_gain"], "of": "wheel_speed"},
    ]


def _good_coefficients(radius: float) -> dict[str, Any]:
    return {
        "angle_gain": _m(GOOD_GAINS[0], "1/rad"),
        "rate_gain": _m(GOOD_GAINS[1], "s/rad"),
        "distance_gain": _m(GOOD_GAINS[2] * radius, "1/rad"),
        "speed_gain": _m(GOOD_GAINS[3] * radius, "s/rad"),
    }


def _radius_of_loop(values: dict[str, float], loop: SiLoop) -> float:
    """The closed loop's true spectral radius, nothing set aside."""
    import numpy as np

    system = loop_module.system(values, loop)
    return float(np.max(np.abs(np.linalg.eigvals(loop_module.closed(system, 1.0)))))


def _with_inert_state(controller: dict[str, Any], pole: float, unit: str = "1") -> dict[str, Any]:
    """``controller`` plus one memory state that nothing reads, ``state[k] = pole·state[k-1]``."""
    out = copy.deepcopy(controller)
    out["coefficients"]["pole"] = _m(pole, "1")
    out["memory"].append({"name": "inert", "unit": unit, "next": "inert_now"})
    out["lines"].insert(
        0,
        {
            "name": "inert_now",
            "unit": unit,
            "terms": [{"sign": 1, "coefficients": ["pole"], "of": "previous.inert"}],
        },
    )
    return out


def _with_loud_state(controller: dict[str, Any], big: float) -> dict[str, Any]:
    """``controller`` plus a state fed ``big·tilt`` that nothing reads: a large coefficient."""
    out = copy.deepcopy(controller)
    out["coefficients"]["big"] = _m(big, "1/rad")
    out["memory"].append({"name": "loud", "unit": "1", "next": "loud_now"})
    out["lines"].insert(
        0,
        {
            "name": "loud_now",
            "unit": "1",
            "terms": [{"sign": 1, "coefficients": ["big"], "of": "tilt"}],
        },
    )
    return out


def _stable_law(radius: float) -> dict[str, Any]:
    """The good gains with the wheel-angle gain: it holds the travel, and is stable."""
    wheel = {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}
    return _law([*_no_travel_terms(), wheel], _good_coefficients(radius))


def _loop_of(controller: dict[str, Any], values: dict[str, float]) -> SiLoop:
    return _si(controller, values["wheel_radius"], version=3)


def test_a_law_with_no_wheel_angle_gain_is_unstable_with_or_without_an_inert_memory_state() -> None:
    values = nominal(_plant())
    plain = _law(_no_travel_terms(), _good_coefficients(values["wheel_radius"]))
    inert = _with_inert_state(plain, 1.0)
    for controller in (plain, inert):
        loop = _loop_of(controller, values)
        assert _radius_of_loop(values, loop) >= 1.0 - 1e-9, "nothing holds the travel"
        assert loop_module.margins(values, loop).stable is False


def test_only_the_inert_state_is_set_aside_never_the_plant_s_own_travel() -> None:
    values = nominal(_plant())
    plain = _law(_no_travel_terms(), _good_coefficients(values["wheel_radius"]))
    system = loop_module.system(values, _loop_of(_with_inert_state(plain, 1.0), values))
    assert system.held is not None
    assert system.held.shape[1] == 1
    assert loop_module.system(values, _loop_of(plain, values)).held is None


@pytest.mark.parametrize("gain", [-1e-6, -1e-8])
def test_a_command_fed_integrator_with_a_tiny_gain_is_unstable_not_set_aside(gain: float) -> None:
    values = nominal(_plant())
    radius = values["wheel_radius"]
    controller = _stable_law(radius)
    controller["coefficients"]["ki"] = _m(gain, "1/rad")
    controller["memory"].append({"name": "total", "unit": "rad", "next": "total_now"})
    controller["lines"].insert(
        0,
        {
            "name": "total_now",
            "unit": "rad",
            "terms": [
                {"sign": 1, "of": "previous.total"},
                {"sign": 1, "of": "wheel_angle"},
            ],
        },
    )
    controller["lines"][-1]["terms"].append(
        {"sign": 1, "coefficients": ["ki"], "of": "previous.total"}
    )
    loop = _loop_of(controller, values)
    assert _radius_of_loop(values, loop) > 1.0 + 1e-8, "the loop really grows"
    assert loop_module.margins(values, loop).stable is False


@pytest.mark.parametrize("big", [1e3, 1e6])
@pytest.mark.parametrize("pole", [1.001, 1.0001])
def test_an_unstable_pole_is_not_set_aside_because_a_large_coefficient_sits_elsewhere(
    big: float, pole: float
) -> None:
    values = nominal(_plant())
    controller = _with_loud_state(_with_inert_state(_stable_law(values["wheel_radius"]), pole), big)
    loop = _loop_of(controller, values)
    assert _radius_of_loop(values, loop) >= pole - 1e-9
    assert loop_module.margins(values, loop).stable is False


@pytest.mark.parametrize(
    ("pole", "stable"),
    [(1.0 + 1e-10, False), (1.0 - 1e-10, True), (1.0 - 1e-13, False), (1.0 - 1e-11, True)],
)
def test_a_pole_just_off_1_is_judged_at_the_stated_absolute_tolerance(
    pole: float, stable: bool
) -> None:
    values = nominal(_plant())
    controller = _with_inert_state(_stable_law(values["wheel_radius"]), pole)
    assert loop_module.margins(values, _loop_of(controller, values)).stable is stable


def test_states_a_law_holds_at_exactly_1_by_its_lines_are_set_aside_and_change_nothing() -> None:
    values = nominal(_plant())
    base = _stable_law(values["wheel_radius"])
    margins = loop_module.margins(values, _loop_of(base, values))
    assert margins.stable
    inert = _with_inert_state(base, 1.0)
    # Two states that share one sum: each next value is the mean of both, so (1, 1) is held.
    shared = copy.deepcopy(base)
    shared["coefficients"]["half"] = _m(0.5, "1")
    shared["memory"] += [
        {"name": "left", "unit": "1", "next": "left_now"},
        {"name": "right", "unit": "1", "next": "right_now"},
    ]
    for name in ("left_now", "right_now"):
        shared["lines"].insert(
            0,
            {
                "name": name,
                "unit": "1",
                "terms": [
                    {"sign": 1, "coefficients": ["half"], "of": "previous.left"},
                    {"sign": 1, "coefficients": ["half"], "of": "previous.right"},
                ],
            },
        )
    for controller in (inert, shared):
        loop = _loop_of(controller, values)
        system = loop_module.system(values, loop)
        assert system.held is not None
        assert system.held.shape[1] == 1, "one mode at 1: the shared sum, or the inert state"
        again = loop_module.margins(values, loop)
        assert again.stable
        for field in ("phase_margin", "upward", "downward"):
            assert _same(getattr(again, field), getattr(margins, field))


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


@pytest.mark.parametrize(
    ("of", "name"),
    [
        ("accelerometer_tilt", "out_of_scope"),
        ("line.phi_hat*tilt_rate", "nonlinear"),
        ("abs(line.phi_hat)", "nonlinear"),
    ],
)
def test_a_law_the_scorer_cannot_judge_is_refused_by_name_and_never_scored_as_a_fail(
    tmp_path: Path, of: str, name: str
) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    controller = _recorded_controller()
    command = next(x for x in controller["lines"] if x["name"] == "command")
    command["terms"][0]["of"] = of
    path = root / "refused.json"
    path.write_bytes(_answer(controller, 3))
    record = scenario.record(path)
    assert record["refusal"]["name"] == name
    assert name in record["refusal"]["reason"]
    assert record["outcome"] == "unscored"
    assert scenario.score(path) == "unscored"
    assert record["specs"] == []


def test_a_law_that_is_merely_malformed_is_still_a_fail(tmp_path: Path) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    controller = _recorded_controller()
    del controller["command"]
    path = root / "malformed.json"
    path.write_bytes(_answer(controller, 3))
    record = scenario.record(path)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "refusal" not in record


@pytest.mark.parametrize("change", ["a term's sign", "a memory source", "a term's number"])
def test_two_laws_with_the_same_coefficients_and_different_lines_are_not_compared(
    tmp_path: Path, change: str
) -> None:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    document = json.loads(_answer(_recorded_controller(), 3))
    twin = copy.deepcopy(document["controller"])
    command = next(x for x in twin["lines"] if x["name"] == "command")
    if change == "a term's sign":
        command["terms"][4]["sign"] = 1
    elif change == "a memory source":
        twin["memory"][1]["next"] = "theta_now"
    else:
        command["terms"][2]["number"] = 2
    document["analysed_controller"] = twin
    path = root / "lines.json"
    path.write_text(json.dumps(document))
    row = {r["name"]: r for r in scenario.record(path)["specs"]}["same"]
    assert row["verdict"] == "unscored", row
    assert "differ in their lines" in row["reason"]


# ── a scope refusal is unscored only for an answer that is otherwise valid ──────────────────


def _out_of_scope(controller: dict[str, Any]) -> dict[str, Any]:
    twisted = copy.deepcopy(controller)
    command = next(x for x in twisted["lines"] if x["name"] == "command")
    command["terms"][0]["of"] = "accelerometer_tilt"
    return twisted


def _record_of(tmp_path: Path, document: dict[str, Any]) -> dict[str, Any]:
    scenario, root = _scenario(tmp_path, copy.deepcopy(SPECS))
    path = root / "scope.json"
    path.write_text(json.dumps(document))
    return scenario.record(path)


def test_an_answer_invalid_for_another_reason_is_a_fail_whatever_its_law_says(
    tmp_path: Path,
) -> None:
    document = json.loads(_answer(_out_of_scope(_recorded_controller()), 3))
    document["parameters"]["update_rate"] = _m(-5, "Hz")
    record = _record_of(tmp_path, document)
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert "refusal" not in record


def test_an_unstable_primary_with_an_analysed_law_out_of_scope_is_a_fail(tmp_path: Path) -> None:
    primary = _recorded_controller()
    primary["coefficients"]["k_theta"]["value"] = 1.0  # the wrong sign: it falls over
    document = json.loads(_answer(primary, 3))
    document["analysed_controller"] = _out_of_scope(_recorded_controller())
    record = _record_of(tmp_path, document)
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "fail"
    assert record["outcome"] == "fail"


def test_a_scorable_primary_with_an_analysed_law_out_of_scope_is_judged_not_failed(
    tmp_path: Path,
) -> None:
    document = json.loads(_answer(_recorded_controller(), 3))
    document["analysed_controller"] = _out_of_scope(_recorded_controller())
    record = _record_of(tmp_path, document)
    rows = {r["name"]: r for r in record["specs"]}
    assert rows["pm"]["verdict"] == "pass"
    assert rows["up"]["verdict"] == "pass"
    assert rows["same"]["verdict"] == "unscored"
    assert "out of the scorer's reach" in rows["same"]["reason"]
    assert record["analysed_refusal"]["name"] == "out_of_scope"
    assert record["outcome"] == "unscored"
    assert "refusal" not in record


def test_a_valid_answer_whose_primary_law_is_out_of_scope_is_unscored_by_name(
    tmp_path: Path,
) -> None:
    document = json.loads(_answer(_out_of_scope(_recorded_controller()), 3))
    record = _record_of(tmp_path, document)
    assert record["refusal"]["name"] == "out_of_scope"
    assert record["outcome"] == "unscored"
    assert record["specs"] == []


def test_the_no_statement_flag_reaches_every_row_and_the_record(tmp_path: Path) -> None:
    flagged = _recorded_controller()
    flagged["no_interface_statement"] = ["command_limit", "sensor_delay"]
    record = _record_of(tmp_path, json.loads(_answer(flagged, 3)))
    assert record["no_interface_statement"] == ["command_limit", "sensor_delay"]
    assert all(
        r["no_interface_statement"] == ["command_limit", "sensor_delay"] for r in record["specs"]
    )
    (tmp_path / "held").mkdir()
    held = _record_of(tmp_path / "held", json.loads(_answer(_recorded_controller(), 3)))
    assert held["no_interface_statement"] == []
    assert all(r["no_interface_statement"] == [] for r in held["specs"])
