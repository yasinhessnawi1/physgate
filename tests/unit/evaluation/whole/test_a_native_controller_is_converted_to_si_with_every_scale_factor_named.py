"""A controller is converted to SI only for the loop, every scale factor named with its source.

The numbers below are this test's own statement of the conversion, written from the kit's
balancing code apart from the module: the angle in millidegrees, the rate in deg/s as the
firmware believes it (raw counts over its divisor), the two wheels' counts summed, the command
in PWM counts, and the change divided by the response divisor times the gear-ratio coefficient.
The published figures an independent check computed are held beside the formula.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
from types import ModuleType
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole.answer import WholeRun, parse_whole_run

_MODULE = "physgate.evaluation.whole.convert"
_RADIUS = 0.040
_RADIUS_SOURCE = "the environment's wheel radius (brief criterion 2)"


def _convert() -> ModuleType:
    """The converter, or a failed assertion if it does not exist."""
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return importlib.import_module(_MODULE)


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _native(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
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
    for field, value in over.items():
        doc[field] = _m(value, doc[field]["unit"])
    return doc


def _rising(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "structure": "incremental_rising_offset",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "rate_ratio": _m(0.14, "s"),
        "angle_gain": _m(0.3, "1/rad"),
        "distance_gain": _m(2.0, "1/m"),
        "speed_gain": _m(0.9, "s/m"),
    }
    doc.update(over)
    return doc


def _feedback() -> dict[str, Any]:
    return {
        "structure": "state_feedback",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0, "s"),
        "compute_delay": _m(0.002, "s"),
        "angle_gain": _m(4.0, "1/rad"),
        "rate_gain": _m(0.5, "s/rad"),
        "distance_gain": _m(1.0, "1/m"),
        "speed_gain": _m(1.5, "s/m"),
    }


def _answer(
    controller: dict[str, Any], *, sensitivity: float = 29.0, counts: float = 1322.9
) -> WholeRun:
    doc = {
        "form": "whole_run",
        "version": 2,
        "controller": controller,
        "parameters": {
            "update_rate": _m(100, "Hz"),
            "gyro_output_data_rate": _m(208, "Hz"),
            "gyro_full_scale": _m(1000, "deg/s"),
            "pwm_frequency": _m(20000, "Hz"),
            "pwm_full_scale": _m(400, "count"),
            "encoder_counts_per_wheel_revolution": _m(counts, "count"),
            "gyro_sensitivity": _m(sensitivity, "count*s/deg"),
        },
    }
    try:
        return parse_whole_run(json.dumps(doc).encode())
    except TaskFormatError as exc:
        pytest.fail(f"the answer is refused: {exc}")


def _si(read: WholeRun, which: str = "controller") -> Any:
    convert = _convert()
    radius = convert.ScaleFactor(
        name="wheel_radius", value=_RADIUS, unit="m", source=_RADIUS_SOURCE
    )
    return convert.to_si(getattr(read, which), read.parameters, wheel_radius=radius)


def _expected(
    *,
    angle: int = 11,
    distance: int = 73,
    speed: int = 3300,
    divisor: int = 100,
    gear: int = 111,
    ratio_ms: int = 140,
    gyro_divisor: int = 29,
    sensitivity: float = 29.0,
    counts: float = 1322.9,
    update_ms: int = 10,
) -> dict[str, float]:
    """The SI gains of the native constants, by this test's own reading of the code."""
    per_increment = divisor * gear * 400.0
    believed = sensitivity / gyro_divisor
    millidegrees_per_rad = 1000.0 * 180.0 / math.pi
    counts_per_metre = counts / (2.0 * math.pi * _RADIUS)
    k_angle = angle * believed * millidegrees_per_rad / per_increment
    return {
        "angle": k_angle,
        "rate": k_angle * ratio_ms / 1000.0,
        "distance": distance * 2.0 * counts_per_metre / per_increment,
        "speed": speed * 2.0 * (update_ms / 1000.0) * counts_per_metre / per_increment,
    }


def test_the_kit_s_constants_convert_to_the_gains_the_independent_check_computed() -> None:
    loop = _si(_answer(_native()))
    want = _expected()
    for gain in ("angle", "rate", "distance", "speed"):
        assert getattr(loop, gain) == pytest.approx(want[gain], rel=1e-12), gain
    # The check's figures, to the digits it gave (counts per metre from 1322.904 there).
    assert loop.angle == pytest.approx(0.14195, rel=5e-5)
    assert loop.rate / loop.angle == pytest.approx(0.140, rel=1e-12)
    assert loop.distance == pytest.approx(0.17308, rel=5e-5)
    assert loop.speed == pytest.approx(0.07824, rel=5e-5)


