"""The balance loop is judged as the firmware runs it: sampled, held, delayed, its margins exact.

Hand cases first (a first-order unstable plant whose margins are known in closed form), then
the pendulum: its discretisation against a fine simulation with the delay as a time, the
incremental controller's matrices against the firmware's own update stepped in time, and the
cross-check against the continuous control scorer at the tolerance frozen before it was run.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
from scipy.linalg import expm, solve_discrete_are
from whole_loop_tolerance import (
    GAIN_MARGIN_RELATIVE,
    LARGEST_OMEGA_T,
    PHASE_MARGIN_DEGREES,
)

_MODULE = "physgate.evaluation.whole.loop"
_DRAFT = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0_draft.json"
T = 0.01


def _loop() -> ModuleType:
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return importlib.import_module(_MODULE)


def _values() -> dict[str, float]:
    from physgate.evaluation.whole.plant import nominal, parse_plant

    return nominal(parse_plant(_DRAFT.read_bytes()))


def _si(**over: Any) -> Any:
    from physgate.evaluation.whole.convert import SiLoop

    base: dict[str, Any] = {
        "incremental": False,
        "angle": 0.0,
        "rate": 0.0,
        "distance": 0.0,
        "speed": 0.0,
        "decay": 1.0,
        "period": T,
        "command_limit": 0.75,
        "sensor_delay": 0.0,
        "compute_delay": 0.0,
        "factors": (),
    }
    base.update(over)
    return SiLoop(**base)


# A first-order unstable plant, dx/dt = p·x + u, held at T, under u = k·x.
P, K = 5.0, -20.0
PHI = math.exp(P * T)
GAMMA = (PHI - 1.0) / P


def _scalar(delay: float = 0.0) -> Any:
    loop = _loop()
    ap, bp, cp = loop.discretise(np.array([[P]]), np.array([[1.0]]), T, delay)
    return loop.System(
        ap=ap,
        bp=bp,
        cp=cp,
        ac=np.zeros((0, 0)),
        bc=np.zeros((0, 1)),
        cc=np.zeros((1, 0)),
        dc=np.array([[K]]),
        period=T,
    )


@pytest.mark.parametrize("fraction", [0.0, 0.3, 1.0, 1.4, 2.75])
def test_a_delay_of_any_time_is_discretised_exactly(fraction: float) -> None:
    delay = fraction * T
    ap, bp, _ = _loop().discretise(np.array([[P]]), np.array([[1.0]]), T, delay)
    whole = math.floor(fraction + 1e-12)
    delta = delay - whole * T
    gamma0 = (math.exp(P * (T - delta)) - 1.0) / P
    gamma1 = math.exp(P * (T - delta)) * (math.exp(P * delta) - 1.0) / P
    assert ap.shape == (whole + 2, whole + 2)
    assert ap[0, 0] == pytest.approx(PHI, rel=1e-12)
    if whole == 0:
        assert bp[0, 0] == pytest.approx(gamma0, rel=1e-12)
    else:
        assert bp[0, 0] == 0.0
        assert ap[0, whole] == pytest.approx(gamma0, rel=1e-12)
    assert ap[0, whole + 1] == pytest.approx(gamma1, rel=1e-12, abs=1e-15)


def test_the_hand_case_s_gain_margins_are_its_closed_form_ones() -> None:
    down, up = _loop().gain_margins(_scalar())
    assert down == pytest.approx((PHI - 1.0) / (-GAMMA * K), rel=1e-7)
    assert up == pytest.approx((PHI + 1.0) / (-GAMMA * K), rel=1e-7)
    assert down == pytest.approx(0.25, rel=1e-3)
    assert up == pytest.approx(10.0, rel=1e-3)


def test_the_hand_case_s_phase_margin_is_its_closed_form_one() -> None:
    reach = -K * GAMMA
    wt = math.acos((1.0 + PHI**2 - reach**2) / (2.0 * PHI))
    z = complex(math.cos(wt), math.sin(wt))
    angle = math.degrees(math.atan2((reach / (z - PHI)).imag, (reach / (z - PHI)).real))
    want = (angle + 180.0 + 180.0) % 360.0 - 180.0
    margin, crossed = _loop().phase_margin(_scalar())
    assert crossed
    assert margin == pytest.approx(want, abs=1e-6)


def _resonant() -> tuple[Any, Any, Any, float]:
    """A lightly damped resonance under a gain of 0.5: |L| rises above 1 near 20 rad/s only.

    Its gain crosses 1 twice, going up (phase near 0, a margin near 170°) and coming down
    (phase near -180°, a margin of a few degrees).
    """
    wn, zeta, gain = 20.0, 0.05, 0.5
    a = np.array([[0.0, 1.0], [-(wn**2), -2.0 * zeta * wn]])
    b = np.array([[0.0], [wn**2]])
    block = np.zeros((3, 3))
    block[:2, :2], block[:2, 2:] = a, b
    held = expm(block * T)
    return held[:2, :2], held[:2, 2:], np.array([[1.0, 0.0]]), gain


def test_with_two_gain_crossovers_the_phase_margin_is_the_smaller() -> None:
    ap, bp, cp, gain = _resonant()
    system = _loop().System(
        ap=ap,
        bp=bp,
        cp=cp,
        ac=np.zeros((0, 0)),
        bc=np.zeros((0, 1)),
        cc=np.zeros((1, 0)),
        dc=np.array([[-gain]]),
        period=T,
    )
    # This test's own reading of the loop L(z) = gain * C (zI - A)^-1 B on a fine grid.
    w = np.linspace(1.0, math.pi / T, 400_001)
    z = np.exp(1j * w * T)
    det = (z - ap[0, 0]) * (z - ap[1, 1]) - ap[0, 1] * ap[1, 0]
    loop_gain = gain * ((z - ap[1, 1]) * bp[0, 0] + ap[0, 1] * bp[1, 0]) / det
    above = np.abs(loop_gain) > 1.0
    at = np.nonzero(above[:-1] != above[1:])[0]
    assert at.size == 2
    # The margin at each crossover: the phase above -180°, wrapped into [-180°, 180°).
    found = [(math.degrees(float(np.angle(loop_gain[i]))) + 360.0) % 360.0 - 180.0 for i in at]
    assert max(found) - min(found) > 100.0, found
    margin, crossed = _loop().phase_margin(system)
    assert crossed
    assert margin == pytest.approx(min(found), abs=0.05)


def test_a_leaky_integrated_angle_has_no_held_offset_to_set_aside() -> None:
    # Only a leak-free angle's offset is a mode at exactly 1; a leak below 1 decays it, so the
    # loop is judged on every one of its modes.
    loop = _loop()
    for decay in (0.999, 0.9):
        assert loop.system(_light_rotor(), _kit_in_si(decay)).neutral is None, decay
    assert loop.system(_light_rotor(), _kit_in_si(1.0)).neutral is not None


def test_a_loop_unstable_as_designed_has_no_margins() -> None:
    loop = _loop()
    weak = _scalar()
    weak = loop.System(**{**weak.__dict__, "dc": np.array([[-1.0]])})
    assert not loop.stable(weak, 1.0)
    with pytest.raises(ValueError, match="unstable as designed"):
        loop.gain_margins(weak)


def test_more_delay_takes_phase_and_never_adds_it() -> None:
    loop = _loop()
    margins = [loop.phase_margin(_scalar(f * T))[0] for f in (0.0, 0.25, 0.5, 1.0)]
    assert margins == sorted(margins, reverse=True)
    assert margins[0] - margins[-1] > 1.0


def test_the_powered_plant_falls_forward_and_a_forward_command_drives_forward() -> None:
    a, b = _loop().continuous(_values())
    assert a.shape == (4, 4) and b.shape == (4, 1)
    assert a[1, 0] > 0, "a forward tilt grows"
    assert b[3, 0] > 0, "a positive duty accelerates the axle forward"
    assert b[1, 0] < 0, "and pitches the body back"
    assert _loop().unstable_pole(_values()) > 0


def _fine(a: Any, b: Any, inputs: list[float], delay: float, steps: int = 400) -> list[Any]:
    """The plant's state at each sample, integrated in fine steps with the input delayed."""
    dt = T / steps
    e = expm(np.block([[a * dt, b * dt], [np.zeros((1, 5))]]))
    phi, gamma = e[:4, :4], e[:4, 4:]
    x = np.zeros((4, 1))
    out = [x.copy()]
    for k in range(len(inputs) - 1):
        for i in range(steps):
            t = k * T + (i + 0.5) * dt - delay
            held = inputs[math.floor(t / T)] if t >= 0 else 0.0
            x = phi @ x + gamma * held
        out.append(x.copy())
    return out


