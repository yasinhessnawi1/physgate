"""A linear time row states how far its numbers can be trusted, and reports only what did not fall.

The numbers come from a loop that rounds its command to whole counts, on a plant that is unstable
while the command sits at its limit: a difference of 1e-17 grows until a count flips, and then
differs by whole counts. So the record carries a measured sensitivity (the batch run a second time
with one tiny, stated perturbation); a point whose verdict differs between the two runs counts
neither way; a lane that fell is frozen and reports nothing of the time after; the record says
whether a fall is the demand's (past the motor's ceiling) or the law's; the peak is sampled at a
stated spacing. Rows that pin physics use cases that are not sensitive (no rounding, or well inside
the stable region), and compare with tolerances, never with a recorded design's corner counts.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from physgate.evaluation.whole import dynamic
from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole.loop import continuous
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal, parse_plant
from physgate.evaluation.whole.scenario import WholeDesignScenario, WholeDesignTask

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
stepping: Any = importlib.import_module(
    "test_the_linear_time_run_is_the_margins_loop_stepped_in_time"
)
rows_module: Any = importlib.import_module(
    "test_a_linear_time_row_is_labelled_secondary_and_changes_no_existing_record"
)

EXACT_COUNTS = 1e18
UNLIMITED = 1e9
SPEED, PUSH, HEADLINE = rows_module.SPEED, rows_module.PUSH, rows_module.HEADLINE


def _speed_at_least(bound: float) -> dict[str, Any]:
    spec: dict[str, Any] = rows_module._linear(dynamic.STEADY_SPEED, bound, "m/s", ">=")
    return spec


def _plant_with_ranges(ranges: dict[str, float]) -> bytes:
    """The draft plant with every range collapsed but these, each ± the given fraction."""
    doc = helpers._plant_doc()
    for name, fraction in ranges.items():
        value = doc["parameters"][name]["value"]
        doc["parameters"][name]["low"] = value * (1.0 - fraction)
        doc["parameters"][name]["high"] = value * (1.0 + fraction)
    return json.dumps(doc).encode()


#: Three ranged inputs: eight corners and the nominal point, a run of about a second.
SMALL_RANGES = {"wheel_radius": 0.005, "kit_mass": 0.02, "motor_no_load_speed": 0.1}


def _record(
    root: Path, specs: list[dict[str, Any]], controller: dict[str, Any], version: int = 3, **kw: Any
) -> Any:
    root = Path(os.path.realpath(root))
    answers = root / "answers"
    answers.mkdir(parents=True)
    task = WholeDesignTask.model_validate_json(
        json.dumps({"id": "whole.fixture", "requirements": ["c5", "c15"], "specs": specs})
    )
    ranges = kw.get("ranges", SMALL_RANGES)
    scenario = WholeDesignScenario(task, _plant_with_ranges(ranges), root=answers, draft=True)
    path = answers / "answer.json"
    path.write_bytes(helpers._answer(controller, version))
    return scenario.record(path)


def _rows(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in record["specs"]}


@pytest.fixture(scope="module")
def stable(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The recorded law on a plant of eight corners it holds at, with bounds well inside it."""
    specs = [HEADLINE, _speed_at_least(1.0), PUSH]
    return _record(tmp_path_factory.mktemp("stable"), specs, helpers._recorded_controller())


def _falling_controller() -> dict[str, Any]:
    c = helpers._feedback()
    c["angle_gain"] = helpers._m(-helpers.GOOD_GAINS[0], "1/rad")
    return c  # type: ignore[no-any-return]


# ── H1: the sensitivity, measured and stated ─────────────────────────────────────────────────


def test_the_perturbation_is_a_named_tiny_offset_of_the_tilt_rate_in_every_lane() -> None:
    assert 0.0 < dynamic.SENSITIVITY_RATE_OFFSET <= 1e-9 * dynamic.PUSH_RATE
    values = nominal(_plant())
    plan = _plan(values)
    for offset in (0.0, dynamic.SENSITIVITY_RATE_OFFSET):
        sim = _sim(plan, rate_offset=offset)
        assert (sim.x[:, 1] == offset).all()
        assert (sim.x[:, [0, 2, 3]] == 0.0).all()


def _plant() -> Any:
    root = Path(__file__).resolve().parents[2]
    return parse_plant((root / "src/physgate/evaluation/whole/plant_v0.json").read_bytes())


