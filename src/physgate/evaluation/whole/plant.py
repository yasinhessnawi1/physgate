"""The validation environment's plant: its parameters, each sourced or an assumption with a range.

The whole-design scorer judges an answer against a plant it never takes from the answer. This
module holds that plant's parameter file and the derivations made from it. Every parameter is
a number with its unit, its source (a criterion of the brief, a row of the parts sheet, a
vendor page) or the word ``assumption``, and a stated range ``[low, high]``: a sourced value's
published tolerance (a point when none is published), an assumption's plausible span with the
measurement that would replace it. No parameter is fitted to make a criterion pass.

A verdict rests only on what the sources fix. A predicate that reads the plant is evaluated at
the nominal values and at every corner of the ranges of the parameters it reads (a range
narrowed by the kit's stability evidence is judged as narrowed, :class:`Bound`); where its
outcome changes inside those ranges the scorer reports it ``unscored``, with the reason, and
never pass or fail (:mod:`physgate.evaluation.whole.scenario`).

**The model.** Planar and linearised about upright: a body of mass ``m`` with its centre of
mass ``h`` above the axle and inertia ``I_b`` about it; two wheels rolling without slip, of
total mass ``m_w`` and inertia ``I_w``; each wheel driven by a DC gearmotor through the whole
ratio ``N``, its rotor's inertia ``J_r`` reflected as ``N²·J_r`` onto the motion of the wheel
relative to the body. With ``a = m·h·r``, ``b = (m + m_w)·r² + I_w``, ``I_p = I_b + m·h²`` and
``J = 2·N²·J_r``, in the wheel angle ``φ`` and the tilt ``θ``:

    (b + J)·φ̈ + (a − J)·θ̈ = T
    (a − J)·φ̈ + (I_p + J)·θ̈ − m·g·h·θ = −T

where ``T`` is the two motors' torque at the wheels, ``T = 2·(K_t/R)·(u·V − K_e·(φ̇ − θ̇))``,
``u`` the duty, ``V`` the pack voltage, ``R``, ``K_t`` and ``K_e`` the winding resistance and
the torque and back-EMF constants at the wheel. The gearbox's Coulomb friction is not linear
and is left out of the powered loop; it enters only the unpowered fall.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

#: Standard gravity, m/s², by definition.
GRAVITY = 9.80665
#: The word a parameter carries in place of a source when nothing publishes it.
ASSUMPTION = "assumption"

#: Every parameter of the plant, with the one unit it is given in.
PLANT_UNITS: dict[str, str] = {
    "pack_voltage": "V",
    "wheel_radius": "m",
    "gear_ratio": "1",
    "external_stage_ratio": "1",
    "motor_rated_voltage": "V",
    "motor_stall_torque": "N*m",
    "motor_stall_current": "A",
    "motor_no_load_speed": "rad/s",
    "motor_no_load_current": "A",
    "kit_mass": "kg",
    "wheel_mass": "kg",
    "cell_mass": "kg",
    "cell_count": "1",
    "com_height": "m",
    "body_inertia": "kg*m**2",
    "wheel_inertia_factor": "1",
    "rotor_inertia": "kg*m**2",
    "gearbox_friction": "N*m",
}

#: The parameters the stall current reads (brief criterion 6).
STALL_INPUTS = ("pack_voltage", "motor_rated_voltage", "motor_stall_current")
#: The parameters the rigid bodies read: geometry, masses and inertias.
MECHANICAL_INPUTS = (
    "wheel_radius",
    "gear_ratio",
    "kit_mass",
    "wheel_mass",
    "cell_mass",
    "cell_count",
    "com_height",
    "body_inertia",
    "wheel_inertia_factor",
    "rotor_inertia",
)
#: The parameters the motors read.
ELECTRICAL_INPUTS = (
    "pack_voltage",
    "external_stage_ratio",
    "motor_rated_voltage",
    "motor_stall_torque",
    "motor_stall_current",
    "motor_no_load_speed",
    "motor_no_load_current",
)
#: The parameters the powered loop reads: everything but the gearbox's Coulomb friction.
LOOP_INPUTS = MECHANICAL_INPUTS + ELECTRICAL_INPUTS
#: The parameters the unpowered fall reads: the rigid bodies and the gearbox's friction.
FALL_INPUTS = (*MECHANICAL_INPUTS, "gearbox_friction")

_Text = Annotated[str, StringConstraints(min_length=1, max_length=600)]
_Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


class Bound(_Frozen):
    """A range narrowed by stability evidence, kept beside the range as sourced or assumed.

    The owner ruled (13.11.2026) that "the real kit balances with the published controller"
    may bound the plant, as stability evidence only, never as evidence of a margin. The
    bound is computed by ``scripts/whole_design_corners.py --bound``, never typed in:
    ``report`` is the SHA-256 of the report it was read from, and ``evidence`` says in plain
    words what bounded the range and names that report.
    """

    low: float
    high: float
    evidence: _Text
    report: _Sha256


class Parameter(_Frozen):
    """One plant parameter: its value and range in its unit, and where it comes from.

    ``source`` cites a criterion, a parts-sheet row or a vendor document, or is
    ``assumption``. A cited value says in ``locator`` where in its source the number is read
    (a page, a table, a row, a URL); an assumption says in ``reason`` what bounds its range
    and in ``measure_by`` what measurement would replace it. ``bounded``, where present, is
    the range the stability evidence leaves (:class:`Bound`); ``low`` and ``high`` stay as
    sourced or assumed, so a reader sees what the evidence did.
    """

    value: float
    unit: str
    low: float
    high: float
    source: _Text
    reason: _Text
    locator: _Text | None = None
    measure_by: _Text | None = None
    bounded: Bound | None = None


def span(p: Parameter) -> tuple[float, float]:
    """The range the scorer judges over: the bounded one where there is one, else the stated."""
    if p.bounded is not None:
        return (p.bounded.low, p.bounded.high)
    return (p.low, p.high)


class PlantFile(_Frozen):
    """The plant's parameter file: every parameter of :data:`PLANT_UNITS`, and nothing else."""

    form: Literal["whole_design_plant"]
    version: Literal[1]
    status: Literal["draft", "frozen"]
    fall_terminals: Literal["open"]
    parameters: dict[str, Parameter] = Field(min_length=1)


