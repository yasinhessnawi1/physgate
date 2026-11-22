"""The linear time run steps the loop the margins judge, in time, and reads its numbers off it.

The agreement rows are the proof that the two models are one: for a small kick, no saturation and
no reference, the plant as the law reads it (the state ``sensor_delay`` earlier) is the margins'
closed loop's own sample, so the time response matches the closed loop's state recursion, whatever
the two delays (fractions of a period, longer than one, none), for a law and for each version 2
named structure through its conversion. The rest pin what the numbers mean on laws made for the
row, not on a recorded design.
"""

from __future__ import annotations

import importlib
import math
import random
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.linalg import expm

from physgate.evaluation.whole import dynamic
from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import SampledLaw, parse_answer
from physgate.evaluation.whole.convert import ScaleFactor, to_si
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal, parse_plant

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")

_ROOT = Path(__file__).resolve().parents[2]
_PLANT = parse_plant((_ROOT / "src/physgate/evaluation/whole/plant_v0.json").read_bytes())
TOLERANCE = 1e-9
#: A command limit and a full scale that neither clip nor round at the kick's size.
UNLIMITED = 1e9
EXACT_COUNTS = 1e18

#: (sensor delay, compute delay), s: fractions of a period, whole periods, none, and longer.
TIMINGS = [
    (1 / 208, 0.004),
    (0.0, 0.0),
    (0.02, 0.0073),
    (0.0048, 0.0302),
    (0.0123, 0.0),
    (0.0, 0.025),
]


