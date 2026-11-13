"""A whole-run controller in the SI the loop analysis needs, and the coefficients a brief compares.

The analysis of the balance loop runs in SI, whatever structure the answer wrote. An SI
structure passes through. A native structure is converted, and every scale factor the
conversion uses is returned with it, named, with its unit and where it came from, so the
record says what the SI gains rest on. A factor that no source fixes is taken from the
answer, never assumed: the gyro's true sensitivity (the code divides by its own 29, the
sensor's datasheet gives about 28.571) and the encoder counts per wheel revolution (1322.9,
1323 and 1332 are all in play). The wheel radius is the environment's, passed in with its
source by the caller.

The conversion is for the loop only. Whether two controllers are the same is decided on
:func:`coefficients`, the numbers as the answer wrote them, never on converted values: the
map from the code's integers to SI is not one-to-one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from physgate.evaluation.whole.answer import (
    Controller,
    IncrementalRisingOffset,
    NativeRisingOffset,
    Parameters,
    StateFeedback,
)

#: The code's angle is in millidegrees: this many per radian.
MILLIDEGREES_PER_RADIAN = 1000.0 * 180.0 / math.pi
#: The code sums the two wheels' counts; the contract's travel and speed are their mean.
WHEELS_SUMMED = 2


@dataclass(frozen=True)
class ScaleFactor:
    """One number a conversion rests on, with its unit and where it came from."""

    name: str
    value: float
    unit: str
    source: str


@dataclass(frozen=True)
class SiLoop:
    """A controller in SI, as the loop analysis takes it.

    ``incremental``: the command is changed by the terms each update (else it is set by
    them). The terms are ``angle·θ̂ + rate·θ̇ + distance·x + speed·v``, in 1/rad, s/rad, 1/m
    and s/m; ``θ̂`` is the controller's integrated angle with the per-update ``decay`` (1 for
    a state feedback, whose angle is the measured tilt). Times in s, the limit a duty.
    """

    incremental: bool
    angle: float
    rate: float
    distance: float
    speed: float
    decay: float
    period: float
    command_limit: float
    sensor_delay: float
    compute_delay: float
    factors: tuple[ScaleFactor, ...]


def to_si(controller: Controller, parameters: Parameters, *, wheel_radius: ScaleFactor) -> SiLoop:
    """``controller`` in SI, with every scale factor of the conversion.

    Raises:
        ValueError: a native controller with no stated gyro sensitivity (the schema refuses
            that answer first), or a wheel radius that is not a positive length in m.
    """
    if isinstance(controller, IncrementalRisingOffset):
        decay = controller.angle_decay_per_update
        angle = float(controller.angle_gain.value)
        return SiLoop(
            incremental=True,
            angle=angle,
            rate=angle * float(controller.rate_ratio.value),
            distance=float(controller.distance_gain.value),
            speed=float(controller.speed_gain.value),
            decay=1.0 if decay is None else float(decay.value),
            period=float(controller.period.value),
            command_limit=float(controller.command_limit.value),
            sensor_delay=float(controller.sensor_delay.value),
            compute_delay=float(controller.compute_delay.value),
            factors=(),
        )
    if isinstance(controller, StateFeedback):
        return SiLoop(
            incremental=False,
            angle=float(controller.angle_gain.value),
            rate=float(controller.rate_gain.value),
            distance=float(controller.distance_gain.value),
            speed=float(controller.speed_gain.value),
            decay=1.0,
            period=float(controller.period.value),
            command_limit=float(controller.command_limit.value),
            sensor_delay=float(controller.sensor_delay.value),
            compute_delay=float(controller.compute_delay.value),
            factors=(),
        )
    return _native_to_si(controller, parameters, wheel_radius)


def _native_to_si(
    controller: NativeRisingOffset, parameters: Parameters, wheel_radius: ScaleFactor
) -> SiLoop:
    sensitivity = parameters.gyro_sensitivity
    if sensitivity is None:
        msg = "a native controller is converted only with the gyro's stated sensitivity"
        raise ValueError(msg)
    if wheel_radius.unit != "m" or not wheel_radius.value > 0:
        msg = f"the wheel radius is {wheel_radius.value} {wheel_radius.unit}; it is a length in m"
        raise ValueError(msg)
    divisor = int(controller.response_divisor.value) * int(controller.gear_ratio_coefficient.value)
    factors = (
        ScaleFactor(
            "gyro_sensitivity",
            float(sensitivity.value),
            "count*s/deg",
            "the answer, parameters.gyro_sensitivity: the sensor's true counts per deg/s",
        ),
        ScaleFactor(
            "gyro_divisor",
            int(controller.gyro_divisor.value),
            "count*s/deg",
            "the answer, controller.gyro_divisor: what the code divides the raw rate by",
        ),
        ScaleFactor(
            "encoder_counts_per_wheel_revolution",
            float(parameters.encoder_counts_per_wheel_revolution.value),
            "1",
            "the answer, parameters.encoder_counts_per_wheel_revolution",
        ),
        ScaleFactor(
            "pwm_full_scale",
            float(parameters.pwm_full_scale.value),
            "1",
            "the answer, parameters.pwm_full_scale: PWM counts at a duty of 1",
        ),
        ScaleFactor(
            "update_time",
            int(controller.update_time.value),
            "ms",
            "the answer, controller.update_time: the interval the code integrates over",
        ),
        ScaleFactor(
            "increment_divisor",
            divisor,
            "1",
            "the answer, controller.response_divisor times controller.gear_ratio_coefficient",
        ),
        wheel_radius,
        ScaleFactor(
            "wheels_summed",
            WHEELS_SUMMED,
            "1",
            "definition: the code sums the two wheels' counts; the contract's x and v are "
            "their mean",
        ),
        ScaleFactor(
            "millidegrees_per_radian",
            MILLIDEGREES_PER_RADIAN,
            "1/rad",
            "definition: the code's angle is in millidegree units",
        ),
    )
    full_scale = float(parameters.pwm_full_scale.value)
    per_increment = divisor * full_scale
    believed = float(sensitivity.value) / int(controller.gyro_divisor.value)
    period = int(controller.update_time.value) / 1000.0
    counts_per_metre = float(parameters.encoder_counts_per_wheel_revolution.value) / (
        2.0 * math.pi * wheel_radius.value
    )
    angle = (
        int(controller.angle_response.value) * believed * MILLIDEGREES_PER_RADIAN / per_increment
    )
    return SiLoop(
        incremental=True,
        angle=angle,
        rate=angle * int(controller.angle_rate_ratio.value) / 1000.0,
        distance=(
            int(controller.distance_response.value)
            * WHEELS_SUMMED
            * counts_per_metre
            / per_increment
        ),
        speed=(
            int(controller.speed_response.value)
            * WHEELS_SUMMED
            * period
            * counts_per_metre
            / per_increment
        ),
        decay=int(controller.angle_decay_numerator.value)
        / int(controller.angle_decay_denominator.value),
        period=period,
        command_limit=int(controller.motor_speed_limit.value) / full_scale,
        sensor_delay=float(controller.sensor_delay.value),
        compute_delay=float(controller.compute_delay.value),
        factors=factors,
    )


#: One compared coefficient: its name, its value as the answer wrote it, and its unit.
Coefficient = tuple[str, int | float, str]

_COMPARED: dict[type, tuple[str, ...]] = {
    IncrementalRisingOffset: (
        "period",
        "command_limit",
        "rate_ratio",
        "angle_gain",
        "distance_gain",
        "speed_gain",
    ),
    StateFeedback: (
        "period",
        "command_limit",
        "angle_gain",
        "rate_gain",
        "distance_gain",
        "speed_gain",
    ),
    NativeRisingOffset: (
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
    ),
}


def coefficients(controller: Controller) -> tuple[Coefficient, ...]:
    """What a brief's "same coefficients, period and limit" compares, as the answer wrote it.

    A native structure's are its integers, as ``int``; an SI structure's are its numbers.
    The delays are not coefficients and are not compared; neither is the turn term, which no
    structure carries. An absent angle decay is the default 1 and compares as 1.
    """
    out: list[Coefficient] = []
    for name in _COMPARED[type(controller)]:
        measure = getattr(controller, name)
        value = measure.value
        if isinstance(controller, NativeRisingOffset):
            value = int(value)
        out.append((name, value, measure.unit))
    if isinstance(controller, IncrementalRisingOffset):
        decay = controller.angle_decay_per_update
        out.append(("angle_decay_per_update", 1.0 if decay is None else decay.value, "1"))
    return tuple(out)
