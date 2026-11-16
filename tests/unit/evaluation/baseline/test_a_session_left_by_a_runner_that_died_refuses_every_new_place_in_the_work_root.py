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

import contextlib
import errno
import json
import os
import signal
import subprocess
import sys
import threading
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


def test_facts_whose_pid_was_reused_by_a_later_process_refuse_nothing(
    left_trial: tuple[StandInStore, Left],
) -> None:
    """The pid runs now, but with another start time: not that session, nor its group."""
    store, left = left_trial
    facts_file = left.entry / PLACE / "session" / "process.json"
    facts = json.loads(facts_file.read_text())
    facts["started"] = "Mon Jan  1 00:00:00 2001"
    facts_file.write_text(json.dumps(facts))
    assert _new_trial(store) == "made", "a reused pid was taken for the session"


#: A stand-in session that starts one child, in the session's group or in a group of its own
#: (as the Bash tool runs a command), writes the child's pid, and waits.
WITH_A_CHILD = """
import os, subprocess, sys, time
own_group = sys.argv[2] == "own"
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
    process_group=0 if own_group else None,
)
with open(sys.argv[1], "w") as out:
    out.write(str(child.pid))
time.sleep(120)
"""


@pytest.mark.parametrize("group", ["the session's", "own"])
def test_a_session_whose_leader_has_ended_but_whose_child_runs_still_refuses(
    tmp_path: Path, made: StandInStore, group: str
) -> None:
    store = copied(made, tmp_path / "store")
    sid = str(uuid.uuid4())
    pids = tmp_path / "child"
    leader = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-c", WITH_A_CHILD, str(pids), group, "--session-id", sid],
        start_new_session=True,
    )
    child = 0
    try:
        started = None
        for _ in range(400):
            started = started or started_at(leader.pid)
            if started and pids.is_file() and pids.read_text().strip():
                child = int(pids.read_text())
                break
            time.sleep(0.05)
        assert started and child, "the stand-in session did not start its child"
        entry = work_root(store.store, "control") / f"{BASELINE_DIR}-dead-0001-1"
        _leave(entry, entry / PLACE / "session", leader, started, sid)
        leader.kill()
        leader.wait()
        assert started_at(child) is not None, "the child did not outlive its leader"
        outcome = _new_trial(store)
    finally:
        if child:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
        leader.kill()
        leader.wait()
    assert isinstance(outcome, BaselineError), f"made beside a living child: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert "still runs" in str(outcome), outcome


def test_a_session_directory_without_its_process_facts_refuses_in_words(
    left_trial: tuple[StandInStore, Left],
) -> None:
    """The facts removed: whether the session runs cannot be told, so nothing is made."""
    store, left = left_trial
    (left.entry / PLACE / "session" / "process.json").unlink()
    work = _work(store)
    outcome = _new_trial(store)
    assert isinstance(outcome, BaselineError), f"made with no facts to judge by: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert "cannot be told" in str(outcome), outcome
    assert _work(store) == work, "the refusal made something in the work root"


@pytest.mark.parametrize("planted", ["fifo", "link", "directory"])
def test_something_else_at_the_facts_name_refuses_at_once(
    left_trial: tuple[StandInStore, Left], planted: str
) -> None:
    """A named pipe there would hang an open that waits on it: the row fails on a timeout."""
    store, left = left_trial
    at = left.entry / PLACE / "session" / "process.json"
    facts = at.read_text()
    at.unlink()
    if planted == "fifo":
        os.mkfifo(at)
    elif planted == "link":
        (at.parent / "elsewhere.json").write_text(facts)
        at.symlink_to(at.parent / "elsewhere.json")
    else:
        at.mkdir()
    outcome: list[object] = []
    asking = threading.Thread(target=lambda: outcome.append(_new_trial(store)), daemon=True)
    asking.start()
    asking.join(timeout=20)
    if asking.is_alive() and planted == "fifo":
        # Let the hung open go, so the thread ends; the row has failed already.
        with contextlib.suppress(OSError):
            os.close(os.open(at, os.O_WRONLY | os.O_NONBLOCK))
    assert not asking.is_alive(), "the facts' open hung on what was planted there"
    (found,) = outcome
    assert isinstance(found, BaselineError), f"made beside an unjudged session: {found!r}"
    assert found.context.get("refused_because") == "session_lives", found.context
    assert "cannot be told" in str(found), found


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
