"""The balance loop as the firmware runs it: sampled, held, delayed, and its margins.

The plant is :mod:`physgate.evaluation.whole.plant`'s linearised pendulum with its motors,
states ``[θ, θ̇, x, v]`` and the duty as input. It is discretised with a zero-order hold at the
controller's period, the input delayed by the sum of the sensor and compute delays (for a
linear loop a delay on the measurement and one on the command are one delay on the command).
That delay is a time, often less than one period: it is discretised exactly, ``d`` whole
periods and a fraction ``δ`` of one, with ``X[k+1] = Φ·X[k] + Γ0·u[k-d] + Γ1·u[k-d-1]``,
``Γ0 = ∫₀^{T-δ} e^{As} ds·B`` and ``Γ1 = e^{A(T-δ)}·∫₀^{δ} e^{As} ds·B``.

The controller is :class:`~physgate.evaluation.whole.convert.SiLoop`, read as the firmware
reads it: an incremental structure integrates the measured rate into its own angle,
``θ̂[k] = d·(θ̂[k-1] + T·θ̇[k])``, and changes the command; a state feedback sets it from the
measured tilt. The command limit is not in the linear loop, nor are the code's integer
truncations.

**What the controller reads.** The tilt and its rate, and the travel and speed the wheel
encoders give. The encoders sit on the motor shafts, whose housings are fixed to the body, so
they count each wheel's turn relative to the body: the travel read is ``x − r·θ`` and the
speed ``v − r·θ̇`` (:func:`measurement`), never the ground's.

**The leak-free angle's offset.** With no leak (``d`` = 1) the integrated angle keeps whatever
offset from the tilt it starts with, and the travel settles where the distance term cancels
it: ``θ̂ = c``, ``x = -c·angle/distance``, the body upright and still, the command 0. That is a
fixed point for every ``c`` and at every gain, a mode at exactly 1 that neither grows nor
decays, set by the integrator's start and not by the balance. The loop's stability is judged
on its other modes; that one is set aside exactly, by a change of basis that holds it apart.
With no distance gain nothing holds the travel, and no mode is set aside.

**Margins.** With the controller's command multiplied by a gain ``κ`` before the plant, the
closed loop is stable for ``κ`` in an interval about 1 when the design is stable at all. The
upward and downward gain margins are that interval's ends, found by stepping out from 1 and
bisecting on the closed loop's poles (the spectral radius against 1): well defined though the
open loop is unstable. The phase margin is the smallest, over every gain crossover of the
loop's frequency response on the unit circle, of ``180° + ∠L``, ``L = -C·P`` the loop broken
at the plant's input.

**What the searches can miss.** The gain margins step out from 1 by :data:`GAIN_STEP` and take
the first unstable gain, so an unstable band narrower than one step is skipped, and the stable
gains are taken to be one interval. The phase-margin sweep has :data:`POINTS_PER_DECADE` points
a decade from :data:`LOWEST_FREQUENCY` to the Nyquist frequency, and finds a crossover by a
change of sign between two points, so two crossovers inside one step are missed. The phase
margin is wrapped to ±180°, so a stable loop can report a negative one. Each score records
this grid (:func:`search_grid`).

**Numerical failure.** A plant, a delay line or a frequency response that is not finite is a
:class:`SimulationError`, never a number judged; the scenario catches it, and every other
numerical failure of the analysis (:data:`NUMERICAL_FAILURES`), in one place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.linalg import expm

from physgate.evaluation.whole.convert import SiLoop
from physgate.evaluation.whole.plant import bodies, motor

Matrix = Any  # a numpy float array; numpy's own types do not survive mypy --strict here

#: The gain margins are searched out to this factor either way; beyond it, infinite (or 0).
GAIN_SEARCH_LIMIT = 1000.0
#: The step, as a factor, when stepping out from 1 before bisecting.
GAIN_STEP = 1.02
#: Bisection stops when the bracket's ends are within this ratio.
GAIN_TOLERANCE = 1e-9
#: Frequency points per decade of the phase-margin sweep, and its lowest frequency, rad/s.
POINTS_PER_DECADE = 400
LOWEST_FREQUENCY = 1e-4
#: A closed loop is stable when its spectral radius is below one by at least this.
STABILITY_EPSILON = 1e-12
#: A fraction of a period below this is no fraction at all.
FRACTION_EPSILON = 1e-12
#: A leak this close to 1 is no leak: its time constant, ``period/(1 - d)``, is at least a
#: billion periods (four months at 10 ms), past any time a criterion is judged over. Without it
#: a leak just below 1 would leave a mode inside :data:`STABILITY_EPSILON` of the unit circle,
#: judged unstable though it decays, while the leak-free loop sets that mode aside.
DECAY_TOLERANCE = 1e-9
#: The plant's own states, ``[θ, θ̇, x, v]``.
PLANT_STATES = 4


class SimulationError(ArithmeticError):
    """The analysis met a number that is not finite: a plant, a delay line or a response."""


#: Every numerical failure the analysis can raise, caught by the scenario in one place.
NUMERICAL_FAILURES = (ArithmeticError, np.linalg.LinAlgError)


def _finite(what: str, *arrays: Matrix) -> None:
    if not all(np.all(np.isfinite(a)) for a in arrays):
        msg = f"{what} is not finite"
        raise SimulationError(msg)


def continuous(values: dict[str, float]) -> tuple[Matrix, Matrix]:
    """The plant's ``A`` (4×4) and ``B`` (4×1), states ``[θ, θ̇, x, v]``, input the duty."""
    c = bodies(values)
    mo = motor(values)
    r = c.wheel_radius
    drive = 2.0 * mo.torque_constant * mo.pack_voltage / mo.resistance
    damping = 2.0 * mo.torque_constant * mo.back_emf_constant / mo.resistance
    inverse = np.linalg.inv(np.array([[c.b + c.j, c.a - c.j], [c.a - c.j, c.i_p + c.j]]))
    # Generalised forces on (φ, θ), each a row over [θ, θ̇, x, v, u].
    force_phi = np.array([0.0, damping, 0.0, -damping / r, drive])
    force_theta = np.array([c.mgh, -damping, 0.0, damping / r, -drive])
    phi_dd = inverse[0, 0] * force_phi + inverse[0, 1] * force_theta
    theta_dd = inverse[1, 0] * force_phi + inverse[1, 1] * force_theta
    a = np.zeros((4, 4))
    a[0, 1] = 1.0
    a[1, :] = theta_dd[:4]
    a[2, 3] = 1.0
    a[3, :] = r * phi_dd[:4]
    b = np.array([[0.0], [theta_dd[4]], [0.0], [r * phi_dd[4]]])
    return a, b


