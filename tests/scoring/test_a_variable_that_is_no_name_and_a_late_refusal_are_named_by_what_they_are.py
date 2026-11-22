"""The scorer never raises on an answer, and a scorer fault carries the refusal that was raised.

A term whose variable is the marker's old text (``outside the scorer's scope``), or any text that
is no well-formed name, is a malformed answer: the ordinary fail, never an exception out of
``scenario.record``. A refusal raised after validation accepted the law is the scorer
contradicting itself, so whichever it is, the outcome is ``scorer_fault`` and the record names the
refusal that was raised, with every row's own fields.
"""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

import pytest

from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole.scenario import METRICS

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
scope: Any = importlib.import_module("test_a_law_s_scope_flags_and_held_modes_reach_the_score")

ILL_FORMED = [
    "outside the scorer's scope",
    "",
    " ",
    "tilt rate",
    "zé",
    "тilt",
    "5",
    "1.5",
    "Tilt",
    "tilt\n",
    "previous.",
]


def _with_term(of: str, *, another: bool) -> dict[str, Any]:
    controller = copy.deepcopy(helpers._recorded_controller())
    command = scope._command(controller)
    command["terms"].append({"sign": 1, "number": 0, "of": of})
    if another:
        command["terms"].append({"sign": 1, "number": 1, "of": "tilt*tilt_rate"})
    out: dict[str, Any] = controller
    return out


@pytest.mark.parametrize("another", [False, True])
@pytest.mark.parametrize("of", ILL_FORMED)
def test_a_variable_that_is_no_name_is_the_ordinary_fail_never_an_exception(
    tmp_path: Path, of: str, another: bool
) -> None:
    record = scope._record(tmp_path, _with_term(of, another=another))
    assert record["answer_valid"] is False, record
    assert record["outcome"] == "fail"
    assert "refusal" not in record
    assert record["specs"] == []


def test_a_term_that_is_an_expression_is_still_unscored_by_name(tmp_path: Path) -> None:
    record = scope._record(tmp_path, _with_term("tilt*tilt_rate", another=False))
    assert record["outcome"] == "unscored"
    assert record["refusal"]["name"] == "nonlinear"


# ── a scorer fault carries the refusal that was raised ──


def _late(code: str) -> Any:
    def raised(*_args: Any, **_kwargs: Any) -> Any:
        raise law_module.LawRefused(code, f"a constructed late refusal, {code}")

    return raised


@pytest.mark.parametrize("code", ["zero_divisor", "malformed", "written_numbers_do_not_match"])
def test_any_refusal_after_validation_is_a_scorer_fault_under_its_own_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    scenario, root = helpers._scenario(tmp_path, copy.deepcopy(helpers.SPECS))
    path = root / "answer.json"
    path.write_bytes(helpers._answer(helpers._recorded_controller(), 3))
    monkeypatch.setattr(law_module, "held_report", _late(code))
    record = scenario.record(path)
    assert record["answer_valid"] is True
    assert record["outcome"] == "scorer_fault"
    assert record["refusal"] == {
        "name": code,
        "reason": f"{code}: a constructed late refusal, {code}",
    }
    specs = scenario._task.specs
    assert len(record["specs"]) == len(specs) > 0
    for spec, row in zip(specs, record["specs"], strict=True):
        assert row == {
            "name": spec.name,
            "metric": spec.metric,
            "kind": METRICS[spec.metric][1],
            "counts": spec.counts,
            "composes": list(spec.composes),
            "verdict": "scorer_fault",
            "measured": None,
            "reason": record["refusal"]["reason"],
        }
    assert scenario.score(path) == "scorer_fault"


def test_a_scorer_fault_row_carries_its_spec_s_own_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A spec counts either as a headline or as a secondary measure. Give the specs both, so that
    # a row that said "headline" for every spec would differ from the spec's own on the secondary
    # ones.
    specs = copy.deepcopy(helpers.SPECS)
    for index, spec in enumerate(specs):
        spec["counts"] = "secondary" if index % 2 == 0 else "headline"
    scenario, root = helpers._scenario(tmp_path, specs)
    path = root / "answer.json"
    path.write_bytes(helpers._answer(helpers._recorded_controller(), 3))
    monkeypatch.setattr(law_module, "held_report", _late("zero_divisor"))
    record = scenario.record(path)
    assert record["outcome"] == "scorer_fault"
    task_specs = scenario._task.specs
    assert {spec.counts for spec in task_specs} == {"headline", "secondary"}
    assert len(record["specs"]) == len(task_specs)
    for spec, row in zip(task_specs, record["specs"], strict=True):
        assert row["counts"] == spec.counts, (spec.name, row["counts"], spec.counts)
    assert [row["counts"] for row in record["specs"]] == [
        "secondary" if index % 2 == 0 else "headline" for index in range(len(specs))
    ]
