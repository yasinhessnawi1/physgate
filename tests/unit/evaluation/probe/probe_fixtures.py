"""Stand-ins for the probe's rows: a store of one version, and answers that need no scorer.

The store is the baseline round's stand-in (twenty-four fixture tasks split into one version, eight
of them held out). Each stand-in task composes two requirements. The fixture method makes each
task a scenario whose answer file lists the requirements it meets, and builds, for a requirement,
an answer that meets that requirement alone. What decides a scenario's pass is the row's choice:
every requirement (a tier that composes), or the first one only (a tier whose scenarios each turn
on one requirement, though they declare two).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXPOSURE_TESTS = Path(__file__).resolve().parents[1] / "exposure"
if str(EXPOSURE_TESTS) not in sys.path:
    sys.path.insert(0, str(EXPOSURE_TESTS))

from exposure_fixtures import StandInStore, api, stand_in_store  # noqa: E402

from physgate.evaluation.tiers.task import Task  # noqa: E402

__all__ = ["FixtureMethod", "StandInStore", "api", "requirements_of", "stand_in_store"]

#: What decides a fixture scenario's pass, given its requirements.
DECIDES: dict[str, Callable[[tuple[str, ...]], frozenset[str]]] = {
    "every": frozenset,
    "first": lambda requirements: frozenset(requirements[:1]),
}


def requirements_of(task: Task) -> tuple[str, ...]:
    """The requirements ``task``'s headline specifications compose, sorted, each once."""
    return tuple(
        sorted({r for spec in task.specs if spec.counts == "headline" for r in spec.composes})
    )


@dataclass(frozen=True)
class FixtureScenario:
    """A task as a scenario whose answer is the list of requirements it meets."""

    task: Task
    decides: str
    outcome: str | None = None
    #: The requirements this scenario says it composes; its task's when ``None``.
    declared: tuple[str, ...] | None = None
    #: ``"score"``: scoring raises an error naming the task's id.
    raising: str | None = None

    @property
    def id(self) -> str:
        return self.task.id

    @property
    def requirements(self) -> tuple[str, ...]:
        return requirements_of(self.task) if self.declared is None else self.declared

    def score(self, answer: Path) -> Any:  # noqa: ANN401
        if self.raising == "score":
            msg = f"the task {self.task.id} cannot be scored"
            raise ValueError(msg)
        if self.outcome is not None:
            return self.outcome
        met = frozenset(json.loads(answer.read_text())["meets"])
        return "pass" if DECIDES[self.decides](self.requirements) <= met else "fail"


@dataclass(frozen=True)
class FixtureMethod:
    """The probe's way of answering for the stand-in tasks, with no scorer and no search.

    ``decides``: which requirements decide each scenario's pass. ``missing``: the requirements
    (by their place in a task's sorted list) for which no answer is found. ``outcome``: what every
    score says instead of judging. ``declared``: the requirements every scenario says it composes.
    ``judges``: the one scorer whose tasks it makes scenarios of; a task of another is refused
    with its id in the words, as the control role's scenario refuses one. ``raising``: where an
    error naming the task's id is raised, ``"answer"`` (after the answer is written) or
    ``"score"``.
    """

    decides: str = "every"
    missing: Sequence[int] = ()
    outcome: str | None = None
    declared: tuple[str, ...] | None = None
    role: str = "control"
    judges: str | None = None
    raising: str | None = None
    #: Every answer built, by the requirement it was built for: what the rows look at.
    built: list[Path] = field(default_factory=list)

    def describe(self) -> dict[str, Any]:
        return {"answers": "fixture"}

    def probed(self, task: Task, seed: int) -> Any:  # noqa: ANN401
        if self.judges is not None and task.scorer.id != self.judges:
            error = api("physgate.evaluation.tiers.scenario.ScenarioError")
            raise error(f"the task {task.id!r} is not judged here", task=task.id)
        scenario = FixtureScenario(task, self.decides, self.outcome, self.declared, self.raising)
        requirements = scenario.requirements

        def answer_for(requirement: str, into: Path) -> Path | None:
            if requirements.index(requirement) in self.missing:
                return None
            path = into / "answer.json"
            path.write_text(json.dumps({"meets": [requirement], "seed": seed}))
            self.built.append(path)
            if self.raising == "answer":
                raise OSError(5, f"the answer for {task.id} cannot be written", str(path))
            return path

        probed = api("physgate.evaluation.tiers.probe.Probed")
        return probed(scenario=scenario, answer_for=answer_for)
