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
- ``x``, the axle's ground travel in m (the mean of the two wheels'), and ``v`` its ground
  speed in m/s, each measured minus a reference that advances at the commanded speed, so both
  are zero when the robot holds its commanded motion;
- ``u``, the command to both motors as a duty: the average voltage across a motor is ``u``
  times the pack voltage, positive driving forward, held to ``[-limit, +limit]``.

**The closed list of structures.** Each runs once per ``period``:

- ``incremental_rising_offset``, the form of the reference kit's own balancing example: the
  command is changed, never set, by
  ``u[k] = sat(u[k-1] + angle_gain·(θ[k] + rate_ratio·θ̇[k]) + distance_gain·x[k]
  + speed_gain·v[k])``. ``θ + rate_ratio·θ̇`` is zero on the trajectory that rises to
  vertical with no speed left. Gains in 1/rad, s, 1/m and s/m;
- ``state_feedback``, a discrete state feedback that sets the command,
  ``u[k] = sat(angle_gain·θ[k] + rate_gain·θ̇[k] + distance_gain·x[k] + speed_gain·v[k])``.
  Gains in 1/rad, s/rad, 1/m and s/m.

In both, the measurements used at update ``k`` were taken ``sensor_delay`` updates earlier,
and the command computed at ``k`` reaches the motors ``compute_delay`` updates later; both
are whole numbers of updates. A structure off the list is refused rather than approximated:
a scorer that guessed what an unknown structure meant would be judging its own guess.

**Units are exact spellings**, as for the per-role controller: each field is given in the one
unit below, and any other spelling, however equivalent, is refused, so no answer is judged
through a conversion it did not ask for.

``controller`` is the controller the firmware runs. ``analysed_controller``, when given, is
the one the design's analysis is shown for; a brief can require the two to be the same, and
the scorer compares them. ``files`` names module files the answer refers to, by path inside
the answer's directory; reading them is the scorer's business, and naming them here grants
nothing outside that directory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.base import Measure

#: The largest answer file read: a controller, six settings and a list of paths.
MAX_ANSWER_BYTES = 64 * 1024
#: The longest delay accepted, in updates. Half a second at the reference brief's 100 Hz:
#: far past any delay a balancing loop survives, and it keeps the scorer's delay line small.
MAX_DELAY_SAMPLES = 50
#: The largest magnitude any value may have (not yet enforced).
MAX_MAGNITUDE = 1e12
#: The most module files an answer names.
MAX_FILES = 64
#: The longest path to a module file.
MAX_PATH_LENGTH = 200
#: One part of a path: ASCII letters, digits, ``_``, ``.`` and ``-``, not starting with a dot,
#: so neither ``..`` nor a hidden directory (a repository's own ``.git``) is ever a part.
_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


def _unit(measure: Measure, unit: str, what: str) -> float:
    if measure.unit != unit:
        msg = f"{what} is in {measure.unit!r}; it is given in {unit!r}"
        raise ValueError(msg)
    return float(measure.value)


def _positive(measure: Measure, unit: str, what: str) -> float:
    value = _unit(measure, unit, what)
    if not value > 0:
        msg = f"{what} is {value} {unit}; it is positive"
        raise ValueError(msg)
    return value


def _whole(value: float) -> bool:
    return value.is_integer()


class _Loop(_Frozen):
    """What every structure has: its period, its command limit and its two delays."""

    period: Measure
    command_limit: Measure
    sensor_delay: Measure
    compute_delay: Measure

    @model_validator(mode="after")
    def _timing_is_physical(self) -> _Loop:
        _positive(self.period, "s", "the period")
        limit = _unit(self.command_limit, "1", "the command limit")
        if not 0 < limit <= 1:
            msg = f"the command limit is {limit}; it is a duty above 0 and at most 1"
            raise ValueError(msg)
        for what, delay in (
            ("the sensor delay", self.sensor_delay),
            ("the compute delay", self.compute_delay),
        ):
            samples = _unit(delay, "1", what)
            if not (_whole(samples) and 0 <= samples <= MAX_DELAY_SAMPLES):
                msg = (
                    f"{what} is {samples}; it is a whole number of samples from 0 to "
                    f"{MAX_DELAY_SAMPLES}"
                )
                raise ValueError(msg)
        return self


