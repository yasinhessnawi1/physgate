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

**What "held by structure" means for a sampled law.** A mode may be set aside only if the law's
own lines hold it at exactly 1 whatever the gain, *and the wheels, displaced alone, return*. In
plain words: put the body upright and still, the wheels anywhere (the travel is the plant's one
pole at 1), and some value in the law's memory; the mode is held if one update then gives a
command of exactly 0 and gives the very same memory back. A held mode is the offset of something
the law conserves at rest; displace the wheels alone and the loop settles where that conserved
quantity says. The mode is set aside only if nothing the wheels' motion can add feeds that
quantity: not the command, and no wheel speed (the plant's motor force is one combination of the
command and the wheel speed, so a steady cruise has the body upright and still, and the tilt and
its rate feed nothing the wheels can move). Then the wheels return, whatever is in memory. Both
are decided on the numbers the law has, in exact arithmetic, as written
(:func:`physgate.evaluation.whole.law.held_modes`), with no window: a memory state whose update is
itself and nothing else, a sum of states the updates conserve, a state nothing reads or only the
tilt or its rate feed, and the leak-free angle's offset (where the wheels' angle is part of the
mode, balanced against the memory) are held and set aside; a pole at ``1 + 1e-6``, or an integrator
fed from the command with a gain of ``1e-6``, is not held, whatever other coefficient the law has.
A memory that merely follows the wheel angle (a backward-difference speed with no position gain,
a washout, a position gain of zero) holds a mode at 1 that is the travel itself: the wheels do not
return, nothing is set aside, and the loop is unstable. So is a law that reads the wheel angle
nowhere, whether or not it also has an inert state.

**What is decided exactly.** The *rest subspace* of the law is the largest part of its state (the
wheel angle, which is kept at rest, and the memory) on which the command stays zero at every update
with the plant at rest; it is closed under the update, so the closed loop's eigenvalues there are
the law's own. On it, in exact arithmetic on the law's numbers as written
(:class:`~physgate.evaluation.whole.law.UnitCircle`), the algebraic multiplicity of the eigenvalue
1 against the number of modes set aside, and any eigenvalue of exactly -1: either one makes the law
unstable outright, whatever a floating-point eigenvalue comes out as, a chain of integrators behind
a set-aside mode included (the count at -1 is the dimension of a kernel, the independent
eigenvectors). **What is judged in floating point** is every mode that moves the plant, and a mode
at exactly 1 or -1 that is reached only through the plant or through a state the command reads (a
held integrator the command reads, fed by a constant state nothing feeds): such a mode lies outside
the rest subspace. For the shape named here and its amplified variants the error measured is below
1e-15; that is no bound for every mode outside the rest subspace. An eigenvalue exactly on the unit
circle there is included, and so is anything within
:data:`STABILITY_EPSILON` of the circle, by the one stated rule: the closed loop is stable when its
spectral radius, after exactly the modes set aside are taken out, is below 1 by at least
:data:`STABILITY_EPSILON`.

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

from physgate.evaluation.whole.convert import LinearLaw, SiLoop
from physgate.evaluation.whole.law import UnitCircle
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
#: A closed loop is stable when its spectral radius is below one by at least this, an absolute
#: number, whatever the law's coefficients. Chosen from what was measured: the same recorded law
#: written with a memory state scaled from 1e-6 to 1e6 moves its spectral radius by up to 3.6e-13
#: (0.999039737170975 to 0.999039737171331) with the margins identical to nine digits, so 1e-12 is
#: about three times that rounding, not "thousands of times": a loop within it of the unit
#: circle is not told from one on it, and is called unstable; a pole above 1 by more than this is
#: unstable, however large another coefficient is. Where the rounding is larger than this (with a
#: coefficient near the bound of 1e6 the rounding of the eigenvalues can reach 1e-10, which is
#: why the answer bounds a coefficient) a loop within that rounding of the unit circle can be
#: called either: the verdict is exact only outside it, except for what a sampled law's exact
#: arithmetic decides without a float on its rest subspace (the eigenvalue 1 beyond the modes set
#: aside, and any -1: the circle count of the law); a mode at exactly 1 or -1 outside that subspace
#: is judged by the float.
STABILITY_EPSILON = 1e-12
#: A fraction of a period below this is no fraction at all.
FRACTION_EPSILON = 1e-12
#: A leak this close to 1 is no leak: its time constant, ``period/(1 - d)``, is at least a
#: billion periods (four months at 10 ms), past any time a criterion is judged over. Without it
#: a leak just below 1 would leave a mode inside :data:`STABILITY_EPSILON` of the unit circle,
#: judged unstable though it decays, while the leak-free loop sets that mode aside.
DECAY_TOLERANCE = 1e-9
#: The plant's own states, ``[θ, θ̇, x, v]``, and where the travel ``x`` is among them.
PLANT_STATES = 4
TRAVEL = 2


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


def _law_reads(wheel_radius: float) -> Matrix:
    """The law's signals from the measurements: the tilt, its rate, the wheels' angle and speed.

    The wheels' angle and speed are the encoders' travel and speed over the wheel radius.
    """
    read = np.zeros((4, 4))
    read[0, 0] = 1.0
    read[1, 1] = 1.0
    read[2, 2] = 1.0 / wheel_radius
    read[3, 3] = 1.0 / wheel_radius
    return read


