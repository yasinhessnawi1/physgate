"""An external task set is a source of the baseline, kept apart from the three tiers (criterion 6).

A published benchmark's tasks (ControlEval, the firmware set) are run the way a tier version's
are: every harness trial of the run set, capped at its harness total, under its pins. The set is
named by its own directory, never by a tier version; its round records the set (its benchmark,
its task count and its digest) where a tier round records its tiers, and counts its trials under
``external`` alone. A tier's task is never taken as an external one, nor the reverse.

The rows capture what the round returned or raised and assert on it, so a row fails on its
assertion whatever the runner does.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
from task_fixtures import external_task, own_task, write_task_dir

from physgate.evaluation.baseline.record import BASELINE_RECORD, TIERS_RECORD, BaselineRecord
from physgate.evaluation.baseline.runner import BASELINE_DIR, TRIALS, RunSet, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.heldout import tier_digest
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import Task, parse_task

EXTERNAL_RECORD = Path("evaluation") / "external.json"


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _try(call: Callable[[], Any]) -> Any:  # noqa: ANN401 - what the call returned, or raised
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the row asserts on what it was
        return exc


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


def _external(i: int, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    raw = external_task(
        id=f"controleval.second_order_unstable.{i:03d}",
        brief=f"Design a controller for published plant {i}. Write it to answer.json.",
    )
    raw["source"]["index"] = i
    raw.update(changes)
    return raw


def _set(directory: Path, *raws: dict[str, Any]) -> list[Task]:
    for raw in raws:
        write_task_dir(directory / raw["id"], raw, {})
    return [parse_task(json.dumps(raw).encode()) for raw in raws]


def _round(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **source: Any) -> Any:  # noqa: ANN401
    return _try(
        lambda: run_baseline(
            store=made.store,
            role="control",
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=lambda _s: None,
            **source,
        )
    )


def test_an_external_set_is_run_as_a_source_of_its_own_and_recorded_apart_from_the_tiers(
    tmp_path: Path, store: StandInStore
) -> None:
    directory = tmp_path / "controleval"
    tasks = _set(directory, *(_external(i) for i in range(3)))
    runs = run_set(*((harness_run(tmp_path / "runs", t, store), 0) for t in tasks))
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, runs, out, arm, external=directory)
    assert isinstance(record, BaselineRecord), record
    assert sorted(task_id for task_id, _, _ in arm.calls) == sorted(t.id for t in tasks)
    assert {cap for _, cap, _ in arm.calls} == {1000}
    written = json.loads((out / EXTERNAL_RECORD).read_text())
    assert written == {
        "format": 1,
        "benchmark": "controleval",
        "role": "control",
        "tasks": 3,
        "sha256": tier_digest(directory),
    }
    as_read = json.loads((out / BASELINE_RECORD).read_text())
    assert as_read["external"] == written and as_read["tiers"] is None
    assert set(as_read["counts"]) == {"external"}
    assert (as_read["counts"]["external"]["trials"], as_read["counts"]["external"]["passed"]) == (
        3,
        3,
    )
    assert not (out / TIERS_RECORD).exists()
    # A published task is no protected one: its trials lie in the round's own directory.
    assert len((out / TRIALS).read_text().splitlines()) == 3
    assert not (withheld_root(store.store, "control") / BASELINE_DIR).exists()


@pytest.mark.parametrize(
    "intruder",
    [
        own_task(id="control.own_01", brief="An own visible task among the published ones."),
        own_task(
            id="control.own_02",
            tier="held_out",
            canary="ab" * 16,
            brief="An own held-out task among the published ones.",
        ),
    ],
    ids=["a visible task", "a held-out task"],
)
def test_a_tier_s_task_in_an_external_set_refuses_the_round_before_any_session(
    tmp_path: Path, store: StandInStore, intruder: dict[str, Any]
) -> None:
    directory = tmp_path / "controleval"
    tasks = _set(directory, _external(0), intruder)
    runs = run_set((harness_run(tmp_path / "runs", tasks[0], store), 0))
    arm = StandInArm()
    refused = _round(store, runs, tmp_path / "round", arm, external=directory)
    assert type(refused).__name__ == "BaselineError", refused
    assert "external" in str(refused) and arm.calls == []


@pytest.mark.parametrize("both", [True, False], ids=["a version and a set", "neither"])
def test_a_round_names_one_source_a_tier_version_or_an_external_set(
    tmp_path: Path, store: StandInStore, both: bool
) -> None:
    directory = tmp_path / "controleval"
    tasks = _set(directory, _external(0))
    runs = run_set((harness_run(tmp_path / "runs", tasks[0], store), 0))
    arm = StandInArm()
    source: dict[str, Any] = {"version": store.version, "external": directory} if both else {}
    refused = _round(store, runs, tmp_path / "round", arm, **source)
    assert type(refused).__name__ == "BaselineError", refused
    assert "one source" in str(refused) and arm.calls == []


def test_a_run_on_a_tier_s_task_is_no_trial_of_an_external_set(
    tmp_path: Path, store: StandInStore
) -> None:
    directory = tmp_path / "controleval"
    _set(directory, _external(0))
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    arm = StandInArm()
    refused = _round(store, runs, tmp_path / "round", arm, external=directory)
    assert type(refused).__name__ == "BaselineError", refused
    assert "no task of" in str(refused) and arm.calls == []


def test_an_external_set_of_two_benchmarks_is_refused(tmp_path: Path, store: StandInStore) -> None:
    directory = tmp_path / "mixed"
    other = _external(1, id="otherbench.plant.001")
    other["source"]["benchmark"] = "otherbench"
    tasks = _set(directory, _external(0), other)
    runs = run_set((harness_run(tmp_path / "runs", tasks[0], store), 0))
    arm = StandInArm()
    refused = _round(store, runs, tmp_path / "round", arm, external=directory)
    assert type(refused).__name__ == "BaselineError", refused
    assert "one benchmark" in str(refused) and arm.calls == []


def test_an_external_set_inside_the_store_is_refused(tmp_path: Path, store: StandInStore) -> None:
    """Kept apart: a set beneath the store would be read by the store's own scans and splits."""
    directory = store.store / "control" / "controleval"
    tasks = _set(directory, _external(0))
    runs = run_set((harness_run(tmp_path / "runs", tasks[0], store), 0))
    arm = StandInArm()
    refused = _round(store, runs, tmp_path / "round", arm, external=directory)
    assert type(refused).__name__ == "BaselineError", refused
    assert "apart" in str(refused) and arm.calls == []


