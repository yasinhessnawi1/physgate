"""The whole-run answer: one file, written by either arm, stating the design's choices.

A whole design is judged from one answer file that both arms can write: the harness by an
exporter from its design-state graph and sealed records, a raw agent by hand, each told the
same form in the same bytes. The answer states choices and nothing else. It carries no plant:
the scorer computes every consequence (a stall current, a margin, a recovery) from a frozen
validation environment and the choices here, never from a model the answer brings, so an
answer cannot make itself pass by describing an easier robot.

An answer is untrusted input, written by the session under test. It is held to this schema
whole before any number in it is used, and every refusal is a :class:`TaskFormatError`: a
failure of the answer, never an error of the scorer.

**What the controller reads.** Every signal is in SI units, the scorer's convention:

- ``θ``, the body's tilt from vertical in rad, positive when it leans forward (towards the
  direction of positive travel), and ``θ̇`` its rate in rad/s;
- ``x``, the travel in m that the wheel encoders give (the mean of the two wheels'), and ``v``
  its speed in m/s, each measured minus a reference that advances at the commanded speed, so
  both are zero when the robot holds its commanded motion. The encoders sit on the motor
  shafts, whose housings are fixed to the body, so they count each wheel's turn relative to
  the body: ``x`` is the wheel radius times that turn, the ground travel less ``r·θ``;
- ``u``, the command to both motors as a duty: the average voltage across a motor is ``u``
  times the pack voltage, positive driving forward, held to ``[-limit, +limit]``.

**The closed list of structures.** Each runs once per ``period``:

- ``incremental_rising_offset``, the form of the reference kit's own balancing example in SI:
  the command is changed, never set, by
  ``u[k] = sat(u[k-1] + angle_gain·(θ̂[k] + rate_ratio·θ̇[k]) + distance_gain·x[k]
  + speed_gain·v[k])``, where ``θ̂`` is the controller's own integrated angle (see
  :class:`IncrementalRisingOffset`, with its optional leak). ``θ̂ + rate_ratio·θ̇`` is zero
  where the tilt is ``rate_ratio`` times its rate, rising. ``rate_ratio`` is the controller's
  lead time, chosen or tuned (the kit's 0.140 s is tuned on its own build), never a property
  of the plant. Gains in 1/rad, s, 1/m and s/m;
- ``state_feedback``, a discrete state feedback that sets the command,
  ``u[k] = sat(angle_gain·θ[k] + rate_gain·θ̇[k] + distance_gain·x[k] + speed_gain·v[k])``.
  Gains in 1/rad, s/rad, 1/m and s/m;
- ``native_incremental_rising_offset``, the same incremental form as the kit's code writes
  it: its integers in the code's own scalings (:class:`NativeRisingOffset`). The scorer
  converts it to SI only where a predicate needs SI, every scale factor named with its
  source; a brief's "relative difference of 0" compares the integers themselves.

**Version 3** adds a fourth structure and names the settings as the gate's catalogue does
(``output_data_rate`` for version 2's ``gyro_output_data_rate``):

- ``sampled_law``, a general sampled linear law over the tilt and its rate and the wheels'
  angle and speed, with memory states, stated as the design states it
  (:mod:`physgate.evaluation.whole.law`). Version 2 is read exactly as it was; a version 2
  answer is never read as a version 3 one nor the reverse.

In each, the measurements used at update ``k`` were taken ``sensor_delay`` earlier, and the
command computed at ``k`` reaches the motors ``compute_delay`` later. Both are times in s,
not whole updates: the kit's own sensor and computation delay is a few milliseconds, less
than one 10 ms update. A structure off the list is refused rather than approximated: a scorer
that guessed what an unknown structure meant would be judging its own guess.

**Units are exact spellings**, as for the per-role controller: each field is given in the one
unit below, and any other spelling, however equivalent, is refused, so no answer is judged
through a conversion it did not ask for.

**Every number is bounded**, below and above, each bound with its reason
(:data:`FIELD_BOUNDS`): what the hardware, the reference code or the sample rate can be, or a
chosen bound where no source fixes one. The two delays together span at most
:data:`MAX_DELAY_SAMPLES` periods. A value past a bound is refused on reading, so the scorer
never computes with a period of a day or a delay line of a million states.

``controller`` is the controller the firmware runs. ``analysed_controller``, when given, is
the one the design's analysis is shown for; a brief can require the two to be the same, and
the scorer compares them; without it there is nothing to compare, and that requirement is not
judged either way. ``files`` names module files the answer refers to, by path inside
the answer's directory; reading them is the scorer's business, and naming them here grants
nothing outside that directory.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.authoring import AuthoringError, _open_chain
from physgate.evaluation.tiers.base import Measure
from physgate.evaluation.whole import law as law_module

#: The largest answer file read: a controller, six settings and a list of paths.
MAX_ANSWER_BYTES = 64 * 1024
#: The longest delay accepted, in s: far past any delay a balancing loop survives.
MAX_DELAY_SECONDS = 0.5
#: The most whole periods the total delay may span. The scorer's delay line holds one command
#: per whole period of the delay, so this caps its states at 51. A chosen bound: the first
#: form of this answer gave a delay in whole updates, from 0 to this same 50.
MAX_DELAY_SAMPLES = 50
#: The largest magnitude any value may have. Far above any setting here (the largest the
#: reference brief names is a 20 kHz PWM frequency), and small enough that the products and
#: powers a scorer forms of them stay finite floats. A larger value is refused, as is an
#: integer too large to be a float at all, which would otherwise end in an overflow inside the
#: scorer rather than in a refusal of the answer.
MAX_MAGNITUDE = 1e12
#: The most module files an answer names.
MAX_FILES = 64
#: The longest path to a module file.
MAX_PATH_LENGTH = 200


@dataclass(frozen=True)
class FieldBound:
    """The range one numeric field may take, in its unit, and why.

    ``low_open``: the low end itself is refused (a duty, a rate or a scale above 0).
    """

    low: float
    high: float
    reason: str
    low_open: bool = False


_GAIN = FieldBound(
    -MAX_MAGNITUDE,
    MAX_MAGNITUDE,
    "chosen bound: a gain has no bound in the hardware (the linear analysis takes any), and "
    "within this magnitude every product the scorer forms of it stays a finite float",
)
_INT16 = "the reference code declares it int16_t (Balance.h), so it is from -32768 to 32767"
_LITERAL = (
    "the reference code writes it as an int literal, 16 bits on the kit's AVR; chosen to that "
    "range, at least 1 since the code divides by it"
)
_PERIOD = (
    "low: the shortest update the reference code can state (its update time is a whole number "
    "of ms, at least 1); high, a chosen bound: the body falls with a time constant near 0.14 s, "
    "so no loop sampled once a second balances it"
)

#: Every numeric field of an answer, by name, with its bound and the bound's reason.
FIELD_BOUNDS: dict[str, FieldBound] = {
    "period": FieldBound(0.001, 1.0, _PERIOD),
    "update_time": FieldBound(
        1, 255, "the reference code holds its update time as uint8_t ms (Balance.h); 0 is none"
    ),
    "command_limit": FieldBound(0.0, 1.0, "a duty: above 0 and at most 1", low_open=True),
    "sensor_delay": FieldBound(
        0.0,
        MAX_DELAY_SECONDS,
        "chosen bound: a time, and far past any delay a balancing loop survives",
    ),
    "compute_delay": FieldBound(
        0.0,
        MAX_DELAY_SECONDS,
        "chosen bound: a time, and far past any delay a balancing loop survives",
    ),
    "angle_gain": _GAIN,
    "rate_gain": _GAIN,
    "distance_gain": _GAIN,
    "speed_gain": _GAIN,
    "rate_ratio": _GAIN,
    "angle_decay_per_update": FieldBound(
        0.0, 1.0, "a leak: it never grows the angle, and 0 would erase it", low_open=True
    ),
    "motor_speed_limit": FieldBound(
        1, 32767, _INT16 + "; at least 1, and at most the PWM full scale"
    ),
    "angle_rate_ratio": FieldBound(0, 32767, _INT16 + "; a lead time, never negative"),
    "angle_response": FieldBound(-32768, 32767, _INT16),
    "distance_response": FieldBound(-32768, 32767, _INT16),
    "speed_response": FieldBound(-32768, 32767, _INT16),
    "gear_ratio_coefficient": FieldBound(1, 32767, _INT16 + "; at least 1, a divisor"),
    "response_divisor": FieldBound(1, 32767, _LITERAL),
    "gyro_divisor": FieldBound(1, 32767, _LITERAL),
    "angle_decay_numerator": FieldBound(1, 32767, _LITERAL),
    "angle_decay_denominator": FieldBound(1, 32767, _LITERAL),
    "update_rate": FieldBound(1.0, 1000.0, "the period's bounds, as a rate"),
    "gyro_output_data_rate": FieldBound(
        0.0,
        10_000.0,
        "chosen bound: above 0, and ten times a loop at its fastest 1 ms update can read",
        low_open=True,
    ),
    "gyro_full_scale": FieldBound(
        0.0,
        10_000.0,
        "chosen bound: above 0, and past the full scale of any gyro offered on the kit",
        low_open=True,
    ),
    "pwm_frequency": FieldBound(
        0.0,
        1e6,
        "chosen bound: above 0, and fifty times the 20 kHz the reference brief names",
        low_open=True,
    ),
    "pwm_full_scale": FieldBound(
        1, 65535, "the PWM counter's top on the kit's ATmega32U4 Timer1, which counts in 16 bits"
    ),
    "encoder_counts_per_wheel_revolution": FieldBound(
        0.0,
        1e6,
        "chosen bound: above 0, and past any encoder on any gear ratio offered for the kit "
        "(about 1,323 counts on the kit's own)",
        low_open=True,
    ),
    "gyro_sensitivity": FieldBound(
        0.0,
        1e4,
        "chosen bound: above 0, and past the finest sensitivity of any gyro offered on the kit",
        low_open=True,
    ),
}


#: One part of a path: ASCII letters, digits, ``_``, ``.`` and ``-``, not starting with a dot,
#: so neither ``..`` nor a hidden directory (a repository's own ``.git``) is ever a part.
_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


def _unit(measure: Measure, unit: str, what: str) -> float:
    if measure.unit != unit:
        msg = f"{what} is in {measure.unit!r}; it is given in {unit!r}"
        raise ValueError(msg)
    # Compared before any conversion: an int and a float compare exactly in Python, while
    # float() of a 400-digit integer raises OverflowError, which is not a refusal.
    if not abs(measure.value) <= MAX_MAGNITUDE:
        msg = f"{what} is beyond {MAX_MAGNITUDE:g} in magnitude"
        raise ValueError(msg)
    return float(measure.value)


def _bounded(measure: Measure, unit: str, what: str, field: str) -> float:
    """``measure`` in ``unit``, inside the bound :data:`FIELD_BOUNDS` states for ``field``."""
    value = _unit(measure, unit, what)
    bound = FIELD_BOUNDS[field]
    above_low = value > bound.low if bound.low_open else value >= bound.low
    if not (above_low and value <= bound.high):
        low = "above" if bound.low_open else "from"
        # A value at or below 0 where the bound is above 0 is named for what it is not.
        excludes_zero = bound.low > 0 or (bound.low == 0 and bound.low_open)
        kind = "positive, " if value <= 0 and excludes_zero else ""
        msg = (
            f"{what} is {value:g} {unit}; it is {kind}{low} {bound.low:g} to {bound.high:g} "
            f"{unit} ({bound.reason})"
        )
        raise ValueError(msg)
    return value


def _whole(value: float) -> bool:
    return value.is_integer()


def _integer(measure: Measure, unit: str, what: str, field: str) -> int:
    """``measure`` as the whole number it must be, in ``unit``, inside its field's bound."""
    value = _unit(measure, unit, what)
    if not _whole(value):
        msg = f"{what} is {value}; the code holds it as a whole number"
        raise ValueError(msg)
    return int(_bounded(measure, unit, what, field))


