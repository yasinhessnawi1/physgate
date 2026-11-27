"""A complete round states every trial that gives no figure, and ends done where a cap is given.

A trial whose harness run gives the raw arm no figure (it ended at its decomposition, the machine
ended it after its one more go, it stands where a resume continues it, or a session was read with
no result to check it against) never blocks its pair: the cap rule gives its raw trial the largest
figure among the same task's other trials, else the middle figure of the cell. So the round
states each such trial in one recorded form (``no_figure``: why, from the run's own records, and
the refusal in words) on its ledger line and in its record, counts them in its summary, and ends
``done`` (exit 0) wherever a trial of the same tier gives a figure. Only a tier with no figure at
all, where the rule has nothing to take, ends the round ``done_without_caps`` (exit 3), and its
record names that tier.
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


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def test_a_round_with_a_trial_the_planner_failed_ends_done_and_states_its_no_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "invalid_plan"}))
    assert status == "done" and summary["done"] is True
    assert summary.get("no_cap") == {"visible": 1}
    assert summary.get("no_figure") == {"visible": 1}
    written = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    assert written.get("no_figure") == {"visible": 1}
    record = _record(rig)
    assert record.get("no_figure") == {"visible": 1}
    assert record.get("no_cap_in_the_cell") == []
    first, second = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    assert first["harness_total"] is None and second["harness_total"] is not None
    assert first["no_figure"]["because"] == "no_role_session"
    assert first["no_figure"]["detail"] == first["no_total"]
    assert second["no_figure"] is None
    assert [t["no_figure"] for t in record["trials"]] == [first["no_figure"], None]


def test_a_trial_unscored_at_its_decomposition_states_why_it_gives_no_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "api_error", 2: "api_error"}))
    assert status == "done" and summary.get("no_figure") == {"visible": 1}
    first = next(x for x in _ledger(rig) if x["kind"] == "assembled")
    assert (first["unscored"], first["no_figure"]["because"]) == (True, "unscored")


def test_a_round_whose_tier_gives_no_figure_at_all_ends_done_without_caps(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver(fails={1: "invalid_plan", 2: "invalid_plan"}))
    assert status == "done_without_caps" and summary.get("no_figure") == {"visible": 2}
    assert _record(rig).get("no_cap_in_the_cell") == ["visible"]


def test_a_round_whose_every_trial_has_a_cap_ends_done(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    status, summary = _round(rig, rig.driver())
    assert status == "done" and summary.get("no_cap") == {"visible": 0}
    assert summary.get("no_figure") == {"visible": 0}


@pytest.mark.parametrize(
    ("fails", "code"),
    [({1: "invalid_plan", 2: "invalid_plan"}, 3), ({1: "invalid_plan"}, 0), ({}, 0)],
)
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
    assert json.loads(line)["status"] == ("done_without_caps" if code == 3 else "done")


def test_a_session_read_with_no_result_to_check_it_against_is_a_leftover_unread(
    tmp_path: Path,
) -> None:
    # A driver killed while a role session ran leaves the session to be read at the resume with
    # no result: its usage is partial, so the run gives no figure, and the round says why. The
    # rig's kills fall before a session runs, so the log a resume reads so is written here.
    rig = make_rig(tmp_path)
    _round(rig, rig.driver())
    run_dir = Path(next(x for x in _ledger(rig) if x["kind"] == "assembled")["run_dir"])
    log = run_dir / "events.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    used = next(x for x in lines if x["kind"] == "tokens_used")
    used["partial"] = True
    log.write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert harness_round._no_figure_because(run_dir, unscored=False) == "leftover_unread"