def test_the_loop_s_period_limit_decay_and_delays_come_from_the_native_integers() -> None:
    loop = _si(_answer(_native()))
    assert loop.incremental is True
    assert loop.period == pytest.approx(0.010, rel=1e-15)
    assert loop.command_limit == pytest.approx(0.75, rel=1e-15)
    assert loop.decay == pytest.approx(0.999, rel=1e-15)
    assert (loop.sensor_delay, loop.compute_delay) == (0.0048, 0.002)


def test_the_gyro_s_stated_sensitivity_scales_the_angle_and_rate_terms_only() -> None:
    at_divisor = _si(_answer(_native()))
    at_datasheet = _si(_answer(_native(), sensitivity=28.571))
    scale = 28.571 / 29.0
    assert at_datasheet.angle == pytest.approx(at_divisor.angle * scale, rel=1e-12)
    assert at_datasheet.rate == pytest.approx(at_divisor.rate * scale, rel=1e-12)
    assert at_datasheet.distance == at_divisor.distance
    assert at_datasheet.speed == at_divisor.speed


def test_the_counts_per_revolution_are_the_answer_s_own() -> None:
    stated = _si(_answer(_native(), counts=1323.0))
    want = _expected(counts=1323.0)
    assert stated.distance == pytest.approx(want["distance"], rel=1e-12)
    assert stated.speed == pytest.approx(want["speed"], rel=1e-12)
    assert stated.angle == pytest.approx(_expected()["angle"], rel=1e-12)


def test_the_update_time_scales_the_speed_gain_and_sets_the_period() -> None:
    loop = _si(_answer(_native(update_time=20)))
    assert loop.speed == pytest.approx(_expected(update_ms=20)["speed"], rel=1e-12)
    assert loop.period == pytest.approx(0.020, rel=1e-15)


_FACTORS = {
    "gyro_sensitivity": ("count*s/deg", "parameters.gyro_sensitivity"),
    "gyro_divisor": ("count*s/deg", "controller.gyro_divisor"),
    "encoder_counts_per_wheel_revolution": (
        "count",
        "parameters.encoder_counts_per_wheel_revolution",
    ),
    "pwm_full_scale": ("count", "parameters.pwm_full_scale"),
    "update_time": ("ms", "controller.update_time"),
    "increment_divisor": ("1", "controller.response_divisor"),
    "wheel_radius": ("m", _RADIUS_SOURCE),
    "wheels_summed": ("1", "sum"),
    "millidegrees_per_radian": ("1/rad", "millidegree"),
}


def test_every_scale_factor_is_named_with_its_unit_and_source_in_the_record() -> None:
    loop = _si(_answer(_native(), sensitivity=28.571))
    by_name = {f.name: f for f in loop.factors}
    assert set(by_name) == set(_FACTORS)
    for name, (unit, says) in _FACTORS.items():
        assert by_name[name].unit == unit, name
        assert says in by_name[name].source, (name, by_name[name].source)
    assert by_name["gyro_sensitivity"].value == 28.571
    assert by_name["gyro_divisor"].value == 29
    assert by_name["increment_divisor"].value == 100 * 111
    assert by_name["wheels_summed"].value == 2
    assert by_name["millidegrees_per_radian"].value == pytest.approx(180_000 / math.pi, rel=1e-15)
    assert by_name["wheel_radius"].value == _RADIUS


def test_the_si_incremental_structure_passes_through_with_no_factor() -> None:
    loop = _si(_answer(_rising()))
    assert loop.incremental is True
    assert (loop.angle, loop.distance, loop.speed) == (0.3, 2.0, 0.9)
    assert loop.rate == pytest.approx(0.3 * 0.14, rel=1e-15)
    assert loop.decay == 1.0
    assert loop.factors == ()
    leaky = _si(_answer(_rising(angle_decay_per_update=_m(0.999, "1"))))
    assert leaky.decay == 0.999


def test_a_state_feedback_passes_through_and_sets_the_command() -> None:
    loop = _si(_answer(_feedback()))
    assert loop.incremental is False
    assert (loop.angle, loop.rate, loop.distance, loop.speed) == (4.0, 0.5, 1.0, 1.5)
    assert loop.decay == 1.0
    assert (loop.period, loop.command_limit) == (0.01, 0.75)