def measurement(values: dict[str, float]) -> Matrix:
    """What the controller reads of ``[θ, θ̇, x, v]``: the tilt, its rate, and the encoders'.

    Rows ``θ``, ``θ̇``, ``x − r·θ`` and ``v − r·θ̇``, ``r`` the wheel radius of ``values``.
    """
    r = values["wheel_radius"]
    read = np.eye(4)
    read[2, 0] = -r
    read[3, 1] = -r
    return read


def _held(a: Matrix, b: Matrix, span: float) -> tuple[Matrix, Matrix]:
    """``e^{A·span}`` and ``∫₀^{span} e^{As} ds·B``, from one exponential of the block matrix."""
    n, m = a.shape[0], b.shape[1]
    block = np.zeros((n + m, n + m))
    block[:n, :n] = a * span
    block[:n, n:] = b * span
    e = expm(block)
    return e[:n, :n], e[:n, n:]


def _split(delay: float, period: float) -> tuple[int, float]:
    """``delay`` as whole periods and the fraction of one left, in s."""
    whole = math.floor(delay / period + FRACTION_EPSILON)
    fraction = delay - whole * period
    if fraction < FRACTION_EPSILON * period:
        fraction = 0.0
    return whole, fraction


def discretise(a: Matrix, b: Matrix, period: float, delay: float) -> tuple[Matrix, Matrix, Matrix]:
    """The plant held at ``period`` with its input delayed by ``delay``: ``(Ap, Bp, Cp)``.

    The state is the plant's, then the last ``d + 1`` commands, newest first; ``Cp`` reads
    the plant's own state at the sample.
    """
    whole, fraction = _split(delay, period)
    n = a.shape[0]
    phi, _ = _held(a, b, period)
    after, gamma0 = _held(a, b, period - fraction)
    during = _held(a, b, fraction)[1] if fraction else np.zeros_like(b)
    gamma1 = after @ during
    size = n + whole + 1
    ap = np.zeros((size, size))
    bp = np.zeros((size, 1))
    ap[:n, :n] = phi
    if whole == 0:
        bp[:n] = gamma0
    else:
        ap[:n, n + whole - 1 : n + whole] = gamma0
    ap[:n, n + whole : n + whole + 1] = gamma1
    bp[n, 0] = 1.0
    for i in range(1, whole + 1):
        ap[n + i, n + i - 1] = 1.0
    cp = np.zeros((n, size))
    cp[:, :n] = np.eye(n)
    return ap, bp, cp


