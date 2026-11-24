"""A complete round says when the baseline's plan will refuse its run set, and how many trials why.

A trial whose harness run had no role session (it ended at its decomposition: the machine's end
after the trial's one more go, or the planner's own failure) gives no cap for a raw session, and
one such trial makes the baseline's plan refuse the whole combined set until a cap rule for it
exists. So a round whose every trial is assembled, but some of whose trials have no cap, ends
``done_without_caps`` with an exit status of its own (3), and says how many of the visible tier's
trials have none, in its summary and its output directory; every tier's count is in its record
beneath the withheld root. A round whose every trial has a cap ends ``done`` and exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import HARNESS_ROUNDS, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: StandInDriver) -> tuple[str, dict[str, Any]]:
    status, summary = run_round(
        rig.inputs(trials=2), driver=driver, scorer=_score, sleep=lambda _: None
    )
    return status, summary


def _record(rig: Rig) -> dict[str, Any]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return dict(json.loads((place / ROUND_RECORD).read_bytes()))


def test_a_round_with_a_trial_the_planner_failed_ends_done_without_caps_and_counts_it(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "invalid_plan"}))
    assert status == "done_without_caps" and summary["done"] is True
    assert summary.get("no_cap") == {"visible": 1}
    written = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    assert written.get("no_cap") == {"visible": 1}
    assert _record(rig).get("no_cap") == {"visible": 1}


def test_a_round_with_a_trial_unscored_at_its_decomposition_ends_done_without_caps(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "api_error", 2: "api_error"}))
    assert status == "done_without_caps" and summary.get("no_cap") == {"visible": 1}


def test_a_round_whose_every_trial_has_a_cap_ends_done(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver())
    assert status == "done" and summary.get("no_cap") == {"visible": 0}


@pytest.mark.parametrize(("fails", "code"), [({1: "invalid_plan"}, 3), ({}, 0)])
def test_the_command_exits_3_when_done_without_caps_and_0_when_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fails: dict[int, str],
    code: int,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(fails=fails)
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _score)
    argv = [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", "visible", "--trials", "2", "--seed-base", "100", "--tasks", "1"),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
    ]
    assert main(argv) == code
    (line,) = capsys.readouterr().out.strip().splitlines()
    assert json.loads(line)["status"] == ("done_without_caps" if fails else "done")
