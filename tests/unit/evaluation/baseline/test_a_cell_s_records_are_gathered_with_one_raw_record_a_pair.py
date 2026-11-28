"""A cell's records are gathered for the report: its harness round's, and one raw record a pair.

The gatherer is given a harness round's run set of one tier and the store. The set must be the
round's own, in its order, the round ended; every pair's raw rounds are found by the pair
register beneath the withheld root, and each pair must have exactly one counted raw record (a
once-more's in place of the record it superseded), held to the draw the harness round kept. An
excluded record of either arm, a development round's record and two harness commits refuse the
cell. What it prints is counts and digests.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    CHECKOUT,
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

from physgate.evaluation.baseline.gather import GatherError, gather, write_gathered
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import RoundWaits, RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.per_role.report import parse_trials
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import Role
from physgate.orchestrator.run_config import HarnessState, RunConfig


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _raw(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any) -> Any:  # noqa: ANN401
    try:
        return run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=how.pop("setup", setup_for),
            score=lambda _t, _a: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
            **how,
        )
    except Exception as exc:  # noqa: BLE001 - asserted by the caller
        return exc


def _cell(store: StandInStore, root: Path, n: int = 2, **changes: Any) -> list[Path]:  # noqa: ANN401
    tasks = store.tasks["visible"]
    runs = [harness_run_spending(root, tasks[i], store, 1500 + i) for i in range(n)]
    harness_round_of(store, [RoundPlace(run, 0, tasks[i]) for i, run in enumerate(runs)], **changes)
    return runs


def _refused(store: StandInStore, runs: RunSet, because: str) -> GatherError:
    try:
        outcome: object = gather(store.store, "control", store.version, runs)
    except Exception as exc:  # noqa: BLE001 - asserted below: only the gatherer's refusal will do
        outcome = exc
    assert isinstance(outcome, GatherError), f"not refused by name: {outcome!r}"
    assert outcome.context["refused_because"] == because, outcome.context
    return outcome


def _round_id(out: Path) -> str:
    return str(json.loads((out / "ledger.jsonl").read_text().splitlines()[0])["round"])


def _pins_on_disk(out: Path, harness: dict[str, Any] | None) -> None:
    """The raw round's one session record, its harness checkout written as ``harness``."""
    (record,) = (out / "work").glob("*/harness/raw.json")
    fields = json.loads(record.read_text())
    if harness is None:
        del fields["pins"]["harness"]
    else:
        fields["pins"]["harness"] = harness
    record.write_text(json.dumps(fields))


