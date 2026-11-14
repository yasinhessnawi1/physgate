"""A whole design is judged on its static and computed criteria, never on an unsourced value.

Fixture tiers only: the tasks, the answers and the plants are this test's own, the plants the
draft's with their ranges collapsed to points except where a row ranges one on purpose.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MODULE = "physgate.evaluation.whole.scenario"
_DRAFT = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0_draft.json"
#: A discrete LQR state feedback for the first draft's nominal plant, designed outside this
#: test; on the sourced draft's nominal plant, phase margin about 68°, gain margins about 0.45
#: and 4.1.
GOOD_GAINS = (1.6643, 0.191, 0.2853, 1.3421)


def _scenario_module() -> ModuleType:
    assert importlib.util.find_spec(_MODULE) is not None, f"{_MODULE} does not exist"
    return importlib.import_module(_MODULE)


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _plant(**ranges: tuple[float, float]) -> bytes:
    """The draft with no bound and every range a point, but those given."""
    doc = json.loads(_DRAFT.read_text())
    for name, p in doc["parameters"].items():
        p.pop("bounded", None)
        p["low"] = p["high"] = p["value"]
        if name in ranges:
            p["low"], p["high"] = ranges[name]
            if not p["low"] <= p["value"] <= p["high"]:
                p["value"] = p["low"]
    return json.dumps(doc).encode()


def _spec(
    name: str, metric: str, op: str, bound: Any, composes: str, **extra: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "metric": metric,
        "op": op,
        "bound": bound,
        "composes": [composes],
        **extra,
    }


STATIC_SPECS = [
    _spec("limit", "command_limit", "<=", _m(0.75, "1"), "c5"),
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
COMPUTED_SPECS = [
    _spec("stall", "stall_current", "<=", _m(1.8, "A"), "c6"),
    _spec("pm", "phase_margin", ">=", _m(30, "deg"), "c15"),
    _spec("up", "gain_margin_upward", ">=", _m(2, "1"), "c16"),
    _spec("down", "gain_margin_downward", "<=", _m(0.5, "1"), "c16"),
]
DYNAMIC_SPECS = [
    _spec("speed", "balanced_speed", ">=", _m(1.2, "m/s"), "c17"),
    _spec("push", "push_recovery_tilt", "<=", _m(70, "deg"), "c18"),
]


def _task(specs: list[dict[str, Any]], requirements: tuple[str, ...] = ("c5", "c15")) -> Any:
    # Read from JSON, as a tier's task file is.
    return _scenario_module().WholeDesignTask.model_validate_json(
        json.dumps({"id": "whole.fixture", "requirements": list(requirements), "specs": specs})
    )


def _feedback(gains: tuple[float, ...] = GOOD_GAINS, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "structure": "state_feedback",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "angle_gain": _m(gains[0], "1/rad"),
        "rate_gain": _m(gains[1], "s/rad"),
        "distance_gain": _m(gains[2], "1/m"),
        "speed_gain": _m(gains[3], "s/m"),
    }
    doc.update(over)
    return doc


def _native(**over: int) -> dict[str, Any]:
    doc: dict[str, Any] = {
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
    }
    for field, value in over.items():
        doc[field] = _m(value, doc[field]["unit"])
    return doc


def _answer(controller: dict[str, Any] | None = None, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "form": "whole_run",
        "version": 2,
        "controller": controller or _feedback(),
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
    doc.update(over)
    return doc


def _root(tmp_path: Path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    return root


def _judge(
    tmp_path: Path, doc: dict[str, Any], specs: list[dict[str, Any]], plant: bytes | None = None
) -> dict[str, Any]:
    root = _root(tmp_path)
    path = root / "whole_run.json"
    path.write_text(json.dumps(doc))
    scenario = _scenario_module().WholeDesignScenario(
        _task(specs), plant if plant is not None else _plant(), root=root
    )
    try:
        record: dict[str, Any] = scenario.record(path)
        outcome = scenario.score(path)
    except Exception as exc:  # a scorer never crashes on an answer: a crash is a failed row
        pytest.fail(f"the scenario raised on an answer: {exc!r}")
    assert outcome == record["outcome"]
    return record


def _rows(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in record["specs"]}


def test_a_good_design_passes_every_static_and_computed_criterion(tmp_path: Path) -> None:
    record = _judge(tmp_path, _answer(), STATIC_SPECS + COMPUTED_SPECS)
    assert record["answer_valid"] is True
    bad = {n: r for n, r in _rows(record).items() if r["verdict"] != "pass"}
    assert bad == {}
    assert record["outcome"] == "pass"


def test_the_dynamic_criteria_are_unscored_labelled_so_and_never_fail(tmp_path: Path) -> None:
    record = _judge(tmp_path, _answer(), STATIC_SPECS + COMPUTED_SPECS + DYNAMIC_SPECS)
    rows = _rows(record)
    for name in ("speed", "push"):
        assert rows[name]["verdict"] == "unscored"
        assert rows[name]["kind"] == "dynamic"
        assert "dynamic" in rows[name]["reason"]
    assert record["outcome"] == "unscored"


_STATIC_BREAKS = [
    (("controller", "command_limit"), _m(0.8, "1"), "limit"),
    (("parameters", "update_rate"), _m(98, "Hz"), "rate"),
    (("controller", "period"), _m(0.0098, "s"), "period"),
    (("parameters", "gyro_output_data_rate"), _m(416, "Hz"), "odr"),
    (("parameters", "gyro_full_scale"), _m(2000, "deg/s"), "scale"),
    (("parameters", "pwm_frequency"), _m(10000, "Hz"), "pwm"),
    (("parameters", "pwm_full_scale"), _m(255, "count"), "top"),
    (("parameters", "encoder_counts_per_wheel_revolution"), _m(1332, "count"), "counts"),
]


@pytest.mark.parametrize(
    ("path", "value", "fails"), _STATIC_BREAKS, ids=[b[2] for b in _STATIC_BREAKS]
)
def test_each_static_criterion_fails_on_its_own_setting_alone(
    tmp_path: Path, path: tuple[str, str], value: dict[str, object], fails: str
) -> None:
    doc = _answer()
    doc[path[0]][path[1]] = value
    record = _judge(tmp_path, doc, STATIC_SPECS)
    assert {n for n, r in _rows(record).items() if r["verdict"] == "fail"} == {fails}
    assert record["outcome"] == "fail"


def test_the_native_command_limit_is_read_through_the_answer_s_full_scale(tmp_path: Path) -> None:
    record = _judge(tmp_path, _answer(_native(motor_speed_limit=320)), STATIC_SPECS[:1])
    row = _rows(record)["limit"]
    assert row["measured"]["value"] == pytest.approx(0.8)
    assert row["verdict"] == "fail"


@pytest.mark.parametrize(
    ("controller", "analysed", "verdict"),
    [
        (_feedback(), None, "pass"),
        (_feedback(), _feedback(), "pass"),
        (_native(), _native(), "pass"),
        (
            _native(),
            _native(
                angle_response=22,
                distance_response=146,
                speed_response=6600,
                gear_ratio_coefficient=222,
            ),
            "fail",
        ),
        (_native(), _native(angle_decay_numerator=998), "fail"),
        (_feedback(), _feedback((1.6643 * (1 + 1e-12), *GOOD_GAINS[1:])), "fail"),
        (_feedback(), _feedback(period=_m(0.02, "s")), "fail"),
        (_feedback(), _feedback(compute_delay=_m(0.004, "s")), "pass"),
    ],
    ids=[
        "absent",
        "same_si",
        "same_native",
        "native_same_si_other_integers",
        "native_other_leak",
        "si_off_by_1e-12",
        "other_period",
        "delays_not_coefficients",
    ],
)
def test_the_same_coefficients_means_the_numbers_as_written(
    tmp_path: Path, controller: dict[str, Any], analysed: dict[str, Any] | None, verdict: str
) -> None:
    doc = _answer(controller)
    if analysed is not None:
        doc["analysed_controller"] = analysed
    row = _rows(_judge(tmp_path, doc, STATIC_SPECS[-1:]))["same"]
    assert row["verdict"] == verdict, row


def test_controllers_in_different_structures_are_not_compared_through_a_conversion(
    tmp_path: Path,
) -> None:
    # Criterion 19 asks for a relative difference of 0 in each coefficient; across two
    # structures there is no coefficient to difference, so it is not judged either way.
    doc = _answer(_native(), analysed_controller=_feedback())
    record = _judge(tmp_path, doc, STATIC_SPECS[-1:])
    row = _rows(record)["same"]
    assert row["verdict"] == "unscored"
    assert row["measured"] is None
    assert "different structures" in row["reason"]
    assert record["outcome"] == "unscored"


@pytest.mark.parametrize(("limit", "amps"), [(0.75, 1.35), (1.0, 1.8)])
def test_the_stall_current_is_the_plant_s_at_the_answer_s_limit(
    tmp_path: Path, limit: float, amps: float
) -> None:
    doc = _answer(_feedback(command_limit=_m(limit, "1")))
    row = _rows(_judge(tmp_path, doc, COMPUTED_SPECS[:1]))["stall"]
    assert row["measured"]["value"] == pytest.approx(amps, rel=1e-12)
    assert row["verdict"] == "pass"


def test_a_criterion_reading_no_ranged_parameter_is_scored_whatever_else_ranges(
    tmp_path: Path,
) -> None:
    plant = _plant(com_height=(0.005, 0.078), rotor_inertia=(1e-8, 1e-7))
    row = _rows(_judge(tmp_path, _answer(), COMPUTED_SPECS[:1], plant))["stall"]
    assert row["verdict"] == "pass"
    assert row["corners"]["ranged"] == []
    assert row["corners"]["count"] == 1


def _pm_at(tmp_path: Path, rotor: float) -> float:
    plant = _plant(rotor_inertia=(rotor, rotor))
    sub = tmp_path / f"at{rotor}"
    sub.mkdir()
    row = _rows(_judge(sub, _answer(), COMPUTED_SPECS[1:2], plant))["pm"]
    value: float = row["measured"]["value"]
    return value


def test_a_margin_whose_verdict_moves_inside_a_range_is_unscored_with_the_reason(
    tmp_path: Path,
) -> None:
    low, high = _pm_at(tmp_path, 2.5e-8), _pm_at(tmp_path, 1e-7)
    assert abs(low - high) > 1.0
    between = (low + high) / 2
    spec = _spec("pm", "phase_margin", ">=", _m(between, "deg"), "c15")
    plant = _plant(rotor_inertia=(2.5e-8, 1e-7))
    record = _judge(tmp_path, _answer(), [spec, *STATIC_SPECS], plant)
    row = _rows(record)["pm"]
    assert row["verdict"] == "unscored"
    assert "rotor_inertia" in row["reason"]
    assert row["corners"]["ranged"] == ["rotor_inertia"]
    assert row["corners"]["count"] == 2
    assert row["corners"]["passing"] == 1
    assert record["outcome"] == "unscored"


@pytest.mark.parametrize(("offset", "verdict"), [(-1.0, "pass"), (1.0, "fail")])
def test_a_margin_on_one_side_at_every_corner_is_scored(
    tmp_path: Path, offset: float, verdict: str
) -> None:
    ends = [_pm_at(tmp_path, 2.5e-8), _pm_at(tmp_path, 1e-7)]
    bound = (min(ends) + offset) if offset < 0 else (max(ends) + offset)
    spec = _spec("pm", "phase_margin", ">=", _m(bound, "deg"), "c15")
    plant = _plant(rotor_inertia=(2.5e-8, 1e-7))
    row = _rows(_judge(tmp_path, _answer(), [spec], plant))["pm"]
    assert row["verdict"] == verdict


def test_a_failure_elsewhere_makes_the_outcome_fail_though_one_is_unscored(tmp_path: Path) -> None:
    doc = _answer()
    doc["parameters"]["pwm_frequency"] = _m(10000, "Hz")
    record = _judge(tmp_path, doc, STATIC_SPECS + DYNAMIC_SPECS)
    assert record["outcome"] == "fail"


def test_a_secondary_spec_never_decides_the_outcome(tmp_path: Path) -> None:
    doc = _answer()
    doc["parameters"]["pwm_frequency"] = _m(10000, "Hz")
    secondary = [dict(s, counts="secondary") if s["name"] == "pwm" else s for s in STATIC_SPECS]
    record = _judge(tmp_path, doc, secondary)
    assert _rows(record)["pwm"]["verdict"] == "fail"
    assert record["outcome"] == "pass"


def test_a_design_unstable_at_every_corner_fails_its_margins_with_no_number(tmp_path: Path) -> None:
    doc = _answer(_feedback((-1.0, 0.0, 0.0, 0.0)))
    plant = _plant(rotor_inertia=(2.5e-8, 1e-7))
    rows = _rows(_judge(tmp_path, doc, COMPUTED_SPECS[1:], plant))
    for name in ("pm", "up", "down"):
        assert rows[name]["verdict"] == "fail", rows[name]
        assert rows[name]["measured"] is None
        assert rows[name]["corners"]["unstable"] == 2


@pytest.mark.parametrize("bad", ["not json", json.dumps(_answer(version=1))])
def test_an_answer_that_is_not_one_fails_with_its_reason(tmp_path: Path, bad: str) -> None:
    root = _root(tmp_path)
    path = root / "whole_run.json"
    path.write_text(bad)
    scenario = _scenario_module().WholeDesignScenario(_task(STATIC_SPECS), _plant(), root=root)
    record = scenario.record(path)
    assert record["answer_valid"] is False
    assert record["outcome"] == "fail"
    assert "whole-run answer" in record["reason"]


def test_an_answer_outside_the_scenario_s_root_fails(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = Path(os.path.realpath(tmp_path)) / "whole_run.json"
    outside.write_text(json.dumps(_answer()))
    scenario = _scenario_module().WholeDesignScenario(_task(STATIC_SPECS), _plant(), root=root)
    assert scenario.score(outside) == "fail"


@pytest.mark.parametrize(
    "spec",
    [
        _spec("x", "settling_time", "<=", _m(1, "s"), "c15"),
        _spec("x", "phase_margin", ">=", _m(0.5, "rad"), "c15"),
        _spec("x", "stall_current", "<=", _m(1800, "mA"), "c6"),
    ],
    ids=["unknown_metric", "other_unit", "other_unit_amps"],
)
def test_a_task_the_scenario_cannot_judge_is_refused_before_any_answer(
    tmp_path: Path, spec: dict[str, Any]
) -> None:
    module = _scenario_module()
    from physgate.evaluation.tiers.scenario import ScenarioError

    with pytest.raises(ScenarioError):
        module.WholeDesignScenario(_task([spec]), _plant(), root=_root(tmp_path))


def test_a_task_composing_one_requirement_is_refused(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from physgate.evaluation.tiers.scenario import ScenarioError

    with pytest.raises(ValidationError):
        _task(STATIC_SPECS, requirements=("c5",))
    with pytest.raises(ScenarioError):
        _scenario_module().WholeDesignScenario(
            _task(STATIC_SPECS, requirements=("c5", "c5")), _plant(), root=_root(tmp_path)
        )


def test_a_plant_file_that_is_not_one_is_refused(tmp_path: Path) -> None:
    from physgate.evaluation.whole.plant import PlantError

    doc = json.loads(_plant())
    doc["parameters"].pop("rotor_inertia")
    with pytest.raises(PlantError):
        _scenario_module().WholeDesignScenario(
            _task(STATIC_SPECS), json.dumps(doc).encode(), root=_root(tmp_path)
        )


def test_the_scenario_is_a_tier_scenario_composing_its_criteria(tmp_path: Path) -> None:
    from physgate.evaluation.tiers.scenario import Scenario, require_composing

    scenario = _scenario_module().WholeDesignScenario(
        _task(STATIC_SPECS, requirements=("c5", "c9", "c19")), _plant(), root=_root(tmp_path)
    )
    assert isinstance(scenario, Scenario)
    assert require_composing(scenario) is scenario
    assert scenario.requirements == ("c5", "c9", "c19")
    assert scenario.id == "whole.fixture"


def test_the_record_carries_the_plant_s_digest_and_status_and_every_scale_factor(
    tmp_path: Path,
) -> None:
    plant = _plant()
    record = _judge(tmp_path, _answer(_native()), STATIC_SPECS[:1], plant)
    assert record["plant"] == {
        "version": None,
        "status": "draft",
        "sha256": hashlib.sha256(plant).hexdigest(),
    }
    factors = {f["name"]: f for f in record["scale_factors"]}
    assert len(factors) == 9
    assert factors["wheel_radius"]["value"] == 0.040
    assert "brief criterion 2" in factors["wheel_radius"]["source"]
    assert "parameters.gyro_sensitivity" in factors["gyro_sensitivity"]["source"]


def test_a_native_controller_s_margins_use_each_corner_s_wheel_radius(tmp_path: Path) -> None:
    plant = _plant(rotor_inertia=(1e-8, 1e-8), wheel_radius=(0.039, 0.041))
    row = _rows(_judge(tmp_path, _answer(_native()), COMPUTED_SPECS[3:], plant))["down"]
    assert row["corners"]["ranged"] == ["wheel_radius"]
    assert row["corners"]["count"] == 2
    assert row["corners"]["unstable"] == 0
    assert row["corners"]["low"]["value"] < row["corners"]["high"]["value"]


def test_each_corner_converts_a_native_controller_at_that_corner_s_wheel_radius(
    tmp_path: Path,
) -> None:
    # Native gains act on encoder counts; their SI distance and speed gains scale with the
    # wheel's radius. At each corner of the radius's range the conversion takes that corner's
    # radius, never the nominal one: the margins at the two ends are this test's own reading
    # of the plant at that radius under the gains converted at that radius.
    from physgate.evaluation.whole import loop as loop_module
    from physgate.evaluation.whole.answer import parse_whole_run
    from physgate.evaluation.whole.convert import ScaleFactor, to_si
    from physgate.evaluation.whole.plant import nominal, parse_plant

    plant = _plant(rotor_inertia=(1e-8, 1e-8), wheel_radius=(0.039, 0.041))
    doc = _answer(_native())
    read = parse_whole_run(json.dumps(doc).encode())
    values = nominal(parse_plant(plant))
    want = []
    for radius in (0.039, 0.041):
        at = {**values, "wheel_radius": radius}
        si = to_si(
            read.controller,
            read.parameters,
            wheel_radius=ScaleFactor("wheel_radius", radius, "m", "this test"),
        )
        margins = loop_module.margins(at, si)
        assert margins.downward is not None
        want.append(margins.downward)
    row = _rows(_judge(tmp_path, doc, COMPUTED_SPECS[3:], plant))["down"]
    assert row["corners"]["count"] == 2
    assert row["corners"]["low"]["value"] == pytest.approx(min(want), rel=1e-9)
    assert row["corners"]["high"]["value"] == pytest.approx(max(want), rel=1e-9)


def test_a_design_written_with_no_leak_is_judged_on_its_balance(tmp_path: Path) -> None:
    # The kit's gains in SI with no angle_decay_per_update: the integrated angle's offset is
    # not a mode that fails the margins.
    controller = {
        "structure": "incremental_rising_offset",
        "period": _m(0.01, "s"),
        "command_limit": _m(0.75, "1"),
        "sensor_delay": _m(0.0048, "s"),
        "compute_delay": _m(0.002, "s"),
        "rate_ratio": _m(0.14, "s"),
        "angle_gain": _m(0.14195, "1/rad"),
        "distance_gain": _m(0.17308, "1/m"),
        "speed_gain": _m(0.07824, "s/m"),
    }
    plant = _plant(rotor_inertia=(1e-9, 1e-9))
    rows = _rows(_judge(tmp_path, _answer(controller), COMPUTED_SPECS[1:], plant))
    for name in ("pm", "up", "down"):
        assert rows[name]["corners"]["unstable"] == 0, rows[name]
        assert rows[name]["measured"] is not None, rows[name]


def test_the_counts_are_bounded_in_count() -> None:
    metrics = _scenario_module().METRICS
    assert metrics["pwm_full_scale"] == ("count", "static")
    assert metrics["encoder_counts_per_wheel_revolution"] == ("count", "static")
