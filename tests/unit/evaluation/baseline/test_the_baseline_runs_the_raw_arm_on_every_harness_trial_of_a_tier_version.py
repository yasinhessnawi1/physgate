"""A baseline round: the raw arm on every trial a harness run set made on one tier version.

Every row runs on a stand-in store the fixture writes and stand-in harness runs laid out as
the loop leaves them; the raw arm is a stand-in that leaves what the real one leaves. No
session is started and no model is called.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    MODEL,
    PRICES,
    SCORED,
    StandInArm,
    StandInStore,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import (
    BASELINE_RECORD,
    TIERS_RECORD,
    BaselineRecord,
    TiersRecord,
    pin_set_sha256,
)
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    TRIALS,
    BaselineError,
    RunSet,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.manifest import read_version
from physgate.evaluation.tiers.store import role_root, version_dir, withheld_root
from physgate.evaluation.tiers.task import Task
from physgate.orchestrator.budget import REPAIR_BUDGET

API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}


def _score(task: Task, answer: Path) -> dict[str, Any]:
    assert answer.is_file()
    return dict(SCORED)


def _round(
    made: StandInStore,
    runs: RunSet,
    out: Path,
    arm: StandInArm,
    *,
    development: bool = False,
    slept: list[float] | None = None,
) -> BaselineRecord:
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
        sleep=(slept if slept is not None else []).append,
        development=development,
    )


def _every_task(made: StandInStore) -> list[Task]:
    return [task for tier in ("visible", "validation", "held_out") for task in made.tasks[tier]]


def _all_runs(tmp_path: Path, made: StandInStore) -> RunSet:
    runs = tmp_path / "runs"
    return run_set(*((harness_run(runs, task, made), 0) for task in _every_task(made)))


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


def test_a_round_runs_every_harness_trial_and_records_its_tier_version_and_pin_set(
    tmp_path: Path, store: StandInStore
) -> None:
    arm = StandInArm()
    out = tmp_path / "round"
    record = _round(store, _all_runs(tmp_path, store), out, arm)
    assert len(arm.calls) == 24
    # Each session was capped at its harness run's total, every class of token counted.
    assert {cap for _, cap, _ in arm.calls} == {1000}
    manifest = read_version(version_dir(store.store, "control", store.version))
    tiers = TiersRecord.model_validate_json((out / TIERS_RECORD).read_bytes())
    assert tiers.version == store.version == record.tiers.version
    assert (tiers.visible, tiers.validation, tiers.held_out) == (
        manifest.visible.sha256,
        manifest.validation.sha256,
        manifest.held_out.sha256,
    )
    written = BaselineRecord.model_validate_json((out / BASELINE_RECORD).read_bytes())
    assert written == record and not record.development
    for tier in ("visible", "validation", "held_out"):
        counts = record.counts[tier]
        assert (counts.trials, counts.passed, counts.excluded) == (8, 8, 0), tier
        assert (counts.cap, counts.spent) == (8000, 8 * 400), tier
    assert record.pin_set_sha256 == pin_set_sha256(record.pins)
    assert record.pins["model"] == MODEL and "brief_sha256" not in record.pins
    assert record.pins["bounds"]["session_max_turns"] == 150 * REPAIR_BUDGET


def test_a_protected_task_s_trial_lies_beneath_the_withheld_root_and_nowhere_else(
    tmp_path: Path, store: StandInStore
) -> None:
    """Its session's record, stream, answer, score and trial record: beneath the root only.

    Every run that names the store withholds the role's withheld root; a held-out answer or
    outcome beside it would be read by any session that found it.
    """
    out = tmp_path / "round"
    record = _round(store, _all_runs(tmp_path, store), out, StandInArm())
    beneath = withheld_root(store.store, "control") / BASELINE_DIR / record.id
    assert len(list((beneath).glob("*/raw.json"))) == 16
    assert len(list((beneath).glob("*/score.json"))) == 16
    assert len((beneath / TRIALS).read_text().splitlines()) == 16
    assert len((out / TRIALS).read_text().splitlines()) == 8
    assert not list(role_root(store.store, "control").glob("*.working"))
    protected = [t.id for t in store.tasks["validation"] + store.tasks["held_out"]]
    for path in (p for p in out.rglob("*") if p.is_file()):
        text = path.read_bytes()
        for task_id in protected:
            assert task_id.encode() not in text, f"a protected task is named in {path.name}"
    visible = store.tasks["visible"][0].id
    assert visible.encode() in (out / TRIALS).read_bytes()
    assert visible.encode() not in (out / BASELINE_RECORD).read_bytes()


def test_a_protected_trial_whose_session_failed_leaves_its_record_and_the_store_refuses(
    tmp_path: Path, store: StandInStore
) -> None:
    """A round stopped while a protected session's work is outside the store says so there."""
    task = store.tasks["held_out"][0]
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    with pytest.raises(RuntimeError, match="the session could not start"):
        _round(
            store,
            runs,
            tmp_path / "round",
            StandInArm(raises={1: RuntimeError("the session could not start")}),
        )
    assert len(list(role_root(store.store, "control").glob("*.working"))) == 1
    arm = StandInArm()
    with pytest.raises(BaselineError, match="nothing starts on it"):
        _round(store, runs, tmp_path / "again", arm)
    assert arm.calls == []