def test_a_cell_is_gathered_as_its_harness_records_then_one_raw_record_a_pair(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = _cell(store, tmp_path / "runs")
    for i, run in enumerate(runs):
        assert isinstance(
            _raw(store, run_set((run, 0)), tmp_path / f"raw{i}", StandInArm()), BaselineRecord
        )
    cell = run_set(*((r, 0) for r in runs))
    gathered = gather(store.store, "control", store.version, cell)
    assert [(r.arm, r.task) for r in gathered.harness + gathered.raw] == [
        ("harness", store.tasks["visible"][0].id),
        ("harness", store.tasks["visible"][1].id),
        ("raw", store.tasks["visible"][0].id),
        ("raw", store.tasks["visible"][1].id),
    ]
    assert gathered.harness_commit == CHECKOUT.commit and len(gathered.raw_rounds) == 2
    out = tmp_path / "cell.trials.jsonl"
    digest = write_gathered(store.store, "control", gathered, out)
    assert len(parse_trials(out.read_text().splitlines())) == 4
    printed = gathered.printed(digest)
    assert printed == {
        "format": 1,
        "status": "gathered",
        "tier": "visible",
        "pairs": 2,
        "harness_round": "a1b2c3d4e5f60718",
        "raw_rounds": 2,
        "harness_commit": CHECKOUT.commit,
        "records_sha256": digest,
    }
    assert not any(word in json.dumps(printed) for word in ("pass", "fail", "outcome"))


def test_a_pair_with_no_raw_record_or_with_two_refuses_the_cell_naming_its_place(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.evaluation.baseline.runner as runner

    runs = _cell(store, tmp_path / "runs")
    cell = run_set(*((r, 0) for r in runs))
    assert isinstance(
        _raw(store, run_set((runs[0], 0)), tmp_path / "a", StandInArm()), BaselineRecord
    )
    refused = _refused(store, cell, "pair_without_record")
    assert refused.context["place"] == "1"
    assert isinstance(
        _raw(store, run_set((runs[1], 0)), tmp_path / "b", StandInArm()), BaselineRecord
    )
    with monkeypatch.context() as patched:
        patched.setattr(runner, "pairs_refusal", lambda *_a, **_k: None)
        assert isinstance(
            _raw(store, run_set((runs[1], 0)), tmp_path / "c", StandInArm()), BaselineRecord
        )
    refused = _refused(store, cell, "pair_counted_twice")
    assert refused.context["place"] == "1"


def test_a_once_more_s_record_is_gathered_in_place_of_the_one_it_superseded(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _cell(store, tmp_path / "runs", 1)
    cell = run_set((run, 0))
    first = tmp_path / "first"
    assert isinstance(_raw(store, cell, first, StandInArm(end_refused={1})), BaselineRecord)
    # An excluded record, run no more, leaves the cell with no verdict.
    refused = _refused(store, cell, "trial_excluded")
    assert refused.context["arm"] == "raw"
    once = tmp_path / "once"
    assert isinstance(_raw(store, cell, once, StandInArm(), rerun_of=first), BaselineRecord)
    gathered = gather(store.store, "control", store.version, cell)
    once_id = json.loads((once / "ledger.jsonl").read_text().splitlines()[0])["round"]
    assert gathered.raw_rounds == (once_id,) and gathered.raw[0].outcome == "pass"


def test_a_set_that_is_not_its_harness_round_s_own_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = _cell(store, tmp_path / "runs", 3)
    for given in (
        run_set((runs[0], 0), (runs[1], 0)),
        run_set((runs[2], 0), (runs[1], 0), (runs[0], 0)),
    ):
        _refused(store, given, "cell_not_the_round_s")
    other = _cell(store, tmp_path / "other", 1, round_id="0f1e2d3c4b5a6978")
    _refused(
        store,
        run_set((runs[0], 0), (runs[1], 0), (runs[2], 0), (other[0], 0)),
        "cell_not_the_round_s",
    )


def test_a_cell_whose_harness_round_has_places_left_is_not_gathered(
    tmp_path: Path, store: StandInStore
) -> None:
    tasks = store.tasks["visible"]
    one = harness_run_spending(tmp_path / "runs", tasks[0], store, 1500)
    two = harness_run_spending(tmp_path / "runs", tasks[1], store, 1600)
    harness_round_of(store, [RoundPlace(one, 0, tasks[0]), RoundPlace(two, 0, tasks[1], left=True)])
    refused = _refused(store, run_set((one, 0)), "cell_not_ended")
    assert refused.context["places_left"] == "1"


def test_a_raw_record_held_to_a_draw_its_round_did_not_keep_is_not_the_pair_s(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    superseded = harness_run_spending(tmp_path / "runs", task, store, 1200)
    kept = harness_run_spending(tmp_path / "runs", task, store, 1300)
    harness_round_of(store, [RoundPlace(kept, 0, task, earlier=(superseded,))])
    first = tmp_path / "first"
    assert isinstance(_raw(store, run_set((superseded, 0)), first, StandInArm()), BaselineRecord)
    refused = _refused(store, run_set((kept, 0)), "pair_on_a_superseded_draw")
    assert (
        refused.context["earlier_round"]
        == json.loads((first / "ledger.jsonl").read_text().splitlines()[0])["round"]
    )


def test_a_cell_whose_trials_ran_from_two_harness_commits_is_refused_naming_both(
    tmp_path: Path, store: StandInStore
) -> None:
    tasks = store.tasks["visible"]
    other = HarnessState(commit="d" * 40, clean=True, uncommitted_sha256=None)
    one = harness_run_spending(tmp_path / "runs", tasks[0], store, 1500)
    two = harness_run_spending(tmp_path / "runs", tasks[1], store, 1600)
    config = json.loads((two / "run.json").read_text())
    config["harness"] = other.model_dump(mode="json")
    (two / "run.json").write_text(json.dumps(config))
    harness_round_of(store, [RoundPlace(one, 0, tasks[0]), RoundPlace(two, 0, tasks[1])])

    def from_other(run: RunConfig, role: Role) -> RawSetup:
        return replace(setup_for(run, role), harness=other)

    assert isinstance(_raw(store, run_set((one, 0)), tmp_path / "a", StandInArm()), BaselineRecord)
    raw = _raw(store, run_set((two, 0)), tmp_path / "b", StandInArm(), setup=from_other)
    assert isinstance(raw, BaselineRecord), raw
    refused = _refused(store, run_set((one, 0), (two, 0)), "harness_commit_differs")
    assert str(CHECKOUT.commit) in str(refused) and "d" * 40 in str(refused)


def test_a_protected_cell_s_records_are_written_beneath_the_withheld_root_or_not_at_all(
    tmp_path: Path, store: StandInStore, capsys: pytest.CaptureFixture[str]
) -> None:
    from physgate.cli import main

    task = store.tasks["held_out"][0]
    run = harness_run_spending(tmp_path / "runs", task, store, 1500)
    harness_round_of(store, [RoundPlace(run, 0, task, tier="held_out")])
    assert isinstance(
        _raw(store, run_set((run, 0)), tmp_path / "raw", StandInArm()), BaselineRecord
    )
    (tmp_path / "cell.json").write_text(run_set((run, 0)).model_dump_json())
    argv = ["baseline", "gather", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--runs", str(tmp_path / "cell.json")]
    assert main([*argv, "--out", str(tmp_path / "outside.jsonl")]) == 1
    assert json.loads(capsys.readouterr().out)["refused_because"] == "out_not_withheld"
    assert not (tmp_path / "outside.jsonl").exists()
    inside = withheld_root(store.store, "control") / "cells" / "held_out.trials.jsonl"
    assert main([*argv, "--out", str(inside)]) == 0
    said = json.loads(capsys.readouterr().out)
    assert (said["status"], said["tier"], said["pairs"]) == ("gathered", "held_out", 1)
    assert task.id not in json.dumps(said) and len(inside.read_text().splitlines()) == 2
    # Never written over: a second gathering into the same file is refused.
    assert main([*argv, "--out", str(inside)]) == 1
    assert json.loads(capsys.readouterr().out)["refused_because"] == "out_exists"


def test_a_harness_record_the_round_kept_as_excluded_refuses_the_cell(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    run = harness_run_spending(tmp_path / "runs", task, store, 1500)
    harness_round_of(store, [RoundPlace(run, 0, task, excluded=True)])
    refused = _refused(store, run_set((run, 0)), "trial_excluded")
    assert (refused.context["arm"], refused.context["place"]) == ("harness", "0")


def test_a_raw_record_whose_session_names_no_harness_commit_refuses_the_cell(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _cell(store, tmp_path / "runs", 1)
    out = tmp_path / "raw"
    assert isinstance(_raw(store, run_set((run, 0)), out, StandInArm()), BaselineRecord)
    _pins_on_disk(out, None)
    refused = _refused(store, run_set((run, 0)), "harness_commit_unknown")
    assert "raw record at place 0" in str(refused)


def test_a_raw_record_from_another_commit_than_its_harness_run_refuses_the_cell_naming_both(
    tmp_path: Path, store: StandInStore
) -> None:
    # Both harness runs ran from one commit: only the raw record's own commit tells them apart.
    runs = _cell(store, tmp_path / "runs")
    for i, run in enumerate(runs):
        out = tmp_path / f"raw{i}"
        assert isinstance(_raw(store, run_set((run, 0)), out, StandInArm()), BaselineRecord)
    _pins_on_disk(tmp_path / "raw1", {"commit": "d" * 40, "clean": True})
    refused = _refused(store, run_set(*((r, 0) for r in runs)), "harness_commit_differs")
    assert str(CHECKOUT.commit) in str(refused) and "d" * 40 in str(refused)


def test_a_pair_whose_raw_round_cannot_be_read_as_its_own_refuses_the_cell_naming_it(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _cell(store, tmp_path / "runs", 1)
    out = tmp_path / "raw"
    assert isinstance(_raw(store, run_set((run, 0)), out, StandInArm()), BaselineRecord)
    held = _round_id(out)
    out.rename(tmp_path / "moved")
    refused = _refused(store, run_set((run, 0)), "pair_unread")
    assert (refused.context["earlier_round"], refused.context["place"]) == (held, "0")


def test_a_pair_recorded_in_a_raw_round_that_has_not_ended_refuses_the_cell(
    tmp_path: Path, store: StandInStore
) -> None:
    runs = _cell(store, tmp_path / "runs")
    out = tmp_path / "raw"
    # The round records its first entry and waits at the usage limit on its second.
    waits = _raw(store, run_set(*((r, 0) for r in runs)), out, StandInArm(limited={2: RESET_EPOCH}))
    assert isinstance(waits, RoundWaits), waits
    refused = _refused(store, run_set(*((r, 0) for r in runs)), "raw_round_not_ended")
    assert (refused.context["earlier_round"], refused.context["place"]) == (_round_id(out), "0")


def test_a_set_holding_a_run_no_harness_round_placed_refuses_the_cell_naming_its_place(
    tmp_path: Path, store: StandInStore
) -> None:
    (run,) = _cell(store, tmp_path / "runs", 1)
    by_hand = harness_run(tmp_path / "hand", store.tasks["visible"][3], store)
    refused = _refused(store, run_set((run, 0), (by_hand, 0)), "no_harness_round")
    assert refused.context["place"] == "1"


def _round_of_the_cell(
    store: StandInStore, root: Path, round_id: str, started: str, **changes: Any
) -> list[Path]:
    """A harness round of the first two visible tasks, each place with its one raw record."""
    tasks = store.tasks["visible"]
    runs = [harness_run_spending(root, tasks[i], store, 1500 + i) for i in range(2)]
    places = [RoundPlace(run, 0, tasks[i]) for i, run in enumerate(runs)]
    harness_round_of(store, places, round_id=round_id, started=started, **changes)
    for i, run in enumerate(runs):
        out = root / f"raw{i}"
        assert isinstance(_raw(store, run_set((run, 0)), out, StandInArm()), BaselineRecord)
    return runs


def test_a_cell_is_gathered_from_its_first_harness_round_and_a_later_one_is_refused_naming_it(
    tmp_path: Path, store: StandInStore
) -> None:
    first = _round_of_the_cell(store, tmp_path / "a", "a1b2c3d4e5f60718", "2026-11-28T10:00:00Z")
    # Started before it, but neither counts: a shakedown, and a round of another version.
    _round_of_the_cell(
        store, tmp_path / "s", "5a5a5a5a5a5a5a5a", "2026-11-27T10:00:00Z", shakedown=True
    )
    _round_of_the_cell(
        store, tmp_path / "v", "7e7e7e7e7e7e7e7e", "2026-11-27T11:00:00Z", version="f" * 64
    )
    later = _round_of_the_cell(store, tmp_path / "b", "b1b2c3d4e5f60718", "2026-11-28T11:00:00Z")
    refused = _refused(store, run_set(*((r, 0) for r in later)), "cell_has_an_earlier_round")
    assert refused.context["earlier_round"] == "a1b2c3d4e5f60718"
    assert "a1b2c3d4e5f60718" in str(refused)
    gathered = gather(store.store, "control", store.version, run_set(*((r, 0) for r in first)))
    assert gathered.harness_round == "a1b2c3d4e5f60718"
    # Two rounds of the cell whose order cannot be told: neither is gathered.
    _round_of_the_cell(store, tmp_path / "c", "c1b2c3d4e5f60718", "2026-11-28T10:00:00Z")
    refused = _refused(store, run_set(*((r, 0) for r in first)), "cell_has_an_earlier_round")
    assert refused.context["earlier_round"] == "c1b2c3d4e5f60718"
