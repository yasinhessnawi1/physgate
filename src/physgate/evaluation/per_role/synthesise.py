"""Reference answers for control tasks, built by a seeded search and held to the scorer.

The good reference is found by differential evolution over a PID controller with a
filtered derivative (and, failing that, PID with a lead term), in log-parameter space,
with a fixed seed and a fixed number of generations and no time budget, so the same task
always gives the same reference. Its objective is how far the controller's closed loop
sits outside each headline specification, measured by the control scorer itself.

The bad references are built from the good one mechanically, each aimed at one
specification and kept only if the scorer fails it there:

- ``bad_unstable``: the good controller's gain scaled until the loop is unstable;
- ``bad_margin``: its gain raised until the phase margin falls short;
- ``bad_slow``: its gain lowered until the settling window is missed;
- ``bad_truncated_plant``: a controller searched for on the plant with only the first
  numerator coefficient, kept where it fails on the real plant (the published checker
  scored that truncated plant);
- ``bad_delay_free``: a controller searched for on the plant without its delay, kept
  where it fails with the delay (the published checker judged stability that way).

A task for which no good reference is found is reported, never dropped; one for which no
bad reference can be built is reported too.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import control as ct
import numpy as np
from scipy.optimize import differential_evolution

from physgate.evaluation.per_role.answer import LtiTf, power_unit
from physgate.evaluation.per_role.exceptions import SynthesisError
from physgate.evaluation.per_role.scorers import control as scorer
from physgate.evaluation.per_role.task import Task, canonical_json

SEED = 0
GENERATIONS = 60
POPULATION = 12
#: Log10 bounds: proportional, integral and derivative gains, the derivative filter's
#: corner, and the lead term's zero and pole.
GAIN_BOUNDS = (-3.0, 7.0)
FILTER_BOUNDS = (-1.0, 5.0)
LEAD_BOUNDS = (-3.0, 4.0)
#: Gain factors tried, in order, for each mechanically built bad reference.
UNSTABLE_FACTORS = (1e3, 1e-3, 1e4, 1e-4, 1e2, 1e-2, 1e5, 1e-5, 1e6, 1e-6)
MARGIN_FACTORS = tuple(1.5**k for k in range(1, 40))
SLOW_FACTORS = tuple(0.7**k for k in range(1, 40))
#: The coarse time grid candidates are screened on; a candidate that passes it is then
#: measured exactly as a score measures it, and found only if it passes that too.
SCREEN_POINTS = 2_001


def _pid(params: Sequence[float], lead: bool) -> Any:
    s = ct.tf("s")
    kp, ki, kd, corner = (10.0**x for x in params[:4])
    controller = kp + ki / s + kd * s / (s / corner + 1)
    if lead:
        zero, pole = 10.0 ** params[4], 10.0 ** params[5]
        controller = controller * (s / zero + 1) / (s / pole + 1)
    return ct.minreal(controller, verbose=False)


def _answer(controller: Any) -> LtiTf:
    num = [float(c) for c in np.atleast_1d(controller.num[0][0])]
    den = [float(c) for c in np.atleast_1d(controller.den[0][0])]
    scale = den[0]
    num, den = [c / scale for c in num], [c / scale for c in den]

    def coefficients(values: list[float]) -> list[dict[str, Any]]:
        degree = len(values) - 1
        return [{"value": v, "unit": power_unit(degree - i)} for i, v in enumerate(values)]

    return LtiTf.model_validate_json(
        json.dumps(
            {
                "form": "lti_tf",
                "gain": {"value": 1.0, "unit": "1"},
                "num": coefficients(num),
                "den": coefficients(den),
            }
        )
    )


def _scaled(answer: LtiTf, factor: float) -> LtiTf:
    return answer.model_copy(
        update={"gain": answer.gain.model_copy(update={"value": answer.gain.value * factor})}
    )


def _violation(task: Task, values: dict[str, float | None]) -> float:
    total = 0.0
    for spec in task.specs:
        if spec.counts != "headline":
            continue
        value = values[spec.metric]
        if value is None or math.isnan(value):
            total += 10.0
            continue
        bounds = spec.bound if isinstance(spec.bound, tuple) else (spec.bound,)
        limits = [float(b.value) for b in bounds]
        scale = max(abs(limits[-1]), 1e-9)
        if spec.op == "in":
            total += max(0.0, limits[0] - value) / max(abs(limits[0]), 1e-9)
            total += max(0.0, value - limits[1]) / scale
        elif spec.op in (">=", ">"):
            total += max(0.0, limits[0] - value) / scale
        else:
            total += max(0.0, value - limits[0]) / scale
            if spec.op == "<" and value >= limits[0]:
                total += 1.0 + min(value, 1e3)
    return total


def _measure(task: Task, answer: LtiTf, *, screen: bool = False) -> dict[str, float | None]:
    try:
        if screen:
            values, _ = scorer.measure(task, answer, points=SCREEN_POINTS, secondary=False)
        else:
            values, _ = scorer.measure(task, answer)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError):
        return dict.fromkeys(scorer.METRIC_UNITS)
    return values


def search(task: Task, *, seed: int = SEED) -> LtiTf:
    """A controller the scorer passes on every headline spec of ``task``.

    Raises:
        SynthesisError: neither family reached zero violation within the generations.
    """
    for lead in (False, True):
        bounds = [GAIN_BOUNDS] * 3 + [FILTER_BOUNDS] + ([LEAD_BOUNDS] * 2 if lead else [])
        found: dict[str, Any] = {}

        def objective(params: Any, lead: bool = lead, found: dict[str, Any] = found) -> float:
            if "answer" in found:
                return 0.0
            try:
                answer = _answer(_pid(params, lead))
            except (ValueError, ArithmeticError):
                return 1e6
            violation = _violation(task, _measure(task, answer, screen=True))
            if violation == 0.0:
                exact = _violation(task, _measure(task, answer))
                if exact == 0.0:
                    found["answer"] = answer
                return exact
            return violation

        differential_evolution(
            objective,
            bounds,
            seed=seed,
            maxiter=GENERATIONS,
            popsize=POPULATION,
            tol=0.0,
            polish=False,
            callback=lambda *_args, found=found, **_kw: "answer" in found,
        )
        if "answer" in found:
            answer: LtiTf = found["answer"]
            return answer
    msg = f"no PID or PID-lead controller meets every headline spec of {task.id!r}"
    raise SynthesisError(msg, task=task.id)


def _fails(task: Task, answer: LtiTf, spec_name: str) -> bool:
    values = _measure(task, answer)
    spec = next(s for s in task.specs if s.name == spec_name)
    return not scorer._holds(spec, values[spec.metric])[0]


def _first_failing(task: Task, good: LtiTf, factors: Sequence[float], spec: str) -> LtiTf | None:
    for factor in factors:
        candidate = _scaled(good, factor)
        if _fails(task, candidate, spec):
            return candidate
    return None


def _mismodelled(task: Task, *, truncate: bool, drop_delay: bool) -> Task | None:
    inputs = list(task.inputs)
    if truncate:
        numerator = [m for m in inputs if m.name.startswith("plant_num_")]
        if len(numerator) < 2:
            return None
        # The first coefficient alone, kept in the unit of the power it now stands for.
        first = numerator[0].model_copy(update={"unit": "1"})
        inputs = [m for m in inputs if not m.name.startswith("plant_num_")] + [first]
    if drop_delay:
        if not any(m.name == "plant_delay" for m in inputs):
            return None
        inputs = [m for m in inputs if m.name != "plant_delay"]
    return task.model_copy(update={"inputs": tuple(inputs)})


def bad_references(task: Task, good: LtiTf, *, seed: int = SEED) -> dict[str, tuple[LtiTf, str]]:
    """Every bad reference that could be built for ``task``, each with the spec it fails."""
    built: dict[str, tuple[LtiTf, str]] = {}
    for name, factors, spec in (
        ("bad_unstable", UNSTABLE_FACTORS, "stable"),
        ("bad_margin", MARGIN_FACTORS, "margin"),
        ("bad_slow", SLOW_FACTORS, "settling"),
    ):
        if any(s.name == spec for s in task.specs):
            candidate = _first_failing(task, good, factors, spec)
            if candidate is not None:
                built[name] = (candidate, spec)
    for name, truncate, drop_delay in (
        ("bad_truncated_plant", True, False),
        ("bad_delay_free", False, True),
    ):
        wrong = _mismodelled(task, truncate=truncate, drop_delay=drop_delay)
        if wrong is None:
            continue
        try:
            candidate = search(wrong, seed=seed)
        except SynthesisError:
            continue
        failed = [
            s.name for s in task.specs if s.counts == "headline" and _fails(task, candidate, s.name)
        ]
        if failed:
            built[name] = (candidate, failed[0])
    return built


def write_references(
    task_dir: Path, good: LtiTf, bads: dict[str, tuple[LtiTf, str]], answer_name: str
) -> None:
    """The references written beside ``task_dir/task.json`` in the layout tasks load from."""
    references = task_dir / "references"
    for name, answer, fails in [("good", good, None), *((n, a, f) for n, (a, f) in bads.items())]:
        ref = references / name
        ref.mkdir(parents=True, exist_ok=True)
        (ref / answer_name).write_bytes(canonical_json(answer.model_dump(mode="json")))
        if fails is not None:
            (ref / "expect.json").write_text(json.dumps({"fails": fails}) + "\n", encoding="utf-8")


def prepare(tasks: Sequence[Task], out: Path, *, seed: int = SEED) -> list[dict[str, Any]]:
    """Each task written to ``out`` with its references, and held to them; one row each.

    A task whose good reference cannot be found, or for which no bad reference can be
    built, is still written and gets its row saying so: the category stays whole and the
    gap is reported, never hidden.
    """
    from physgate.evaluation.per_role.controleval import write_task
    from physgate.evaluation.per_role.exceptions import ReferenceCheckError
    from physgate.evaluation.per_role.task import load_task

    rows: list[dict[str, Any]] = []
    for task in tasks:
        task_dir = write_task(task, out)
        row: dict[str, Any] = {"task": task.id, "good": False, "bad": [], "checked": False}
        try:
            good = search(task, seed=seed)
        except SynthesisError as exc:
            row["reason"] = str(exc)
            rows.append(row)
            continue
        bads = bad_references(task, good, seed=seed)
        write_references(task_dir, good, bads, task.answer.path)
        row.update(good=True, bad=sorted(f"{name}:{spec}" for name, (_, spec) in bads.items()))
        if not bads:
            row["reason"] = "no bad reference could be built"
        else:
            try:
                scorer.check_references(load_task(task_dir))
                row["checked"] = True
            except ReferenceCheckError as exc:
                row["reason"] = str(exc)
        rows.append(row)
    return rows