def _delay_line(delays: _Delays, period: float) -> None:
    """The two delays' sum spans at most :data:`MAX_DELAY_SAMPLES` whole periods."""
    total = float(delays.sensor_delay.value) + float(delays.compute_delay.value)
    # A relative allowance for the decimal spelling of a delay that is exactly the cap.
    if total / period > MAX_DELAY_SAMPLES * (1 + 1e-9):
        msg = (
            f"the delays sum to {total:g} s, {total / period:g} periods of {period:g} s; the "
            f"scorer's delay line holds at most {MAX_DELAY_SAMPLES} periods"
        )
        raise ValueError(msg)


class _Delays(_Frozen):
    """The two delays every structure states, each a time in s."""

    sensor_delay: Measure
    compute_delay: Measure

    @model_validator(mode="after")
    def _delays_are_times(self) -> _Delays:
        _bounded(self.sensor_delay, "s", "the sensor delay", "sensor_delay")
        _bounded(self.compute_delay, "s", "the compute delay", "compute_delay")
        return self


class _Loop(_Delays):
    """What every SI structure has: its period, its command limit and its two delays."""

    period: Measure
    command_limit: Measure

    @model_validator(mode="after")
    def _timing_is_physical(self) -> _Loop:
        period = _bounded(self.period, "s", "the period", "period")
        _bounded(self.command_limit, "1", "the command limit", "command_limit")
        _delay_line(self, period)
        return self


