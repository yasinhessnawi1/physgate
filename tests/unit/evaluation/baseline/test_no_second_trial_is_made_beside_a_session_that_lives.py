"""No second trial is made in the work root while a session of the round lives there.

A trial's session is withheld the work root's entries beside its own place as they stand when it
is installed: a list, so an entry made there after the install is on no session's list. Trials run
one at a time, so the runner makes a trial's directory and its record of work only while it holds
the work root, and holds it until that trial's session has ended and the trial has been moved
out. A second trial's creation while the work root is held is refused, and nothing is made: no
directory, no record of work. Once the earlier session has ended the next trial is made as before.
"""

from __future__ import annotations

import contextlib
import os
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
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import BaselineError, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import WORKING, role_root, work_root
from physgate.evaluation.tiers.task import Task

#: A second trial's round and name, distinct from every trial the round makes itself.
SECOND = ("second", "0007-1")


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


def _score(_task: Task, _answer: Path) -> dict[str, Any]:
    return dict(SCORED)


def _round(store: StandInStore, base: Path, arm: Any, *tiers: str) -> BaselineRecord:  # noqa: ANN401
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


def _creation() -> Any:  # noqa: ANN401
    create = getattr(runner, "trial_place", None)
    assert create is not None, "the runner has no creation of a trial's place of its own"
    return create


def _records(store: StandInStore) -> list[str]:
    return sorted(n for n in os.listdir(role_root(store.store, "control")) if n.endswith(WORKING))


def _work(store: StandInStore) -> list[str]:
    return sorted(os.listdir(work_root(store.store, "control")))


@pytest.mark.parametrize("tier", ["visible", "held_out"])
def test_a_trial_s_creation_while_a_session_of_the_round_lives_is_refused_and_makes_nothing(
    tmp_path: Path, made: StandInStore, tier: str
) -> None:
    store = copied(made, tmp_path / "store")
    met: dict[str, Any] = {}

    def second(_place: Path, _harness: Path) -> None:
        # The session lives: its place is in the work root, and the arm has not returned.
        met["work"], met["records"] = _work(store), _records(store)
        create = getattr(runner, "trial_place", None)
        if create is None:
            met["outcome"] = None
            return
        try:
            with create(store.store, "control", *SECOND):
                met["outcome"] = "made"
        except BaselineError as exc:
            met["outcome"] = exc
        met["work after"], met["records after"] = _work(store), _records(store)

    _round(store, tmp_path, StandInArm(left=second), tier)
    _creation()
    outcome = met["outcome"]
    assert isinstance(outcome, BaselineError), f"a second trial was not refused: {outcome!r}"
    assert outcome.context.get("refused_because") == "session_lives", outcome.context
    assert "lives" in str(outcome), outcome
    assert len(met["work"]) == 1, "the living session's trial is not the one entry there"
    assert met["work after"] == met["work"], "the refusal made something in the work root"
    assert met["records after"] == met["records"], "the refusal left a record of work"


def test_the_round_s_own_creation_is_refused_while_another_trial_s_session_lives(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another trial is made in the work root after this round was planned, and its session lives."""
    store = copied(made, tmp_path / "store")
    create = _creation()
    arm = StandInArm()
    held: list[tuple[Path, Path]] = []
    real = runner.plan
    with contextlib.ExitStack() as living:

        def planned_then_another(*a: Any, **k: Any) -> Any:  # noqa: ANN401
            found = real(*a, **k)
            held.append(living.enter_context(create(store.store, "control", *SECOND)))
            return found

        monkeypatch.setattr(runner, "plan", planned_then_another)
        with pytest.raises(BaselineError) as raised:
            _round(store, tmp_path, arm, "visible")
        ((trial_dir, working),) = held
        assert _work(store) == [trial_dir.name], "the refused round made something there"
        assert _records(store) == [working.name], "the refused round left a record of work"
    assert raised.value.context.get("refused_because") == "session_lives", raised.value.context
    assert arm.calls == [], "a session was started beside the living one"


def test_a_trial_is_made_as_before_once_the_earlier_session_has_ended(
    tmp_path: Path, made: StandInStore
) -> None:
    store = copied(made, tmp_path / "store")
    create = _creation()
    arm = StandInArm()
    record = _round(store, tmp_path, arm, "visible", "held_out", "visible")
    assert len(arm.calls) == 3, "each trial is made once the session before it has ended"
    assert record.counts["visible"].trials == 2
    assert _work(store) == [] and _records(store) == []
    with create(store.store, "control", *SECOND) as (trial_dir, working):
        assert trial_dir.is_dir() and trial_dir.parent == work_root(store.store, "control")
        assert working.is_file() and working.parent == role_root(store.store, "control")
        assert _work(store) == [trial_dir.name]
