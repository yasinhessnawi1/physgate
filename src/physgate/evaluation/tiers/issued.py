"""What a session is given for a task: its brief, the values it gives, and where its answer goes.

A task is defined as giving a session its brief, its inputs and its answer contract
(:class:`.task.Task`), and its scorer reads the plant from the inputs, not from the brief. A
brief may write the plant in symbols whose values only the inputs hold, so a session given the
brief alone may be given less than the answer is judged against. :func:`issued_text` is the one
text both arms are given: the raw arm's prompt and the harness trial's brief file are these bytes.

It is the brief, byte for byte, then:

- **the values the task gives**, each as ``name = value [unit]``. For a control task they are
  written as the control scorer reads them (:func:`.per_role.plant.read_plant`): the plant's
  coefficients in order, then its gain and delay, then every other input in the task's order;
  a value the scorer takes by default where the task gives none (the gain as 1, the delay as 0,
  and the reference step as 1 where the task bounds the controller's peak output, the one metric
  that uses it) is written too, said to be not given by the task and taken as that default;
- **the plant those values make**, for a control task, as the scorer builds it, in numbers;
- **where the answer goes**: the answer contract's path and form.

Nothing of the scored specifications is added (their bounds are the brief's to state) and no
reference answer: the text is a function of the brief, the inputs, the answer contract and
whether the task bounds the peak output, and of nothing else. A task the control scorer refuses
to read (a coefficient out of sequence or in another unit, a peak bound with no actuator limit)
is refused here with the scorer's own reason, so no session is given a task its answer cannot
be scored on.

A run records the digest of the text it was given (:func:`issued_sha256`), and every reader that
finds a run's task finds it by that digest. A tier's own maps, a round's order and its places
stay keyed by the brief's digest (:func:`brief_sha256`), so nothing that orders or names tasks
moves. A run whose recorded digest is a task's brief alone was given less than the task, and is
told apart (:func:`given_the_brief_alone`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from physgate.evaluation.per_role.metrics import REFERENCE_STEP
from physgate.evaluation.per_role.plant import (
    DEFAULTS,
    DELAY,
    GAIN,
    actuator_limit,
    bounds_actuator_peak,
    read_plant,
)
from physgate.evaluation.tiers.base import Measure
from physgate.evaluation.tiers.task import Task

VALUES_HEADING = "## The values this task gives"
ANSWER_HEADING = "## Where the answer goes"
#: How a value the scorer takes by default is marked, after its line.
TAKEN = ": not given by the task; taken as {value}"


def _number(value: float | int) -> str:
    # As the scorer reads it: a float, written by ``repr``, which reads back to the same float.
    return repr(float(value))


def _line(name: str, measure: Measure, *, taken: bool = False) -> str:
    text = f"- {name} = {_number(measure.value)} [{measure.unit}]"
    return text + (TAKEN.format(value=_number(measure.value)) if taken else "")


def _polynomial(coefficients: Iterable[Measure]) -> str:
    values = [float(c.value) for c in coefficients]
    degree = len(values) - 1
    terms = []
    for index, value in enumerate(values):
        power = degree - index
        variable = "" if power == 0 else ("*s" if power == 1 else f"*s^{power}")
        terms.append(f"{value!r}{variable}")
    return " + ".join(terms)


def _control_values(task: Task) -> list[str]:
    plant = read_plant(task)
    lines = [_line(m.name, m) for m in (*plant.num, *plant.den)]
    for name, given in ((GAIN, plant.gain), (DELAY, plant.delay)):
        lines.append(
            _line(name, DEFAULTS[name], taken=True) if given is None else _line(name, given)
        )
    if bounds_actuator_peak(task):
        # The scorer reads the limit's unit for every bound on the peak, and refuses without it.
        actuator_limit(task)
    shown = {m.name for m in (*plant.num, *plant.den)} | {GAIN, DELAY}
    lines += [_line(m.name, m) for m in task.inputs if m.name not in shown]
    if bounds_actuator_peak(task) and all(m.name != REFERENCE_STEP for m in task.inputs):
        lines.append(_line(REFERENCE_STEP, DEFAULTS[REFERENCE_STEP], taken=True))
    lines += [
        "",
        "The plant these values make, as the answer is scored against it (s in 1/s):",
        f"G(s) = {GAIN} * N(s) / D(s) * exp(-{DELAY} * s)",
        f"N(s) = {_polynomial(plant.num)}",
        f"D(s) = {_polynomial(plant.den)}",
    ]
    return lines


def issued_text(task: Task) -> str:
    """What a session is given for ``task``: the same text on every call, for either arm.

    Raises:
        TaskFormatError: the task is a control task whose inputs the control scorer refuses.
    """
    if task.scorer.id == "control":
        values = _control_values(task)
    else:
        values = [_line(m.name, m) for m in task.inputs]
    parts = []
    if values:
        parts += [
            VALUES_HEADING,
            "",
            "Each value is written as name = value [unit].",
            "",
            *values,
            "",
        ]
    parts += [
        ANSWER_HEADING,
        "",
        f"The file `{task.answer.path}` in the directory you work in, in the form "
        f"`{task.answer.form}`.",
        "",
    ]
    gap = "\n" if task.brief.endswith("\n") else "\n\n"
    return task.brief + gap + "\n".join(parts)


def issued_bytes(task: Task) -> bytes:
    """:func:`issued_text` as the bytes a brief file holds."""
    return issued_text(task).encode("utf-8")


def issued_sha256(task: Task) -> str:
    """The digest a run given ``task`` records as its brief's: of the issued text's bytes."""
    return hashlib.sha256(issued_bytes(task)).hexdigest()


def brief_sha256(task: Task) -> str:
    """The digest of ``task``'s brief alone: the key a tier's maps and a round's order use."""
    return hashlib.sha256(task.brief.encode()).hexdigest()


def given_the_brief_alone(recorded: str, tasks: Iterable[Task]) -> bool:
    """Whether ``recorded``, a run's brief digest, is one of ``tasks``' briefs alone.

    Such a run was given a task's brief without its values, as runs were before every session
    was given :func:`issued_text`: it was given less than the task, and is never read as a
    run of it.
    """
    return any(recorded == brief_sha256(task) != issued_sha256(task) for task in tasks)


__all__ = [
    "ANSWER_HEADING",
    "TAKEN",
    "VALUES_HEADING",
    "brief_sha256",
    "given_the_brief_alone",
    "issued_bytes",
    "issued_sha256",
    "issued_text",
]