def _plan(
    values: dict[str, float], limit: float = UNLIMITED, full_scale: float = EXACT_COUNTS
) -> Any:
    legacy = helpers._si(helpers._feedback(), values["wheel_radius"])
    return dynamic.Plan(
        law=dynamic.compile_law(
            dynamic.named_as_law(legacy),
            dynamic.named_values([legacy], [values["wheel_radius"]]),
            legacy.period,
        ),
        period=legacy.period,
        sensor_delay=legacy.sensor_delay,
        compute_delay=legacy.compute_delay,
        command_limit=limit,
        full_scale=full_scale,
        points=(values,),
    )


def _sim(plan: Any, rate_offset: float = 0.0) -> Any:
    tm = dynamic.timing(plan.period, plan.sensor_delay, plan.compute_delay)
    radius, phis, gams = dynamic._segments(plan, tm)
    return dynamic._Sim(plan, radius, phis, gams, tm, rate_offset=rate_offset)


def test_a_row_carries_its_sensitivity_beside_its_number_judged_by_nothing(stable: Any) -> None:
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        row = _rows(stable)[name]
        s = row["sensitivity"]
        assert s["perturbation"] == {
            "name": "initial_tilt_rate_offset",
            "value": dynamic.SENSITIVITY_RATE_OFFSET,
            "unit": "rad/s",
        }
        assert "judged by nothing" in s["meaning"]
        c = s["corners"]
        assert c["count"] == 8
        assert (c["verdict_differs"], c["fell_differs"]) == (0, 0)
        assert c["largest_change"]["unit"] == row["measured"]["unit"]
        assert c["largest_change"]["value"] < 0.05 * abs(row["measured"]["value"])
        assert s["nominal"]["verdict_differs"] is False
        assert row["corners"]["contested"] == 0
        assert row["corners"]["failing"] == 0


def test_the_label_says_the_counts_may_differ_by_a_few_points_between_machines(
    stable: Any,
) -> None:
    sentence = "reproducible on one machine and may differ by a few points between machines"
    assert sentence in dynamic.LABEL
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        assert sentence in _rows(stable)[name]["label"]
    assert "last bit" in dynamic.LABEL


def _with_second_run_altered(monkeypatch: pytest.MonkeyPatch, alter: Any) -> None:
    """The scenario's second run, as the first but for what ``alter`` does to its result."""
    real = dynamic.run

    def run(plan: Any, **kw: Any) -> Any:
        result = real(plan, **kw)
        return alter(result) if kw.get("rate_offset") else result

    monkeypatch.setattr(dynamic, "run", run)


def test_the_corner_counts_say_how_many_points_sit_on_a_changed_verdict_or_fall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def alter(res: Any) -> Any:
        speed = res.speed.copy()
        speed[2] = speed[2] - 0.1  # a finite point whose number moves, the verdict not
        speed[3] = speed[3] - 0.5  # a finite point whose number moves past the bound
        speed[4] = math.nan  # a point that falls in the second run only
        fell = res.fell_before.copy()
        fell[4] = True
        return dataclasses.replace(res, speed=speed, fell_before=fell)

    _with_second_run_altered(monkeypatch, alter)
    record = _record(tmp_path, [HEADLINE, _speed_at_least(1.0)], helpers._recorded_controller())
    row = _rows(record)[dynamic.STEADY_SPEED]
    s = row["sensitivity"]["corners"]
    assert s["count"] == 8
    assert s["verdict_differs"] == 2  # the fourth's number (1.2 - 0.5 < 1.0) and the fifth's fall
    assert s["fell_differs"] == 1
    # the largest change is over the points that have a number in both runs
    assert s["largest_change"]["value"] == pytest.approx(0.5, abs=0.05)
    assert row["corners"]["contested"] == 2
    assert row["corners"]["passing"] + row["corners"]["failing"] + 2 == 8


def test_a_point_whose_verdict_differs_counts_neither_way_and_leaves_the_row_unscored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = helpers._recorded_controller()
    specs = [HEADLINE, _speed_at_least(1.0)]
    before = _rows(_record(tmp_path / "a", specs, controller))
    assert before[dynamic.STEADY_SPEED]["verdict"] == "pass"

    def alter(res: Any) -> Any:
        speed = res.speed.copy()
        speed[5] = 0.5
        return dataclasses.replace(res, speed=speed)

    _with_second_run_altered(monkeypatch, alter)
    after = _rows(_record(tmp_path / "b", specs, controller))
    row = after[dynamic.STEADY_SPEED]
    assert row["corners"]["contested"] == 1
    assert row["corners"]["passing"] == 7
    assert row["verdict"] == "unscored"
    assert "contested" in row["reason"]


