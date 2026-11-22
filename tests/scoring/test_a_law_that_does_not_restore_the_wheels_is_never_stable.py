"""A sampled law is stable only if the wheels, displaced alone, are restored.

A mode held at exactly 1 is set aside only where it carries no weight on the plant's travel:
displace the wheels alone and the loop settles where it started. A law whose memory merely
follows the wheel angle (a backward-difference speed with no position gain, a washout, a
recorded design with its position gain set to zero) holds a mode at 1 that is the travel
itself: displace the wheels and it settles somewhere else. It is unstable, however the memory
is written. The leak-free incremental form's offset (the angle estimate against the travel it
settles to) carries no weight on the travel and is set aside, as the named structure sets it
aside; the numbers below are the two cases' left eigenvectors' weight on the travel state, the
reviewer's own discriminator, beside the exact rule that decides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy import linalg

from physgate.evaluation.whole import loop as loop_module
from physgate.evaluation.whole.answer import parse_answer
from physgate.evaluation.whole.convert import ScaleFactor, SiLoop, to_si
from physgate.evaluation.whole.plant import LOOP_INPUTS, corners, nominal, parse_plant

_ROOT = Path(__file__).resolve().parents[2]
_DRAFT = _ROOT / "src/physgate/evaluation/whole/plant_v0_draft.json"
_RECORDED = _ROOT / "tests/unit/evaluation/whole/recorded_law/law.json"
GOOD_GAINS = (1.6643, 0.191, 0.2853, 1.3421)


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _timing() -> dict[str, Any]:
    return {
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.004, "s"),
    }


SETTINGS = {
    "update_rate": _m(100, "Hz"),
    "output_data_rate": _m(208, "Hz"),
    "gyro_full_scale": _m(1000, "deg/s"),
    "pwm_frequency": _m(20000, "Hz"),
    "pwm_full_scale": _m(400, "count"),
    "encoder_counts_per_wheel_revolution": _m(1322.9, "count"),
}


def _plant() -> Any:
    doc = json.loads(_DRAFT.read_text())
    for p in doc["parameters"].values():
        p.pop("bounded", None)
        p["low"] = p["high"] = p["value"]
    for name in ("wheel_radius", "com_height", "body_inertia", "motor_no_load_current"):
        p = doc["parameters"][name]
        if name == "wheel_radius":
            p["low"], p["high"] = 0.039, 0.041
        else:
            p["low"], p["high"] = p["value"] * 0.5, p["value"] * 1.5
    return parse_plant(json.dumps(doc).encode())


def _loop(controller: dict[str, Any], values: dict[str, float]) -> SiLoop:
    raw = json.dumps(
        {"form": "whole_run", "version": 3, "controller": controller, "parameters": SETTINGS}
    ).encode()
    answer = parse_answer(raw)
    radius = ScaleFactor("wheel_radius", values["wheel_radius"], "m", "this test's plant")
    return to_si(answer.controller, answer.parameters, wheel_radius=radius)


def _good(radius: float) -> dict[str, Any]:
    return {
        "angle_gain": _m(GOOD_GAINS[0], "1/rad"),
        "rate_gain": _m(GOOD_GAINS[1], "s/rad"),
        "distance_gain": _m(GOOD_GAINS[2] * radius, "1/rad"),
        "speed_gain": _m(GOOD_GAINS[3] * radius, "s/rad"),
    }


def _law(
    terms: list[dict[str, Any]],
    coefficients: dict[str, Any],
    memory: list[dict[str, Any]] | None = None,
    lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "structure": "sampled_law",
        **_timing(),
        "coefficients": coefficients,
        "memory": memory or [],
        "lines": [*(lines or []), {"name": "command", "unit": "1", "terms": terms}],
        "command": "command",
    }


def _no_position() -> list[dict[str, Any]]:
    """The good gains on the tilt, its rate and the wheel speed, and nothing on the wheel angle."""
    return [
        {"sign": 1, "coefficients": ["angle_gain"], "of": "tilt"},
        {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
        {"sign": 1, "coefficients": ["speed_gain"], "of": "wheel_speed"},
    ]


def _backward_difference(radius: float) -> dict[str, Any]:
    """A speed from the encoder's backward difference, and no position gain."""
    coefficients = {**_good(radius), "slope": _m(0.05, "1/rad")}
    return _law(
        [
            *_no_position(),
            {"sign": 1, "coefficients": ["slope"], "of": "wheel_angle"},
            {"sign": -1, "coefficients": ["slope"], "of": "previous.last"},
        ],
        coefficients,
        [{"name": "last", "unit": "rad", "next": "last_now"}],
        [{"name": "last_now", "unit": "rad", "terms": [{"sign": 1, "of": "wheel_angle"}]}],
    )