def controller(loop: SiLoop) -> tuple[Matrix, Matrix, Matrix, Matrix]:
    """The controller from the measurements ``[θ, θ̇, x, v]`` to the command: ``(Ac, Bc, Cc, Dc)``.

    An incremental structure's state is ``[θ̂[k-1], u[k-1]]``; a state feedback has none.
    """
    gains = np.array([[loop.angle, loop.rate, loop.distance, loop.speed]])
    if not loop.incremental:
        return np.zeros((0, 0)), np.zeros((0, 4)), np.zeros((1, 0)), gains
    # The angle term acts on θ̂, never on the measured tilt: its column of the gains is 0.
    d, t = (1.0 if leak_free(loop) else loop.decay), loop.period
    rate_in = np.array([[0.0, d * t, 0.0, 0.0]])
    direct = np.array([[0.0, loop.rate, loop.distance, loop.speed]]) + loop.angle * rate_in
    ac = np.array([[d, 0.0], [loop.angle * d, 1.0]])
    bc = np.vstack([rate_in, direct])
    cc = np.array([[loop.angle * d, 1.0]])
    return ac, bc, cc, direct


@dataclass(frozen=True)
class System:
    """A discrete plant and controller, the loop to be closed: ``(Ap, Bp, Cp)``, ``(Ac..Dc)``."""

    ap: Matrix
    bp: Matrix
    cp: Matrix
    ac: Matrix
    bc: Matrix
    cc: Matrix
    dc: Matrix
    period: float
    neutral: Matrix | None = None


def leak_free(loop: SiLoop) -> bool:
    """Whether ``loop``'s angle has no leak: its decay is within :data:`DECAY_TOLERANCE` of 1."""
    return loop.decay >= 1.0 - DECAY_TOLERANCE


def _neutral(loop: SiLoop, plant_size: int, size: int) -> Matrix | None:
    """The leak-free angle's held offset as a closed-loop state, or ``None`` when it has none.

    The closed loop's state is the plant's (``plant_size``, the tilt first and the travel
    third), then the controller's ``[θ̂[k-1], u[k-1]]``.
    """
    if not loop.incremental or not leak_free(loop) or loop.distance == 0.0:
        return None
    mode = np.zeros((size, 1))
    mode[2, 0] = -loop.angle / loop.distance
    mode[plant_size, 0] = 1.0
    return mode


def closed(system: System, gain: float) -> Matrix:
    """The closed loop's state matrix with the command multiplied by ``gain``."""
    s = system
    top = np.hstack([s.ap + gain * s.bp @ s.dc @ s.cp, gain * s.bp @ s.cc])
    bottom = np.hstack([s.bc @ s.cp, s.ac])
    return np.vstack([top, bottom])


