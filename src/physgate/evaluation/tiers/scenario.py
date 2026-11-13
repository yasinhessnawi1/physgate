"""What a scenario is to the tiers, whatever kind of design it judges.

A scenario has a stable id, names the requirements it composes, and scores an answer to one
of four outcomes. The tiers, the gaps and the isolation probe ask nothing else of it, so a
per-role task scored by its role's scorer and a whole design judged over the design-state
graph and its simulation are measured alike.

- ``pass`` and ``fail``: the answer was judged, and met every headline requirement or not;
- ``unscored``: the scenario could not judge the answer (its scorer refuses the scenario);
- ``flaky``: judged twice alike, it would not give the same outcome.

A scenario composes at least two requirements (ARCH-141): one that tests a requirement alone
shows no gap when an implementer has isolated that one feature, so it is refused
(:func:`require_composing`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, get_args, runtime_checkable

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.task import COMPOSES_AT_LEAST

Outcome = Literal["pass", "fail", "unscored", "flaky"]
#: Every outcome a scenario's score may be.
OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)


class ScenarioError(PerRoleError):
    """A scenario is not one the tiers can measure."""


@runtime_checkable
class Scenario(Protocol):
    """One scenario of a tier: its id, the requirements it composes, and its scorer."""

    @property
    def id(self) -> str:
        """The scenario's stable id."""
        ...

    @property
    def requirements(self) -> tuple[str, ...]:
        """The requirements the scenario composes, each once."""
        ...

    def score(self, answer: Path) -> Outcome:
        """The outcome of the answer at ``answer``."""
        ...


def require_composing(scenario: Scenario) -> Scenario:
    """``scenario``, refused unless it composes at least two distinct requirements.

    Raises:
        ScenarioError: it composes fewer.
    """
    if len(set(scenario.requirements)) < COMPOSES_AT_LEAST:
        msg = (
            f"the scenario {scenario.id!r} composes {len(set(scenario.requirements))} "
            f"requirement(s); a scenario composes at least {COMPOSES_AT_LEAST}"
        )
        raise ScenarioError(msg, scenario=scenario.id)
    return scenario
