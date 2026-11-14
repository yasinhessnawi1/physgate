"""A protected trial's session and the harness's own files never share a directory.

A trial's directory holds two: the session's own place (``place``, the one directory the
session is given out of the run's held-out roots) and the harness's (``harness``, which the
session is never given: the copied answer, the session's record and the score are written
there). Whatever a session leaves at the names the harness writes (a link, a directory, a
file) is inert: the write does not follow it, does not collide with it, and nothing of the
trial is in a visible place afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    config,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)
from task_fixtures import controller, own_task

from physgate.evaluation.baseline.record import BASELINE_RECORD, TIERS_RECORD
from physgate.evaluation.baseline.runner import BASELINE_DIR, HARNESS, PLACE, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.store import role_root, version_dir, withheld_root, work_root
from physgate.evaluation.tiers.task import parse_task


def _score(_task: Any, answer: Path) -> dict[str, Any]:  # noqa: ANN401
    assert answer.is_file() and not answer.is_symlink()
    return dict(SCORED)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _plant(kind: str, name: str, decoy: Path) -> Callable[[Path, Path], None]:
    def plant(place: Path, _harness: Path) -> None:
        target = place / name
        if kind == "link":
            target.symlink_to(decoy)
        elif kind == "directory":
            target.mkdir()
            (target / "inside").write_text("planted")
        else:
            target.write_text("planted")

    return plant


NAMES = ["answer", "raw.json", "score.json"]
KINDS = ["link", "directory", "file"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("kind", KINDS)
def test_what_a_session_leaves_at_a_name_the_harness_writes_is_inert(
    tmp_path: Path, store: StandInStore, kind: str, name: str
) -> None:
    """The trial is taken and the harness's files are real files in its own directory.

    The decoy a planted link points at is as it was; nothing is left in a visible place.
    """
    task = store.tasks["held_out"][0]
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    decoy = tmp_path / "decoy.json"
    decoy.write_text("decoy")
    arm = StandInArm(left=_plant(kind, name, decoy))
    out = tmp_path / "round"
    places = [
        withheld_root(store.store, "control"),
        work_root(store.store, "control"),
        version_dir(store.store, "control", store.version),
    ]
    before = set(tmp_path.rglob("*"))
    outcome: BaseException | Any
    try:
        outcome = run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
        )
    except Exception as exc:  # noqa: BLE001 - asserted below, so a refusal is a failed row
        outcome = exc
    assert not isinstance(outcome, BaseException), f"the round stopped: {outcome!r}"
    record = outcome
    assert record.counts["held_out"].passed == 1
    assert decoy.read_text() == "decoy", "a write went through a planted link"
    (trial,) = (withheld_root(store.store, "control") / BASELINE_DIR).glob("*/0000-1")
    harness = trial / HARNESS
    assert not any(p.is_symlink() for p in harness.rglob("*")), "a link in the harness's files"
    for artefact in ("raw.json", "score.json"):
        assert (harness / artefact).is_file()
    assert (harness / "answer").is_dir()
    assert (trial / PLACE / name).exists() or kind == "link", "the session's own file was removed"
    # Nothing of the trial is outside the protected places but the round's own records.
    new_outside = {
        p.relative_to(tmp_path)
        for p in set(tmp_path.rglob("*")) - before
        if not any(p.is_relative_to(w) for w in places)
    }
    assert {p.name for p in new_outside} == {
        out.name,
        Path(TIERS_RECORD).name,
        Path(TIERS_RECORD).parent.name,
        BASELINE_RECORD,
    }, new_outside
    assert role_root(store.store, "control").is_dir()


def test_the_session_is_given_its_own_place_alone_and_never_the_harness_s(
    tmp_path: Path, store: StandInStore
) -> None:
    """The place given to the session is a directory of the trial's, beside the harness's."""
    task = store.tasks["held_out"][0]
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    given: list[tuple[str, Path, Path]] = []

    def seen(place: Path, harness: Path) -> None:
        given.append((place.name, place.parent, harness))

    arm = StandInArm(left=seen)
    run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=tmp_path / "round",
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
    )
    ((name, trial, harness),) = given
    assert name == PLACE and harness == trial / HARNESS
    assert not harness.is_relative_to(trial / PLACE)
    assert not (trial / PLACE).is_relative_to(harness)


@pytest.mark.parametrize("kind", KINDS)
def test_the_real_raw_arm_writes_the_copied_answer_and_its_record_beside_the_session_alone(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """What the session left at ``answer`` and ``raw.json`` in its own place changes nothing.

    The arm's copy and record land in the harness's directory as new files; no link is followed.
    """
    task = store.tasks["held_out"][0]
    decoy = tmp_path / "decoy.json"
    decoy.write_text("decoy")
    place, harness = tmp_path / "trial" / PLACE, tmp_path / "trial" / HARNESS
    harness.mkdir(parents=True)

    def session(
        _prompt: str,
        _setup: Any,  # noqa: ANN401
        work: Path,
        *,
        cap: int,
        identity: list[tuple[int, int]],
    ) -> dict[str, Any]:
        assert cap == 1
        work.mkdir()
        (work / "worktree").mkdir()
        identity.extend((i.st_dev, i.st_ino) for i in (work.stat(), (work / "worktree").stat()))
        (work / "worktree" / task.answer.path).write_text(json.dumps(controller()))
        for name in ("answer", "raw.json"):
            _plant(kind, name, decoy)(work, work)
        return {"end": "ended"}

    monkeypatch.setattr(raw, "run_session", session)
    setup = setup_for(config(task, store), "control")
    try:
        record = raw.run_raw(task, setup, place, cap=1, harness=harness)
    except Exception as exc:  # noqa: BLE001 - a refusal here is a failed row, asserted
        pytest.fail(f"the arm stopped on what the session left: {exc!r}")
    assert record["answer"] == "found"
    assert decoy.read_text() == "decoy", "a write went through a planted link"
    copied_answer = harness / "answer" / task.answer.path
    assert copied_answer.is_file() and not copied_answer.is_symlink()
    assert copied_answer.read_bytes() == (place / "worktree" / task.answer.path).read_bytes()
    assert (harness / "raw.json").is_file() and not (harness / "raw.json").is_symlink()
    assert json.loads((harness / "raw.json").read_text())["answer"] == "found"


def test_an_answer_that_is_a_link_out_of_the_session_s_place_is_not_taken(
    tmp_path: Path,
) -> None:
    """A link to a file outside the worktree, and a named pipe, are refused, not followed."""
    task = parse_task(json.dumps(own_task()).encode())
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    for make in (
        lambda w: (w / task.answer.path).symlink_to(outside),
        lambda w: os.mkfifo(w / task.answer.path),
    ):
        worktree = tmp_path / f"w{id(make)}"
        worktree.mkdir()
        make(worktree)
        out = tmp_path / f"out{id(make)}" / "answer.json"
        assert raw._take_answer(worktree, task, out) == "not_a_file"
        assert not out.exists()


def _swapped(swap: str, place: Path, outside: Path) -> None:
    """What a session able to write the directories it works in could do to them."""
    worktree = place / "worktree"
    if swap == "worktree to a link":
        worktree.rename(place / "moved")
        worktree.symlink_to(outside)
    elif swap == "worktree to another directory":
        worktree.rename(place / "moved")
        shutil.copytree(outside, worktree)
    else:  # the directory holding the worktree
        place.rename(place.with_name("moved"))
        place.symlink_to(outside.parent)


@pytest.mark.parametrize(
    "swap", ["worktree to a link", "worktree to another directory", "place to a link"]
)
def test_an_answer_is_not_taken_from_a_directory_the_session_swapped_for_another(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    """A link, or another directory, where the worktree or its holder was: nothing is read.

    What stands there afterwards holds a well-formed answer; it is refused, and nothing of
    it is copied to the harness's directory.
    """
    task = store.tasks["held_out"][0]
    outside = tmp_path / "outside" / "worktree"
    outside.mkdir(parents=True)
    (outside / task.answer.path).write_text(json.dumps(controller()))
    place, harness = tmp_path / "trial" / PLACE, tmp_path / "trial" / HARNESS
    harness.mkdir(parents=True)

    def session(
        _prompt: str,
        _setup: Any,  # noqa: ANN401
        work: Path,
        *,
        cap: int,  # noqa: ARG001
        identity: list[tuple[int, int]],
    ) -> dict[str, Any]:
        work.mkdir()
        (work / "worktree").mkdir()
        identity.extend((i.st_dev, i.st_ino) for i in (work.stat(), (work / "worktree").stat()))
        _swapped(swap, work, outside)
        return {"end": "ended"}

    monkeypatch.setattr(raw, "run_session", session)
    setup = setup_for(config(task, store), "control")
    record = raw.run_raw(task, setup, place, cap=1, harness=harness)
    assert record["answer"] == "not_a_file"
    assert not (harness / "answer").exists(), "something read from outside was copied"
