"""Conditions a run must meet before it starts, registered by whoever needs them.

The core states its own condition about the OS layer beside the run's configuration rather
than here (``run_config.os_layer_refusal``): a run runs only inside the layer unless its
parameters allow the layer's absence, for development, and a run that acts on queue decisions
never runs without it (ARCH-091, ARCH-133).
A party that needs more (the evaluation, whose numbers are reported) registers a
requirement here from the command's composition root, and the core asks every registered
requirement before a run spends anything: at decomposition, and again at every run and
resume. Removing that party removes its requirement and touches nothing here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from physgate.orchestrator.run_config import RunConfig
from physgate.oslayer.probe import Absent, Present


@dataclass(frozen=True)
class RunFacts:
    """What a requirement is shown about the run it judges."""

    config: RunConfig
    #: The OS layer's state where the run's sessions will run.
    os_layer: Present | Absent
    #: Whether the run's sessions run shell commands: every orchestrated run's role
    #: sessions do; a run of reviewers alone does not.
    shell_sessions: bool
    #: Whether the run is being started, at decomposition, rather than driven or resumed: a
    #: requirement on how a run is configured is asked of a new run, and a run recorded before
    #: the requirement existed is not refused on resume for not meeting it.
    new_run: bool = False


#: A requirement: ``None`` if the run may start, else why it may not.
RunRequirement = Callable[[RunFacts], str | None]

_registered: tuple[RunRequirement, ...] = ()


def register(requirements: Iterable[RunRequirement]) -> None:
    """Set the requirements every run is held to (replacing any set before)."""
    global _registered  # noqa: PLW0603 - the one place the command's root sets them
    _registered = tuple(requirements)


def registered() -> tuple[RunRequirement, ...]:
    """The requirements every run is held to now."""
    return _registered


def refusals(facts: RunFacts) -> list[str]:
    """Why the run may not start, one reason per requirement that refuses it."""
    return [why for requirement in _registered if (why := requirement(facts)) is not None]
