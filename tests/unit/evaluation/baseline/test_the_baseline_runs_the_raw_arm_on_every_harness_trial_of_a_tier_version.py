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
from physgate.evaluation.tiers.task import Task, parse_task
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
    assert record.tiers is not None and record.external is None
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
    # Said by its tier and the error's kind: an arm's error may name the task.
    with pytest.raises(BaselineError, match=r"held_out trial stopped on an error \(RuntimeError\)"):
        _round(
            store,
            runs,
            tmp_path / "round",
            StandInArm(raises={1: RuntimeError("the session could not start")}),
        )
    assert len(list(role_root(store.store, "control").glob("*.working"))) == 1
    arm = StandInArm()
    with pytest.raises(BaselineError, match="nothing starts on it") as refused:
        _round(store, runs, tmp_path / "again", arm)
    assert refused.value.context.get("refused_because") == "work_left"
    assert arm.calls == []


def _refused(
    store: StandInStore,
    runs: RunSet,
    out: Path,
    says: str,
    because: dict[str, str] | None = None,
    **how: Any,  # noqa: ANN401
) -> None:
    """The round refused before any session, saying ``says`` with ``because`` in its context."""
    arm = StandInArm()
    with pytest.raises(BaselineError, match=says) as raised:
        _round(store, runs, out, arm, **how)
    assert arm.calls == [], "a session started before the round was refused"
    for key, value in (because or {}).items():
        assert raised.value.context.get(key) == value, raised.value.context
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


@pytest.mark.parametrize(
    "development", [False, True], ids=["reportable round", "development round"]
)
def test_an_ablation_run_is_never_taken_as_a_baseline_trial(
    tmp_path: Path, store: StandInStore, development: bool
) -> None:
    """An ablation run is refused before any session, in a development round too.

    It is never reportable, which a development round forgives; its own kind is not forgiven,
    since its numbers are of a harness with a part taken away, and no baseline is held to it.
    """
    run = harness_run(
        tmp_path / "runs", store.tasks["visible"][0], store, ablation=True, reportable=False
    )
    _refused(store, run_set((run, 0)), tmp_path / "round", "ablation run", development=development)


def test_trials_of_runs_on_different_binary_builds_are_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    """Master's comparison rule: the binary's bytes must match where both runs recorded them."""
    one = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][0],
        store,
        binary={"sha256": "d" * 64, "platform": "linux-x64"},
    )
    two = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][1],
        store,
        binary={"sha256": "e" * 64, "platform": "linux-x64"},
    )
    _refused(store, run_set((one, 0), (two, 0)), tmp_path / "round", "binary", {"entry": "1"})


def test_a_run_that_recorded_no_binary_is_not_held_against_one_that_did_and_accounts_are_not(
    tmp_path: Path, store: StandInStore
) -> None:
    """Only where both recorded it is the binary compared; the account is never compared."""
    one = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][0],
        store,
        binary={"sha256": "d" * 64, "platform": "linux-x64"},
        account={"name": "run-seat-1", "token_sha256_prefix": "a" * 12},
    )
    two = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][1],
        store,
        binary=None,
        account={"name": "run-seat-2", "token_sha256_prefix": "b" * 12},
    )
    record = _round(store, run_set((one, 0), (two, 0)), tmp_path / "round", StandInArm())
    assert record.counts["visible"].trials == 2


def test_a_round_into_a_directory_that_exists_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    out = tmp_path / "round"
    out.mkdir()
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()
    outcome = _try(lambda: _round(store, run_set((run, 0)), out, arm))
    assert isinstance(outcome, BaselineError), outcome
    assert "the round's directory exists" in str(outcome) and arm.calls == []
    assert list(out.iterdir()) == [], "the directory that was there was written into"


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
        outcome = _try(lambda: _round(store, run_set((run, 0)), tmp_path / "round", arm))
    assert isinstance(outcome, BaselineError), outcome
    assert "two tasks of the version share a brief" in str(outcome), outcome
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


def _try(call: Any) -> Any:  # noqa: ANN401 - what the call returned, or raised
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the row asserts on what it was
        return exc


def test_a_version_whose_provenance_is_not_its_manifest_s_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    """A version is read as its manifest says it is, or not at all (``read_version``).

    The store's scan for leftovers refuses a changed version first; it is set aside here, as
    in the shared-brief row, so the row reaches the version's own check behind it: the
    provenance record, changed, no longer has the digest the manifest names.
    """
    from physgate.evaluation.baseline import runner

    directory = version_dir(store.store, "control", store.version)
    provenance = directory / "provenance.json"
    provenance.write_bytes(provenance.read_bytes().replace(b"s-1", b"s-2"))
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "leftover_refusal", lambda _s: None)
        outcome = _try(lambda: _round(store, run_set((run, 0)), tmp_path / "round", arm))
    assert isinstance(outcome, PerRoleError), outcome
    assert "provenance" in str(outcome) and arm.calls == []