def test_an_empty_external_set_is_refused(tmp_path: Path, store: StandInStore) -> None:
    directory = tmp_path / "controleval"
    directory.mkdir()
    task = parse_task(json.dumps(_external(0)).encode())
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    arm = StandInArm()
    refused = _round(store, runs, tmp_path / "round", arm, external=directory)
    assert type(refused).__name__ == "BaselineError", refused
    assert "no task" in str(refused) and arm.calls == []


def test_a_record_holds_one_source_and_counts_only_its_tiers(
    tmp_path: Path, store: StandInStore
) -> None:
    """Read back, a record naming both sources, or counting a tier its source lacks, is refused."""
    directory = tmp_path / "controleval"
    tasks = _set(directory, _external(0))
    runs = run_set((harness_run(tmp_path / "runs", tasks[0], store), 0))
    external = _round(store, runs, tmp_path / "ext", StandInArm(), external=directory)
    visible = store.tasks["visible"][0]
    runs = run_set((harness_run(tmp_path / "runs", visible, store), 0))
    tiered = _round(store, runs, tmp_path / "tiers", StandInArm(), version=store.version)
    assert isinstance(external, BaselineRecord), external
    assert isinstance(tiered, BaselineRecord), tiered
    good = external.model_dump(mode="json")
    both = dict(good, tiers=tiered.model_dump(mode="json")["tiers"])
    counted = dict(good, counts={**good["counts"], "visible": good["counts"]["external"]})
    tier_counted = dict(
        tiered.model_dump(mode="json"),
        counts={"external": good["counts"]["external"]},
    )
    for bad in (both, counted, tier_counted):
        with pytest.raises(ValueError, match="one source|exactly its source"):
            BaselineRecord.model_validate_json(json.dumps(bad))
    assert BaselineRecord.model_validate_json(json.dumps(good)) == external
