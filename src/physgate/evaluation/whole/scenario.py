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
A static metric reads no plant parameter, so no range can move it. **A computed "pass" means
pass at the nominal values and at every corner of the ranges**; points inside the ranges are
not searched, so a margin that dips between corners is not seen.

**Outcomes.** ``fail`` when any headline spec fails; otherwise ``unscored`` when any headline
spec could not be judged; ``pass`` only when every headline spec passes. ``unscored`` is never
``fail``. An answer that is not a whole-run answer fails, with its reason; it is never an
error of the scorer. A sampled law with a term that is not linear (``nonlinear``) or reads a
signal outside the closed list (``out_of_scope``) is the exception, but only if that term can
affect the command: a term of weight 0, or in a line nothing the command reads reads, is taken
out and the law judged without it (the record lists what was set aside). A law with such a term
that can matter cannot be judged, so it is ``unscored`` with a ``refusal`` of that name, never a
fail, and only after every other check has run on it: a fault anywhere else in the answer
(a name not declared, a unit that does not balance, a setting, a zero divisor) is the ordinary
fail, so a scope refusal never covers an invalid answer. It does cover an answer that is valid and
would fail: a law with a live term the scorer cannot take is not judged, whatever else it would
have scored (an unstable law with one more term of any weight on a signal outside the list is
``unscored``, not ``fail``); a dead term is never such a ground. ``unscored`` is never a pass and
stays in the denominator, so nothing is bought by it. Nor is an answer the analysis
cannot compute with, or one whose analysis would cost more than :data:`MAX_WORK`: each fails as a
named ``refusal``, the work bound decided before any of the work is done. The ways an answer ends
``unscored`` are exactly: a law with a live term out of scope in the primary controller; a
headline row that cannot be judged (a dynamic metric, criterion 19 with no analysed controller or
a different structure, an analysed law out of scope or with other lines or coefficients, corners
that disagree, so a law that is unstable at one corner and not another can end there); and a law
whose written numbers do not correspond to the law scored (an internal fault of the scorer,
``written_numbers_do_not_match``).

**The plant judged on.** The scenario judges on a frozen plant (one of
:data:`~physgate.evaluation.whole.plant.FROZEN_PLANTS`, by digest) unless it is told it judges a
draft; every record names the plant's version (``None`` for a draft), status and digest.