def test_the_contested_count_is_said_to_be_at_least_the_fragile_points_one_perturbation_finds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stable: Any
) -> None:
    # one perturbation finds some of the points whose verdict is fragile, not every one: the
    # record says that the count is a lower bound, in the row's meaning and in its reason
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        assert "at least" in _rows(stable)[name]["sensitivity"]["meaning"]

    def alter(res: Any) -> Any:
        speed = res.speed.copy()
        speed[5] = 0.5
        return dataclasses.replace(res, speed=speed)

    _with_second_run_altered(monkeypatch, alter)
    specs = [HEADLINE, _speed_at_least(1.0)]
    row = _rows(_record(tmp_path, specs, helpers._recorded_controller()))[dynamic.STEADY_SPEED]
    assert row["corners"]["contested"] == 1
    assert "1 are contested" in row["reason"]
    assert "at least that many points are fragile" in row["reason"]


def test_a_row_that_fails_at_some_points_and_at_the_nominal_one_is_unscored_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = dynamic.run

    def run(plan: Any, **kw: Any) -> Any:
        result = real(plan, **kw)
        speed = result.speed.copy()
        speed[0] = 0.5  # the nominal point and one corner are under the bound in both runs
        speed[3] = 0.5
        return dataclasses.replace(result, speed=speed)

    monkeypatch.setattr(dynamic, "run", run)
    record = _record(tmp_path, [HEADLINE, _speed_at_least(1.0)], helpers._recorded_controller())
    row = _rows(record)[dynamic.STEADY_SPEED]
    assert (row["corners"]["passing"], row["corners"]["failing"], row["corners"]["contested"]) == (
        7,
        1,
        0,
    )
    assert row["verdict"] == "unscored"


def test_a_nominal_point_whose_verdict_differs_also_leaves_the_row_unscored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def alter(res: Any) -> Any:
        speed = res.speed.copy()
        speed[0] = 0.5
        return dataclasses.replace(res, speed=speed)

    _with_second_run_altered(monkeypatch, alter)
    record = _record(tmp_path, [HEADLINE, _speed_at_least(1.0)], helpers._recorded_controller())
    row = _rows(record)[dynamic.STEADY_SPEED]
    assert row["sensitivity"]["nominal"]["verdict_differs"] is True
    assert row["verdict"] == "unscored"


# ── a linear row can pass, and can fail at every point ───────────────────────────────────────


def test_a_law_that_holds_at_every_point_gives_a_linear_pass_that_changes_no_outcome(
    stable: Any,
) -> None:
    rows = _rows(stable)
    speed, push = rows[dynamic.STEADY_SPEED], rows[dynamic.PUSH_PEAK_TILT]
    assert speed["verdict"] == "pass"
    assert push["verdict"] == "pass"
    assert speed["corners"] | {"ranged": None} == {
        "ranged": None,
        "count": 8,
        "passing": 8,
        "failing": 0,
        "contested": 0,
        "fell": 0,
        "low": speed["corners"]["low"],
        "high": speed["corners"]["high"],
    }
    assert 1.0 < speed["corners"]["low"]["value"] <= speed["corners"]["high"]["value"] < 1.4
    assert 0.0 < push["corners"]["high"]["value"] < 70.0
    assert "holds at the nominal values and at every corner" in speed["reason"]
    assert stable["outcome"] == "pass"


def test_a_bound_no_point_reaches_gives_a_linear_fail_at_every_point_and_a_pass_headline(
    tmp_path: Path,
) -> None:
    specs = [HEADLINE, _speed_at_least(1e6)]
    record = _record(tmp_path, specs, helpers._recorded_controller())
    row = _rows(record)[dynamic.STEADY_SPEED]
    assert row["verdict"] == "fail"
    assert row["corners"]["passing"] == 0
    assert row["corners"]["failing"] == 8
    assert "fails at the nominal values and at every corner" in row["reason"]
    assert _rows(record)["rate"]["verdict"] == "pass"
    assert record["outcome"] == "pass"


