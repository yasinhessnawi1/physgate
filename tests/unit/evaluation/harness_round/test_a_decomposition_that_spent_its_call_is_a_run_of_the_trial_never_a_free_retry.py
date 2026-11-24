"""A decomposition that spent its call is a run of the trial, never a free retry.

The plan's review is on (``design_review: observe``, as a measured run's is), and the decomposition
goes through the core's own rounds with its call and its review scripted.

- A directory is set aside for free only when its own records show that no call was made and no
  session started: the parameters recorded, nothing else. That is named in the ledger and the
  round's record with what the directory held, and is no attempt; a second for the same trial
  stops the round for a person.
- A decomposition that made its call and left no run (killed after the call, killed during the
  plan's review, or ended void) is superseded once: kept where it is, named with its cause
  (``killed``, or the void's) and its spend (read from the round journal's end lines, or
  ``unread`` where only a start line was written), in no run set and no cap. One fresh
  decomposition follows after the registered delay, and that is the trial's one more go.
- Once the trial's one more go is spent, such a directory stops the round for a person (exit 77),
  naming the trial, its directory, its cause and its spend: there is no run to count. Only a
  restart that names the trial sets it aside, recorded as the operator's act.
- Before a directory is left behind, the round does what the core's commands do with one a killed
  decomposition left: the credential files of its sessions no process runs as are removed, the
  plan's review session left running is stopped, and its stream is scanned for the held-out
  canaries; one that showed one stops the round.
"""

from __future__ import annotations

import inspect
import json
import os
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Killed, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import (
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    RoundError,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator.processes import started_at

#: The decomposition's one call, as the stand-in's call spends it, and the plan review's.
CALL_TOKENS = 70


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.fixture
def drivers() -> Iterator[list[StandInDriver]]:
    """Every driver a row makes; a review session one of them left running is stopped after."""
    made: list[StandInDriver] = []
    yield made
    for driver in made:
        for pid, _sid in driver.left_reviews:
            if started_at(pid) is not None:
                os.kill(pid, signal.SIGKILL)


def _driver(rig: Rig, drivers: list[StandInDriver], **how: Any) -> StandInDriver:  # noqa: ANN401
    driver = rig.driver(**how)
    drivers.append(driver)
    return driver


def _go(
    rig: Rig,
    driver: StandInDriver,
    slept: list[float],
    *,
    resume: bool = False,
    set_aside: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """The round's status and summary, or the reason it was refused and its context."""
    given: dict[str, Any] = {}
    if set_aside is not None:
        assert "set_aside" in inspect.signature(run_round).parameters, "no restart names a trial"
        given["set_aside"] = set_aside
    try:
        status, summary = run_round(
            rig.inputs(trials=1),
            driver=driver,
            scorer=_score,
            resume=resume,
            sleep=slept.append,
            **given,
        )
    except RoundError as exc:
        return f"refused:{exc.context.get('refused_because')}", dict(exc.context)
    return status, summary


def _killed(rig: Rig, driver: StandInDriver, *, resume: bool = False) -> None:
    with pytest.raises(Killed):
        run_round(
            rig.inputs(trials=1), driver=driver, scorer=_score, resume=resume, sleep=lambda _: None
        )


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if x["kind"] == kind]


def _outcomes(rig: Rig) -> list[str]:
    path = rig.root / "out" / "visible.trials.jsonl"
    return (
        [json.loads(x)["outcome"] for x in path.read_text().splitlines()] if path.exists() else []
    )


def _gone(rig: Rig, attempt: int) -> list[tuple[Any, ...]]:
    return [
        (x["attempt"], x["cause"], x["tokens"], x["by"])
        for x in _ledger(rig, "superseded")
        if x["attempt"] == attempt
    ]


def test_a_decomposition_killed_after_its_call_is_superseded_once_with_its_spend_unread(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_after_call={1}))
    then = _driver(rig, drivers)
    status, _ = _go(rig, then, slept, resume=True)
    assert status == "done"
    assert _gone(rig, 1) == [(1, "killed", "unread", "rule")]
    assert [c.run_dir.name for c in then.decomposed] == ["0000-2"] and slept == [7.0]
    assert _ledger(rig, "left") == [] and _outcomes(rig) == ["pass"]
    # Kept where it was, for the exposure scan.
    assert (rig.run_root / _place(rig).name / "0000-1" / "decomposition").is_dir()