@pytest.mark.parametrize("delay", [0.0, 0.0068, 0.0125])
def test_the_pendulum_held_and_delayed_matches_a_fine_simulation(delay: float) -> None:
    loop = _loop()
    a, b = loop.continuous(_values())
    ap, bp, cp = loop.discretise(a, b, T, delay)
    rng = np.random.default_rng(7)
    inputs = [float(u) for u in rng.uniform(-0.5, 0.5, 12)]
    state = np.zeros((ap.shape[0], 1))
    fine = _fine(a, b, inputs, delay)
    for k in range(len(inputs) - 1):
        assert np.allclose(cp @ state, fine[k], rtol=1e-6, atol=1e-9), k
        state = ap @ state + bp * inputs[k]


def _firmware(system: Any, si: Any, steps: int) -> list[float]:
    """The firmware's own update stepped in time on the discretised plant: its commands."""
    xi = np.zeros((system.ap.shape[0], 1))
    xi[0, 0] = 0.02
    angle, command, out = 0.0, 0.0, []
    for _ in range(steps):
        theta, rate, x, v = (float(e) for e in (system.cp @ xi)[:, 0])
        angle = si.decay * (angle + si.period * rate)
        command = command + si.angle * angle + si.rate * rate + si.distance * x + si.speed * v
        out.append(command)
        xi = system.ap @ xi + system.bp * command
    return out