def test_a_version_2_named_structure_gets_rows_of_the_same_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The state feedback, asked for 0.6 m/s so its command stays inside the limit, tracks it."""
    monkeypatch.setattr(dynamic, "DEMAND_SPEED", 0.6)
    specs = [HEADLINE, _speed_at_least(0.5), PUSH]
    record = _record(
        tmp_path, specs, helpers._feedback(), version=2, ranges={"wheel_radius": 0.005}
    )
    rows = _rows(record)
    speed = rows[dynamic.STEADY_SPEED]
    assert speed["corners"]["count"] == 2
    assert record["dynamic_linear"]["points"] == 3
    assert speed["measured"]["value"] == pytest.approx(0.6, rel=0.03)
    assert speed["measured"]["unit"] == "m/s"
    assert speed["corners"]["fell"] == 0
    assert speed["verdict"] == "pass"
    push = rows[dynamic.PUSH_PEAK_TILT]
    assert push["measured"]["unit"] == "deg"
    assert 0.5 < push["measured"]["value"] < 30.0
    assert push["verdict"] == "pass"


# ── the physics rows: constructed, not sensitive, with tolerances ────────────────────────────


def _exact(limit: float = UNLIMITED, **tweak: float) -> Any:
    return stepping._stepped(limit, EXACT_COUNTS, **tweak)


def test_a_push_adds_to_the_peak_in_proportion_when_nothing_rounds_and_nothing_limits() -> None:
    """The response is linear below the limit with no rounding: the three peaks are the pushes'."""
    result = _exact()
    low, mid, high = (float(p) for p in result.peak[:, 0])
    kicks = [dynamic.PUSH_RATE * (1.0 + b) for b in dynamic.PUSH_BAND]
    # the peak is the cruise's tilt plus the push times a constant: differences are in the pushes
    assert (high - low) / (mid - low) == pytest.approx(
        (kicks[2] - kicks[0]) / (kicks[1] - kicks[0]), rel=1e-6
    )
    # and the recorded perturbation moves none of them by a hundredth
    again = stepping._stepped(UNLIMITED, EXACT_COUNTS, rate_offset=dynamic.SENSITIVITY_RATE_OFFSET)
    assert again.peak[:, 0] == pytest.approx(result.peak[:, 0], rel=1e-2)


# ── M1, M2: a lane that fell is frozen and reports nothing of what came after ───────────────


def test_a_lane_that_fell_counts_no_update_at_the_limit_after_it_fell() -> None:
    result = stepping._stepped(0.75, EXACT_COUNTS, angle_gain=-1.0)
    assert result.fell_before[0]
    # it fell within a fraction of a second of the rest, long before the hold window
    assert result.fell_at[0] < dynamic.REST_TIME + 2.0
    assert result.saturated_hold[0] == 0
    assert (result.saturated_push[:, 0] == 0).all()


def test_a_lane_that_fell_has_no_window_mean_and_no_speed_at_the_push() -> None:
    result = stepping._stepped(0.75, EXACT_COUNTS, angle_gain=-1.0)
    assert math.isnan(result.speed[0])
    assert all(math.isnan(m[0]) for m in result.means.values())
    assert math.isnan(result.speed_at_push[0])


def test_the_window_means_before_a_fall_stay_numbers_and_those_after_it_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fall at about 12 s: the means at 5 and 10 s are the robot's, those at 15 and 20 are not."""
    monkeypatch.setattr(dynamic, "REST_TIME", 12.0)
    # a bound the rest never reaches and the ramp's lean passes: 70 degrees is far; take 0.5 deg
    monkeypatch.setattr(dynamic, "FELL_TILT", math.radians(0.5))
    result = _exact()
    assert result.fell_before[0]
    assert 12.0 < result.fell_at[0] < 14.0
    assert result.means[5.0][0] == pytest.approx(0.0, abs=1e-9)
    assert result.means[10.0][0] == pytest.approx(0.0, abs=1e-9)
    assert math.isnan(result.means[15.0][0])
    assert math.isnan(result.means[20.0][0])
    assert math.isnan(result.speed_at_push[0])


def test_a_lane_that_never_falls_keeps_every_number_and_has_no_time_of_fall() -> None:
    result = _exact()
    assert not result.fell_before[0]
    assert math.isnan(result.fell_at[0])
    assert not math.isnan(result.speed_at_push[0])
    assert result.fell_at_push.shape == (3, 1)
    assert np.isnan(result.fell_at_push).all()


