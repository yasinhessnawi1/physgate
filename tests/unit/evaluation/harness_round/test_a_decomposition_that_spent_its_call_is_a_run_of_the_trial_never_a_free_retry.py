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
  canaries; one that showed one stops the round. A restart does that first, for every directory
  the round placed, before anything can refuse it: a refused start leaves no left review running
  and no credential of one on disk.
"""

from __future__ import annotations

import fcntl
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
from physgate.evaluation.tiers.exposure import exposed_versions
from physgate.evaluation.tiers.store import withheld_root
from physgate.orchestrator import decomposition_review
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


def _keys(rig: Rig) -> list[Path]:
    """The credential files of sessions beneath the run root, as a session's login puts one."""
    return [p for p in rig.run_root.rglob("key") if p.parent.name == "state"]


def test_a_start_refused_for_a_left_review_s_canary_leaves_no_credential_and_nothing_running(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    canary = sorted(rig.made.canaries)[0]
    first = _driver(rig, drivers, killed_in_review={1}, review_shows=f"read {canary}")
    _killed(rig, first)
    ((pid, _sid),) = first.left_reviews
    assert started_at(pid) is not None and _keys(rig) != []
    status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "refused:left_review_exposed"
    # Dealt with before the refusal: the session stopped, its credential gone.
    assert started_at(pid) is None, "the left review session still runs"
    assert _keys(rig) == [], "a credential file stays beneath the run root"
    # The register counts it too, and a later start is refused again, by the same word.
    assert rig.made.version in exposed_versions(rig.made.store, "control")
    status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "refused:left_review_exposed"


def test_a_refused_start_deals_with_every_directory_the_round_left_not_only_the_first(
    tmp_path: Path, drivers: list[StandInDriver], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    canary = sorted(rig.made.canaries)[0]
    first = _driver(rig, drivers, killed_in_review={1})
    _killed(rig, first)
    # Started again while the process table cannot say whether the first left review runs: the
    # stop keeps its record and signals nothing, so it is left; the trial's one more go is then
    # killed in its own review. Two directories are left, each with a review still running.
    with monkeypatch.context() as patch:

        def unreadable(*_: Any) -> bool:  # noqa: ANN401
            msg = "ps could not be run"
            raise OSError(msg)

        patch.setattr(decomposition_review, "is_session", unreadable)
        second = _driver(rig, drivers, killed_in_review={1})
        _killed(rig, second, resume=True)
    left = [*first.left_reviews, *second.left_reviews]
    assert len(left) == 2 and all(started_at(pid) is not None for pid, _ in left)
    # The first, still running, writes the canary into its stream after that start read it.
    (stream,) = (rig.run_root / _place(rig).name / "0000-1" / "review").rglob("stdout.jsonl")
    with stream.open("a") as written:
        written.write(json.dumps({"type": "assistant", "text": f"read {canary}"}) + "\n")
    status, said = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "refused:left_review_exposed"
    assert (said["index"], said["attempt"], said["directories"]) == ("0", "1", "1")
    # Every directory dealt with before the refusal, the one after the exposed one too.
    assert [pid for pid, _ in left if started_at(pid) is not None] == []
    assert _keys(rig) == [], "a credential file stays beneath the run root"


def test_a_review_that_showed_the_canary_and_raised_in_the_round_s_own_process_stops_it(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    canary = sorted(rig.made.canaries)[0]
    driver = _driver(
        rig, drivers, review_errs={1: "invocation_error"}, review_shows=f"read {canary}"
    )
    status, said = _go(rig, driver, [])
    assert status == "refused:left_review_exposed"
    assert (said["index"], said["attempt"]) == ("0", "1")
    assert [c.run_dir.name for c in driver.decomposed] == ["0000-1"]
    assert _ledger(rig, "superseded") == [] and _keys(rig) == []


def test_a_restart_deals_only_with_the_directories_its_own_ledger_placed(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    first = _driver(rig, drivers, killed_in_review={1})
    _killed(rig, first)
    ((pid, _sid),) = first.left_reviews
    # Another round beneath the same run root, made and started again: it touches nothing of the
    # first round's, whose left review still runs with its credential.
    other = rig.inputs(trials=1, out=rig.root / "other")
    for resume in (False, True):
        made, _ = run_round(
            other, driver=_driver(rig, drivers), scorer=_score, resume=resume, sleep=lambda _: None
        )
        assert made == "done"
    assert started_at(pid) is not None and len(_keys(rig)) == 1
    status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "done" and started_at(pid) is None and _keys(rig) == []


def test_a_restart_given_another_run_root_deals_with_the_round_s_own_directories_first(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    first = _driver(rig, drivers, killed_in_review={1})
    _killed(rig, first)
    ((pid, _sid),) = first.left_reviews
    elsewhere = rig.root / "elsewhere"
    elsewhere.mkdir()
    # The directories are the ones the round's ledger placed, beneath the run root it records:
    # never found beneath the root a restart names.
    with pytest.raises(RoundError) as refused:
        run_round(
            rig.inputs(trials=1, run_root=elsewhere),
            driver=_driver(rig, drivers),
            scorer=_score,
            resume=True,
            sleep=lambda _: None,
        )
    assert refused.value.context.get("refused_because") == "run_root_not_registered"
    assert started_at(pid) is None and _keys(rig) == []
    status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "done" and _outcomes(rig) == ["pass"]


def test_a_start_refused_because_another_driver_holds_the_round_touches_nothing(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    first = _driver(rig, drivers, killed_in_review={1})
    _killed(rig, first)
    ((pid, _sid),) = first.left_reviews
    held = os.open(_place(rig) / "driver.lock", os.O_RDWR)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
        assert status == "refused:round_held"
        # The round may be driven now: what its driver runs is its own to stop.
        assert started_at(pid) is not None and len(_keys(rig)) == 1
    finally:
        os.close(held)
    status, _ = _go(rig, _driver(rig, drivers), [], resume=True)
    assert status == "done" and started_at(pid) is None and _keys(rig) == []


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


def test_the_operator_s_word_sets_aside_one_directory_and_a_void_after_it_stops_the_round_again(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_after_call={1}))
    _killed(rig, _driver(rig, drivers, killed_after_call={1}), resume=True)
    named = _driver(rig, drivers, review_errs={1: "model_separation"})
    status, summary = _go(rig, named, slept, resume=True, set_aside=0)
    # The word took the second directory; the third ended void in the same process, and the
    # round stops for a person again rather than taking the word for it too.
    assert status == "waiting_for_a_person"
    assert [c.run_dir.name for c in named.decomposed] == ["0000-3"]
    assert Path(summary["waiting"]["run_dir"]).name == "0000-3"
    assert [(x["attempt"], x["by"]) for x in _ledger(rig, "superseded")] == [
        (1, "rule"),
        (2, "operator"),
    ]


def test_a_directory_whose_review_root_holds_anything_is_never_set_aside_free(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_in_decompose={1}))
    # A review session's directory beneath the run's review root: a session may have started.
    left = rig.run_root / _place(rig).name / "0000-1" / "review" / "a-session"
    left.mkdir(parents=True)
    status, _ = _go(rig, _driver(rig, drivers), slept, resume=True)
    assert status == "done" and _outcomes(rig) == ["pass"]
    assert _ledger(rig, "left") == []
    assert _gone(rig, 1) == [(1, "killed", "unread", "rule")]


def test_a_call_its_schema_refused_is_counted_in_the_superseded_decomposition_s_spend(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    driver = _driver(rig, drivers, schema_refused_first={1}, start_raises={1})
    status, _ = _go(rig, driver, slept)
    assert status == "done"
    # The refused call (70), the call made once more (70) and the plan's review (10).
    assert _gone(rig, 1) == [(1, "RunStateError", 2 * CALL_TOKENS + 10, "rule")]


def test_a_decomposition_superseded_with_no_run_spends_the_trial_s_one_more_go(
    tmp_path: Path, drivers: list[StandInDriver]
) -> None:
    rig, slept = make_rig(tmp_path, design_review="observe"), list[float]()
    _killed(rig, _driver(rig, drivers, killed_after_call={1}))
    then = _driver(rig, drivers, fails={1: "api_error"})
    status, _ = _go(rig, then, slept, resume=True)
    # The fresh decomposition was the one more go: the machine's end there is the trial's.
    assert status == "done_without_caps"
    assert [c.run_dir.name for c in then.decomposed] == ["0000-2"]
    assert [x["attempt"] for x in _ledger(rig, "superseded")] == [1]
    assert _outcomes(rig) == ["unscored"]
