"""A blind check and a baseline trial never work in the role's work root at the same time.

Both make a directory of their own in the role's work root, each with a copy of protected tasks,
while a session works there. One made while the other's session lives is a place that session's
install never saw. So the check takes the same hold on the work root a trial takes, from before
its record of work until its work is out of the root: a check is refused while a trial's session
lives, a trial is refused while a check's session lives, and the refused one makes nothing.

The check's own session is withheld the whole store but its own work, by rule (the trial's is
withheld its root the same way), so an entry made beside its work by anything else is withheld
from it too.
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from test_no_session_s_work_is_left_outside_the_protected_root import _answers
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _held_tier,
    _setup,
    check_setup,
    check_work,
)

from physgate.evaluation.baseline import runner
from physgate.evaluation.baseline.runner import BASELINE_DIR, PLACE, BaselineError
from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import blind_check
from physgate.evaluation.tiers import store as store_module
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.store import WORKING, role_root, work_root
from physgate.orchestrator.processes import started_at

TRIAL = ("r1", "0001-1")


def _check(tmp_path: Path, version: str, fake: FakeSession) -> Any:  # noqa: ANN401
    store = tmp_path / "private" / "store"
    setup = dataclasses.replace(
        check_setup(store, _setup(tmp_path / "private")),
        held_out_canaries=root_canaries(role_root(store, "control")),
    )
    try:
        return blind_check(
            store,
            "control",
            version,
            setup,
            check_work(store),
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    except AuthoringError as exc:
        return exc


def _work(store: Path) -> list[str]:
    return sorted(os.listdir(work_root(store, "control")))


def _records(store: Path) -> list[str]:
    return sorted(n for n in os.listdir(role_root(store, "control")) if n.endswith(WORKING))


def test_a_check_is_refused_while_a_trial_s_session_lives_and_makes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trial that lives already has its record of work, which refuses the check, or its hold."""
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    with runner.trial_place(plan.store, "control", *TRIAL) as (trial_dir, working):
        work, records = _work(plan.store), _records(plan.store)
        assert work == [trial_dir.name] and records == [working.name]
        outcome = _check(tmp_path, version, fake)
        assert isinstance(outcome, AuthoringError), f"the check was not refused: {outcome!r}"
        assert outcome.context.get("refused_because") in {"work_left", "session_lives"}
        assert fake.calls == [], "a check's session was started beside the trial's"
        assert _work(plan.store) == work, "the refused check made something in the work root"
        assert _records(plan.store) == records, "the refused check left a record of work"


def test_a_trial_made_after_the_check_s_last_look_for_work_left_still_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the record of work leaves: the trial comes after the check's last look for it.

    The check looks for work left before it reads its tasks; a trial made after that, just before
    the check's own record of work, is refused to it by the hold alone.
    """
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    real = author_session.bundle
    with contextlib.ExitStack() as living:
        made: list[tuple[Path, Path]] = []

        def read_then_a_trial_came(tier: Path) -> dict[str, dict[str, Any]]:
            tasks = real(tier)
            made.append(living.enter_context(runner.trial_place(plan.store, "control", *TRIAL)))
            return tasks

        monkeypatch.setattr(author_session, "bundle", read_then_a_trial_came)
        outcome = _check(tmp_path, version, fake)
        assert made, "no trial came while the check was set up: the row shows nothing"
        assert isinstance(outcome, AuthoringError), f"the check was not refused: {outcome!r}"
        assert outcome.context.get("refused_because") == "session_lives", outcome.context
        assert fake.calls == [], "a check's session was started beside the trial's"
        ((trial_dir, working),) = made
        assert _work(plan.store) == [trial_dir.name], "the refused check made something there"
        assert _records(plan.store) == [working.name], "the refused check left a record of work"


def test_a_trial_is_refused_while_a_check_s_session_lives_and_makes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    met: dict[str, Any] = {}

    def while_the_check_lives(worktree: Path) -> None:
        _answers(worktree)
        met["work"], met["records"] = _work(plan.store), _records(plan.store)
        try:
            with runner.trial_place(plan.store, "control", *TRIAL):
                met["outcome"] = "made"
        except BaselineError as exc:
            met["outcome"] = exc
        met["work after"], met["records after"] = _work(plan.store), _records(plan.store)

    fake = FakeSession(while_the_check_lives)
    monkeypatch.setattr(author_session, "run_session", fake)
    out = _check(tmp_path, version, fake)
    assert isinstance(out, dict) and out.get("answered"), out
    outcome = met["outcome"]
    assert isinstance(outcome, BaselineError), f"a trial was made beside the check: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert met["work after"] == met["work"], "the refused trial made something in the work root"
    assert met["records after"] == met["records"], "the refused trial left a record of work"


def test_a_trial_is_made_as_before_once_the_check_has_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    out = _check(tmp_path, version, fake)
    assert isinstance(out, dict) and out.get("answered"), out
    with runner.trial_place(plan.store, "control", *TRIAL) as (trial_dir, _working):
        assert _work(plan.store) == [trial_dir.name]


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


def test_a_check_is_refused_in_words_while_a_dead_runner_s_trial_session_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner was killed: no hold and (a person removed it) no record; the session runs."""
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    sid = str(uuid.uuid4())
    process, started = _spawn(sid)
    try:
        trial = work_root(plan.store, "control") / f"{BASELINE_DIR}-dead-0001-1"
        session = trial / PLACE / "session"
        session.mkdir(mode=0o700, parents=True)
        facts = {"pid": process.pid, "started": started, "session_id": sid, "kind": "raw"}
        (session / "process.json").write_text(json.dumps(facts))
        work, records = _work(plan.store), _records(plan.store)
        outcome = _check(tmp_path, version, fake)
    finally:
        process.kill()
        process.wait()
    assert isinstance(outcome, AuthoringError), f"the check was not refused: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert str(process.pid) in str(outcome) and "still runs" in str(outcome), outcome
    assert fake.calls == [], "a check's session was started beside the living one"
    assert _work(plan.store) == work, "the refused check made something in the work root"
    assert _records(plan.store) == records, "the refused check left a record of work"


def test_a_check_on_a_volume_where_the_lock_cannot_be_taken_is_refused_with_its_own_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)

    def no_locks(_fd: int, _op: int) -> None:
        raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))

    monkeypatch.setattr(store_module.fcntl, "flock", no_locks)
    try:
        outcome = _check(tmp_path, version, fake)
    except Exception as exc:  # noqa: BLE001 - the row asserts what it was
        outcome = exc
    assert isinstance(outcome, AuthoringError), f"not the check's own refusal: {outcome!r}"
    assert outcome.context.get("refused_because") == "work_root_unlockable", outcome.context
    assert os.strerror(errno.ENOLCK) in str(outcome), outcome
    assert fake.calls == [], "a check's session was started without the hold"
    assert _records(plan.store) == [], "the refused check left a record of work"


def test_the_check_s_session_is_withheld_the_whole_store_but_its_own_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    out = _check(tmp_path, version, fake)
    assert isinstance(out, dict) and out.get("answered"), out
    (setup,) = fake.setups
    whole = getattr(setup, "withheld_whole", None)
    assert whole == (str(plan.store.resolve()),), f"the check's store is withheld by list: {whole}"
