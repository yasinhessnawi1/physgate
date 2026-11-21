"""A law is untrusted input: whatever is written in it, the reader refuses it by name or reads it.

Seeded mutations of the recorded design's law, in an answer (primary and analysed) and in a law
file: a value replaced by a junk one (null, a truth value, a huge integer, a list, an expression,
a signal outside the list) or a key taken out, up to three at a time. Every refusal is a
:class:`TaskFormatError` for an answer and a :class:`LawRefused` for a file; nothing else escapes.
The found escapes (a memory that is not a list, an integer past a float in a number or a
coefficient) each have a row of their own below.
"""

from __future__ import annotations

import copy
import importlib
import json
import random
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role.exceptions import TaskFormatError

_HERE = Path(__file__).resolve().parent
_FILE = json.loads((_HERE / "recorded_law" / "law.json").read_text())
_LAW = "physgate.evaluation.whole.law"
_ANSWER = "physgate.evaluation.whole.answer"

JUNK: list[Any] = [
    None,
    True,
    0,
    -1,
    1.5,
    10**400,
    1e308,
    "",
    "x",
    "previous.",
    "line.command",
    "accelerometer_tilt",
    "tilt*tilt_rate",
    [],
    [1],
    {},
    {"a": 1},
    ["tilt"],
    "tilt\n",
]
SETTINGS: dict[str, Any] = {
    "update_rate": {"value": 100, "unit": "Hz"},
    "output_data_rate": {"value": 208, "unit": "Hz"},
    "gyro_full_scale": {"value": 1000, "unit": "deg/s"},
    "pwm_frequency": {"value": 20000, "unit": "Hz"},
    "pwm_full_scale": {"value": 400, "unit": "count"},
    "encoder_counts_per_wheel_revolution": {"value": 1322.9, "unit": "count"},
}
COEFFICIENTS: dict[str, Any] = {
    "k_phi": {"value": -0.0054505, "unit": "1/rad"},
    "k_theta": {"value": -1.03529, "unit": "1/rad"},
    "k_w": {"value": -0.038326, "unit": "s/rad"},
    "k_rate": {"value": -0.0625146, "unit": "s/rad"},
    "k_u": {"value": -0.346975, "unit": "1"},
    "leak": {"value": 0.999, "unit": "1"},
}


def _controller() -> dict[str, Any]:
    return {
        "structure": "sampled_law",
        **{k: copy.deepcopy(_FILE[k]) for k in ("memory", "lines", "command")},
        "coefficients": copy.deepcopy(COEFFICIENTS),
        "period": {"value": 0.01, "unit": "s"},
        "command_limit": {"value": 0.9425, "unit": "1"},
        "sensor_delay": {"value": 1 / 208, "unit": "s"},
        "compute_delay": {"value": 0.004, "unit": "s"},
    }


def _paths(node: Any, prefix: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    found = [prefix]
    if isinstance(node, dict):
        for key, value in node.items():
            found += _paths(value, (*prefix, key))
    elif isinstance(node, list):
        for at, value in enumerate(node):
            found += _paths(value, (*prefix, at))
    return found


def _mutate(document: dict[str, Any], rnd: random.Random) -> None:
    for _ in range(rnd.choice([1, 1, 2, 3])):
        path = rnd.choice(_paths(document)[1:])
        holder: Any = document
        for key in path[:-1]:
            holder = holder[key]
        if rnd.random() < 0.2:
            if isinstance(holder, dict):
                holder.pop(path[-1], None)
            else:
                del holder[path[-1]]
        else:
            holder[path[-1]] = copy.deepcopy(rnd.choice(JUNK))


def test_no_mutated_answer_escapes_as_anything_but_a_refusal() -> None:
    answer = importlib.import_module(_ANSWER)
    rnd = random.Random(20261121)
    refused = read = 0
    for _ in range(1500):
        document: dict[str, Any] = {
            "form": "whole_run",
            "version": 3,
            "controller": _controller(),
            "parameters": copy.deepcopy(SETTINGS),
        }
        if rnd.random() < 0.3:
            document["analysed_controller"] = _controller()
            document["analysed_controller"]["lines"][-1]["terms"][0]["of"] = rnd.choice(
                ["accelerometer_tilt", "a*b", "tilt"]
            )
        _mutate(document, rnd)
        raw = json.dumps(document).encode()
        for parse in (answer.parse_answer, answer.parse_answer_scoped):
            try:
                parse(raw)
                read += 1
            except TaskFormatError:
                refused += 1
            except Exception as exc:  # noqa: BLE001 - what escaped is the finding
                pytest.fail(f"{type(exc).__name__} escaped: {exc}\n{json.dumps(document)[:400]}")
    assert refused > 100
    assert read > 0


def test_no_mutated_law_file_escapes_as_anything_but_a_refusal() -> None:
    law = importlib.import_module(_LAW)
    rnd = random.Random(20261122)
    for _ in range(1500):
        document = copy.deepcopy(_FILE)
        _mutate(document, rnd)
        raw = json.dumps(document).encode()
        for defer in (False, True):
            try:
                law.parse_file(raw, defer_scope=defer)
            except law.LawRefused:
                pass
            except Exception as exc:  # noqa: BLE001 - what escaped is the finding
                pytest.fail(f"{type(exc).__name__} escaped: {exc}\n{json.dumps(document)[:400]}")


def _refused(raw: bytes, *words: str) -> None:
    """The answer is refused as a format error; anything else it raises is the finding."""
    answer = importlib.import_module(_ANSWER)
    try:
        answer.parse_answer(raw)
    except TaskFormatError as exc:
        for word in words:
            assert word in str(exc), str(exc)
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding
        pytest.fail(f"{type(exc).__name__} escaped: {exc}")
    else:
        pytest.fail("the answer was read")


@pytest.mark.parametrize("memory", [None, 1.5, "z", {}, [None, 3]])
def test_a_memory_that_is_not_a_list_of_states_is_refused_not_an_exception(memory: Any) -> None:
    controller = _controller()
    controller["memory"] = memory
    controller["lines"][-1]["terms"][0]["of"] = "accelerometer_tilt"
    _refused(
        json.dumps(
            {"form": "whole_run", "version": 3, "controller": controller, "parameters": SETTINGS}
        ).encode()
    )


@pytest.mark.parametrize("where", ["number", "coefficient"])
def test_an_integer_past_a_float_is_refused_by_the_bound_not_by_an_overflow(where: str) -> None:
    controller = _controller()
    if where == "number":
        controller["lines"][-1]["terms"][0]["number"] = 10**400
    else:
        controller["coefficients"]["k_phi"]["value"] = 10**400
    raw = json.dumps(
        {"form": "whole_run", "version": 3, "controller": controller, "parameters": SETTINGS}
    ).encode()
    _refused(raw, "digits")
