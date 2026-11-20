"""``compare`` refuses two runs on one tier version whose held-out counts left out different tasks.

The tiers record beside a run (``evaluation/tiers.json``) says, for a round on a version, how many
held-out tasks its version's blind check flagged and the round left out, the check record's digest
and its source, never which tasks. One left-out set is one record: two records of one version that
name different check records, or of which one left out what a check flagged and the other names
none, are not counts of one tier, and the comparison is refused, in words of its own and naming
the field. Two that name the same record are compared.
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


def _left(count: int = 1, check: str = "c" * 64, source: str = "check") -> dict[str, Any]:
    return {"count": count, "check_sha256": check, "source": source}


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
        (_left(), _left(check="d" * 64)),
        (_left(), _left(0, check="d" * 64)),
        (_left(), None),
        (_left(), _left(check="d" * 64, source="imported")),
    ],
    ids=["another record", "none left out", "one record before there was any", "imported"],
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
        assert "left out what different check records flagged" in str(refused.value)


def test_runs_on_one_version_that_left_out_the_same_tasks_are_compared(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    baseline, candidate = fake_run(tmp_path, "base", repo), fake_run(tmp_path, "cand", repo)
    _write(baseline, _tiers(_left()))
    _write(candidate, _tiers(_left()))
    compare(baseline, candidate)


def test_a_tiers_record_that_names_which_tasks_were_left_out_is_not_one() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _tiers({**_left(), "digests": ["a" * 16]})


def test_a_record_written_before_any_was_left_out_keeps_its_bytes() -> None:
    assert b"held_out_left_out" not in _tiers(None)
