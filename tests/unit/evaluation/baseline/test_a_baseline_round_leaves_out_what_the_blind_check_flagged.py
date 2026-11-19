"""A baseline round leaves out what its version's blind check flagged, and is refused without it.

A round on a version whose check is not recorded is refused before any session: a held-out tier
nobody checked is not scored. A harness trial of a held-out task the check flagged is not run;
the round's held-out count leaves it out, and its tiers record says how many, with the check
record's digest and its source: never which, since a run's directory may be published and a task's
id may be guessed. The visible and validation trials are run whole.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import TIERS_RECORD, BaselineRecord
from physgate.evaluation.baseline.runner import BaselineError, RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.checks import read_check
from physgate.evaluation.tiers.task import Task, id_digest

_slept: list[float] = []


def _score(task: Task, answer: Path) -> dict[str, object]:
    return dict(SCORED)


def _round(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm) -> BaselineRecord:
    return run_baseline(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=_slept.append,
    )


def _runs(tmp_path: Path, made: StandInStore) -> RunSet:
    tasks = [made.tasks["visible"][0], made.tasks["validation"][0], *made.tasks["held_out"][:3]]
    return run_set(*((harness_run(tmp_path / "runs", task, made), 0) for task in tasks))


def test_a_round_on_a_version_with_no_check_record_is_refused_before_any_session(
    tmp_path: Path,
) -> None:
    made = stand_in_store(tmp_path / "u", checked=False)
    arm = StandInArm()
    with pytest.raises(BaselineError) as refused:
        _round(made, _runs(tmp_path, made), tmp_path / "round", arm)
    assert refused.value.context.get("refused_because") == "held_out_unchecked"
    assert arm.calls == [], "a session ran on a version nobody checked"


def test_a_flagged_held_out_task_is_not_run_and_the_round_says_what_it_left_out(
    tmp_path: Path,
) -> None:
    made = stand_in_store(tmp_path / "s", flagged=(0,))
    flagged = made.tasks["held_out"][0]
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(made, _runs(tmp_path, made), out, arm)
    ran = [task for task, _, _ in arm.calls]
    assert flagged.id not in ran, "a flagged task was run"
    assert len(ran) == 4
    assert record.counts["held_out"].trials == 2, "a flagged task was counted"
    assert record.counts["visible"].trials == 1 and record.counts["validation"].trials == 1
    tiers = json.loads((out / TIERS_RECORD).read_text())
    check = read_check(made.store, "control", made.version)
    assert check is not None
    assert tiers["held_out_left_out"] == {
        "count": 1,
        "check_sha256": check.sha256,
        "source": "check",
    }, "the tiers record does not say how many were left out, or says which"
    assert record.tiers is not None and record.tiers.held_out_left_out is not None
    assert record.tiers.held_out_left_out.count == 1
    for task in made.tasks["held_out"]:
        text = (out / TIERS_RECORD).read_text() + (out / "baseline.json").read_text()
        assert task.id not in text and id_digest(task.id) not in text, "a held-out task is named"