def test_a_fall_after_the_push_has_its_time_and_the_limit_counts_stop_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dynamic, "PUSH_RATE", 100.0)
    result = stepping._stepped(1.3, EXACT_COUNTS)
    assert result.fell_after[:, 0].all()
    times = result.fell_at_push[:, 0]
    assert (times > dynamic.PUSH_TIME).all()
    assert (times < dynamic.PUSH_TIME + dynamic.OBSERVE).all()
    # a fall within a few updates of the push: nothing like the 400 of the observed time
    assert (result.saturated_push[:, 0] < 20).all()
    assert not result.fell_before[0]


def test_a_record_of_a_law_that_falls_everywhere_has_no_lane_at_the_limit_and_no_mean(
    tmp_path: Path,
) -> None:
    specs = [HEADLINE, _speed_at_least(1.2), PUSH]
    record = _record(tmp_path, specs, _falling_controller(), version=2)
    rows = _rows(record)
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        info = rows[name]["linear_run"]
        assert rows[name]["corners"]["fell"] == 8
        assert info["limit_reached"] == {"nominal_updates": None, "corners": 0, "of": 0}
        assert info["fell"]["before_push"] == 8
        assert info["fell"]["nominal"]["before_push_at"]["unit"] == "s"
        assert "reached at 0 of 0" in rows[name]["reason"]
    speed = rows[dynamic.STEADY_SPEED]["linear_run"]
    assert all(m is None for m in speed["window_means_at_nominal"].values())
    push = rows[dynamic.PUSH_PEAK_TILT]["linear_run"]
    assert push["speed_at_push_at_nominal"] is None
    assert push["fell"]["after_push"] == 0


# ── M3: the ceiling, and a fall that is the demand's or the law's ───────────────────────────


def test_the_ceiling_is_the_steady_speed_of_a_constant_command_at_the_limit() -> None:
    values = nominal(_plant())
    limit = 0.9425
    ceiling = dynamic.ceiling(values, limit)
    a, b = continuous(values)
    # the steady state: the tilt leans, the speed is constant, and neither accelerates
    lean = -(a[1, 3] * ceiling + b[1, 0] * limit) / a[1, 0]
    state = np.array([lean, 0.0, 0.0, ceiling])
    rates = a @ state + b[:, 0] * limit
    scale = np.abs(a * state[None, :]).max()
    assert abs(rates[1]) < 1e-9 * scale
    assert abs(rates[3]) < 1e-9 * scale
    assert rates[0] == 0.0
    assert ceiling > 0.0
    assert dynamic.ceiling(values, 2 * limit) == pytest.approx(2 * ceiling, rel=1e-12)
    assert dynamic.ceiling(values, -limit) == pytest.approx(-ceiling, rel=1e-12)


def test_the_ceiling_falls_as_the_motor_runs_out_of_speed() -> None:
    values = nominal(_plant())
    slower = {**values, "motor_no_load_speed": values["motor_no_load_speed"] * 0.5}
    assert dynamic.ceiling(slower, 0.75) < dynamic.ceiling(values, 0.75)


def _ceilings(ranges: dict[str, float], limit: float) -> list[float]:
    plant = parse_plant(_plant_with_ranges(ranges))
    return [dynamic.ceiling(c, limit) for c in corners(plant, LOOP_INPUTS)]


