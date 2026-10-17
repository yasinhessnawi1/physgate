"""Plants, controllers and tasks for the control scorer's tests: our own numbers only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role.answer import power_unit
from physgate.evaluation.per_role.task import Task, parse_task


def poly(prefix: str, coefficients: list[float]) -> list[dict[str, Any]]:
    """Plant inputs for one polynomial, highest power first, each in the unit of its power."""
    degree = len(coefficients) - 1
    return [
        {"name": f"{prefix}_{i}", "value": c, "unit": power_unit(degree - i)}
        for i, c in enumerate(coefficients)
    ]


def coefficients(values: list[float]) -> list[dict[str, Any]]:
    """A controller polynomial, highest power first, each coefficient in its power's unit."""
    degree = len(values) - 1
    return [{"value": v, "unit": power_unit(degree - i)} for i, v in enumerate(values)]


def controller(num: list[float], den: list[float], gain: float = 1.0) -> dict[str, Any]:
    """An ``lti_tf`` answer."""
    return {
        "form": "lti_tf",
        "gain": {"value": gain, "unit": "1"},
        "num": coefficients(num),
        "den": coefficients(den),
    }


#: An unstable second-order plant, 10 / (s**2 - 2 s + 3), and a PID with a filtered
#: derivative that holds it: 2 + 4/s + s/(s/100 + 1), written over one denominator.
UNSTABLE_NUM = [10.0]
UNSTABLE_DEN = [1.0, -2.0, 3.0]
GOOD_PID = controller([1.02, 2.04, 4.0], [0.01, 1.0, 0.0])


def control_task(
    num: list[float] = UNSTABLE_NUM,
    den: list[float] = UNSTABLE_DEN,
    *,
    delay: float | None = None,
    pm_min: float = 45.0,
    ts: tuple[float, float] = (0.05, 3.0),
    ess_max: float = 1e-4,
    extra_specs: list[dict[str, Any]] | None = None,
) -> Task:
    """A visible own task: hold ``num/den`` stable, with a margin, a settling window and ess."""
    inputs = poly("plant_num", num) + poly("plant_den", den)
    if delay is not None:
        inputs.append({"name": "plant_delay", "value": delay, "unit": "s"})
    specs: list[dict[str, Any]] = [
        {
            "name": "stable",
            "metric": "max_real_pole",
            "op": "<",
            "bound": {"value": 0, "unit": "1/s"},
            "composes": ["hold_the_plant"],
        },
        {
            "name": "margin",
            "metric": "phase_margin",
            "op": ">=",
            "bound": {"value": pm_min, "unit": "deg"},
            "composes": ["hold_the_plant", "tolerate_model_error"],
        },
        {
            "name": "settling",
            "metric": "settling_time",
            "op": "in",
            "bound": [{"value": ts[0], "unit": "s"}, {"value": ts[1], "unit": "s"}],
            "composes": ["respond_in_time"],
        },
        {
            "name": "accuracy",
            "metric": "steady_state_error",
            "op": "<=",
            "bound": {"value": ess_max, "unit": "1"},
            "composes": ["respond_in_time"],
        },
        *(extra_specs or []),
    ]
    task = {
        "id": "control.test_plant",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": "Hold the plant. Write the controller to answer.json.",
        "inputs": inputs,
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": specs,
        "scorer": {"id": "control", "version": "1.0.0"},
    }
    return parse_task(json.dumps(task).encode())


def write_answer(directory: Path, answer: dict[str, Any], name: str = "answer.json") -> Path:
    """``answer`` written as JSON in ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(answer), encoding="utf-8")
    return path