def controller(
    loop: SiLoop, wheel_radius: float | None = None
) -> tuple[Matrix, Matrix, Matrix, Matrix]:
    """The controller from the measurements ``[θ, θ̇, x, v]`` to the command: ``(Ac, Bc, Cc, Dc)``.

    An incremental structure's state is ``[θ̂[k-1], u[k-1]]``; a state feedback has none. A
    sampled law's state is its memory before the update, and ``wheel_radius`` (the plant's)
    takes the encoders' travel and speed to the law's wheel angle and speed.
    """
    if loop.law is not None:
        if wheel_radius is None:
            msg = "a sampled law is read through the plant's wheel radius"
            raise ValueError(msg)
        law = loop.law
        reads = _law_reads(wheel_radius)
        n = law.states
        ac = np.array(law.a, dtype=float).reshape(n, n)
        bc = np.array(law.b, dtype=float).reshape(n, 4) @ reads
        cc = np.array(law.c, dtype=float).reshape(1, n)
        dc = np.array(law.d, dtype=float).reshape(1, 4) @ reads
        return ac, bc, cc, dc
    gains = np.array([[loop.angle, loop.rate, loop.distance, loop.speed]])
    if not loop.incremental:
        return np.zeros((0, 0)), np.zeros((0, 4)), np.zeros((1, 0)), gains
    # The angle term acts on θ̂, never on the measured tilt: its column of the gains is 0.
    d, t = loop.decay, loop.period
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
    held: Matrix | None = None
    #: A sampled law's exact eigenvalues at 1 beyond the modes set aside, and the dimension of the
    #: kernel at -1 (independent eigenvectors, not a multiplicity), on its rest subspace only;
    #: see ``unit_circle``.
    unit_circle: UnitCircle = UnitCircle(0, 0)


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


def _held_columns(law: LinearLaw, plant_size: int, wheel_radius: float) -> Matrix | None:
    """The law's held modes as closed-loop states, as columns, or ``None`` when it holds none.

    A mode of :func:`physgate.evaluation.whole.law.held_modes` is the wheel angle ``β`` and the
    memory; as a closed-loop state the plant is at rest but for its travel, ``x = r·β``, the
    delay line empty (the command is 0), and the memory is the law's.
    """
    if not law.held:
        return None
    columns = np.zeros((plant_size + law.states, len(law.held)))
    for j, mode in enumerate(law.held):
        columns[TRAVEL, j] = mode[0] * wheel_radius
        columns[plant_size:, j] = mode[1:]
    return columns


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
    if system.unit_circle.unstable:
        # On the law's rest subspace, an eigenvalue of exactly 1 beyond the modes set aside (a
        # chain behind one included) or of exactly -1, decided exactly on the law's numbers as
        # written, whatever the floating-point eigenvalue comes out as.
        return False
    matrix = closed(system, gain)
    if system.held is not None:
        # The held modes span an invariant subspace at 1: in an orthonormal basis that starts
        # with it, the matrix is block upper triangular and the other poles are the last block.
        q, _ = np.linalg.qr(system.held, mode="complete")
        k = system.held.shape[1]
        matrix = (q.T @ matrix @ q)[k:, k:]
    elif system.neutral is not None:
        at = system.ap.shape[0]
        basis = np.eye(matrix.shape[0])
        basis[:, at : at + 1] = system.neutral
        held = np.linalg.solve(basis, matrix @ basis)
        matrix = np.delete(np.delete(held, at, axis=0), at, axis=1)
    radius = float(np.max(np.abs(np.linalg.eigvals(matrix))))
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
    if loop.law is not None:
        return PLANT_STATES + whole + 1 + loop.law.states
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
    """The pendulum of ``values`` under ``loop``, discretised as the module's docstring says.

    A number that overflows is a :class:`SimulationError` (the scenario names it), and the
    floating-point warning that came with it is not left in the scorer's log.
    """
    with np.errstate(over="ignore", invalid="ignore"):
        return _system(values, loop)


def _system(values: dict[str, float], loop: SiLoop) -> System:
    a, b = continuous(values)
    ap, bp, held = discretise(a, b, loop.period, loop.sensor_delay + loop.compute_delay)
    cp = measurement(values) @ held
    ac, bc, cc, dc = controller(loop, values["wheel_radius"])
    _finite("the plant held at the period, or the controller,", ap, bp, cp, ac, bc, cc, dc)
    if loop.law is not None:
        return System(
            ap=ap,
            bp=bp,
            cp=cp,
            ac=ac,
            bc=bc,
            cc=cc,
            dc=dc,
            period=loop.period,
            held=_held_columns(loop.law, ap.shape[0], values["wheel_radius"]),
            unit_circle=loop.law.circle,
        )
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
    with np.errstate(over="ignore", invalid="ignore"):
        return _margins(values, loop)


def _margins(values: dict[str, float], loop: SiLoop) -> Margins:
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
