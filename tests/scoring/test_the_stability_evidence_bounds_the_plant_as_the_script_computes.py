"""The stability evidence bounds the plant as the recorded script computes it, never by hand.

The owner ruled on 13.11.2026 that "the real kit balances with the published controller" may
bound the plant's ranges, as stability evidence only. ``scripts/whole_design_corners.py
--bound`` computes the bound: a grid over the loop's parameters no source gives, each grid
point judged with the kit's published controller (its constants as Balance.h and Balance.cpp
write them) at the other ranged parameters' values and at every corner of their ranges as
sourced. A point is admitted when the loop is stable at any of those (the real robot is one
point; the evidence rules a value out only where no admissible combination is stable). A
parameter's bound is the span of its admitted grid values, widened to the next grid value
outward on each side (the true edge lies between the two, and the bound never claims more
than the grid shows). The kit's delays are the answer's assumptions, so the bound is computed
with them and with none, and the wider of the two is used.

These rows hold the derivation to that rule, the bound to an independent recomputation on a
small grid, and the draft's bounded ranges to the recorded report, byte for byte by digest.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import itertools
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DRAFT = _ROOT / "src/physgate/evaluation/whole/plant_v0_draft.json"
_REPORT = _ROOT / "src/physgate/evaluation/whole/plant_v0_bound.json"


class _Script:
    """The script, each name it lacks an assertion's failure rather than an error."""

    def __init__(self, module: ModuleType) -> None:
        self._module = module

    def __getattr__(self, name: str) -> Any:
        assert hasattr(self._module, name), f"the script has no {name}"
        return getattr(self._module, name)


def _script() -> Any:
    assert importlib.util.find_spec("whole_design_corners") is not None, (
        "scripts/whole_design_corners.py does not exist"
    )
    return _Script(importlib.import_module("whole_design_corners"))


def _plant(ranged: dict[str, tuple[float, float]]) -> bytes:
    """The draft with no bound and every range a point, but those given."""
    doc = json.loads(_DRAFT.read_text())
    for name, p in doc["parameters"].items():
        p.pop("bounded", None)
        p["low"] = p["high"] = p["value"]
        if name in ranged:
            p["low"], p["high"] = ranged[name]
            if not p["low"] <= p["value"] <= p["high"]:
                p["value"] = p["low"]
    return json.dumps(doc).encode()


def _narrowed(report: dict[str, Any]) -> list[str]:
    return [n for n, b in report["bounds"].items() if b["used"] != b["sourced"]]


# ---- the derivation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("admitted", "expected"),
    [
        ([False, True, True, False, False], (1.0, 4.0)),
        ([True, True, True, True, True], (1.0, 5.0)),
        ([True, False, False, False, False], (1.0, 2.0)),
        ([False, False, False, False, True], (4.0, 5.0)),
        ([False, True, False, True, False], (1.0, 5.0)),
        ([False, False, True, False, False], (2.0, 4.0)),
    ],
    ids=["middle", "all", "first", "last", "gap", "one"],
)
def test_a_bound_is_the_admitted_span_widened_to_the_next_grid_value(
    admitted: list[bool], expected: tuple[float, float]
) -> None:
    axis = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _script().interval(axis, admitted) == expected


def test_with_no_admitted_value_the_evidence_and_the_ranges_contradict() -> None:
    with pytest.raises(ValueError, match="contradict"):
        _script().interval([1.0, 2.0, 3.0], [False, False, False])


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ([(0.005, 0.060), (0.005, 0.071)], (0.005, 0.071)),
        ([(0.005, 0.071), (0.005, 0.060)], (0.005, 0.071)),
        ([(0.010, 0.060), (0.005, 0.050)], (0.005, 0.060)),
        ([None, (0.005, 0.050)], (0.005, 0.050)),
    ],
    ids=["second_wider", "first_wider", "neither_nested", "one_contradicts"],
)
def test_the_wider_of_the_delay_bounds_is_the_one_used(
    bounds: list[tuple[float, float] | None], expected: tuple[float, float]
) -> None:
    assert _script().wider(bounds) == expected


def test_admitted_is_stable_anywhere_and_the_stronger_reading_stable_everywhere() -> None:
    script = _script()
    assert script.admitted([False, False, True]) == (True, False)
    assert script.admitted([True, True, True]) == (True, True)
    assert script.admitted([False, False, False]) == (False, False)


