"""``compare`` refuses two runs on one tier version whose held-out counts left out different tasks.

The tiers record beside a run (``evaluation/tiers.json``) names, for a round on a version, what
its version's blind check flagged and the round left out of its held-out count. Two records of one
version that left out different tasks, or of which one left out what the check flagged and the
other left out nothing, are not counts of one tier: the comparison is refused, in words of its
own and naming the field. Two that left out the same are compared.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from observe_rig import fake_run, target_repo

from physgate.evaluation.baseline.record import TiersRecord, record_bytes
from physgate.evaluation.observe.compare import compare
from physgate.evaluation.observe.exceptions import CompareRefusedError

RECORD = Path("evaluation") / "tiers.json"
FIELD = "evaluation/tiers.json:held_out_left_out"


def _left(*digests: str, check: str = "c" * 64) -> dict[str, Any]:
    return {"count": len(digests), "digests": list(digests), "check_sha256": check}


def _tiers(left: dict[str, Any] | None) -> bytes:
    return record_bytes(
        TiersRecord.model_validate_json(
            json.dumps(
                {
                    "format": 1,
                    "version": "1" * 64,
                    "role": "control",
                    "visible": "2" * 64,
                    "validation": "3" * 64,
                    "held_out": "4" * 64,
                    "held_out_left_out": left,
                }
            )
        )
    )


def _write(run_dir: Path, data: bytes) -> None:
    (run_dir / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (run_dir / RECORD).write_bytes(data)


@pytest.mark.parametrize(
    ("mine", "theirs"),
    [
        (_left("a" * 16), _left("b" * 16)),
        (_left("a" * 16), _left()),
        (_left("a" * 16), None),
        (_left("a" * 16), _left("a" * 16, check="d" * 64)),
    ],
    ids=["another task", "none left out", "one record before there was any", "another record"],
)
def test_runs_on_one_version_that_left_out_different_tasks_are_not_compared(
    tmp_path: Path, mine: dict[str, Any], theirs: dict[str, Any] | None
) -> None:
    repo = target_repo(tmp_path)
    baseline, candidate = fake_run(tmp_path, "base", repo), fake_run(tmp_path, "cand", repo)
    _write(baseline, _tiers(mine))
    _write(candidate, _tiers(theirs))
    for one, other in ((baseline, candidate), (candidate, baseline)):
        with pytest.raises(CompareRefusedError) as refused:
            compare(one, other)
        assert refused.value.context.get("drifted") == FIELD, "different left-out sets compared"
        assert "left out different held-out tasks" in str(refused.value)


def test_runs_on_one_version_that_left_out_the_same_tasks_are_compared(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline, candidate = fake_run(tmp_path, "base", repo), fake_run(tmp_path, "cand", repo)
    _write(baseline, _tiers(_left("a" * 16)))
    _write(candidate, _tiers(_left("a" * 16)))
    compare(baseline, candidate)


def test_a_record_written_before_any_was_left_out_keeps_its_bytes() -> None:
    assert b"held_out_left_out" not in _tiers(None)
