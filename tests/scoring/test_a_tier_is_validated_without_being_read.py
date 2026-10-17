from __future__ import annotations

import json
from pathlib import Path

from control_fixtures import GOOD_PID, control_task, controller

from physgate.evaluation.per_role.validate import validate


def _write(root: Path, task_id: str, brief: str, good: dict, bad: dict) -> None:  # type: ignore[type-arg]
    task = json.loads(control_task().model_dump_json())
    task.update(id=task_id, brief=brief)
    d = root / task_id
    (d / "references" / "good").mkdir(parents=True)
    (d / "references" / "bad_unstable").mkdir(parents=True)
    (d / "task.json").write_text(json.dumps(task))
    (d / "references" / "good" / "answer.json").write_text(json.dumps(good))
    (d / "references" / "bad_unstable" / "answer.json").write_text(json.dumps(bad))
    (d / "references" / "bad_unstable" / "expect.json").write_text('{"fails": "stable"}')


def test_counts_ids_and_a_digest_are_all_it_reports(tmp_path: Path) -> None:
    unstable = controller([1.0], [1.0], gain=0.1)
    _write(tmp_path, "control.a", "Hold the plant 10/(s^2-2s+3).", GOOD_PID, unstable)
    _write(
        tmp_path,
        "control.b",
        "Hold it; try 1.02 s^2 + 2.04 s + 4 over 0.01 s^2 + s.",
        GOOD_PID,
        unstable,
    )
    _write(tmp_path, "control.c", "Hold the plant.", unstable, unstable)
    report = validate(tmp_path)
    assert report["tasks"] == 3 and report["references_held"] == 2
    assert report["refused"] == ["control.c"]
    assert report["brief_gives_the_answer"] == ["control.b"]
    assert set(report) == {
        "tasks",
        "references_held",
        "refused",
        "brief_gives_the_answer",
        "ids",
        "sha256",
    }
