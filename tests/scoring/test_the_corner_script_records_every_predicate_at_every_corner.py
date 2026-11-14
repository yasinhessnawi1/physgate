"""``scripts/whole_design_corners.py``: the scorer's corner counts, recorded and rerunnable.

The script is evidence: it judges an answer on a plant file and prints, for each predicate,
its verdict and how many corners of the plant's ranges pass, and for each ranged parameter
the margins at its two ends with every other parameter at its value. These rows pin the
output's form, never its numbers: the numbers move with the plant, and that is their use.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_DRAFT = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0_draft.json"
_VERDICTS = {"pass", "fail", "unscored"}


def _script() -> ModuleType:
    assert importlib.util.find_spec("whole_design_corners") is not None, (
        "scripts/whole_design_corners.py does not exist"
    )
    return importlib.import_module("whole_design_corners")


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


def _report(plant: bytes) -> dict[str, Any]:
    script = _script()
    report: dict[str, Any] = script.judge(plant, script.KIT_ANSWER)
    return report


def test_the_report_names_the_plant_the_answer_and_the_outcome() -> None:
    plant = _plant({"com_height": (0.010, 0.030)})
    report = _report(plant)
    assert set(report) == {
        "plant",
        "answer",
        "outcome",
        "predicates",
        "one_at_a_time",
        "extremes",
    }
    assert set(report["plant"]) == {"sha256", "status"}
    assert set(report["answer"]) == {"structure", "sha256"}
    assert report["outcome"] in _VERDICTS


def test_each_predicate_says_its_criterion_verdict_and_corner_counts() -> None:
    report = _report(_plant({"com_height": (0.010, 0.030)}))
    kinds = {row["kind"] for row in report["predicates"]}
    assert kinds == {"static", "computed", "dynamic"}
    for row in report["predicates"]:
        assert set(row) == {
            "criterion",
            "metric",
            "kind",
            "verdict",
            "nominal",
            "corners",
            "reason",
        }
        assert row["verdict"] in _VERDICTS
        if row["kind"] == "computed":
            corners = row["corners"]
            assert set(corners) == {"count", "passing", "unstable", "ranged"}
            assert all(isinstance(corners[k], int) for k in ("count", "passing", "unstable"))
            assert 0 <= corners["passing"] <= corners["count"]
        else:
            assert row["corners"] is None


def test_the_margins_rows_count_every_corner_of_what_ranges() -> None:
    report = _report(_plant({"com_height": (0.010, 0.030), "rotor_inertia": (1e-9, 1e-8)}))
    margins = [r for r in report["predicates"] if r["metric"] == "phase_margin"]
    assert len(margins) == 1
    assert margins[0]["corners"]["count"] == 4
    assert margins[0]["corners"]["ranged"] == ["com_height", "rotor_inertia"]


def test_each_ranged_parameter_is_moved_alone_to_its_two_ends() -> None:
    report = _report(_plant({"com_height": (0.010, 0.030), "rotor_inertia": (1e-9, 1e-8)}))
    moved = report["one_at_a_time"]
    assert [m["parameter"] for m in moved] == ["com_height", "rotor_inertia"]
    for m in moved:
        assert set(m) == {"parameter", "unit", "low", "high"}
        for end in ("low", "high"):
            assert set(m[end]) == {
                "value",
                "stable",
                "phase_margin",
                "gain_margin_upward",
                "gain_margin_downward",
            }


_MARGINS = ("phase_margin", "gain_margin_upward", "gain_margin_downward")


def _extremes(plant: bytes) -> dict[str, Any]:
    report = _report(plant)
    assert "extremes" in report, "the report names no worst or best corner"
    extremes: dict[str, Any] = report["extremes"]
    return extremes


def test_each_margin_s_worst_and_best_corner_is_named_with_its_value() -> None:
    script = _script()
    plant = _plant({"com_height": (0.010, 0.030), "rotor_inertia": (1e-9, 1e-8)})
    extremes = _extremes(plant)
    assert set(extremes) == set(_MARGINS)
    values = []
    for low_com in (0.010, 0.030):
        for rotor in (1e-9, 1e-8):
            one = _plant({})
            doc = json.loads(one)
            doc["parameters"]["com_height"]["value"] = low_com
            doc["parameters"]["rotor_inertia"]["value"] = rotor
            for name in ("com_height", "rotor_inertia"):
                p = doc["parameters"][name]
                p["low"] = p["high"] = p["value"]
            pm = script.judge(json.dumps(doc).encode(), script.KIT_ANSWER)["predicates"]
            row = next(r for r in pm if r["metric"] == "phase_margin")
            values.append(((low_com, rotor), row["nominal"]))
    stable = [(at, v) for at, v in values if v is not None]
    pm = extremes["phase_margin"]
    assert pm["stable_corners"] == len(stable)
    if stable:
        worst = min(stable, key=lambda item: item[1])
        best = max(stable, key=lambda item: item[1])
        assert pm["worst"]["value"] == pytest.approx(worst[1], rel=1e-9)
        assert pm["best"]["value"] == pytest.approx(best[1], rel=1e-9)
        assert (pm["worst"]["at"]["com_height"], pm["worst"]["at"]["rotor_inertia"]) == worst[0]
        assert (pm["best"]["at"]["com_height"], pm["best"]["at"]["rotor_inertia"]) == best[0]


def test_the_downward_gain_margin_s_worst_corner_is_its_largest() -> None:
    plant = _plant({"com_height": (0.010, 0.030), "rotor_inertia": (1e-9, 1e-8)})
    extremes = _extremes(plant)
    down = extremes["gain_margin_downward"]
    assert down["worst"]["value"] >= down["best"]["value"]
    up = extremes["gain_margin_upward"]
    assert up["worst"]["value"] <= up["best"]["value"]


def test_with_every_corner_unstable_the_extremes_are_none() -> None:
    plant = _plant({"com_height": (0.077, 0.078)})
    doc = json.loads(plant)
    doc["parameters"]["rotor_inertia"].update(value=1e-7, low=1e-7, high=1e-7)
    extremes = _extremes(json.dumps(doc).encode())
    for metric in _MARGINS:
        assert extremes[metric] == {"stable_corners": 0, "worst": None, "best": None}


def _region(plant: bytes, axes: dict[str, list[float]]) -> dict[str, Any]:
    script = _script()
    assert hasattr(script, "region"), "the script judges no region"
    region: dict[str, Any] = script.region(plant, script.KIT_ANSWER, axes)
    return region


def test_the_region_judges_every_grid_point_at_nominal_and_at_every_other_corner() -> None:
    plant = _plant({"com_height": (0.010, 0.030), "rotor_inertia": (1e-9, 1e-8)})
    axes = {"com_height": [0.010, 0.030], "rotor_inertia": [1e-9]}
    region = _region(plant, axes)
    assert set(region) == {"axes", "others", "bounds", "points", "summary"}
    assert region["axes"] == axes
    assert region["others"] == []
    assert region["bounds"] == {
        "phase_margin": 30.0,
        "gain_margin_upward": 2.0,
        "gain_margin_downward": 0.5,
    }
    assert len(region["points"]) == 2
    for point in region["points"]:
        assert set(point) == {"at", "nominal", "every_corner"}
        assert set(point["nominal"]) == {"stable", "meets", *_MARGINS}
        assert set(point["every_corner"]) == {"corners", "stable", "meets"}
        assert point["every_corner"]["corners"] == 1


def test_a_region_point_meets_the_bounds_only_when_every_margin_does() -> None:
    script = _script()
    plant = _plant({})
    region = _region(plant, {"rotor_inertia": [1e-9, 1e-8, 1e-7]})
    for point in region["points"]:
        n = point["nominal"]
        expected = (
            n["stable"]
            and n["phase_margin"] >= 30.0
            and n["gain_margin_upward"] >= 2.0
            and n["gain_margin_downward"] <= 0.5
        )
        assert n["meets"] is bool(expected)
        doc = json.loads(plant)
        doc["parameters"]["rotor_inertia"]["value"] = point["at"]["rotor_inertia"]
        doc["parameters"]["rotor_inertia"]["low"] = point["at"]["rotor_inertia"]
        doc["parameters"]["rotor_inertia"]["high"] = point["at"]["rotor_inertia"]
        row = next(
            r
            for r in script.judge(json.dumps(doc).encode(), script.KIT_ANSWER)["predicates"]
            if r["metric"] == "phase_margin"
        )
        assert n["phase_margin"] == row["nominal"]
    summary = region["summary"]
    assert summary["points"] == 3
    assert summary["stable_at_nominal"] == sum(p["nominal"]["stable"] for p in region["points"])
    assert summary["meets_at_nominal"] == sum(p["nominal"]["meets"] for p in region["points"])


def test_a_region_point_holds_at_every_corner_only_if_it_holds_at_each() -> None:
    plant = _plant({"motor_no_load_speed": (54.454272662223076, 81.68140899333461)})
    region = _region(plant, {"rotor_inertia": [1e-9, 2e-8]})
    assert region["others"] == ["motor_no_load_speed"]
    script = _script()
    for point in region["points"]:
        corners = point["every_corner"]
        assert corners["corners"] == 2
        each = []
        for speed in (54.454272662223076, 81.68140899333461):
            doc = json.loads(plant)
            for name, value in (
                ("rotor_inertia", point["at"]["rotor_inertia"]),
                ("motor_no_load_speed", speed),
            ):
                doc["parameters"][name].update(value=value, low=value, high=value)
            rows = script.judge(json.dumps(doc).encode(), script.KIT_ANSWER)["predicates"]
            pm = next(r for r in rows if r["metric"] == "phase_margin")["nominal"]
            each.append(pm)
        assert corners["stable"] is all(v is not None for v in each)


def test_a_region_axis_must_be_a_parameter_the_loop_reads() -> None:
    with pytest.raises(ValueError, match="gearbox_friction"):
        _region(_plant({}), {"gearbox_friction": [0.01]})


def test_the_command_prints_the_region_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    assert hasattr(script, "region"), "the script judges no region"
    plant = tmp_path / "plant.json"
    plant.write_bytes(_plant({}))
    assert script.main(["--plant", str(plant), "--region"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"axes", "others", "bounds", "points", "summary"}
    assert set(printed["axes"]) == {"com_height", "body_inertia", "rotor_inertia"}


def test_the_command_reads_its_files_and_prints_the_report_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    plant = tmp_path / "plant.json"
    plant.write_bytes(_plant({"com_height": (0.010, 0.030)}))
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps(script.KIT_ANSWER))
    assert script.main(["--plant", str(plant), "--answer", str(answer)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == script.judge(plant.read_bytes(), script.KIT_ANSWER)


#: A state feedback (the scoring rows' fixture gains) with the delays the kit's answer states.
_FIXTURE_GAINS = (1.6643, 0.191, 0.2853, 1.3421)
_SLOW, _FAST = 54.454272662223076, 81.68140899333461


def _feedback_answer(scale: float) -> dict[str, Any]:
    script = _script()
    answer: dict[str, Any] = json.loads(json.dumps(script.KIT_ANSWER))
    g = [scale * x for x in _FIXTURE_GAINS]
    answer["controller"] = {
        "structure": "state_feedback",
        "period": {"value": 0.01, "unit": "s"},
        "command_limit": {"value": 0.75, "unit": "1"},
        "sensor_delay": {"value": 0.0048, "unit": "s"},
        "compute_delay": {"value": 0.002, "unit": "s"},
        "angle_gain": {"value": g[0], "unit": "1/rad"},
        "rate_gain": {"value": g[1], "unit": "s/rad"},
        "distance_gain": {"value": g[2], "unit": "1/m"},
        "speed_gain": {"value": g[3], "unit": "s/m"},
    }
    return answer


def test_a_point_unstable_at_any_corner_is_not_stable_at_every_corner() -> None:
    # Half the gains: below the lower gain margin with the slow motor (the first corner),
    # inside it with the fast one (the last).
    script = _script()
    assert hasattr(script, "region"), "the script judges no region"
    plant = _plant({"motor_no_load_speed": (_SLOW, _FAST)})
    answer = _feedback_answer(0.5)
    ends = []
    for speed in (_SLOW, _FAST):
        doc = json.loads(plant)
        doc["parameters"]["motor_no_load_speed"].update(value=speed, low=speed, high=speed)
        rows = script.judge(json.dumps(doc).encode(), answer)["predicates"]
        ends.append(next(r for r in rows if r["metric"] == "phase_margin")["nominal"] is not None)
    assert ends == [False, True], "the fixture no longer separates the two corners"
    point = script.region(plant, answer, {"rotor_inertia": [1e-8]})["points"][0]
    assert point["every_corner"]["stable"] is False


def test_a_point_short_of_the_downward_margin_at_a_corner_does_not_meet_at_every_corner() -> None:
    # The fixture gains meet every bound at nominal; with the slow motor the downward gain
    # margin alone is above 0.5.
    script = _script()
    assert hasattr(script, "region"), "the script judges no region"
    plant = _plant({"motor_no_load_speed": (_SLOW, _FAST)})
    point = script.region(plant, _feedback_answer(1.0), {"rotor_inertia": [1e-8]})["points"][0]
    assert point["nominal"]["meets"] is True
    assert point["every_corner"]["stable"] is True
    assert point["every_corner"]["meets"] is False
