"""A whole design judged against the brief's criteria: static, computed, and dynamic predicates.

A :class:`WholeDesignScenario` reads one whole-run answer and judges it on its task's specs,
each a metric, a comparison and a bound (E0's :class:`~physgate.evaluation.tiers.task.Spec`).
Its metrics fall into three classes:

- **static**, a setting the answer chose against its criterion: read from the answer alone;
- **computed**, a consequence of the answer on the plant (a stall current, a margin): the
  plant is the scenario's, never the answer's;
- **dynamic** (balancing at speed, push recovery): ``unscored`` until the dynamic environment
  exists, and labelled so in every record.

**A verdict never rests on an unsourced value.** A computed metric is evaluated at the
plant's nominal values and at every corner of the ranges of the parameters it reads
(:mod:`physgate.evaluation.whole.plant`). Where it passes at some and fails at others, it is
``unscored``, with the parameters that range and the count at each verdict, never pass or fail.
A static metric reads no plant parameter, so no range can move it.

**Outcomes.** ``fail`` when any headline spec fails; otherwise ``unscored`` when any headline
spec could not be judged; ``pass`` only when every headline spec passes. ``unscored`` is never
``fail``. An answer that is not a whole-run answer fails, with its reason; it is never an
error of the scorer.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.base import Identifier
from physgate.evaluation.tiers.scenario import Outcome, ScenarioError
from physgate.evaluation.tiers.task import COMPOSES_AT_LEAST, Spec, TaskId
from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import WholeRun, read_whole_run
from physgate.evaluation.whole.convert import ScaleFactor, SiLoop, coefficients, to_si
from physgate.evaluation.whole.plant import (
    LOOP_INPUTS,
    STALL_INPUTS,
    corners,
    nominal,
    parse_plant,
    ranged,
    stall_current,
)

Kind = Literal["static", "computed", "dynamic"]
Verdict = Literal["pass", "fail", "unscored"]

#: Every metric the scenario computes: its unit and its class.
METRICS: dict[str, tuple[str, Kind]] = {
    "command_limit": ("1", "static"),
    "command_limit_counts": ("count", "static"),
    "update_rate": ("Hz", "static"),
    "controller_rate": ("Hz", "static"),
    "gyro_output_data_rate": ("Hz", "static"),
    "gyro_full_scale": ("deg/s", "static"),
    "pwm_frequency": ("Hz", "static"),
    "pwm_full_scale": ("1", "static"),
    "encoder_counts_per_wheel_revolution": ("1", "static"),
    "coefficient_difference": ("1", "static"),
    "stall_current": ("A", "computed"),
    "phase_margin": ("deg", "computed"),
    "gain_margin_upward": ("1", "computed"),
    "gain_margin_downward": ("1", "computed"),
    "balanced_speed": ("m/s", "dynamic"),
    "push_recovery_tilt": ("deg", "dynamic"),
}
#: The plant parameters each computed metric reads.
METRIC_INPUTS: dict[str, tuple[str, ...]] = {
    "stall_current": STALL_INPUTS,
    "phase_margin": LOOP_INPUTS,
    "gain_margin_upward": LOOP_INPUTS,
    "gain_margin_downward": LOOP_INPUTS,
}
#: What every dynamic metric's record says.
DYNAMIC_REASON = "dynamic: judged only in the dynamic environment, which does not exist yet"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


class WholeDesignTask(_Frozen):
    """A whole-design scenario's own spec: its id, the criteria it composes, and its specs."""

    id: TaskId
    requirements: tuple[Identifier, ...] = Field(min_length=COMPOSES_AT_LEAST)
    specs: tuple[Spec, ...] = Field(min_length=1)


def _holds(spec: Spec, value: float) -> bool:
    bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
    limits = [float(b.value) for b in bounds]
    if math.isnan(value):
        return False
    if spec.op == "in":
        return limits[0] <= value <= limits[1]
    return {
        ">=": value >= limits[0],
        "<=": value <= limits[0],
        ">": value > limits[0],
        "<": value < limits[0],
    }[spec.op]


def _relative(a: float, b: float) -> float:
    if a == b:
        return 0.0
    if b == 0:
        return math.inf
    return abs(a - b) / abs(b)


