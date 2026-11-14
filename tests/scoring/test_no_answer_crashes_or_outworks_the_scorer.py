"""No answer crashes the scorer or makes it work without bound; a score says what it rests on.

A score is a failure of the answer, never an error of the scorer: an answer the scorer cannot
compute with is refused by name, and an answer whose analysis would cost more than the stated
work bound is refused before any of that work is done. Every score records its work, the plant
it was computed against (by version and digest), and the grid its margin searches used.

Fixture plants are the draft's (the scorer is told it judges a draft) and the frozen v0 file.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_a_whole_design_is_judged_never_on_an_unsourced_value import (
    COMPUTED_SPECS,
    STATIC_SPECS,
    _answer,
    _feedback,
    _m,
    _native,
    _plant,
    _root,
    _rows,
    _scenario_module,
    _task,
)

_FROZEN = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0.json"


class _ComputedError(Exception):
    """A margin was computed where none may be."""


@pytest.fixture
def no_margins(monkeypatch: pytest.MonkeyPatch) -> None:
    from physgate.evaluation.whole import loop

    def refuse(*_: object) -> None:
        raise _ComputedError

    monkeypatch.setattr(loop, "margins", refuse)
    monkeypatch.setattr(loop, "system", refuse)


def _scenario(specs: list[dict[str, Any]], plant: bytes, root: Path, *, draft: bool) -> Any:
    cls = _scenario_module().WholeDesignScenario
    try:
        return cls(_task(specs), plant, root=root, draft=draft)
    except TypeError as exc:
        pytest.fail(f"the scenario is not told whether it judges a draft: {exc}")


def _record(
    tmp_path: Path,
    doc: dict[str, Any] | str,
    specs: list[dict[str, Any]],
    plant: bytes | None = None,
    *,
    draft: bool = True,
) -> dict[str, Any]:
    root = _root(tmp_path)
    path = root / "whole_run.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    scenario = _scenario(specs, _plant() if plant is None else plant, root, draft=draft)
    try:
        record: dict[str, Any] = scenario.record(path)
    except _ComputedError:
        pytest.fail("a margin was computed for an answer refused before any work")
    except Exception as exc:  # a scorer never crashes on an answer
        pytest.fail(f"the scenario raised on an answer: {exc!r}")
    return record


def _expected_steps(period: float) -> int:
    sweep = int((math.log10(math.pi / period) - math.log10(1e-4)) * 400) + 1
    stepping = math.ceil(math.log(1000.0) / math.log(1.02))
    bisecting = math.ceil(math.log2(math.log(1.02) / 1e-9))
    return sweep + 2 + 2 * (stepping + bisecting)


# F1: the answers that crashed the scorer, and the values that never reach it.


@pytest.mark.parametrize(
    "controller",
    [
        _feedback(period=_m(1e5, "s")),
        _feedback(period=_m(1e12, "s")),
        _feedback(period=_m(1e-300, "s")),
        _native(update_time=10**12),
    ],
    ids=["period_a_day", "period_1e12_s", "period_1e-300_s", "native_update_time_1e12_ms"],
)
def test_the_periods_that_crashed_the_scorer_are_a_refused_answer(
    tmp_path: Path, controller: dict[str, Any], no_margins: None
) -> None:
    record = _record(tmp_path, _answer(controller), COMPUTED_SPECS[1:2])
    assert record["answer_valid"] is False
    assert record["outcome"] == "fail"
    assert "period" in record["reason"] or "update time" in record["reason"], record["reason"]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_in_a_native_answer_are_a_refused_answer(
    tmp_path: Path, token: str, no_margins: None
) -> None:
    text = json.dumps(_answer(_native(angle_response=0))).replace(
        '"value": 0, "unit": "1"', f'"value": {token}, "unit": "1"', 1
    )
    assert token in text
    record = _record(tmp_path, text, COMPUTED_SPECS[1:2])
    assert record["answer_valid"] is False
    assert record["outcome"] == "fail"


@pytest.mark.parametrize("value", [10**400, -(10**400), 2**63])
def test_a_huge_integer_in_a_native_answer_is_a_refused_answer(
    tmp_path: Path, value: int, no_margins: None
) -> None:
    record = _record(tmp_path, _answer(_native(speed_response=value)), COMPUTED_SPECS[1:2])
    assert record["answer_valid"] is False
    assert record["outcome"] == "fail"


def test_a_numerical_failure_inside_the_analysis_is_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.whole import loop

    def singular(*_: object) -> None:
        raise np.linalg.LinAlgError("Singular matrix")

    monkeypatch.setattr(loop, "margins", singular)
    record = _record(tmp_path, _answer(), COMPUTED_SPECS[1:2])
    assert record["outcome"] == "fail"
    refusal = record.get("refusal") or {}
    assert refusal.get("name") == "numerical_failure", record
    assert "Singular matrix" in refusal.get("reason", "")
    assert record["specs"] == []


def test_a_plant_that_is_not_finite_at_the_period_is_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.whole import loop

    monkeypatch.setattr(loop, "expm", lambda block: np.full(block.shape, np.inf))
    record = _record(tmp_path, _answer(), COMPUTED_SPECS[1:2])
    assert record["outcome"] == "fail"
    refusal = record.get("refusal") or {}
    assert refusal.get("name") == "numerical_failure", record
    assert "not finite" in refusal.get("reason", ""), refusal


# F2 and F3: bounded work, decided before any of it, and recorded.


@pytest.mark.parametrize(
    ("period", "sensor"),
    [(0.001, 0.5), (0.0002, 0.5)],
    ids=["period_1_ms_delay_half_a_second", "period_0.2_ms_delay_half_a_second"],
)
def test_the_answers_that_ran_for_minutes_are_refused_before_any_margin(
    tmp_path: Path, period: float, sensor: float, no_margins: None
) -> None:
    controller = _feedback(
        period=_m(period, "s"), sensor_delay=_m(sensor, "s"), compute_delay=_m(0.0, "s")
    )
    plant = _plant(rotor_inertia=(3e-9, 2e-8), com_height=(0.005, 0.078))
    record = _record(tmp_path, _answer(controller), COMPUTED_SPECS[1:2], plant)
    assert record["answer_valid"] is False
    assert record["outcome"] == "fail"


def test_an_answer_past_the_work_bound_is_refused_before_any_margin(
    tmp_path: Path, no_margins: None
) -> None:
    # A 1 ms loop with a delay of fifty periods, on v0's 1,024 corners: a valid answer whose
    # analysis would cost more than the bound.
    controller = _feedback(
        period=_m(0.001, "s"), sensor_delay=_m(0.03, "s"), compute_delay=_m(0.02, "s")
    )
    record = _record(
        tmp_path, _answer(controller), COMPUTED_SPECS[1:2], _FROZEN.read_bytes(), draft=False
    )
    assert record["outcome"] == "fail"
    refusal = record.get("refusal") or {}
    assert refusal.get("name") == "work_bound", record
    work = record["work"]
    assert work["corners"] == {"value": 1025, "unit": "1"}
    assert work["states"] == {"value": 4 + 51, "unit": "1"}
    assert work["steps"] == {"value": _expected_steps(0.001), "unit": "1"}
    assert work["total"]["value"] == 1025 * 55 * _expected_steps(0.001)
    assert work["total"]["value"] > work["bound"]["value"]
    assert record["specs"] == []


def test_an_ordinary_score_on_the_largest_plant_allowed_is_within_the_bound() -> None:
    # The kit's 10 ms loop, its delay under one period, a state feedback (five states), at the
    # 4,096 corners of the most ranged parameters a plant may have, and the nominal set.
    module = _scenario_module()
    bound = getattr(module, "MAX_WORK", None)
    assert bound is not None, "the scenario states no work bound"
    assert 4097 * 5 * _expected_steps(0.01) <= bound
    assert 1025 * 55 * _expected_steps(0.001) > bound


def test_every_score_records_the_work_it_did(tmp_path: Path) -> None:
    plant = _plant(rotor_inertia=(3e-9, 2e-8), com_height=(0.005, 0.078))
    record = _record(tmp_path, _answer(), COMPUTED_SPECS[1:2], plant)
    work = record.get("work")
    assert work is not None, "the record carries no work"
    assert work["corners"] == {"value": 5, "unit": "1"}
    assert work["states"] == {"value": 5, "unit": "1"}
    assert work["steps"] == {"value": _expected_steps(0.01), "unit": "1"}
    assert work["total"] == {"value": 5 * 5 * _expected_steps(0.01), "unit": "1"}
    assert work["bound"]["unit"] == "1"


def test_a_score_reading_no_loop_does_no_loop_work(tmp_path: Path, no_margins: None) -> None:
    record = _record(tmp_path, _answer(), STATIC_SPECS + COMPUTED_SPECS[:1])
    work = record.get("work")
    assert work is not None, "the record carries no work"
    assert work["corners"] == {"value": 0, "unit": "1"}
    assert work["total"] == {"value": 0, "unit": "1"}


# F6: the plant a score was computed against.


def test_a_score_names_the_frozen_plant_it_was_computed_against(tmp_path: Path) -> None:
    raw = _FROZEN.read_bytes()
    record = _record(tmp_path, _answer(), STATIC_SPECS[:1], raw, draft=False)
    assert record["plant"] == {
        "version": "v0",
        "status": "frozen",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_a_draft_is_judged_only_when_the_scorer_is_told_so_and_says_draft(tmp_path: Path) -> None:
    from physgate.evaluation.whole.plant import PlantError

    plant = _plant()
    (tmp_path / "refused").mkdir()
    with pytest.raises(PlantError, match="not a frozen plant"):
        _scenario(STATIC_SPECS, plant, _root(tmp_path / "refused"), draft=False)
    record = _record(tmp_path, _answer(), STATIC_SPECS[:1], plant, draft=True)
    assert record["plant"]["version"] is None
    assert record["plant"]["status"] == "draft"


@pytest.mark.parametrize("draft", [False, True])
def test_a_frozen_plant_edited_after_its_freeze_is_refused(tmp_path: Path, draft: bool) -> None:
    from physgate.evaluation.whole.plant import PlantError

    doc = json.loads(_FROZEN.read_bytes())
    doc["parameters"]["com_height"]["high"] = 0.05
    edited = json.dumps(doc).encode()
    with pytest.raises(PlantError, match="not a frozen plant"):
        _scenario(STATIC_SPECS, edited, _root(tmp_path), draft=draft)


# The notes: the leak, an unheld travel, the corners, the search grid.

_KIT_SI = {
    "structure": "incremental_rising_offset",
    "period": _m(0.01, "s"),
    "command_limit": _m(0.75, "1"),
    "sensor_delay": _m(0.0048, "s"),
    "compute_delay": _m(0.002, "s"),
    "rate_ratio": _m(0.14, "s"),
    "angle_gain": _m(0.14195, "1/rad"),
    "distance_gain": _m(0.17308, "1/m"),
    "speed_gain": _m(0.07824, "s/m"),
}


@pytest.mark.parametrize("decay", [1 - 1e-12, 1 - 1e-10, 1 - 1e-14])
def test_a_leak_too_small_to_act_is_judged_as_no_leak(tmp_path: Path, decay: float) -> None:
    plant = _plant(rotor_inertia=(1e-9, 1e-9))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    leak_free = _rows(_record(tmp_path / "a", _answer(dict(_KIT_SI)), COMPUTED_SPECS[1:], plant))
    leaky = dict(_KIT_SI, angle_decay_per_update=_m(decay, "1"))
    tiny = _rows(_record(tmp_path / "b", _answer(leaky), COMPUTED_SPECS[1:], plant))
    for name in ("pm", "up", "down"):
        assert tiny[name]["verdict"] == leak_free[name]["verdict"], (name, tiny[name])
        assert tiny[name]["measured"] is not None, (name, tiny[name])
        assert tiny[name]["measured"]["value"] == pytest.approx(
            leak_free[name]["measured"]["value"], rel=1e-6
        )


def test_a_design_with_no_distance_gain_fails_and_the_record_says_why(tmp_path: Path) -> None:
    controller = _feedback((1.6643, 0.191, 0.0, 1.3421))
    rows = _rows(_record(tmp_path, _answer(controller), COMPUTED_SPECS[1:]))
    for name in ("pm", "up", "down"):
        assert rows[name]["verdict"] == "fail", rows[name]
        assert rows[name]["measured"] is None
        reason = rows[name]["reason"]
        assert "unstable" in reason, reason
        assert "no distance gain" in reason, reason


def test_a_pass_says_it_holds_at_every_corner_and_that_the_interior_is_not_searched(
    tmp_path: Path,
) -> None:
    plant = _plant(rotor_inertia=(3e-9, 2e-8))
    rows = _rows(_record(tmp_path, _answer(), COMPUTED_SPECS[1:2], plant))
    assert rows["pm"]["verdict"] == "pass", rows["pm"]
    assert "every corner" in rows["pm"]["reason"]
    assert "interior" in rows["pm"]["reason"] and "not searched" in rows["pm"]["reason"]


def test_each_margin_records_the_grid_its_search_used(tmp_path: Path) -> None:
    rows = _rows(_record(tmp_path, _answer(), COMPUTED_SPECS[1:]))
    for name in ("pm", "up", "down"):
        search = rows[name].get("search")
        assert search is not None, f"{name} records no search grid"
        assert search["gain_step"] == {"value": 1.02, "unit": "1"}
        assert search["gain_limit"] == {"value": 1000.0, "unit": "1"}
        assert search["gain_tolerance"] == {"value": 1e-9, "unit": "1"}
        assert search["points_per_decade"] == {"value": 400, "unit": "1"}
        assert search["lowest_frequency"] == {"value": 1e-4, "unit": "rad/s"}
        assert search["highest_frequency"]["unit"] == "rad/s"
        assert search["highest_frequency"]["value"] == pytest.approx(math.pi / 0.01)
