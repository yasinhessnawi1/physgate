"""A per-role task as a scenario: the task, scored by its role's scorer.

The control scorer judges an answer file, so a control task is a scenario as it stands: its
id is the task's, its requirements are those its headline specifications compose, and its
outcome is the scorer's pass. An answer that is not a controller scores as a fail, as the
scorer has it; a task the scorer refuses to judge is ``unscored``, never a fail. The firmware
scorer judges the traces of a closed loop rather than a file, so a firmware task is not a
scenario of this kind. Runs in the evaluation environment, since it runs the scorer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.scorers.control import score
from physgate.evaluation.tiers.scenario import Outcome, ScenarioError
from physgate.evaluation.tiers.task import Task


@dataclass(frozen=True)
class TaskScenario:
    """A control task with its scorer, as a :class:`.tiers.scenario.Scenario`."""

    task: Task

    def __post_init__(self) -> None:
        """Refuse a task whose scorer does not judge an answer file."""
        if self.task.scorer.id != "control":
            msg = f"the task {self.task.id!r} is scored on traces, not an answer file"
            raise ScenarioError(msg, task=self.task.id)

    @property
    def id(self) -> str:
        """The task's id."""
        return self.task.id

    @property
    def requirements(self) -> tuple[str, ...]:
        """The requirements the task's headline specifications compose, sorted, each once."""
        return tuple(
            sorted(
                {
                    requirement
                    for spec in self.task.specs
                    if spec.counts == "headline"
                    for requirement in spec.composes
                }
            )
        )

    def score(self, answer: Path) -> Outcome:
        """``pass`` or ``fail`` as the scorer judges ``answer``; ``unscored`` if it cannot."""
        try:
            record = score(self.task, answer)
        except PerRoleError:
            return "unscored"
        return "pass" if record["passed"] else "fail"