class PlantError(ValueError):
    """A plant parameter file that does not hold to its schema."""


def parse_plant(raw: bytes) -> PlantFile:
    """``raw`` as a plant parameter file, every parameter checked, or refused with the reason.

    Raises:
        PlantError: not the schema; a parameter missing or unknown, in another unit, outside
            its own range, or a value not positive; a parameter with no source, a cited one
            with no locator, an assumption with no measurement named, or, in a frozen plant,
            an assumption held at a point (its outcome would be scored as if it were known);
            a bounded range with no evidence, or an evidence line that names no report, or a
            bound outside the stated range or without the value.
    """
    try:
        plant = PlantFile.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"not a plant parameter file: {exc.errors()[0]['msg']}"
        raise PlantError(msg) from exc
    names = set(plant.parameters)
    if names != set(PLANT_UNITS):
        msg = (
            f"the plant names {sorted(names - set(PLANT_UNITS))} it has no use for and lacks "
            f"{sorted(set(PLANT_UNITS) - names)}"
        )
        raise PlantError(msg)
    for name, p in plant.parameters.items():
        if p.unit != PLANT_UNITS[name]:
            msg = f"{name} is in {p.unit!r}; it is given in {PLANT_UNITS[name]!r}"
            raise PlantError(msg)
        if not 0 < p.low <= p.value <= p.high:
            msg = f"{name} is {p.value} in [{p.low}, {p.high}]; each is positive, low first"
            raise PlantError(msg)
        if not p.source.strip():
            msg = f"{name} names no source; it cites one or is an {ASSUMPTION}"
            raise PlantError(msg)
        _check_bound(name, p)
        if p.source.strip().lower() != ASSUMPTION:
            if p.locator is None or not p.locator.strip():
                msg = f"{name} cites {p.source!r} and names no locator in it"
                raise PlantError(msg)
            continue
        if p.measure_by is None:
            msg = f"{name} is an assumption and names no measurement that would replace it"
            raise PlantError(msg)
        low, high = span(p)
        if plant.status == "frozen" and low == high:
            msg = f"{name} is an assumption held at a point in a frozen plant; it ranges"
            raise PlantError(msg)
    return plant