def _washout(radius: float, keep: float, take: float) -> dict[str, Any]:
    """``z' = keep·z + take·wheel_angle``, the command reading ``wheel_angle - z``."""
    coefficients = {
        **_good(radius),
        "keep": _m(keep, "1"),
        "take": _m(take, "1"),
        "slope": _m(0.02, "1/rad"),
    }
    return _law(
        [
            *_no_position(),
            {"sign": 1, "coefficients": ["slope"], "of": "wheel_angle"},
            {"sign": -1, "coefficients": ["slope"], "of": "previous.z"},
        ],
        coefficients,
        [{"name": "z", "unit": "rad", "next": "z_now"}],
        [
            {
                "name": "z_now",
                "unit": "rad",
                "terms": [
                    {"sign": 1, "coefficients": ["keep"], "of": "previous.z"},
                    {"sign": 1, "coefficients": ["take"], "of": "wheel_angle"},
                ],
            }
        ],
    )


def _recorded(k_phi: float) -> dict[str, Any]:
    body = json.loads(_RECORDED.read_text())
    coefficients = {
        "k_phi": _m(k_phi, "1/rad"),
        "k_theta": _m(-1.03529, "1/rad"),
        "k_w": _m(-0.038326, "s/rad"),
        "k_rate": _m(-0.0625146, "s/rad"),
        "k_u": _m(-0.346975, "1"),
        "leak": _m(0.999, "1"),
    }
    return {
        "structure": "sampled_law",
        **{key: body[key] for key in ("memory", "lines", "command")},
        "coefficients": coefficients,
        **_timing(),
    }


def _leak_free_incremental(radius: float) -> dict[str, Any]:
    """The velocity form with no leak, as a law: its offset is the one legitimate held mode."""
    angle = 0.13984913700800736
    coefficients = {
        "angle_gain": _m(angle, "1/rad"),
        "rate_gain": _m(angle * 0.14, "s/rad"),
        "distance_gain": _m(0.17308404749760797 * radius, "1/rad"),
        "speed_gain": _m(0.07824347352631594 * radius, "s/rad"),
        "decay": _m(1.0, "1"),
    }
    return _law(
        [
            {"sign": 1, "of": "previous.applied"},
            {"sign": 1, "coefficients": ["angle_gain"], "of": "line.angle_now"},
            {"sign": 1, "coefficients": ["rate_gain"], "of": "tilt_rate"},
            {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"},
            {"sign": 1, "coefficients": ["speed_gain"], "of": "wheel_speed"},
        ],
        coefficients,
        [
            {"name": "angle", "unit": "rad", "next": "angle_now"},
            {"name": "applied", "unit": "1", "next": "command", "applied": True},
        ],
        [
            {
                "name": "angle_now",
                "unit": "rad",
                "terms": [
                    {"sign": 1, "coefficients": ["decay"], "of": "previous.angle"},
                    {"sign": 1, "coefficients": ["decay", "period"], "of": "tilt_rate"},
                ],
            }
        ],
    )


def _travel_weight(values: dict[str, float], loop: SiLoop) -> float:
    """The largest weight of a left eigenvector at 1 on the plant's travel state, unit norm.

    The reviewer's discriminator: displace the wheels alone, and the loop settles where this
    weight times the displacement says. Zero means the wheels return.
    """
    system = loop_module.system(values, loop)
    matrix = loop_module.closed(system, 1.0)
    eigenvalues, left = linalg.eig(matrix, left=True, right=False)
    weights = [
        float(abs(left[loop_module.TRAVEL, i]) / np.linalg.norm(left[:, i]))
        for i, e in enumerate(eigenvalues)
        if abs(e - 1.0) < 1e-6
    ]
    return max(weights, default=0.0)


def _unstable(values: dict[str, float], controller: dict[str, Any]) -> bool:
    return not loop_module.margins(values, _loop(controller, values)).stable


# ── the reviewer's laws ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "build",
    [
        lambda r: _backward_difference(r),
        lambda r: _washout(r, 0.75, 0.25),
        lambda r: _washout(r, 0.9, 0.1),
        lambda r: _recorded(0.0),
        lambda r: _recorded(1e-9),
    ],
    ids=["backward_difference", "washout_quarters", "washout_tenths", "k_phi_0", "k_phi_1e-9"],
)
def test_a_law_that_does_not_restore_the_wheels_is_unstable_at_every_point(
    build: Any,
) -> None:
    plant = _plant()
    for values in (nominal(plant), *corners(plant, LOOP_INPUTS)):
        assert _unstable(values, build(values["wheel_radius"])), values["wheel_radius"]


def test_the_wheels_are_free_in_those_laws_and_held_in_the_legitimate_one() -> None:
    """The left eigenvector's weight on the travel: 0.03 to 0.8 where free, 1e-13 where held."""
    plant = _plant()
    values = nominal(plant)
    radius = values["wheel_radius"]
    free = [
        _backward_difference(radius),
        _washout(radius, 0.75, 0.25),
        _washout(radius, 0.9, 0.1),
        _recorded(0.0),
    ]
    for controller in free:
        assert _travel_weight(values, _loop(controller, values)) > 1e-3
    assert _travel_weight(values, _loop(_leak_free_incremental(radius), values)) < 1e-9


