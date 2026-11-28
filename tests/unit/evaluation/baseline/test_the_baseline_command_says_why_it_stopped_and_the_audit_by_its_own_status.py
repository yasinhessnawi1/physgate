"""The baseline command says why it stopped on one line, and the audit says what it found by status.

``physgate baseline run`` exits 1 when the round is refused or stopped and prints one JSON line:
why, the entry by its place in the run set, and whether a session of that entry had started (a
refusal before any session spends nothing; a stop after one is never run again in its round). A
round that has ended, started again, prints its record and exits 0, as the harness command does.

``physgate baseline audit`` exits 0 when nothing differs, 1 when a record differs, and 3 when the
audit cannot be made, whatever stops it; 2 is the command line refused. It audits the harness
arm's records without a baseline round when it is given none.

Every row runs the command's own entry point on the stand-in store; the scorer, whose libraries
are the evaluation environment's, is a stand-in module.
"""

from __future__ import annotations

import json
import sys
import types
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

from physgate.cli import main
from physgate.evaluation.baseline.audit import AuditError, HarnessCell, audit_harness
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import WORK, BaselineError, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


@pytest.fixture
def scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("physgate.evaluation.per_role.scorers.control")
    module.score = lambda _task, _answer: dict(SCORED)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)


def _run_argv(tmp_path: Path) -> list[str]:
    (tmp_path / "runs.json").write_text(
        json.dumps({"format": 1, "trials": [{"run_dir": "/r", "trial": 0}]})
    )
    argv = ["baseline", "run", "--store", str(tmp_path), "--role", "control", "--version", "v"]
    return [
        *argv,
        "--runs",
        str(tmp_path / "runs.json"),
        "--out",
        str(tmp_path / "o"),
        "--prices",
        PRICES,
    ]


@pytest.mark.parametrize(
    ("context", "said"),
    [
        (
            {"refused_because": "pair_differs", "entry": "2", "session_started": "true"},
            {"refused_because": "pair_differs", "entry": 2, "session_started": True},
        ),
        (
            {"refused_because": "work_left"},
            {"refused_because": "work_left", "entry": None, "session_started": False},
        ),
    ],
    ids=["a stop after a session", "a refusal before any"],
)
def test_a_refused_or_stopped_round_prints_one_line_saying_why_and_whether_a_session_ran(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scorer: None,
    context: dict[str, str],
    said: dict[str, Any],
) -> None:
    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install

    def refuses(**_given: Any) -> None:  # noqa: ANN401
        raise BaselineError("words for a person", **context)

    monkeypatch.setattr(runner, "run_baseline", refuses)
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    assert main(_run_argv(tmp_path)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"format": 1, "status": "refused", **said}
    assert "words for a person" in captured.err


def test_a_round_that_ended_started_again_prints_its_record_and_exits_0(
    tmp_path: Path,
    store: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scorer: None,
) -> None:
    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install

    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    out = tmp_path / "o"
    record = run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=lambda _t, _a: dict(SCORED),
        prices=load_price_sheet(PRICES),
        arm=StandInArm(),
    )
    real = runner.run_baseline

    def again(**given: Any) -> BaselineRecord:  # noqa: ANN401
        assert given["resume"] is True
        return real(**{**given, "setup_for": setup_for, "arm": StandInArm()})

    monkeypatch.setattr(runner, "run_baseline", again)
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    (tmp_path / "runs.json").write_text(runs.model_dump_json())
    argv = ["baseline", "run", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--runs", str(tmp_path / "runs.json"), "--out", str(out)]
    argv += ["--prices", PRICES, "--resume"]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out) == record.model_dump(mode="json")


# -- the audit ------------------------------------------------------------------------------------


