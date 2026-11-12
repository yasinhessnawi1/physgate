"""A valid task of each tier, as plain dicts a test can break one field at a time."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def own_task(**changes: Any) -> dict[str, Any]:
    """A valid visible own control task composing two requirements."""
    task: dict[str, Any] = {
        "id": "control.pendulum_01",
        "role": "control",
        "tier": "visible",
        "source": {"kind": "own"},
        "brief": "Stabilise the plant. Write the controller to answer.json.",
        "inputs": [{"name": "plant_gain", "value": 2.0, "unit": "1"}],
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": [
            {
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["recover_tilt"],
            },
            {
                "name": "settling",
                "metric": "settling_time",
                "op": "in",
                "bound": [{"value": 0.1, "unit": "s"}, {"value": 2.0, "unit": "s"}],
                "composes": ["recover_tilt", "respect_actuator"],
            },
        ],
        "scorer": {"id": "control", "version": "1.1.0", "params": []},
    }
    task.update(copy.deepcopy(changes))
    return task


def external_task(**changes: Any) -> dict[str, Any]:
    """A valid ControlEval-shaped external task, one requirement per spec as published."""
    task = own_task(
        id="controleval.second_order_unstable.000",
        tier="external",
        source={
            "kind": "external",
            "benchmark": "controleval",
            "file": "ControlEval/second_order_unstable_data.json",
            "index": 0,
            "upstream_sha": "7a4898eb57b4c76cf5bc69afd4546a4630927bdb",
            "upstream_sha256": "826946d8d5fca7129add2485b0de66489ce5409997dae2dd575d494a5832c68c",
        },
        specs=[
            {
                "name": "stable",
                "metric": "max_real_pole",
                "op": "<",
                "bound": {"value": 0, "unit": "1/s"},
                "composes": ["as_posed"],
            }
        ],
    )
    task.update(copy.deepcopy(changes))
    return task


def controller(**changes: Any) -> dict[str, Any]:
    """A valid PI controller ``2 * (s + 1) / s`` in the ``lti_tf`` form."""
    answer: dict[str, Any] = {
        "form": "lti_tf",
        "gain": {"value": 2.0, "unit": "1"},
        "num": [{"value": 1.0, "unit": "s"}, {"value": 1.0, "unit": "1"}],
        "den": [{"value": 1.0, "unit": "s"}, {"value": 0.0, "unit": "1"}],
    }
    answer.update(copy.deepcopy(changes))
    return answer


def write_task_dir(
    root: Path, task: dict[str, Any], references: dict[str, tuple[dict[str, Any], str | None]]
) -> Path:
    """A task directory: ``task.json``, and each reference's answer and expectation."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.json").write_text(json.dumps(task), encoding="utf-8")
    for name, (answer, fails) in references.items():
        ref = root / "references" / name
        ref.mkdir(parents=True)
        (ref / task["answer"]["path"]).write_text(json.dumps(answer), encoding="utf-8")
        if fails is not None:
            (ref / "expect.json").write_text(json.dumps({"fails": fails}), encoding="utf-8")
    return root