def test_a_decomposition_that_ended_void_after_its_round_is_superseded_with_its_spend(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    driver = _driver(rig, drivers, start_raises={1})
    status, _ = _go(rig, driver, slept)
    assert status == "done"
    assert _gone(rig, 1) == [(1, "RunStateError", CALL_TOKENS + 10, "rule")]
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1", "0000-2"]
    assert _outcomes(rig) == ["pass"]


def test_a_second_spent_decomposition_stops_the_round_for_a_person_until_a_restart_names_it(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_after_call={1}))
    _killed(rig, _driver(rig, drivers, killed_after_call={1}), resume=True)
    again = _driver(rig, drivers)
    status, summary = _go(rig, again, slept, resume=True)
    assert status == "waiting_for_a_person"
    assert again.decomposed == [] and _ledger(rig, "assembled") == []
    waiting = summary["waiting"]
    assert (waiting["index"], waiting["cause"], waiting["tokens"]) == (0, "killed", "unread")
    assert Path(waiting["run_dir"]).name == "0000-2"
    # Without the flag the round stays stopped, however often it is started.
    status, _ = _go(rig, _driver(rig, drivers), slept, resume=True)
    assert status == "waiting_for_a_person" and len(_ledger(rig, "superseded")) == 1
    named = _driver(rig, drivers)
    status, _ = _go(rig, named, slept, resume=True, set_aside=0)
    assert status == "done" and _outcomes(rig) == ["pass"]
    assert [c.run_dir.name for c in named.decomposed] == ["0000-3"]
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    (trial,) = record["trials"]
    assert [(x["attempt"], x["cause"], x["tokens"], x["by"]) for x in trial["superseded"]] == [
        (1, "killed", "unread", "rule"),
        (2, "killed", "unread", "operator"),
    ]


def test_a_void_a_person_must_fix_says_so_when_it_stops_the_round(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    driver = _driver(rig, drivers, review_errs={1: "model_separation", 2: "model_separation"})
    status, summary = _go(rig, driver, slept)
    assert status == "waiting_for_a_person"
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1", "0000-2"]
    waiting = summary["waiting"]
    assert waiting["cause"] == "model_separation" and waiting["fix_first"] is True
    assert _gone(rig, 1)[0][1] == "model_separation"


def test_a_decomposition_killed_during_its_plan_s_review_leaves_nothing_running_or_unread(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    first = _driver(rig, drivers, killed_in_review={1})
    _killed(rig, first)
    ((pid, _sid),) = first.left_reviews
    assert started_at(pid) is not None  # the review session the kill left still runs
    status, _ = _go(rig, _driver(rig, drivers), slept, resume=True)
    assert status == "done"
    assert started_at(pid) is None, "the left review session still runs"
    keys = [p for p in rig.run_root.rglob("key") if p.parent.name == "state"]
    assert keys == [], "a credential file stays beneath the run root"
    assert _gone(rig, 1) == [(1, "killed", "unread", "rule")]
    assert _outcomes(rig) == ["pass"]


def test_a_left_review_whose_stream_showed_a_held_out_canary_stops_the_round(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    canary = sorted(rig.made.canaries)[0]
    _killed(rig, _driver(rig, drivers, killed_in_review={1}, review_shows=f"read {canary}"))
    then = _driver(rig, drivers)
    status, _ = _go(rig, then, [], resume=True)
    assert status == "refused:left_review_exposed"
    assert then.decomposed == [] and _ledger(rig, "superseded") == []
    left = rig.run_root / _place(rig).name / "0000-1"
    assert (left / "decomposition" / "review_exposed.json").is_file()


def test_a_directory_with_only_its_parameters_recorded_is_set_aside_once_and_named(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_in_decompose={1}))
    status, _ = _go(rig, _driver(rig, drivers), slept, resume=True)
    assert status == "done" and _outcomes(rig) == ["pass"]
    (left,) = _ledger(rig, "left")
    assert (left["attempt"], left["by"]) == (1, "rule")
    assert left["held"] == ["params_source.json", "review", "target"]
    assert _ledger(rig, "superseded") == [] and slept == []
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert [(x["attempt"], x["held"]) for x in record["left"]] == [(1, left["held"])]


def test_a_second_free_set_aside_for_one_trial_stops_the_round_for_a_person(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_in_decompose={1}))
    _killed(rig, _driver(rig, drivers, killed_in_decompose={1}), resume=True)
    again = _driver(rig, drivers)
    status, summary = _go(rig, again, slept, resume=True)
    assert status == "waiting_for_a_person" and again.decomposed == []
    assert summary["waiting"]["index"] == 0 and len(_ledger(rig, "left")) == 1
    status, _ = _go(rig, _driver(rig, drivers), slept, resume=True, set_aside=0)
    assert status == "done"
    assert [(x["attempt"], x["by"]) for x in _ledger(rig, "left")] == [(1, "rule"), (2, "operator")]


def test_a_restart_that_names_a_trial_the_round_is_not_stopped_at_is_refused(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_after_call={1}))
    lines = (_place(rig) / LEDGER).read_bytes()
    named = _driver(rig, drivers)
    status, _ = _go(rig, named, slept, resume=True, set_aside=0)
    assert status == "refused:set_aside_not_waiting"
    assert named.decomposed == [] and (_place(rig) / LEDGER).read_bytes() == lines
