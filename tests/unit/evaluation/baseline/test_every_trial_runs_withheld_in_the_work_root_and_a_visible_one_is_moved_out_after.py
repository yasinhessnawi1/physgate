"""Every trial runs in the store's withheld work root; a visible one is moved out once it ends.

A round's trials, visible or protected, are made where a protected trial's always were: in the
role's work root, which every run on the store withholds, each session given its own place out
of the run's held-out roots and nothing else there. The round's own directory, where finished
visible trials and the round's records lie, is withheld from every session besides. So a
session reads and writes its own place and nothing else of the round: not a sibling trial's
place or harness files, not a finished trial's score, not the round's directory itself.

Once a visible trial has ended, the harness moves its whole directory beneath the round's,
``work/<name>``: the destination made new (one already there refuses the move), nothing
followed. Where the two lie on different filesystems the move is a copy, file by file, each
read as every file a session could have reached is read and written as a new file, and the
source removed only after the copy is whole. A move that fails leaves nothing half made beneath
the round's directory and the trial in the work root with its record, as a protected trial
stopped at any step is left. A protected trial is not moved out, as before.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import io
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)
from startup_stand_in import stand_in_spawn_env

from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import HARNESS, PLACE, SCORE, TRIALS, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.tiers.store import WORKING, role_root, work_root
from physgate.evaluation.tiers.task import Task
from physgate.hooks import paths
from physgate.hooks.cli import add_parser
from physgate.hooks.config import SessionConfig
from physgate.oslayer.session_temp import session_temps_root

OWN_TEMP = Path(session_temps_root()) / "0123456789"


def _score(_task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


def _round(store: StandInStore, base: Path, arm: Any, *tiers: str) -> BaselineRecord:  # noqa: ANN401
    """A round on one task of each of ``tiers``, in order, into ``base / "round"``."""
    seen: dict[str, int] = {}
    tasks = []
    for tier in tiers:
        tasks.append(store.tasks[tier][seen.get(tier, 0)])
        seen[tier] = seen.get(tier, 0) + 1
    return run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=run_set(*((harness_run(base / "runs", t, store), 0) for t in tasks)),
        out=base / "round",
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=lambda _s: None,
    )


def _outcome(call: Any) -> Any:  # noqa: ANN401
    try:
        return call()
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - the row asserts on what it was
        return exc


def _completed(store: StandInStore, base: Path, arm: Any, *tiers: str) -> BaselineRecord:  # noqa: ANN401
    """The round's record; the row fails on its assertion if the round stopped."""
    record = _outcome(lambda: _round(store, base, arm, *tiers))
    assert isinstance(record, BaselineRecord), f"the round stopped: {record!r}"
    return record


def _one(found: Any, what: str) -> Path:  # noqa: ANN401
    listed = list(found)
    assert len(listed) == 1, f"{what}: {listed}"
    return Path(listed[0])


def _installed(setup: RawSetup, place: Path, monkeypatch: pytest.MonkeyPatch) -> SessionConfig:
    """The session configuration the real installer writes for a session given ``setup``.

    The raw arm's own call to the installer (``raw._install``), run in this process: what the
    session's every tool is then judged by.
    """
    (place / "worktree").mkdir(exist_ok=True)
    probe = place / "probe"
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": stand_in_spawn_env()}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    with monkeypatch.context() as patched:
        patched.setattr(subprocess, "run", fake_run)
        raw._install(setup, place / "worktree", probe, None, own_temp=OWN_TEMP)
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(seen[0][1:])
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = _outcome(lambda: args.func(args))
    assert code == 0, f"the installer refused the session: {code!r}"
    written = json.loads(printed.getvalue())
    return SessionConfig.model_validate_json(Path(written["config"]).read_text())