def _refused(store: StandInStore, runs: RunSet, out: Path, says: str, **how: Any) -> None:
    arm = StandInArm()
    with pytest.raises(BaselineError, match=says) as raised:
        _round(store, runs, out, arm, **how)
    assert arm.calls == [], "a session started before the round was refused"
    protected = [t.id for t in store.tasks["validation"] + store.tasks["held_out"]]
    told = f"{raised.value} {raised.value.context}"
    assert not any(task_id in told for task_id in protected)


def test_a_run_given_no_task_of_the_version_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    task = store.tasks["visible"][0].model_copy(update={"brief": "Another brief entirely."})
    runs = run_set((harness_run(tmp_path / "runs", task, store), 0))
    _refused(store, runs, tmp_path / "round", "no task of this version")


def test_a_trial_listed_twice_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    _refused(store, run_set((run, 0), (run, 0)), tmp_path / "round", "listed twice")


def test_a_run_whose_token_account_gives_no_cap_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store, ended=False)
    _refused(store, run_set((run, 0)), tmp_path / "round", "gives no cap")


@pytest.mark.parametrize(
    "changes",
    [
        {"reportable": False},
        {
            "reportable": False,
            "harness": {"commit": "c" * 40, "clean": False, "uncommitted_sha256": "d" * 64},
        },
    ],
    ids=["not reportable", "dirty checkout"],
)
def test_a_development_run_is_refused_but_to_a_development_round(
    tmp_path: Path, store: StandInStore, changes: dict[str, Any]
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store, **changes)
    _refused(store, run_set((run, 0)), tmp_path / "round", "development round")
    record = _round(store, run_set((run, 0)), tmp_path / "dev", StandInArm(), development=True)
    assert record.development and record.counts["visible"].passed == 1


def test_a_round_into_a_directory_that_exists_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    out = tmp_path / "round"
    out.mkdir()
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    _refused(store, run_set((run, 0)), out, "directory of its own")


def test_a_version_of_the_store_that_changed_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    directory = version_dir(store.store, "control", store.version)
    task_json = next((directory / "visible").glob("*/task.json"))
    task_json.write_text(task_json.read_text().replace("Answer here.", "Answer there."))
    arm = StandInArm()
    # A version that is not what its manifest names is read as work left in the store, before
    # the version is read for its tasks; either refuses the round.
    with pytest.raises(PerRoleError, match="nothing starts on it|not the bytes its manifest"):
        _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert arm.calls == []


def test_a_pair_that_differs_in_more_than_the_harness_stops_the_round_naming_the_field(
    tmp_path: Path, store: StandInStore
) -> None:
    """An endpoint that answered as another model: the field is named, the task is not."""
    task = store.tasks["held_out"][0]
    run = harness_run(tmp_path / "runs", task, store)
    with pytest.raises(BaselineError, match="more than the harness: answered_by") as raised:
        _round(
            store,
            run_set((run, 0)),
            tmp_path / "round",
            StandInArm(answered={1: "claude-sonnet-5"}),
        )
    assert task.id not in f"{raised.value} {raised.value.context}"


def test_trials_under_different_pins_are_no_one_baseline(
    tmp_path: Path, store: StandInStore
) -> None:
    """Each pair is fair; the two harness runs were not run alike, so no one pin set holds."""
    one = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    two = harness_run(tmp_path / "runs", store.tasks["visible"][1], store, effort="low")
    with pytest.raises(BaselineError, match="different pins"):
        _round(store, run_set((one, 0), (two, 0)), tmp_path / "round", StandInArm())