@pytest.fixture(autouse=True)
def _no_demand(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The margins' loop has no reference: the agreement rows turn the demand off."""
    if "_to_1e_9" in request.node.name or "agrees_too" in request.node.name:
        monkeypatch.setattr(dynamic, "DEMAND_SPEED", 0.0)


def _points() -> list[dict[str, float]]:
    out = [nominal(_PLANT)]
    out += [c for c in corners(_PLANT, LOOP_INPUTS)][:: 1024 // 3]
    return out


def _law_controller(sensor: float, compute: float, period: float = 0.01) -> dict[str, Any]:
    c = helpers._recorded_controller()
    c["sensor_delay"] = helpers._m(sensor, "s")
    c["compute_delay"] = helpers._m(compute, "s")
    c["period"] = helpers._m(period, "s")
    return c  # type: ignore[no-any-return]


def _named(name: str, sensor: float, compute: float) -> dict[str, Any]:
    c = {
        "state_feedback": helpers._feedback,
        "incremental": lambda: helpers._incremental(0.999),
        "incremental_without_a_leak": lambda: helpers._incremental(None),
    }[name]()
    c["sensor_delay"] = helpers._m(sensor, "s")
    c["compute_delay"] = helpers._m(compute, "s")
    return c  # type: ignore[no-any-return]


def _trace(plan: dynamic.Plan, kick_at: int, kick: float, periods: int) -> dict[int, Any]:
    """The plant at each sensor-read instant (what the law reads), a small kick at ``kick_at``."""
    tm = dynamic.timing(plan.period, plan.sensor_delay, plan.compute_delay)
    radius, phis, gams = dynamic._segments(plan, tm)
    sim = dynamic._Sim(plan, radius, phis, gams, tm)
    out: dict[int, Any] = {}
    for k in range(periods):
        if k == kick_at:
            sim.x[:, 1] += kick
        sim.period(k, in_hold=False, after_push=False)
        out[k] = sim.snaps[k][0].copy()
    return out


def _agreement(
    values: dict[str, float], body: Any, coefficients: Any, margins_loop: Any, timing: Any
) -> float:
    """The worst relative difference between the time run and the margins' state recursion."""
    sensor, compute, period = timing
    plan = dynamic.Plan(
        law=dynamic.compile_law(body, coefficients, period),
        period=period,
        sensor_delay=sensor,
        compute_delay=compute,
        command_limit=UNLIMITED,
        full_scale=EXACT_COUNTS,
        points=(values,),
    )
    kick_at, kick, periods = 40, 1e-3, 330
    trace = _trace(plan, kick_at, kick, periods)
    system = loop_module.system(values, margins_loop)
    closed = loop_module.closed(system, 1.0)
    whole, fraction = divmod(sensor, period)
    whole = int(whole)
    if fraction < 1e-12 * period:
        fraction = 0.0
    a, _ = loop_module.continuous(values)
    if fraction > 0.0:
        first = kick_at + whole + 1
        # the kick reaches the margins' time axis ``sensor`` later, between two of its samples
        w = expm(a * (first * period - (kick_at * period + sensor)))[:, 1] * kick
        offset = whole + 1
    else:
        first = kick_at + whole
        w = np.array([0.0, kick, 0.0, 0.0])
        offset = whole
    z = np.zeros(closed.shape[0])
    z[:4] = w
    worst = 0.0
    scale = np.zeros(4)
    got = []
    for j in range(first, first + 250):
        got.append((z[:4].copy(), trace[j - offset]))
        z = closed @ z
    for _, phys in got:
        scale = np.maximum(scale, np.abs(phys))
    for margins_state, phys in got:
        worst = max(worst, float(np.max(np.abs(margins_state - phys) / scale)))
    return worst


@pytest.mark.parametrize(("sensor", "compute"), TIMINGS)
def test_a_law_s_time_response_is_the_margins_closed_loop_to_1e_9(
    sensor: float, compute: float
) -> None:
    controller = _law_controller(sensor, compute)
    answer = parse_answer(helpers._answer(controller, 3))
    law = answer.controller
    assert isinstance(law, SampledLaw)
    coefficients = {n: float(m.value) for n, m in law.coefficients.items()}
    judged = 0
    for values in _points():
        radius = ScaleFactor("wheel_radius", values["wheel_radius"], "m", "this plant")
        margins_loop = to_si(law, answer.parameters, wheel_radius=radius)
        if not loop_module.margins(values, margins_loop).stable:
            continue
        judged += 1
        assert _agreement(values, law, coefficients, margins_loop, (sensor, compute, 0.01)) < (
            TOLERANCE
        )
    assert judged >= 1, "no plant point is stable: the row proves nothing"


def test_a_law_at_another_period_agrees_too() -> None:
    controller = _law_controller(0.0031, 0.0105, period=0.007)
    answer = parse_answer(helpers._answer(controller, 3))
    law = answer.controller
    assert isinstance(law, SampledLaw)
    values = nominal(_PLANT)
    radius = ScaleFactor("wheel_radius", values["wheel_radius"], "m", "this plant")
    margins_loop = to_si(law, answer.parameters, wheel_radius=radius)
    assert loop_module.margins(values, margins_loop).stable
    coefficients = {n: float(m.value) for n, m in law.coefficients.items()}
    assert _agreement(values, law, coefficients, margins_loop, (0.0031, 0.0105, 0.007)) < TOLERANCE


@pytest.mark.parametrize("name", ["state_feedback", "incremental", "incremental_without_a_leak"])
@pytest.mark.parametrize(
    ("sensor", "compute"), [TIMINGS[0], TIMINGS[1], TIMINGS[4], (0.0061, 0.0123)]
)
def test_a_named_structure_through_its_conversion_is_the_margins_loop_to_1e_9(
    name: str, sensor: float, compute: float
) -> None:
    judged = 0
    for values in _points():
        radius = values["wheel_radius"]
        legacy = helpers._si(_named(name, sensor, compute), radius)
        if not loop_module.margins(values, legacy).stable:
            continue
        judged += 1
        body = dynamic.named_as_law(legacy)
        coefficients = dynamic.named_values([legacy], [radius])
        assert _agreement(values, body, coefficients, legacy, (sensor, compute, 0.01)) < TOLERANCE
    assert judged >= 1


# ── what the stepper does to a command, a law's lines, a push ───────────────────────────────


def test_the_command_is_held_and_rounded_exactly_as_the_law_s_counts() -> None:
    rng = random.Random(7)
    duties = [rng.uniform(-2.0, 2.0) for _ in range(2000)]
    duties += [k / 800 for k in range(-900, 900, 7)]  # ties at half a count of 400
    for limit, full_scale in ((0.9425, 400.0), (0.75, 255.0), (1.0, 400.0)):
        got = dynamic.counts_of(np.array(duties), limit, full_scale)
        for duty, count in zip(duties, got, strict=True):
            assert count == law_module.counts(duty, limit, full_scale)


def test_the_compiled_lines_are_bitwise_the_lines_evaluated() -> None:
    answer = parse_answer(helpers._answer(helpers._recorded_controller(), 3))
    law = answer.controller
    assert isinstance(law, SampledLaw)
    values = {n: float(m.value) for n, m in law.coefficients.items()}
    compiled = dynamic.compile_law(law, values, 0.01)
    rng = random.Random(3)
    for _ in range(200):
        state = {m.name: rng.uniform(-1, 1) for m in law.memory}
        signals = {n: rng.uniform(-2, 2) for n in law_module.SIGNALS}
        duty, following = dynamic.update(compiled, state, signals)
        expected, expected_next = law_module.evaluate(
            law, values, period=0.01, state=state, signals=signals
        )
        assert duty == expected
        assert following == expected_next


def test_a_push_changes_the_tilt_rate_by_the_step_and_nothing_else() -> None:
    values = nominal(_PLANT)
    legacy = helpers._si(helpers._feedback(), values["wheel_radius"])
    plan = dynamic.Plan(
        law=dynamic.compile_law(
            dynamic.named_as_law(legacy), dynamic.named_values([legacy], [0.04]), 0.01
        ),
        period=0.01,
        sensor_delay=0.0,
        compute_delay=0.0,
        command_limit=UNLIMITED,
        full_scale=EXACT_COUNTS,
        points=(values,),
    )
    tm = dynamic.timing(0.01, 0.0, 0.0)
    radius, phis, gams = dynamic._segments(plan, tm)
    sim = dynamic._Sim(plan, radius, phis, gams, tm)
    for k in range(5):
        sim.period(k, in_hold=False, after_push=False)
    before = sim.x.copy()
    sim.branch(3, np.repeat([1.0, 2.0, 3.0], 1))
    for branch in range(3):
        assert sim.x[branch, 1] - before[0, 1] == pytest.approx(branch + 1.0, abs=1e-15)
        for column in (0, 2, 3):
            assert sim.x[branch, column] == before[0, column]


def test_the_period_is_cut_at_the_instants_the_delays_name() -> None:
    tm = dynamic.timing(0.01, 0.0048, 0.002)
    assert tm.compute_periods == 0
    assert tm.sensor_periods == 0
    assert tm.offsets[tm.apply_cut] == pytest.approx(0.002)
    assert tm.snapshot_cut is not None
    assert tm.offsets[tm.snapshot_cut] == pytest.approx(0.0052)
    assert tm.offsets[0] == 0.0
    assert tm.offsets[-1] == pytest.approx(0.01)
    whole = dynamic.timing(0.01, 0.02, 0.03)
    assert (whole.sensor_periods, whole.compute_periods) == (2, 3)
    assert whole.snapshot_cut is None
    assert whole.apply_cut == 0


def test_the_reference_stands_ramps_at_the_acceleration_and_then_holds_the_demand() -> None:
    ramp = dynamic.DEMAND_SPEED / dynamic.RAMP_ACCELERATION
    start = dynamic.REST_TIME
    assert dynamic.reference_position(start) == 0.0
    assert dynamic.reference_position(start + 0.5) == pytest.approx(
        0.5 * dynamic.RAMP_ACCELERATION * 0.25
    )
    end = dynamic.reference_position(start + ramp)
    assert end == pytest.approx(0.5 * dynamic.DEMAND_SPEED * ramp)
    assert dynamic.reference_position(start + ramp + 10.0) - end == pytest.approx(
        10.0 * dynamic.DEMAND_SPEED
    )


def test_the_number_is_the_lowest_sliding_mean_and_the_settled_figure_is_a_difference() -> None:
    period = 0.01
    u = dynamic.updates(period)
    window = list(range(u.window_first, u.push))
    assert len(window) == round(dynamic.HOLD_LENGTH / period)
    series = np.full(len(window), 1.30)
    n = round(dynamic.SPEED_AVERAGE / period)
    series[100 : 100 + n] = 1.10  # a dip as long as the averaging window
    series[30:32] = 0.0  # a dip shorter than the window
    speeds = {i: np.array([series[j]]) for j, i in enumerate(window)}
    lowest, settled = dynamic._window_numbers(speeds, window, period, 1)
    expected = min(series[s : s + n].mean() for s in range(len(series) - n + 1))
    assert lowest[0] == pytest.approx(expected, abs=1e-12)
    assert lowest[0] == pytest.approx(1.10, abs=1e-12)
    half = len(window) // 2
    assert settled[0] == pytest.approx(series[-half:].mean() - series[:half].mean(), abs=1e-12)


def test_the_timeline_puts_the_hold_window_just_before_the_push() -> None:
    u = dynamic.updates(0.01)
    assert u.push == 2000
    assert u.window_first == 1800
    assert u.observed == 400
    assert dynamic.work(1025, 0.01, 10) == 1025 * (2000 + 3 * 400) * 10


# ── numbers on laws made for the row ─────────────────────────────────────────────────────────


def _stepped(limit: float, controller: dict[str, Any] | None = None, **tweak: float) -> Any:
    values = nominal(_PLANT)
    legacy = helpers._si(controller or helpers._feedback(), values["wheel_radius"])
    coefficients = dynamic.named_values([legacy], [values["wheel_radius"]])
    for key, factor in tweak.items():
        coefficients[key] = coefficients[key] * factor
    plan = dynamic.Plan(
        law=dynamic.compile_law(dynamic.named_as_law(legacy), coefficients, legacy.period),
        period=legacy.period,
        sensor_delay=legacy.sensor_delay,
        compute_delay=legacy.compute_delay,
        command_limit=limit,
        full_scale=400.0,
        points=(values,),
    )
    return dynamic.run(plan)


def test_a_stable_law_reaches_the_speed_the_reference_advances_at() -> None:
    result = _stepped(UNLIMITED)
    assert not result.fell_before[0]
    assert result.speed[0] == pytest.approx(dynamic.DEMAND_SPEED, rel=1e-2)
    assert abs(result.settled[0]) < 1e-3
    assert result.saturated_hold[0] == 0


def test_a_command_limit_below_what_the_reference_needs_is_counted_and_not_hidden() -> None:
    result = _stepped(0.75)
    # the demand is past what 0.75 of the pack can drive the wheels at: the limit is reached
    assert result.saturated_hold[0] > 0


def test_a_law_that_falls_has_no_speed_and_no_peak() -> None:
    result = _stepped(UNLIMITED, angle_gain=-1.0)
    assert result.fell_before[0]
    assert math.isnan(result.speed[0])
    assert np.isnan(result.peak[:, 0]).all()


def test_the_push_branches_are_the_band_and_the_peak_grows_with_the_push() -> None:
    result = _stepped(UNLIMITED)
    low, mid, high = (float(p) for p in result.peak[:, 0])
    assert low < mid < high
    assert dynamic.PUSH_BAND == (-0.05, 0.0, 0.05)
    # the response is linear below the limit: the peak is the push's size times a constant
    # beside the cruise's own tilt, so the three peaks are in the ratio of the pushes' sizes
    assert (high - low) / (mid - low) == pytest.approx(2.0, rel=0.05)


def test_a_tilt_past_seventy_degrees_is_a_fall_and_stays_a_number_past_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dynamic, "PUSH_RATE", 100.0)
    result = _stepped(UNLIMITED)
    assert result.fell_after[:, 0].all()
    assert (result.peak[:, 0] > 70.0).all()
    assert not result.fell_before[0]


def test_the_push_is_added_forward_at_the_brief_s_size_in_each_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []
    original = dynamic._Sim.branch

    def spy(self: Any, n: int, kick: Any) -> None:
        seen.append((n, np.array(kick)))
        original(self, n, kick)

    monkeypatch.setattr(dynamic._Sim, "branch", spy)
    _stepped(UNLIMITED)
    ((n, kick),) = seen
    assert n == 3
    assert list(kick) == [dynamic.PUSH_RATE * (1.0 + b) for b in dynamic.PUSH_BAND]
    assert kick[0] == pytest.approx(1.425)
    assert kick[1] == pytest.approx(1.5)
    assert kick[2] == pytest.approx(1.575)


def test_a_limit_that_is_reached_changes_the_run_and_the_applied_memory_holds_the_limit() -> None:
    free = _stepped(UNLIMITED)
    held = _stepped(0.75)
    assert math.isnan(held.speed[0]) or abs(held.speed[0] - free.speed[0]) > 1e-3
    values = nominal(_PLANT)
    legacy = helpers._si(helpers._incremental(0.999), values["wheel_radius"])
    plan = dynamic.Plan(
        law=dynamic.compile_law(
            dynamic.named_as_law(legacy),
            dynamic.named_values([legacy], [values["wheel_radius"]]),
            0.01,
        ),
        period=0.01,
        sensor_delay=0.0,
        compute_delay=0.0,
        command_limit=0.5,
        full_scale=400.0,
        points=(values,),
    )
    tm = dynamic.timing(0.01, 0.0, 0.0)
    radius, phis, gams = dynamic._segments(plan, tm)
    sim = dynamic._Sim(plan, radius, phis, gams, tm)
    sim.x[:, 1] = 500.0  # a rate the law answers with far more than half the pack
    sim.period(0, in_hold=False, after_push=False)
    assert abs(sim.memory["applied"][0]) == pytest.approx(0.5)


def test_a_lane_that_falls_is_frozen_where_it_passed_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dynamic, "PUSH_RATE", 100.0)
    result = _stepped(UNLIMITED)
    assert (result.peak[:, 0] < 120.0).all()


