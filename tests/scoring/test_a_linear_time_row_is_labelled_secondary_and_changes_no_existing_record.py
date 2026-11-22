"""A linear time row says what it is, counts for nothing, and is unscored where it cannot run.

The two metrics are the linear model's answer. A task may name them only as secondary specs; each
row carries its label, its timeline and the count of updates at the command limit; a law that reads
no speed reference, or a run past the work bound, leaves the rows unscored without failing the
answer; and a task that names neither metric gets the record it always got, with no new key.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.tiers.scenario import ScenarioError
from physgate.evaluation.whole import dynamic
from physgate.evaluation.whole.scenario import METRICS, WholeDesignScenario, WholeDesignTask

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")

_PLANT = (
    Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0.json"
).read_bytes()

HEADLINE: dict[str, Any] = {
    "name": "rate",
    "metric": "update_rate",
    "op": "in",
    "composes": ["c9"],
    "bound": [helpers._m(99, "Hz"), helpers._m(101, "Hz")],
}


def _linear(metric: str, bound: float, unit: str, op: str, counts: str = "secondary") -> Any:
    return {
        "name": metric,
        "metric": metric,
        "op": op,
        "composes": ["c17"],
        "counts": counts,
        "bound": helpers._m(bound, unit),
    }


SPEED = _linear(dynamic.STEADY_SPEED, 1.2, "m/s", ">=")
PUSH = _linear(dynamic.PUSH_PEAK_TILT, 70, "deg", "<=")


def _scenario(tmp_path: Path, specs: list[dict[str, Any]]) -> tuple[WholeDesignScenario, Path]:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    task = WholeDesignTask.model_validate_json(
        json.dumps({"id": "whole.fixture", "requirements": ["c5", "c15"], "specs": specs})
    )
    return WholeDesignScenario(task, _PLANT, root=root), root


def _record(tmp_path: Path, specs: list[dict[str, Any]], controller: dict[str, Any]) -> Any:
    scenario, root = _scenario(tmp_path, specs)
    path = root / "answer.json"
    path.write_bytes(helpers._answer(controller, 3))
    return scenario.record(path)


def _rows(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in record["specs"]}


def test_the_metrics_are_of_the_linear_kind_in_their_units() -> None:
    assert METRICS[dynamic.STEADY_SPEED] == ("m/s", "dynamic_linear")
    assert METRICS[dynamic.PUSH_PEAK_TILT] == ("deg", "dynamic_linear")
    assert METRICS["balanced_speed"][1] == "dynamic"
    assert METRICS["push_recovery_tilt"][1] == "dynamic"


@pytest.mark.parametrize("metric", [SPEED, PUSH])
def test_a_task_that_counts_a_linear_metric_in_its_headline_is_refused(
    tmp_path: Path, metric: dict[str, Any]
) -> None:
    headline = copy.deepcopy(metric)
    headline["counts"] = "headline"
    with pytest.raises(ScenarioError, match="secondary"):
        _scenario(tmp_path, [HEADLINE, headline])


def test_a_linear_row_is_labelled_and_the_record_carries_its_timeline(tmp_path: Path) -> None:
    record = _record(tmp_path, [HEADLINE, SPEED, PUSH], helpers._recorded_controller())
    rows = _rows(record)
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        row = rows[name]
        assert row["kind"] == "dynamic_linear"
        assert row["counts"] == "secondary"
        assert row["label"] == dynamic.LABEL
        assert "not criterion 17's or 18's verdict" in row["label"]
        assert "criterion" in row["reason"]
        assert row["corners"]["count"] == 1024
        assert "limit_reached" in row["linear_run"]
    block = record["dynamic_linear"]
    assert block["label"] == dynamic.LABEL
    assert "proposal" in block["status"]
    assert block["timeline"]["push_time"] == {"value": dynamic.PUSH_TIME, "unit": "s"}
    assert block["not_modelled"] == list(dynamic.NOT_MODELLED)
    assert block["realised"]["sensor_delay"]["unit"] == "s"
    speed_info = rows[dynamic.STEADY_SPEED]["linear_run"]
    assert set(speed_info["window_means_at_nominal"]) == {"5", "10", "15", "20"}
    assert "second half less its first half" in speed_info["settled"]["meaning"]
    branches = rows[dynamic.PUSH_PEAK_TILT]["linear_run"]["branches_at_nominal"]
    assert [b["push_band"] for b in branches] == list(dynamic.PUSH_BAND)
    assert rows[dynamic.PUSH_PEAK_TILT]["measured"]["value"] == max(
        b["peak"]["value"] for b in branches
    )


def test_the_linear_rows_never_decide_the_outcome(tmp_path: Path) -> None:
    impossible = [_linear(dynamic.STEADY_SPEED, 1e6, "m/s", ">="), PUSH]
    record = _record(tmp_path, [HEADLINE, *impossible], helpers._recorded_controller())
    rows = _rows(record)
    assert rows[dynamic.STEADY_SPEED]["verdict"] == "fail"
    assert rows["rate"]["verdict"] == "pass"
    assert record["outcome"] == "pass"


def test_a_law_that_reads_no_speed_reference_leaves_both_rows_unscored(tmp_path: Path) -> None:
    law = helpers._stable_law(0.04)
    record = _record(tmp_path, [HEADLINE, SPEED, PUSH], law)
    rows = _rows(record)
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        assert rows[name]["verdict"] == "unscored"
        assert "no speed input" in rows[name]["reason"]
        assert rows[name]["measured"] is None
    assert record["outcome"] == "pass"
    assert "not_run" in record["dynamic_linear"]


def test_a_run_past_the_work_bound_is_unscored_and_never_fails_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dynamic, "MAX_DYNAMIC_WORK", 1000)
    record = _record(tmp_path, [HEADLINE, SPEED, PUSH], helpers._recorded_controller())
    rows = _rows(record)
    assert rows[dynamic.STEADY_SPEED]["verdict"] == "unscored"
    assert "past the bound" in rows[dynamic.STEADY_SPEED]["reason"]
    assert record["outcome"] == "pass"
    assert "refusal" not in record


def test_a_version_2_named_structure_gets_the_same_rows(tmp_path: Path) -> None:
    scenario, root = _scenario(tmp_path, [HEADLINE, SPEED, PUSH])
    path = root / "named.json"
    path.write_bytes(helpers._answer(helpers._incremental(0.999), 2))
    record = scenario.record(path)
    rows = _rows(record)
    assert rows[dynamic.STEADY_SPEED]["kind"] == "dynamic_linear"
    assert rows[dynamic.STEADY_SPEED]["corners"]["count"] == 1024
    assert record["dynamic_linear"]["points"] == 1025


def test_a_task_naming_neither_metric_gets_no_new_key_anywhere(tmp_path: Path) -> None:
    pm = {
        "name": "pm",
        "metric": "phase_margin",
        "op": ">=",
        "composes": ["c15"],
        "bound": helpers._m(30, "deg"),
    }
    record = _record(tmp_path, [HEADLINE, pm], helpers._recorded_controller())
    assert "dynamic_linear" not in record
    for row in record["specs"]:
        assert "label" not in row
        assert "linear_run" not in row
        assert row["kind"] != "dynamic_linear"
    assert set(record["work"]) == {"corners", "steps", "states", "total", "bound"}
