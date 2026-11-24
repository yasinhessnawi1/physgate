"""The linear plant stepped in time under a law's lines: the dynamic checks' first, labelled kind.

**What this is.** The whole-design scorer judges a design's loop in the frequency domain
(:mod:`physgate.evaluation.whole.loop`). This module steps the same linear plant in time, with a
sampled law run as its lines, a speed reference and a push, and reads two numbers off the run:
the ground speed reached under a speed reference (:data:`STEADY_SPEED`) and the largest tilt after
a push on the tilt rate (:data:`PUSH_PEAK_TILT`). They are of the kind ``dynamic_linear``: the
linear model's answer, never criterion 17's or 18's verdict (a dynamic environment judges those),
and they count for nothing in a headline.

**The same loop as the margins.** The plant is ``loop.continuous`` (``A`` and ``B``, the duty in),
held exactly with the helper the margins' discretisation uses, the controller reads what the
margins' controller reads (the tilt, its rate, and the wheels' turn relative to the body,
``(x - r·θ)/r`` and ``(v - r·θ̇)/r``). The delays are stepped in physical time: at update ``k``
(time ``k·T``) the law reads the plant as it was ``sensor_delay`` earlier, and the command it
computes lands ``compute_delay`` after ``k·T`` and is held until the next one lands. The period is
cut exactly at the instants that matter (the update, the landing of a command, the instant a
reading is taken, and output points no further apart than :data:`OUTPUT_SPACING`), each segment
held with its own exact matrices, so a delay that is a fraction of a period, or longer than one,
is not rounded.
Moving the sensor delay onto the plant's time axis shows that what the law reads is the margins'
closed loop's own sample, ``W(jT) = X(jT - τs)``; a row proves it to 1e-9 on small signals.

**The command.** Each update's duty is held to ``±command_limit`` and rounded to whole counts of
the PWM full scale (:func:`physgate.evaluation.whole.law.counts`, here on arrays); a memory state
marked ``applied`` holds the applied value. Where the command reaches the limit the loop is no
longer linear: the number is then that of a linear plant under a limited command, and the record
counts the updates at the limit.

**What the numbers can bear.** The command is rounded to whole counts on a plant that is unstable
while the command sits at its limit, so a lane near the limit amplifies the last bit: a difference
of 1e-17 grows until a count flips, and then differs by whole counts. The batch is therefore run a
second time with one tiny perturbation (:data:`SENSITIVITY_RATE_OFFSET`), and the record says how
many points change verdict or fall between the two runs; such a point counts neither way.

**A lane that fell** is frozen where it passed 70°. Nothing of it is counted at the limit, and its
window means and its speed at the push are not numbers; the record says when it fell.

**One stepper.** A version 3 law is stepped as its lines. A version 2 named structure goes
through :func:`named_as_law`, its lines written as a law with the corner's wheel radius folded
into the gains, as the equivalence rows do. Both are compiled by :func:`compile_law` into the same
float operations :func:`physgate.evaluation.whole.law.evaluate` makes (a row asserts the two are
bitwise equal), and every plant point is stepped in one batch of numpy arrays.

**Proposals.** Every number of the timeline below is a proposal, chosen, none sourced, none
frozen: each is to be frozen before any design is scored. The three taken from the brief (the push,
its band and 70°) are the brief's own.

**Not modelled** (:data:`NOT_MODELLED`): the gyro's full scale, the encoders' counts, noise,
bias, the gearbox's friction, large angles, contact and slip.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from physgate.evaluation.whole import law as law_module

# The margins' own helpers, imported rather than copied so that the two loops cannot drift apart
# (a row proves their agreement); they are private to ``loop`` and ``law`` and are used as they are.
from physgate.evaluation.whole.convert import SiLoop
from physgate.evaluation.whole.loop import (  # noqa: PLC2701
    FRACTION_EPSILON,
    _held,
    _split,
    continuous,
)

#: The two metrics, each with its unit.
STEADY_SPEED = "linear_steady_speed"
PUSH_PEAK_TILT = "linear_peak_tilt_after_push"
METRICS: dict[str, str] = {STEADY_SPEED: "m/s", PUSH_PEAK_TILT: "deg"}
#: What every record of the kind says.
LABEL = (
    "the linear model's answer: a linear plant under the law's lines, with the command limit and "
    "whole counts; not criterion 17's or 18's verdict. The corner counts are reproducible on one "
    "machine and may differ by a few points between machines, because a lane near the limit "
    "amplifies the last bit"
)
NOT_MODELLED = (
    "gyro_full_scale_clip",
    "encoder_counts",
    "noise_and_bias",
    "gearbox_friction",
    "large_angles",
    "contact_and_slip",
)

# ── the timeline: every number a proposal, none frozen, each to be frozen before scoring ────────
#: Proposal: the robot balances at rest this long before the reference moves, s.
REST_TIME = 1.0
#: Proposal: the reference ground speed ramps at this acceleration, m/s².
RAMP_ACCELERATION = 1.0
#: Proposal: the demanded ground speed, m/s (above the brief's 1.2, so that a design tracking it
#: exactly is not judged on the last decimal).
DEMAND_SPEED = 1.25
#: Proposal: the push comes late, so that a slow but honest design is not failed for a time the
#: brief does not give; s.
PUSH_TIME = 20.0
#: Proposal: the hold window is the last this-many seconds before the push, s.
HOLD_LENGTH = 2.0
#: Proposal: the speed is averaged over this sliding window and the lowest mean is the number, s.
SPEED_AVERAGE = 0.5
#: Proposal: the push is watched for this long, s.
OBSERVE = 4.0
#: Proposal: the instants at which the record gives the speed's window mean, for information, s.
INFORMATION_TIMES = (5.0, 10.0, 15.0)
#: The brief's (criterion 18): the push raises the tilt rate by this, rad/s.
PUSH_RATE = 1.5
#: The brief's (criterion 18): the push's tolerance; the run branches at each end and the middle.
PUSH_BAND = (-0.05, 0.0, 0.05)
#: The brief's (criterion 18): a tilt past this angle is a fall, rad.
FELL_TILT = math.radians(70.0)
#: Proposal: the output points of a period are no further apart than this, s, so that the peak
#: between two updates is found at this spacing whatever the period (the record states it). A
#: smooth tilt whose peak falls between two points ``h`` apart is read low by at most
#: ``h**2 / 8`` times the largest tilt acceleration there (its rate is zero at the peak); a row
#: holds a slow period's peak to that bound against a fine run.
OUTPUT_SPACING = 2.5e-3
#: Proposal: the one tiny perturbation of the second run, rad/s, added to the initial tilt rate of
#: every lane. It is twelve orders below the brief's push (1.5 rad/s), and it is the only
#: nonzero part of the starting state, so it enters every lane; it is large enough, against the
#: plant's unit scales, not to be lost to rounding at the start.
SENSITIVITY_RATE_OFFSET = 1e-12
#: The tolerance, in updates, with which an instant is taken as being on an update.
INDEX_TOLERANCE = 1e-9
#: The runs of one analysis: the batch, and the batch again with the perturbation.
RUNS = 2
#: Proposal: what one cut of a period costs an update, in the units of one state or one term of
#: the law (a matrix product and the fall test are about this many array operations).
SEGMENT_WEIGHT = 12
#: Proposal: what setting up one cut of a period costs, in the same units: a matrix exponential
#: per point, cut and run before the first step (measured at about 30 us on a laptop, over 11,000
#: units of 2.6 ns). At a period of 1 s, 400 cuts, this is most of the analysis's work.
EXPONENTIAL_WEIGHT = 12_000
#: The most work one analysis may do: runs × points × (updates (the shared run and the three
#: branches) × (states + the law's size + the cuts' weight) + the cuts' set-up). A proposal, and a
#: task past it has its rows unscored. What a unit costs depends on the machine and the period:
#: on a Linux server a whole record at a 1 ms period counted 3.55e9 units and took 40 s, so a law
#: at the bound takes minutes there (about four), not seconds.
MAX_DYNAMIC_WORK = 20_000_000_000


@dataclass(frozen=True)
class Timing:
    """One period's cuts: offsets from 0 to the period, and where the events fall among them."""

    offsets: tuple[float, ...]
    apply_cut: int
    snapshot_cut: int | None
    compute_periods: int
    sensor_periods: int