def _check_bound(name: str, p: Parameter) -> None:
    b = p.bounded
    if b is None:
        return
    if not b.evidence.strip():
        msg = f"{name} is bounded and names no evidence for it"
        raise PlantError(msg)
    if b.report not in b.evidence:
        msg = f"{name} is bounded and its evidence names no report it was computed in"
        raise PlantError(msg)
    if not p.low <= b.low <= p.value <= b.high <= p.high:
        msg = (
            f"{name} is bounded to [{b.low}, {b.high}]; a bound lies inside its stated range "
            f"[{p.low}, {p.high}] and holds its value {p.value}"
        )
        raise PlantError(msg)


def nominal(plant: PlantFile) -> dict[str, float]:
    """Every parameter at its stated value."""
    return {name: p.value for name, p in plant.parameters.items()}


def ranged(plant: PlantFile, names: tuple[str, ...]) -> tuple[str, ...]:
    """Those of ``names`` whose judged range (:func:`span`) is more than a point, in order."""
    return tuple(n for n in names if (s := span(plant.parameters[n]))[0] < s[1])


def corners(plant: PlantFile, names: tuple[str, ...]) -> Iterator[dict[str, float]]:
    """Every corner of the judged ranges (:func:`span`) of ``names``, the others at their values.

    Each corner is a full parameter set; a parameter whose range is a point stays at it. With
    no ranged parameter among ``names`` there is one corner, the nominal set.
    """
    base = nominal(plant)
    varied = ranged(plant, names)
    for ends in itertools.product((0, 1), repeat=len(varied)):
        corner = dict(base)
        for name, end in zip(varied, ends, strict=True):
            low, high = span(plant.parameters[name])
            corner[name] = high if end else low
        yield corner


def assumptions(plant: PlantFile) -> list[tuple[str, Parameter]]:
    """The parameters no source gives, each with its range and what would measure it."""
    return [
        (name, p) for name, p in plant.parameters.items() if p.source.strip().lower() == ASSUMPTION
    ]


@dataclass(frozen=True)
class Motor:
    """The motors' derived quantities at the wheel, from one parameter set (D1-D9).

    - ``R`` from the rated voltage over the stall current (the parts sheet's stall figures are
      extrapolated, so this is a limit);
    - ``K_t`` at the gearmotor's output from the stall torque over the stall current less the
      no-load current, and ``K_e`` from the rated voltage less the no-load current's drop over
      the no-load speed; each taken to the wheel through the external stage, its efficiency 1;
    - the wheel's stall torque and no-load speed at the pack voltage.
    """

    resistance: float
    torque_constant: float
    back_emf_constant: float
    pack_voltage: float
    wheel_stall_torque: float
    wheel_no_load_speed: float