def test_a_run_withholding_the_store_in_another_case_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    """Every place is named as the filesystem spells it.

    Another case reaches the same files where case is ignored, but not every layer of the
    protection is shown to refuse it.
    """
    other = store.store.parent / store.store.name.upper()
    if not other.exists():
        pytest.skip("this filesystem tells cases apart, so another case names no place")
    spelt = [h.replace(str(store.store), str(other)) for h in store.held_out]
    run = harness_run(
        tmp_path / "runs",
        store.tasks["visible"][0],
        store,
        held_out=spelt,
        held_out_sha256=[_digest_of(root) for root in spelt],
    )
    _refused(store, run_set((run, 0)), tmp_path / "round", "spelt as the filesystem")


def test_a_run_the_spelling_check_refuses_is_refused_before_any_session_on_any_filesystem(
    tmp_path: Path, store: StandInStore
) -> None:
    """The round asks the store's spelling check of every run, where cases are told apart too.

    The check itself is shown elsewhere; here it is made to refuse, so the row holds on a
    filesystem where no other case of the store exists to name.
    """
    from physgate.evaluation.baseline import runner

    asked: list[tuple[str, ...]] = []

    def refusing(held_out: tuple[str, ...], **_also: Any) -> tuple[str, str]:  # noqa: ANN401
        asked.append(held_out)
        return "held_out_not_spelt_as_on_disk", "not spelt as the filesystem spells them"

    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "spelling_refusal", refusing)
        outcome = _try(lambda: _round(store, run_set((run, 0)), tmp_path / "round", arm))
    assert isinstance(outcome, BaselineError), outcome
    assert outcome.context.get("refused_because") == "held_out_not_spelt_as_on_disk"
    assert asked == [tuple(store.held_out)] and arm.calls == []


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
    reason = {
        "withheld": "withheld_root_not_named",
        "work": "work_root_not_named",
        "validation": "protected_tier_not_named",
        "held_out": "protected_tier_not_named",
    }[omit]
    (dropped,) = set(store.held_out) - set(kept)
    # The one place the run left open, named alone: a refusal of another place says another.
    named = f"({Path(dropped).resolve()})"
    _refused(
        store,
        run_set((run, 0)),
        tmp_path / "round",
        "does not withhold the store as every run on it must",
        because={"refused_because": reason},
    )
    with pytest.raises(BaselineError) as raised:
        _round(store, run_set((run, 0)), tmp_path / "again", StandInArm())
    assert named in str(raised.value), str(raised.value)


@pytest.mark.parametrize("tier", ["validation", "held_out"])
def test_a_run_that_did_not_look_for_a_protected_canary_of_the_version_is_refused(
    tmp_path: Path, store: StandInStore, tier: str
) -> None:
    dropped = store.tasks[tier][0].canary
    canaries = [c for c in store.canaries if c != dropped]
    run = harness_run(
        tmp_path / "runs", store.tasks["visible"][0], store, held_out_canaries=canaries
    )
    _refused(
        store,
        run_set((run, 0)),
        tmp_path / "round",
        "did not look for every canary of the version's protected tasks",
        because={"missing": "1"},
    )


def _another_role_s_places(made: StandInStore) -> list[str]:
    """The firmware role's places beside the store's own role, each made, empty.

    Its withheld and work roots and the two protected tiers of one version; the store's scan
    for leftovers finds nothing out of place in them.
    """
    root = made.store / "firmware"
    places = [root / "withheld", root / "work"]
    places += [root / made.version / tier for tier in ("validation", "held_out")]
    for place in places:
        place.mkdir(parents=True, exist_ok=True)
    return [str(place) for place in places]


def _source(tmp_path: Path, made: StandInStore, source: str) -> tuple[Task, dict[str, Any]]:
    """A visible task of the version, or the one task of an external set, and how to name it."""
    if source == "version":
        return made.tasks["visible"][0], {"version": made.version}
    from task_fixtures import external_task, write_task_dir

    raw = external_task(brief="A published plant to stabilise.")
    write_task_dir(tmp_path / "set" / raw["id"], raw, {})
    return parse_task(json.dumps(raw).encode()), {"external": tmp_path / "set"}


def _withholding(
    root: Path, task: Task, made: StandInStore, places: list[str], **changes: Any
) -> Path:  # noqa: ANN401
    """A harness run withholding the store's own places and ``places`` as well."""
    held_out = [*made.held_out, *places]
    return harness_run(
        root,
        task,
        made,
        held_out=held_out,
        held_out_sha256=[_digest_of(place) for place in held_out],
        **changes,
    )