def test_a_visible_session_reaches_neither_a_sibling_trial_nor_the_round_s_directory(
    outside_tmp: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second of two visible trials, judged by the real installer's configuration.

    Its every tool is refused a read or a listing of the first trial (its place and its
    harness's files, its score among them), of the round's work directory and of the round's
    records, and a write anywhere there; its own place it reads and writes.
    """
    store = copied(made, outside_tmp / "store")
    out = outside_tmp / "round"
    arm = StandInArm()
    judged: list[tuple[Path, Any]] = []

    def second_judged(task: Task, setup: RawSetup, work: Path, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
        record = arm(task, setup, work, **kw)
        if len(arm.calls) == 2:
            judged.append((work, _outcome(lambda: _installed(setup, work, monkeypatch))))
        return record

    _completed(store, outside_tmp, second_judged, "visible", "visible")
    assert len(judged) == 1, "the second session was not installed"
    ((place, config),) = judged
    assert isinstance(config, SessionConfig), f"the installer refused the session: {config!r}"
    cwd = str(place / "worktree")
    sibling = out / "work" / "0000-1"
    assert (sibling / HARNESS / SCORE).is_file(), "the first trial is not where it was moved"
    refused = [
        sibling / PLACE / "session" / "stdout.jsonl",
        sibling / PLACE,
        sibling / HARNESS / "raw.json",
        sibling / HARNESS / SCORE,
        sibling,
        out / "work",
        out / TRIALS,
        out,
    ]
    reached = [p for p in refused if paths.protection(str(p), cwd, config, writing=False) is None]
    assert not reached, f"a visible session may read {reached}"
    for target in (out / "work" / "planted", sibling / HARNESS / "planted", out / "planted"):
        assert paths.protection(str(target), cwd, config, writing=True) is not None, target
    for own in (place / "worktree" / "answer.json", place / "worktree" / "notes" / "a.txt"):
        assert paths.protection(str(own), cwd, config, writing=False) is None, own
        assert paths.protection(str(own), cwd, config, writing=True) is None, own


def test_every_session_works_in_the_work_root_given_its_place_alone_and_withheld_the_round(
    tmp_path: Path, made: StandInStore
) -> None:
    """Visible or protected: the place lies in the work root, carved; the round's directory held."""
    store = copied(made, tmp_path / "store")
    given: list[tuple[RawSetup, Path]] = []
    arm = StandInArm()

    def seen(task: Task, setup: RawSetup, work: Path, **kw: Any) -> dict[str, Any]:  # noqa: ANN401
        given.append((setup, work))
        return arm(task, setup, work, **kw)

    _completed(store, tmp_path, seen, "visible", "held_out", "visible")
    assert len(given) == 3
    out = os.path.realpath(tmp_path / "round")
    for setup, work in given:
        assert work.name == PLACE
        assert work.parent.parent == work_root(store.store, "control")
        assert setup.held_out_carved == str(work)
        assert out in vars(setup).get("held_out_also", ()), "the round's directory is not withheld"
        assert setup.held_out == store.held_out, "the run's own roots are given as recorded"


def test_a_finished_visible_trial_lies_beneath_the_round_and_nothing_of_it_in_the_work_root(
    tmp_path: Path, made: StandInStore
) -> None:
    """Its place and the harness's files are moved whole; its record of work is cleared."""
    store = copied(made, tmp_path / "store")
    arm = StandInArm()
    record = _completed(store, tmp_path, arm, "visible")
    assert record.counts["visible"].passed == 1
    ((_, _, work),) = arm.calls
    assert work.is_relative_to(work_root(store.store, "control")), "it ran outside the work root"
    trial = tmp_path / "round" / "work" / "0000-1"
    assert (trial / PLACE / "session" / "stdout.jsonl").is_file()
    assert (trial / HARNESS / SCORE).is_file() and (trial / HARNESS / "raw.json").is_file()
    assert not os.path.lexists(work.parent), "the trial is still in the work root"
    assert not list(work_root(store.store, "control").iterdir())
    assert not list(role_root(store.store, "control").glob(f"*{WORKING}"))


def test_a_protected_trial_is_not_moved_out_and_the_round_holds_nothing_of_it(
    tmp_path: Path, made: StandInStore
) -> None:
    store = copied(made, tmp_path / "store")
    _completed(store, tmp_path, StandInArm(), "held_out", "visible")
    work = tmp_path / "round" / "work"
    moved = sorted(p.name for p in work.iterdir()) if work.is_dir() else []
    assert moved == ["0001-1"], moved
    assert not list(work_root(store.store, "control").iterdir())


def _cross_filesystem(monkeypatch: pytest.MonkeyPatch, store: StandInStore) -> list[str]:
    """Every rename of a trial's directory out of the work root fails as across filesystems."""
    real = os.rename
    tried: list[str] = []
    root = os.path.realpath(work_root(store.store, "control"))

    def rename(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        if os.path.realpath(os.path.dirname(os.fspath(src))) == root:
            tried.append(os.fspath(src))
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
        real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rename)
    return tried


def test_a_visible_trial_on_another_filesystem_is_copied_whole_and_its_source_removed(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File by file, as written; a link copied as the link it is, never followed."""
    store = copied(made, tmp_path / "store")
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("outside the place")

    def leave(place: Path, _harness: Path) -> None:
        (place / "worktree" / "deep").mkdir(parents=True)
        (place / "worktree" / "deep" / "notes.txt").write_text("the session's own")
        (place / "worktree" / "pointer").symlink_to(decoy)

    tried = _cross_filesystem(monkeypatch, store)
    record = _outcome(lambda: _round(store, tmp_path, StandInArm(left=leave), "visible"))
    assert tried, "no move across filesystems was tried"
    assert not isinstance(record, Exception), f"the copy was refused: {record!r}"
    assert record.counts["visible"].passed == 1
    trial = tmp_path / "round" / "work" / "0000-1"
    worktree = trial / PLACE / "worktree"
    assert (worktree / "deep" / "notes.txt").read_text() == "the session's own"
    assert (worktree / "pointer").is_symlink(), "a link was copied as what it points at"
    assert os.readlink(worktree / "pointer") == str(decoy)
    assert (trial / HARNESS / SCORE).is_file()
    assert not list(work_root(store.store, "control").iterdir())
    assert not list(role_root(store.store, "control").glob(f"*{WORKING}"))


@pytest.mark.parametrize("kind", ["named pipe", "hard link"])
def test_a_move_that_fails_leaves_nothing_half_made_and_the_trial_in_the_work_root(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A file the copy refuses stops the round; the round's directory holds none of the trial."""
    store = copied(made, tmp_path / "store")
    outside = tmp_path / "outside.txt"
    outside.write_text("a file elsewhere")

    def leave(place: Path, _harness: Path) -> None:
        (place / "worktree").mkdir()
        (place / "worktree" / "first.txt").write_text("copied before the refusal")
        left = place / "worktree" / "zz-left"
        if kind == "named pipe":
            os.mkfifo(left)
        else:
            os.link(outside, left)

    _cross_filesystem(monkeypatch, store)
    outcome = _outcome(lambda: _round(store, tmp_path, StandInArm(left=leave), "visible"))
    assert isinstance(outcome, Exception), "a trial holding what the copy refuses was moved"
    assert str(tmp_path) not in f"{outcome} {getattr(outcome, 'context', {})}"
    work = tmp_path / "round" / "work"
    assert not os.path.lexists(work / "0000-1"), "a half-made trial is left beneath the round"
    left = _one(work_root(store.store, "control").iterdir(), "the trial left in the work root")
    assert (left / PLACE / "worktree" / "first.txt").is_file(), "the source was removed"
    assert (left / HARNESS / "raw.json").is_file()
    working = _one(role_root(store.store, "control").glob(f"*{WORKING}"), "its record of work")
    assert json.loads(working.read_text())["work"] == str(left)


def test_a_visible_trial_s_destination_already_there_refuses_the_move(
    tmp_path: Path, made: StandInStore
) -> None:
    """The destination is made new: what lies there is left as it was, the trial where it ran."""
    store = copied(made, tmp_path / "store")
    taken = tmp_path / "round" / "work" / "0000-1"

    def leave(_place: Path, _harness: Path) -> None:
        taken.mkdir(parents=True)

    outcome = _outcome(lambda: _round(store, tmp_path, StandInArm(left=leave), "visible"))
    assert isinstance(outcome, Exception), "a trial was moved onto a directory already there"
    assert taken.is_dir() and not list(taken.iterdir()), "what lay at the destination changed"
    left = _one(work_root(store.store, "control").iterdir(), "the trial left in the work root")
    assert (left / HARNESS / "raw.json").is_file()
    assert list(role_root(store.store, "control").glob(f"*{WORKING}"))
