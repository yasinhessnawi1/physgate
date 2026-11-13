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
    """The draft with every range a point, but those given."""
    doc = json.loads(_DRAFT.read_text())
    for name, p in doc["parameters"].items():
        p["low"] = p["high"] = p["value"]
        if name in ranged:
            p["low"], p["high"] = ranged[name]
    return json.dumps(doc).encode()


def _report(plant: bytes) -> dict[str, Any]:
    script = _script()
    report: dict[str, Any] = script.judge(plant, script.KIT_ANSWER)
    return report


def test_the_report_names_the_plant_the_answer_and_the_outcome() -> None:
    plant = _plant({"com_height": (0.010, 0.030)})
    report = _report(plant)
    assert set(report) == {"plant", "answer", "outcome", "predicates", "one_at_a_time"}
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
