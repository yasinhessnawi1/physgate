"""The plant a session is told it is scored against is the plant the scorer builds, in numbers.

What a session is given for a control task (:func:`.tiers.issued.issued_text`) writes the plant
from the task's inputs as the scorer reads them: the coefficients of ``N(s)`` and ``D(s)``, the
gain and the delay (each said to be taken by default where the task gives none). Read back from
the text, they are the scorer's own plant, coefficient for coefficient and bit for bit, and its
transfer function is the scorer's; a task's score does not depend on how it is issued.
"""

from __future__ import annotations

import json
import re
from typing import Any

import control as ct
import numpy as np
import pytest

from physgate.evaluation.per_role.scorers.control import Plant
from physgate.evaluation.tiers.issued import issued_text
from physgate.evaluation.tiers.practice import PLANTS, practice_task
from physgate.evaluation.tiers.task import Task, parse_task


def _m(name: str, value: float, unit: str) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": unit}


def _own(inputs: list[dict[str, Any]]) -> Task:
    fields = practice_task(0)
    fields["inputs"] = inputs
    return parse_task(json.dumps(fields).encode())


TASKS: list[Task] = [
    *(parse_task(json.dumps(practice_task(n)).encode()) for n in range(len(PLANTS))),
    # A third-order plant with its own gain and a delay, the coefficients awkward floats.
    _own(
        [
            _m("plant_num_0", 0.1, "s"),
            _m("plant_num_1", 1 / 3, "1"),
            _m("plant_den_0", 2.0, "s**3"),
            _m("plant_den_1", 0.7, "s**2"),
            _m("plant_den_2", 1e-3, "s"),
            _m("plant_den_3", 0, "1"),
            _m("plant_gain", 1 / 7, "1"),
            _m("plant_delay", 0.02, "s"),
        ]
    ),
    # A gain-free integer plant: every value written as an integer in the task.
    _own([_m("plant_num_0", 7, "1"), _m("plant_den_0", 1, "s"), _m("plant_den_1", 3, "1")]),
]


def _polynomial(text: str, name: str) -> list[float]:
    line = re.search(rf"^{name}\(s\) = (.+)$", text, re.MULTILINE)
    assert line is not None, name
    return [float(term.split("*")[0]) for term in line.group(1).split(" + ")]


def _value(text: str, name: str) -> float:
    line = re.search(rf"^- {name} = (\S+) \[", text, re.MULTILINE)
    assert line is not None, name
    return float(line.group(1))


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id + str(len(t.inputs)))
def test_the_issued_plant_read_back_is_the_scorer_s_plant_bit_for_bit(task: Task) -> None:
    text = issued_text(task)
    plant = Plant(task)
    assert _polynomial(text, "N") == plant.num
    assert _polynomial(text, "D") == plant.den
    # Each coefficient's own line, as well as the polynomial it makes.
    names = sorted(m.name for m in task.inputs if m.name.startswith(("plant_num_", "plant_den_")))
    listed = {name: _value(text, name) for name in names}
    assert [listed[f"plant_num_{i}"] for i in range(len(plant.num))] == plant.num
    assert [listed[f"plant_den_{i}"] for i in range(len(plant.den))] == plant.den
    assert _value(text, "plant_gain") == plant.gain
    assert _value(text, "plant_delay") == plant.delay
    told = ct.tf(
        [_value(text, "plant_gain") * c for c in _polynomial(text, "N")], _polynomial(text, "D")
    )
    scored = plant.tf()
    assert np.array_equal(told.num[0][0], scored.num[0][0])
    assert np.array_equal(told.den[0][0], scored.den[0][0])
