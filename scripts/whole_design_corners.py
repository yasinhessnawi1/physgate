"""The whole-design scorer's corner counts on a plant file: every predicate, every corner.

Evidence, recorded so that it can be rerun whenever the plant's values or ranges change. It
judges one whole-run answer on one plant parameter file and prints a JSON report:

- ``plant`` and ``answer``: what was judged, each by its SHA-256;
- ``outcome``: the scenario's;
- ``predicates``: for each criterion judged, its verdict, its value at the plant's nominal
  values, and for a computed one how many corners of the ranges it reads there are, how many
  pass, how many leave the loop unstable, and which parameters range;
- ``one_at_a_time``: each ranged parameter the balance loop reads, moved alone to the two
  ends of its range with every other at its value, and the loop's margins there: which
  assumption decides a verdict;
- ``extremes``: for each margin, over every corner of the ranges the loop reads, how many
  corners are stable, and the worst and the best stable corner (worst: the smallest phase
  and upward gain margins, the largest downward one) with its value and the corner itself
  (a margin with no finite value at a corner is left out of its worst and best).

With ``--region`` it prints instead the region of the plant's parameters in which the
answer's loop is stable and meets the brief's margins (:func:`region`): a grid over the
parameters no source gives (the centre of mass's height, the body's inertia and the rotor's),
each grid point judged with every other parameter at its value and at every corner of the
other ranges. That is evidence for a question the owner rules on (whether a controller known
to balance the real kit may bound those parameters); the script applies nothing.

With ``--bound`` it prints the bound the owner's ruling of 13.11.2026 admits (:func:`bound`):
"the real kit balances with the published controller" bounds the plant as stability evidence
only, never as evidence of a margin. Over a grid of the parameters no source gives, each grid
point is judged with the answer's loop at the other ranged parameters' values and at every
corner of their ranges as sourced, with the answer's own delays and with none. A point is
admitted when the loop is stable at any of those: the real robot is one point, so the evidence
rules a value out only where no combination the ranges allow is stable. A parameter's bound is
the span of its admitted grid values, widened to the next grid value outward on each side (the
true edge lies between the two; the bound never claims more than the grid shows), and the
wider of the two delays' bounds is the one used. The stronger reading (a point stable at every
corner) is reported beside it and not used. The plant file's ``bounded`` ranges are copied from
this report, which they name by its SHA-256.

The bounds are the reference brief's for the criteria the scorer judges, written here as the
fixture rows write them; this is a measuring instrument, not a tier's task. The default answer
is the kit's published balancing controller as its code writes it (``KIT_ANSWER``), with the
gyro's datasheet sensitivity and the encoder counts per wheel revolution from the tooth
counts stated, as a native answer must state them.

Run with the evaluation group: ``uv run --group evaluation python
scripts/whole_design_corners.py [--plant PATH] [--answer PATH] [--region | --bound
[--workers N]]``. The bound report is printed on one line, as recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from physgate.evaluation.whole import loop
from physgate.evaluation.whole.answer import parse_whole_run
from physgate.evaluation.whole.convert import ScaleFactor, to_si
from physgate.evaluation.whole.plant import (
    LOOP_INPUTS,
    PlantFile,
    corners,
    nominal,
    parse_plant,
    ranged,
    span,
)
from physgate.evaluation.whole.scenario import WholeDesignScenario, WholeDesignTask

#: The draft plant, the default.
DRAFT = Path(__file__).resolve().parents[1] / "src/physgate/evaluation/whole/plant_v0_draft.json"


def _m(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}


#: The kit's balancing example (Balance.h and Balance.cpp) as a native whole-run answer. The
#: delays are the gyro sample's worst age at 208 Hz and the plan's 2 ms computation budget.
KIT_ANSWER: dict[str, Any] = {
    "form": "whole_run",
    "version": 2,
    "controller": {
        "structure": "native_incremental_rising_offset",
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "update_time": _m(10, "ms"),
        "motor_speed_limit": _m(300, "count"),
        "angle_rate_ratio": _m(140, "ms"),
        "angle_response": _m(11, "1"),
        "distance_response": _m(73, "1"),
        "speed_response": _m(3300, "1"),
        "response_divisor": _m(100, "1"),
        "gear_ratio_coefficient": _m(111, "1"),
        "gyro_divisor": _m(29, "count*s/deg"),
        "angle_decay_numerator": _m(999, "1"),
        "angle_decay_denominator": _m(1000, "1"),
    },
    "parameters": {
        "update_rate": _m(100, "Hz"),
        "gyro_output_data_rate": _m(208, "Hz"),
        "gyro_full_scale": _m(1000, "deg/s"),
        "pwm_frequency": _m(20000, "Hz"),
        "pwm_full_scale": _m(400, "count"),
        "encoder_counts_per_wheel_revolution": _m(1322.9, "count"),
        "gyro_sensitivity": _m(28.571, "count*s/deg"),
    },
}


def _spec(
    criterion: str, metric: str, op: str, bound: Any, name: str | None = None
) -> dict[str, Any]:
    return {
        "name": name or metric,
        "metric": metric,
        "op": op,
        "bound": bound,
        "composes": [criterion],
    }


#: The brief's bounds for every criterion the scorer judges, and the two it cannot yet.
SPECS: list[dict[str, Any]] = [
    _spec("c5", "command_limit", "<=", _m(0.75, "1")),
    _spec("c6", "stall_current", "<=", _m(1.8, "A")),
    _spec("c9", "update_rate", "in", [_m(99, "Hz"), _m(101, "Hz")]),
    _spec("c9", "controller_rate", "in", [_m(99, "Hz"), _m(101, "Hz")]),
    _spec("c11", "gyro_output_data_rate", "in", [_m(208, "Hz"), _m(208, "Hz")]),
    _spec("c11", "gyro_full_scale", "in", [_m(1000, "deg/s"), _m(1000, "deg/s")]),
    _spec("c12", "pwm_frequency", "in", [_m(19800, "Hz"), _m(20200, "Hz")]),
    _spec("c12", "pwm_full_scale", "in", [_m(400, "count"), _m(400, "count")]),
    _spec(
        "c13",
        "encoder_counts_per_wheel_revolution",
        "in",
        [_m(1322, "count"), _m(1324, "count")],
    ),
    _spec("c15", "phase_margin", ">=", _m(30, "deg")),
    _spec("c16", "gain_margin_upward", ">=", _m(2, "1")),
    _spec("c16", "gain_margin_downward", "<=", _m(0.5, "1")),
    _spec("c17", "balanced_speed", ">=", _m(1.2, "m/s")),
    _spec("c18", "push_recovery_tilt", "<=", _m(70, "deg")),
    _spec("c19", "coefficient_difference", "<=", _m(0, "1")),
]


def _number(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _margins_at(values: dict[str, float], answer: dict[str, Any]) -> dict[str, Any]:
    read = parse_whole_run(json.dumps(answer).encode())
    radius = ScaleFactor("wheel_radius", values["wheel_radius"], "m", "the plant's")
    m = loop.margins(values, to_si(read.controller, read.parameters, wheel_radius=radius))
    return {
        "stable": m.stable,
        "phase_margin": _number(m.phase_margin),
        "gain_margin_upward": _number(m.upward),
        "gain_margin_downward": _number(m.downward),
    }


#: The margins, each with the sense in which a larger value is better (True) or worse.
MARGINS: dict[str, bool] = {
    "phase_margin": True,
    "gain_margin_upward": True,
    "gain_margin_downward": False,
}
#: The brief's bound on each margin (criteria 15 and 16), as :data:`SPECS` writes them.
BOUNDS: dict[str, float] = {
    s["metric"]: float(s["bound"]["value"]) for s in SPECS if s["metric"] in MARGINS
}
#: The region's default axes: the loop's parameters no source gives, with the number of
#: grid points across each one's stated range (the rotor's spaced geometrically).
REGION_AXES: dict[str, int] = {"com_height": 12, "body_inertia": 7, "rotor_inertia": 5}


def _extremes(parsed: PlantFile, answer: dict[str, Any]) -> dict[str, Any]:
    varied = ranged(parsed, LOOP_INPUTS)
    judged = []
    for corner in corners(parsed, LOOP_INPUTS):
        m = _margins_at(corner, answer)
        if m["stable"]:
            judged.append(({n: corner[n] for n in varied}, m))
    out: dict[str, Any] = {}
    for metric, larger_is_better in MARGINS.items():
        rows = [(at, m[metric]) for at, m in judged if m[metric] is not None]
        if not rows:
            out[metric] = {"stable_corners": len(judged), "worst": None, "best": None}
            continue
        low = min(rows, key=lambda row: row[1])
        high = max(rows, key=lambda row: row[1])
        worst, best = (low, high) if larger_is_better else (high, low)
        out[metric] = {
            "stable_corners": len(judged),
            "worst": {"value": worst[1], "at": worst[0]},
            "best": {"value": best[1], "at": best[0]},
        }
    return out


def _meets(m: dict[str, Any]) -> bool:
    if not m["stable"]:
        return False
    for metric, larger_is_better in MARGINS.items():
        value = m[metric]
        if value is None:
            # A margin with no finite value: no crossover (phase), or none found within the
            # search limit (gain); either way the loop is not short of it.
            continue
        if larger_is_better and value < BOUNDS[metric]:
            return False
        if not larger_is_better and value > BOUNDS[metric]:
            return False
    return True


def _grid(low: float, high: float, points: int, geometric: bool) -> list[float]:
    if low == high or points == 1:
        return [low]
    if geometric:
        return [low * (high / low) ** (i / (points - 1)) for i in range(points)]
    return [low + (high - low) * i / (points - 1) for i in range(points)]


def default_axes(plant: bytes) -> dict[str, list[float]]:
    """:data:`REGION_AXES` across the plant's stated ranges."""
    parsed = parse_plant(plant)
    return {
        name: _grid(
            parsed.parameters[name].low,
            parsed.parameters[name].high,
            points,
            geometric=name == "rotor_inertia",
        )
        for name, points in REGION_AXES.items()
    }