def motor(values: Mapping[str, float]) -> Motor:
    """The motors of the parameter set ``values``, reading only :data:`ELECTRICAL_INPUTS`."""
    v = values
    resistance = v["motor_rated_voltage"] / v["motor_stall_current"]
    stage = v["external_stage_ratio"]
    kt = v["motor_stall_torque"] / (v["motor_stall_current"] - v["motor_no_load_current"]) * stage
    ke = (
        (v["motor_rated_voltage"] - v["motor_no_load_current"] * resistance)
        / v["motor_no_load_speed"]
        * stage
    )
    return Motor(
        resistance=resistance,
        torque_constant=kt,
        back_emf_constant=ke,
        pack_voltage=v["pack_voltage"],
        wheel_stall_torque=kt * (v["pack_voltage"] / resistance - v["motor_no_load_current"]),
        wheel_no_load_speed=(v["pack_voltage"] - v["motor_no_load_current"] * resistance) / ke,
    )


def stall_current(values: Mapping[str, float], duty: float) -> float:
    """Each motor's stall current, in A, at the largest average voltage ``duty`` commands."""
    resistance = values["motor_rated_voltage"] / values["motor_stall_current"]
    return duty * values["pack_voltage"] / resistance


@dataclass(frozen=True)
class Bodies:
    """The rigid bodies, from one parameter set (D10, D11), and the equations' coefficients.

    The body's mass is the kit's less its two wheels plus its cells; the wheels' inertia is
    the factor times ``m_w·r²`` (½ a disc, 1 a ring); the rotors' inertia is reflected through
    the whole ratio, both motors. ``a``, ``b``, ``i_p``, ``j`` and ``mgh`` are the
    coefficients of the equations in the module's docstring.
    """

    body_mass: float
    wheels_mass: float
    wheels_inertia: float
    wheel_radius: float
    a: float
    b: float
    i_p: float
    j: float
    mgh: float


def bodies(values: Mapping[str, float]) -> Bodies:
    """The rigid bodies of ``values``, reading only :data:`MECHANICAL_INPUTS`."""
    v = values
    wheels_mass = 2.0 * v["wheel_mass"]
    r, h = v["wheel_radius"], v["com_height"]
    m = v["kit_mass"] - wheels_mass + v["cell_count"] * v["cell_mass"]
    wheels_inertia = v["wheel_inertia_factor"] * wheels_mass * r**2
    return Bodies(
        body_mass=m,
        wheels_mass=wheels_mass,
        wheels_inertia=wheels_inertia,
        wheel_radius=r,
        a=m * h * r,
        b=(m + wheels_mass) * r**2 + wheels_inertia,
        i_p=v["body_inertia"] + m * h**2,
        j=2.0 * v["gear_ratio"] ** 2 * v["rotor_inertia"],
        mgh=m * GRAVITY * h,
    )


@dataclass(frozen=True)
class Fall:
    """The unpowered fall from near vertical, its ratio ``τ = θ/θ̇`` in each reading, in s.

    - ``locked``: the gearbox held by its friction, body and wheels one rigid body rolling;
    - ``geared``: the gearbox turning freely, the rotors' reflected inertia in play;
    - ``free``: the gearbox turning with no rotor inertia either (the free-wheel limit);
    - ``lock_torque_per_rad``: the torque the two gearboxes must carry, per rad of tilt, for
      the lock to hold; ``lock_angle``: the tilt, in rad, below which the friction holds it.

    The true fall lies between ``free`` and ``locked``; friction pushes it towards locked.
    """

    locked: float
    geared: float
    free: float
    lock_torque_per_rad: float
    lock_angle: float


def fall(values: Mapping[str, float]) -> Fall:
    """The fall of the parameter set ``values``, motors off with their terminals open."""
    c = bodies(values)
    i_locked = c.i_p + 2.0 * c.a + c.b

    def tau(inertia: float) -> float:
        return math.sqrt(inertia / c.mgh)

    def geared(j: float) -> float:
        return c.i_p + j - (j - c.a) ** 2 / (c.b + j)

    per_rad = (c.a + c.b) * c.mgh / i_locked
    return Fall(
        locked=tau(i_locked),
        geared=tau(geared(c.j)),
        free=tau(geared(0.0)),
        lock_torque_per_rad=per_rad,
        lock_angle=2.0 * values["gearbox_friction"] / per_rad,
    )