def test_the_leak_free_form_s_offset_is_still_set_aside_and_the_loop_is_stable() -> None:
    values = nominal(_plant())
    controller = _leak_free_incremental(values["wheel_radius"])
    loop = _loop(controller, values)
    assert loop_module.system(values, loop).held is not None
    assert loop_module.margins(values, loop).stable


def test_the_recorded_design_with_its_position_gain_is_stable_and_without_it_is_not() -> None:
    values = nominal(_plant())
    assert loop_module.margins(values, _loop(_recorded(-0.0054505), values)).stable
    assert _unstable(values, _recorded(0.0))
    assert _unstable(values, _recorded(1e-9))  # the wrong sign: it pushes the wheels away


def test_no_position_gain_of_the_wrong_sign_or_none_gets_margins() -> None:
    """Zero and any size of the wrong sign are unstable alike: no margins for holding no position.

    The right sign, however small, restores the wheels, slowly: at 1e-9 the radius is 1 - 1e-9,
    inside the stability margin, and the loop is judged on its poles like any other.
    """
    values = nominal(_plant())
    for gain in (0.0, 1e-12, 1e-9, 1e-6, 1e-3):
        assert _unstable(values, _recorded(gain)), gain
    assert not _unstable(values, _recorded(-1e-9))


def test_a_named_state_feedback_with_no_distance_gain_and_the_same_design_as_a_law_agree() -> None:
    values = nominal(_plant())
    radius = values["wheel_radius"]
    named = {
        "structure": "state_feedback",
        **_timing(),
        "angle_gain": _m(GOOD_GAINS[0], "1/rad"),
        "rate_gain": _m(GOOD_GAINS[1], "s/rad"),
        "distance_gain": _m(0.0, "1/m"),
        "speed_gain": _m(GOOD_GAINS[3], "s/m"),
    }
    as_law = _law(_no_position(), _good(radius))
    assert _unstable(values, named)
    assert _unstable(values, as_law)
    # With a distance gain they are stable together.
    named["distance_gain"] = _m(GOOD_GAINS[2], "1/m")
    restored = _law(
        [*_no_position(), {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}],
        _good(radius),
    )
    assert not _unstable(values, named)
    assert not _unstable(values, restored)


def test_the_steady_cruise_of_the_plant_has_no_tilt_so_a_tilt_fed_state_is_no_free_travel() -> None:
    """The premise of the exact rule: the motor force is one combination of command and speed.

    At a steady cruise (no acceleration) the body is upright and the tilt rate is zero, whatever
    the plant's parameters; only the wheel speed is not zero. So a memory state that
    integrates the tilt or its rate is settled by the loop whatever the wheels do first, and one
    that integrates the wheel speed or angle is not.
    """
    plant = _plant()
    for values in (nominal(plant), *corners(plant, LOOP_INPUTS)):
        a, b = loop_module.continuous(values)
        # unknowns (theta, v) at constant command 1: rows theta-dot-dot and v-dot are zero
        system = np.array([[a[1, 0], a[1, 3]], [a[3, 0], a[3, 3]]])
        theta, speed = np.linalg.solve(system, -np.array([b[1, 0], b[3, 0]]))
        assert abs(theta) <= 1e-9 * max(1.0, abs(speed))
        assert abs(speed) > 1e-6


def _split_pole(radius: float, first: float, second: float) -> dict[str, Any]:
    """A law that holds the wheels, plus an unread state ``z' = first·z + second·z``."""
    coefficients = {**_good(radius), "first": _m(first, "1"), "second": _m(second, "1")}
    return _law(
        [*_no_position(), {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"}],
        coefficients,
        [{"name": "z", "unit": "1", "next": "z_now"}],
        [
            {
                "name": "z_now",
                "unit": "1",
                "terms": [
                    {"sign": 1, "coefficients": ["first"], "of": "previous.z"},
                    {"sign": 1, "coefficients": ["second"], "of": "previous.z"},
                ],
            }
        ],
    )


@pytest.mark.parametrize(
    ("first", "second"), [(0.75, 0.25), (0.9, 0.1), (0.6, 0.4), (0.7, 0.3), (0.3, 0.7), (0.2, 0.8)]
)
def test_a_state_held_at_1_by_two_decimals_is_judged_alike_whatever_the_decimals(
    first: float, second: float
) -> None:
    """0.9 and 0.1 are tenths: their sum is 1 as 0.75 and 0.25 are, though not in binary."""
    values = nominal(_plant())
    radius = values["wheel_radius"]
    base = loop_module.margins(values, _loop(_split_pole(radius, 0.75, 0.25), values))
    again = loop_module.margins(values, _loop(_split_pole(radius, first, second), values))
    assert base.stable
    assert again.stable
    assert system_held(values, _split_pole(radius, first, second)) == 1
    for field in ("phase_margin", "upward", "downward"):
        assert getattr(again, field) == pytest.approx(getattr(base, field), rel=1e-9)


def system_held(values: dict[str, float], controller: dict[str, Any]) -> int:
    held = loop_module.system(values, _loop(controller, values)).held
    return 0 if held is None else int(held.shape[1])