def test_a_fall_is_split_by_whether_the_ceiling_is_below_the_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The law falls everywhere; with the demand among the ceilings, the split is theirs."""
    limit = 0.75
    ranges = {"motor_no_load_speed": 0.3, "wheel_radius": 0.005}
    ceilings = _ceilings(ranges, limit)
    demand = float(np.median(ceilings))
    assert min(ceilings) < demand < max(ceilings)
    monkeypatch.setattr(dynamic, "DEMAND_SPEED", demand)
    below = sum(c < demand for c in ceilings)
    specs = [HEADLINE, _speed_at_least(1.0)]
    record = _record(tmp_path, specs, _falling_controller(), version=2, ranges=ranges)
    info = _rows(record)[dynamic.STEADY_SPEED]["linear_run"]
    assert info["fell"]["before_push"] == len(ceilings)
    split = info["fell"]["by_ceiling"]
    assert split == {"below_demand": below, "at_or_above_demand": len(ceilings) - below}
    assert 0 < below < len(ceilings)
    assert info["ceiling"]["demand"]["value"] == demand
    assert info["ceiling"]["low"]["value"] == pytest.approx(min(ceilings))
    assert info["ceiling"]["high"]["value"] == pytest.approx(max(ceilings))
    assert info["ceiling"]["nominal"]["unit"] == "m/s"
    assert "formula" in info["ceiling"]


def test_a_law_that_falls_where_the_ceiling_is_far_above_the_demand_is_the_laws_fall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = 0.75
    ranges = {"motor_no_load_speed": 0.3, "wheel_radius": 0.005}
    monkeypatch.setattr(dynamic, "DEMAND_SPEED", 0.4)
    assert min(_ceilings(ranges, limit)) > 2 * dynamic.DEMAND_SPEED
    record = _record(
        tmp_path, [HEADLINE, _speed_at_least(1.0)], _falling_controller(), version=2, ranges=ranges
    )
    info = _rows(record)[dynamic.STEADY_SPEED]["linear_run"]
    assert info["fell"]["by_ceiling"] == {
        "below_demand": 0,
        "at_or_above_demand": info["fell"]["before_push"],
    }
    assert info["fell"]["before_push"] == 4


# ── M4: the peak between updates ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("period", [0.001, 0.0073, 0.01, 0.05, 0.2, 1.0])
def test_the_output_points_are_never_further_apart_than_the_stated_spacing(period: float) -> None:
    tm = dynamic.timing(period, 0.0, 0.0)
    gaps = np.diff(tm.offsets)
    assert gaps.max() <= dynamic.OUTPUT_SPACING * (1.0 + 1e-9)
    assert tm.offsets[0] == 0.0
    assert tm.offsets[-1] == pytest.approx(period)
    assert dynamic.output_points(period) * dynamic.OUTPUT_SPACING >= period * (1.0 - 1e-9)


def test_the_spacing_the_run_used_is_in_the_record(stable: Any) -> None:
    block = stable["dynamic_linear"]
    assert block["output_spacing"] == {"value": dynamic.OUTPUT_SPACING, "unit": "s"}
    assert block["realised"]["output_spacing"]["unit"] == "s"
    assert block["realised"]["output_spacing"]["value"] <= dynamic.OUTPUT_SPACING


def _fine(monkeypatch: pytest.MonkeyPatch, step: float) -> None:
    """The run's own cuts, with output points added at the given step."""
    original = dynamic.timing

    def fine(period: float, sensor: float, compute: float) -> Any:
        base = original(period, sensor, compute)
        raw = sorted({*base.offsets, *(j * step for j in range(1, round(period / step)))})
        offsets = tuple(raw)

        def at(x: float) -> int:
            return min(range(len(offsets)), key=lambda i: abs(offsets[i] - x))

        return dynamic.Timing(
            offsets=offsets,
            apply_cut=at(base.offsets[base.apply_cut]) if base.apply_cut else 0,
            snapshot_cut=None if base.snapshot_cut is None else at(base.offsets[base.snapshot_cut]),
            compute_periods=base.compute_periods,
            sensor_periods=base.sensor_periods,
        )

    monkeypatch.setattr(dynamic, "timing", fine)


def _slow_period_peak() -> float:
    values = nominal(_plant())
    legacy = helpers._si(helpers._feedback(), values["wheel_radius"])
    # the good state feedback with its angle gain at 0.7, at a period of 50 ms with no delay: a
    # peak between two updates that a coarse sampling reads low by about 2e-3
    legacy = dataclasses.replace(legacy, period=0.05, sensor_delay=0.0, compute_delay=0.0)
    gains = dynamic.named_values([legacy], [values["wheel_radius"]])
    gains["angle_gain"] = gains["angle_gain"] * 0.7
    plan = dynamic.Plan(
        law=dynamic.compile_law(dynamic.named_as_law(legacy), gains, 0.05),
        period=0.05,
        sensor_delay=0.0,
        compute_delay=0.0,
        command_limit=UNLIMITED,
        full_scale=EXACT_COUNTS,
        points=(values,),
    )
    result = dynamic.run(plan)
    assert not result.fell_before[0]
    return float(result.peak[:, 0].max())