def test_a_named_structure_at_the_reference_s_own_pace_has_no_speed_error() -> None:
    """Travelling as the reference advances, the structure's travel and speed terms are 0."""
    period, radius = 0.01, 0.04
    legacy = helpers._si(helpers._feedback(), radius)
    compiled = dynamic.compile_law(
        dynamic.named_as_law(legacy), dynamic.named_values([legacy], [radius]), period
    )
    speed = 1.1  # m/s
    angle = 3.0  # rad of wheel, wherever the wheels are
    state = {"reference": angle - speed * period / radius}
    signals = {
        "tilt": 0.0,
        "tilt_rate": 0.0,
        "wheel_angle": angle,
        "wheel_speed": speed / radius,
        "wheel_reference": angle,
    }
    duty, _ = dynamic.update(compiled, state, signals)
    assert duty == pytest.approx(0.0, abs=1e-12)
    # a wheel angle off the reference's is the distance gain's, in rad of wheel
    signals["wheel_angle"] = angle + 0.5
    duty, _ = dynamic.update(compiled, state, signals)
    assert duty == pytest.approx(0.5 * legacy.distance * radius, rel=1e-9)


def test_the_period_is_output_at_equal_points_between_the_updates() -> None:
    tm = dynamic.timing(0.01, 0.0, 0.0)
    assert len(tm.offsets) == dynamic.OUTPUT_PER_PERIOD + 1
    assert tm.offsets[1] == pytest.approx(0.0025)
