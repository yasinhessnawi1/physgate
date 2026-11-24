"""The scorer judges the block's example and every answer built to break a rule as the block says.

The example the block quotes scores on the frozen plant without a refusal, and is no design: it
does not pass. For each rule the block lists as refused, an answer built to break exactly that
rule is a failed answer, by the name the block gives where it gives one; for each it lists as not
judged, the answer is unscored by the name given, and never a failed design. This is the only row
that runs the loop on the example; the cases end before it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit/evaluation/whole"))

from answer_form_cases import Case, cases, example, precedence  # noqa: E402
from test_a_whole_design_is_judged_never_on_an_unsourced_value import (  # noqa: E402
    COMPUTED_SPECS,
    STATIC_SPECS,
    _scenario_module,
    _task,
)

from physgate.evaluation.whole import form  # noqa: E402
from physgate.evaluation.whole import law as law_module  # noqa: E402
from physgate.evaluation.whole import scenario as scenario_module  # noqa: E402

_PLANT = Path(__file__).resolve().parents[2] / "src/physgate/evaluation/whole/plant_v0.json"
RULES = {r.key: r for r in (*form.REFUSED, *form.NOT_JUDGED)}
ALL = [(key, case) for key, group in cases().items() for case in group]
IDS = [f"{key}:{case.label}" for key, case in ALL]
_ONE_LOOP_ROW = [STATIC_SPECS[0], COMPUTED_SPECS[1]]


def _record(tmp_path: Path, data: bytes, specs: list[dict[str, Any]]) -> dict[str, Any]:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    path = root / form.ANSWER_FILE
    path.write_bytes(data)
    scorer = _scenario_module().WholeDesignScenario(_task(specs), _PLANT.read_bytes(), root=root)
    record: dict[str, Any] = scorer.record(path)
    return record


def _said(record: dict[str, Any]) -> str:
    return f"{record.get('reason', '')} {record.get('refusal', {}).get('name', '')}"


def test_the_example_scores_without_a_refusal_on_the_frozen_plant_and_is_no_design(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path, form.EXAMPLE_PATH.read_bytes(), STATIC_SPECS[:3] + COMPUTED_SPECS)
    assert record["plant"]["version"] == "v0" and record["plant"]["status"] == "frozen"
    assert record["answer_valid"] is True
    assert "refusal" not in record and "analysed_refusal" not in record
    assert record["structure"] == "sampled_law"
    verdicts = {row["name"]: row["verdict"] for row in record["specs"]}
    assert set(verdicts.values()) <= {"pass", "fail", "unscored"}
    assert len(verdicts) == len(STATIC_SPECS[:3] + COMPUTED_SPECS)
    assert record["outcome"] != "pass", "the example would be a design that meets the requirements"
    assert verdicts["pm"] != "pass" and verdicts["up"] != "pass"
    assert record["held_state_flags"] == []


def test_a_state_that_does_not_leak_is_flagged_and_one_that_leaks_is_not(tmp_path: Path) -> None:
    doc = example()
    doc["controller"]["coefficients"]["leak"]["value"] = 1
    held = _record(tmp_path, json.dumps(doc).encode(), _ONE_LOOP_ROW)
    assert held["answer_valid"] is True
    assert held["held_state_flags"] == [law_module.HELD_STATE_FLAG]


@pytest.mark.parametrize(("key", "case"), ALL, ids=IDS)
def test_an_answer_built_to_break_one_rule_is_scored_as_the_block_says(
    tmp_path: Path, key: str, case: Case
) -> None:
    assert case.changed, f"{case.label}: the edit found its text in the example not exactly once"
    rule = RULES[key]
    record = _record(tmp_path, case.data, _ONE_LOOP_ROW)
    assert record["outcome"] == case.outcome, record
    if case.parse == "outside":
        assert record["answer_valid"] is False
        assert record["refusal"]["name"] == rule.name
        assert record["specs"] == []
    elif case.parse == "parses":
        assert record["answer_valid"] is True
        assert record["refusal"]["name"] == rule.name
        assert record["work"]["total"]["value"] > record["work"]["bound"]["value"]
        assert record["specs"] == []
    else:
        assert record["answer_valid"] is False
        assert "refusal" not in record or record["refusal"]["name"] != "work_bound"
        assert record["specs"] == []
        if rule.name is not None:
            assert rule.name in _said(record), (rule.name, _said(record))


def test_a_fault_of_the_answer_beats_a_term_that_is_not_judged_at_the_scorer(
    tmp_path: Path,
) -> None:
    for at, case in enumerate(precedence()):
        sub = tmp_path / f"case{at}"
        sub.mkdir()
        record = _record(sub, case.data, _ONE_LOOP_ROW)
        assert record["outcome"] == "fail" and record["answer_valid"] is False


def test_the_names_the_block_prints_are_each_one_the_scorer_gave_in_a_case() -> None:
    names = {r.name for r in (*form.REFUSED, *form.NOT_JUDGED) if r.name}
    assert names == {
        "malformed",
        "units_do_not_balance",
        "zero_divisor",
        "number_underflows",
        "number_overflows",
        "work_bound",
        "nonlinear",
        "out_of_scope",
    }


def test_the_scorer_s_own_work_bound_is_a_constant_the_block_does_not_tell() -> None:
    assert scenario_module.MAX_WORK > 0
    assert "scenario.MAX_WORK" in form.NOT_TOLD
    assert str(scenario_module.MAX_WORK) not in form.render_answer_form()
    assert f"{scenario_module.MAX_WORK:,}" not in form.render_answer_form()
