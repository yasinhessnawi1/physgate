"""The two arms of one cell wait for the account's usage limit alike, and count their pair once.

A harness trial whose role session meets the limit is waited for by the round driver: the command
exits with its status for the limit and prints a ``waiting`` line. Once the reset has passed the
driver resumes the run and assembles the trial. The baseline round then runs the raw arm on the
run set the driver wrote, and the raw session meets the limit too. The baseline round stops with
the driver's own status, exit status and ``waiting`` keys, each word the same; only the instant
differs, each arm's being the reset its own session's stream gave. After that reset the raw
session runs, and the pair is counted once in each arm. The limit cost neither arm an attempt,
nor made either trial unscored.

The harness half is the rig's (the real loop, a stand-in session); the raw half the baseline's
stand-in arm. Each role session's tool list is written where the command's installer leaves it,
which the rig's stand-in session does not. The rig's limited session reports no tokens, so what
the limit cost is held as attempts and unscored trials, not as tokens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from round_rig import PRICES, SCORED, Rig, StandInArm, make_rig, setup_for

from physgate.cli import main
from physgate.evaluation import harness_round
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import LEDGER as RAW_LEDGER
from physgate.evaluation.baseline.runner import TRIALS as RAW_TRIALS
from physgate.evaluation.baseline.runner import RoundWaits, RunSet, run_baseline
from physgate.evaluation.harness_round import HARNESS_ROUNDS, LEDGER, ROUND_RECORD, run_round
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import withheld_root
from physgate.hooks.settings import CONFIG_NAME, PROFILE_TOOLS
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT


@pytest.fixture
def trial_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The row's own place, named apart from the row (a review root's path is held to words)."""
    return tmp_path_factory.mktemp("trial")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _driver_waits(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], resets: str
) -> tuple[int, dict[str, Any]]:
    """The driver's command on one visible trial whose role session meets the limit."""
    driver = rig.driver(limited={1}, limit_resets_at=resets)
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _score)
    argv = [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", "visible", "--trials", "1", "--seed-base", "100", "--tasks", "1"),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", PRICES, "--out", str(rig.root / "out")),
    ]
    code = main(argv)
    (line,) = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(line)


def _driver_ledger(rig: Rig) -> list[dict[str, Any]]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])
    return [json.loads(x) for x in (place / LEDGER).read_bytes().splitlines()]


def _installed(run_dir: Path) -> None:
    """Each role session's generated configuration, where the command's installer leaves it.

    The rig's stand-in session installs nothing; the baseline's pair check reads the harness
    run's tool list from there.
    """
    body = {"profile": "role", "role": "control", "tools_allowed": list(PROFILE_TOOLS["role"])}
    for session in sorted(p for p in (run_dir / "sessions").iterdir() if p.is_dir()):
        (session / "session").mkdir(exist_ok=True)
        (session / "session" / CONFIG_NAME).write_text(json.dumps(body))


def _raw(rig: Rig, runs: RunSet, out: Path, arm: StandInArm, at: datetime, **how: Any) -> Any:  # noqa: ANN401
    """The baseline round on the driver's run set: its record, or the wait it raised."""
    try:
        return run_baseline(
            store=rig.made.store,
            role="control",
            version=rig.made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
            now=lambda: at,
            **how,
        )
    except RoundWaits as waits:
        return waits


def test_the_raw_arm_waits_for_the_limit_as_the_driver_does_and_the_pair_is_counted_once(
    trial_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(trial_dir)
    start = datetime.now(UTC).replace(microsecond=0)
    harness_resets = start + timedelta(hours=2)

    # The harness arm: the driver waits for the reset its role session's stream gave.
    code, printed = _driver_waits(rig, monkeypatch, capsys, utc_stamp(harness_resets))
    assert printed["status"] == "waiting_for_limit"
    driver_waiting = printed["waiting"]
    assert driver_waiting["resume_after"] == utc_stamp(harness_resets)
    after = harness_resets + timedelta(seconds=1)
    late = rig.driver()
    late.clock = lambda: after
    status, summary = run_round(
        rig.inputs(trials=1),
        driver=late,
        scorer=_score,
        resume=True,
        sleep=lambda _: None,
        now=lambda: after,
    )
    assert status == "done"
    runs = RunSet.model_validate_json((rig.root / "out" / "visible.runs.json").read_bytes())
    assert len(runs.trials) == 1
    _installed(Path(runs.trials[0].run_dir))

    # The raw arm of the same cell: its session meets the limit, with a reset of its own.
    raw_resets = after + timedelta(hours=1)
    arm = StandInArm(limited={1: int(raw_resets.timestamp())})
    out = rig.root / "raw-round"
    waits = _raw(rig, runs, out, arm, after)
    assert isinstance(waits, RoundWaits), f"the raw round did not wait: {waits!r}"
    # The driver's status, exit status and keys; each word the same, the instant each its own.
    assert waits.status == printed["status"]
    assert waits.exit_code == code == EXIT_WAITING_FOR_LIMIT
    assert set(waits.waiting) == set(driver_waiting)
    assert {k: v for k, v in waits.waiting.items() if k != "resume_after"} == {
        k: v for k, v in driver_waiting.items() if k != "resume_after"
    }
    assert waits.waiting["resume_after"] == utc_stamp(raw_resets)

    # After the raw session's reset it runs, and the pair is counted once in each arm.
    record = _raw(rig, runs, out, arm, raw_resets + timedelta(seconds=1), resume=True)
    assert isinstance(record, BaselineRecord), f"the raw round did not end: {record!r}"
    counts = record.counts["visible"]
    assert (counts.trials, counts.passed, counts.unscored) == (1, 1, 0)
    assert len((out / RAW_TRIALS).read_text().splitlines()) == 1
    assert len(arm.calls) == 2
    harness_trials = (rig.root / "out" / "visible.trials.jsonl").read_text().splitlines()
    assert len(harness_trials) == 1
    visible = summary["tiers"]["visible"]
    assert (visible["trials"], visible["assembled"], visible["pass"]) == (1, 1, 1)

    # What the limit cost: no attempt and no unscored trial, in either arm.
    ledger = _driver_ledger(rig)
    assert [x["attempt"] for x in ledger if x["kind"] == "placed"] == [1]
    assert [x for x in ledger if x["kind"] == "superseded"] == []
    (assembled,) = [x for x in ledger if x["kind"] == "assembled"]
    assert assembled["unscored"] is False and assembled["outcome"] == "pass"
    raw_kinds = [json.loads(x)["kind"] for x in (out / RAW_LEDGER).read_text().splitlines()]
    assert raw_kinds == ["round", "started", "limit", "started", "moving", "recorded"]
