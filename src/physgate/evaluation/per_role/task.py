"""One task for one design role: what both arms read, and what their answer is held to.

A task lives in a directory holding ``task.json`` and, beside it, ``references/``: one
known-good answer and one or more known-bad answers, each bad one naming the single
specification it is built to fail. Before any arm runs, every task's scorer must pass its
good answer and fail each bad one on exactly the specification that answer names, which
is how a wrong scorer is found before it produces a number (a published benchmark's own
scorer was found wrong this way).

Every number a task carries is a ``{value, unit}`` pair. A bare number is a schema error,
and so is NaN, infinity, an empty unit or a unit that is not a product of named units with
small powers. Validation is strict rather than coercing, for the same reason as the
design-state graph's: a coercing model takes the string ``"2.4"`` and ``True`` as numbers.

Two tasks that validate equal serialise to the same bytes (:func:`canonical_json`), which
is what lets a task suite be hashed and the hash be committed in place of the suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.evaluation.per_role.base import Identifier, Measure, NamedMeasure, _Frozen
from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.firmware.spec import FirmwareSpec

#: The largest ``task.json`` read. A task is a brief and a few dozen numbers; anything
#: larger is not one, and it is refused before it is parsed.
MAX_TASK_BYTES = 256 * 1024

TaskId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=96)]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
#: A canary: an opaque token that reveals nothing about its task. Found in any session's
#: stream, it proves that session read the task.
Canary = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

Role = Literal["control", "firmware"]
Tier = Literal["visible", "held_out", "external"]
Comparison = Literal[">=", "<=", ">", "<", "in"]
#: Whether a specification decides the task's pass, or is reported beside it only.
Counts = Literal["headline", "secondary"]
#: The forms an answer takes. Each has its own schema in :mod:`.answer`.
AnswerForm = Literal["lti_tf", "espidf_project"]
ScorerId = Literal["control", "firmware"]


class Spec(_Frozen):
    """One numeric acceptance specification: a metric the scorer computes, and its bound.

    ``in`` takes a closed interval, two measures in one unit with the lower first; every
    other comparison takes one measure. ``composes`` names the requirements this
    specification serves, so that a task can be shown to compose requirements rather than
    test one alone.
    """

    name: Identifier
    metric: Identifier
    op: Comparison
    bound: Measure | tuple[Measure, Measure]
    counts: Counts = "headline"
    composes: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bound_fits_op(self) -> Spec:
        if self.op == "in":
            if not isinstance(self.bound, tuple):
                msg = f"the spec {self.name!r} compares 'in' an interval, so its bound is two"
                raise ValueError(msg)
            low, high = self.bound
            if low.unit != high.unit:
                msg = f"the spec {self.name!r} gives its interval in two units"
                raise ValueError(msg)
            if low.value > high.value:
                msg = f"the spec {self.name!r} gives its interval's upper end first"
                raise ValueError(msg)
        elif isinstance(self.bound, tuple):
            msg = f"the spec {self.name!r} compares {self.op!r}, so its bound is one measure"
            raise ValueError(msg)
        return self


class OwnSource(_Frozen):
    """A task written for this evaluation."""

    kind: Literal["own"] = "own"


class ExternalSource(_Frozen):
    """A task taken from a published benchmark: where, at which commit, from which bytes."""

    kind: Literal["external"] = "external"
    benchmark: Identifier
    file: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./-]+$", max_length=200)]
    index: int = Field(ge=0)
    upstream_sha: GitSha
    upstream_sha256: Sha256


class AnswerContract(_Frozen):
    """Where an arm puts its answer, relative to the directory it works in, and its form.

    The path is part of the brief, so both arms are told the same place.
    """

    path: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$", max_length=64)
    ]
    form: AnswerForm


class ScorerRef(_Frozen):
    """Which scorer judges the task, at which version, with every parameter a measure."""

    id: ScorerId
    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    params: tuple[NamedMeasure, ...] = ()


class Task(_Frozen):
    """One task: the brief both arms read, the inputs it gives, and the specifications.

    An own task composes at least two requirements across its headline specifications
    (ARCH-141: feature isolation alone produces a gap without tampering). A held-out task
    carries a canary. A published benchmark's task is taken as its benchmark set it, so
    neither rule binds it.
    """

    id: TaskId
    role: Role
    tier: Tier
    source: OwnSource | ExternalSource = Field(discriminator="kind")
    brief: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    inputs: tuple[NamedMeasure, ...] = ()
    answer: AnswerContract
    specs: tuple[Spec, ...] = Field(min_length=1)
    scorer: ScorerRef
    canary: Canary | None = None
    #: A firmware task's closed loop: its line protocol, scenarios and probes.
    firmware: FirmwareSpec | None = None

    @model_validator(mode="after")
    def _holds_its_tier_s_rules(self) -> Task:
        names = [spec.name for spec in self.specs]
        if len(set(names)) != len(names):
            msg = f"the task {self.id!r} names a spec twice"
            raise ValueError(msg)
        if not any(spec.counts == "headline" for spec in self.specs):
            msg = f"the task {self.id!r} has no headline spec, so nothing decides its pass"
            raise ValueError(msg)
        external = isinstance(self.source, ExternalSource)
        if external != (self.tier == "external"):
            msg = f"the task {self.id!r} is external exactly when it comes from a benchmark"
            raise ValueError(msg)
        if not external:
            served = {
                req for spec in self.specs if spec.counts == "headline" for req in spec.composes
            }
            if len(served) < 2:
                msg = (
                    f"the task {self.id!r} tests one requirement alone; an own task composes "
                    "at least two"
                )
                raise ValueError(msg)
        if self.tier == "held_out" and self.canary is None:
            msg = f"the held-out task {self.id!r} carries no canary"
            raise ValueError(msg)
        return self


def canonical_json(payload: Any) -> bytes:
    """``payload`` as bytes that are the same whenever the payload is.

    Keys are sorted, separators fixed, floats written by ``repr`` (the shortest string
    that reads back to the same float) and NaN refused, so a task or a score serialises
    identically on every call and can be hashed.
    """
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode("utf-8")


def task_bytes(task: Task) -> bytes:
    """The canonical bytes of ``task``: what its hash is taken over."""
    return canonical_json(task.model_dump(mode="json"))


def parse_task(raw: bytes, *, where: str = "task.json") -> Task:
    """``raw`` validated whole as a task, or refused with the reason.

    Raises:
        TaskFormatError: it is too large, not JSON, or not a task.
    """
    if len(raw) > MAX_TASK_BYTES:
        msg = f"{where} is larger than any task ({len(raw)} bytes)"
        raise TaskFormatError(msg, where=where)
    try:
        return Task.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"{where} is not a task: {exc.errors()[0]['msg']}"
        raise TaskFormatError(msg, where=where) from exc


#: A reference directory's name: ``good``, or ``bad_<what it gets wrong>``.
REFERENCE_NAME = re.compile(r"^(good|bad_[a-z0-9_]+)$")


class Reference(_Frozen):
    """One reference answer: good, or bad and naming the one spec it is built to fail."""

    name: Annotated[str, StringConstraints(pattern=REFERENCE_NAME.pattern)]
    fails: Identifier | None
    answer_path: str


class LoadedTask(_Frozen):
    """A task with its references, as read from its directory."""

    task: Task
    references: tuple[Reference, ...]


class _Expectation(_Frozen):
    fails: Identifier


def load_task(directory: Path) -> LoadedTask:
    """The task in ``directory``, with its references, refused unless complete.

    The directory holds ``task.json`` and ``references/``: exactly one ``good`` and at
    least one ``bad_*``, each holding the answer at the task's answer path. Each bad
    reference also holds ``expect.json``, naming the one headline spec it is built to fail.

    Raises:
        TaskFormatError: anything is missing, extra, or does not validate.
    """
    task = parse_task((directory / "task.json").read_bytes(), where=str(directory))
    refs_dir = directory / "references"
    if not refs_dir.is_dir():
        msg = f"the task {task.id!r} has no references"
        raise TaskFormatError(msg, task=task.id)
    headline = {spec.name for spec in task.specs if spec.counts == "headline"}
    references: list[Reference] = []
    for entry in sorted(refs_dir.iterdir()):
        if not entry.is_dir() or entry.is_symlink() or not REFERENCE_NAME.fullmatch(entry.name):
            msg = f"the task {task.id!r} holds {entry.name!r}, which is not a reference"
            raise TaskFormatError(msg, task=task.id)
        answer = entry / task.answer.path
        if not answer.is_file() or answer.is_symlink():
            msg = f"the reference {entry.name!r} of {task.id!r} holds no answer"
            raise TaskFormatError(msg, task=task.id)
        fails: str | None = None
        if entry.name != "good":
            try:
                fails = _Expectation.model_validate_json((entry / "expect.json").read_bytes()).fails
            except (OSError, ValidationError) as exc:
                msg = f"the bad reference {entry.name!r} of {task.id!r} names no spec it fails"
                raise TaskFormatError(msg, task=task.id) from exc
            if fails not in headline:
                msg = f"the bad reference {entry.name!r} names {fails!r}, not a headline spec"
                raise TaskFormatError(msg, task=task.id)
        references.append(Reference(name=entry.name, fails=fails, answer_path=str(answer)))
    goods = [ref for ref in references if ref.fails is None]
    if len(goods) != 1 or len(references) < 2:
        msg = f"the task {task.id!r} needs one good reference and at least one bad"
        raise TaskFormatError(msg, task=task.id)
    return LoadedTask(task=task, references=tuple(references))
