"""Every number an answer states lies between a stated lower and upper bound, checked on reading.

An answer is untrusted input, and the scorer computes with every number in it: a period of a
day overflows the plant's exponential, a period of 1e-300 s asks for a delay line no machine
holds. So each numeric field has a lower and an upper bound, each with its reason beside it
(what the hardware, the code or the sample rate can be; a bound no source fixes says it is
chosen), and a value past either is refused as an answer, never computed with.

The bounds here are this test's own literals, not read from the module: a bound moved in the
code is a row that fails.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole import answer as answer_module
from physgate.evaluation.whole.answer import parse_whole_run


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _parameters() -> dict[str, Any]:
    return {
        "update_rate": _m(100, "Hz"),
        "gyro_output_data_rate": _m(208, "Hz"),
        "gyro_full_scale": _m(1000, "deg/s"),
        "pwm_frequency": _m(20000, "Hz"),
        "pwm_full_scale": _m(400, "count"),
        "encoder_counts_per_wheel_revolution": _m(1322.9, "count"),
        "gyro_sensitivity": _m(28.571, "count*s/deg"),
    }


def _feedback() -> dict[str, Any]:
    return {
        "structure": "state_feedback",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "angle_gain": _m(1.6643, "1/rad"),
        "rate_gain": _m(0.191, "s/rad"),
        "distance_gain": _m(0.2853, "1/m"),
        "speed_gain": _m(1.3421, "s/m"),
    }


def _incremental() -> dict[str, Any]:
    return {
        "structure": "incremental_rising_offset",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "rate_ratio": _m(0.14, "s"),
        "angle_gain": _m(0.14195, "1/rad"),
        "distance_gain": _m(0.17308, "1/m"),
        "speed_gain": _m(0.07824, "s/m"),
        "angle_decay_per_update": _m(0.999, "1"),
    }


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


_BASES = {"feedback": _feedback, "incremental": _incremental, "native": _native}


def _answer(base: str) -> dict[str, Any]:
    return {
        "form": "whole_run",
        "version": 2,
        "controller": _BASES[base](),
        "parameters": _parameters(),
    }


def _set(doc: dict[str, Any], where: str, value: object) -> None:
    part, name = where.split(".")
    doc[part][name]["value"] = value


def _parses(doc: dict[str, Any]) -> bool:
    try:
        parse_whole_run(json.dumps(doc).encode())
    except TaskFormatError:
        return False
    return True


#: (base, field, accepted at the low end or None for an open end, refused just below, accepted
#: at the high end, refused just above, other settings the row needs).
_BOUNDS: list[tuple[str, str, object, object, object, object, dict[str, object]]] = [
    (
        "feedback",
        "controller.period",
        0.001,
        0.000999,
        1.0,
        1.000001,
        {"controller.sensor_delay": 0.0, "controller.compute_delay": 0.0},
    ),
    ("feedback", "controller.command_limit", None, 0.0, 1.0, 1.000001, {}),
    (
        "feedback",
        "controller.sensor_delay",
        0.0,
        -1e-9,
        0.5,
        0.500001,
        {"controller.period": 0.02, "controller.compute_delay": 0.0},
    ),
    (
        "feedback",
        "controller.compute_delay",
        0.0,
        -1e-9,
        0.5,
        0.500001,
        {"controller.period": 0.02, "controller.sensor_delay": 0.0},
    ),
    ("feedback", "controller.angle_gain", -1e12, -1.000001e12, 1e12, 1.000001e12, {}),
    ("feedback", "controller.rate_gain", -1e12, -1.000001e12, 1e12, 1.000001e12, {}),
    ("feedback", "controller.distance_gain", -1e12, -1.000001e12, 1e12, 1.000001e12, {}),
    ("feedback", "controller.speed_gain", -1e12, -1.000001e12, 1e12, 1.000001e12, {}),
    ("incremental", "controller.rate_ratio", -1e12, -1.000001e12, 1e12, 1.000001e12, {}),
    ("incremental", "controller.angle_decay_per_update", None, 0.0, 1.0, 1.000001, {}),
    (
        "native",
        "controller.update_time",
        1,
        0,
        255,
        256,
        {"controller.sensor_delay": 0.0, "controller.compute_delay": 0.0},
    ),
    (
        "native",
        "controller.motor_speed_limit",
        1,
        0,
        32767,
        32768,
        {"parameters.pwm_full_scale": 65535},
    ),
    ("native", "controller.angle_rate_ratio", 0, -1, 32767, 32768, {}),
    ("native", "controller.angle_response", -32768, -32769, 32767, 32768, {}),
    ("native", "controller.distance_response", -32768, -32769, 32767, 32768, {}),
    ("native", "controller.speed_response", -32768, -32769, 32767, 32768, {}),
    ("native", "controller.response_divisor", 1, 0, 32767, 32768, {}),
    ("native", "controller.gear_ratio_coefficient", 1, 0, 32767, 32768, {}),
    ("native", "controller.gyro_divisor", 1, 0, 32767, 32768, {}),
    (
        "native",
        "controller.angle_decay_numerator",
        1,
        0,
        32767,
        32768,
        {"controller.angle_decay_denominator": 32767},
    ),
    (
        "native",
        "controller.angle_decay_denominator",
        1,
        0,
        32767,
        32768,
        {"controller.angle_decay_numerator": 1},
    ),
    ("feedback", "parameters.update_rate", 1, 0.999999, 1000, 1000.001, {}),
    ("feedback", "parameters.gyro_output_data_rate", None, 0.0, 10000, 10000.01, {}),
    ("feedback", "parameters.gyro_full_scale", None, 0.0, 10000, 10000.01, {}),
    ("feedback", "parameters.pwm_frequency", None, 0.0, 1e6, 1.000001e6, {}),
    ("feedback", "parameters.pwm_full_scale", 1, 0, 65535, 65536, {}),
    ("feedback", "parameters.encoder_counts_per_wheel_revolution", None, 0.0, 1e6, 1.000001e6, {}),
    ("native", "parameters.gyro_sensitivity", None, 0.0, 1e4, 10000.01, {}),
]


def _case(row: tuple[Any, ...], value: object) -> dict[str, Any]:
    base, where, *_, others = row
    doc = _answer(base)
    for other, v in others.items():
        _set(doc, other, v)
    _set(doc, where, value)
    return doc


@pytest.mark.parametrize("row", _BOUNDS, ids=[r[1] for r in _BOUNDS])
def test_each_number_is_taken_at_its_bounds_and_refused_past_them(row: tuple[Any, ...]) -> None:
    _, where, at_low, below, at_high, above, _ = row
    if at_low is not None:
        assert _parses(_case(row, at_low)), f"{where} = {at_low} is its lower bound; taken"
    assert not _parses(_case(row, below)), f"{where} = {below} is below its bound; refused"
    assert _parses(_case(row, at_high)), f"{where} = {at_high} is its upper bound; taken"
    assert not _parses(_case(row, above)), f"{where} = {above} is above its bound; refused"


def test_every_numeric_field_of_every_structure_has_a_bound_with_its_reason() -> None:
    bounds = getattr(answer_module, "FIELD_BOUNDS", None)
    assert bounds is not None, "the answer's module states no bound per field"
    fields = {r[1].split(".")[1] for r in _BOUNDS}
    assert set(bounds) == fields
    for name, bound in bounds.items():
        assert bound.low < bound.high, name
        assert bound.reason.strip(), f"{name}'s bound gives no reason"


@pytest.mark.parametrize(
    "name",
    [
        "angle_gain",
        "rate_gain",
        "distance_gain",
        "speed_gain",
        "rate_ratio",
        "gyro_output_data_rate",
        "gyro_full_scale",
        "pwm_frequency",
        "encoder_counts_per_wheel_revolution",
        "gyro_sensitivity",
        "sensor_delay",
        "compute_delay",
    ],
)
def test_a_bound_no_source_fixes_says_it_is_chosen(name: str) -> None:
    bounds = getattr(answer_module, "FIELD_BOUNDS", None)
    assert bounds is not None, "the answer's module states no bound per field"
    assert "chosen" in bounds[name].reason, bounds[name].reason


@pytest.mark.parametrize(
    ("base", "changes"),
    [
        ("feedback", {"controller.period": 1e5}),
        ("feedback", {"controller.period": 1e12}),
        ("feedback", {"controller.period": 1e-300}),
        ("native", {"controller.update_time": 10**12}),
    ],
    ids=["period_a_day", "period_1e12_s", "period_1e-300_s", "native_update_time_1e12_ms"],
)
def test_the_periods_that_crashed_the_scorer_are_refused_on_reading(
    base: str, changes: dict[str, object]
) -> None:
    doc = _answer(base)
    for where, value in changes.items():
        _set(doc, where, value)
    with pytest.raises(TaskFormatError):
        parse_whole_run(json.dumps(doc).encode())


#: The delay line holds a command per whole period of the total delay; at most this many.
DELAY_SAMPLES = 50


@pytest.mark.parametrize(
    ("base", "period", "sensor", "compute", "taken"),
    [
        ("feedback", 0.01, 0.3, 0.2, True),
        ("feedback", 0.01, 0.3, 0.201, False),
        ("feedback", 0.001, 0.03, 0.02, True),
        ("feedback", 0.001, 0.0301, 0.02, False),
        ("feedback", 0.001, 0.5, 0.0, False),
        ("native", 1, 0.03, 0.02, True),
        ("native", 1, 0.0301, 0.02, False),
        ("native", 10, 0.3, 0.2, True),
        ("native", 10, 0.3, 0.201, False),
    ],
)
def test_the_delay_line_is_at_most_fifty_periods_long(
    base: str, period: float, sensor: float, compute: float, taken: bool
) -> None:
    doc = _answer(base)
    _set(doc, "controller.update_time" if base == "native" else "controller.period", period)
    _set(doc, "controller.sensor_delay", sensor)
    _set(doc, "controller.compute_delay", compute)
    assert _parses(doc) is taken, (period, sensor, compute)
    if not taken:
        with pytest.raises(TaskFormatError, match="delay line"):
            parse_whole_run(json.dumps(doc).encode())


def test_the_analysed_controller_is_held_to_the_same_bounds() -> None:
    doc = _answer("feedback")
    doc["analysed_controller"] = copy.deepcopy(doc["controller"])
    doc["analysed_controller"]["period"]["value"] = 1e5
    assert not _parses(doc)


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("controller.angle_response", 10**400),
        ("controller.speed_response", -(10**400)),
        ("controller.gyro_divisor", 10**30),
        ("controller.update_time", 2**63),
    ],
)
def test_a_huge_integer_in_the_native_form_is_refused_never_converted(
    where: str, value: int
) -> None:
    doc = _answer("native")
    _set(doc, where, value)
    with pytest.raises(TaskFormatError):
        parse_whole_run(json.dumps(doc).encode())


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("where", ["controller.angle_response", "parameters.gyro_sensitivity"])
def test_nan_and_the_infinities_in_the_native_form_are_refused(where: str, token: str) -> None:
    doc = _answer("native")
    _set(doc, where, "@@")
    raw = json.dumps(doc).replace('"@@"', token).encode()
    with pytest.raises(TaskFormatError):
        parse_whole_run(raw)
