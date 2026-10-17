from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import control as ct
import pytest
from control_fixtures import GOOD_PID, control_task, controller, write_answer

from physgate.evaluation.per_role.exceptions import ReferenceCheckError, TaskFormatError
from physgate.evaluation.per_role.scorers.control import (
    check_references,
    gain_margin,
    phase_margin,
    score,
    score_bytes,
)
from physgate.evaluation.per_role.task import load_task


def _row(record: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in record["specs"] if row["name"] == name)


def test_a_controller_that_meets_every_spec_passes(tmp_path: Path) -> None:
    record = score(control_task(), write_answer(tmp_path, GOOD_PID))
    assert record["answer_valid"] and record["passed"]
    assert _row(record, "settling")["measured"]["unit"] == "s"


def test_the_same_answer_scores_to_the_same_bytes(tmp_path: Path) -> None:
    path = write_answer(tmp_path, GOOD_PID)
    assert score_bytes(control_task(), path) == score_bytes(control_task(), path)


def test_the_phase_margin_with_a_delay_is_exact() -> None:
    # L = K e^{-s tau} / s crosses at w = K, where its phase is -90 deg - K tau rad.
    gain, delay = 2.0, 0.1
    margin, crossed = phase_margin(ct.tf([gain], [1, 0]), ct.tf([1], [1]), delay)
    assert crossed
    assert margin == pytest.approx(90.0 - math.degrees(gain * delay), abs=1e-9)


@pytest.mark.parametrize(
    ("c", "g"),
    [
        (ct.tf([1.02, 2.04, 4.0], [0.01, 1.0, 0.0]), ct.tf([10], [1, -2, 3])),
        (ct.tf([5, 5], [1, 0]), ct.tf([1125], [1, 84.2, 1845, 7020, 13500])),
        (ct.tf([3.0], [1.0]), ct.tf([1, 2], [1, 3, 5, 1])),
    ],
)
def test_without_a_delay_the_margins_agree_with_python_control(c: Any, g: Any) -> None:
    gm, pm, _, _ = ct.margin(c * g)
    assert phase_margin(c, g, 0.0)[0] == pytest.approx(pm, abs=1e-6)
    assert gain_margin(c, g, 0.0) == pytest.approx(gm, rel=1e-6)


@pytest.mark.parametrize(
    ("c", "g"),
    [
        (ct.tf([1e12], [1]), ct.tf([1], [1, 1e6, 0])),
        (ct.tf([1e9], [1]), ct.tf([1], [1, 1e6, 0])),
        (ct.tf([1e-6], [1]), ct.tf([1], [1, 0])),
        (ct.tf([1e5], [1]), ct.tf([1], [1, 0])),
    ],
    ids=[
        "crossover near 8e5 rad/s",
        "integrator, crossover at 1e3 rad/s",
        "crossover at 1e-6",
        "no root to start from, crossover at 1e5",
    ],
)
def test_every_crossover_is_found_wherever_the_loop_puts_it(c: Any, g: Any) -> None:
    margin, crossed = phase_margin(c, g, 0.0)
    assert crossed
    assert margin == pytest.approx(ct.margin(c * g)[1], abs=1e-6)


def test_the_plant_is_its_whole_numerator(tmp_path: Path) -> None:
    # (s + 5) / (s**2 + s + 1): dropping the zero changes the margin.
    task = control_task([1.0, 5.0], [1.0, 1.0, 1.0], pm_min=0.0, ts=(0.0, 100.0), ess_max=1.0)
    record = score(task, write_answer(tmp_path, controller([1.0], [1.0], gain=3.0)))
    full = ct.margin(ct.tf([3.0, 15.0], [1, 1, 1]))[1]
    truncated = ct.margin(ct.tf([3.0], [1, 1, 1]))[1]
    assert _row(record, "margin")["measured"]["value"] == pytest.approx(full, abs=1e-6)
    assert abs(full - truncated) > 1.0


def test_a_response_that_never_settles_fails_and_says_so(tmp_path: Path) -> None:
    # A lightly damped loop: stable, but nowhere near settled inside the horizon.
    task = control_task([1.0], [1.0, 1e-4, 1.0], pm_min=0.0, ts=(0.0, 3.0), ess_max=1.0)
    record = score(task, write_answer(tmp_path, controller([1.0], [1.0], gain=1e-3)))
    assert _row(record, "stable")["passed"]
    assert record["flags"]["did_not_settle"]
    assert _row(record, "settling")["measured"] is None
    assert not _row(record, "settling")["passed"]
    assert not record["passed"]


def test_stability_is_judged_with_the_delay(tmp_path: Path) -> None:
    # 10 / (s + 1) is held by unity gain without a delay, and lost with 0.5 s of it.
    answer = write_answer(tmp_path, controller([1.0], [1.0], gain=10.0))
    loose = dict(pm_min=-180.0, ts=(0.0, 50.0), ess_max=1.0)
    without = score(control_task([1.0], [1.0, 1.0], **loose), answer)  # type: ignore[arg-type]
    with_delay = score(control_task([1.0], [1.0, 1.0], delay=0.5, **loose), answer)  # type: ignore[arg-type]
    assert _row(without, "stable")["passed"]
    assert not _row(with_delay, "stable")["passed"]
    assert not with_delay["passed"]