class IncrementalRisingOffset(_Loop):
    """The command changed each update by the rising offset, the travel and the speed."""

    structure: Literal["incremental_rising_offset"]
    rate_ratio: Measure
    angle_gain: Measure
    distance_gain: Measure
    speed_gain: Measure

    @model_validator(mode="after")
    def _gains_in_their_units(self) -> IncrementalRisingOffset:
        _unit(self.rate_ratio, "s", "the rate ratio")
        _unit(self.angle_gain, "1/rad", "the angle gain")
        _unit(self.distance_gain, "1/m", "the distance gain")
        _unit(self.speed_gain, "s/m", "the speed gain")
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
        _unit(self.angle_gain, "1/rad", "the angle gain")
        _unit(self.rate_gain, "s/rad", "the rate gain")
        _unit(self.distance_gain, "1/m", "the distance gain")
        _unit(self.speed_gain, "s/m", "the speed gain")
        return self


#: A controller, one structure of the closed list, told apart by its ``structure``.
Controller = Annotated[IncrementalRisingOffset | StateFeedback, Field(discriminator="structure")]


class Parameters(_Frozen):
    """The settings a brief constrains that the design chooses, each in its own unit."""

    update_rate: Measure
    gyro_output_data_rate: Measure
    gyro_full_scale: Measure
    pwm_frequency: Measure
    pwm_full_scale: Measure
    encoder_counts_per_wheel_revolution: Measure

    @model_validator(mode="after")
    def _each_positive_in_its_unit(self) -> Parameters:
        _positive(self.update_rate, "Hz", "the update rate")
        _positive(self.gyro_output_data_rate, "Hz", "the gyro's output data rate")
        _positive(self.gyro_full_scale, "deg/s", "the gyro's full scale")
        _positive(self.pwm_frequency, "Hz", "the PWM frequency")
        full_scale = _positive(self.pwm_full_scale, "1", "the PWM full scale")
        if not _whole(full_scale):
            msg = f"the PWM full scale is {full_scale}; it is a whole number of counts"
            raise ValueError(msg)
        # Not a whole number: counting every edge of a 12-count encoder through a 110.24:1
        # drive gives 1322.9 counts per wheel revolution, and that is the true figure.
        _positive(
            self.encoder_counts_per_wheel_revolution,
            "1",
            "the encoder counts per wheel revolution",
        )
        return self


def _module_path(path: str) -> str:
    if len(path) > MAX_PATH_LENGTH or not all(_PART.fullmatch(p) for p in path.split("/")):
        msg = f"the file {path!r} is not a plain path inside the answer's directory"
        raise ValueError(msg)
    return path


ModulePath = Annotated[str, AfterValidator(_module_path)]


class WholeRun(_Frozen):
    """One whole-run answer: the controller, the chosen settings and the files it names."""

    form: Literal["whole_run"]
    version: Literal[1]
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


def parse_whole_run(raw: bytes, *, where: str = "answer") -> WholeRun:
    """``raw`` validated whole as a whole-run answer, or refused with the reason.

    Raises:
        TaskFormatError: it is too large, not UTF-8, not JSON, or not a whole-run answer.
    """
    if len(raw) > MAX_ANSWER_BYTES:
        msg = f"the answer is larger than any whole-run answer ({len(raw)} bytes)"
        raise TaskFormatError(msg, where=where)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "the answer is not UTF-8 text"
        raise TaskFormatError(msg, where=where) from exc
    try:
        return WholeRun.model_validate_json(text)
    except ValidationError as exc:
        msg = f"the answer is not a whole-run answer: {exc.errors()[0]['msg']}"
        raise TaskFormatError(msg, where=where) from exc


def read_whole_run(path: Path, *, root: Path) -> WholeRun:
    """The whole-run answer at ``path``, or refused with the reason.

    Raises:
        TaskFormatError: it is missing, a link, not a regular file, or not an answer.
    """
    del root  # not yet held to it
    if path.is_symlink() or not path.is_file():
        msg = "no answer file"
        raise TaskFormatError(msg, path=str(path))
    return parse_whole_run(path.read_bytes(), where=str(path))