@pytest.mark.parametrize("decay", [1.0, 0.999, 0.9])
def test_the_incremental_controller_is_the_firmware_s_update(decay: float) -> None:
    loop = _loop()
    si = _si(
        incremental=True,
        angle=0.14,
        rate=0.14 * 0.14,
        distance=0.17,
        speed=0.078,
        decay=decay,
        sensor_delay=0.0048,
        compute_delay=0.002,
    )
    system = loop.system(_values(), si)
    want = _firmware(system, si, 40)
    state = np.zeros((system.ap.shape[0] + system.ac.shape[0], 1))
    state[0, 0] = 0.02
    matrix = loop.closed(system, 1.0)
    got = []
    for _ in range(40):
        plant, ctrl = state[: system.ap.shape[0]], state[system.ap.shape[0] :]
        got.append(float((system.cc @ ctrl + system.dc @ (system.cp @ plant))[0, 0]))
        state = matrix @ state
    assert np.allclose(got, want, rtol=1e-9, atol=1e-12)


def _lqr(values: dict[str, float]) -> Any:
    """A slow discrete LQR state feedback for the pendulum, designed here, no delay."""
    loop = _loop()
    a, b = loop.continuous(values)
    ap, bp, _ = loop.discretise(a, b, T, 0.0)
    phi, gamma = ap[:4, :4], bp[:4]
    q = np.diag([1.0, 0.01, 1.0, 0.1])
    r = np.array([[50.0]])
    s = solve_discrete_are(phi, gamma, q, r)
    k = np.linalg.solve(r + gamma.T @ s @ gamma, gamma.T @ s @ phi)
    return -k[0]


def _crossover(system: Any) -> float:
    w = np.logspace(-3, math.log10(math.pi / T), 6000)
    mag = np.abs(_loop().response(system, w))
    i = np.nonzero(np.sign(mag[:-1] - 1) != np.sign(mag[1:] - 1))[0]
    return float(w[i[-1]])


@pytest.mark.parametrize("delay", [0.0, 0.004])
def test_the_discrete_margins_agree_with_the_continuous_scorer_s_within_the_frozen_tolerance(
    delay: float,
) -> None:
    import control as ct

    from physgate.evaluation.per_role.scorers.control import gain_margin, phase_margin

    loop = _loop()
    values = _values()
    gains = _lqr(values)
    # The controller reads the encoders' travel; these gains on what it reads are the LQR's on
    # the state, so both sides judge the same feedback.
    read = gains @ np.linalg.inv(loop.measurement(values))
    si = _si(angle=read[0], rate=read[1], distance=read[2], speed=read[3], compute_delay=delay)
    system = loop.system(values, si)
    assert loop.stable(system, 1.0)
    assert _crossover(system) * T <= LARGEST_OMEGA_T
    a, b = loop.continuous(values)
    g = ct.ss2tf(ct.ss(a, b, -gains.reshape(1, 4), 0.0))
    c = ct.tf([1.0], [1.0])
    continuous_pm, _ = phase_margin(c, g, delay + T / 2)
    discrete_pm, crossed = loop.phase_margin(system)
    assert crossed
    assert abs(discrete_pm - continuous_pm) <= PHASE_MARGIN_DEGREES, (discrete_pm, continuous_pm)
    down, _ = loop.gain_margins(system)
    continuous_down = gain_margin(c, g, delay + T / 2)
    assert abs(down - continuous_down) / continuous_down <= GAIN_MARGIN_RELATIVE, (
        down,
        continuous_down,
    )