def test_at_a_50_ms_period_the_peak_is_low_by_at_most_the_spacing_s_bound_against_a_fine_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Between two output points h apart, a smooth tilt with a peak at t* (where its rate is 0)
    # is below the peak by at most (h**2 / 8) * max|tilt acceleration|: the sampled peak is low by
    # at most that. The acceleration is the plant's own, A·x + B·u, at each point of the fine run.
    reported = _slow_period_peak()
    _fine(monkeypatch, 0.05 / 64)
    seen: list[tuple[Any, Any]] = []
    freeze = dynamic._Sim._freeze

    def watched(self: Any, track_peak: bool, at: float) -> None:
        freeze(self, track_peak, at)
        if track_peak:
            seen.append((self.x.copy(), self.active.copy()))

    monkeypatch.setattr(dynamic._Sim, "_freeze", watched)
    fine = _slow_period_peak()
    a, b = continuous(nominal(_plant()))
    acceleration = max(float(np.abs(x @ a[1] + u * b[1, 0]).max()) for x, u in seen)
    spacing = 0.05 / dynamic.output_points(0.05)
    assert spacing <= dynamic.OUTPUT_SPACING
    bound = math.degrees(spacing**2 / 8 * acceleration)
    assert 0 < fine - reported <= bound, (fine - reported, bound)
    assert reported <= fine * (1.0 + 1e-9)


def test_the_push_row_says_how_low_a_sampled_peak_can_be_read(stable: Any) -> None:
    meaning = _rows(stable)[dynamic.PUSH_PEAK_TILT]["linear_run"]["peak_meaning"]
    assert "the output spacing squared over 8 times the largest tilt acceleration" in meaning


# ── lows ─────────────────────────────────────────────────────────────────────────────────────


def _big_law(lines: int, terms: int) -> law_module.Body:
    body = []
    for i in range(lines):
        body.append(
            {
                "name": f"l{i}",
                "unit": "1",
                "terms": [
                    {"sign": 1, "coefficients": [], "per": [], "of": "tilt"} for _ in range(terms)
                ],
            }
        )
    memory = [{"name": f"m{j}", "unit": "1", "next": f"l{j}"} for j in range(3)]
    return law_module.Body.model_validate(
        {"memory": memory, "lines": body, "command": f"l{lines - 1}"}, strict=False
    )


def test_the_work_counts_the_size_of_the_law_so_a_large_law_cannot_hide_in_the_bound() -> None:
    big = _big_law(32, 16)
    assert dynamic.law_size(big) == 32 * 16 + 32
    small = _big_law(2, 2)
    assert dynamic.law_size(small) == 2 * 2 + 2
    states = 4 + 1 + 3
    period = 0.0015
    assert dynamic.work(1025, period, states, dynamic.law_size(big)) > dynamic.MAX_DYNAMIC_WORK
    assert dynamic.work(1025, period, states, dynamic.law_size(small)) < dynamic.MAX_DYNAMIC_WORK
    assert dynamic.work(1025, period, states, 100) > dynamic.work(1025, period, states, 10)
    assert dynamic.work(2050, period, states, 10) == 2 * dynamic.work(1025, period, states, 10)


def test_the_work_counts_the_set_up_s_exponentials_so_a_long_period_cannot_hide_its_cost() -> None:
    # one exponential of a period's cut costs about 30 us on a laptop, over 10,000 units of the
    # bound's 2.6 ns; at a period of 1 s each of the 1,025 points takes one per cut and run
    exponentials = dynamic.RUNS * 1025 * (dynamic.output_points(1.0) + 2)
    assert dynamic.work(1025, 1.0, 8, 10) >= exponentials * 10_000
    assert dynamic.work(1025, 1.0, 8, 10) < dynamic.MAX_DYNAMIC_WORK


def test_the_timeline_puts_the_hold_window_just_before_the_push_whatever_the_constants() -> None:
    u = dynamic.updates(0.01)
    assert u.push == round(dynamic.PUSH_TIME / 0.01)
    assert u.push - u.window_first == round(dynamic.HOLD_LENGTH / 0.01)
    assert u.observed == round(dynamic.OBSERVE / 0.01)
    per_run = u.push + len(dynamic.PUSH_BAND) * u.observed
    cuts = dynamic.SEGMENT_WEIGHT * (dynamic.output_points(0.01) + 2)
    assert dynamic.work(1025, 0.01, 10, 6) == dynamic.RUNS * 1025 * per_run * (10 + 6 + cuts)


