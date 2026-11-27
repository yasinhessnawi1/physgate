"""A harness trial that gives no figure never blocks its raw pair: the cell's rule caps it.

The raw arm's cap is the paired harness run's token total. Where the harness trial gives no
figure (unscored, stuck, a leftover session read without a result), its raw trial's cap is the
largest total among the same task's other harness trials of the cell; where none of them gives
one, the median of every total of the cell (for an even count, the mean of the two middle ones,
rounded down to a whole token). A cell is one tier's trials: a held-out trial's cap is never a
visible trial's total. Such a raw trial runs after every other entry of its round, and the rule's
step and inputs are recorded with it, beside its record, where the audit derives them again.
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
    StandInArm,
    StandInStore,
    copied,
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


def test_a_trial_with_no_figure_runs_last_capped_at_its_task_s_largest(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    assert harness_figure(stuck) is None and harness_figure(ended) == 1800
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


def test_a_round_of_the_no_figure_entry_alone_takes_its_cap_from_the_cell_it_is_given(
    tmp_path: Path, store: StandInStore
) -> None:
    visible = store.tasks["visible"]
    stuck = harness_run(tmp_path / "runs", visible[0], store, ended=False)
    others = [
        harness_run_spending(tmp_path / "runs", visible[i], store, tokens)
        for i, tokens in ((1, 1200), (2, 3000), (3, 2000))
    ]
    cell = run_set((stuck, 0), *((run, 0) for run in others))
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, run_set((stuck, 0)), out, arm, cell=cell)
    assert isinstance(record, BaselineRecord), record
    assert [cap for _, cap, _ in arm.calls] == [2000]
    assert _cap_record(out, "0000-1")["rule"] == "cell_median"
    # Outside the cell it was given, an entry has no cell to be capped from.
    refused = _round(
        store,
        run_set((stuck, 0)),
        tmp_path / "r2",
        StandInArm(),
        cell=run_set(*((r, 0) for r in others)),
    )
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "not_in_the_cell"


def test_a_held_out_trial_s_cap_is_never_a_visible_trial_s_total(
    tmp_path: Path, store: StandInStore
) -> None:
    stuck = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store, ended=False)
    visible = harness_run_spending(tmp_path / "runs", store.tasks["visible"][0], store, 5000)
    arm = StandInArm()
    refused = _round(store, run_set((visible, 0), (stuck, 0)), tmp_path / "round", arm)
    assert isinstance(refused, BaselineError)
    assert refused.context["refused_because"] == "no_cap_in_the_cell"
    assert refused.context["entry"] == "1" and arm.calls == []


def test_the_audit_holds_a_session_s_cap_to_the_rule(tmp_path: Path, store: StandInStore) -> None:
    task = store.tasks["visible"][0]
    stuck = harness_run(tmp_path / "runs", task, store, ended=False)
    ended = harness_run_spending(tmp_path / "runs", task, store, 1800)
    runs = run_set((stuck, 0), (ended, 1))
    out = tmp_path / "round"
    assert isinstance(_round(store, runs, out, StandInArm()), BaselineRecord)
    kept = out / WORK / "0000-1" / "harness" / "cap.json"
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