class IncrementalRisingOffset(_Loop):
    """The command changed each update by the rising offset, the travel and the speed.

    The angle in the offset is the controller's own, ``θ̂``: the measured tilt rate
    integrated once per update, with an optional leak ``d`` (``angle_decay_per_update``):
    ``θ̂[k] = d·(θ̂[k-1] + period·θ̇[k])``. The leak acts on that integrated angle, never on
    a measured one. Absent, ``d`` is 1 and ``θ̂`` is the integral of the rate, the tilt
    itself. Below 1, in continuous time ``dθ̂/dt = θ̇ - θ̂/τ_L`` with
    ``τ_L = -period/ln(d)`` (about ``period/(1 - d)``): ``θ̂`` is the tilt through a
    first-order high-pass with corner ``1/τ_L`` rad/s, so a constant gyro bias settles to a
    bounded angle instead of growing without end. The kit's code leaks by 999/1000 each 10 ms
    update, ``τ_L`` = 10.0 s.
    """

    structure: Literal["incremental_rising_offset"]
    rate_ratio: Measure
    angle_gain: Measure
    distance_gain: Measure
    speed_gain: Measure
    angle_decay_per_update: Measure | None = None

    @model_validator(mode="after")
    def _gains_in_their_units(self) -> IncrementalRisingOffset:
        _bounded(self.rate_ratio, "s", "the rate ratio", "rate_ratio")
        _bounded(self.angle_gain, "1/rad", "the angle gain", "angle_gain")
        _bounded(self.distance_gain, "1/m", "the distance gain", "distance_gain")
        _bounded(self.speed_gain, "s/m", "the speed gain", "speed_gain")
        if self.angle_decay_per_update is not None:
            _bounded(
                self.angle_decay_per_update,
                "1",
                "the angle decay per update",
                "angle_decay_per_update",
            )
        return self


class StateFeedback(_Loop):
    """The command set each update from the tilt, its rate, the travel and the speed."""

    structure: Literal["state_feedback"]
    angle_gain: Measure
    rate_gain: Measure
    distance_gain: Measure
    speed_gain: Measure

    @model_validator(mode="after")
    def _gains_in_their_units(self) -> StateFeedback:
        _bounded(self.angle_gain, "1/rad", "the angle gain", "angle_gain")
        _bounded(self.rate_gain, "s/rad", "the rate gain", "rate_gain")
        _bounded(self.distance_gain, "1/m", "the distance gain", "distance_gain")
        _bounded(self.speed_gain, "s/m", "the speed gain", "speed_gain")
        return self


