"""A harness trial has one counted raw record, whatever rounds a person starts and names.

The store itself knows which harness trial each baseline round took on: before its first session
a round writes a line for each of its pairs beneath the withheld root, by the harness trial (the
harness round's place that placed the entry's run, whichever draw of it, or the run itself where
no round did), never by the round's name or a run set's file name. A round is refused before it
makes anything for a pair another round holds: one that recorded it, stopped on it, started a
session of it that is not settled, or has it still to run, naming that round. The one second
round a pair may have is the once-more of its earlier round (``--rerun-of``), at most one: the
earlier round's ledger is told which round runs its entry in its place. A pair counted in two
rounds is refused by the audit too.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
    RESET_EPOCH,
    SCORED,
    RoundPlace,
    StandInArm,
    StandInStore,
    copied,
    harness_round_of,
    harness_run,
    harness_run_spending,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.audit import AuditError, audit_raw
from physgate.evaluation.baseline.cli import refused_line
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import (
    BaselineError,
    RoundWaits,
    RunSet,
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


def _id(out: Path) -> str:
    return str(json.loads((out / "ledger.jsonl").read_text().splitlines()[0])["round"])


def _refused(outcome: BaselineRecord | Exception, because: str, earlier: Path | None) -> None:
    assert isinstance(outcome, BaselineError), f"not refused: {outcome!r}"
    assert outcome.context["refused_because"] == because, outcome.context
    if earlier is not None:
        assert outcome.context["earlier_round"] == _id(earlier)
        assert _id(earlier) in str(outcome)


def _audit(store: StandInStore, runs: RunSet, out: Path) -> Any:  # noqa: ANN401
    return audit_raw(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        prices=load_price_sheet(PRICES),
        score=lambda _t, _a: dict(SCORED),
    )


def _placed(store: StandInStore, root: Path, n: int = 1) -> list[Path]:
    """``n`` harness trials of a stand-in harness round, each kept on its first draw."""
    tasks = store.tasks["visible"]
    runs = [harness_run_spending(root, tasks[i], store, 1500 + i) for i in range(n)]
    harness_round_of(store, [RoundPlace(run, 0, tasks[i]) for i, run in enumerate(runs)])
    return runs


def test_the_same_harness_trial_given_to_a_second_round_is_refused_naming_the_first(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _placed(store, tmp_path / "runs")
    first = tmp_path / "first"
    assert isinstance(_round(store, run_set((run, 0)), first, StandInArm()), BaselineRecord)
    # The same one-entry set, and the same trial in another set file: refused before anything.
    arm = StandInArm()
    again = _round(store, run_set((run, 0)), tmp_path / "second", arm)
    _refused(again, "pair_recorded", first)
    assert arm.calls == [] and not (tmp_path / "second").exists()
    # And a run no harness round placed, by its directory and trial.
    by_hand = harness_run(tmp_path / "hand", store.tasks["visible"][3], store)
    one = tmp_path / "one"
    assert isinstance(_round(store, run_set((by_hand, 0)), one, StandInArm()), BaselineRecord)
    _refused(
        _round(store, run_set((by_hand, 0)), tmp_path / "two", StandInArm()), "pair_recorded", one
    )


def test_a_run_set_listing_one_harness_trial_twice_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    run = harness_run(tmp_path / "runs", task, store)
    arm = StandInArm()
    twice = _round(store, run_set((run, 0), (run, 0)), tmp_path / "twice", arm)
    _refused(twice, "pair_listed_twice", None)
    assert twice.context["entry"] == "1"  # type: ignore[union-attr]
    # Two draws of one harness trial: the draw the round excluded and the one it kept.
    superseded = harness_run_spending(tmp_path / "runs", task, store, 1200)
    kept = harness_run_spending(tmp_path / "runs", task, store, 1300)
    harness_round_of(store, [RoundPlace(kept, 0, task, earlier=(superseded,))])
    both = _round(store, run_set((superseded, 0), (kept, 0)), tmp_path / "both", arm)
    _refused(both, "pair_listed_twice", None)
    assert arm.calls == []


def test_an_entry_naming_another_trial_number_than_its_round_s_place_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _placed(store, tmp_path / "runs")
    refused = _round(store, run_set((run, 1)), tmp_path / "round", StandInArm())
    _refused(refused, "not_the_place_s_trial", None)


def test_a_pair_whose_session_started_and_is_not_settled_is_resumed_never_started_again(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _placed(store, tmp_path / "runs")
    first = tmp_path / "first"
    assert isinstance(
        _round(store, run_set((run, 0)), first, StandInArm(limited={1: RESET_EPOCH})), RoundWaits
    )
    _refused(
        _round(store, run_set((run, 0)), tmp_path / "second", StandInArm()), "pair_started", first
    )


def test_a_pair_an_earlier_round_has_still_to_run_is_that_round_s(
    tmp_path: Path, store: StandInStore
) -> None:
    one, two = _placed(store, tmp_path / "runs", 2)
    first = tmp_path / "first"
    waits = _round(store, run_set((one, 0), (two, 0)), first, StandInArm(limited={1: RESET_EPOCH}))
    assert isinstance(waits, RoundWaits)
    second = _round(store, run_set((two, 0)), tmp_path / "second", StandInArm())
    _refused(second, "pair_claimed", first)


def test_a_pair_a_round_stopped_before_reaching_is_free_for_a_round_of_its_own(
    tmp_path: Path, store: StandInStore
) -> None:
    one, two = _placed(store, tmp_path / "runs", 2)
    stopped = tmp_path / "stopped"
    outcome = _round(store, run_set((one, 0), (two, 0)), stopped, StandInArm(answered={1: "x"}))
    assert isinstance(outcome, BaselineError)
    assert outcome.context["refused_because"] == "pair_differs"
    alone = _round(store, run_set((two, 0)), tmp_path / "alone", StandInArm())
    assert isinstance(alone, BaselineRecord), alone


def test_a_pair_whose_earlier_round_cannot_be_read_as_its_own_waits_for_a_person(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _placed(store, tmp_path / "runs")
    first = tmp_path / "first"
    assert isinstance(_round(store, run_set((run, 0)), first, StandInArm()), BaselineRecord)
    held = _id(first)
    shutil.rmtree(first)
    refused = _round(store, run_set((run, 0)), tmp_path / "second", StandInArm())
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "pair_unread"
    assert refused.context["earlier_round"] == held


def test_after_its_one_once_more_a_pair_is_never_given_to_the_raw_arm_again(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _placed(store, tmp_path / "runs")
    runs = run_set((run, 0))
    first = tmp_path / "first"
    record = _round(store, runs, first, StandInArm(end_refused={1}))
    assert isinstance(record, BaselineRecord) and record.counts["visible"].excluded == 1
    # A plain round of an excluded record is refused: only the once-more runs it again.
    _refused(_round(store, runs, tmp_path / "plain", StandInArm()), "pair_recorded", first)
    once = tmp_path / "once"
    assert isinstance(_round(store, runs, once, StandInArm(), rerun_of=first), BaselineRecord)
    _refused(_round(store, runs, tmp_path / "third", StandInArm()), "pair_recorded", once)
    twice = _round(store, runs, tmp_path / "twice", StandInArm(), rerun_of=first)
    assert isinstance(twice, BaselineError)
    assert (twice.context["why"], twice.context["earlier_round"]) == ("rerun_twice", _id(once))
    again = _round(store, runs, tmp_path / "again", StandInArm(), rerun_of=once)
    assert isinstance(again, BaselineError) and again.context["why"] == "second_rerun"
    # Each round audits clean: the earlier record is superseded, the once-more's is the pair's.
    assert _audit(store, runs, first) == []
    assert _audit(store, runs, once) == []


def test_a_round_begun_before_it_wrote_its_pairs_writes_them_at_its_next_start(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.evaluation.baseline.runner as runner

    (run,) = _placed(store, tmp_path / "runs")
    first = tmp_path / "first"
    with monkeypatch.context() as patched:
        patched.setattr(runner, "take_pairs", lambda *_a, **_k: None)
        waits = _round(store, run_set((run, 0)), first, StandInArm(limited={1: RESET_EPOCH}))
    assert isinstance(waits, RoundWaits)
    # Nothing holds the pair yet: as for a round that ended before the register was written.
    pairs = store.store / "control" / "withheld" / "baseline" / "pairs"
    assert not pairs.exists()
    resumed = _round(
        store, run_set((run, 0)), first, StandInArm(limited={1: RESET_EPOCH}), resume=True
    )
    assert isinstance(resumed, RoundWaits)
    assert len(list(pairs.iterdir())) == 1
    _refused(
        _round(store, run_set((run, 0)), tmp_path / "second", StandInArm()), "pair_started", first
    )


def test_were_two_rounds_to_count_one_pair_the_audit_of_either_refuses(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.evaluation.baseline.runner as runner

    (run,) = _placed(store, tmp_path / "runs")
    runs = run_set((run, 0))
    first, second = tmp_path / "first", tmp_path / "second"
    assert isinstance(_round(store, runs, first, StandInArm()), BaselineRecord)
    with monkeypatch.context() as patched:
        patched.setattr(runner, "pairs_refusal", lambda *_a, **_k: None)
        assert isinstance(_round(store, runs, second, StandInArm()), BaselineRecord)
    for out, other in ((first, second), (second, first)):
        with pytest.raises(AuditError) as refused:
            _audit(store, runs, out)
        assert refused.value.context["refused_because"] == "pair_counted_twice"
        assert refused.value.context["earlier_round"] == _id(other)


def test_the_command_s_refusal_names_the_round_that_holds_the_pair() -> None:
    said = json.loads(
        refused_line({"refused_because": "pair_recorded", "entry": "0", "earlier_round": "ab12"})
    )
    assert said == {
        "format": 1,
        "status": "refused",
        "refused_because": "pair_recorded",
        "entry": 0,
        "session_started": False,
        "earlier_round": "ab12",
    }
    assert "earlier_round" not in json.loads(refused_line({"refused_because": "out_exists"}))