def stable(system: System, gain: float) -> bool:
    """Whether the closed loop at ``gain`` has every pole strictly inside the unit circle.

    A leak-free angle's held offset (:func:`_neutral`) is not one of them: in a basis whose
    column for ``θ̂`` is that mode, the matrix's column there is the unit vector, and the
    other poles are those of what remains.
    """
    matrix = closed(system, gain)
    if system.neutral is not None:
        at = system.ap.shape[0]
        basis = np.eye(matrix.shape[0])
        basis[:, at : at + 1] = system.neutral
        held = np.linalg.solve(basis, matrix @ basis)
        matrix = np.delete(np.delete(held, at, axis=0), at, axis=1)
    radius = float(np.max(np.abs(np.linalg.eigvals(matrix))))
    if not math.isfinite(radius):
        msg = f"the closed loop's spectral radius at gain {gain:g} is not finite"
        raise SimulationError(msg)
    return radius < 1.0 - STABILITY_EPSILON


def _edge(system: System, toward: float) -> float:
    """The first gain from 1 towards ``toward`` (a factor per step) at which the loop is unstable.

    Returns ``inf`` (upward) or ``0.0`` (downward) when none is found within the limit.
    """
    inside = 1.0
    while True:
        outside = inside * toward
        if outside > GAIN_SEARCH_LIMIT:
            return math.inf
        if outside < 1.0 / GAIN_SEARCH_LIMIT:
            return 0.0
        if not stable(system, outside):
            break
        inside = outside
    while abs(outside / inside - 1.0) > GAIN_TOLERANCE:
        middle = math.sqrt(inside * outside)
        if stable(system, middle):
            inside = middle
        else:
            outside = middle
    return outside


def gain_margins(system: System) -> tuple[float, float]:
    """The downward and upward gain margins; the closed loop must be stable at 1.

    Raises:
        ValueError: the closed loop is unstable as designed.
    """
    if not stable(system, 1.0):
        msg = "the closed loop is unstable as designed, so it has no gain margin"
        raise ValueError(msg)
    return _edge(system, 1.0 / GAIN_STEP), _edge(system, GAIN_STEP)


def response(system: System, w: Matrix) -> Matrix:
    """``L(e^{jωT}) = -C·P`` at the frequencies ``w`` (rad/s), the loop broken at the input."""
    s = system
    z = np.exp(1j * w * s.period)
    n = s.ap.shape[0]
    plant = np.linalg.solve(
        z[:, None, None] * np.eye(n) - s.ap, np.broadcast_to(s.bp, (z.size, n, 1))
    )
    measured = s.cp @ plant
    if s.ac.shape[0]:
        m = s.ac.shape[0]
        inner = np.linalg.solve(z[:, None, None] * np.eye(m) - s.ac, s.bc @ measured)
        command = s.cc @ inner + s.dc @ measured
    else:
        command = s.dc @ measured
    out = -command[:, 0, 0]
    _finite("the loop's frequency response", out)
    return out


