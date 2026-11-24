"""A raw session's own error message stops no round; a real model other than the pin still does.

The pinned client writes messages of its own into a session's stream under the model name
``<synthetic>``: an API error's notice, the usage limit's. A raw session that met one and was then
answered by the pinned model differs from the harness arm in nothing, and its trial is counted as
any other. A real model other than the pinned one still stops the round on ``answered_by``; a
session only the client wrote to was answered by no model and is never a counted trial.

Every row runs on the stand-in store and harness runs the round's other rows use; the raw arm is
the stand-in that leaves what the real one leaves. No session is started and no model is called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import TRIALS, BaselineError, RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.task import Task

ENDED_ON_AN_API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
NONE_SPENT = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}


def _notice(text: str, mid: str, **outer: Any) -> dict[str, Any]:  # noqa: ANN401
    """A message the client wrote itself, in the shape the pinned binary writes one."""
    message = {
        "id": mid,
        "model": "<synthetic>",
        "role": "assistant",
        "type": "message",
        "content": [{"type": "text", "text": text}],
        "usage": NONE_SPENT,
    }
    return {"type": "assistant", "message": message, "parent_tool_use_id": None, **outer}


API_ERROR = [
    _notice(
        "API Error: 529 Overloaded. The service is busy.",
        "notice-1",
        error="unknown",
        is_api_error_message=True,
    )
]
USAGE_LIMIT = [
    {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "rejected",
            "resetsAt": 1794572400,
            "rateLimitType": "five_hour",
        },
    },
    _notice(
        "You've hit your session limit · resets 1:20pm (Europe/Oslo)",
        "notice-2",
        error="rate_limit",
    ),
]
NOTICES = pytest.mark.parametrize(
    "notice", [API_ERROR, USAGE_LIMIT], ids=["an API error", "a usage limit"]
)


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


def _round(
    made: StandInStore, runs: RunSet, out: Path, arm: StandInArm
) -> BaselineRecord | Exception:
    """The round's record, or what stopped it: a row asserts on either, so a stop is a failure."""
    try:
        return _run(made, runs, out, arm)
    except Exception as exc:  # noqa: BLE001 - the row asserts on what it was
        return exc


def _run(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm) -> BaselineRecord:
    slept: list[float] = []
    return run_baseline(
        store=made.store,
        role="control",
        version=made.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=slept.append,
        development=False,
    )


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    """A store of this row's own: the module's version, copied, so a round's records stay here."""
    import shutil

    copy = tmp_path / "store"
    shutil.copytree(made.store, copy, symlinks=True)
    old, new = str(made.store), str(copy)
    return StandInStore(
        copy,
        made.version,
        made.tasks,
        made.canaries,
        tuple(h.replace(old, new) for h in made.held_out),
    )


@NOTICES
def test_a_trial_whose_session_met_a_notice_and_was_then_answered_by_the_pin_is_counted(
    tmp_path: Path, store: StandInStore, notice: list[dict[str, Any]]
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm(notices={1: notice})
    record = _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert isinstance(record, BaselineRecord), f"the client's notice stopped the round: {record}"
    assert len(arm.calls) == 1
    assert record.counts["visible"].passed == 1


def test_a_trial_the_machine_ended_twice_after_its_model_answered_is_unscored(
    tmp_path: Path, store: StandInStore
) -> None:
    """The model answered, then the client noted the API error it ended on: the machine's end.

    An API error's notice only: how a raw session that met the account's usage limit is to wait
    is the round's own rule, not this one's.
    """
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    arm = StandInArm(
        ended={1: ENDED_ON_AN_API_ERROR, 2: ENDED_ON_AN_API_ERROR},
        notices={1: API_ERROR, 2: API_ERROR},
    )
    record = _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert isinstance(record, BaselineRecord), f"the client's notice stopped the round: {record}"
    assert len(arm.calls) == 2
    counts = record.counts["held_out"]
    assert (counts.unscored, counts.passed, counts.failed) == (1, 0, 0)


@NOTICES
def test_a_real_model_other_than_the_pin_after_a_notice_still_stops_the_round(
    tmp_path: Path, store: StandInStore, notice: list[dict[str, Any]]
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm(notices={1: notice}, answered={1: "claude-sonnet-5"})
    stopped = _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert isinstance(stopped, BaselineError), stopped
    assert str(stopped).endswith("more than the harness: answered_by"), stopped


@NOTICES
def test_a_session_only_the_client_wrote_to_is_no_counted_trial(
    tmp_path: Path, store: StandInStore, notice: list[dict[str, Any]]
) -> None:
    """Answered by no model, twice: run once more as the machine's end, then never counted."""
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm(
        ended={1: ENDED_ON_AN_API_ERROR, 2: ENDED_ON_AN_API_ERROR},
        notices={1: notice, 2: notice},
        unanswered={1, 2},
    )
    out = tmp_path / "round"
    stopped = _round(store, run_set((run, 0)), out, arm)
    assert isinstance(stopped, BaselineError), stopped
    assert str(stopped).endswith("more than the harness: answered_by"), stopped
    # The first attempt was the machine's end and was run once more; the second is not counted.
    assert len(arm.calls) == 2
    trials = out / TRIALS
    assert not trials.exists() or trials.read_text() == "", "a trial no model answered is counted"