def test_the_delay_variants_change_the_two_delays_and_nothing_else() -> None:
    script = _script()
    kit = script.KIT_ANSWER
    assert script.delay_variants(kit) == {"assumed": (0.0048, 0.002), "zero": (0.0, 0.0)}
    zero = script.with_delays(kit, 0.0, 0.0)
    assert zero["controller"]["sensor_delay"] == {"value": 0.0, "unit": "s"}
    assert zero["controller"]["compute_delay"] == {"value": 0.0, "unit": "s"}
    rest = {k: v for k, v in zero["controller"].items() if not k.endswith("_delay")}
    assert rest == {k: v for k, v in kit["controller"].items() if not k.endswith("_delay")}
    assert zero["parameters"] == kit["parameters"]
    assert kit["controller"]["sensor_delay"]["value"] == 0.0048, "the kit's answer was changed"


def test_the_kit_answer_carries_the_published_example_s_constants() -> None:
    """Balance.h and Balance.cpp, pololu/balboa-32u4-arduino-library tag 1.1.2 (= master)."""
    c = _script().KIT_ANSWER["controller"]
    assert c["structure"] == "native_incremental_rising_offset"
    published = {
        "update_time": 10,
        "motor_speed_limit": 300,
        "angle_rate_ratio": 140,
        "angle_response": 11,
        "distance_response": 73,
        "speed_response": 3300,
        "response_divisor": 100,
        "gear_ratio_coefficient": 111,
        "gyro_divisor": 29,
        "angle_decay_numerator": 999,
        "angle_decay_denominator": 1000,
    }
    assert {k: c[k]["value"] for k in published} == published


# ---- the bound, recomputed independently on a small grid --------------------------------


def test_the_bound_judges_each_point_at_nominal_and_every_sourced_corner_for_each_delay() -> None:
    script = _script()
    plant = _plant(
        {
            "com_height": (0.005, 0.078),
            "rotor_inertia": (3e-9, 2e-8),
            "motor_no_load_speed": (54.454272662223076, 81.68140899333461),
        }
    )
    axes = {"com_height": [0.005, 0.040, 0.078], "rotor_inertia": [3e-9, 2e-8]}
    report = script.bound(plant, script.KIT_ANSWER, axes)
    assert report["axes"] == axes
    assert report["others"] == ["motor_no_load_speed"]
    variants = script.delay_variants(script.KIT_ANSWER)
    base = json.loads(plant)["parameters"]
    values = {n: p["value"] for n, p in base.items()}
    for variant, (sensor, compute) in variants.items():
        answer = script.with_delays(script.KIT_ANSWER, sensor, compute)
        rows = report["points"][variant]
        assert len(rows) == 6
        for row, (com, rotor) in zip(rows, itertools.product(*axes.values()), strict=True):
            here = {**values, "com_height": com, "rotor_inertia": rotor}
            stable = [
                bool(script._margins_at({**here, "motor_no_load_speed": s}, answer)["stable"])
                for s in (here["motor_no_load_speed"], 54.454272662223076, 81.68140899333461)
            ]
            assert row == [com, rotor, any(stable), all(stable)], (variant, com, rotor)


def test_the_bound_report_derives_each_axis_from_its_points() -> None:
    script = _script()
    plant = _plant({"com_height": (0.005, 0.078), "rotor_inertia": (3e-9, 2e-8)})
    axes = {"com_height": [0.005, 0.040, 0.078], "rotor_inertia": [3e-9, 2e-8]}
    report = script.bound(plant, script.KIT_ANSWER, axes)
    assert report["bounds"] == script.bounds_from_points(axes, report["points"])
    for name, b in report["bounds"].items():
        assert b["sourced"] == [axes[name][0], axes[name][-1]]
        found = [b[v] for v in ("assumed", "zero")]
        assert b["used"] == list(script.wider([None if f is None else tuple(f) for f in found]))
    assert report["applies"] == _narrowed(report)


def test_an_axis_the_loop_does_not_read_cannot_be_bounded() -> None:
    script = _script()
    with pytest.raises(ValueError, match="balance loop"):
        script.bound(_plant({}), script.KIT_ANSWER, {"gearbox_friction": [0.009, 0.036]})


# ---- the draft's bounded ranges are the recorded report's -------------------------------


def _report() -> dict[str, Any]:
    assert _REPORT.is_file(), f"no recorded bound report at {_REPORT}"
    loaded: dict[str, Any] = json.loads(_REPORT.read_text())
    return loaded


def test_the_draft_s_bounded_ranges_are_the_recorded_report_s() -> None:
    from physgate.evaluation.whole.plant import parse_plant

    report = _report()
    digest = hashlib.sha256(_REPORT.read_bytes()).hexdigest()
    parsed = parse_plant(_DRAFT.read_bytes())
    bounded = {n: p.bounded for n, p in parsed.parameters.items() if p.bounded is not None}
    assert sorted(bounded) == sorted(report["applies"])
    for name, b in bounded.items():
        assert [b.low, b.high] == report["bounds"][name]["used"], name
        assert b.report == digest, name
        p = parsed.parameters[name]
        assert [p.low, p.high] == report["bounds"][name]["sourced"], name


