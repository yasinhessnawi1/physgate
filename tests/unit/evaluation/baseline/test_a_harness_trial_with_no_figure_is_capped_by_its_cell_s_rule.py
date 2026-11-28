"""A harness trial that gives no figure never blocks its raw pair: the cell's rule caps it.

The raw arm's cap is the paired harness run's token total. Where the harness trial gives no
figure (unscored, stuck, a leftover session read without a result), its raw trial's cap is the
largest total among the same task's other harness trials of the cell; where none of them gives
one, the median of every total of the cell (for an even count, the mean of the two middle ones,
rounded down to a whole token). A cell is one tier's trials of the entry's own harness round,
found from the entry and never from a file a person names: a held-out trial's cap is never a
visible trial's total, and a draw the round excluded, an ablation arm's trial and a trial of
another round are never in it. It is whole once the round has ended, and not before. Such a raw
trial runs after every other entry of its round, and the rule's step, its inputs and the cell's
origin are recorded with it, beside its record, where the audit derives them again.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    PRICES,
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
from harness_rig import loop_run

from physgate.evaluation.baseline.audit import audit_raw
from physgate.evaluation.baseline.caps import CellTrial, NoCapError, RawCap, median_total, raw_cap
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import (
    WORK,
    BaselineError,
    RunSet,
    harness_figure,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.orchestrator.events import ReviewRan, SessionSpawned, read_events

# -- the rule ------------------------------------------------------------------------------------


def test_a_trial_with_a_figure_is_capped_at_its_own_total() -> None:
    own = CellTrial(0, "a", 1200)
    assert raw_cap(own, [own, CellTrial(1, "a", 9000)]) == RawCap("pair", 1200, ((0, 1200),))


def test_a_trial_with_no_figure_takes_the_largest_of_its_task_s_other_trials() -> None:
    own = CellTrial(2, "a", None)
    cell = [CellTrial(0, "a", 1200), CellTrial(1, "a", 1500), own, CellTrial(3, "b", 9000)]
    assert raw_cap(own, cell) == RawCap("task_largest", 1500, ((0, 1200), (1, 1500)))


def test_with_no_figure_in_its_task_it_takes_the_cell_s_median() -> None:
    own = CellTrial(0, "a", None)
    cell = [own, CellTrial(1, "b", 100), CellTrial(2, "c", 700), CellTrial(3, "d", 300)]
    assert raw_cap(own, cell) == RawCap("cell_median", 300, ((1, 100), (2, 700), (3, 300)))


def test_the_median_of_an_even_count_is_the_two_middle_totals_mean_rounded_down() -> None:
    own = CellTrial(0, "a", None)
    cell = [own, CellTrial(1, "b", 100), CellTrial(2, "c", 301), CellTrial(3, "d", 400)]
    cell.append(CellTrial(4, "e", 900))
    assert raw_cap(own, cell).cap == (301 + 400) // 2 == 350
    assert median_total([4, 1, 3, 2]) == 2 and median_total([5]) == 5


def test_a_cell_with_no_figure_at_all_gives_no_cap() -> None:
    own = CellTrial(0, "a", None)
    with pytest.raises(NoCapError) as refused:
        raw_cap(own, [own, CellTrial(1, "b", None)])
    assert refused.value.context["refused_because"] == "no_cap_in_the_cell"


# -- the round -----------------------------------------------------------------------------------


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


def _cap_record(out: Path, name: str) -> Any:  # noqa: ANN401
    return json.loads((out / WORK / name / "harness" / "cap.json").read_text())


def _origin(place: Path, *runs: tuple[Path, int], tier: str = "visible") -> dict[str, str]:
    """The cell's origin a cap record names: the round, the tier, and its set's digest."""
    import hashlib
    import os

    entries = [{"run_dir": os.path.realpath(r), "trial": t} for r, t in runs]
    tier_set = RunSet.model_validate_json(json.dumps({"format": 1, "trials": entries}))
    digest = hashlib.sha256(tier_set.model_dump_json().encode()).hexdigest()
    return {"round": place.name, "tier": tier, "runs_sha256": digest}


def test_a_trial_with_no_figure_runs_last_capped_at_its_task_s_largest(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    assert harness_figure(stuck) is None and harness_figure(ended) == 1800
    place = harness_round_of(store, [RoundPlace(stuck, 0, task), RoundPlace(ended, 1, task)])
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, run_set((stuck, 0), (ended, 1)), out, arm)
    assert isinstance(record, BaselineRecord), record
    # The entry with no figure runs after the other, at its own place in the run set.
    assert [cap for _, cap, _ in arm.calls] == [1800, 1800]
    assert [p.parent.name[-6:] for _, _, p in arm.calls] == ["0001-1", "0000-1"]
    assert _cap_record(out, "0000-1") == {
        "rule": "task_largest",
        "cap": 1800,
        "inputs": [{"place": 1, "total": 1800}],
        "cell": _origin(place, (stuck, 0), (ended, 1)),
    }
    assert _cap_record(out, "0001-1") == {
        "rule": "pair",
        "cap": 1800,
        "inputs": [{"place": 1, "total": 1800}],
    }
    assert record.counts["visible"].cap == 3600
    assert record.no_figure == {"visible": {"entries": 2, "no_figure": 1}}
    found = audit_raw(
        store=store.store,
        role="control",
        version=store.version,
        runs=run_set((stuck, 0), (ended, 1)),
        out=out,
        prices=load_price_sheet(PRICES),
        score=lambda _t, _a: dict(SCORED),
    )
    assert found == []


def test_a_reviewed_trial_s_raw_pair_is_capped_at_its_own_total(
    tmp_path: Path, store: StandInStore
) -> None:
    """Each review's session is spawned on the log, and only its own lines end it.

    So a harness trial whose module was reviewed, here twice, gives its own figure, and its raw
    pair is capped by the rule's first step, never by the cell's.
    """
    task = store.tasks["visible"][0]
    run = harness_run(tmp_path / "runs", task, store)
    made = loop_run(tmp_path / "loop" / "run", verdicts=("fail",))
    shutil.copyfile(made / "events.jsonl", run / "events.jsonl")
    shutil.copytree(made / "review", run / "review", dirs_exist_ok=True)
    events = read_events(run / "events.jsonl")
    reviews = {e.result.session_id for e in events if isinstance(e, ReviewRan)}
    assert len(reviews) == 2
    assert reviews <= {e.session_id for e in events if isinstance(e, SessionSpawned)}
    total = harness_figure(run)
    assert total is not None
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, run_set((run, 0)), out, arm)
    assert isinstance(record, BaselineRecord), record
    assert [cap for _, cap, _ in arm.calls] == [total]
    assert _cap_record(out, "0000-1") == {
        "rule": "pair",
        "cap": total,
        "inputs": [{"place": 0, "total": total}],
    }


def test_a_round_of_the_no_figure_entry_alone_takes_its_cap_from_its_harness_round_s_cell(
    tmp_path: Path, store: StandInStore
) -> None:
    visible = store.tasks["visible"]
    stuck = harness_run(tmp_path / "runs", visible[0], store, ended=False)
    others = [
        harness_run_spending(tmp_path / "runs", visible[i], store, tokens)
        for i, tokens in ((1, 1200), (2, 3000), (3, 2000))
    ]
    place = harness_round_of(
        store,
        [RoundPlace(stuck, 0, visible[0])]
        + [RoundPlace(run, 0, visible[i]) for i, run in enumerate(others, 1)],
    )
    arm = StandInArm()
    out = tmp_path / "round"
    # No cell is named: the entry's own harness round gives it.
    record = _round(store, run_set((stuck, 0)), out, arm)
    assert isinstance(record, BaselineRecord), record
    assert [cap for _, cap, _ in arm.calls] == [2000]
    assert _cap_record(out, "0000-1") == {
        "rule": "cell_median",
        "cap": 2000,
        "inputs": [
            {"place": 1, "total": 1200},
            {"place": 2, "total": 3000},
            {"place": 3, "total": 2000},
        ],
        "cell": _origin(place, (stuck, 0), *((r, 0) for r in others)),
    }


def test_a_cell_named_by_a_person_is_held_to_the_round_s_own_and_never_changes_a_cap(
    tmp_path: Path, store: StandInStore
) -> None:
    visible = store.tasks["visible"]
    stuck = harness_run(tmp_path / "runs", visible[0], store, ended=False)
    cheap = harness_run_spending(tmp_path / "runs", visible[1], store, 1200)
    dear = harness_run_spending(tmp_path / "runs", visible[2], store, 3000)
    harness_round_of(
        store,
        [
            RoundPlace(stuck, 0, visible[0]),
            RoundPlace(cheap, 0, visible[1]),
            RoundPlace(dear, 0, visible[2]),
        ],
    )
    # The trial and one other task's dearest: a cell that would cap it at 3000.
    for name, given in (
        ("dearest", run_set((stuck, 0), (dear, 0))),
        ("cheapest", run_set((stuck, 0), (cheap, 0))),
        ("reordered", run_set((dear, 0), (cheap, 0), (stuck, 0))),
    ):
        arm = StandInArm()
        refused = _round(store, run_set((stuck, 0)), tmp_path / name, arm, cell=given)
        assert isinstance(refused, BaselineError), name
        assert refused.context["refused_because"] == "cell_not_the_round_s"
        assert arm.calls == [] and not (tmp_path / name).exists()
    arm = StandInArm()
    own = run_set((stuck, 0), (cheap, 0), (dear, 0))
    record = _round(store, run_set((stuck, 0)), tmp_path / "own", arm, cell=own)
    assert isinstance(record, BaselineRecord), record
    assert [cap for _, cap, _ in arm.calls] == [(1200 + 3000) // 2]


def test_a_trial_with_no_figure_waits_for_its_harness_round_s_last_place(
    tmp_path: Path, store: StandInStore
) -> None:
    visible = store.tasks["visible"]
    stuck = harness_run(tmp_path / "runs", visible[0], store, ended=False)
    done = harness_run_spending(tmp_path / "runs", visible[1], store, 1200)
    later = harness_run_spending(tmp_path / "runs", visible[2], store, 3000)
    harness_round_of(
        store,
        [
            RoundPlace(stuck, 0, visible[0]),
            RoundPlace(done, 0, visible[1]),
            RoundPlace(later, 0, visible[2], left=True),
        ],
    )
    arm = StandInArm()
    refused = _round(store, run_set((stuck, 0)), tmp_path / "round", arm)
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "cell_not_ended"
    assert refused.context["places_left"] == "2"
    assert arm.calls == [] and not (tmp_path / "round").exists()
    # A trial with a figure of its own is not held to the cell: its raw pair runs now.
    record = _round(store, run_set((done, 0)), tmp_path / "now", StandInArm())
    assert isinstance(record, BaselineRecord), record


def test_no_excluded_draw_ablation_trial_or_other_round_s_trial_is_in_a_cell_s_figures(
    tmp_path: Path, store: StandInStore
) -> None:
    visible = store.tasks["visible"]
    runs = tmp_path / "runs"
    stuck = harness_run(runs, visible[0], store, ended=False)
    superseded = harness_run_spending(runs, visible[1], store, 9000)
    kept = harness_run_spending(runs, visible[1], store, 1000)
    excluded = harness_run_spending(runs, visible[2], store, 8000)
    arm_run = harness_run_spending(runs, visible[3], store, 7000)
    other = harness_run_spending(runs, visible[3], store, 6000)
    harness_round_of(
        store,
        [
            RoundPlace(stuck, 0, visible[0]),
            RoundPlace(kept, 0, visible[1], earlier=(superseded,)),
            RoundPlace(excluded, 0, visible[2], excluded=True),
            RoundPlace(arm_run, 0, visible[3], arm="reviewers_off"),
        ],
    )
    harness_round_of(store, [RoundPlace(other, 0, visible[3])], round_id="0f1e2d3c4b5a6978")
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, run_set((stuck, 0)), out, arm)
    assert isinstance(record, BaselineRecord), record
    # The kept draw alone gives a figure: the median of one total is that total.
    assert [cap for _, cap, _ in arm.calls] == [1000]
    assert _cap_record(out, "0000-1")["inputs"] == [{"place": 1, "total": 1000}]
    # A draw the round did not keep, with no figure of its own, is never capped from the cell.
    dropped = harness_run(runs, visible[0], store, ended=False)
    again = harness_run(runs, visible[0], store, ended=False)
    given = harness_run_spending(runs, visible[1], store, 1000)
    harness_round_of(
        store,
        [RoundPlace(given, 0, visible[1]), RoundPlace(again, 0, visible[0], earlier=(dropped,))],
        round_id="1f2e3d4c5b6a7980",
    )
    refused = _round(store, run_set((dropped, 0)), tmp_path / "draw", StandInArm())
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "not_the_final_draw"


def test_a_held_out_trial_s_cap_is_never_a_visible_trial_s_total(
    tmp_path: Path, store: StandInStore
) -> None:
    stuck = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store, ended=False)
    visible = harness_run_spending(tmp_path / "runs", store.tasks["visible"][0], store, 5000)
    harness_round_of(
        store,
        [
            RoundPlace(visible, 0, store.tasks["visible"][0]),
            RoundPlace(stuck, 0, store.tasks["held_out"][0], tier="held_out"),
        ],
    )
    arm = StandInArm()
    refused = _round(store, run_set((visible, 0), (stuck, 0)), tmp_path / "round", arm)
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "no_cap_in_the_cell"
    assert refused.context["entry"] == "1" and arm.calls == []


def test_a_trial_with_no_figure_and_no_harness_round_is_capped_only_in_a_development_round(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    runs = run_set((stuck, 0), (ended, 1))
    refused = _round(store, runs, tmp_path / "counted", StandInArm())
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "no_harness_round"
    arm = StandInArm()
    record = _round(store, runs, tmp_path / "development", arm, development=True)
    assert isinstance(record, BaselineRecord), record
    assert [cap for _, cap, _ in arm.calls] == [1800, 1800]


def test_the_audit_holds_a_session_s_cap_to_the_rule(tmp_path: Path, store: StandInStore) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    harness_round_of(store, [RoundPlace(stuck, 0, task), RoundPlace(ended, 1, task)])
    runs = run_set((stuck, 0), (ended, 1))
    out = tmp_path / "round"
    assert isinstance(_round(store, runs, out, StandInArm()), BaselineRecord)
    kept = out / WORK / "0000-1" / "harness" / "cap.json"
    written = json.loads(kept.read_text())
    # A record written before the cell's origin was held names none, and audits clean.
    kept.write_text(json.dumps({k: v for k, v in written.items() if k != "cell"}))
    assert (
        audit_raw(
            store=store.store,
            role="control",
            version=store.version,
            runs=runs,
            out=out,
            prices=load_price_sheet(PRICES),
            score=lambda _t, _a: dict(SCORED),
        )
        == []
    )
    # Another cell's origin differs.
    kept.write_text(json.dumps({**written, "cell": {**written["cell"], "round": "0" * 16}}))
    assert [
        (d.kind, d.index)
        for d in audit_raw(
            store=store.store,
            role="control",
            version=store.version,
            runs=runs,
            out=out,
            prices=load_price_sheet(PRICES),
            score=lambda _t, _a: dict(SCORED),
        )
    ] == [("cap", 0)]
    kept.write_text(json.dumps({"rule": "cell_median", "cap": 1800, "inputs": []}))
    found = audit_raw(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        prices=load_price_sheet(PRICES),
        score=lambda _t, _a: dict(SCORED),
    )
    assert [(d.kind, d.index) for d in found] == [("cap", 0)]


def test_a_round_where_more_than_a_third_gave_no_figure_says_so_loudly(
    tmp_path: Path,
    store: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sys
    import types

    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install
    from physgate.cli import main

    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    harness_round_of(store, [RoundPlace(stuck, 0, task), RoundPlace(ended, 1, task)])
    runs = run_set((stuck, 0), (ended, 1))
    (tmp_path / "runs.json").write_text(runs.model_dump_json())
    real = runner.run_baseline
    module = types.ModuleType("physgate.evaluation.per_role.scorers.control")
    module.score = lambda _task, _answer: dict(SCORED)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(
        runner,
        "run_baseline",
        lambda **given: real(**{**given, "setup_for": setup_for, "arm": StandInArm()}),
    )
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    argv = ["baseline", "run", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--runs", str(tmp_path / "runs.json")]
    argv += ["--out", str(tmp_path / "o"), "--prices", PRICES]
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert "1 of the 2 visible entries gave no token total of their own" in captured.err
    assert json.loads(captured.out)["no_figure"] == {"visible": {"entries": 2, "no_figure": 1}}


def test_a_cell_is_held_to_the_combined_set_its_harness_round_wrote(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    place = harness_round_of(store, [RoundPlace(stuck, 0, task), RoundPlace(ended, 1, task)])
    written = json.loads((place / "all.runs.json").read_text())
    written["trials"] = written["trials"][:1]
    (place / "all.runs.json").write_text(json.dumps(written))
    refused = _round(store, run_set((stuck, 0)), tmp_path / "round", StandInArm())
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "cell_not_the_round_s"


def test_a_run_two_harness_rounds_place_is_no_round_s_and_refuses(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    run = harness_run_spending(tmp_path / "runs", task, store, 1800)
    harness_round_of(store, [RoundPlace(run, 0, task)])
    harness_round_of(store, [RoundPlace(run, 0, task)], round_id="0f1e2d3c4b5a6978")
    refused = _round(store, run_set((run, 0)), tmp_path / "round", StandInArm())
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "run_in_two_rounds"
