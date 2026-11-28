"""The vector writer: the protected tiers reach the gaps only as an anonymous per-task vector.

``physgate gaps vector`` is the harness side's step. It reads a protected tier's trial records
and the run set they came from, holds them to the counting rule, and writes, beneath the role's
withheld root, each task's passes and trials in an order shuffled afresh, with no id, no brief's
digest, no timing and no cost. Every run of it is one measurement of the version, a line in the
register. It refuses, writing nothing, inside a session, for a version exposed as read now, and
for a run set the rule refuses. The raw arm has no run sets yet, and is refused in words.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from gap_fixtures import (
    Measured,
    StandInStore,
    api,
    measured,
    record,
    stand_in_store,
    write_records,
    write_runs,
)

from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.tiers.issued import issued_sha256
from physgate.evaluation.tiers.store import withheld_root

WRITE = "physgate.evaluation.tiers.measure.write_vector"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path / "st")


def _measurements(made: StandInStore) -> list[Any]:
    lines = api("physgate.evaluation.tiers.exposure.register_lines")(made.store, "control")
    return [line for line in lines if line.kind == "measurement"]


def _write(made: StandInStore, tier: str, m: Measured, **changes: Any) -> str:  # noqa: ANN401
    args: dict[str, Any] = {"version": made.version, "tier": tier, "runs": m.runs}
    args["trials"] = m.trials
    args.update(changes)
    key: str = api(WRITE)(withheld_root(made.store, "control"), **args)
    return key


def _refused(made: StandInStore, tier: str, m: Measured, **changes: Any) -> str:  # noqa: ANN401
    """Why the writer refused; the row fails if it wrote anything."""
    before = _measurements(made)
    writer = api(WRITE)
    try:
        writer(
            withheld_root(made.store, "control"),
            **{"version": made.version, "tier": tier, "runs": m.runs, "trials": m.trials} | changes,
        )
    except Exception as exc:  # noqa: BLE001 - the refusal's reason is what is read
        reason = str(getattr(exc, "context", {}).get("refused_because", type(exc).__name__))
    else:
        pytest.fail("the writer wrote a vector it should have refused")
    assert _measurements(made) == before, "a refused write counted a measurement"
    vectors = withheld_root(made.store, "control") / "gaps"
    assert not vectors.exists() or not any(vectors.iterdir()), "a refused write left a vector"
    return reason


def test_a_vector_is_written_beneath_the_withheld_root_as_counts_alone(
    tmp_path: Path, made: StandInStore
) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    key = _write(made, "held_out", m)
    path = withheld_root(made.store, "control") / "gaps" / f"{key}.json"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == key, "the key is not the vector's digest"
    vector = json.loads(raw)
    # Every held-out task, two trials each: task 0 passes trial 0 only, the rest pass none.
    assert sorted((t["passes"], t["trials"]) for t in vector["tasks"]) == [(0, 2)] * 7 + [(1, 2)]
    assert vector["version"] == made.version and vector["tier"] == "held_out"
    text = raw.decode()
    for task in made.tasks["held_out"]:
        assert task.id not in text, "the vector names a task"
        assert hashlib.sha256(task.brief.encode()).hexdigest() not in text, "a brief's digest"
        assert issued_sha256(task) not in text, "the digest of what a session is given"
    for run_dir in m.run_dirs:
        assert str(run_dir) not in text and run_dir.name not in text, "the vector names a run"
    for word in ("seed", "wall_clock", "usd", "tokens", "suite"):
        assert word not in text, f"the vector holds {word}"


def test_every_run_of_the_writer_is_one_measurement_line(
    tmp_path: Path, made: StandInStore
) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    first = _write(made, "held_out", m)
    second = _write(made, "held_out", m)
    lines = _measurements(made)
    assert [(line.measured, line.version) for line in lines] == [("gaps", made.version)] * 2
    assert {line.key for line in lines} == {first, second}, "a write is not its own measurement"


def test_the_order_is_shuffled_afresh_on_every_write(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    orders = set()
    for _ in range(20):
        key = _write(made, "held_out", m)
        vector = json.loads(
            (withheld_root(made.store, "control") / "gaps" / f"{key}.json").read_text()
        )
        orders.add(tuple(t["passes"] for t in vector["tasks"]))
    assert len(orders) > 1, "twenty writes of eight tasks kept one order"


def test_inside_a_session_the_writer_writes_nothing(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    assert _refused(made, "held_out", m) == "inside_a_session"


def test_a_version_exposed_as_read_now_is_not_measured(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    api("physgate.evaluation.tiers.exposure.mark_exposed")(
        made.store, "control", made.version, by="a person", reason="opened a task file"
    )
    assert _refused(made, "held_out", m) == "version_exposed"


def test_the_raw_arm_is_refused_in_words(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    assert _refused(made, "held_out", m, arm="raw") == "raw_arm_has_no_run_sets"


def test_records_kept_outside_the_withheld_root_are_refused(
    tmp_path: Path, made: StandInStore
) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    outside = write_records(tmp_path / "out" / "trials.jsonl", _records(m))
    assert _refused(made, "held_out", m, trials=outside) == "trials_not_withheld"


def _swap_records(m: Measured, records: list[dict[str, Any]]) -> Measured:
    return Measured(m.runs, write_records(m.trials, records), m.run_dirs, m.tasks)


def _swap_runs(m: Measured, runs: list[tuple[Path, int]]) -> Measured:
    return Measured(write_runs(m.runs, runs), m.trials, m.run_dirs, m.tasks)


def _records(m: Measured) -> list[dict[str, Any]]:
    return [json.loads(line) for line in m.trials.read_text().splitlines()]


def test_a_run_on_another_tier_s_task_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "visible", tmp_path / "a")
    place = withheld_root(made.store, "control") / "trials" / "v"
    runs = write_runs(place / "runs.json", [(r, i % 2) for i, r in enumerate(m.run_dirs)])
    trials = write_records(place / "trials.jsonl", _records(m))
    assert _refused(made, "held_out", Measured(runs, trials, m.run_dirs, m.tasks)) == (
        "run_not_in_tier"
    )


@pytest.mark.parametrize("tier", ["validation", "held_out"])
def test_a_run_given_a_task_s_brief_without_its_values_is_refused_by_its_own_name(
    tmp_path: Path, made: StandInStore, tier: str
) -> None:
    alone = hashlib.sha256(made.tasks[tier][0].brief.encode()).hexdigest()
    m = measured(made, tier, tmp_path / "a", tasks=1, brief_sha256=alone)
    assert _refused(made, tier, m) == "given_the_brief_alone"


def test_a_run_listed_twice_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    runs = [(r, i % 2) for i, r in enumerate(m.run_dirs)]
    assert _refused(made, "held_out", _swap_runs(m, [*runs, runs[0]])) == "run_listed_twice"


@pytest.mark.parametrize("field", ["effort", "max_output_tokens"])
def test_a_drift_field_that_differs_between_runs_is_refused(
    tmp_path: Path, made: StandInStore, field: str
) -> None:
    assert field in DRIFT
    m = measured(made, "held_out", tmp_path / "a")
    other: dict[str, Any] = {field: {"effort": "low", "max_output_tokens": 1000}[field]}
    odd = measured(made, "held_out", tmp_path / "b", tasks=1, trials=1, **other)
    runs = [(r, i % 2) for i, r in enumerate(m.run_dirs)]
    runs[-1] = (odd.run_dirs[0], 1)
    assert _refused(made, "held_out", _swap_runs(m, runs)) == "drift"


def test_one_task_s_runs_start_from_one_target_head(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    odd = measured(made, "held_out", tmp_path / "b", tasks=1, trials=1, target_head="d" * 40)
    runs = [(r, i % 2) for i, r in enumerate(m.run_dirs)]
    runs[1] = (odd.run_dirs[0], 1)
    assert _refused(made, "held_out", _swap_runs(m, runs)) == "target_head"


def test_tasks_may_start_from_different_target_heads(tmp_path: Path, made: StandInStore) -> None:
    # Task 0's two runs from one target commit, every other task's from another.
    first = measured(made, "held_out", tmp_path / "a", trials=2)
    other = measured(made, "held_out", tmp_path / "b", trials=2, target_head="d" * 40)
    runs = [(r, i % 2) for i, r in enumerate(first.run_dirs[:2])]
    runs += [(r, i % 2) for i, r in enumerate(other.run_dirs[2:])]
    _write(made, "held_out", _swap_runs(first, runs))


def test_a_record_without_its_run_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    extra = record(m.tasks[0].id, 5, "pass")
    assert _refused(made, "held_out", _swap_records(m, [*_records(m), extra])) == (
        "records_not_runs"
    )


def test_a_run_without_its_record_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    assert _refused(made, "held_out", _swap_records(m, _records(m)[:-1])) == "records_not_runs"


def test_an_excluded_trial_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    records = _records(m)
    last = records[-1]
    records[-1] = {k: last[k] for k in ("suite", "task", "arm", "trial")} | {"reason": "x: y"}
    assert _refused(made, "held_out", _swap_records(m, records)) == "trial_excluded"


def test_a_record_of_another_arm_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    records = _records(m)
    records[0] = record(records[0]["task"], records[0]["trial"], "pass", arm="observe")
    assert _refused(made, "held_out", _swap_records(m, records)) == "records_not_runs"


def test_tasks_with_unequal_trials_are_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    runs = [(r, i % 2) for i, r in enumerate(m.run_dirs)][:-1]
    assert _refused(made, "held_out", _swap_records(_swap_runs(m, runs), _records(m)[:-1])) == (
        "unequal_trials"
    )


def test_a_run_that_is_not_reportable_is_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a", reportable=False)
    assert _refused(made, "held_out", m) == "run_not_measured"


def test_a_task_s_trial_numbered_twice_is_refused(tmp_path: Path, made: StandInStore) -> None:
    # Two runs of one task, both trial 0, with records to match: equal trials per task, and
    # yet one trial counted twice.
    m = measured(made, "held_out", tmp_path / "a")
    records = [dict(r, trial=0) for r in _records(m)]
    runs = [(r, 0) for r in m.run_dirs]
    assert _refused(made, "held_out", _swap_records(_swap_runs(m, runs), records)) == (
        "trial_repeated"
    )


def test_trials_not_numbered_from_zero_are_refused(tmp_path: Path, made: StandInStore) -> None:
    m = measured(made, "held_out", tmp_path / "a")
    records = [dict(r, trial=r["trial"] + 1) for r in _records(m)]
    runs = [(r, 1 + i % 2) for i, r in enumerate(m.run_dirs)]
    assert _refused(made, "held_out", _swap_records(_swap_runs(m, runs), records)) == (
        "trials_not_numbered"
    )


def test_an_exposure_recorded_after_the_rule_and_before_the_count_is_seen(
    tmp_path: Path, made: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The register is re-read for exposure under its own lock, as the measurement is counted:
    # a hand mark made after the counting rule read it is not missed.
    import physgate.evaluation.tiers.measure as module

    m = measured(made, "held_out", tmp_path / "a")
    rule = module.census

    def then_marked(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        found = rule(*args, **kwargs)
        api("physgate.evaluation.tiers.exposure.mark_exposed")(
            made.store, "control", made.version, by="a person", reason="opened a task file"
        )
        return found

    monkeypatch.setattr(module, "census", then_marked)
    assert _refused(made, "held_out", m) == "version_exposed"