class NativeRisingOffset(_Delays):
    """The kit's balancing example as its code writes it: integers in the code's own scalings.

    Each update the code reads the gyro once and forms, in its own units,

    - the rate ``R = raw / gyro_divisor`` in deg/s (``raw`` the gyro's counts), and the angle
      ``A = d·(A + R·update_time)`` in millidegrees, ``d`` being
      ``angle_decay_numerator / angle_decay_denominator`` (the leak on that integrated angle);
    - ``D``, the two wheels' encoder counts summed, and ``S``, their counts this update summed,
      each less the reference's;
    - the command, in PWM counts, changed by
      ``(angle_response·(R·angle_rate_ratio + A) + distance_response·D + speed_response·S)
      / response_divisor / gear_ratio_coefficient`` and held to ``±motor_speed_limit``.

    The turn term, which drives the two wheels apart, is left out: the pitch loop is judged
    symmetric, and nothing here claims to compare it. The code's integer truncations and its
    integer signals are outside the analysed loop.

    The map to SI is linear but not one-to-one: the three responses enter only as a ratio to
    ``response_divisor·gear_ratio_coefficient``, so two different sets of integers can give
    the same SI gains. Two controllers are the same only when their integers are.
    """

    structure: Literal["native_incremental_rising_offset"]
    update_time: Measure
    motor_speed_limit: Measure
    angle_rate_ratio: Measure
    angle_response: Measure
    distance_response: Measure
    speed_response: Measure
    response_divisor: Measure
    gear_ratio_coefficient: Measure
    gyro_divisor: Measure
    angle_decay_numerator: Measure
    angle_decay_denominator: Measure

    @model_validator(mode="after")
    def _integers_in_their_units(self) -> NativeRisingOffset:
        update_time = _integer(self.update_time, "ms", "the update time", "update_time")
        _integer(self.motor_speed_limit, "count", "the motor speed limit", "motor_speed_limit")
        _integer(self.angle_rate_ratio, "ms", "the angle rate ratio", "angle_rate_ratio")
        _integer(self.angle_response, "1", "the angle response", "angle_response")
        _integer(self.distance_response, "1", "the distance response", "distance_response")
        _integer(self.speed_response, "1", "the speed response", "speed_response")
        _integer(self.response_divisor, "1", "the response divisor", "response_divisor")
        _integer(
            self.gear_ratio_coefficient,
            "1",
            "the gear ratio coefficient",
            "gear_ratio_coefficient",
        )
        _integer(self.gyro_divisor, "count*s/deg", "the gyro divisor", "gyro_divisor")
        numerator = _integer(
            self.angle_decay_numerator, "1", "the decay numerator", "angle_decay_numerator"
        )
        denominator = _integer(
            self.angle_decay_denominator, "1", "the decay denominator", "angle_decay_denominator"
        )
        _delay_line(self, update_time / 1000.0)
        if numerator > denominator:
            msg = (
                f"the angle decay is {numerator}/{denominator}; it never grows the angle, so "
                "the numerator is at most the denominator"
            )
            raise ValueError(msg)
        return self


#: A controller, one structure of the closed list, told apart by its ``structure``.
Controller = Annotated[
    IncrementalRisingOffset | StateFeedback | NativeRisingOffset,
    Field(discriminator="structure"),
]


#: The largest magnitude a law's coefficient or number may have. Chosen: a gain of a million
#: per unit is past any a 10 ms loop on this kit can hold, and its products stay finite.
LAW_MAGNITUDE = 1e6


class SampledLaw(_Loop, law_module.Body):
    """A general sampled linear law, stated as the design states it (version 3).

    The command is the line ``command`` (see :mod:`physgate.evaluation.whole.law`): a sum of
    terms, each one coefficient-weighted variable, over the signals the loop analysis feeds
    (the tilt and its rate, the wheels' angle and speed relative to the body) and the memory
    the law keeps. Each coefficient is ``{value, unit}``, named by the design; every line is
    checked for units, and a law that is not linear in its signals, or that reads a signal
    outside the closed list, is refused by name and never judged. The limit and the integer
    rounding are outside the linear loop, as for every other structure. The two delays are
    times in s, the same as for every other structure.
    """

    structure: Literal["sampled_law"]
    coefficients: dict[law_module.Name, Measure] = Field(max_length=law_module.MAX_COEFFICIENTS)
    #: The loop quantities (``period``, ``sensor_delay``, ``compute_delay``, ``command_limit``)
    #: the run's interface states nothing to hold against: the export's flag, carried to the
    #: scorer's rows. Empty where every one was held against the interface.
    no_interface_statement: tuple[
        Literal["command_limit", "compute_delay", "period", "sensor_delay"], ...
    ] = ()
    #: What the export found wrong with where the compute delay comes from, each by its own name
    #: (distinct from the flag above): it leaves out time-valued quantities of the interface
    #: nodes it draws on (``compute_delay_omitted`` names them), or it draws on a quantity the
    #: run's interface does not state.
    compute_delay_flags: tuple[
        Literal[
            "compute_delay_omits_interface_times",
            "compute_delay_names_a_non_interface_quantity",
        ],
        ...,
    ] = ()
    compute_delay_omitted: tuple[Annotated[str, Field(max_length=80)], ...] = Field(
        default=(), max_length=law_module.MAX_COEFFICIENTS * 4
    )

    #: Each number of the law as written in the text it was read from (:func:`parse_answer` sets
    #: it), and each out-of-scope term that cannot affect the command and was set aside: neither is
    #: a field of the answer.
    _written: law_module.Written | None = PrivateAttr(default=None)
    _set_aside: tuple[law_module.Outside, ...] = PrivateAttr(default=())

    @property
    def written(self) -> law_module.Written | None:
        """The numbers as written, where the answer was read from text; else ``None``."""
        return self._written

    @property
    def set_aside(self) -> tuple[law_module.Outside, ...]:
        """The out-of-scope terms that cannot affect the command, taken out before judging."""
        return self._set_aside

    @model_validator(mode="after")
    def _law_holds(self) -> SampledLaw:
        units: dict[str, str] = {}
        for name, measure in self.coefficients.items():
            if name == law_module.PERIOD:
                msg = "the period is the loop's own, not a coefficient"
                raise ValueError(msg)
            _unit_bounded(measure, name)
            units[name] = measure.unit
        try:
            law_module.check(self, units)
        except law_module.LawRefused as exc:
            raise ValueError(str(exc)) from exc
        divisors = law_module.zero_divisors(
            self, {name: float(m.value) for name, m in self.coefficients.items()}
        )
        if divisors:
            msg = (
                f"zero_divisor: a term divides by the coefficient {divisors[0]!r}, whose number "
                "is 0; nothing is defined there"
            )
            raise ValueError(msg)
        for line in self.lines:
            for term in line.terms:
                if not 0 < abs(term.number) <= LAW_MAGNITUDE:
                    msg = (
                        f"line {line.name!r} has the number {_shown(term.number)}, "
                        f"outside 0 to {LAW_MAGNITUDE:g}"
                    )
                    raise ValueError(msg)
        return self