def output_points(period: float) -> int:
    """The equal parts a period is cut into for its peak: none further apart than the spacing."""
    return max(1, math.ceil(period / OUTPUT_SPACING - INDEX_TOLERANCE))


def timing(period: float, sensor_delay: float, compute_delay: float) -> Timing:
    """The cuts of one period under the two delays, each fraction of a period kept exact."""
    eps = FRACTION_EPSILON * period
    compute_periods, compute_fraction = _split(compute_delay, period)
    sensor_periods, sensor_fraction = _split(sensor_delay, period)
    points = output_points(period)
    raw = [0.0, period, *(j * period / points for j in range(1, points))]
    if compute_fraction > 0.0:
        raw.append(compute_fraction)
    snapshot_at = period - sensor_fraction if sensor_fraction > 0.0 else None
    if snapshot_at is not None:
        raw.append(snapshot_at)
    groups: list[list[float]] = []
    for offset in sorted(raw):
        if groups and offset - groups[-1][0] <= eps:
            groups[-1].append(offset)
        else:
            groups.append([offset])
    offsets = tuple(g[0] for g in groups)

    def index(x: float) -> int:
        return min(range(len(offsets)), key=lambda i: abs(offsets[i] - x))

    return Timing(
        offsets=offsets,
        apply_cut=index(compute_fraction) if compute_fraction > 0.0 else 0,
        snapshot_cut=index(snapshot_at) if snapshot_at is not None else None,
        compute_periods=compute_periods,
        sensor_periods=sensor_periods,
    )


