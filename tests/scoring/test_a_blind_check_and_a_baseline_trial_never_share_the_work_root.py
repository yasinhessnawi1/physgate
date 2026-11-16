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

import dataclasses
import os
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
from physgate.evaluation.baseline.runner import BaselineError
from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import blind_check
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries
from physgate.evaluation.tiers.store import WORKING, role_root, work_root

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
    plan, version = _held_tier(tmp_path, monkeypatch)
    fake = FakeSession(_answers)
    monkeypatch.setattr(author_session, "run_session", fake)
    with runner.trial_place(plan.store, "control", *TRIAL) as (trial_dir, working):
        work, records = _work(plan.store), _records(plan.store)
        assert work == [trial_dir.name] and records == [working.name]
        outcome = _check(tmp_path, version, fake)
        assert isinstance(outcome, AuthoringError), f"the check was not refused: {outcome!r}"
        assert outcome.context.get("refused_because") == "session_lives", outcome.context
        assert fake.calls == [], "a check's session was started beside the trial's"
        assert _work(plan.store) == work, "the refused check made something in the work root"
        assert _records(plan.store) == records, "the refused check left a record of work"


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