def _static(answer: WholeRun, metric: str) -> tuple[float | None, str | None]:
    """A static metric's value, or ``None`` with the reason it has none."""
    p, c = answer.parameters, answer.controller
    si = to_si(c, p, wheel_radius=ScaleFactor("wheel_radius", 1.0, "m", "unused"))
    full_scale = float(p.pwm_full_scale.value)
    values: dict[str, Callable[[], float]] = {
        "command_limit": lambda: si.command_limit,
        "command_limit_counts": lambda: si.command_limit * full_scale,
        "update_rate": lambda: float(p.update_rate.value),
        "controller_rate": lambda: 1.0 / si.period,
        "gyro_output_data_rate": lambda: float(p.gyro_output_data_rate.value),
        "gyro_full_scale": lambda: float(p.gyro_full_scale.value),
        "pwm_frequency": lambda: float(p.pwm_frequency.value),
        "pwm_full_scale": lambda: full_scale,
        "encoder_counts_per_wheel_revolution": lambda: float(
            p.encoder_counts_per_wheel_revolution.value
        ),
    }
    if metric != "coefficient_difference":
        return values[metric](), None
    analysed = answer.analysed_controller
    if analysed is None:
        return 0.0, None
    if type(analysed) is not type(c):
        return None, (
            "the firmware's and the analysed controller are written in different structures; "
            "coefficients are compared as written, never through a conversion"
        )
    pairs = zip(coefficients(c), coefficients(analysed), strict=True)
    return max(_relative(float(a[1]), float(b[1])) for a, b in pairs), None


@dataclass
class _Corner:
    values: dict[str, float]
    loop: SiLoop | None = None
    margins: loop_module.Margins | None = None
    factors: tuple[ScaleFactor, ...] = field(default=())


