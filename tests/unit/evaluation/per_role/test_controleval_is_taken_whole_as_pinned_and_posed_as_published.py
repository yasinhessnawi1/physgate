from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.per_role import controleval
from physgate.evaluation.per_role.exceptions import ControlEvalError
from physgate.evaluation.per_role.task import parse_task, task_bytes


def _record(i: int, **changes: Any) -> dict[str, Any]:
    """A made-up record in the upstream shape (our numbers, not the benchmark's)."""
    record: dict[str, Any] = {
        "id": i,
        "num": [2.5, 1.0 + i],
        "den": [1, -0.5, 3.0 + i],
        "gain_margin_min": 6.25,
        "phase_margin_min": 47.5,
        "settling_time_min": 0.125,
        "settling_time_max": 4.75,
        "overshoot_max": 13.375,
        "steadystate_error_max": 0.0001,
        "metadata": "made up",
        "scenario": "other",
    }
    record.update(changes)
    return record


def _file(tmp_path: Path, records: list[dict[str, Any]]) -> tuple[Path, str]:
    path = tmp_path / "category.json"
    raw = json.dumps(records).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _tasks(tmp_path: Path, records: list[dict[str, Any]]) -> list[Any]:
    path, digest = _file(tmp_path, records)
    return controleval.category_tasks("second_order_unstable", path, pinned=digest)


def test_a_whole_category_becomes_fifty_external_tasks_in_order(tmp_path: Path) -> None:
    tasks = _tasks(tmp_path, [_record(i) for i in range(50)])
    assert [t.id for t in tasks][:2] == [
        "controleval.second_order_unstable.000",
        "controleval.second_order_unstable.001",
    ]
    assert len(tasks) == 50
    assert {t.tier for t in tasks} == {"external"}
    assert tasks[7].source.index == 7


@pytest.mark.parametrize(
    "records",
    [
        [_record(i) for i in range(49)],
        [_record(i) for i in range(51)],
        [_record(i) for i in (1, 0, *range(2, 50))],
    ],
    ids=["49 tasks", "51 tasks", "out of order"],
)
def test_a_category_that_is_not_whole_is_refused(
    tmp_path: Path, records: list[dict[str, Any]]
) -> None:
    with pytest.raises(ControlEvalError, match="whole category"):
        _tasks(tmp_path, records)


@pytest.mark.parametrize(
    "change",
    [{"phase_margin_min": "47.5"}, {"num": []}, {"solution": [1, 2]}, {"tau": -0.1}],
    ids=["string number", "empty numerator", "unknown field", "negative delay"],
)
def test_a_record_off_the_upstream_shape_is_refused(tmp_path: Path, change: dict[str, Any]) -> None:
    records = [_record(i) for i in range(50)]
    records[3] = _record(3, **change)
    with pytest.raises(ControlEvalError, match="not a ControlEval task"):
        _tasks(tmp_path, records)


def test_bytes_that_are_not_the_pinned_ones_are_refused(tmp_path: Path) -> None:
    path, _ = _file(tmp_path, [_record(i) for i in range(50)])
    with pytest.raises(ControlEvalError, match="pinned"):
        controleval.category_tasks("second_order_unstable", path)


def test_the_four_posed_requirements_decide_and_the_unposed_fields_are_kept_beside(
    tmp_path: Path,
) -> None:
    task = _tasks(tmp_path, [_record(i) for i in range(50)])[0]
    headline = {(s.name, s.metric) for s in task.specs if s.counts == "headline"}
    secondary = {(s.name, s.metric, s.bound.unit) for s in task.specs if s.counts == "secondary"}
    assert headline == {
        ("stable", "max_real_pole"),
        ("margin", "phase_margin"),
        ("settling", "settling_time"),
        ("accuracy", "steady_state_error"),
    }
    assert secondary == {
        ("gain_margin_as_ratio", "gain_margin_ratio", "1"),
        ("gain_margin_as_db", "gain_margin_db", "dB"),
        ("overshoot", "overshoot", "percent"),
    }


def test_the_brief_states_the_posed_requirements_and_nothing_the_benchmark_did_not_pose(
    tmp_path: Path,
) -> None:
    brief = _tasks(tmp_path, [_record(i) for i in range(50)])[0].brief
    for posed in ("47.5", "0.125", "4.75", "0.0001"):
        assert posed in brief
    for unposed in ("6.25", "13.375"):
        assert unposed not in brief
    assert "answer.json" in brief


def test_the_whole_numerator_and_the_delay_reach_the_plant(tmp_path: Path) -> None:
    records = [_record(i, tau=0.25) for i in range(50)]
    task = _tasks(tmp_path, records)[4]
    inputs = {m.name: (m.value, m.unit) for m in task.inputs}
    assert inputs["plant_num_0"] == (2.5, "s") and inputs["plant_num_1"] == (5.0, "1")
    assert inputs["plant_delay"] == (0.25, "s")
    assert re.search(r"exp\(-0\.25\*s\)", task.brief)


def test_a_written_task_reads_back_as_the_same_bytes(tmp_path: Path) -> None:
    task = _tasks(tmp_path, [_record(i) for i in range(50)])[0]
    root = controleval.write_task(task, tmp_path / "out")
    assert task_bytes(parse_task((root / "task.json").read_bytes())) == task_bytes(task)


def test_a_fetch_writes_only_the_pinned_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served" / controleval.UPSTREAM_SHA / "ControlEval"
    served.mkdir(parents=True)
    raw = json.dumps([_record(i) for i in range(50)]).encode()
    (served / "second_order_unstable_data.json").write_bytes(raw)
    base = (tmp_path / "served").as_uri()
    cache = tmp_path / "cache"
    with pytest.raises(ControlEvalError, match="not the pinned bytes"):
        controleval.fetch("second_order_unstable", cache, base_url=base)
    assert not any(cache.rglob("*.json"))
    pinned = ("ControlEval/second_order_unstable_data.json", hashlib.sha256(raw).hexdigest())
    monkeypatch.setitem(controleval.CATEGORIES, "second_order_unstable", pinned)
    path = controleval.fetch("second_order_unstable", cache, base_url=base)
    assert path.read_bytes() == raw
    path.write_bytes(raw + b" ")
    with pytest.raises(ControlEvalError, match="cached"):
        controleval.fetch("second_order_unstable", cache, base_url=base)