def test_two_native_controllers_with_the_same_si_gains_are_not_the_same_coefficients() -> None:
    once = _answer(_native())
    doubled = _answer(
        _native(
            angle_response=22,
            distance_response=146,
            speed_response=6600,
            gear_ratio_coefficient=222,
        )
    )
    a, b = _si(once), _si(doubled)
    for gain in ("angle", "rate", "distance", "speed"):
        assert getattr(a, gain) == pytest.approx(getattr(b, gain), rel=1e-14), gain
    convert = _convert()
    assert convert.coefficients(once.controller) != convert.coefficients(doubled.controller)


_NATIVE_COMPARED = {
    "update_time",
    "motor_speed_limit",
    "angle_rate_ratio",
    "angle_response",
    "distance_response",
    "speed_response",
    "response_divisor",
    "gear_ratio_coefficient",
    "gyro_divisor",
    "angle_decay_numerator",
    "angle_decay_denominator",
}


def test_the_native_coefficients_compared_are_the_code_s_integers_and_no_delay() -> None:
    compared = _convert().coefficients(_answer(_native()).controller)
    names = {name for name, _, _ in compared}
    assert names == _NATIVE_COMPARED
    for name, value, _ in compared:
        assert type(value) is int, (name, value)
    as_float = _answer(_native(speed_response=3300.0)).controller
    assert _convert().coefficients(as_float) == compared
    for name, value, _ in _convert().coefficients(as_float):
        assert type(value) is int, (name, value)


def test_an_absent_angle_decay_compares_as_one() -> None:
    convert = _convert()
    absent = convert.coefficients(_answer(_rising()).controller)
    one = convert.coefficients(_answer(_rising(angle_decay_per_update=_m(1, "1"))).controller)
    leaky = convert.coefficients(_answer(_rising(angle_decay_per_update=_m(0.999, "1"))).controller)
    assert absent == one
    assert absent != leaky
    names = {name for name, _, _ in absent}
    assert names == {
        "period",
        "command_limit",
        "rate_ratio",
        "angle_gain",
        "distance_gain",
        "speed_gain",
        "angle_decay_per_update",
    }


def test_the_state_feedback_s_coefficients_are_its_gains_period_and_limit() -> None:
    names = {name for name, _, _ in _convert().coefficients(_answer(_feedback()).controller)}
    assert names == {
        "period",
        "command_limit",
        "angle_gain",
        "rate_gain",
        "distance_gain",
        "speed_gain",
    }


@pytest.mark.parametrize(("counts", "full_scale_duty"), [(300, 0.75), (200, 0.5), (400, 1.0)])
def test_the_command_limit_is_the_speed_limit_over_the_pwm_full_scale(
    counts: int, full_scale_duty: float
) -> None:
    loop = _si(_answer(_native(motor_speed_limit=counts)))
    assert loop.command_limit == full_scale_duty


def test_each_scale_factor_is_the_answer_s_or_the_environment_s_never_the_kit_s() -> None:
    # Off the kit's figures: a PWM full scale of 255, a gyro divisor of 31, a wheel of 0.05 m.
    # Each gain is this test's own reading of the code with those factors; a converter that
    # used the kit's 400, 29 or 0.040 m in place of any of them gives other numbers.
    doc = {
        "form": "whole_run",
        "version": 2,
        "controller": _native(gyro_divisor=31, motor_speed_limit=200),
        "parameters": {
            "update_rate": _m(100, "Hz"),
            "gyro_output_data_rate": _m(208, "Hz"),
            "gyro_full_scale": _m(1000, "deg/s"),
            "pwm_frequency": _m(20000, "Hz"),
            "pwm_full_scale": _m(255, "count"),
            "encoder_counts_per_wheel_revolution": _m(1322.9, "count"),
            "gyro_sensitivity": _m(28.571, "count*s/deg"),
        },
    }
    read = parse_whole_run(json.dumps(doc).encode())
    convert = _convert()
    radius = convert.ScaleFactor(name="wheel_radius", value=0.05, unit="m", source="this test")
    loop = convert.to_si(read.controller, read.parameters, wheel_radius=radius)
    per_increment = 100 * 111 * 255.0
    k_angle = 11 * (28.571 / 31) * (1000.0 * 180.0 / math.pi) / per_increment
    counts_per_metre = 1322.9 / (2.0 * math.pi * 0.05)
    assert loop.angle == pytest.approx(k_angle, rel=1e-12)
    assert loop.distance == pytest.approx(73 * 2.0 * counts_per_metre / per_increment, rel=1e-12)
    assert loop.speed == pytest.approx(
        3300 * 2.0 * 0.010 * counts_per_metre / per_increment, rel=1e-12
    )
    assert loop.command_limit == pytest.approx(200 / 255.0, rel=1e-12)