def _shown(value: float) -> str:
    """``value`` as a short ``%g`` text; an integer past a float is said by its digits."""
    try:
        return f"{value:g}"
    except OverflowError:
        return f"an integer of {len(str(value))} digits"


def _unit_bounded(measure: Measure, name: str) -> None:
    """A law coefficient in a unit that is one, and its magnitude inside :data:`LAW_MAGNITUDE`."""
    try:
        law_module.dimension(measure.unit)
    except law_module.LawRefused as exc:
        msg = f"the coefficient {name!r} is in {measure.unit!r}, which is not a unit"
        raise ValueError(msg) from exc
    if not abs(measure.value) <= LAW_MAGNITUDE:
        msg = f"the coefficient {name!r} is {_shown(measure.value)}; it is within {LAW_MAGNITUDE:g}"
        raise ValueError(msg)


#: A version 3 controller: the closed list of version 2 and the general sampled law.
ControllerV3 = Annotated[
    IncrementalRisingOffset | StateFeedback | NativeRisingOffset | SampledLaw,
    Field(discriminator="structure"),
]


class Parameters(_Frozen):
    """The settings a brief constrains that the design chooses, each in its own unit.

    ``gyro_sensitivity`` is the gyro's true scale at its full scale, in raw counts per deg/s,
    as the answer states it (the sensor's datasheet figure). It is required when a controller
    is written natively: the code's ``gyro_divisor`` is what the firmware believes, and no
    source fixes it to the sensor, so the scorer takes the true scale from the answer rather
    than assume the two agree.
    """

    update_rate: Measure
    gyro_output_data_rate: Measure
    gyro_full_scale: Measure
    pwm_frequency: Measure
    pwm_full_scale: Measure
    encoder_counts_per_wheel_revolution: Measure
    gyro_sensitivity: Measure | None = None

    @model_validator(mode="after")
    def _each_positive_in_its_unit(self) -> Parameters:
        _bounded(self.update_rate, "Hz", "the update rate", "update_rate")
        _bounded(
            self.gyro_output_data_rate,
            "Hz",
            "the gyro's output data rate",
            "gyro_output_data_rate",
        )
        _bounded(self.gyro_full_scale, "deg/s", "the gyro's full scale", "gyro_full_scale")
        _bounded(self.pwm_frequency, "Hz", "the PWM frequency", "pwm_frequency")
        full_scale = _bounded(self.pwm_full_scale, "count", "the PWM full scale", "pwm_full_scale")
        if not _whole(full_scale):
            msg = f"the PWM full scale is {full_scale}; it is a whole number of counts"
            raise ValueError(msg)
        # Not a whole number: counting every edge of a 12-count encoder through a 110.24:1
        # drive gives 1322.9 counts per wheel revolution, and that is the true figure.
        _bounded(
            self.encoder_counts_per_wheel_revolution,
            "count",
            "the encoder counts per wheel revolution",
            "encoder_counts_per_wheel_revolution",
        )
        if self.gyro_sensitivity is not None:
            _bounded(
                self.gyro_sensitivity, "count*s/deg", "the gyro's sensitivity", "gyro_sensitivity"
            )
        return self


def _settings_hold(p: Parameters | ParametersV3) -> None:
    """The settings of either version in their units and bounds, each field by its own name."""
    odr = p.output_data_rate if isinstance(p, ParametersV3) else p.gyro_output_data_rate
    _bounded(p.update_rate, "Hz", "the update rate", "update_rate")
    _bounded(odr, "Hz", "the gyro's output data rate", "gyro_output_data_rate")
    _bounded(p.gyro_full_scale, "deg/s", "the gyro's full scale", "gyro_full_scale")
    _bounded(p.pwm_frequency, "Hz", "the PWM frequency", "pwm_frequency")
    full_scale = _bounded(p.pwm_full_scale, "count", "the PWM full scale", "pwm_full_scale")
    if not _whole(full_scale):
        msg = f"the PWM full scale is {full_scale}; it is a whole number of counts"
        raise ValueError(msg)
    _bounded(
        p.encoder_counts_per_wheel_revolution,
        "count",
        "the encoder counts per wheel revolution",
        "encoder_counts_per_wheel_revolution",
    )
    if p.gyro_sensitivity is not None:
        _bounded(p.gyro_sensitivity, "count*s/deg", "the gyro's sensitivity", "gyro_sensitivity")


