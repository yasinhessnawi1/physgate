"""The isolation probe's answers for control tasks: the seeded search, aimed at one requirement.

For one requirement of a task, its specifications are the task's headline specifications that
serve it (those whose ``composes`` names it; a specification serving two requirements is a
specification of each). The answer built for it is the first controller the reference search
finds that meets those specifications alone (:func:`.synthesise.search` given ``specs``), seeded,
with no time budget, so the same task and seed always give the same answer; where the search
finds none, there is no answer. Its scenario is the task scored by the control scorer
(:class:`.scenario.TaskScenario`), on every headline specification, as any answer is scored.

Runs in the evaluation environment, since it runs the search and the scorer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from physgate.evaluation.per_role import synthesise
from physgate.evaluation.per_role.exceptions import SynthesisError
from physgate.evaluation.per_role.scenario import TaskScenario
from physgate.evaluation.per_role.scorers import control as scorer
from physgate.evaluation.tiers.probe import Probed
from physgate.evaluation.tiers.task import Task, canonical_json


def requirement_specs(task: Task, requirement: str) -> frozenset[str]:
    """The names of ``task``'s headline specifications that serve ``requirement``."""
    return frozenset(
        spec.name
        for spec in task.specs
        if spec.counts == "headline" and requirement in spec.composes
    )


@dataclass(frozen=True)
class ControlSearch:
    """The control role's answers for one requirement alone, by the seeded reference search."""

    role: str = "control"

    def describe(self) -> dict[str, Any]:
        """The search, and its fixed parameters, as the probe's result records them."""
        return {
            "answers": "seeded_search_on_one_requirement_s_specs",
            "families": ["pid_filtered_derivative", "pid_lead"],
            "generations": synthesise.GENERATIONS,
            "population": synthesise.POPULATION,
            # The search and the scorer give the same answer and score only on the same
            # numerical libraries, so the result names them.
            "libraries": scorer.library_versions(),
        }

    def probed(self, task: Task, seed: int) -> Probed:
        """``task`` scored by its scorer, with an answer for each requirement found by ``seed``."""
        scenario = TaskScenario(task)

        def answer_for(requirement: str, into: Path) -> Path | None:
            try:
                answer = synthesise.search(
                    task, seed=seed, specs=requirement_specs(task, requirement)
                )
            except SynthesisError:
                return None
            path = into / task.answer.path
            path.write_bytes(canonical_json(answer.model_dump(mode="json")))
            return path

        return Probed(scenario=scenario, answer_for=answer_for)