class WholeDesignScenario:
    """One whole-design scenario: a task, the plant it is judged on, and the answers' root.

    Raises:
        ScenarioError: the task names a metric the scenario lacks, bounds one in another
            unit, or composes fewer than two requirements.
        PlantError: the plant file is not one.
    """

    def __init__(self, task: WholeDesignTask, plant: bytes, *, root: Path) -> None:
        """The scenario of ``task``, judged on the plant file ``plant``, answers in ``root``.

        The plant is parsed here from the bytes it is digested from, so the record's digest
        is the plant's that judged.
        """
        for spec in task.specs:
            known = METRICS.get(spec.metric)
            if known is None:
                msg = f"the task {task.id!r} names {spec.metric!r}, which no whole design has"
                raise ScenarioError(msg, task=task.id)
            bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
            if any(b.unit != known[0] for b in bounds):
                msg = f"the task {task.id!r} bounds {spec.metric} in another unit than {known[0]!r}"
                raise ScenarioError(msg, task=task.id)
        if len(set(task.requirements)) < COMPOSES_AT_LEAST:
            msg = f"the task {task.id!r} composes fewer than {COMPOSES_AT_LEAST} requirements"
            raise ScenarioError(msg, task=task.id)
        self._task = task
        self._plant = parse_plant(plant)
        self._root = root
        self._plant_digest = hashlib.sha256(plant).hexdigest()

    @property
    def id(self) -> str:
        """The scenario's stable id."""
        return self._task.id

    @property
    def requirements(self) -> tuple[str, ...]:
        """The criteria the scenario composes."""
        return self._task.requirements

    def score(self, answer: Path) -> Outcome:
        """The outcome of the answer at ``answer``."""
        outcome: Outcome = self.record(answer)["outcome"]
        return outcome

    def record(self, answer: Path) -> dict[str, Any]:
        """The full judgement of the answer at ``answer``, as a plain record."""
        record: dict[str, Any] = {
            "scenario": self.id,
            "plant": {"status": self._plant.status, "sha256": self._plant_digest},
        }
        try:
            read = read_whole_run(answer, root=self._root)
        except TaskFormatError as exc:
            record.update(answer_valid=False, reason=str(exc), specs=[], outcome="fail")
            return record
        corner_sets = self._corner_sets(read)
        rows = [self._row(spec, read, corner_sets) for spec in self._task.specs]
        headline = [row["verdict"] for row in rows if row["counts"] == "headline"]
        outcome: Outcome = (
            "fail" if "fail" in headline else "unscored" if "unscored" in headline else "pass"
        )
        nominal_corner = corner_sets["nominal"][0]
        record.update(
            answer_valid=True,
            structure=read.controller.structure,
            scale_factors=[f.__dict__ for f in nominal_corner.factors],
            specs=rows,
            outcome=outcome,
        )
        return record

    def _corner_sets(self, read: WholeRun) -> dict[str, list[_Corner]]:
        sets: dict[str, list[_Corner]] = {"nominal": [_Corner(nominal(self._plant))]}
        for inputs in {
            METRIC_INPUTS[s.metric] for s in self._task.specs if s.metric in METRIC_INPUTS
        }:
            sets[",".join(inputs)] = [_Corner(c) for c in corners(self._plant, inputs)]
        for corner_list in sets.values():
            for corner in corner_list:
                radius = ScaleFactor(
                    "wheel_radius",
                    corner.values["wheel_radius"],
                    "m",
                    "the plant's wheel_radius: " + self._plant.parameters["wheel_radius"].source,
                )
                corner.loop = to_si(read.controller, read.parameters, wheel_radius=radius)
                corner.factors = corner.loop.factors
        return sets

    def _computed(self, metric: str, read: WholeRun, corner: _Corner) -> float:
        assert corner.loop is not None
        if metric == "stall_current":
            return stall_current(corner.values, corner.loop.command_limit)
        if corner.margins is None:
            corner.margins = loop_module.margins(corner.values, corner.loop)
        m = corner.margins
        if not m.stable:
            return math.nan
        value = {
            "phase_margin": m.phase_margin,
            "gain_margin_upward": m.upward,
            "gain_margin_downward": m.downward,
        }[metric]
        assert value is not None
        return value

    def _row(self, spec: Spec, read: WholeRun, sets: dict[str, list[_Corner]]) -> dict[str, Any]:
        unit, kind = METRICS[spec.metric]
        row: dict[str, Any] = {
            "name": spec.name,
            "metric": spec.metric,
            "kind": kind,
            "counts": spec.counts,
            "composes": list(spec.composes),
        }
        if kind == "dynamic":
            row.update(verdict="unscored", measured=None, reason=DYNAMIC_REASON)
            return row
        if kind == "static":
            value, reason = _static(read, spec.metric)
            if value is None:
                row.update(verdict="fail", measured=None, reason=reason)
                return row
            row.update(
                verdict="pass" if _holds(spec, value) else "fail",
                measured=_measure(value, unit),
                reason="reads no plant parameter",
            )
            return row
        inputs = METRIC_INPUTS[spec.metric]
        at_nominal = self._computed(spec.metric, read, sets["nominal"][0])
        values = [self._computed(spec.metric, read, c) for c in sets[",".join(inputs)]]
        held = [_holds(spec, v) for v in values]
        varied = ranged(self._plant, inputs)
        row.update(
            measured=_measure(at_nominal, unit),
            corners={
                "ranged": list(varied),
                "count": len(values),
                "passing": sum(held),
                "unstable": sum(math.isnan(v) for v in values),
                "low": _measure(min(values), unit) if not any(map(math.isnan, values)) else None,
                "high": _measure(max(values), unit) if not any(map(math.isnan, values)) else None,
            },
        )
        if all(held) and _holds(spec, at_nominal):
            row.update(verdict="pass", reason="passes at the nominal values and every corner")
        elif not any(held) and not _holds(spec, at_nominal):
            row.update(verdict="fail", reason="fails at the nominal values and every corner")
        else:
            row.update(
                verdict="unscored",
                reason=(
                    f"passes at {sum(held)} of {len(values)} corners of the ranges of "
                    f"{', '.join(varied)}: the verdict rests on values no source fixes"
                ),
            )
        return row


def _measure(value: float, unit: str) -> dict[str, Any] | None:
    if math.isnan(value):
        return None
    return {
        "value": value if math.isfinite(value) else None,
        "infinite": math.isinf(value),
        "unit": unit,
    }