class ParametersV3(_Frozen):
    """The settings of version 3: those of version 2 under the gate catalogue's names.

    The gyro's rate is ``output_data_rate``, as the catalogue names it; every other setting,
    its unit and its bound are version 2's.
    """

    update_rate: Measure
    output_data_rate: Measure
    gyro_full_scale: Measure
    pwm_frequency: Measure
    pwm_full_scale: Measure
    encoder_counts_per_wheel_revolution: Measure
    gyro_sensitivity: Measure | None = None

    @model_validator(mode="after")
    def _each_positive_in_its_unit(self) -> ParametersV3:
        _settings_hold(self)
        return self


#: Each setting of version 3, with its unit and the name its bound is held under in
#: :data:`FIELD_BOUNDS`.
SETTINGS: dict[str, tuple[str, str]] = {
    "update_rate": ("Hz", "update_rate"),
    "output_data_rate": ("Hz", "gyro_output_data_rate"),
    "gyro_full_scale": ("deg/s", "gyro_full_scale"),
    "pwm_frequency": ("Hz", "pwm_frequency"),
    "pwm_full_scale": ("count", "pwm_full_scale"),
    "encoder_counts_per_wheel_revolution": ("count", "encoder_counts_per_wheel_revolution"),
    "gyro_sensitivity": ("count*s/deg", "gyro_sensitivity"),
}


def setting_problem(name: str, value: object, unit: object) -> str | None:
    """Why ``value`` in ``unit`` is not a value of the version 3 setting ``name``, or ``None``.

    The answer's own rule, field by field: a finite number (never a truth value) in the one
    unit the setting has, inside the bound :data:`FIELD_BOUNDS` states for it; the PWM full scale
    a whole number of counts.
    """
    if name not in SETTINGS:
        return f"{name!r} is not a setting of the answer"
    expected, bound = SETTINGS[name]
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return f"{name} is {value!r}; it is a finite number"
    if not isinstance(unit, str):
        return f"{name} is in {unit!r}; it is given in {expected!r}"
    try:
        measure = Measure(value=value, unit=unit)
        number = _bounded(measure, expected, name, bound)
    except (ValueError, ValidationError) as exc:
        return str(exc).splitlines()[0]
    if name == "pwm_full_scale" and not _whole(number):
        return f"{name} is {number}; it is a whole number of counts"
    return None


def _module_path(path: str) -> str:
    if len(path) > MAX_PATH_LENGTH or not all(_PART.fullmatch(p) for p in path.split("/")):
        msg = f"the file {path!r} is not a plain path inside the answer's directory"
        raise ValueError(msg)
    return path


ModulePath = Annotated[str, AfterValidator(_module_path)]


class WholeRun(_Frozen):
    """One whole-run answer: the controller, the chosen settings and the files it names.

    Version 2 gives the delays as times, adds the native structure and the angle's leak.
    Version 1, with delays in whole updates, was never released.
    """

    form: Literal["whole_run"]
    version: Literal[2]
    controller: Controller
    analysed_controller: Controller | None = None
    parameters: Parameters
    files: tuple[ModulePath, ...] = Field(default=(), max_length=MAX_FILES)

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_a_number(cls, value: object) -> object:
        # A literal 1 also matches ``true``, which Python holds equal to 1, strict mode or not.
        if isinstance(value, bool):
            msg = "the version is a number, not a truth value"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _each_file_once(self) -> WholeRun:
        # Compared case-folded: on a case-insensitive filesystem two spellings are one file,
        # and the answer would name it twice.
        seen: set[str] = set()
        for path in self.files:
            if path.lower() in seen:
                msg = f"the answer names the file {path!r} twice"
                raise ValueError(msg)
            seen.add(path.lower())
        return self

    @model_validator(mode="after")
    def _native_needs_its_scales(self) -> WholeRun:
        full_scale = float(self.parameters.pwm_full_scale.value)
        for controller in (self.controller, self.analysed_controller):
            if not isinstance(controller, NativeRisingOffset):
                continue
            if self.parameters.gyro_sensitivity is None:
                msg = (
                    "a controller written natively needs the gyro's sensitivity stated in "
                    "the parameters: its divisor is what the code believes, not the sensor"
                )
                raise ValueError(msg)
            if controller.motor_speed_limit.value > full_scale:
                msg = (
                    f"the motor speed limit is {controller.motor_speed_limit.value} counts, "
                    f"past the PWM full scale of {full_scale:g}"
                )
                raise ValueError(msg)
        return self


class WholeRunV3(_Frozen):
    """One whole-run answer of version 3: version 2's, with the catalogue's names and the law.

    The controller is any structure of the closed list, the general sampled law included, and
    the settings carry the gate catalogue's names. Version 2 is unchanged and still read.
    """

    form: Literal["whole_run"]
    version: Literal[3]
    controller: ControllerV3
    analysed_controller: ControllerV3 | None = None
    parameters: ParametersV3
    files: tuple[ModulePath, ...] = Field(default=(), max_length=MAX_FILES)

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_a_number(cls, value: object) -> object:
        if isinstance(value, bool):
            msg = "the version is a number, not a truth value"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _each_file_once(self) -> WholeRunV3:
        seen: set[str] = set()
        for path in self.files:
            if path.lower() in seen:
                msg = f"the answer names the file {path!r} twice"
                raise ValueError(msg)
            seen.add(path.lower())
        return self

    @model_validator(mode="after")
    def _native_needs_its_scales(self) -> WholeRunV3:
        full_scale = float(self.parameters.pwm_full_scale.value)
        for controller in (self.controller, self.analysed_controller):
            if not isinstance(controller, NativeRisingOffset):
                continue
            if self.parameters.gyro_sensitivity is None:
                msg = (
                    "a controller written natively needs the gyro's sensitivity stated in "
                    "the parameters: its divisor is what the code believes, not the sensor"
                )
                raise ValueError(msg)
            if controller.motor_speed_limit.value > full_scale:
                msg = (
                    f"the motor speed limit is {controller.motor_speed_limit.value} counts, "
                    f"past the PWM full scale of {full_scale:g}"
                )
                raise ValueError(msg)
        return self