def _wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def phase_margin(system: System) -> tuple[float, bool]:
    """The smallest phase margin over every gain crossover below the Nyquist frequency, deg.

    Returns ``(margin, crossed)``; with no crossover the margin is infinite and ``crossed``
    False.
    """
    top = math.pi / system.period
    w = np.logspace(math.log10(LOWEST_FREQUENCY), math.log10(top), sweep_points(system.period))
    excess = np.abs(response(system, w)) - 1.0
    crossings = np.nonzero(np.sign(excess[:-1]) != np.sign(excess[1:]))[0]
    if crossings.size == 0:
        return math.inf, False
    margins = []
    for i in crossings:
        lo, hi = float(w[i]), float(w[i + 1])
        f_lo = float(abs(response(system, np.array([lo]))[0]) - 1.0)
        for _ in range(80):
            mid = math.sqrt(lo * hi)
            f_mid = float(abs(response(system, np.array([mid]))[0]) - 1.0)
            if (f_lo <= 0) == (f_mid <= 0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
        at = response(system, np.array([math.sqrt(lo * hi)]))[0]
        margins.append(_wrap(math.degrees(float(np.angle(at))) + 180.0))
    return min(margins), True


def sweep_points(period: float) -> int:
    """The frequency points of the phase-margin sweep at ``period``: up to the Nyquist frequency."""
    decades = math.log10(math.pi / period) - math.log10(LOWEST_FREQUENCY)
    return int(decades * POINTS_PER_DECADE) + 1


def states(loop: SiLoop) -> int:
    """The closed loop's state count under ``loop``: plant, delay line and controller.

    The delay line holds the last ``d + 1`` commands, ``d`` the whole periods of the delay.
    """
    whole, _ = _split(loop.sensor_delay + loop.compute_delay, loop.period)
    return PLANT_STATES + whole + 1 + (2 if loop.incremental else 0)


def steps(loop: SiLoop) -> int:
    """The most closed-loop evaluations one analysis of ``loop`` makes, known before it runs.

    The phase-margin sweep's points, the two stability checks at gain 1, and each gain margin's
    stepping out to :data:`GAIN_SEARCH_LIMIT` and its bisection to :data:`GAIN_TOLERANCE`. The
    refinement of each gain crossover the sweep finds (80 evaluations) is not counted: the
    crossovers are not known before the sweep.
    """
    stepping = math.ceil(math.log(GAIN_SEARCH_LIMIT) / math.log(GAIN_STEP))
    bisecting = math.ceil(math.log2(math.log(GAIN_STEP) / GAIN_TOLERANCE))
    return sweep_points(loop.period) + 2 + 2 * (stepping + bisecting)


def search_grid(period: float) -> dict[str, dict[str, float | int | str]]:
    """The grid and resolution of the margin searches at ``period``, each a value and its unit."""
    return {
        "gain_step": {"value": GAIN_STEP, "unit": "1"},
        "gain_limit": {"value": GAIN_SEARCH_LIMIT, "unit": "1"},
        "gain_tolerance": {"value": GAIN_TOLERANCE, "unit": "1"},
        "points_per_decade": {"value": POINTS_PER_DECADE, "unit": "1"},
        "lowest_frequency": {"value": LOWEST_FREQUENCY, "unit": "rad/s"},
        "highest_frequency": {"value": math.pi / period, "unit": "rad/s"},
    }


def system(values: dict[str, float], loop: SiLoop) -> System:
    """The pendulum of ``values`` under ``loop``, discretised as the module's docstring says."""
    a, b = continuous(values)
    ap, bp, held = discretise(a, b, loop.period, loop.sensor_delay + loop.compute_delay)
    cp = measurement(values) @ held
    ac, bc, cc, dc = controller(loop)
    _finite("the plant held at the period, or the controller,", ap, bp, cp, ac, bc, cc, dc)
    neutral = _neutral(loop, ap.shape[0], ap.shape[0] + ac.shape[0])
    return System(
        ap=ap, bp=bp, cp=cp, ac=ac, bc=bc, cc=cc, dc=dc, period=loop.period, neutral=neutral
    )


@dataclass(frozen=True)
class Margins:
    """The loop's margins; ``stable`` False leaves the others ``None``."""

    stable: bool
    phase_margin: float | None
    crossed: bool
    upward: float | None
    downward: float | None


def margins(values: dict[str, float], loop: SiLoop) -> Margins:
    """The phase and gain margins of the pendulum of ``values`` under ``loop``."""
    s = system(values, loop)
    if not stable(s, 1.0):
        return Margins(stable=False, phase_margin=None, crossed=False, upward=None, downward=None)
    down, up = gain_margins(s)
    pm, crossed = phase_margin(s)
    return Margins(stable=True, phase_margin=pm, crossed=crossed, upward=up, downward=down)


def unstable_pole(values: dict[str, float]) -> float:
    """The powered plant's unstable pole, rad/s: the open loop's fastest growing mode."""
    a, _ = continuous(values)
    return float(np.max(np.linalg.eigvals(a).real))
