"""The record audit derives a harness round's records again from its runs, by the round's own step.

A round the driver ran (its runs made by the real loop on the rig's stand-in store) leaves its run
set and its trial records; the audit runs the round's own assembly again on each run's directory
and finds nothing to differ. A record doctored in its outcome, its gate's counts or its reviews'
counts is caught by that kind and the trial's place; the scratch place the audit took answers into
is gone afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, make_rig

from physgate.evaluation.baseline.audit import HarnessCell, audit_harness
from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import run_round
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import withheld_root

PRICES = "2026-10-16"


@pytest.fixture
def trial_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The row's own place, named apart from the row (a review root's path is held to words)."""
    return tmp_path_factory.mktemp("trial")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(trial_dir: Path) -> tuple[Any, Path, Path]:  # noqa: ANN401
    rig = make_rig(trial_dir)
    status, _ = run_round(
        rig.inputs(trials=1), driver=rig.driver(), scorer=_score, sleep=lambda _: None
    )
    assert status in ("done", "done_without_caps")
    out = rig.root / "out"
    return rig, out / "visible.runs.json", out / "visible.trials.jsonl"


def _audit(rig: Any, runs: Path, trials: Path) -> list[Any]:  # noqa: ANN401
    scratch = withheld_root(rig.made.store, "control") / "audit-scratch"
    found = audit_harness(
        store=rig.made.store,
        role="control",
        version=rig.made.version,
        cells=[HarnessCell("visible", RunSet.model_validate_json(runs.read_bytes()), trials)],
        prices=load_price_sheet(PRICES),
        score=_score,
        scratch=scratch,
    )
    assert not scratch.exists(), "the answers taken for the audit are removed"
    return found


def test_a_harness_round_s_records_are_derived_again_the_same(trial_dir: Path) -> None:
    rig, runs, trials = _round(trial_dir)
    assert json.loads(trials.read_text().splitlines()[0])["outcome"] == "pass"
    assert _audit(rig, runs, trials) == []


@pytest.mark.parametrize("kind", ["outcome", "gate", "review"])
def test_a_harness_record_doctored_is_caught_by_its_kind_and_place(
    trial_dir: Path, kind: str
) -> None:
    rig, runs, trials = _round(trial_dir)
    line = json.loads(trials.read_text().splitlines()[0])
    if kind == "outcome":
        line["outcome"] = "fail"
    elif kind == "gate":
        line["gate"] = {**line["gate"], "checks_run": line["gate"]["checks_run"] + 1}
    else:
        line["review"] = {**line["review"], "reviews": line["review"]["reviews"] + 1}
    trials.write_text(json.dumps(line) + "\n")
    found = _audit(rig, runs, trials)
    assert [(d.kind, d.index, d.arm) for d in found] == [(kind, 0, "harness")]
