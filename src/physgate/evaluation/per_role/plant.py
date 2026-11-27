"""The control scorer's reading of a task's inputs: its plant, its reference step, its limit.

Kept apart from the scorer, which needs the evaluation's numerical libraries, so that what a
session is given (:mod:`physgate.evaluation.tiers.issued`) is written from the same reading the
scorer measures with, in the harness's own environment, and the two cannot come apart.

The inputs are ``plant_num_<i>`` and ``plant_den_<i>`` (``i`` from 0, highest power first,
each coefficient of ``s**k`` in ``s**k``), ``plant_gain`` (in 1) and ``plant_delay`` (in s),
``reference_step`` and ``actuator_limit``. Three of them are taken by default where a task
does not give them: the gain as 1, the delay as 0 and the reference step as 1.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from physgate.evaluation.per_role.answer import power_unit
from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.metrics import ACTUATOR_LIMIT, ACTUATOR_PEAK, REFERENCE_STEP
from physgate.evaluation.tiers.base import Measure, NamedMeasure
from physgate.evaluation.tiers.task import Task

NUMERATOR = "plant_num"
DENOMINATOR = "plant_den"
GAIN = "plant_gain"
DELAY = "plant_delay"
#: What the scorer takes where a task does not give the value, and the unit it is taken in.
DEFAULTS: dict[str, Measure] = {
    GAIN: Measure(value=1.0, unit="1"),
    DELAY: Measure(value=0.0, unit="s"),
    REFERENCE_STEP: Measure(value=1.0, unit="1"),
}


@dataclass(frozen=True)
class PlantReading:
    """A task's plant as the scorer reads it: every coefficient, the gain and the delay.

    ``num`` and ``den`` are the coefficients as measures, highest power first, each in the unit
    of its power; ``gain`` and ``delay`` are the task's own, or ``None`` where it gives none and
    the scorer takes its default.
    """

    num: tuple[NamedMeasure, ...]
    den: tuple[NamedMeasure, ...]
    gain: NamedMeasure | None
    delay: NamedMeasure | None

    @property
    def gain_value(self) -> float:
        """The gain the scorer multiplies the numerator by."""
        return float((DEFAULTS[GAIN] if self.gain is None else self.gain).value)

    @property
    def delay_value(self) -> float:
        """The delay the scorer delays the plant's input by, in s."""
        return float((DEFAULTS[DELAY] if self.delay is None else self.delay).value)


def in_unit[M: Measure](measure: M, unit: str, task_id: str) -> M:
    """``measure``, refused unless it is written in ``unit``.

    Raises:
        TaskFormatError: it is written in another unit.
    """
    if measure.unit != unit:
        msg = f"the task {task_id!r} gives {measure.unit!r} where {unit!r} belongs"
        raise TaskFormatError(msg, task=task_id)
    return measure


def _poly(
    by_name: Mapping[str, NamedMeasure], prefix: str, task_id: str
) -> tuple[NamedMeasure, ...]:
    coefficients: list[NamedMeasure] = []
    while f"{prefix}_{len(coefficients)}" in by_name:
        coefficients.append(by_name[f"{prefix}_{len(coefficients)}"])
    stray = [n for n in by_name if n.startswith(prefix + "_")]
    if not coefficients or len(stray) != len(coefficients):
        msg = f"the task {task_id!r} gives {prefix} coefficients out of sequence"
        raise TaskFormatError(msg, task=task_id)
    degree = len(coefficients) - 1
    for index, c in enumerate(coefficients):
        in_unit(c, power_unit(degree - index), task_id)
    return tuple(coefficients)


def read_plant(task: Task) -> PlantReading:
    """The plant ``task``'s inputs give, as the scorer reads it.

    Raises:
        TaskFormatError: a coefficient is missing, out of order or in the wrong unit, the
            delay is negative, or the denominator has no leading term.
    """
    by_name = {m.name: m for m in task.inputs}
    num = _poly(by_name, NUMERATOR, task.id)
    den = _poly(by_name, DENOMINATOR, task.id)
    gain = by_name.get(GAIN)
    if gain is not None:
        in_unit(gain, "1", task.id)
    delay = by_name.get(DELAY)
    if delay is not None:
        in_unit(delay, "s", task.id)
    reading = PlantReading(num=num, den=den, gain=gain, delay=delay)
    if reading.delay_value < 0 or float(den[0].value) == 0:
        msg = f"the task {task.id!r} gives a plant with a negative delay or no leading term"
        raise TaskFormatError(msg, task=task.id)
    return reading


def bounds_actuator_peak(task: Task) -> bool:
    """Whether ``task`` bounds the controller's peak output, the one metric using two inputs."""
    return any(spec.metric == ACTUATOR_PEAK for spec in task.specs)


def actuator_limit(task: Task) -> NamedMeasure:
    """The task's actuator limit, whose unit every bound on the controller's peak is in.

    Raises:
        TaskFormatError: the task gives none.
    """
    limit = next((m for m in task.inputs if m.name == ACTUATOR_LIMIT), None)
    if limit is None:
        msg = f"the task {task.id!r} bounds {ACTUATOR_PEAK} but gives no {ACTUATOR_LIMIT}"
        raise TaskFormatError(msg, task=task.id)
    return limit


def reference_step(task: Task) -> NamedMeasure | None:
    """The task's reference step, or ``None`` where it gives none and the scorer takes 1."""
    return next((m for m in task.inputs if m.name == REFERENCE_STEP), None)


__all__ = [
    "DEFAULTS",
    "DELAY",
    "DENOMINATOR",
    "GAIN",
    "NUMERATOR",
    "PlantReading",
    "actuator_limit",
    "bounds_actuator_peak",
    "in_unit",
    "read_plant",
    "reference_step",
]
