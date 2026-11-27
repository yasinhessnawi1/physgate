"""A trial the harness arm ran once more has its raw pair run once more, under the re-run's cap.

Both arms on the rig: the harness round excludes a draw for a reason not to trust its answer (a
score whose verdict is not a bool), runs the trial again into a fresh directory, and writes its
one-entry run set and the sheet beside it naming the draw it superseded. A raw pair that had run
under the superseded draw (a run set built by hand) is run once more as a new round of its one
entry: the sheet names the superseded run, the earlier raw round is named, and the session is
capped at the re-run's own total. The raw arm reads exclusions by the harness round's own rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import PRICES, SCORED, Rig, StandInArm, make_rig, setup_for
from test_the_two_arms_wait_for_the_usage_limit_alike_and_count_a_pair_once import _installed

from physgate.evaluation.baseline.cli import replaced_run
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import RunSet, harness_figure, run_baseline
from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import withheld_root

UNREADABLE = {**SCORED, "passed": "yes"}


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _raw(rig: Rig, runs: RunSet, out: Path, arm: StandInArm, **how: Any) -> BaselineRecord:  # noqa: ANN401
    return run_baseline(
        store=rig.made.store,
        role="control",
        version=rig.made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=lambda _t, _a: dict(SCORED),
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
        **how,
    )


def test_a_raw_pair_that_ran_under_a_superseded_draw_runs_once_more_under_the_re_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    rig = make_rig(tmp_path_factory.mktemp("trial"))
    calls = [0]

    def score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
        calls[0] += 1
        return dict(UNREADABLE if calls[0] == 1 else SCORED)

    status, _ = run_round(
        rig.inputs(trials=1), driver=rig.driver(), scorer=score, sleep=lambda _: None
    )
    assert status == "done"
    lines = _ledger(rig)
    (excluded,) = [x for x in lines if x["kind"] == "excluded"]
    assembled = [x for x in lines if x["kind"] == "assembled"][-1]
    superseded, rerun = Path(excluded["run_dir"]), Path(assembled["run_dir"])
    for run_dir in (superseded, rerun):
        _installed(run_dir)
    one = rig.root / "out" / "trials" / "0000.runs.json"
    trial = RunSet.model_validate_json(one.read_bytes()).trials[0]
    earlier = tmp_path_factory.mktemp("raw") / "first"
    by_hand = {"format": 1, "trials": [{"run_dir": str(superseded), "trial": trial.trial}]}
    _raw(rig, RunSet.model_validate_json(json.dumps(by_hand)), earlier, StandInArm())
    assert replaced_run(one) == str(superseded)
    arm = StandInArm()
    again = _raw(
        rig,
        RunSet.model_validate_json(one.read_bytes()),
        earlier.parent / "again",
        arm,
        rerun_of=earlier,
        replaces=replaced_run(one),
    )
    assert again.rerun_of is not None and again.rerun_of["because"] == "harness_rerun"
    assert [cap for _, cap, _ in arm.calls] == [harness_figure(rerun)]
    assert harness_figure(rerun) != harness_figure(superseded)
