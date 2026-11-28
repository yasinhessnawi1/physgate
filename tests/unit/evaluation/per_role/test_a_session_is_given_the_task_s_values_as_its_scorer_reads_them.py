"""A session is given a task's brief, its values as its scorer reads them, and where to answer.

A brief may write its plant in symbols whose values only the task's inputs hold, and the scorer
reads the plant from the inputs. What a session is given (:func:`.tiers.issued.issued_text`) is
the brief, byte for byte, then every input by name, value and unit, each value the scorer takes
by default where the task gives none (labelled so, and only where the scorer uses it), the plant
those values make, and the answer contract. It is the same bytes on every call, and the same for
two tasks that differ only in what is scored or how the task is filed. A task the scorer cannot
read is refused, with the scorer's own reason.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from task_fixtures import own_task

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.tiers.issued import (
    brief_sha256,
    given_the_brief_alone,
    issued_bytes,
    issued_sha256,
    issued_text,
)
from physgate.evaluation.tiers.task import Task, parse_task

BRIEF = (
    "Hold the cart. Its plant is G(s) = plant_gain * plant_num_0 / (s^2 + plant_den_1 s + "
    "plant_den_2). Keep the actuator within the given limit. Write the controller to answer.json."
)
#: A made-up task whose plant is written in symbols, and whose gain no input gives.
SYMBOLS: list[dict[str, Any]] = [
    {"name": "plant_num_0", "value": 3, "unit": "1"},
    {"name": "plant_den_0", "value": 1.0, "unit": "s**2"},
    {"name": "plant_den_1", "value": 0.5, "unit": "s"},
    {"name": "plant_den_2", "value": -2.0, "unit": "1"},
    {"name": "actuator_limit", "value": 2.5, "unit": "N*m"},
]
PEAK = {
    "name": "effort",
    "metric": "actuator_peak",
    "op": "<=",
    "bound": {"value": 2.5, "unit": "N*m"},
    "composes": ["respect_actuator"],
}


def _task(**changes: Any) -> Task:  # noqa: ANN401
    fields = own_task(brief=BRIEF, inputs=SYMBOLS)
    fields["specs"] = [*fields["specs"], PEAK]
    fields.update(changes)
    return parse_task(json.dumps(fields).encode())


def test_the_text_is_the_brief_then_every_value_the_plant_and_where_the_answer_goes() -> None:
    assert issued_text(_task()) == (
        BRIEF
        + """

## The values this task gives

Each value is written as name = value [unit].

- plant_num_0 = 3.0 [1]
- plant_den_0 = 1.0 [s**2]
- plant_den_1 = 0.5 [s]
- plant_den_2 = -2.0 [1]
- plant_gain = 1.0 [1]: not given by the task; taken as 1.0
- plant_delay = 0.0 [s]: not given by the task; taken as 0.0
- actuator_limit = 2.5 [N*m]
- reference_step = 1.0 [1]: not given by the task; taken as 1.0

The plant these values make, as the answer is scored against it (s in 1/s):
G(s) = plant_gain * N(s) / D(s) * exp(-plant_delay * s)
N(s) = 3.0
D(s) = 1.0*s^2 + 0.5*s + -2.0

## Where the answer goes