def test_no_gain_crossover_counts_as_a_margin_and_is_flagged(tmp_path: Path) -> None:
    task = control_task([1.0], [1.0, 1.0], pm_min=45.0, ts=(0.0, 20.0), ess_max=1.0)
    record = score(task, write_answer(tmp_path, controller([1.0], [1.0], gain=0.5)))
    assert record["flags"]["no_gain_crossover"]
    assert _row(record, "margin")["infinite"] and _row(record, "margin")["passed"]


def test_a_value_within_half_a_percent_of_its_bound_is_flagged(tmp_path: Path) -> None:
    answer = write_answer(tmp_path, GOOD_PID)
    measured = _row(score(control_task(), answer), "margin")["measured"]["value"]
    record = score(control_task(pm_min=measured * 0.999), answer)
    assert _row(record, "margin")["borderline"] and _row(record, "margin")["passed"]


def test_an_answer_that_is_not_a_controller_fails_without_a_scorer_error(tmp_path: Path) -> None:
    record = score(control_task(), write_answer(tmp_path, {"form": "lti_tf", "gain": 2.0}))
    assert not record["answer_valid"] and not record["passed"]


def test_a_metric_the_scorer_lacks_or_a_bound_in_the_wrong_unit_is_refused(
    tmp_path: Path,
) -> None:
    answer = write_answer(tmp_path, GOOD_PID)
    odd = {"name": "odd", "metric": "bandwidth", "op": ">=", "composes": ["x"]}
    with pytest.raises(TaskFormatError, match="lacks"):
        score(control_task(extra_specs=[{**odd, "bound": {"value": 1, "unit": "rad/s"}}]), answer)
    in_radians = {
        "name": "margin_rad",
        "metric": "phase_margin",
        "op": ">=",
        "bound": {"value": 0.7, "unit": "rad"},
        "composes": ["x"],
    }
    with pytest.raises(TaskFormatError, match="'rad' where 'deg'"):
        score(control_task(extra_specs=[in_radians]), answer)


def _task_dir(tmp_path: Path, references: dict[str, tuple[dict[str, Any], str | None]]) -> Path:
    root = tmp_path / "task"
    root.mkdir()
    (root / "task.json").write_text(control_task().model_dump_json(), encoding="utf-8")
    for name, (answer, fails) in references.items():
        ref = root / "references" / name
        write_answer(ref, answer)
        if fails is not None:
            (ref / "expect.json").write_text(json.dumps({"fails": fails}), encoding="utf-8")
    return root


#: The good PID with its integral gain cut twentyfold: stable, with its margin and no
#: steady-state error, but settling in about 22 s against a 3 s window.
SLOW_PID = controller([1.02, 2.002, 0.2], [0.01, 1.0, 0.0])


def test_a_slow_controller_fails_the_settling_window_and_nothing_else(tmp_path: Path) -> None:
    record = score(control_task(), write_answer(tmp_path, SLOW_PID))
    failed = {row["name"] for row in record["specs"] if not row["passed"]}
    assert failed == {"settling"}
    assert _row(record, "settling")["measured"]["value"] > 3.0


def test_the_scorer_passes_its_good_reference_and_fails_each_bad_one(tmp_path: Path) -> None:
    root = _task_dir(
        tmp_path,
        {
            "good": (GOOD_PID, None),
            "bad_unstable": (controller([1.0], [1.0], gain=0.1), "stable"),
            "bad_slow": (SLOW_PID, "settling"),
        },
    )
    check_references(load_task(root))


def test_a_scorer_that_fails_its_good_reference_is_refused(tmp_path: Path) -> None:
    root = _task_dir(
        tmp_path,
        {
            "good": (controller([1.0], [1.0], gain=0.1), None),
            "bad_unstable": (controller([1.0], [1.0], gain=0.1), "stable"),
        },
    )
    with pytest.raises(ReferenceCheckError, match="good reference"):
        check_references(load_task(root))


def test_a_bad_reference_that_passes_its_spec_is_refused(tmp_path: Path) -> None:
    root = _task_dir(
        tmp_path,
        {"good": (GOOD_PID, None), "bad_not_really": (GOOD_PID, "margin")},
    )
    with pytest.raises(ReferenceCheckError, match="should fail 'margin'"):
        check_references(load_task(root))


def test_a_nan_meets_no_bound_whatever_the_comparison() -> None:
    from physgate.evaluation.per_role.scorers.control import _holds

    for spec in control_task().specs:
        assert _holds(spec, math.nan) == (False, False)
        assert _holds(spec, None) == (False, False)