# ── a law's lines, compiled ──────────────────────────────────────────────────────────────────

_OF = law_module._OF  # noqa: SLF001 - the one grammar of a term's variable, used as it is


@dataclass(frozen=True)
class Compiled:
    """A law's lines with each term's scale made once (a float, or an array over points)."""

    lines: tuple[tuple[str, tuple[tuple[Any, str | None, str], ...]], ...]
    memory: tuple[tuple[str, str, bool], ...]
    command: str

    def tiled(self, n: int) -> Compiled:
        """The same law over ``n`` copies of the points, each array scale repeated."""

        def tile(scale: Any) -> Any:
            return np.tile(scale, n) if isinstance(scale, np.ndarray) else scale

        return Compiled(
            tuple(
                (name, tuple((tile(s), kind, var) for s, kind, var in terms))
                for name, terms in self.lines
            ),
            self.memory,
            self.command,
        )


def _variable(term: Any) -> tuple[str | None, str]:
    """A term's variable as (its kind, its name); a term with none the scorer reads is refused."""
    found = _OF.fullmatch(term.of) if isinstance(term.of, str) else None
    if found is None:
        msg = "a term holds no variable the scorer can step: nothing is stepped that it cannot take"
        raise law_module.LawRefused("malformed", msg)
    kind, name = found.groups()
    return kind, name