#: A whole-run answer of either version.
Answer = WholeRun | WholeRunV3


def _document(text: str) -> dict[str, Any]:
    """The JSON document ``text`` is, if an object, or an empty one where it is not readable."""
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    return document if isinstance(document, dict) else {}


class OutsideScope(TaskFormatError):  # noqa: N818 - a refusal by name, not an error of the scorer
    """A law the scorer cannot judge, refused by name and never scored.

    Not linear (``nonlinear``), or reading a signal it is not given (``out_of_scope``): no
    verdict on the design, so not a failed answer.
    """

    def __init__(self, message: str, *, name: str, **context: str) -> None:
        """Keep the refusal's ``name`` with the message and ``context``."""
        super().__init__(message, **context)
        self.name = name


def _scoped(
    document: dict[str, Any], where: str
) -> tuple[dict[str, Any], dict[str, OutsideScope], dict[str, tuple[law_module.Outside, ...]]]:
    """The document with each law's out-of-scope terms sorted by whether they can matter.

    Returns the document to validate (a term that cannot affect the command taken out, one that
    can marked, so that every other check still runs on its law), the laws refused by name for a
    term that can matter, by the field that holds them, and the terms set aside, by field. Read
    from the document as written, since a schema would name only the field it fails on.
    """
    probe = dict(document)
    refused: dict[str, OutsideScope] = {}
    aside: dict[str, tuple[law_module.Outside, ...]] = {}
    for key in ("controller", "analysed_controller"):
        controller = document.get(key)
        if not (isinstance(controller, dict) and controller.get("structure") == "sampled_law"):
            continue
        coefficients = controller.get("coefficients")
        values = (
            {n: m.get("value") for n, m in coefficients.items() if isinstance(m, dict)}
            if isinstance(coefficients, dict)
            else None
        )
        sorted_out = law_module.scoped(controller, values)
        probe[key] = sorted_out.body
        if sorted_out.dead:
            aside[key] = sorted_out.dead
        if sorted_out.live:
            first = sorted_out.live[0]
            msg = f"{key} is out of the scorer's reach: {first.code}: {first.detail}"
            refused[key] = OutsideScope(msg, name=first.code, where=where)
    return probe, refused, aside


def _attach(answer: Answer, text: str, aside: dict[str, tuple[law_module.Outside, ...]]) -> Answer:
    """Give each sampled law of ``answer`` its numbers as ``text`` wrote them, and what went.

    The numbers are read again from the same text with decimals kept as decimals, so that what is
    decided on the law's structure is decided on ``0.1`` and not on the bits of its binary form.
    """
    if not isinstance(answer, WholeRunV3):
        return answer
    written = json.loads(text, parse_float=Decimal)
    for key in ("controller", "analysed_controller"):
        controller = getattr(answer, key)
        if not isinstance(controller, SampledLaw):
            continue
        as_written = written.get(key)
        if isinstance(as_written, dict):
            # The same document the answer was validated from: the same terms taken out.
            coefficients = as_written.get("coefficients")
            values = (
                {n: m.get("value") for n, m in coefficients.items() if isinstance(m, dict)}
                if isinstance(coefficients, dict)
                else None
            )
            as_written = law_module.scoped(as_written, values).body
            controller._written = law_module.written_from(as_written)  # noqa: SLF001
        controller._set_aside = aside.get(key, ())  # noqa: SLF001
    return answer


def parse_whole_run(raw: bytes, *, where: str = "answer") -> WholeRun:
    """``raw`` validated whole as a version 2 whole-run answer, or refused with the reason.

    Version 2 is read exactly as it always was; :func:`parse_answer` reads either version.

    Raises:
        TaskFormatError: it is too large, not UTF-8, not JSON, or not a version 2 answer.
    """
    answer, _ = _parse(raw, where, versions=(2,))
    assert isinstance(answer, WholeRun)
    return answer


def parse_answer(raw: bytes, *, where: str = "answer") -> Answer:
    """``raw`` validated whole as a whole-run answer of version 2 or 3, or refused with the reason.

    Raises:
        TaskFormatError: it is too large, not UTF-8, not JSON, or not a whole-run answer.
    """
    return _parse(raw, where, versions=(2, 3))[0]


def parse_answer_scoped(raw: bytes, *, where: str = "answer") -> tuple[Answer, OutsideScope | None]:
    """:func:`parse_answer`, but an ``analysed_controller`` alone out of scope is returned.

    The answer is then read without its analysed controller, and the refusal is the second
    value: the primary controller is still scorable, only the comparison with the analysed one
    is not. A refusal of the primary ``controller`` is raised, and only once the rest of the
    answer is valid: an answer invalid for any other reason fails, whatever its laws say.

    Raises:
        OutsideScope: the primary controller is out of the scorer's reach, the rest being valid.
        TaskFormatError: it is too large, not UTF-8, not JSON, or not a whole-run answer.
    """
    return _parse(raw, where, versions=(2, 3), tolerate_analysed=True)


