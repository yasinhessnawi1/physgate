"""A raw trial is run once more only as a new round of its one entry, held to the earlier round.

A round that stopped on an entry for a cause (a pair that differs, other pins, an error, a move
that failed), or recorded its trial excluded for a reason its records give for not trusting the
answer, or ran it under a harness run that was itself run once more, lets that entry be run once
more: as a new round of the one entry, which names the earlier round (``rerun_of``), decided from
the earlier round's ledger and its trial line's kind before any score is read. The earlier round
is kept as it is. A trial with a raw record is never given to the raw arm again otherwise, an
exposure is never run again, and a once-more is never run a third time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    RESET_EPOCH,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    harness_run_spending,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.cli import replaced_run
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import (
    BaselineError,
    RoundWaits,
    RunSet,
    raw_rerun_cause,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _round(
    made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any
) -> BaselineRecord | Exception:  # noqa: ANN401
    try:
        return run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=lambda _t, _a: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
            **how,
        )
    except Exception as exc:  # noqa: BLE001 - asserted by the caller
        return exc


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _why(outcome: BaselineRecord | Exception) -> str | None:
    assert isinstance(outcome, BaselineError), f"not refused: {outcome!r}"
    assert outcome.context["refused_because"] == "rerun_refused"
    return outcome.context.get("why")


def test_an_entry_its_round_stopped_on_for_a_cause_is_run_once_more_as_a_round_of_its_own(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    first = tmp_path / "first"
    stopped = _round(store, runs, first, StandInArm(answered={1: "claude-other"}))
    assert (
        isinstance(stopped, BaselineError) and stopped.context["refused_because"] == "pair_differs"
    )
    kept = _snapshot(first)
    again = _round(store, runs, tmp_path / "again", StandInArm(), rerun_of=first)
    assert isinstance(again, BaselineRecord), again
    round_id = json.loads((first / "ledger.jsonl").read_text().splitlines()[0])["round"]
    assert again.rerun_of == {
        "round": round_id,
        "out": str(first),
        "entry": 0,
        "session": 1,
        "because": "stopped:pair",
    }
    assert _snapshot(first) == kept, "the earlier round is kept as it is"
    # A once-more is never run a third time.
    third = _round(store, runs, tmp_path / "third", StandInArm(), rerun_of=tmp_path / "again")
    assert _why(third) == "second_rerun"


def test_a_trial_excluded_for_a_reason_not_to_trust_it_is_run_once_more(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    first = tmp_path / "first"
    record = _round(store, runs, first, StandInArm(end_refused={1}))
    assert isinstance(record, BaselineRecord) and record.counts["visible"].excluded == 1
    again = _round(store, runs, tmp_path / "again", StandInArm(), rerun_of=first)
    assert isinstance(again, BaselineRecord), again
    assert again.rerun_of is not None
    assert again.rerun_of["because"] == "excluded:sentinel_after_stop"


def test_an_exposure_and_a_trial_with_a_raw_record_are_never_run_again(
    tmp_path: Path, store: StandInStore, made: StandInStore
) -> None:
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["held_out"][0], store), 0))
    seen = tmp_path / "seen"
    assert isinstance(_round(store, runs, seen, StandInArm(seen={1})), BaselineRecord)
    # The register reads the raw record's canary as an exposure of the version: every later
    # round on it is refused before any link is read.
    exposed = _round(store, runs, tmp_path / "a", StandInArm(), rerun_of=seen)
    assert isinstance(exposed, BaselineError)
    assert exposed.context["refused_because"] == "version_exposed"
    store = copied(made, tmp_path / "clean")
    runs = run_set((harness_run(tmp_path / "runs2", store.tasks["held_out"][0], store), 0))
    counted = tmp_path / "counted"
    assert isinstance(_round(store, runs, counted, StandInArm()), BaselineRecord)
    assert _why(_round(store, runs, tmp_path / "b", StandInArm(), rerun_of=counted)) == "recorded"


def test_an_earlier_round_that_has_not_ended_with_the_entry_is_resumed_not_run_again(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    first = tmp_path / "first"
    assert isinstance(_round(store, runs, first, StandInArm(limited={1: RESET_EPOCH})), RoundWaits)
    again = _round(store, runs, tmp_path / "again", StandInArm(), rerun_of=first)
    assert _why(again) == "earlier_not_ended"


def test_a_raw_pair_that_ran_under_a_harness_run_since_run_once_more_runs_under_the_new_cap(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    superseded = harness_run(tmp_path / "runs", task, store)
    first = tmp_path / "first"
    assert isinstance(_round(store, run_set((superseded, 0)), first, StandInArm()), BaselineRecord)
    rerun = harness_run_spending(tmp_path / "runs", task, store, 2500)
    arm = StandInArm()
    # Without the sheet's word that this run superseded the earlier one, nothing links them.
    alone = _round(store, run_set((rerun, 0)), tmp_path / "alone", StandInArm(), rerun_of=first)
    assert _why(alone) == "not_this_entry"
    again = _round(
        store,
        run_set((rerun, 0)),
        tmp_path / "again",
        arm,
        rerun_of=first,
        replaces=str(superseded),
    )
    assert isinstance(again, BaselineRecord), again
    assert again.rerun_of is not None and again.rerun_of["because"] == "harness_rerun"
    assert [cap for _, cap, _ in arm.calls] == [2500]


def test_a_once_more_is_a_round_of_one_entry(tmp_path: Path, store: StandInStore) -> None:
    one = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    two = harness_run(tmp_path / "runs", store.tasks["visible"][1], store)
    first = tmp_path / "first"
    assert isinstance(
        _round(store, run_set((one, 0)), first, StandInArm(end_refused={1})), BaselineRecord
    )
    both = _round(store, run_set((one, 0), (two, 0)), tmp_path / "b", StandInArm(), rerun_of=first)
    assert _why(both) == "not_one_entry"


@pytest.mark.parametrize(
    ("reason", "cause"),
    [
        (
            "end: 'watch_failed' is not an end the raw arm writes for a session it takes",
            "untrusted",
        ),
        ("sentinel_after_stop: the end check refused the session", "untrusted"),
        ("stream: a stream written after its result", "untrusted"),
        ("score: the verdict is not a bool", "untrusted"),
        ("canary: the task's own canary showed in the session's stream", "exposure"),
        ("held_out_seen: the record does not say whether a held-out canary showed", "exposure"),
        ("something no one enumerated", "unknown"),
    ],
)
def test_a_raw_exclusion_is_classed_by_the_field_its_reason_begins_with(
    reason: str, cause: str
) -> None:
    assert raw_rerun_cause(reason) == cause


def test_the_command_reads_the_run_a_re_run_harness_trial_superseded_from_its_sheet(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "0004.runs.json"
    runs.write_text(json.dumps({"format": 1, "trials": [{"run_dir": "/r/0004-2", "trial": 1}]}))
    assert replaced_run(runs) is None
    sheet = {"format": 1, "index": 4, "rerun_of": {"attempt": 1, "run_dir": "/r/0004-1"}}
    (tmp_path / "0004.trial.json").write_text(json.dumps(sheet))
    assert replaced_run(runs) == "/r/0004-1"
    (tmp_path / "0004.trial.json").write_text(json.dumps({**sheet, "rerun_of": None}))
    assert replaced_run(runs) is None
