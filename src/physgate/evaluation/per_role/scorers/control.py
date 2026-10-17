"""The control scorer: a controller's closed loop with its plant, measured against the specs.

Independent of any published benchmark's own checker, and written so that the defects
found in one are impossible here:

- the plant is the whole numerator, never its first coefficient;
- a response that never settles inside the horizon is a failure, never a pass (a NaN
  compared with a bound is False both ways, which is how a published checker passed it);
- stability is judged on the loop with its delay, never on the delay-free plant;
- the phase margin is read off the exact frequency response, the delay as ``e^{-jωτ}``,
  on a frequency grid that follows the loop's own poles and zeros, so a crossover above
  any fixed grid is still found.

Closed loop: unity negative feedback, ``T = L / (1 + L)`` with ``L = C·G``. In the time
domain a delay enters through a Padé approximation of order :data:`PADE_ORDER`, cross-
checked at :data:`PADE_CHECK_ORDER`; measured against an exact delay-buffer simulation the
two agree within 0.2 % at every phase margin the public tasks ask for.

The score is canonical JSON, so the same answer scored twice gives the same bytes on the
same machine and library versions, which the score records.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any

import control as ct
import numpy as np

from physgate.evaluation.per_role.answer import LtiTf, read_lti_tf
from physgate.evaluation.per_role.base import Measure
from physgate.evaluation.per_role.exceptions import ReferenceCheckError, TaskFormatError
from physgate.evaluation.per_role.metrics import CONTROL_METRIC_UNITS
from physgate.evaluation.per_role.task import LoadedTask, Spec, Task, canonical_json

#: A real or complex numpy array. Spelt as ``Any``: the types are checked in the harness's
#: environment, which never has numpy (see the evaluation group in ``pyproject.toml``).
type Floats = Any

#: The scorer's version: part of every score, so a changed rule is a changed version.
SCORER_VERSION = "1.0.0"
PADE_ORDER = 10
PADE_CHECK_ORDER = 12
#: The time horizon, in multiples of the settling-time window's upper end, and its samples.
HORIZON_FACTOR = 20.0
HORIZON_POINTS = 40_001
#: Grid density, and how far the grid reaches past the loop's own slowest and fastest
#: pole or zero, in decades.
POINTS_PER_DECADE = 400
GRID_MARGIN_DECADES = 3.0
#: A measured value this close to its bound, relative to the bound, is flagged.
BORDERLINE_FRACTION = 0.005
#: Settling times at the two Padé orders further apart than this are flagged.
PADE_TOLERANCE = 0.005

#: The metric each spec may name, and the unit its bound must be written in.
METRIC_UNITS = CONTROL_METRIC_UNITS


class Plant:
    """The plant a task gives: ``gain * N(s) / D(s) * e^{-s·delay}``, from its inputs.

    The inputs are ``plant_num_<i>`` and ``plant_den_<i>`` (``i`` from 0, highest power
    first, each coefficient of ``s**k`` in ``s**k``), ``plant_gain`` and ``plant_delay``
    (in s, optional).
    """

    def __init__(self, task: Task) -> None:
        """Read the plant from ``task``'s inputs.

        Raises:
            TaskFormatError: a coefficient is missing, out of order or in the wrong unit.
        """
        by_name = {m.name: m for m in task.inputs}
        self.num = _poly(by_name, "plant_num", task.id)
        self.den = _poly(by_name, "plant_den", task.id)
        gain = by_name.get("plant_gain")
        self.gain = 1.0 if gain is None else float(_in_unit(gain, "1", task.id).value)
        delay = by_name.get("plant_delay")
        self.delay = 0.0 if delay is None else float(_in_unit(delay, "s", task.id).value)
        if self.delay < 0 or self.den[0] == 0:
            msg = f"the task {task.id!r} gives a plant with a negative delay or no leading term"
            raise TaskFormatError(msg, task=task.id)

    def tf(self) -> Any:
        """The delay-free part as a python-control transfer function."""
        return ct.tf([self.gain * c for c in self.num], self.den)


def _in_unit(measure: Measure, unit: str, task_id: str) -> Measure:
    if measure.unit != unit:
        msg = f"the task {task_id!r} gives {measure.unit!r} where {unit!r} belongs"
        raise TaskFormatError(msg, task=task_id)
    return measure


def _poly(by_name: Mapping[str, Measure], prefix: str, task_id: str) -> list[float]:
    coefficients: list[Measure] = []
    while f"{prefix}_{len(coefficients)}" in by_name:
        coefficients.append(by_name[f"{prefix}_{len(coefficients)}"])
    stray = [n for n in by_name if n.startswith(prefix + "_")]
    if not coefficients or len(stray) != len(coefficients):
        msg = f"the task {task_id!r} gives {prefix} coefficients out of sequence"
        raise TaskFormatError(msg, task=task_id)
    degree = len(coefficients) - 1
    for index, c in enumerate(coefficients):
        power = degree - index
        expected = "1" if power == 0 else ("s" if power == 1 else f"s**{power}")
        _in_unit(c, expected, task_id)
    return [float(c.value) for c in coefficients]


def _controller_tf(answer: LtiTf) -> Any:
    gain = float(answer.gain.value)
    return ct.tf([gain * c for c in answer.num_values()], answer.den_values())


def _loop_response(c: Any, g: Any, delay: float) -> Callable[[Floats], Floats]:
    cn, cd = (np.asarray(x, dtype=float) for x in (c.num[0][0], c.den[0][0]))
    gn, gd = (np.asarray(x, dtype=float) for x in (g.num[0][0], g.den[0][0]))

    def at(w: Floats) -> Floats:
        s = 1j * w
        value = np.polyval(cn, s) * np.polyval(gn, s) / (np.polyval(cd, s) * np.polyval(gd, s))
        return np.asarray(value * np.exp(-s * delay))

    return at


def _grid(c: Any, g: Any, at: Callable[[Floats], Floats]) -> Floats:
    """Frequencies from well below the loop's slowest root to well above its fastest.

    The upper end is pushed out a decade at a time until the loop's gain is below one
    there, and the lower end down until it is above one (or twelve decades have been
    added, for a loop whose gain never reaches one), so every gain crossover is inside.
    """
    roots = np.concatenate([ct.poles(c), ct.zeros(c), ct.poles(g), ct.zeros(g)])
    magnitudes = np.abs(roots[np.abs(roots) > 1e-12])
    low = (magnitudes.min() if magnitudes.size else 1.0) / 10**GRID_MARGIN_DECADES
    high = (magnitudes.max() if magnitudes.size else 1.0) * 10**GRID_MARGIN_DECADES
    for _ in range(12):
        if abs(at(np.array([high]))[0]) < 1.0:
            break
        high *= 10.0
    for _ in range(12):
        if abs(at(np.array([low]))[0]) > 1.0:
            break
        low /= 10.0
    decades = math.log10(high) - math.log10(low)
    return np.logspace(math.log10(low), math.log10(high), int(decades * POINTS_PER_DECADE) + 1)


def _bisect(f: Callable[[float], float], lo: float, hi: float) -> float:
    f_lo = f(lo)
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        f_mid = f(mid)
        if (f_lo <= 0) == (f_mid <= 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def _wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def phase_margin(c: Any, g: Any, delay: float) -> tuple[float, bool]:
    """The smallest phase margin over every gain crossover, in degrees, exactly.

    Returns ``(margin, crossed)``. With no gain crossover the margin is infinite, as
    python-control reports it, and ``crossed`` is False so the score can flag it.
    """
    at = _loop_response(c, g, delay)
    w = _grid(c, g, at)
    excess = np.abs(at(w)) - 1.0
    crossings = np.nonzero(np.sign(excess[:-1]) != np.sign(excess[1:]))[0]
    if crossings.size == 0:
        return math.inf, False
    margins = []
    for i in crossings:
        wc = _bisect(lambda x: float(abs(at(np.array([x]))[0]) - 1.0), w[i], w[i + 1])
        angle = math.degrees(float(np.angle(at(np.array([wc]))[0])))
        margins.append(_wrap(angle + 180.0))
    return min(margins), True


def gain_margin(c: Any, g: Any, delay: float) -> float:
    """The smallest gain margin over every phase crossover, as a ratio; infinite if none."""
    at = _loop_response(c, g, delay)
    w = _grid(c, g, at)
    phase = np.degrees(np.angle(at(w)))
    shifted = np.array([_wrap(p + 180.0) for p in phase])
    # A phase crossover is where the wrapped distance from -180 degrees changes sign
    # without jumping across the wrap.
    turns = np.nonzero(
        (np.sign(shifted[:-1]) != np.sign(shifted[1:]))
        & (np.abs(shifted[:-1] - shifted[1:]) < 180.0)
    )[0]
    if turns.size == 0:
        return math.inf
    ratios = []
    for i in turns:
        wp = _bisect(
            lambda x: _wrap(math.degrees(float(np.angle(at(np.array([x]))[0]))) + 180.0),
            w[i],
            w[i + 1],
        )
        ratios.append(1.0 / abs(at(np.array([wp]))[0]))
    return float(min(ratios))


def _closed_loop(c: Any, g: Any, delay: float, order: int) -> Any:
    loop = c * g
    if delay > 0:
        loop = loop * ct.tf(*ct.pade(delay, order))
    return ct.feedback(loop, 1)


def _settling(t_loop: Any, horizon: float, points: int = HORIZON_POINTS) -> tuple[float, float]:
    """The 2 % settling time and the overshoot (in %), NaN where they cannot be read.

    python-control's ``step_info`` raises rather than returning NaN when the response
    never reaches 90 % of its final value inside the horizon (measured on 0.10.1 with a
    loop a thousand times slower than its window). That is a response that did not settle,
    and an answer is never allowed to crash its own scoring.
    """
    times = np.linspace(0.0, horizon, points)
    try:
        info = ct.step_info(t_loop, times)
    except (IndexError, ValueError, ZeroDivisionError):
        return math.nan, math.nan
    return float(info["SettlingTime"]), float(info["Overshoot"])


def _horizon(task: Task) -> float:
    for spec in task.specs:
        if spec.metric == "settling_time":
            bound = spec.bound
            upper = bound[1] if isinstance(bound, tuple) else bound
            return HORIZON_FACTOR * float(upper.value)
    msg = f"the task {task.id!r} names no settling-time window to set the horizon from"
    raise TaskFormatError(msg, task=task.id)


def measure(
    task: Task, answer: LtiTf, *, points: int = HORIZON_POINTS, secondary: bool = True
) -> tuple[dict[str, float | None], dict[str, bool]]:
    """Every metric of ``answer``'s closed loop with ``task``'s plant, and the flags.

    A metric that cannot be measured (the loop is unstable, or its response never settles)
    is ``None``, which fails any bound. ``points`` and ``secondary`` are for the reference
    search, which screens many candidates coarsely; a score always uses the defaults.
    """
    plant = Plant(task)
    c, g = _controller_tf(answer), plant.tf()
    t_loop = _closed_loop(c, g, plant.delay, PADE_ORDER)
    max_pole = float(np.max(np.real(ct.poles(t_loop))))
    check_pole = float(np.max(np.real(ct.poles(_closed_loop(c, g, plant.delay, PADE_CHECK_ORDER)))))
    pm, crossed = phase_margin(c, g, plant.delay)
    gm = gain_margin(c, g, plant.delay) if secondary else math.inf
    values: dict[str, float | None] = {
        "max_real_pole": max(max_pole, check_pole),
        "phase_margin": pm,
        "gain_margin_ratio": gm,
        "gain_margin_db": 20.0 * math.log10(gm) if gm > 0 and math.isfinite(gm) else gm,
        "settling_time": None,
        "overshoot": None,
        "steady_state_error": None,
    }
    flags = {"no_gain_crossover": not crossed, "did_not_settle": False, "pade_unconverged": False}
    if values["max_real_pole"] is not None and values["max_real_pole"] < 0:
        horizon = _horizon(task)
        settling, overshoot = _settling(t_loop, horizon, points)
        if math.isnan(settling):
            flags["did_not_settle"] = True
        else:
            values["settling_time"] = settling
            values["overshoot"] = overshoot
            if plant.delay > 0:
                check, _ = _settling(
                    _closed_loop(c, g, plant.delay, PADE_CHECK_ORDER), horizon, points
                )
                flags["pade_unconverged"] = math.isnan(check) or (
                    abs(check - settling) > PADE_TOLERANCE * settling
                )
        values["steady_state_error"] = abs(1.0 - float(ct.dcgain(t_loop)))
    return values, flags


def _holds(spec: Spec, value: float | None) -> tuple[bool, bool]:
    """Whether ``value`` meets ``spec``, and whether it sits within the borderline band."""
    if value is None or math.isnan(value):
        return False, False
    bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
    limits = [float(b.value) for b in bounds]
    near = any(
        math.isfinite(value) and abs(value - x) <= BORDERLINE_FRACTION * max(abs(x), 1e-12)
        for x in limits
    )
    if spec.op == "in":
        return limits[0] <= value <= limits[1], near
    limit = limits[0]
    held = {
        ">=": value >= limit,
        "<=": value <= limit,
        ">": value > limit,
        "<": value < limit,
    }[spec.op]
    return held, near


def _library_versions() -> dict[str, str]:
    return {name: version(name) for name in ("control", "numpy", "scipy")}


def require_known_metrics(task: Task) -> None:
    """Refuse a task that names a metric this scorer lacks, or bounds one in another unit.

    Raises:
        TaskFormatError: an unknown metric, or a bound in a unit that is not the metric's.
    """
    for spec in task.specs:
        unit = METRIC_UNITS.get(spec.metric)
        if unit is None:
            msg = f"the task {task.id!r} names {spec.metric!r}, which the control scorer lacks"
            raise TaskFormatError(msg, task=task.id)
        bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
        for bound in bounds:
            _in_unit(bound, unit, task.id)


def score(task: Task, answer_path: Path) -> dict[str, Any]:
    """The score of the answer at ``answer_path`` against ``task``, as a plain record.

    An answer that is not a controller scores as a failure with its reason; it is never a
    scorer error. A task this scorer cannot judge is refused before anything is measured.

    Raises:
        TaskFormatError: the task is not one this scorer judges.
    """
    if task.scorer.id != "control" or task.scorer.version != SCORER_VERSION:
        msg = f"the task {task.id!r} asks for scorer {task.scorer.id} {task.scorer.version}"
        raise TaskFormatError(msg, task=task.id)
    require_known_metrics(task)
    record: dict[str, Any] = {
        "task": task.id,
        "scorer": {"id": "control", "version": SCORER_VERSION, "libraries": _library_versions()},
    }
    try:
        answer = read_lti_tf(answer_path)
    except TaskFormatError as exc:
        record.update(answer_valid=False, reason=str(exc), specs=[], flags={}, passed=False)
        return record
    try:
        values, flags = measure(task, answer)
    except (ValueError, ArithmeticError, IndexError, np.linalg.LinAlgError) as exc:
        # A controller whose loop the numerics cannot evaluate fails; it never crashes
        # the run that scores it. The reason is kept so a person can look.
        record.update(
            answer_valid=True, reason=f"unmeasurable: {exc!r}", specs=[], flags={}, passed=False
        )
        return record
    rows = []
    for spec in task.specs:
        value = values[spec.metric]
        held, near = _holds(spec, value)
        rows.append(
            {
                "name": spec.name,
                "metric": spec.metric,
                "counts": spec.counts,
                "measured": None
                if value is None or not math.isfinite(value)
                else {"value": value, "unit": METRIC_UNITS[spec.metric]},
                "infinite": value is not None and math.isinf(value),
                "passed": held,
                "borderline": near,
            }
        )
    passed = all(row["passed"] for row in rows if row["counts"] == "headline")
    record.update(answer_valid=True, specs=rows, flags=flags, passed=passed)
    return record


def score_bytes(task: Task, answer_path: Path) -> bytes:
    """The score of ``answer_path`` against ``task``, as canonical JSON."""
    return canonical_json(score(task, answer_path))


def check_references(loaded: LoadedTask) -> None:
    """Hold ``loaded``'s scorer to its references before any arm is scored with it.

    The good reference must pass. Each bad reference must fail, and the headline spec it
    names must be among those it fails: a bad reference that fails for another reason
    proves nothing about the spec it was built to test.

    Raises:
        ReferenceCheckError: a reference is scored otherwise.
    """
    for ref in loaded.references:
        record = score(loaded.task, Path(ref.answer_path))
        failed = {
            row["name"]
            for row in record["specs"]
            if row["counts"] == "headline" and not row["passed"]
        }
        if ref.fails is None and not record["passed"]:
            msg = f"the good reference of {loaded.task.id!r} fails {sorted(failed)}"
            raise ReferenceCheckError(msg, task=loaded.task.id, reference=ref.name)
        if ref.fails is not None and ref.fails not in failed:
            msg = (
                f"the bad reference {ref.name!r} of {loaded.task.id!r} should fail "
                f"{ref.fails!r}; it fails {sorted(failed)}"
            )
            raise ReferenceCheckError(msg, task=loaded.task.id, reference=ref.name)