**What a record holds.** ``plant``; ``answer_valid`` and, when not, ``reason``; ``work``, the
loop analyses' cost known before they run (``corners``: the parameter sets the loop is analysed
at, every corner and the nominal set; ``steps``: the most closed-loop evaluations one analysis
makes; ``states``: the closed loop's state count; ``total``, their product; ``bound``,
:data:`MAX_WORK`), each a value and its unit; ``refusal``, when the answer was refused by name;
``specs``, one row per spec, a margin's row with the ``search`` grid its searches used; and
``outcome``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.base import Identifier
from physgate.evaluation.tiers.scenario import Outcome, ScenarioError
from physgate.evaluation.tiers.task import COMPOSES_AT_LEAST, Spec, TaskId
from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import (
    Answer,
    OutsideScope,
    SampledLaw,
    read_answer_scoped,
)
from physgate.evaluation.whole.convert import ScaleFactor, SiLoop, coefficients, to_si
from physgate.evaluation.whole.plant import (
    FROZEN_PLANTS,
    LOOP_INPUTS,
    STALL_INPUTS,
    PlantError,
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
    "pwm_full_scale": ("count", "static"),
    "encoder_counts_per_wheel_revolution": ("count", "static"),
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
#: The metrics read from the balance loop's analysis.
LOOP_METRICS = frozenset(m for m, inputs in METRIC_INPUTS.items() if inputs == LOOP_INPUTS)
#: The most work one score may do, in closed-loop state-evaluations (corners × steps ×
#: states, :meth:`WholeDesignScenario._work`). A chosen bound: an ordinary design (a 10 ms
#: loop, its delay under one period) on v0's 1,024 corners is 17 to 24 million, well under a
#: minute; this is four times the larger, so such a design is judged even on a plant ranging
#: the most parameters allowed (4,096 corners), and no score costs more than a few minutes.
MAX_WORK = 100_000_000
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


def _static(
    answer: Answer, metric: str, refused: OutsideScope | None = None
) -> tuple[float | None, str | None]:
    """A static metric's value, or ``None`` with the reason it has none."""
    p, c = answer.parameters, answer.controller
    si = to_si(c, p, wheel_radius=ScaleFactor("wheel_radius", 1.0, "m", "unused"))
    full_scale = float(p.pwm_full_scale.value)
    values: dict[str, Callable[[], float]] = {
        "command_limit": lambda: si.command_limit,
        "command_limit_counts": lambda: si.command_limit * full_scale,
        "update_rate": lambda: float(p.update_rate.value),
        "controller_rate": lambda: 1.0 / si.period,
        "gyro_output_data_rate": lambda: float(_output_data_rate(p).value),
        "gyro_full_scale": lambda: float(p.gyro_full_scale.value),
        "pwm_frequency": lambda: float(p.pwm_frequency.value),
        "pwm_full_scale": lambda: full_scale,
        "encoder_counts_per_wheel_revolution": lambda: float(
            p.encoder_counts_per_wheel_revolution.value
        ),
    }
    if metric != "coefficient_difference":
        return values[metric](), None
    if refused is not None:
        return None, f"the analysed controller is out of the scorer's reach ({refused}); not judged"
    analysed = answer.analysed_controller
    if analysed is None:
        return None, (
            "no analysed controller is stated, so there is no second controller to compare "
            "the firmware's with; not judged either way"
        )
    if type(analysed) is not type(c):
        return None, (
            "the firmware's and the analysed controller are written in different structures; "
            "coefficients are compared as written, never through a conversion"
        )
    if isinstance(c, SampledLaw) and isinstance(analysed, SampledLaw):
        # For a law the structure is its lines: two laws with the same coefficient names and
        # numbers and different lines are two controllers, and no number says they are one.
        if (c.memory, c.lines, c.command) != (analysed.memory, analysed.lines, analysed.command):
            return None, (
                "the firmware's and the analysed law differ in their lines (their memory, their "
                "terms or their command); laws are compared as written, never through a conversion"
            )
        if set(c.coefficients) != set(analysed.coefficients):
            return None, (
                "the firmware's and the analysed law name different coefficients; they are "
                "compared as written, never through a conversion"
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

    def __init__(
        self, task: WholeDesignTask, plant: bytes, *, root: Path, draft: bool = False
    ) -> None:
        """The scenario of ``task``, judged on the plant file ``plant``, answers in ``root``.

        The plant is parsed here from the bytes it is digested from, so the record's digest
        is the plant's that judged. It is a frozen plant, held to its recorded digest, unless
        ``draft`` says the caller judges a draft; a draft is then taken only with its status a
        draft, so an edited frozen plant is never judged.
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
        self._analysed_refusal: OutsideScope | None = None
        #: The sampled law's flags of the answer being judged, on every row beside the record's.
        self._law_flags: dict[str, Any] = {}
        self._plant_digest = hashlib.sha256(plant).hexdigest()
        self._plant_version = FROZEN_PLANTS.get(self._plant_digest)
        if draft and self._plant.status != "draft":
            msg = "the plant is not a frozen plant's file, and its status says it is not a draft"
            raise PlantError(msg)
        if not draft and self._plant_version is None:
            msg = (
                f"the plant is not a frozen plant: its digest {self._plant_digest} is none of "
                "the frozen plants', and the scenario was not told it judges a draft"
            )
            raise PlantError(msg)

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
            "plant": {
                "version": self._plant_version,
                "status": self._plant.status,
                "sha256": self._plant_digest,
            },
        }
        try:
            read, analysed_refusal = read_answer_scoped(answer, root=self._root)
        except OutsideScope as exc:
            # A law that is not linear, or reads a signal outside the closed list, is refused by
            # name: the scorer cannot judge it, which is no verdict on the design.
            record.update(answer_valid=False, reason=str(exc))
            record.update(refusal={"name": exc.name, "reason": str(exc)})
            record.update(specs=[], outcome="unscored")
            return record
        except TaskFormatError as exc:
            record.update(answer_valid=False, reason=str(exc), specs=[], outcome="fail")
            return record
        record.update(answer_valid=True, structure=read.controller.structure)
        self._analysed_refusal = analysed_refusal
        self._law_flags = {}
        if analysed_refusal is not None:
            record["analysed_refusal"] = {
                "name": analysed_refusal.name,
                "reason": str(analysed_refusal),
            }
        try:
            return self._judged(record, read)
        except law_module.LawRefused as exc:
            # The law's own numbers do not correspond to the law that is scored (a fault of the
            # scorer's, not of the design): no verdict, refused by name, never a pass.
            record.pop("specs", None)
            record.update(refusal={"name": exc.code, "reason": str(exc)}, specs=[])
            record.update(outcome="unscored")
            return record

    def _judged(self, record: dict[str, Any], read: Answer) -> dict[str, Any]:
        """``record`` with the answer's work, its rows and its outcome."""
        if isinstance(read.controller, SampledLaw):
            law_record = _law_record(read.controller)
            record.update(law_record)
            self._law_flags = {k: law_record[k] for k in FLAG_KEYS}
        work = self._work(read)
        record["work"] = {name: _quantity(value, "1") for name, value in work.items()}
        record["work"]["bound"] = _quantity(MAX_WORK, "1")
        if work["total"] > MAX_WORK:
            reason = (
                f"the analysis would take {work['total']:,} state-evaluations ({work['corners']} "
                f"parameter sets, {work['steps']} steps, {work['states']} states), past the "
                f"bound of {MAX_WORK:,}; refused before any of it"
            )
            record.update(refusal={"name": "work_bound", "reason": reason})
            record.update(specs=[], outcome="fail")
            return record
        try:
            corner_sets = self._corner_sets(read)
            rows = [self._row(spec, read, corner_sets) for spec in self._task.specs]
        except loop_module.NUMERICAL_FAILURES as exc:
            reason = f"the analysis could not compute with the answer: {type(exc).__name__}: {exc}"
            record.update(refusal={"name": "numerical_failure", "reason": reason})
            record.update(specs=[], outcome="fail")
            return record
        headline = [row["verdict"] for row in rows if row["counts"] == "headline"]
        outcome: Outcome = (
            "fail" if "fail" in headline else "unscored" if "unscored" in headline else "pass"
        )
        nominal_corner = corner_sets["nominal"][0]
        record.update(
            scale_factors=[f.__dict__ for f in nominal_corner.factors],
            specs=rows,
            outcome=outcome,
        )
        return record

    def _radius(self, values: dict[str, float]) -> ScaleFactor:
        return ScaleFactor(
            "wheel_radius",
            values["wheel_radius"],
            "m",
            "the plant's wheel_radius: " + self._plant.parameters["wheel_radius"].source,
        )

    def _work(self, read: Answer) -> dict[str, int]:
        """The loop analyses' work, known before any is done: corners, steps, states, total."""
        loop = to_si(
            read.controller, read.parameters, wheel_radius=self._radius(nominal(self._plant))
        )
        reads_loop = any(s.metric in LOOP_METRICS for s in self._task.specs)
        corners = 1 + 2 ** len(ranged(self._plant, LOOP_INPUTS)) if reads_loop else 0
        steps, states = loop_module.steps(loop), loop_module.states(loop)
        return {
            "corners": corners,
            "steps": steps,
            "states": states,
            "total": corners * steps * states,
        }

    def _corner_sets(self, read: Answer) -> dict[str, list[_Corner]]:
        sets: dict[str, list[_Corner]] = {"nominal": [_Corner(nominal(self._plant))]}
        for inputs in {
            METRIC_INPUTS[s.metric] for s in self._task.specs if s.metric in METRIC_INPUTS
        }:
            sets[",".join(inputs)] = [_Corner(c) for c in corners(self._plant, inputs)]
        for corner_list in sets.values():
            for corner in corner_list:
                radius = self._radius(corner.values)
                corner.loop = to_si(read.controller, read.parameters, wheel_radius=radius)
                corner.factors = corner.loop.factors
        return sets

    def _computed(self, metric: str, read: Answer, corner: _Corner) -> float:
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

    def _row(self, spec: Spec, read: Answer, sets: dict[str, list[_Corner]]) -> dict[str, Any]:
        unit, kind = METRICS[spec.metric]
        row: dict[str, Any] = {
            "name": spec.name,
            "metric": spec.metric,
            "kind": kind,
            "counts": spec.counts,
            "composes": list(spec.composes),
        }
        if isinstance(read.controller, SampledLaw):
            row.update(self._law_flags)
        if kind == "dynamic":
            row.update(verdict="unscored", measured=None, reason=DYNAMIC_REASON)
            return row
        if kind == "static":
            value, reason = _static(read, spec.metric, self._analysed_refusal)
            if value is None:
                # Not judged either way: criterion 19's relative difference of 0 is taken
                # coefficient by coefficient, and two structures share no coefficient.
                row.update(verdict="unscored", measured=None, reason=reason)
                return row
            row.update(
                verdict="pass" if _holds(spec, value) else "fail",
                measured=_measure(value, unit),
                reason="reads no plant parameter",
            )
            return row
        inputs = METRIC_INPUTS[spec.metric]
        nominal_corner = sets["nominal"][0]
        at_nominal = self._computed(spec.metric, read, nominal_corner)
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
        if spec.metric in LOOP_METRICS:
            assert nominal_corner.loop is not None
            row["search"] = loop_module.search_grid(nominal_corner.loop.period)
        unstable = _unstable_reason(nominal_corner, at_nominal, values)
        if all(held) and _holds(spec, at_nominal):
            row.update(
                verdict="pass",
                reason=(
                    "passes at the nominal values and at every corner of the ranges; the "
                    "ranges' interior is not searched"
                ),
            )
        elif not any(held) and not _holds(spec, at_nominal):
            row.update(
                verdict="fail",
                reason="fails at the nominal values and at every corner of the ranges" + unstable,
            )
        else:
            row.update(
                verdict="unscored",
                reason=(
                    f"passes at {sum(held)} of {len(values)} corners of the ranges of "
                    f"{', '.join(varied)}: the verdict rests on values no source fixes"
                ),
            )
        return row


#: The keys of the flags on the record and on every row of a sampled law.
FLAG_KEYS = (
    "no_interface_statement",
    "compute_delay_flags",
    "compute_delay_omitted",
    "held_state_flags",
)


def _flags(law: SampledLaw, modes: Sequence[law_module.HeldMode]) -> dict[str, Any]:
    """What is flagged about the law, by name: on the record and on every row.

    What the export flagged about its timing (the answer says it; a raw answer's own claim), and
    the flag the scorer decides itself from the law's own modes: a held state a signal feeds and
    the command reads.
    """
    return {
        "no_interface_statement": list(law.no_interface_statement),
        "compute_delay_flags": list(law.compute_delay_flags),
        "compute_delay_omitted": list(law.compute_delay_omitted),
        "held_state_flags": list(law_module.held_state_flags(modes)),
    }


def _law_record(law: SampledLaw) -> dict[str, Any]:
    """What the record says of a sampled law beside its flags.

    The signals it reads (a law that reads the true tilt is judged as if tilt were measured
    directly, as the named state feedback is); each mode the stability test sets aside, with the
    memory states in it, what feeds them and whether the command reads them, and the note that a
    held state is bounded in the model and not in the firmware; and each out-of-scope term that
    cannot affect the command, taken out before judging.
    """
    values = {name: float(m.value) for name, m in law.coefficients.items()}
    modes = law_module.held_report(law, values, period=float(law.period.value), written=law.written)
    return {
        **_flags(law, modes),
        "law_signals": list(law_module.signals_read(law)),
        "held_modes": [mode.as_record() for mode in modes],
        "set_aside": [
            {"line": o.line, "term": o.index + 1, "code": o.code, "detail": o.detail}
            for o in law.set_aside
        ],
    }


def _output_data_rate(p: Any) -> Any:
    """The gyro's output data rate under either version's name for it."""
    return p.output_data_rate if hasattr(p, "output_data_rate") else p.gyro_output_data_rate


def _unstable_reason(nominal_corner: _Corner, at_nominal: float, values: list[float]) -> str:
    """Why a margin has no number, when the loop is unstable somewhere: a clause, or ``""``."""
    count = sum(math.isnan(v) for v in values)
    if count == 0 and not math.isnan(at_nominal):
        return ""
    where = f"at {count} of {len(values)} corners"
    if math.isnan(at_nominal):
        where += " and at the nominal values"
    clause = f"; the closed loop is unstable {where}, and an unstable loop has no margin"
    loop = nominal_corner.loop
    if loop is not None and loop.law is None and loop.distance == 0.0:
        clause += (
            "; with no distance gain nothing holds the travel, so the plant's travel stays a "
            "pole at 1 and the loop is never strictly stable"
        )
    return clause


def _quantity(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}


def _measure(value: float, unit: str) -> dict[str, Any] | None:
    if math.isnan(value):
        return None
    return {
        "value": value if math.isfinite(value) else None,
        "infinite": math.isinf(value),
        "unit": unit,
    }
