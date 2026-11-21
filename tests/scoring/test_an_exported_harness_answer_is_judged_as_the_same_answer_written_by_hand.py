"""The harness arm's exported answer is judged exactly as the same answer written by hand.

Both arms meet at the answer file: whatever a harness run's graph states, exported, and the
raw agent's own file stating the same choices, are one judgement. Fixture graphs and tasks
only, judged on the frozen plant v0.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from physgate.evaluation.whole.export import export_whole_run
from physgate.evaluation.whole.scenario import WholeDesignScenario, WholeDesignTask
from physgate.state.store import Store

_FROZEN = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0.json"
#: A run's event log, recorded from the loop over its fakes, with every module recorded complete.
_FINISHED = (
    Path(__file__).resolve().parents[1] / "unit/evaluation/whole/recorded_runs/finished.jsonl"
)

#: The reference kit's balancing example as its code writes it, and the kit's settings.
NATIVE = {
    "sensor_delay": (0.0048, "s"),
    "compute_delay": (0.002, "s"),
    "update_time": (10, "ms"),
    "motor_speed_limit": (300, "count"),
    "angle_rate_ratio": (140, "ms"),
    "angle_response": (11, "1"),
    "distance_response": (73, "1"),
    "speed_response": (3300, "1"),
    "response_divisor": (100, "1"),
    "gear_ratio_coefficient": (111, "1"),
    "gyro_divisor": (29, "count*s/deg"),
    "angle_decay_numerator": (999, "1"),
    "angle_decay_denominator": (1000, "1"),
}
PARAMETERS = {
    "update_rate": (100, "Hz"),
    "output_data_rate": (208, "Hz"),
    "gyro_full_scale": (1000, "deg/s"),
    "pwm_frequency": (20000, "Hz"),
    "pwm_full_scale": (400, "count"),
    "encoder_counts_per_wheel_revolution": (1322.9, "count"),
    "gyro_sensitivity": (28.571, "count*s/deg"),
}


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _spec(name: str, metric: str, op: str, bound: Any, composes: str) -> dict[str, Any]:
    return {"name": name, "metric": metric, "op": op, "bound": bound, "composes": [composes]}


SPECS = [
    _spec("limit", "command_limit", "<=", _m(0.75, "1"), "c5"),
    _spec("stall", "stall_current", "<=", _m(1.8, "A"), "c6"),
    _spec("rate", "update_rate", "in", [_m(99, "Hz"), _m(101, "Hz")], "c9"),
    _spec("period", "controller_rate", "in", [_m(99, "Hz"), _m(101, "Hz")], "c9"),
    _spec("odr", "gyro_output_data_rate", "in", [_m(208, "Hz"), _m(208, "Hz")], "c11"),
    _spec("scale", "gyro_full_scale", "in", [_m(1000, "deg/s"), _m(1000, "deg/s")], "c11"),
    _spec("pwm", "pwm_frequency", "in", [_m(19800, "Hz"), _m(20200, "Hz")], "c12"),
    _spec("top", "pwm_full_scale", "in", [_m(400, "count"), _m(400, "count")], "c12"),
    _spec(
        "counts",
        "encoder_counts_per_wheel_revolution",
        "in",
        [_m(1322, "count"), _m(1324, "count")],
        "c13",
    ),
    _spec("same", "coefficient_difference", "<=", _m(0, "1"), "c19"),
]


def _node(node_id: str, values: dict[str, tuple[Any, str]], owner: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "module",
        "domain": owner,
        "owner_role": owner,
        "quantities": {
            n: {"value": v, "unit": u, "source": "fixture", "written_by": owner}
            for n, (v, u) in values.items()
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "none",
        "updated": "2026-11-20",
    }


def _scenario(root: Path) -> WholeDesignScenario:
    task = WholeDesignTask.model_validate_json(
        json.dumps({"id": "whole.fixture", "requirements": ["c5", "c19"], "specs": SPECS})
    )
    return WholeDesignScenario(task, _FROZEN.read_bytes(), root=root)


def _both(
    tmp_path: Path, parameters: dict[str, tuple[Any, str]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The exported answer's judgement and the same answer's, written by hand."""
    base = Path(os.path.realpath(tmp_path))
    run = base / "run"
    (run / "store").mkdir(parents=True)
    (run / "events.jsonl").write_bytes(_FINISHED.read_bytes())
    store = Store(run / "store")
    try:
        for node in (
            _node("balance.controller", NATIVE, "control"),
            _node("firmware.loop_timing", parameters, "firmware"),
        ):
            assert store.write_node(node, node["owner_role"]).accepted
    finally:
        store.close()
    root = base / "answers"
    exported = root / "harness" / "whole_run.json"
    assert export_whole_run(run, exported).status == "exported"
    by_hand = root / "raw" / "whole_run.json"
    by_hand.parent.mkdir(parents=True)
    by_hand.write_text(
        json.dumps(
            {
                "form": "whole_run",
                "version": 2,
                "controller": {
                    "structure": "native_incremental_rising_offset",
                    **{n: _m(v, u) for n, (v, u) in NATIVE.items()},
                },
                "parameters": {n: _m(v, u) for n, (v, u) in parameters.items()},
            }
        )
    )
    scenario = _scenario(root)
    return scenario.record(exported), scenario.record(by_hand)


def test_the_kit_s_design_exported_from_a_graph_is_judged_as_the_same_answer_by_hand(
    tmp_path: Path,
) -> None:
    exported, by_hand = _both(tmp_path, PARAMETERS)
    assert exported["answer_valid"] is True
    assert exported["structure"] == "native_incremental_rising_offset"
    # The export states no analysed controller, so the same-coefficients criterion is not
    # judged, exactly as it is not for the same answer by hand.
    rows = {r["name"]: r for r in exported["specs"]}
    assert {n for n, r in rows.items() if r["verdict"] != "pass"} == {"same"}
    assert rows["same"]["verdict"] == "unscored"
    assert exported["outcome"] == "unscored"
    assert exported == by_hand


def test_a_graph_value_in_another_unit_fails_the_exported_answer_as_it_fails_by_hand(
    tmp_path: Path,
) -> None:
    exported, by_hand = _both(tmp_path, {**PARAMETERS, "gyro_full_scale": (17.453, "rad/s")})
    assert exported["answer_valid"] is False
    assert exported["outcome"] == "fail"
    assert "deg/s" in exported["reason"]
    assert exported["outcome"] == by_hand["outcome"]
