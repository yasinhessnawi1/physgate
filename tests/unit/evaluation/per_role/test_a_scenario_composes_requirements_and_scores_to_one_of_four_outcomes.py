"""A scenario has an id, composes at least two requirements, and scores to one of four outcomes.

The tiers, the gaps and the isolation probe ask nothing else of a scenario, so any kind of
design can stand behind one. A fixture stands in here for a whole-design scenario; a control
task with its scorer is the per-role one (its rows run with the scorer, in the evaluation
environment).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


@dataclass(frozen=True)
class WholeDesign:
    """A stand-in for a scenario judged over a whole design: a fixed answer passes."""

    id: str
    requirements: tuple[str, ...]

    def score(self, answer: Path) -> str:
        if not answer.is_file():
            return "unscored"
        return "pass" if answer.read_text() == "meets every requirement" else "fail"


def test_the_four_outcomes_are_pass_fail_unscored_and_flaky() -> None:
    assert tuple(_api("physgate.evaluation.tiers.scenario.OUTCOMES")) == (
        "pass",
        "fail",
        "unscored",
        "flaky",
    )


def test_a_whole_design_stand_in_is_a_scenario(tmp_path: Path) -> None:
    scenario_type = _api("physgate.evaluation.tiers.scenario.Scenario")
    require_composing = _api("physgate.evaluation.tiers.scenario.require_composing")
    design = WholeDesign(id="lift.payload", requirements=("hold_the_load", "fit_the_frame"))
    assert isinstance(design, scenario_type)
    assert require_composing(design) is design
    answer = tmp_path / "answer.txt"
    assert design.score(answer) == "unscored"
    answer.write_text("meets every requirement")
    assert design.score(answer) == "pass"


@pytest.mark.parametrize(
    "requirements",
    [("hold_the_load",), ("hold_the_load", "hold_the_load"), ()],
    ids=["one", "one twice", "none"],
)
def test_a_scenario_that_composes_fewer_than_two_requirements_is_refused(
    requirements: tuple[str, ...],
) -> None:
    require_composing = _api("physgate.evaluation.tiers.scenario.require_composing")
    error = _api("physgate.evaluation.tiers.scenario.ScenarioError")
    with pytest.raises(error, match="composes at least 2"):
        require_composing(WholeDesign(id="lift.payload", requirements=requirements))


def test_what_lacks_a_scorer_is_no_scenario() -> None:
    @dataclass(frozen=True)
    class Unscored:
        id: str
        requirements: tuple[str, ...]

    scenario_type = _api("physgate.evaluation.tiers.scenario.Scenario")
    assert not isinstance(Unscored(id="x", requirements=("a", "b")), scenario_type)
