"""A harness trial is given what a session is given for its task: the raw arm's bytes.

Each trial's brief file holds :func:`.tiers.issued.issued_text` of its task (its brief, its
values as its scorer reads them, where its answer goes), the same bytes the raw arm's prompt is;
the planner is given those bytes. A run in a trial's directory that was given a task's brief
alone is refused by a name of its own, and a version holding a task whose values its scorer
cannot read is refused before any trial starts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.harness_round import RoundError, run_round
from physgate.evaluation.tiers.issued import issued_bytes
from physgate.orchestrator.run_config import RunConfig


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: Any, **changes: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    inputs = rig.inputs(**{"trials": 1, "tasks": 2, **changes})
    return run_round(inputs, driver=driver, scorer=_score, sleep=lambda _: None)


def test_each_trial_and_its_planner_are_given_the_issued_text_of_its_task(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    status, _ = _round(rig, driver)
    assert status == "done"
    given = [call.brief.read_bytes() for call in driver.decomposed]
    issued = {issued_bytes(t) for t in rig.made.tasks["visible"]}
    assert len(given) == 2 and set(given) <= issued
    for data in given:
        task = next(t for t in rig.made.tasks["visible"] if issued_bytes(t) == data)
        # The brief alone is the text's beginning, and never all of it.
        assert data.startswith(task.brief.encode()) and data != task.brief.encode()


def test_a_run_given_its_task_s_brief_alone_is_refused_by_its_own_name(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    made = driver.config_of

    def alone(call: Any) -> RunConfig:  # noqa: ANN401
        # The run records the digest of its task's brief alone, as a run made before did.
        text = call.brief.read_text()
        task = next(t for t in rig.made.tasks["visible"] if text.startswith(t.brief))
        digest = hashlib.sha256(task.brief.encode()).hexdigest()
        return made(call).model_copy(update={"brief_sha256": digest})

    driver.config_of = alone  # type: ignore[method-assign]
    with pytest.raises(RoundError) as refused:
        _round(rig, driver)
    assert refused.value.context["refused_because"] == "given_the_brief_alone"


def test_a_version_holding_a_task_its_scorer_cannot_read_is_refused_before_any_trial(
    tmp_path: Path,
) -> None:
    gain_alone = [{"name": "plant_gain", "value": 2.0, "unit": "1"}]
    rig = make_rig(tmp_path, store={"changes": {"inputs": gain_alone}})
    driver = rig.driver()
    with pytest.raises(RoundError) as refused:
        _round(rig, driver)
    assert refused.value.context["refused_because"] == "task_not_issuable"
    assert driver.decomposed == [] and list(rig.run_root.iterdir()) == []