def test_the_push_is_at_the_first_update_at_or_after_its_time_and_the_record_says_when() -> None:
    assert dynamic.updates(0.01).push * 0.01 == pytest.approx(20.0)
    assert dynamic.updates(0.007).push * 0.007 == pytest.approx(20.006)
    realised = dynamic.realised_times(0.007)
    assert realised["push_time"] == pytest.approx(2858 * 0.007)
    assert realised["speed_average"] == pytest.approx(round(0.5 / 0.007) * 0.007)
    assert dynamic.realised_times(0.7)["speed_average"] == pytest.approx(0.7)


def test_the_record_gives_the_realised_push_time_and_averaging_length(stable: Any) -> None:
    realised = stable["dynamic_linear"]["realised"]
    assert realised["push_time"] == {"value": pytest.approx(20.0), "unit": "s"}
    assert realised["speed_average"] == {"value": pytest.approx(0.5), "unit": "s"}


def test_a_row_of_a_refused_law_carries_its_label_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Any, record: Any, read: Any) -> Any:
        raise law_module.LawRefused("malformed", "the scorer cannot take it")

    monkeypatch.setattr(WholeDesignScenario, "_judged", refuse)
    record = _record(tmp_path, [HEADLINE, SPEED, PUSH], helpers._recorded_controller())
    rows = _rows(record)
    # The key is asserted present before it is read: a row without it fails here, not on a lookup.
    for name in (dynamic.STEADY_SPEED, dynamic.PUSH_PEAK_TILT):
        assert "label" in rows[name], f"the refused row {name!r} carries no label"
        assert rows[name]["label"] == dynamic.LABEL
    assert "label" not in rows["rate"]


def test_a_term_with_no_variable_the_scorer_can_read_is_refused_not_asserted() -> None:
    class Term:
        of = None

    with pytest.raises(law_module.LawRefused):
        dynamic._variable(Term())

    class Odd:
        of = "not a variable at all"

    with pytest.raises(law_module.LawRefused):
        dynamic._variable(Odd())


def test_no_source_of_the_linear_run_names_a_role_where_a_reason_belongs() -> None:
    root = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole"
    for name in ("dynamic.py", "scenario.py"):
        assert "owner" not in (root / name).read_text().lower()


# ── the bound itself, and the window's arithmetic ────────────────────────────────────────────


def test_a_tilt_is_a_fall_past_seventy_degrees_and_a_state_that_is_not_a_number_is_a_fall() -> None:
    plan = _plan(nominal(_plant()))
    sim = _sim(plan)
    lanes = 4
    sim.lanes = lanes
    sim.fell = np.zeros(lanes, dtype=bool)
    sim.frozen = np.zeros((lanes, 4))
    sim.peak = np.zeros(lanes)
    sim.fell_at = np.full(lanes, np.nan)
    sim.x = np.zeros((lanes, 4))
    sim.x[:, 0] = [math.radians(69.9), math.radians(70.1), math.nan, -math.radians(70.1)]
    sim._freeze(False, 1.0)
    assert list(sim.fell) == [False, True, True, True]
    assert list(np.isnan(sim.fell_at)) == [True, False, False, False]
    assert (sim.fell_at[1:] == 1.0).all()
    assert abs(sim.x[1, 0]) == pytest.approx(math.radians(70.1))  # frozen where it passed
    assert math.radians(70.0) == dynamic.FELL_TILT


@pytest.mark.parametrize("period", [0.001, 0.007, 0.01, 0.0125, 0.3])
def test_the_hold_window_the_push_and_the_average_are_where_the_arithmetic_says(
    period: float,
) -> None:
    u = dynamic.updates(period)
    # the last update before the push is before the push time, the push update is not
    assert (u.push - 1) * period < dynamic.PUSH_TIME <= u.push * period * (1 + 1e-9)
    assert (u.window_first - 1) * period < dynamic.PUSH_TIME - dynamic.HOLD_LENGTH
    assert u.window_first * period >= (dynamic.PUSH_TIME - dynamic.HOLD_LENGTH) * (1 - 1e-9)
    assert u.observed * period >= dynamic.OBSERVE * (1 - 1e-9) > (u.observed - 1) * period
    # a sliding mean of this many updates
    series = np.arange(u.push - u.window_first, dtype=float)
    speeds = {u.window_first + i: np.array([v]) for i, v in enumerate(series)}
    window = list(range(u.window_first, u.push))
    lowest, _ = dynamic._window_numbers(speeds, window, period, 1)
    n = max(1, min(round(dynamic.SPEED_AVERAGE / period), len(window)))
    assert lowest[0] == pytest.approx(series[:n].mean(), abs=1e-9)
