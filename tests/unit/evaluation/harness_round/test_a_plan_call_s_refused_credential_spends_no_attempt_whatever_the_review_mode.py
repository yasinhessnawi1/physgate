"""A plan call's refused credential spends no attempt, whatever the plan's review mode.

Under ``observe`` the call's end is a failed decomposition with a run record; under a mode that
holds the plan (``on``) the rounds end void on it, with no run record. Either way the round names
the directory on a ``credential`` line with its spend, stops for a person (exit 77), and once the
credential is put right decomposes the trial afresh, spending none of its one more go: the void
is never superseded as the machine's, and no delay is slept for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import round_rig
from round_rig import SCORED, make_rig

from physgate.evaluation.harness_round import run_round


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _ledger(rig: round_rig.Rig) -> list[dict[str, Any]]:
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("mode", ["observe", "on"])
def test_a_plan_call_s_refused_credential_waits_for_a_person_and_spends_no_attempt(
    tmp_path: Path, mode: str
) -> None:
    rig = make_rig(tmp_path, design_review=mode)
    driver = rig.driver(fails={1: "credential_refused"})
    slept: list[float] = []
    status, summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=slept.append
    )
    assert status == "waiting_for_a_person"
    assert summary["waiting"]["why"] == "credential_refused"
    kinds = [(x["kind"], x.get("attempt")) for x in _ledger(rig)[1:]]
    assert kinds == [("placed", 1), ("credential", 1)]
    status, _summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, resume=True, sleep=slept.append
    )
    assert status == "done"
    lines = _ledger(rig)
    assert not [x for x in lines if x["kind"] == "superseded"]
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    assert (assembled["attempt"], assembled["outcome"]) == (2, "pass")
    assert slept == [], "a refused credential is no machine end: no delay is slept for it"