def _parse(
    raw: bytes, where: str, *, versions: tuple[int, ...], tolerate_analysed: bool = False
) -> tuple[Answer, OutsideScope | None]:
    if len(raw) > MAX_ANSWER_BYTES:
        msg = f"the answer is larger than any whole-run answer ({len(raw)} bytes)"
        raise TaskFormatError(msg, where=where)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "the answer is not UTF-8 text"
        raise TaskFormatError(msg, where=where) from exc
    document = _document(text)
    version = document.get("version")
    model: type[WholeRun] | type[WholeRunV3] = (
        WholeRunV3 if version == 3 and 3 in versions and not isinstance(version, bool) else WholeRun
    )
    if model is WholeRun:
        return _validate(model, text, where), None
    probe, refused, aside = _scoped(document, where)
    if probe == document:
        return _attach(_validate(model, text, where), text, {}), None
    # A law's out-of-scope term that cannot affect the command is taken out and the law judged as
    # it is. One that can matter is a refusal by name, but only for an answer that is otherwise
    # valid: the rest (every name declared, the units of every line that can be checked, the
    # settings) is validated first, each refused term marked, so no other fault is hidden behind it.
    answer = _validate(model, json.dumps(probe), where)
    if not refused:
        return _attach(answer, text, aside), None
    if "controller" in refused:
        raise refused["controller"]
    if not tolerate_analysed:
        raise refused["analysed_controller"]
    rest = {k: v for k, v in probe.items() if k != "analysed_controller"}
    return _attach(_validate(model, json.dumps(rest), where), text, aside), refused[
        "analysed_controller"
    ]


def _validate(model: type[WholeRun] | type[WholeRunV3], text: str, where: str) -> Answer:
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        first = exc.errors()[0]
        reason = (
            "a value is nan or inf, and every value is a finite number"
            if first["type"] == "finite_number"
            else first["msg"]
        )
        msg = f"the answer is not a whole-run answer: {reason}"
        raise TaskFormatError(msg, where=where) from exc


#: How the answer file is opened: never through a link, never waiting on a FIFO's writer.
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def read_whole_run(path: Path, *, root: Path) -> WholeRun:
    """The version 2 whole-run answer at ``path``, inside ``root``, or refused with the reason.

    Read as :func:`read_answer` reads, but a version 3 answer is refused.

    Raises:
        TaskFormatError: as :func:`read_answer`.
    """
    answer = _read(path, root, parse_whole_run)
    assert isinstance(answer, WholeRun)
    return answer


def read_answer(path: Path, *, root: Path) -> Answer:
    """The whole-run answer, of version 2 or 3, at ``path``, inside ``root``, or refused.

    Raises:
        TaskFormatError: it is missing, outside ``root``, not spelt plainly, reached through a
            link, not a regular file with one name, too large, or not an answer.
    """
    return _read(path, root, parse_answer)


def read_answer_scoped(path: Path, *, root: Path) -> tuple[Answer, OutsideScope | None]:
    """:func:`read_answer` through :func:`parse_answer_scoped`."""
    return _read(path, root, parse_answer_scoped)


def _read[T](path: Path, root: Path, parse: Callable[..., T]) -> T:
    """Either version's answer at ``path``, inside ``root``, read with ``parse``.

    The file is opened once and read from that one descriptor; nothing is looked up by path
    again, so nothing put in place between a check and the read is read. Its directory is
    reached from ``/`` one component at a time without following a link (the tier store's own
    walk), so a link anywhere on the way refuses, and the path as spelt is where the file is.
    The file itself is opened without following a link, and must be a regular file with one
    name: a hard link is a second name it could be changed or read through from outside
    ``root``. The read stops one byte past the size bound, so neither a large file nor one that
    grows while it is read is ever held whole.

    Raises:
        TaskFormatError: it is missing, outside ``root``, not spelt plainly, reached through a
            link, not a regular file with one name, too large, or not an answer.
    """
    spelt, top = str(path), str(root)
    if not (
        path.is_absolute()
        and root.is_absolute()
        and os.path.normpath(spelt) == spelt
        and os.path.normpath(top) == top
        and path.parent.is_relative_to(root)
    ):
        msg = "no answer file: the answer is named by a plain absolute path inside its root"
        raise TaskFormatError(msg, path=spelt, root=top)
    try:
        directory = _open_chain(path.parent, make=False)
    except AuthoringError as exc:
        msg = "no answer file: its directory is missing or reached through a link"
        raise TaskFormatError(msg, path=spelt) from exc
    try:
        try:
            fd = os.open(path.name, _FILE_FLAGS, dir_fd=directory)
        except OSError as exc:
            msg = f"no answer file: it cannot be opened without following a link ({exc.strerror})"
            raise TaskFormatError(msg, path=spelt) from exc
        try:
            raw = _read_bounded(fd, spelt)
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    return parse(raw, where=spelt)


def _read_bounded(fd: int, where: str) -> bytes:
    """The descriptor's bytes, from a regular file with one name, never past the bound and a byte.

    The read stops one byte past the bound, never trusting the size the descriptor reports: a
    size taken first is out of date the moment the file grows. One byte past is enough for
    :func:`parse_whole_run`, which holds the one size bound, to refuse it.
    """
    found = os.fstat(fd)
    if not stat.S_ISREG(found.st_mode):
        msg = "no answer file: it is not a regular file"
        raise TaskFormatError(msg, path=where)
    if found.st_nlink != 1:
        msg = "the answer file has a second name, through which it could be changed"
        raise TaskFormatError(msg, path=where, links=str(found.st_nlink))
    chunks: list[bytes] = []
    total = 0
    try:
        while total <= MAX_ANSWER_BYTES:
            chunk = os.read(fd, MAX_ANSWER_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        msg = f"no answer file: it cannot be read ({exc.strerror})"
        raise TaskFormatError(msg, path=where) from exc
    return b"".join(chunks)
