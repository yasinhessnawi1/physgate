"""The controller's peak output against the actuator's limit, with every value by hand.

A pure gain ``K`` on ``1/(s+1)``: ``U/R = K(s+1)/(s+1+K)``, so the output jumps to ``K`` at
the step and decays to ``K/(1+K)``; its peak is ``K``. With a delay on the plant the
output stays at ``K`` until the plant answers and only falls after, so the peak is still
``K`` exactly. The unstable plant's PID with a filtered derivative, ``(1.02 s^2 + 2.04 s +
4) / (0.01 s^2 + s)``, has a direct feedthrough of ``1.02 / 0.01 = 102``: its peak.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from control_fixtures import GOOD_PID, control_task, controller, write_answer

from physgate.evaluation.per_role.exceptions import ReferenceCheckError, TaskFormatError
from physgate.evaluation.per_role.scorers.control import check_references, score
from physgate.evaluation.per_role.task import Task, load_task, parse_task


def _effort(limit: float = 5.0, unit: str = "N*m") -> dict[str, Any]:
    return {
        "name": "effort",
        "metric": "actuator_peak",
        "op": "<=",
        "bound": {"value": limit, "unit": unit},
        "composes": ["respect_the_actuator"],
    }


def _task(
    *,
    delay: float | None = None,
    num: list[float] | None = None,
    den: list[float] | None = None,
    limit: dict[str, Any] | bool | None = None,
    step: dict[str, Any] | None = None,
    effort: dict[str, Any] | None = None,
) -> Task:
    base = control_task(
        num if num is not None else [1.0],
        den if den is not None else [1.0, 1.0],
        delay=delay,
        pm_min=30.0,
        ts=(0.05, 10.0),
        ess_max=0.25,
        extra_specs=[effort or _effort()],
    )
    raw = json.loads(base.model_dump_json())
    if limit is not False:
        given = limit if isinstance(limit, dict) else None
        raw["inputs"].append(given or {"name": "actuator_limit", "value": 5.0, "unit": "N*m"})
    if step is not None:
        raw["inputs"].append(step)
    return parse_task(json.dumps(raw).encode())


def _peak(record: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in record["specs"] if row["name"] == "effort")


GAIN_4 = controller([1.0], [1.0], gain=4.0)
GAIN_6 = controller([1.0], [1.0], gain=6.0)


def test_a_gain_s_peak_output_is_the_gain_in_the_actuator_s_unit(tmp_path: Path) -> None:
    row = _peak(score(_task(), write_answer(tmp_path, GAIN_4)))
    assert row["measured"] == {"value": pytest.approx(4.0, abs=1e-9), "unit": "N*m"}
    assert row["passed"]


def test_the_peak_scales_with_the_reference_step(tmp_path: Path) -> None:
    step = {"name": "reference_step", "value": 0.5, "unit": "rad"}
    row = _peak(score(_task(step=step), write_answer(tmp_path, GAIN_4)))
    assert row["measured"]["value"] == pytest.approx(2.0, abs=1e-9)


@pytest.mark.parametrize("delay", [0.02, 0.1, 0.3])
def test_a_delay_enters_exactly_and_never_through_pade(tmp_path: Path, delay: float) -> None:
    # Padé order 10 gives 4.0027, 4.0144 and 4.0437 here; order 12 gives 5.05 at 0.02 s.
    row = _peak(score(_task(delay=delay), write_answer(tmp_path, GAIN_4)))
    assert row["measured"]["value"] == pytest.approx(4.0, abs=1e-6)


def test_a_direct_feedthrough_peaks_at_the_step(tmp_path: Path) -> None:
    limit = {"name": "actuator_limit", "value": 150.0, "unit": "N*m"}
    task = _task(num=[10.0], den=[1.0, -2.0, 3.0], effort=_effort(150.0), limit=limit)
    row = _peak(score(task, write_answer(tmp_path, GOOD_PID)))
    assert row["measured"]["value"] == pytest.approx(102.0, rel=1e-9)


def test_an_unstable_loop_has_no_peak_and_fails_its_bound(tmp_path: Path) -> None:
    unstable = controller([1.0], [1.0], gain=-2.0)
    record = score(_task(), write_answer(tmp_path, unstable))
    assert _peak(record)["measured"] is None and not _peak(record)["passed"]


def test_a_peak_bounded_in_another_unit_than_the_actuator_s_is_refused(tmp_path: Path) -> None:
    task = _task(effort=_effort(5.0, "V"))
    with pytest.raises(TaskFormatError, match="'V' where 'N\\*m'"):
        score(task, write_answer(tmp_path, GAIN_4))


def test_a_peak_bounded_with_no_actuator_limit_is_refused(tmp_path: Path) -> None:
    task = _task(limit=False)
    with pytest.raises(TaskFormatError, match="gives no actuator_limit"):
        score(task, write_answer(tmp_path, GAIN_4))


def _task_dir(tmp_path: Path, references: dict[str, tuple[dict[str, Any], str | None]]) -> Path:
    root = tmp_path / "task"
    root.mkdir()
    (root / "task.json").write_text(_task().model_dump_json(), encoding="utf-8")
    for name, (answer, fails) in references.items():
        ref = root / "references" / name
        write_answer(ref, answer)
        if fails is not None:
            (ref / "expect.json").write_text(json.dumps({"fails": fails}), encoding="utf-8")
    return root


def test_a_controller_past_the_actuator_s_limit_is_the_bad_reference_it_names(
    tmp_path: Path,
) -> None:
    root = _task_dir(tmp_path, {"good": (GAIN_4, None), "bad_effort": (GAIN_6, "effort")})
    check_references(load_task(root))


def test_a_good_reference_past_the_limit_is_refused(tmp_path: Path) -> None:
    root = _task_dir(tmp_path, {"good": (GAIN_6, None), "bad_effort": (GAIN_6, "effort")})
    with pytest.raises(ReferenceCheckError, match="good reference"):
        check_references(load_task(root))
