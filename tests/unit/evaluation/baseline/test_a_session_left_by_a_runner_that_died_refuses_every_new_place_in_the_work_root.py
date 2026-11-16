"""A session left running in the work root by a runner that died refuses every new place there.

The hold on the work root is a lock the kernel drops when the runner's process ends, so a runner
killed outright leaves its trial's session running with nothing held. That session was withheld
the work root's entries by rule, but an entry made beside it now is still one made while it
lives. So, before any trial is made, at a round's start and at each trial, the runner reads the
process facts each session wrote beside its place in the work root (its pid, start time and
session id) and refuses, in words, while any of those sessions still runs: the same session,
told apart from a reused pid by its start time and its command line. A session that has ended
refuses nothing. And a volume on which the lock itself cannot be taken refuses with the round's
own reason, never a bare ``OSError``; nothing is made either way.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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

from physgate.evaluation.baseline import runner
from physgate.evaluation.baseline.runner import BASELINE_DIR, PLACE, BaselineError, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers import store as store_module
from physgate.evaluation.tiers.store import WORKING, role_root, work_root
from physgate.evaluation.tiers.task import Task
from physgate.orchestrator.processes import started_at

#: A new trial's round and name, distinct from the one the dead runner left.
NEW = ("new", "0003-1")


@dataclass
class Left:
    """A session a dead runner left: its process, and the directory it worked in."""

    process: subprocess.Popen[bytes]
    session_id: str
    entry: Path


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


def _score(_task: Task, _answer: Path) -> dict[str, Any]:
    return dict(SCORED)


def _spawn(session_id: str) -> tuple[subprocess.Popen[bytes], str]:
    """A process standing in for a session: its command line carries its session id."""
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-c", "import time; time.sleep(120)", "--session-id", session_id],
        start_new_session=True,
    )
    for _ in range(200):
        started = started_at(process.pid)
        if started is not None:
            return process, started
        time.sleep(0.05)
    process.kill()
    process.wait()
    msg = "the stand-in session's start time could not be read"
    raise AssertionError(msg)


def _leave(
    entry: Path, session: Path, process: subprocess.Popen[bytes], started: str, sid: str
) -> None:
    """What the raw arm writes beside a session it spawned, as a killed runner leaves it."""
    session.mkdir(mode=0o700, parents=True)
    facts = {"pid": process.pid, "started": started, "session_id": sid, "kind": "raw"}
    (session / "process.json").write_text(json.dumps(facts))
    assert entry.is_dir()


@pytest.fixture
def left_trial(tmp_path: Path, made: StandInStore) -> Iterator[tuple[StandInStore, Left]]:
    """A trial's session in the work root, still running, its runner gone: no hold, no record."""
    store = copied(made, tmp_path / "store")
    sid = str(uuid.uuid4())
    process, started = _spawn(sid)
    entry = work_root(store.store, "control") / f"{BASELINE_DIR}-dead-0001-1"
    try:
        _leave(entry, entry / PLACE / "session", process, started, sid)
        yield store, Left(process, sid, entry)
    finally:
        process.kill()
        process.wait()


@pytest.fixture
def left_check(tmp_path: Path, made: StandInStore) -> Iterator[tuple[StandInStore, Left]]:
    """A blind check's session in the work root, still running, its runner gone."""
    store = copied(made, tmp_path / "store")
    sid = str(uuid.uuid4())
    process, started = _spawn(sid)
    entry = work_root(store.store, "control") / "check-dead"
    try:
        _leave(entry, entry / "session", process, started, sid)
        yield store, Left(process, sid, entry)
    finally:
        process.kill()
        process.wait()


def _work(store: StandInStore) -> list[str]:
    return sorted(os.listdir(work_root(store.store, "control")))


def _records(store: StandInStore) -> list[str]:
    return sorted(n for n in os.listdir(role_root(store.store, "control")) if n.endswith(WORKING))


def _new_trial(store: StandInStore) -> object:
    """The outcome of asking for a new trial's place: what was raised, or "made"."""
    try:
        with runner.trial_place(store.store, "control", *NEW):
            return "made"
    except Exception as exc:  # noqa: BLE001 - the row asserts what it was
        return exc


def _round(store: StandInStore, base: Path, arm: StandInArm) -> object:
    task = store.tasks["visible"][0]
    try:
        return run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=run_set((harness_run(base / "runs", task, store), 0)),
            out=base / "round",
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
        )
    except Exception as exc:  # noqa: BLE001 - the row asserts what it was
        return exc


@pytest.mark.parametrize("kind", ["trial", "check"])
def test_a_new_trial_is_refused_in_words_while_a_dead_runner_s_session_still_runs(
    kind: str, request: pytest.FixtureRequest
) -> None:
    store, left = request.getfixturevalue(f"left_{kind}")
    work, records = _work(store), _records(store)
    outcome = _new_trial(store)
    assert isinstance(outcome, BaselineError), (
        f"a trial was made beside a living session: {outcome!r}"
    )
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert str(left.process.pid) in str(outcome), (
        f"the refusal does not name the session: {outcome}"
    )
    assert "still runs" in str(outcome), outcome
    assert _work(store) == work, "the refusal made something in the work root"
    assert _records(store) == records, "the refusal left a record of work"


def test_a_round_is_refused_at_its_start_while_a_dead_runner_s_session_still_runs(
    tmp_path: Path, left_trial: tuple[StandInStore, Left]
) -> None:
    store, left = left_trial
    arm = StandInArm()
    outcome = _round(store, tmp_path, arm)
    assert isinstance(outcome, BaselineError), f"the round was not refused: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert str(left.process.pid) in str(outcome), outcome
    assert arm.calls == [], "a session was started beside the living one"
    assert not (tmp_path / "round").exists(), "the refused round made its directory"
    assert _work(store) == [left.entry.name], "the refused round made something in the work root"


def test_a_session_that_has_ended_refuses_nothing(left_trial: tuple[StandInStore, Left]) -> None:
    store, left = left_trial
    left.process.kill()
    left.process.wait()
    assert _new_trial(store) == "made", "an ended session's facts refused a new trial"


def test_facts_that_name_another_process_refuse_nothing(
    left_trial: tuple[StandInStore, Left],
) -> None:
    """A pid that runs now but is not that session (its command line names another id)."""
    store, left = left_trial
    facts_file = left.entry / PLACE / "session" / "process.json"
    facts = json.loads(facts_file.read_text())
    facts["session_id"] = str(uuid.uuid4())
    facts_file.write_text(json.dumps(facts))
    assert _new_trial(store) == "made", "a process that is not the session refused a new trial"


def test_a_volume_on_which_the_lock_cannot_be_taken_refuses_with_the_round_s_reason(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = copied(made, tmp_path / "store")
    work_root(store.store, "control").mkdir(parents=True, exist_ok=True)
    work, records = _work(store), _records(store)

    def no_locks(_fd: int, _op: int) -> None:
        raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))

    monkeypatch.setattr(store_module.fcntl, "flock", no_locks)
    outcome = _new_trial(store)
    assert isinstance(outcome, BaselineError), f"not the round's own refusal: {outcome!r}"
    assert outcome.context.get("refused_because") == "work_root_unlockable", outcome.context
    assert os.strerror(errno.ENOLCK) in str(outcome), outcome
    assert _work(store) == work, "the refusal made something in the work root"
    assert _records(store) == records, "the refusal left a record of work"