def region(plant: bytes, answer: dict[str, Any], axes: dict[str, list[float]]) -> dict[str, Any]:
    """The answer's loop over a grid of ``axes``, each point at nominal and at every corner.

    Each grid point sets the axes' parameters; the loop's other ranged parameters (``others``)
    are taken at their values (``nominal``) and at every corner of their ranges
    (``every_corner``). A point ``meets`` the brief when the loop is stable and every margin
    is on the right side of its bound (:data:`BOUNDS`).

    Raises:
        ValueError: an axis the balance loop does not read.
    """
    for name in axes:
        if name not in LOOP_INPUTS:
            msg = f"{name} is not a parameter the balance loop reads"
            raise ValueError(msg)
    parsed = parse_plant(plant)
    others = [n for n in ranged(parsed, LOOP_INPUTS) if n not in axes]
    base = nominal(parsed)
    names = list(axes)
    points = []
    for values in itertools.product(*(axes[n] for n in names)):
        at = dict(zip(names, values, strict=True))
        here = {**base, **at}
        m = _margins_at(here, answer)
        count, stable, meets = 0, True, True
        for ends in itertools.product((0, 1), repeat=len(others)):
            corner = dict(here)
            for name, end in zip(others, ends, strict=True):
                p = parsed.parameters[name]
                corner[name] = p.high if end else p.low
            c = _margins_at(corner, answer)
            count += 1
            stable = stable and bool(c["stable"])
            meets = meets and _meets(c)
        points.append(
            {
                "at": at,
                "nominal": {**m, "meets": _meets(m)},
                "every_corner": {"corners": count, "stable": stable, "meets": meets},
            }
        )
    return {
        "axes": axes,
        "others": others,
        "bounds": dict(BOUNDS),
        "points": points,
        "summary": {
            "points": len(points),
            "stable_at_nominal": sum(bool(p["nominal"]["stable"]) for p in points),
            "meets_at_nominal": sum(bool(p["nominal"]["meets"]) for p in points),
            "stable_at_every_corner": sum(bool(p["every_corner"]["stable"]) for p in points),
            "meets_at_every_corner": sum(bool(p["every_corner"]["meets"]) for p in points),
        },
    }