def test_the_recorded_report_was_computed_on_the_draft_s_sourced_ranges_and_the_kit() -> None:
    script = _script()
    report = _report()
    assert report["form"] == "stability_bound"
    assert report["plant_sourced"]["sha256"] == script.sourced_digest(_DRAFT.read_bytes())
    assert report["answer"]["sha256"] == script.answer_digest(script.KIT_ANSWER)
    assert report["answer"]["delays"] == {"assumed": [0.0048, 0.002], "zero": [0.0, 0.0]}
    assert report["axes"] == script.bound_axes(_DRAFT.read_bytes())
    assert "gearbox_friction" not in report["axes"]


def test_the_recorded_report_s_bounds_derive_from_its_own_points() -> None:
    script = _script()
    report = _report()
    assert report["bounds"] == script.bounds_from_points(report["axes"], report["points"])
    assert report["applies"] == _narrowed(report)


def test_the_sourced_digest_ignores_the_bound_and_reads_every_value_and_range() -> None:
    script = _script()
    doc = json.loads(_DRAFT.read_text())
    for p in doc["parameters"].values():
        p.pop("bounded", None)
    base = script.sourced_digest(json.dumps(doc).encode())
    digest = "ef" * 32
    doc["parameters"]["com_height"]["bounded"] = {
        "low": 0.005,
        "high": 0.030,
        "evidence": f"bounded by stability evidence; report sha256 {digest}",
        "report": digest,
    }
    assert script.sourced_digest(json.dumps(doc).encode()) == base
    doc["parameters"]["body_inertia"]["high"] *= 1.01
    assert script.sourced_digest(json.dumps(doc).encode()) != base


def test_the_corner_report_moves_a_bounded_parameter_to_its_bounded_ends() -> None:
    script = _script()
    doc = json.loads(_plant({"com_height": (0.005, 0.078)}))
    digest = "cd" * 32
    doc["parameters"]["com_height"]["value"] = 0.019
    doc["parameters"]["com_height"]["bounded"] = {
        "low": 0.005,
        "high": 0.030,
        "evidence": f"bounded by stability evidence; report sha256 {digest}",
        "report": digest,
    }
    report = script.judge(json.dumps(doc).encode(), script.KIT_ANSWER)
    (moved,) = report["one_at_a_time"]
    assert moved["parameter"] == "com_height"
    assert (moved["low"]["value"], moved["high"]["value"]) == (0.005, 0.030)
    (stable,) = {e["stable_corners"] for e in report["extremes"].values()}
    assert stable <= 2
    com = {p["criterion"]: p for p in report["predicates"]}["c15"]
    assert com["corners"]["count"] == 2


def test_the_bound_used_is_the_wider_delay_reading_and_the_stronger_one_is_beside_it() -> None:
    script = _script()
    axes = {"com_height": [0.01, 0.02, 0.03, 0.04, 0.05], "rotor_inertia": [1e-9]}
    # The rows: com, rotor, admitted (stable at any set), stable at every set.
    assumed = [[c, 1e-9, c <= 0.02, c <= 0.01] for c in axes["com_height"]]
    zero = [[c, 1e-9, c <= 0.03, c <= 0.02] for c in axes["com_height"]]
    bounds = script.bounds_from_points(axes, {"assumed": assumed, "zero": zero})
    com = bounds["com_height"]
    assert com["sourced"] == [0.01, 0.05]
    assert com["assumed"] == [0.01, 0.03]
    assert com["zero"] == [0.01, 0.04]
    assert com["used"] == [0.01, 0.04]
    assert com["every_corner"] == {"assumed": [0.01, 0.02], "zero": [0.01, 0.03]}
    swapped = script.bounds_from_points(axes, {"assumed": zero, "zero": assumed})
    assert swapped["com_height"]["used"] == [0.01, 0.04]


def test_the_bound_judges_the_other_parameters_over_their_ranges_as_sourced_not_as_bounded() -> (
    None
):
    script = _script()
    doc = json.loads(_plant({"motor_no_load_speed": (54.454272662223076, 81.68140899333461)}))
    speed = doc["parameters"]["motor_no_load_speed"]
    digest = "ef" * 32
    speed["bounded"] = {
        "low": speed["value"],
        "high": speed["value"],
        "evidence": f"bounded by stability evidence; report sha256 {digest}",
        "report": digest,
    }
    report = script.bound(json.dumps(doc).encode(), script.KIT_ANSWER, {"com_height": [0.019]})
    assert report["others"] == ["motor_no_load_speed"]
