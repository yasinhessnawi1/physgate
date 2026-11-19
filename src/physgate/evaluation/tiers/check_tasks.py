"""What the blind check is given and what its answer is: the tasks file and the answer file.

The check is given a version's held-out tasks in one file, ``tasks.json``, each under the digest
of its id and holding its brief, inputs, answer contract and specifications, never its
references or canary (:func:`bundle`). It answers in ``answers.json``: three booleans for each
key, and nothing else (:func:`answers_of`). The check's session runner
(:mod:`physgate.evaluation.per_role.author_session`) and the import of an earlier check's kept
session (:func:`.checks.import_check`) both read them here, so the two hold one shape. Nothing
here needs the scorer's libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from physgate.evaluation.tiers.task import id_digest, load_task

QUESTIONS = ("states_every_requirement", "unambiguous", "answerable_as_asked")


class Answer(BaseModel):
    """One task's three answers."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    states_every_requirement: bool
    unambiguous: bool
    answerable_as_asked: bool


class _Answers(RootModel[dict[str, Answer]]):
    model_config = ConfigDict(strict=True)


#: The largest answer file read: three booleans for each of a few dozen tasks.
MAX_ANSWERS_BYTES = 64 * 1024


def bundle(tier: Path) -> dict[str, dict[str, Any]]:
    """The tier's tasks as the check reads them: by id digest, without references or canary.

    Raises:
        PerRoleError: a task in the tier does not load.
    """
    found: dict[str, dict[str, Any]] = {}
    for entry in sorted(p for p in tier.iterdir() if p.is_dir()):
        task = load_task(entry).task
        found[id_digest(task.id)] = {
            "brief": task.brief,
            "inputs": [m.model_dump(mode="json") for m in task.inputs],
            "answer": task.answer.model_dump(mode="json"),
            "specs": [s.model_dump(mode="json") for s in task.specs],
        }
    return found


def answers_of(data: bytes) -> dict[str, dict[str, bool]] | None:
    """An answer file's three booleans for each key, or ``None`` unless that is all it holds."""
    if len(data) > MAX_ANSWERS_BYTES:
        return None
    try:
        answers = _Answers.model_validate_json(data).root
    except ValidationError:
        return None
    return {key: answer.model_dump() for key, answer in answers.items()}


__all__ = ["MAX_ANSWERS_BYTES", "QUESTIONS", "Answer", "answers_of", "bundle"]