def compile_law(body: law_module.Body, values: dict[str, Any], period: float) -> Compiled:
    """``body`` with its coefficients (numbers, or arrays over points) multiplied out per term.

    The float operations are those of :func:`physgate.evaluation.whole.law.evaluate`, in its order.
    """
    coefficients = {**values, law_module.PERIOD: period}
    lines = []
    for line in body.lines:
        terms = []
        for term in line.terms:
            kind, name = _variable(term)
            scale: Any = float(term.sign) * float(term.number)
            for factor in term.coefficients:
                scale = scale * coefficients[factor]
            for factor in term.per:
                scale = scale / coefficients[factor]
            terms.append((scale, kind, name))
        lines.append((line.name, tuple(terms)))
    memory = tuple((m.name, m.next, m.applied) for m in body.memory)
    return Compiled(tuple(lines), memory, body.command)


def update(
    law: Compiled, state: dict[str, Any], signals: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    """One update: the command before any limit and the memory's next values, as ``evaluate``."""
    values: dict[str, Any] = {}
    for name, terms in law.lines:
        total: Any = 0.0
        for scale, kind, var in terms:
            if kind is None:
                variable = signals[var]
            elif kind == "previous":
                variable = state[var]
            else:
                variable = values[var]
            total = total + scale * variable
        values[name] = total
    return values[law.command], {m: values[nxt] for m, nxt, _ in law.memory}


def counts_of(duty: Any, limit: float, full_scale: float) -> Any:
    """:func:`~physgate.evaluation.whole.law.counts` on an array."""
    held = np.minimum(np.maximum(duty, -limit), limit)
    whole = np.floor(np.abs(held) * full_scale + 0.5)
    return np.where(held >= 0, whole, -whole)


# ── a named structure as a law ───────────────────────────────────────────────────────────────


def _term(of: str, *coefficients: str, sign: int = 1, per: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"sign": sign, "coefficients": list(coefficients), "per": list(per), "of": of}


def named_as_law(loop: SiLoop) -> law_module.Body:
    """A version 2 named structure (``loop.law`` is ``None``) as law lines over the signals.

    The structure reads its travel and speed less a reference that advances at the commanded
    speed: the travel's is ``wheel_reference`` (a wheel angle), the speed's is that reference's
    backward difference over one period, kept in a memory state. A term whose gain is 0 is left
    out, so the lines read the reference only where the structure does. The incremental form keeps
    the angle it integrates and the command as applied.
    """
    terms: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
    if loop.incremental:
        lines.append(
            {
                "name": "angle_now",
                "unit": "rad",
                "terms": [
                    _term("previous.angle", "decay"),
                    _term("tilt_rate", "decay", law_module.PERIOD),
                ],
            }
        )
        memory.append({"name": "angle", "unit": "rad", "next": "angle_now"})
        memory.append({"name": "applied", "unit": "1", "next": "command", "applied": True})
        terms += [
            _term("previous.applied"),
            _term("line.angle_now", "angle_gain"),
            _term("tilt_rate", "rate_gain"),
        ]
    else:
        terms += [_term("tilt", "angle_gain"), _term("tilt_rate", "rate_gain")]
    if loop.distance != 0.0:
        terms += [
            _term("wheel_angle", "distance_gain"),
            _term("wheel_reference", "distance_gain", sign=-1),
        ]
    if loop.speed != 0.0:
        lines.append(
            {
                "name": "reference_now",
                "unit": "rad",
                "terms": [_term("wheel_reference")],
            }
        )
        lines.append(
            {
                "name": "reference_speed",
                "unit": "rad/s",
                "terms": [
                    _term("wheel_reference", per=(law_module.PERIOD,)),
                    _term("previous.reference", sign=-1, per=(law_module.PERIOD,)),
                ],
            }
        )
        memory.append({"name": "reference", "unit": "rad", "next": "reference_now"})
        terms += [
            _term("wheel_speed", "speed_gain"),
            _term("line.reference_speed", "speed_gain", sign=-1),
        ]
    lines.append({"name": "command", "unit": "1", "terms": terms})
    return law_module.Body.model_validate(
        {"memory": memory, "lines": lines, "command": "command"}, strict=False
    )


def named_values(loops: list[SiLoop], radii: list[float]) -> dict[str, Any]:
    """The coefficients of :func:`named_as_law` at each point (gains per radian of wheel)."""
    return {
        "angle_gain": np.array([lp.angle for lp in loops]),
        "rate_gain": np.array([lp.rate for lp in loops]),
        "distance_gain": np.array([lp.distance * r for lp, r in zip(loops, radii, strict=True)]),
        "speed_gain": np.array([lp.speed * r for lp, r in zip(loops, radii, strict=True)]),
        "decay": np.array([lp.decay for lp in loops]),
    }


# ── the run ──────────────────────────────────────────────────────────────────────────────────


def reference_position(t: float) -> float:
    """The reference's ground position at time ``t``, m: still, then a ramp, then the demand."""
    if t <= REST_TIME:
        return 0.0
    ramp = DEMAND_SPEED / RAMP_ACCELERATION
    s = t - REST_TIME
    if s <= ramp:
        return 0.5 * RAMP_ACCELERATION * s * s
    return 0.5 * RAMP_ACCELERATION * ramp * ramp + DEMAND_SPEED * (s - ramp)


@dataclass(frozen=True)
class Plan:
    """What is stepped: the law, its timing, the plant points, and the command's rounding."""

    law: Compiled
    period: float
    sensor_delay: float
    compute_delay: float
    command_limit: float
    full_scale: float
    points: tuple[dict[str, float], ...]


@dataclass(frozen=True)
class Updates:
    """How many updates each phase has: the shared run, and each push branch."""

    window_first: int
    push: int
    observed: int


def updates(period: float) -> Updates:
    """The update indices of the hold window's first, of the push, and the observed count."""
    eps = INDEX_TOLERANCE
    return Updates(
        window_first=math.ceil((PUSH_TIME - HOLD_LENGTH) / period - eps),
        push=math.ceil(PUSH_TIME / period - eps),
        observed=math.ceil(OBSERVE / period - eps),
    )


def law_size(body: law_module.Body) -> int:
    """What the law costs an update: its terms and its lines, each a few array operations."""
    return sum(len(line.terms) for line in body.lines) + len(body.lines)


def work(points: int, period: float, states: int, size: int) -> int:
    """The analysis's work, known before it runs.

    The runs × points × updates (the shared run and the branches) × (the closed loop's states, the
    law's size, :func:`law_size`, and the cuts of a period at their weight: the output points and
    the two cuts a delay can add), and the runs × points × the cuts of a period at the weight of
    setting each up (:data:`EXPONENTIAL_WEIGHT`), which every run does before its first step.
    """
    u = updates(period)
    cuts = output_points(period) + 2
    per_update = states + size + SEGMENT_WEIGHT * cuts
    stepped = (u.push + len(PUSH_BAND) * u.observed) * per_update
    return RUNS * points * (stepped + EXPONENTIAL_WEIGHT * cuts)


def realised_times(period: float) -> dict[str, float]:
    """The push's instant and the averaging's length the period realises, s."""
    u = updates(period)
    return {
        "push_time": u.push * period,
        "speed_average": max(1, round(SPEED_AVERAGE / period)) * period,
    }


def ceiling(values: dict[str, float], limit: float) -> float:
    """The ground speed the plant holds under a constant command ``limit``, m/s.

    The steady state of :func:`~physgate.evaluation.whole.loop.continuous` (its motor model: the
    drive ``2·Kt·V/R`` and the back-EMF damping ``2·Kt·Ke/R``): the tilt leans and stays, the speed
    is constant, so the tilt's and the wheels' accelerations are zero. With the unknowns ``θ`` and
    ``v``: ``A[1,0]·θ + A[1,3]·v = -B[1]·u`` and ``A[3,0]·θ + A[3,3]·v = -B[3]·u``.
    """
    a, b = continuous(values)
    rows = [1, 3]
    system = a[np.ix_(rows, [0, 3])]
    try:
        _, speed = np.linalg.solve(system, -b[rows, 0] * limit)
    except np.linalg.LinAlgError:
        return math.nan
    return float(speed)


@dataclass(frozen=True)
class Result:
    """What a run gives, each an array over the plant points (the push's over branch × point)."""

    #: The lowest sliding mean of the ground speed in the hold window, m/s; NaN if it fell first.
    speed: Any
    #: The mean of the ground speed over the last SPEED_AVERAGE before each information time, m/s;
    #: NaN where the lane had fallen by then (a fallen lane is frozen, its speed no speed).
    means: dict[float, Any]
    #: The mean of the hold window's second half less its first half, m/s (information).
    settled: Any
    #: The ground speed at the push, m/s; NaN if it fell first.
    speed_at_push: Any
    #: Whether the tilt went past FELL_TILT (or a state stopped being finite) before the push.
    fell_before: Any
    #: When the lane fell before the push, s from the start; NaN if it did not.
    fell_at: Any
    #: Updates at the limit in the hold window, counted until the lane fell.
    saturated_hold: Any
    #: The largest tilt from the push, deg, per branch; NaN if it fell before the push.
    peak: Any
    #: Updates at the limit from the push on, per branch, counted until the lane fell.
    saturated_push: Any
    #: Whether the tilt went past FELL_TILT after the push, per branch.
    fell_after: Any
    #: When the lane fell after the push, s from the start, per branch; NaN if it did not (or
    #: had fallen before the push).
    fell_at_push: Any
    #: The ground speed the plant holds under a constant command at the limit, m/s, per point.
    ceiling: Any
    timing: Timing


class _Sim:
    """The state of a batch of runs, advanced a period at a time."""

    def __init__(
        self,
        plan: Plan,
        radius: Any,
        phis: list[Any],
        gams: list[Any],
        tm: Timing,
        rate_offset: float = 0.0,
    ):
        lanes = len(plan.points)
        self.plan, self.tm = plan, tm
        self.lanes = lanes
        self.radius = radius
        self.phis, self.gams = phis, gams
        self.law = plan.law
        self.x = np.zeros((lanes, 4))
        self.x[:, 1] = rate_offset
        self.memory = {name: np.zeros(lanes) for name, _, _ in plan.law.memory}
        self.commands: deque[Any] = deque(maxlen=tm.compute_periods + 1)
        self.snaps: dict[int, Any] = {}
        self.active = np.zeros(lanes)
        self.fell = np.zeros(lanes, dtype=bool)
        self.frozen = np.zeros((lanes, 4))
        self.fell_at = np.full(lanes, np.nan)
        self.peak = np.zeros(lanes)
        self.saturated = np.zeros(lanes, dtype=np.int64)
        self.saturated_hold = np.zeros(lanes, dtype=np.int64)

    def branch(self, n: int, kick: Any) -> None:
        """The batch as ``n`` copies, branch-major, the tilt rate of each kicked by ``kick``."""

        def rep(a: Any) -> Any:
            return np.tile(a, (n,) + (1,) * (a.ndim - 1))

        self.lanes *= n
        self.radius = rep(self.radius)
        self.phis = [rep(p) for p in self.phis]
        self.gams = [rep(g) for g in self.gams]
        self.law = self.law.tiled(n)
        self.x = rep(self.x)
        self.x[:, 1] += kick
        self.memory = {k: rep(v) for k, v in self.memory.items()}
        self.commands = deque((rep(c) for c in self.commands), maxlen=self.commands.maxlen)
        self.snaps = {k: rep(v) for k, v in self.snaps.items()}
        self.active = rep(self.active)
        self.fell = rep(self.fell)
        self.frozen = rep(self.frozen)
        self.fell_at = rep(self.fell_at)
        self.peak = np.zeros(self.lanes)
        self.saturated = np.zeros(self.lanes, dtype=np.int64)

    def _freeze(self, track_peak: bool, at: float) -> None:
        tilt = np.abs(self.x[:, 0])
        if track_peak:
            self.peak = np.maximum(self.peak, np.where(np.isfinite(tilt), tilt, np.inf))
        bad = ~(tilt <= FELL_TILT)
        newly = bad & ~self.fell
        if newly.any():
            self.fell_at = np.where(newly, at, self.fell_at)
            self.frozen = np.where(
                newly[:, None],
                np.where(np.isfinite(self.x), self.x, 0.0),
                self.frozen,
            )
        self.fell |= bad
        self.x = np.where(self.fell[:, None], self.frozen, self.x)

    def period(self, k: int, *, in_hold: bool, after_push: bool) -> None:
        """Advance one update period: the update at ``k·T``, then each segment's exact hold."""
        plan, tm = self.plan, self.tm
        if tm.snapshot_cut is None:
            self.snaps[k] = self.x.copy()
        read = k - tm.sensor_periods - (0 if tm.snapshot_cut is None else 1)
        seen = self.snaps.get(read)
        if seen is None:
            seen = np.zeros((self.lanes, 4))
        r = self.radius
        signals = {
            "tilt": seen[:, 0],
            "tilt_rate": seen[:, 1],
            "wheel_angle": (seen[:, 2] - r * seen[:, 0]) / r,
            "wheel_speed": (seen[:, 3] - r * seen[:, 1]) / r,
            "wheel_reference": reference_position(k * plan.period) / r,
        }
        duty, following = update(self.law, self.memory, signals)
        counts = counts_of(duty, plan.command_limit, plan.full_scale)
        applied = counts / plan.full_scale
        # a lane that fell is frozen, and the law keeps reading its frozen state: not counted
        limited = (np.abs(duty) > plan.command_limit) & ~self.fell
        if after_push:
            self.saturated += limited
        if in_hold:
            self.saturated_hold += limited
        self.memory = {
            name: (applied if is_applied else following[name])
            for name, _, is_applied in self.law.memory
        }
        self.commands.append(applied)
        for i in range(len(tm.offsets) - 1):
            if i == tm.apply_cut:
                held = len(self.commands) - 1 - tm.compute_periods
                self.active = self.commands[held] if held >= 0 else np.zeros(self.lanes)
            self.x = (
                np.matmul(self.phis[i], self.x[:, :, None])[:, :, 0]
                + self.gams[i] * self.active[:, None]
            )
            self._freeze(after_push, k * plan.period + tm.offsets[i + 1])
            if tm.snapshot_cut == i + 1:
                self.snaps[k] = self.x.copy()
        self.snaps.pop(k - tm.sensor_periods - 3, None)


def _segments(plan: Plan, tm: Timing) -> tuple[Any, list[Any], list[Any]]:
    radius = np.array([p["wheel_radius"] for p in plan.points])
    lengths = [b - a for a, b in zip(tm.offsets, tm.offsets[1:], strict=False)]
    phis = [np.empty((len(plan.points), 4, 4)) for _ in lengths]
    gams = [np.empty((len(plan.points), 4)) for _ in lengths]
    for lane, values in enumerate(plan.points):
        a, b = continuous(values)
        for i, length in enumerate(lengths):
            phi, gamma = _held(a, b, length)
            phis[i][lane], gams[i][lane] = phi, gamma[:, 0]
    return radius, phis, gams


def run(plan: Plan, *, rate_offset: float = 0.0) -> Result:
    """Step every plant point of ``plan`` through the timeline, and read the two numbers off.

    Never raises on a diverging loop: a point whose tilt passes 70° (or whose state stops being
    finite) is frozen there and reported as having fallen. ``rate_offset`` is added to every
    lane's initial tilt rate: 0 for the run, :data:`SENSITIVITY_RATE_OFFSET` for the second.
    """
    tm = timing(plan.period, plan.sensor_delay, plan.compute_delay)
    u = updates(plan.period)
    with np.errstate(all="ignore"):
        radius, phis, gams = _segments(plan, tm)
        sim = _Sim(plan, radius, phis, gams, tm, rate_offset)
        wanted = _information_indices(plan.period, u)
        speeds: dict[int, Any] = {}
        for k in range(u.push):
            if k in wanted:
                speeds[k] = sim.x[:, 3].copy()
            sim.period(k, in_hold=k >= u.window_first, after_push=False)
        fell_before = sim.fell.copy()
        fell_at = sim.fell_at.copy()
        speed_at_push = np.where(fell_before, np.nan, sim.x[:, 3])
        saturated_hold = sim.saturated_hold.copy()
        kicks = np.repeat([PUSH_RATE * (1.0 + b) for b in PUSH_BAND], sim.lanes)
        sim.branch(len(PUSH_BAND), kicks)
        for k in range(u.push, u.push + u.observed):
            sim.period(k, in_hold=False, after_push=True)
    lanes = len(plan.points)
    peak = np.degrees(sim.peak).reshape(len(PUSH_BAND), lanes)
    peak = np.where(fell_before[None, :], np.nan, peak)
    window = [k for k in range(u.window_first, u.push)]
    speed, settled = _window_numbers(speeds, window, plan.period, lanes)
    speed = np.where(fell_before, np.nan, speed)
    means = {
        t: np.where(
            fell_at < t,  # False for NaN: a lane that never fell keeps its mean
            np.nan,
            _mean_over(speeds, _indices_before(t, plan.period), lanes),
        )
        for t in (*INFORMATION_TIMES, PUSH_TIME)
    }
    return Result(
        speed=speed,
        means=means,
        settled=np.where(fell_before, np.nan, settled),
        speed_at_push=speed_at_push,
        fell_before=fell_before,
        fell_at=fell_at,
        saturated_hold=saturated_hold,
        peak=peak,
        saturated_push=sim.saturated.reshape(len(PUSH_BAND), lanes),
        fell_after=sim.fell.reshape(len(PUSH_BAND), lanes) & ~fell_before[None, :],
        fell_at_push=np.where(
            fell_before[None, :], np.nan, sim.fell_at.reshape(len(PUSH_BAND), lanes)
        ),
        ceiling=np.array([ceiling(p, plan.command_limit) for p in plan.points]),
        timing=tm,
    )


def _indices_before(t: float, period: float) -> list[int]:
    """The updates in the SPEED_AVERAGE before time ``t``."""
    eps = INDEX_TOLERANCE
    first = math.ceil((t - SPEED_AVERAGE) / period - eps)
    last = math.ceil(t / period - eps)
    return list(range(max(first, 0), last))


def _information_indices(period: float, u: Updates) -> set[int]:
    wanted: set[int] = set(range(u.window_first, u.push))
    for t in (*INFORMATION_TIMES, PUSH_TIME):
        wanted.update(i for i in _indices_before(t, period) if i < u.push)
    return wanted


def _mean_over(speeds: dict[int, Any], indices: list[int], lanes: int) -> Any:
    if not indices:
        return np.full(lanes, np.nan)
    return np.mean([speeds[i] for i in indices], axis=0)


def _window_numbers(
    speeds: dict[int, Any], window: list[int], period: float, lanes: int
) -> tuple[Any, Any]:
    """The lowest sliding mean over the hold window, and the second half's mean less the first's."""
    if not window:
        return np.full(lanes, np.nan), np.full(lanes, np.nan)
    series = np.array([speeds[i] for i in window])
    n = max(1, min(round(SPEED_AVERAGE / period), len(window)))
    total = np.vstack([np.zeros((1, lanes)), np.cumsum(series, axis=0)])
    lowest = ((total[n:] - total[:-n]) / n).min(axis=0)
    half = len(window) // 2
    if half == 0:
        return lowest, np.full(lanes, np.nan)
    settled = series[len(window) - half :].mean(axis=0) - series[:half].mean(axis=0)
    return lowest, settled