def test_the_margins_record_says_unstable_with_no_numbers() -> None:
    margins = _loop().margins(_values(), _si(angle=-1.0))
    assert margins.stable is False
    assert (margins.phase_margin, margins.upward, margins.downward) == (None, None, None)


def test_a_stable_design_s_margins_are_all_given() -> None:
    gains = _lqr(_values())
    margins = _loop().margins(
        _values(), _si(angle=gains[0], rate=gains[1], distance=gains[2], speed=gains[3])
    )
    assert margins.stable is True
    assert margins.crossed is True
    assert margins.downward is not None and 0 < margins.downward < 1
    assert margins.upward is not None and margins.upward > 1
    assert json.dumps(margins.phase_margin) != "null"


def _kit_in_si(decay: float, distance: float = 0.17308, angle: float = 0.14195) -> Any:
    """The kit's published gains in SI (the converter's figures), its delays a few ms."""
    return _si(
        incremental=True,
        angle=angle,
        rate=angle * 0.140,
        distance=distance,
        speed=0.07824,
        decay=decay,
        sensor_delay=0.0048,
        compute_delay=0.002,
    )


def _light_rotor() -> dict[str, float]:
    """The draft at a rotor light enough that the kit's leaky controller holds."""
    values = _values()
    values["rotor_inertia"] = 1e-9
    return values


def test_a_leak_free_integrated_angle_is_judged_on_the_balance_not_on_its_offset() -> None:
    # With no leak, the integrated angle's offset from the tilt is held by an offset of the
    # travel: a mode at exactly 1 at every gain, neither growing nor decaying. The balance is
    # judged on the other modes, and comes out as the 0.999 leak's within a whisker.
    loop = _loop()
    leaky = loop.margins(_light_rotor(), _kit_in_si(0.999))
    leak_free = loop.margins(_light_rotor(), _kit_in_si(1.0))
    assert leaky.stable is True
    assert leak_free.stable is True
    assert leak_free.phase_margin is not None and leaky.phase_margin is not None
    assert abs(leak_free.phase_margin - leaky.phase_margin) < 1.0
    assert leak_free.upward is not None and leaky.upward is not None
    assert abs(leak_free.upward / leaky.upward - 1.0) < 0.05
    assert leak_free.downward is not None and leaky.downward is not None
    assert abs(leak_free.downward / leaky.downward - 1.0) < 0.05


def test_setting_the_offset_aside_never_hides_a_growing_mode() -> None:
    # A rotor of 5e-8 kg*m^2 (the first draft's, above what the sources support): the kit's
    # controller is unstable there, leak or none, and setting the offset aside hides nothing.
    loop = _loop()
    heavy = {**_values(), "rotor_inertia": 5e-8}
    assert loop.margins(heavy, _kit_in_si(0.999)).stable is False
    assert loop.margins(heavy, _kit_in_si(1.0)).stable is False


def test_a_loop_that_holds_no_travel_is_not_stable() -> None:
    # No distance gain: nothing holds the travel, and its mode at 1 is the loop's, not set aside.
    loop = _loop()
    assert loop.margins(_light_rotor(), _kit_in_si(1.0, distance=0.0)).stable is False


def test_the_controller_reads_the_travel_the_motor_shaft_encoders_give() -> None:
    # The encoders sit on the motor shafts, whose housings are fixed to the body: they count
    # the wheel's turn relative to the body, so the travel read is x - r*theta and the speed
    # v - r*theta_dot, never the ground's.
    values = _values()
    r = values["wheel_radius"]
    system = _loop().system(values, _si(distance=1.0, speed=1.0))
    read = system.cp[:, :4]
    want = np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [-r, 0.0, 1.0, 0.0], [0.0, -r, 0.0, 1.0]]
    )
    assert np.allclose(read, want, rtol=0.0, atol=1e-15), read


def test_a_tilt_alone_moves_the_travel_the_controller_reads() -> None:
    # Upright wheels held still, the body tilted forward by 0.1 rad: the encoders read the
    # wheel as turned back by 0.1 rad relative to the body.
    values = _values()
    system = _loop().system(values, _si(distance=1.0))
    state = np.zeros((system.ap.shape[0], 1))
    state[0, 0] = 0.1
    command = float((system.dc @ system.cp @ state)[0, 0])
    assert command == pytest.approx(-0.1 * values["wheel_radius"], rel=1e-12)