@pytest.mark.parametrize("source", ["version", "external"])
def test_a_run_that_did_not_look_for_another_role_s_canary_is_refused(
    tmp_path: Path, store: StandInStore, source: str
) -> None:
    """A round looks for the canaries of every role's root in the store, its own role's or not.

    Another role's list lies in a protected tier of its own root, which the run withholds;
    the harness run looked for the version's canaries alone. On an external set too, which
    has no version of its own. The same run looking for that canary as well is taken, so the
    refusal is the canary's and no other.
    """
    another = "ab" * 16
    places = _another_role_s_places(store)
    (Path(places[-1]) / "canaries.json").write_text(json.dumps([another]))
    task, how = _source(tmp_path, store, source)
    run = _withholding(tmp_path / "runs", task, store, places)
    arm = StandInArm()
    outcome = _try(lambda: _round_from(store, run_set((run, 0)), tmp_path / "round", arm, how))
    assert isinstance(outcome, BaselineError), outcome
    assert "did not look for every canary" in str(outcome) and arm.calls == []
    looking = _withholding(
        tmp_path / "looking", task, store, places, held_out_canaries=[*store.canaries, another]
    )
    taken = _try(lambda: _round_from(store, run_set((looking, 0)), tmp_path / "taken", arm, how))
    assert isinstance(taken, BaselineRecord), taken


@pytest.mark.parametrize("source", ["version", "external"])
def test_a_run_not_withholding_another_role_s_root_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore, source: str
) -> None:
    """Every run on the store withholds every role's root in it, not its own role's alone.

    What a run looks for is every role's canaries, so what it withholds is the same scope:
    another role's withheld and work roots and every version's protected tiers there. A run
    withholding its own role's places alone is refused before any session; the same run
    withholding the other role's as well is taken.
    """
    places = _another_role_s_places(store)
    task, how = _source(tmp_path, store, source)
    run = harness_run(tmp_path / "runs", task, store)
    arm = StandInArm()
    outcome = _try(lambda: _round_from(store, run_set((run, 0)), tmp_path / "round", arm, how))
    assert isinstance(outcome, BaselineError), outcome
    assert outcome.context.get("refused_because") == "withheld_root_not_named", outcome.context
    assert arm.calls == []
    whole = _withholding(tmp_path / "whole", task, store, places)
    taken = _try(lambda: _round_from(store, run_set((whole, 0)), tmp_path / "taken", arm, how))
    assert isinstance(taken, BaselineRecord), taken


def test_a_store_whose_other_role_s_list_cannot_be_taken_whole_is_refused_before_any_session(
    tmp_path: Path, store: StandInStore
) -> None:
    """A list that is not a list of canaries is never read as naming none, in any role's root.

    The refusal names the list's tier and its reason, never a task.
    """
    listed = store.store / "firmware" / store.version / "held_out"
    listed.mkdir(parents=True)
    (listed / "canaries.json").write_text(json.dumps("not a list"))
    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    arm = StandInArm()
    outcome = _try(lambda: _round(store, run_set((run, 0)), tmp_path / "round", arm))
    assert isinstance(outcome, BaselineError), outcome
    assert outcome.context.get("refused_because") == "canary_list_unparsed", outcome.context
    assert arm.calls == []


def test_protected_trials_each_in_a_place_of_its_own_run_under_one_pin_set(
    tmp_path: Path, store: StandInStore
) -> None:
    """Each protected trial's directory is its own; the round's pin set holds no trial's place."""
    tasks = store.tasks["validation"][:1] + store.tasks["held_out"][:1]
    runs = run_set(*((harness_run(tmp_path / "runs", t, store), 0) for t in tasks))
    arm = StandInArm()
    outcome = _try(lambda: _round(store, runs, tmp_path / "round", arm))
    assert isinstance(outcome, BaselineRecord), outcome
    assert "held_out_carved" not in outcome.pins
    assert len({work for _, _, work in arm.calls}) == 2


def test_a_store_whose_root_cannot_be_looked_at_for_canaries_is_refused_as_the_runner_s_own(
    tmp_path: Path, store: StandInStore
) -> None:
    """A root whose own ``stat`` is refused stops the round with the runner's refusal.

    Fail-closed either way; said as the runner's own, it names no more than the store's place.
    """
    from physgate.evaluation.baseline import runner

    run = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)

    def unreadable(where: Path) -> list[str]:
        raise PermissionError(13, "Permission denied", str(where))

    arm = StandInArm()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "store_canaries", unreadable)
        outcome = _try(lambda: _round(store, run_set((run, 0)), tmp_path / "round", arm))
    assert isinstance(outcome, BaselineError), outcome
    assert "the store's canaries cannot all be read" in str(outcome), outcome
    assert arm.calls == []


def _round_from(
    made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, how: dict[str, Any]
) -> BaselineRecord:
    return run_baseline(
        store=made.store,
        role="control",
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=_score,
        prices=load_price_sheet(PRICES),
        arm=arm,
        sleep=_no_sleep,
        **how,
    )


def _digest_of(root: str) -> str:
    from physgate.evaluation.tiers.heldout import tier_digest

    return tier_digest(Path(root))
