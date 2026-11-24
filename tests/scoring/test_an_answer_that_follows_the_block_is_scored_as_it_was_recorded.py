"""An answer that follows the answer-form block scores as it did before the reading grew stricter.

The scorer refuses a sign written ``true``, two states marked as holding the applied command and a
key written twice. None of these is in an answer written as the block says, so none of those
answers may score differently. The fixture holds seven such answers (the block's example, a state
that keeps its value exactly, a state feedback, the same feedback written with a sign of -1, a
number and a ``per``, the feedback through one applied state, a read sum of the wheel angle, and a
version 2 answer), each with the record the scorer gave it on master before the change, on the
frozen plant, with the static and computed rows and no time run. Each is scored again here and its
record compared: every verdict, count, flag, name and reason exactly; every number to a relative
1e-9, since the fixture was recorded on one machine and a row may run on another.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit/evaluation/whole"))

from test_a_whole_design_is_judged_never_on_an_unsourced_value import (  # noqa: E402
    _scenario_module,
    _task,
)

from physgate.evaluation.whole import form  # noqa: E402

_HERE = Path(__file__).resolve().parent
_FIXTURE = json.loads((_HERE / "answers_that_follow_the_block.records.json").read_text())
_PLANT = _HERE.parents[1] / "src/physgate/evaluation/whole" / _FIXTURE["plant"]
#: The relative difference two machines' floating point may leave in a recorded number.
_RELATIVE = 1e-9


def _same(now: Any, then: Any, where: str) -> None:
    if isinstance(then, float) or isinstance(now, float):
        assert isinstance(now, int | float) and isinstance(then, int | float), where
        if math.isinf(then) or math.isinf(now):
            assert now == then, where
        else:
            assert now == pytest.approx(then, rel=_RELATIVE, abs=1e-300), (where, now, then)
    elif isinstance(then, dict):
        assert isinstance(now, dict) and sorted(now) == sorted(then), (where, sorted(now))
        for key in then:
            _same(now[key], then[key], f"{where}.{key}")
    elif isinstance(then, list):
        assert isinstance(now, list) and len(now) == len(then), where
        for at, (a, b) in enumerate(zip(now, then, strict=True)):
            _same(a, b, f"{where}[{at}]")
    else:
        assert now == then, (where, now, then)


@pytest.mark.parametrize("entry", _FIXTURE["answers"], ids=lambda e: e["label"])
def test_an_answer_that_follows_the_block_gives_the_record_it_gave_before(
    tmp_path: Path, entry: dict[str, Any]
) -> None:
    root = Path(os.path.realpath(tmp_path)) / "answers"
    root.mkdir()
    path = root / form.ANSWER_FILE
    path.write_bytes(json.dumps(entry["answer"]).encode())
    scorer = _scenario_module().WholeDesignScenario(
        _task(_FIXTURE["specs"]), _PLANT.read_bytes(), root=root
    )
    _same(scorer.record(path), entry["record"], "record")


def test_the_recorded_answers_are_valid_and_reach_a_judged_loop() -> None:
    records = [entry["record"] for entry in _FIXTURE["answers"]]
    assert len(records) == 7 and all(r["answer_valid"] for r in records)
    assert any(r.get("held_state_flags") for r in records)
    margins = [s for r in records for s in r["specs"] if s["name"] == "pm"]
    assert any(s["corners"]["passing"] > 0 for s in margins)
