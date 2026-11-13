"""A control task with its scorer is a scenario.

Its id is the task's, its requirements are those its headline specifications compose, and its
outcome is the scorer's pass. An answer that is not a controller is a fail, as the scorer has
it; a task the scorer will not judge is unscored, never a fail.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from control_fixtures import GOOD_PID, control_task, controller, write_answer

from physgate.evaluation.tiers.task import parse_task


def _api(name: str) -> Any:
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def _scenario(**changes: Any) -> Any:
    task = json.loads(control_task().model_dump_json())
    task.update(changes)
    return _api("physgate.evaluation.per_role.scenario.TaskScenario")(
        parse_task(json.dumps(task).encode())
    )


def test_a_control_task_is_a_scenario_with_its_id_and_its_headline_requirements() -> None:
    scenario = _scenario()
    assert isinstance(scenario, _api("physgate.evaluation.tiers.scenario.Scenario"))
    assert scenario.id == "control.test_plant"
    assert scenario.requirements == ("hold_the_plant", "respond_in_time", "tolerate_model_error")
    assert _api("physgate.evaluation.tiers.scenario.require_composing")(scenario) is scenario


def test_a_secondary_specification_s_requirement_is_not_one_the_scenario_composes() -> None:
    task = json.loads(control_task().model_dump_json())
    task["specs"].append(
        {
            "name": "quiet",
            "metric": "overshoot",
            "op": "<=",
            "bound": {"value": 50, "unit": "percent"},
            "counts": "secondary",
            "composes": ["stay_quiet"],
        }
    )
    scenario = _scenario(specs=task["specs"])
    assert "stay_quiet" not in scenario.requirements


def test_the_good_controller_passes_and_an_unstable_one_fails(tmp_path: Path) -> None:
    scenario = _scenario()
    assert scenario.score(write_answer(tmp_path / "good", GOOD_PID)) == "pass"
    unstable = controller([1.0], [1.0], gain=0.1)
    assert scenario.score(write_answer(tmp_path / "bad", unstable)) == "fail"


def test_an_answer_that_is_not_a_controller_fails_and_is_never_unscored(tmp_path: Path) -> None:
    scenario = _scenario()
    (tmp_path / "answer.json").write_text("not a controller")
    assert scenario.score(tmp_path / "answer.json") == "fail"


def test_a_task_the_scorer_will_not_judge_is_unscored_never_a_fail(tmp_path: Path) -> None:
    scenario = _scenario(scorer={"id": "control", "version": "9.9.9"})
    assert scenario.score(write_answer(tmp_path, GOOD_PID)) == "unscored"


def test_a_task_scored_on_traces_is_not_this_kind_of_scenario() -> None:
    error = _api("physgate.evaluation.tiers.scenario.ScenarioError")
    with pytest.raises(error, match="traces"):
        _scenario(scorer={"id": "firmware", "version": "1.0.0"})
