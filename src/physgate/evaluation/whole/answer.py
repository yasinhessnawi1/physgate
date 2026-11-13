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

import os
import re
import stat
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
from physgate.evaluation.tiers.authoring import AuthoringError, _open_chain
from physgate.evaluation.tiers.base import Measure

#: The largest answer file read: a controller, six settings and a list of paths.
MAX_ANSWER_BYTES = 64 * 1024
#: The longest delay accepted, in updates. Half a second at the reference brief's 100 Hz:
#: far past any delay a balancing loop survives, and it keeps the scorer's delay line small.
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
    """The whole-run answer at ``path``, which lies inside ``root``, or refused with the reason.

    The file is opened once and read from that one descriptor; nothing is looked up by path
    again, so nothing put in place between a check and the read is read. Its directory is
    reached from ``/`` one component at a time without following a link (the tier store's own
    walk), so a link anywhere on the way refuses, and the path as spelt is where the file is.
    The file itself is opened without following a link, and must be a regular file with one
    name: a hard link is a second name it could be changed or read through from outside
    ``root``. Its size is taken from the descriptor and held to the bound before a byte is
    read, and the read stops one byte past the bound, so a file that grows after its size was
    taken is refused too.

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
    return parse_whole_run(raw, where=spelt)


def _read_bounded(fd: int, where: str) -> bytes:
    """The descriptor's bytes, held to a regular file, one name and the size bound."""
    found = os.fstat(fd)
    if not stat.S_ISREG(found.st_mode):
        msg = "no answer file: it is not a regular file"
        raise TaskFormatError(msg, path=where)
    if found.st_nlink != 1:
        msg = "the answer file has a second name, through which it could be changed"
        raise TaskFormatError(msg, path=where, links=str(found.st_nlink))
    if found.st_size > MAX_ANSWER_BYTES:
        msg = f"the answer is larger than any whole-run answer ({found.st_size} bytes)"
        raise TaskFormatError(msg, path=where)
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
    if total > MAX_ANSWER_BYTES:
        msg = "the answer is larger than any whole-run answer (it grew while it was read)"
        raise TaskFormatError(msg, path=where)
    return b"".join(chunks)
