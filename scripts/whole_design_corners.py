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
  assumption decides a verdict.

The bounds are the reference brief's for the criteria the scorer judges, written here as the
fixture rows write them; this is a measuring instrument, not a tier's task. The default answer
is the kit's published balancing controller as its code writes it (``KIT_ANSWER``), with the
gyro's datasheet sensitivity and the encoder counts per wheel revolution from the tooth
counts stated, as a native answer must state them.

Run with the evaluation group: ``uv run --group evaluation python
scripts/whole_design_corners.py [--plant PATH] [--answer PATH]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from physgate.evaluation.whole import loop
from physgate.evaluation.whole.answer import parse_whole_run
from physgate.evaluation.whole.convert import ScaleFactor, to_si
from physgate.evaluation.whole.plant import LOOP_INPUTS, nominal, parse_plant, ranged
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
        for end, value in (("low", p.low), ("high", p.high)):
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
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report for the files named, the draft plant and the kit's answer by default."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--plant", type=Path, default=DRAFT)
    parser.add_argument("--answer", type=Path, default=None)
    args = parser.parse_args(argv)
    answer = KIT_ANSWER if args.answer is None else json.loads(args.answer.read_text())
    report = judge(args.plant.read_bytes(), answer)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