The file `answer.json` in the directory you work in, in the form `lti_tf`.
"""
    )


def test_the_text_begins_with_the_brief_byte_for_byte_whatever_the_brief_ends_in() -> None:
    for brief in (BRIEF, BRIEF + "\n", BRIEF + "\n\n"):
        text = issued_text(_task(brief=brief))
        assert text.startswith(brief)
        assert text[len(brief) :].lstrip("\n").startswith("## The values this task gives")


def test_a_value_the_task_gives_is_written_as_given_and_never_said_to_be_taken() -> None:
    given = [
        *SYMBOLS,
        {"name": "plant_gain", "value": 4.0, "unit": "1"},
        {"name": "plant_delay", "value": 0.05, "unit": "s"},
        {"name": "reference_step", "value": 0.2, "unit": "m"},
    ]
    text = issued_text(_task(inputs=given))
    assert "not given by the task" not in text
    assert "- plant_gain = 4.0 [1]\n" in text
    assert "- plant_delay = 0.05 [s]\n" in text
    assert "- reference_step = 0.2 [m]\n" in text


def test_the_reference_step_is_said_to_be_taken_only_where_the_scorer_uses_it() -> None:
    # Without a bound on the controller's peak output, the scorer never reads the step.
    fields = own_task(brief=BRIEF, inputs=SYMBOLS[:4])
    text = issued_text(parse_task(json.dumps(fields).encode()))
    assert "reference_step" not in text
    assert "- plant_gain = 1.0 [1]: not given by the task; taken as 1.0" in text


def test_the_text_is_the_same_bytes_on_every_call() -> None:
    assert issued_bytes(_task()) == issued_bytes(_task()) == issued_text(_task()).encode()
    assert issued_sha256(_task()) == hashlib.sha256(issued_bytes(_task())).hexdigest()


def test_tasks_differing_only_in_what_is_scored_or_how_they_are_filed_are_given_one_text() -> None:
    """No bound, spec name, requirement, id, tier, canary or scorer parameter reaches it."""
    base = _task()
    specs = [
        {**s.model_dump(mode="json"), "name": f"zq_{s.name}", "composes": ["zq_a", "zq_b"]}
        for s in base.specs
    ]
    specs[1]["bound"] = [{"value": 0.7, "unit": "s"}, {"value": 9.5, "unit": "s"}]
    specs[2]["bound"] = {"value": 1.75, "unit": "N*m"}
    other = _task(
        id="control.zq_other",
        tier="held_out",
        canary="ab" * 16,
        specs=specs,
        scorer={
            "id": "control",
            "version": "1.1.0",
            "params": [{"name": "zq_param", "value": 7.25, "unit": "1"}],
        },
    )
    assert issued_bytes(other) == issued_bytes(base)
    assert not [
        word for word in ("zq", "9.5", "1.75", "7.25", "ab" * 16) if word in issued_text(other)
    ]


def test_a_task_that_bounds_the_peak_output_with_no_actuator_limit_is_refused_by_name() -> None:
    task = _task(inputs=SYMBOLS[:4])
    with pytest.raises(TaskFormatError, match="bounds actuator_peak but gives no actuator_limit"):
        issued_text(task)


@pytest.mark.parametrize(
    ("inputs", "said"),
    [
        (
            [m for m in SYMBOLS if m["name"] != "plant_den_1"],
            "gives plant_den coefficients out of sequence",
        ),
        (
            [{**m, "unit": "1"} if m["name"] == "plant_den_1" else m for m in SYMBOLS],
            "gives '1' where 's' belongs",
        ),
        (
            [*SYMBOLS, {"name": "plant_delay", "value": -0.1, "unit": "s"}],
            "a negative delay or no leading term",
        ),
    ],
)
def test_a_task_whose_plant_the_scorer_cannot_read_is_refused_with_the_scorer_s_reason(
    inputs: list[dict[str, Any]], said: str
) -> None:
    with pytest.raises(TaskFormatError, match=said):
        issued_text(_task(inputs=inputs))


def test_a_task_of_another_scorer_is_given_its_brief_its_inputs_and_its_answer_contract() -> None:
    fields = own_task(
        brief="Blink the lamp.\n",
        inputs=[{"name": "period", "value": 0.5, "unit": "s"}],
        scorer={"id": "firmware", "version": "1.0.0", "params": []},
    )
    task = parse_task(json.dumps(fields).encode())
    assert issued_text(task) == (
        "Blink the lamp.\n\n## The values this task gives\n\nEach value is written as name = "
        "value [unit].\n\n- period = 0.5 [s]\n\n## Where the answer goes\n\nThe file "
        "`answer.json` in the directory you work in, in the form `lti_tf`.\n"
    )


def test_a_run_given_a_task_s_brief_alone_is_told_apart_from_a_run_given_the_task() -> None:
    task = _task()
    assert given_the_brief_alone(brief_sha256(task), [task])
    assert not given_the_brief_alone(issued_sha256(task), [task])
    assert not given_the_brief_alone("f" * 64, [task])
    assert brief_sha256(task) == hashlib.sha256(BRIEF.encode()).hexdigest()