#: The bound's grid: the loop's parameters no source gives, with the number of grid points
#: across each one's stated range (the rotor's spaced geometrically). The centre of mass's
#: height is the finest, about 2 mm a step, since the stability evidence bounds it most.
BOUND_AXES: dict[str, int] = {"com_height": 37, "body_inertia": 7, "rotor_inertia": 9}
#: What the bound report says it is, in plain words.
BOUND_RULE = (
    "Stability evidence only (owner, 13.11.2026): the real kit balances with the published "
    "controller, so a grid value is ruled out only where the loop is unstable at every "
    "combination the stated ranges allow (the other unsourced grid values, and the sourced "
    "parameters at their values and at every corner of their ranges). Each bound is the span "
    "of the admitted grid values widened to the next grid value outward; the wider of the "
    "bounds with the answer's own delays and with none is used. Never evidence of a margin."
)


def answer_digest(answer: dict[str, Any]) -> str:
    """The SHA-256 of ``answer`` as the reports write it."""
    return hashlib.sha256(json.dumps(answer).encode()).hexdigest()


def sourced_digest(plant: bytes) -> str:
    """The SHA-256 of every parameter's value and range as sourced or assumed, bounds aside."""
    parsed = parse_plant(plant)
    doc = {n: [p.value, p.low, p.high] for n, p in parsed.parameters.items()}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def delay_variants(answer: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """The delays the bound is computed with: the answer's own (assumed), and none.

    Raises:
        ValueError: a delay not stated in seconds.
    """
    c = answer["controller"]
    own = []
    for key in ("sensor_delay", "compute_delay"):
        if c[key]["unit"] != "s":
            msg = f"the answer's {key} is in {c[key]['unit']!r}; the bound reads seconds"
            raise ValueError(msg)
        own.append(float(c[key]["value"]))
    return {"assumed": (own[0], own[1]), "zero": (0.0, 0.0)}


def with_delays(answer: dict[str, Any], sensor: float, compute: float) -> dict[str, Any]:
    """A copy of ``answer`` with its two delays set, in seconds; nothing else changed."""
    out: dict[str, Any] = json.loads(json.dumps(answer))
    out["controller"]["sensor_delay"] = _m(sensor, "s")
    out["controller"]["compute_delay"] = _m(compute, "s")
    return out


def admitted(stable: Sequence[bool]) -> tuple[bool, bool]:
    """A point's two readings: stable at any judged set (admitted), and at every one."""
    return (any(stable), all(stable))


def interval(axis: Sequence[float], admits: Sequence[bool]) -> tuple[float, float]:
    """The admitted span of ``axis``, widened to the next grid value outward on each side.

    Raises:
        ValueError: no value admitted (the evidence and the ranges contradict).
    """
    found = [i for i, a in enumerate(admits) if a]
    if not found:
        msg = "no grid value is admitted: the evidence and the stated ranges contradict"
        raise ValueError(msg)
    return (axis[max(found[0] - 1, 0)], axis[min(found[-1] + 1, len(axis) - 1)])


def wider(bounds: Iterable[tuple[float, float] | None]) -> tuple[float, float]:
    """The least restrictive of ``bounds``: the lowest low and the highest high.

    A ``None`` (a reading under which the evidence and the ranges contradict) bounds nothing.

    Raises:
        ValueError: every reading contradicts.
    """
    found = [b for b in bounds if b is not None]
    if not found:
        msg = "every reading contradicts the stated ranges: nothing to bound"
        raise ValueError(msg)
    return (min(b[0] for b in found), max(b[1] for b in found))


def _interval_or_none(axis: Sequence[float], admits: Sequence[bool]) -> list[float] | None:
    try:
        return list(interval(axis, admits))
    except ValueError:
        return None


def bounds_from_points(
    axes: dict[str, list[float]], points: dict[str, list[list[Any]]]
) -> dict[str, Any]:
    """Each axis's bound, read off the judged points of every delay variant.

    A point row is its axis values in order, then its two readings (:func:`admitted`). A grid
    value is admitted when any point at it is; the stronger reading likewise from the second.
    """
    names = list(axes)
    k = len(names)
    out: dict[str, Any] = {}
    for i, name in enumerate(names):
        axis = axes[name]
        per: dict[str, list[float] | None] = {}
        every: dict[str, list[float] | None] = {}
        for variant, rows in points.items():
            per[variant] = _interval_or_none(
                axis, [any(r[i] == v and r[k] for r in rows) for v in axis]
            )
            every[variant] = _interval_or_none(
                axis, [any(r[i] == v and r[k + 1] for r in rows) for v in axis]
            )
        used = wider(None if b is None else (b[0], b[1]) for b in per.values())
        out[name] = {
            "sourced": [axis[0], axis[-1]],
            **per,
            "used": list(used),
            "every_corner": every,
        }
    return out


def bound_axes(plant: bytes) -> dict[str, list[float]]:
    """:data:`BOUND_AXES` across the plant's stated ranges, each grid's ends its range's own."""
    parsed = parse_plant(plant)
    out = {}
    for name, n in BOUND_AXES.items():
        p = parsed.parameters[name]
        grid = _grid(p.low, p.high, n, geometric=name == "rotor_inertia")
        grid[0], grid[-1] = p.low, p.high
        out[name] = grid
    return out


def _point(
    job: tuple[dict[str, float], list[float], list[tuple[str, float, float]], Any],
) -> list[Any]:
    here, at, others, answer = job
    stable: list[bool] = []
    seen = {True: False, False: False}
    sets = itertools.chain(
        [here],
        (
            {
                **here,
                **{
                    n: (high if end else low)
                    for (n, low, high), end in zip(others, ends, strict=True)
                },
            }
            for ends in itertools.product((0, 1), repeat=len(others))
        ),
    )
    for values in sets:
        ok = bool(_margins_at(values, answer)["stable"])
        stable.append(ok)
        seen[ok] = True
        if seen[True] and seen[False]:
            break
    return [*at, *admitted(stable)]


def bound(
    plant: bytes, answer: dict[str, Any], axes: dict[str, list[float]], workers: int = 1
) -> dict[str, Any]:
    """The bound the kit's stability evidence admits on ``axes``, as the module says.

    Each grid point is judged at the other ranged parameters' values and at every corner of
    their ranges **as sourced** (never as bounded), with the answer's delays and with none.

    Raises:
        ValueError: an axis the balance loop does not read.
    """
    for name in axes:
        if name not in LOOP_INPUTS:
            msg = f"{name} is not a parameter the balance loop reads"
            raise ValueError(msg)
    parsed = parse_plant(plant)
    others = [
        n
        for n in LOOP_INPUTS
        if n not in axes and parsed.parameters[n].low < parsed.parameters[n].high
    ]
    ranges = [(n, parsed.parameters[n].low, parsed.parameters[n].high) for n in others]
    base = nominal(parsed)
    names = list(axes)
    variants = delay_variants(answer)
    points: dict[str, list[list[Any]]] = {}
    for variant, (sensor, compute) in variants.items():
        judged = with_delays(answer, sensor, compute)
        jobs = [
            ({**base, **dict(zip(names, at, strict=True))}, list(at), ranges, judged)
            for at in itertools.product(*(axes[n] for n in names))
        ]
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                points[variant] = list(pool.map(_point, jobs, chunksize=8))
        else:
            points[variant] = [_point(job) for job in jobs]
    bounds = bounds_from_points(axes, points)
    return {
        "form": "stability_bound",
        "rule": BOUND_RULE,
        "answer": {
            "sha256": answer_digest(answer),
            "delays": {v: list(d) for v, d in variants.items()},
        },
        "plant_sourced": {"sha256": sourced_digest(plant)},
        "axes": axes,
        "others": others,
        "points": points,
        "bounds": bounds,
        "applies": [n for n, b in bounds.items() if b["used"] != b["sourced"]],
    }


def judge(plant: bytes, answer: dict[str, Any]) -> dict[str, Any]:
    """The report on ``answer`` judged on the plant file ``plant``, as the module says."""
    task = WholeDesignTask.model_validate_json(
        json.dumps(
            {
                "id": "whole.corners",
                "requirements": sorted({c for s in SPECS for c in s["composes"]}),
                "specs": SPECS,
            }
        )
    )
    raw_answer = json.dumps(answer).encode()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(os.path.realpath(tmp))
        (root / "whole_run.json").write_bytes(raw_answer)
        record = WholeDesignScenario(task, plant, root=root).record(root / "whole_run.json")
    predicates = []
    for row in record["specs"]:
        corners = row.get("corners")
        measured = row.get("measured")
        predicates.append(
            {
                "criterion": row["composes"][0],
                "metric": row["metric"],
                "kind": row["kind"],
                "verdict": row["verdict"],
                "nominal": None if measured is None else measured["value"],
                "corners": None
                if corners is None
                else {k: corners[k] for k in ("count", "passing", "unstable", "ranged")},
                "reason": row["reason"],
            }
        )
    parsed = parse_plant(plant)
    base = nominal(parsed)
    moved = []
    for name in ranged(parsed, LOOP_INPUTS):
        p = parsed.parameters[name]
        ends: dict[str, Any] = {"parameter": name, "unit": p.unit}
        for end, value in zip(("low", "high"), span(p), strict=True):
            values = dict(base)
            values[name] = value
            ends[end] = {"value": value, **_margins_at(values, answer)}
        moved.append(ends)
    return {
        "plant": {"sha256": hashlib.sha256(plant).hexdigest(), "status": parsed.status},
        "answer": {
            "structure": record.get("structure"),
            "sha256": hashlib.sha256(raw_answer).hexdigest(),
        },
        "outcome": record["outcome"],
        "predicates": predicates,
        "one_at_a_time": moved,
        "extremes": _extremes(parsed, answer),
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report for the files named, the draft plant and the kit's answer by default."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--plant", type=Path, default=DRAFT)
    parser.add_argument("--answer", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--region", action="store_true")
    mode.add_argument("--bound", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    answer = KIT_ANSWER if args.answer is None else json.loads(args.answer.read_text())
    plant = args.plant.read_bytes()
    if args.bound:
        report = bound(plant, answer, bound_axes(plant), workers=args.workers)
        print(json.dumps(report, separators=(",", ":")))
        return 0
    report = region(plant, answer, default_axes(plant)) if args.region else judge(plant, answer)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
