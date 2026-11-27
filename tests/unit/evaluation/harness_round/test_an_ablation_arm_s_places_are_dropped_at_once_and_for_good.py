"""An ablation arm's remaining places are dropped at once, and for good; its trials keep every rule.

A person's word (who and why) drops every place of the arm not yet assembled: written once on the
ledger, each placed directory dealt with as one left behind and named with what it held, never
taken on again and in no set. The harness's places go on alone. Every later start says the same
words, or is refused. Until then an arm's trial is held to the harness's rules: the machine's one
more go after the registered delay, a refused credential's wait for a person.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, make_rig
from test_an_ablation_arm_runs_beside_its_reference_and_is_never_read_as_the_harness import (
    ARM,
    _drawn,
    _inputs,
    _ledger,
    _place,
    _set,
)

from physgate.evaluation.harness_round import ROUND_RECORD, Drop, RoundError, run_round

WORD = Drop(by="time_rule", why="the remaining hours of the block no longer fit")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _go(rig: Rig, only: int | None, **how: Any) -> tuple[str, dict[str, Any]]:  # noqa: ANN401
    slept = how.pop("slept", [])
    arm = how.pop("arm", True)
    return run_round(
        _inputs(rig, arm=arm),
        driver=how.pop("driver"),
        scorer=_score,
        sleep=slept.append,
        only=only,
        **how,
    )


def _arm_places(rig: Rig) -> list[int]:
    _units, places = _drawn(rig, 2, 2)
    return [k for k, p in enumerate(places) if p[2] == ARM]


def test_a_drop_closes_the_arm_s_remaining_places_and_the_harness_goes_on_alone(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    _go(rig, 0, driver=driver)
    _go(rig, 1, driver=driver, resume=True)
    arm = _arm_places(rig)
    remaining = [k for k in arm if k > 1]
    status, summary = _go(rig, None, driver=driver, resume=True, drop=WORD)
    assert status == "done"
    (dropped,) = [x for x in _ledger(rig) if x["kind"] == "arm_dropped"]
    assert (dropped["arm"], dropped["by"], dropped["why"]) == (ARM, WORD.by, WORD.why)
    assert dropped["places"] == remaining
    assert dropped["left"] == [], "no place of the arm left was placed yet"
    # No dropped place was ever placed after the drop; every harness place was assembled.
    after = _ledger(rig)[_ledger(rig).index(dropped) + 1 :]
    assert not [x for x in after if x.get("index") in remaining]
    assert summary["tiers"]["visible"]["assembled"] == 4
    counts = summary["arms"][ARM]
    assert (counts["assembled"], counts["dropped"]) == (4 - len(remaining), len(remaining))
    assert counts["dropped_places"] == remaining
    out = rig.root / "out"
    assert [a for *_, a in _set(out / "visible.runs.json")] == [False] * 4
    assert len(_set(out / f"ablation.{ARM}.runs.json")) == 4 - len(remaining)
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert record["arms"][ARM]["dropped"]["places"] == remaining


def test_every_start_after_a_drop_says_the_same_words(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    _go(rig, 0, driver=driver)
    first_harness = next(k for k in range(8) if k not in _arm_places(rig) and k > 0)
    _go(rig, None, driver=driver, resume=True, drop=WORD)
    for word, reason in (
        (None, "ablation_dropped_unsaid"),
        (Drop(by="someone", why=WORD.why), "ablation_dropped_otherwise"),
        (Drop(by=WORD.by, why="another reason"), "ablation_dropped_otherwise"),
    ):
        with pytest.raises(RoundError) as refused:
            _go(rig, None, driver=driver, resume=True, drop=word)
        assert refused.value.context["refused_because"] == reason
    status, _summary = _go(rig, first_harness, driver=driver, resume=True, drop=WORD)
    assert status == "done"
    assert len([x for x in _ledger(rig) if x["kind"] == "arm_dropped"]) == 1


def test_a_dropped_place_is_never_taken_on_again(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    _go(rig, 0, driver=driver)
    arm = _arm_places(rig)
    dropped = next(k for k in arm if k > 0)
    first_harness = next(k for k in range(1, 8) if k not in arm)
    status, _ = _go(rig, first_harness, driver=driver, resume=True, drop=WORD)
    assert status == "trial_assembled"
    with pytest.raises(RoundError) as refused:
        _go(rig, dropped, driver=driver, resume=True, drop=WORD)
    assert refused.value.context["refused_because"] == "only_dropped"


def test_a_drop_is_refused_where_there_is_nothing_of_an_arm_to_drop(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver()
    with pytest.raises(RoundError) as fresh:
        _go(rig, 0, driver=driver, drop=WORD)
    assert fresh.value.context["refused_because"] == "ablation_drop_on_a_fresh_round"
    assert not (rig.root / "out").exists()
    _go(rig, 0, driver=driver)
    for word in (Drop(by="a person", why="x"), Drop(by="time_rule", why=" "), Drop("t", "a\nb")):
        with pytest.raises(RoundError) as said:
            _go(rig, None, driver=driver, resume=True, drop=word)
        assert said.value.context["refused_because"] == "ablation_drop_words"
    plain = make_rig(tmp_path / "plain")
    other = plain.driver()
    _go(plain, 0, driver=other, arm=False)
    with pytest.raises(RoundError) as no_arm:
        _go(plain, None, driver=other, resume=True, arm=False, drop=WORD)
    assert no_arm.value.context["refused_because"] == "ablation_drop_no_arm"
    done = make_rig(tmp_path / "done")
    whole = done.driver()
    for place in range(8):
        _go(done, place, driver=whole, resume=place > 0)
    with pytest.raises(RoundError) as nothing:
        _go(done, None, driver=whole, resume=True, drop=WORD)
    assert nothing.value.context["refused_because"] == "ablation_nothing_to_drop"


def test_a_drop_where_the_round_waits_at_an_arm_s_place_names_its_directory_and_goes_on(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    arm = _arm_places(rig)
    first = arm[0]
    # The arm's first trial's decomposition meets a refused credential: the round waits for a
    # person at that place.
    driver = rig.driver(fails={first + 1: "credential_refused"})
    for place in range(first + 1):
        status, summary = _go(rig, place, driver=driver, resume=place > 0)
    assert status == "waiting_for_a_person"
    assert summary["waiting"]["index"] == first
    # A word for the wait at a dropped place is for no wait.
    with pytest.raises(RoundError) as moot:
        _go(rig, None, driver=driver, resume=True, drop=WORD, credential_replaced=True)
    assert moot.value.context["refused_because"] == "credential_replaced_not_waiting"
    status, summary = _go(rig, None, driver=driver, resume=True, drop=WORD)
    assert status == "done"
    (dropped,) = [x for x in _ledger(rig) if x["kind"] == "arm_dropped"]
    (left,) = dropped["left"]
    assert (left["index"], left["attempt"]) == (first, 1)
    assert left["held"], "the directory's entries are named"
    assert Path(left["run_dir"]).is_dir(), "a dropped place's directory stays where it is"
    assert summary["tiers"]["visible"]["assembled"] == 4


def test_an_arm_s_trial_the_machine_ended_is_resumed_once_after_its_delay(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    first = _arm_places(rig)[0]
    # One session per trial before it: the arm's first trial's session and its retry end on the
    # machine, so its run halts on it and is resumed once, as a harness trial's is.
    driver = rig.driver(infra={first + 1, first + 2})
    slept: list[float] = []
    for place in range(first + 1):
        status, _ = _go(rig, place, driver=driver, resume=place > 0, slept=slept)
    assert status == "trial_assembled"
    drives = [
        (d.run_dir.name, d.resume)
        for d in driver.drives
        if d.run_dir.name.startswith(f"{first:04d}-")
    ]
    assert drives == [(f"{first:04d}-1", False), (f"{first:04d}-1", True)]
    assert slept == [7.0]
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled" and x["index"] == first]
    assert (assembled["arm"], assembled["outcome"]) == (ARM, "pass")