def _audit_argv(store: StandInStore, runs: Path | None, out: Path | None, *more: str) -> list[str]:
    argv = ["baseline", "audit", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--prices", PRICES]
    if runs is not None:
        argv += ["--runs", str(runs)]
    if out is not None:
        argv += ["--out", str(out)]
    return [*argv, *more]


def test_the_audit_exits_0_when_nothing_differs_1_when_a_record_does_and_3_when_it_cannot_be_made(
    tmp_path: Path, store: StandInStore, capsys: pytest.CaptureFixture[str], scorer: None
) -> None:
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    (tmp_path / "runs.json").write_text(runs.model_dump_json())
    out = tmp_path / "round"
    run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=lambda _t, _a: dict(SCORED),
        prices=load_price_sheet(PRICES),
        arm=StandInArm(),
    )
    assert main(_audit_argv(store, tmp_path / "runs.json", out)) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 0
    (out / WORK / "0000-1" / "harness" / "raw.json").write_text("{not json")
    assert main(_audit_argv(store, tmp_path / "runs.json", out)) == 1
    found = json.loads(capsys.readouterr().out)
    assert {"kind": "unrederivable", "index": 0, "field": None} in found["differences"][
        "raw.visible"
    ]
    # A round the audit cannot read, whatever stops it, has the status of its own.
    assert main(_audit_argv(store, tmp_path / "runs.json", tmp_path / "nowhere")) == 3
    assert json.loads(capsys.readouterr().out)["refused_because"] == "ledger_unread"
    assert main(_audit_argv(store, None, None)) == 3
    assert json.loads(capsys.readouterr().out)["refused_because"] == "nothing_to_audit"


def test_a_harness_run_of_another_tier_than_its_cell_s_refuses_the_audit(
    tmp_path: Path, store: StandInStore
) -> None:
    """A cell is one tier's trials: a run of another tier in it is a cell that is not one.

    Refused before anything is derived, so a run that would derive whole is refused all the same.
    """
    held_out = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    (tmp_path / "trials.jsonl").write_text("")
    with pytest.raises(AuditError) as refused:
        audit_harness(
            store=store.store,
            role="control",
            version=store.version,
            cells=[HarnessCell("visible", run_set((held_out, 0)), tmp_path / "trials.jsonl")],
            prices=load_price_sheet(PRICES),
            score=lambda _t, _a: dict(SCORED),
            scratch=tmp_path / "scratch",
        )
    assert refused.value.context["refused_because"] == "tier"
    assert refused.value.context["index"] == "0"


def test_the_harness_arm_s_records_are_audited_with_no_baseline_round(
    tmp_path: Path, store: StandInStore, capsys: pytest.CaptureFixture[str], scorer: None
) -> None:
    visible = harness_run(tmp_path / "runs", store.tasks["visible"][0], store)
    (tmp_path / "cell.json").write_text(run_set((visible, 0)).model_dump_json())
    (tmp_path / "trials.jsonl").write_text("")
    argv = _audit_argv(store, None, None, "--harness", "visible", str(tmp_path / "cell.json"))
    assert main([*argv, str(tmp_path / "trials.jsonl")]) == 1
    found = json.loads(capsys.readouterr().out)
    assert found["differences"] == {
        "harness.visible": [{"kind": "unrederivable", "index": 0, "field": None}]
    }
    # A run of another tier refuses the audit, with its own status.
    held_out = harness_run(tmp_path / "runs", store.tasks["held_out"][0], store)
    (tmp_path / "other.json").write_text(run_set((held_out, 0)).model_dump_json())
    argv = _audit_argv(store, None, None, "--harness", "visible", str(tmp_path / "other.json"))
    assert main([*argv, str(tmp_path / "trials.jsonl")]) == 3
    assert json.loads(capsys.readouterr().out)["refused_because"] == "tier"


def test_a_visible_trial_s_error_after_its_session_started_says_its_entry_and_that_it_ran(
    tmp_path: Path,
    store: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scorer: None,
) -> None:
    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install

    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    (tmp_path / "runs.json").write_text(runs.model_dump_json())
    real = runner.run_baseline
    arm = StandInArm(raises={1: RuntimeError("the tools changed while it ran")})

    def stand_in(**given: Any) -> BaselineRecord:  # noqa: ANN401
        return real(**{**given, "setup_for": setup_for, "arm": arm})

    monkeypatch.setattr(runner, "run_baseline", stand_in)
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    argv = ["baseline", "run", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--runs", str(tmp_path / "runs.json")]
    argv += ["--out", str(tmp_path / "o"), "--prices", PRICES]
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().out) == {
        "format": 1,
        "status": "refused",
        "refused_because": "error",
        "entry": 0,
        "session_started": True,
    }
