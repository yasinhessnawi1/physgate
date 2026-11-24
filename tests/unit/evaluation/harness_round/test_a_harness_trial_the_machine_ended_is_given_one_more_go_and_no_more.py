"""A trial the machine ended is given one more go, read from its run's own lines, and no more.

- A run halted on the machine (its infrastructure retries spent) is resumed once, after its first
  registered retry delay: the same run, never a new one. Halted on the machine again after that
  resume, the trial is ``unscored``. Resumed, then ended on its own with no answer, it is the
  harness's own fail.
- A run whose one decomposition call ended on the machine is superseded by one fresh
  decomposition into a new directory, after the same delay: the first run stays where it was,
  named in the ledger and the round's record with its cause and its spend, in no run set. A
  second such end is ``unscored``: there is no third.
- A decomposition that failed on its own (a plan it could not start) is the harness's own fail.
- The account's usage limit spends nothing: a run halted on it whose resume the command refuses
  before the reset, and a decomposition that ended on it, stop the round as waiting for the
  limit, with nothing written; started again after the reset (with the person's word where the
  reset was not read), the round goes on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import HARNESS_ROUNDS, LEDGER, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.events import Halted, read_events


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(
    rig: Rig,
    driver: StandInDriver,
    slept: list[float],
    *,
    resume: bool = False,
    limit_reset: bool = False,
) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=1),
        driver=driver,
        scorer=_score,
        resume=resume,
        limit_reset=limit_reset,
        sleep=slept.append,
    )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / summary["round"]


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _outcome(rig: Rig) -> str:
    (line,) = (rig.root / "out" / "visible.trials.jsonl").read_text().splitlines()
    return str(json.loads(line)["outcome"])


def _run_dirs(rig: Rig) -> list[str]:
    runs = RunSet.model_validate_json((rig.root / "out" / "visible.runs.json").read_bytes())
    return [Path(e.run_dir).name for e in runs.trials]


def _halts(rig: Rig, name: str) -> list[str]:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    events = read_events(rig.run_root / summary["round"] / name / "events.jsonl")
    return [e.reason for e in events if isinstance(e, Halted)]


def test_a_run_halted_on_the_machine_is_resumed_once_after_its_delay(tmp_path: Path) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(infra={1, 2})
    status, _ = _round(rig, driver, slept)
    assert status == "done"
    assert [(d.run_dir.name, d.resume) for d in driver.drives] == [
        ("0000-1", False),
        ("0000-1", True),
    ]
    assert slept == [7.0]
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1"]
    assert _halts(rig, "0000-1") == ["infrastructure_exhausted"]
    assert _outcome(rig) == "pass" and _run_dirs(rig) == ["0000-1"]


def test_a_run_halted_on_the_machine_again_after_its_one_resume_is_unscored(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(infra={1, 2, 3, 4})
    status, _ = _round(rig, driver, slept)
    assert status == "done"
    assert [d.resume for d in driver.drives] == [False, True]
    assert _halts(rig, "0000-1") == ["infrastructure_exhausted", "infrastructure_exhausted"]
    assert _outcome(rig) == "unscored"


def test_a_run_resumed_past_a_machine_halt_that_then_ends_with_no_answer_is_the_harness_s_fail(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(infra={1, 2}, silent={3})
    status, _ = _round(rig, driver, slept)
    assert status == "done"
    assert [d.resume for d in driver.drives] == [False, True]
    assert _outcome(rig) == "fail"


def test_a_decomposition_the_machine_ended_is_superseded_by_one_fresh_decomposition(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(fails={1: "api_error"})
    status, summary = _round(rig, driver, slept)
    assert status == "done" and summary["superseded"] == 1
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1", "0000-2"]
    assert slept == [7.0]
    (gone,) = _ledger(rig, "superseded")
    assert (gone["attempt"], gone["cause"], gone["tokens"]) == (1, "api_error", 70)
    assert _outcome(rig) == "pass" and _run_dirs(rig) == ["0000-2"]
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert [(x["attempt"], x["cause"], x["tokens"]) for x in record["superseded"]] == [
        (1, "api_error", 70)
    ]
    # Superseded, not erased: it stays beneath the run root, where the exposure scan reads it.
    first = rig.run_root / summary["round"] / "0000-1"
    assert (first / "events.jsonl").is_file()
    assert _halts(rig, "0000-1") == ["decomposition_failed"]


def test_a_second_decomposition_the_machine_ended_is_unscored_and_there_is_no_third(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(fails={1: "api_error", 2: "sandbox_unavailable"})
    status, _ = _round(rig, driver, slept)
    assert status == "done"
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1", "0000-2"]
    assert driver.drives == []
    assert _outcome(rig) == "unscored" and _run_dirs(rig) == ["0000-2"]
    assert len(_ledger(rig, "superseded")) == 1


def test_a_decomposition_that_failed_on_its_own_is_the_harness_s_fail_and_gives_no_cap(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    driver = rig.driver(fails={1: "invalid_plan"})
    status, _ = _round(rig, driver, slept)
    assert status == "done"
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1"]
    assert _ledger(rig, "superseded") == [] and slept == []
    assert _outcome(rig) == "fail"
    (assembled,) = _ledger(rig, "assembled")
    assert assembled["harness_total"] is None and "no role session" in assembled["no_total"]


def test_a_decomposition_ended_on_the_usage_limit_waits_for_the_reset_and_spends_nothing(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    first = rig.driver(fails={1: "usage_limit"})
    status, summary = _round(rig, first, slept)
    assert status == "waiting_for_limit" and summary["done"] is False
    assert [c.run_dir.name for c in first.decomposed] == ["0000-1"]
    assert [x["cause"] for x in _ledger(rig, "superseded")] == ["usage_limit"]
    placed = len(_ledger(rig, "placed"))
    # Started again before the person says the limit reset: still waiting, nothing made.
    again = rig.driver()
    status, _ = _round(rig, again, slept, resume=True)
    assert status == "waiting_for_limit"
    assert again.decomposed == [] and len(_ledger(rig, "placed")) == placed
    assert not (rig.run_root / summary["round"] / "0000-2").exists()
    # After the reset: the one fresh decomposition, and the trial is scored.
    after = rig.driver()
    status, _ = _round(rig, after, slept, resume=True, limit_reset=True)
    assert status == "done"
    assert [c.run_dir.name for c in after.decomposed] == ["0000-2"]
    assert _outcome(rig) == "pass" and _run_dirs(rig) == ["0000-2"]


def test_a_run_halted_on_the_usage_limit_waits_for_the_reset_and_its_resume_is_not_spent(
    tmp_path: Path,
) -> None:
    rig, slept = make_rig(tmp_path), []
    first = rig.driver(limited={1})
    status, summary = _round(rig, first, slept)
    assert status == "waiting_for_limit"
    log = rig.run_root / summary["round"] / "0000-1" / "events.jsonl"
    held = log.read_bytes()
    assert _halts(rig, "0000-1") == ["usage_limit"]
    # The command refuses the resume before the reset, writing nothing: the round waits again.
    again = rig.driver()
    status, _ = _round(rig, again, slept, resume=True)
    assert status == "waiting_for_limit"
    assert [d.resume for d in again.drives] == [True] and log.read_bytes() == held
    # Once the person says it reset (its reset was not read), the one resume goes on.
    after = rig.driver()
    status, _ = _round(rig, after, slept, resume=True, limit_reset=True)
    assert status == "done"
    assert [(d.resume, d.limit_reset) for d in after.drives] == [(True, True)]
    assert _halts(rig, "0000-1") == ["usage_limit"]
    assert _outcome(rig) == "pass" and _run_dirs(rig) == ["0000-1"]
    assert slept == []