def test_a_trial_the_machine_ended_runs_once_more_after_the_run_s_own_delay(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    slept: list[float] = []
    arm = StandInArm(ended={1: API_ERROR})
    record = _round(store, run_set((run, 0)), tmp_path / "round", arm, slept=slept)
    assert len(arm.calls) == 2 and slept == [60.0]
    assert record.counts["visible"].passed == 1


def test_a_trial_the_machine_ended_twice_is_unscored(tmp_path: Path, store: StandInStore) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    arm = StandInArm(ended={1: API_ERROR, 2: API_ERROR})
    record = _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert len(arm.calls) == 2
    counts = record.counts["held_out"]
    assert (counts.unscored, counts.passed, counts.failed) == (1, 0, 0)
    assert not list(role_root(store.store, "control").glob("*.working"))


def test_a_trial_whose_stream_showed_its_canary_is_counted_excluded(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    record = _round(store, run_set((run, 0)), tmp_path / "round", StandInArm(seen={1}))
    counts = record.counts["held_out"]
    assert (counts.excluded, counts.passed) == (1, 0)


def test_a_second_round_writes_a_record_of_its_own_and_keeps_the_first(
    tmp_path: Path, store: StandInStore
) -> None:
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    first = _round(store, run_set((run, 0)), tmp_path / "one", StandInArm())
    kept = (tmp_path / "one" / BASELINE_RECORD).read_bytes()
    second = _round(store, run_set((run, 0)), tmp_path / "two", StandInArm())
    assert first.id != second.id
    assert (tmp_path / "one" / BASELINE_RECORD).read_bytes() == kept
    digest = hashlib.sha256(kept).hexdigest()
    assert digest == hashlib.sha256((tmp_path / "one" / BASELINE_RECORD).read_bytes()).hexdigest()


def test_the_command_is_registered_with_the_physgate_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from physgate.cli import main

    with pytest.raises(SystemExit) as done:
        main(["baseline", "run", "--help"])
    assert done.value.code == 0
    assert "--runs" in capsys.readouterr().out


def test_a_round_s_record_is_counts_and_digests_only(tmp_path: Path, store: StandInStore) -> None:
    """No brief, no answer contract, no canary in the record a person reads."""
    run = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    _round(store, run_set((run, 0)), tmp_path / "round", StandInArm())
    text = (tmp_path / "round" / BASELINE_RECORD).read_text()
    assert not any(canary in text for canary in store.canaries)
    assert store.tasks["held_out"][0].brief not in text
    assert set(json.loads(text)["pins"]) == set(json.loads(text)["pins"]) - {"answer"}


def test_a_record_already_there_is_never_written_over(tmp_path: Path) -> None:
    from physgate.evaluation.baseline.record import BaselineRecordError, write_new

    path = tmp_path / "evaluation" / "tiers.json"
    write_new(path, b"first\n")
    with pytest.raises(BaselineRecordError, match="written once and kept"):
        write_new(path, b"second\n")
    assert path.read_bytes() == b"first\n"


def test_a_version_two_of_whose_tasks_share_a_brief_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    """A run's task is found by its brief, so two tasks with one brief leave it unknown."""
    directory = version_dir(store.store, "control", store.version)
    one, two = sorted((directory / "visible").glob("*/task.json"))[:2]
    first = json.loads(one.read_text())
    second = json.loads(two.read_text())
    second["brief"] = first["brief"]
    two.write_text(json.dumps(second))
    # The manifest names the old bytes; the version's own check is set aside here, so the
    # row reaches the brief rule behind it.
    from physgate.evaluation.baseline import runner

    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "read_version", lambda _d: None)
        patch.setattr(runner, "leftover_refusal", lambda _s: None)
        with pytest.raises(BaselineError, match="share a brief"):
            _round(store, run_set((run, 0)), tmp_path / "round", arm)
    assert arm.calls == []


def test_a_run_recorded_against_another_endpoint_is_refused_before_any_credential(
    tmp_path: Path, store: StandInStore
) -> None:
    """The record's endpoint is compared with the operator's, never taken as a destination.

    A record that names another host, by mistake or by a hand that edited it, would otherwise
    have the operator's credential sent there.
    """
    run = harness_run(
        tmp_path / "runs", store.tasks["visible"][0], store, endpoint="http://127.0.0.1:8080"
    )
    asked: list[str] = []

    def setup(config: Any, role: Any) -> Any:  # noqa: ANN401 - the runner's setup hook
        asked.append(config.endpoint)
        return setup_for(config, role)

    arm = StandInArm()
    with pytest.raises(BaselineError, match="endpoint"):
        run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=run_set((run, 0)),
            out=tmp_path / "round",
            setup_for=setup,
            score=_score,
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=_no_sleep,
        )
    assert asked == [] and arm.calls == []


def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    "omit", ["withheld", "work", "validation", "held_out"], ids=lambda o: f"no {o} root"
)
def test_a_run_that_does_not_withhold_the_store_s_protected_places_is_refused(
    tmp_path: Path, store: StandInStore, omit: str
) -> None:
    """The raw session withholds what the harness run withheld: so the run must withhold it all."""
    kept = [root for root in store.held_out if not root.endswith(f"/{omit}")]
    assert len(kept) == len(store.held_out) - 1
    run = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][0],
        store,
        held_out=kept,
        held_out_sha256=[_digest_of(root) for root in kept],
    )
    _refused(store, run_set((run, 0)), tmp_path / "round", "withhold")


@pytest.mark.parametrize("tier", ["validation", "held_out"])
def test_a_run_that_did_not_look_for_a_protected_canary_of_the_version_is_refused(
    tmp_path: Path, store: StandInStore, tier: str
) -> None:
    dropped = store.tasks[tier][0].canary
    canaries = [c for c in store.canaries if c != dropped]
    run = harness_run(
        tmp_path / "runs", store.tasks["visible"][0], store, held_out_canaries=canaries
    )
    _refused(store, run_set((run, 0)), tmp_path / "round", "canar")


def _digest_of(root: str) -> str:
    from physgate.evaluation.tiers.heldout import tier_digest

    return tier_digest(Path(root))
