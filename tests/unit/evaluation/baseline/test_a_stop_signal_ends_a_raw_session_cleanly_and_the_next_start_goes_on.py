"""A stop signal ends a raw trial's session cleanly, and the round's next start goes on.

``physgate baseline run`` told to stop (SIGTERM, an interrupt, a hang-up) while a raw session
runs ends that session as on any error: the arm stops it with its process group and removes its
credential, the round clears its place of the credential files and names the stop on a
``signalled`` line, and the command prints one line (``status: stopped``, the signal, the entry
and whether its session had started) and exits ``128 + N``, which a launch script tells from a
refusal (1). The next start goes on by the rules for a killed round: the session never ended, so
the entry runs again as if it had not, spending nothing, and nothing is left in the store.

The row runs the command's own entry point with the stand-in arm, which signals its own process
while its session would run. On code with no handler the row fails before it signals, so a
missing guard cannot end the test process.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import types
from dataclasses import dataclass
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
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import LEDGER, run_baseline
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.tiers.store import role_root, work_root
from physgate.evaluation.tiers.task import Task

SECRET = "not-a-token"


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@dataclass
class SignalledInItsSession(StandInArm):
    """A session that holds its credential's files when its process is told to stop."""

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        self.calls.append((task.id, cap, work))
        session = work / "session"
        (work / "worktree").mkdir(parents=True)
        (session / "config").mkdir(parents=True)
        (session / "state").mkdir(parents=True)
        (session / "config" / ".credentials.json").write_text(json.dumps({"token": SECRET}))
        (session / "state" / "key").write_text(SECRET)
        (session / "stdout.jsonl").write_text(json.dumps({"type": "user", "x": SECRET}) + "\n")
        handler = signal.getsignal(signal.SIGTERM)
        assert handler not in (signal.SIG_DFL, None), "no stop handler is installed"
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(10)
        pytest.fail("the stop signal did not end the session")


def test_a_stop_signal_ends_the_session_says_so_and_the_next_start_runs_it_again(
    tmp_path: Path,
    made: StandInStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install

    store = copied(made, tmp_path / "store")
    runs = run_set((harness_run(tmp_path / "runs", store.tasks["visible"][0], store), 0))
    (tmp_path / "runs.json").write_text(runs.model_dump_json())
    out = tmp_path / "round"
    real = runner.run_baseline
    arm = SignalledInItsSession()

    def stand_in(**given: Any) -> BaselineRecord:  # noqa: ANN401
        return real(**{**given, "setup_for": setup_for, "arm": arm, "sleep": lambda _s: None})

    module = types.ModuleType("physgate.evaluation.per_role.scorers.control")
    module.score = lambda _task, _answer: dict(SCORED)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(runner, "run_baseline", stand_in)
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    before = signal.getsignal(signal.SIGTERM)
    argv = ["baseline", "run", "--store", str(store.store), "--role", "control"]
    argv += ["--version", store.version, "--runs", str(tmp_path / "runs.json")]
    argv += ["--out", str(out), "--prices", PRICES]
    assert main(argv) == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == before, "the handler is put back"
    said = json.loads(capsys.readouterr().out)
    assert said == {
        "format": 1,
        "status": "stopped",
        "signal": "SIGTERM",
        "entry": 0,
        "session_started": True,
        "sessions_alive": 0,
    }
    lines = [json.loads(x) for x in (out / LEDGER).read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["round", "started", "signalled"]
    assert lines[-1] == {
        "kind": "signalled",
        "index": 0,
        "session": 1,
        "signal": "SIGTERM",
        "cleared": True,
    }
    (place,) = work_root(store.store, "control").iterdir()
    session = place / "place" / "session"
    assert not (session / "config" / ".credentials.json").exists()
    assert not (session / "state" / "key").exists()
    assert SECRET not in (session / "stdout.jsonl").read_text()
    # The next start goes on by a killed round's rules: run again, nothing spent, nothing left.
    again = StandInArm()
    record = run_baseline(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        setup_for=setup_for,
        score=lambda _t, _a: dict(SCORED),
        prices=load_price_sheet(PRICES),
        arm=again,
        sleep=lambda _s: None,
        resume=True,
    )
    assert (record.counts["visible"].passed, record.counts["visible"].unscored) == (1, 0)
    assert len(again.calls) == 1
    kinds = [json.loads(x)["kind"] for x in (out / LEDGER).read_text().splitlines()]
    assert kinds == ["round", "started", "signalled", "killed", "started", "moving", "recorded"]
    assert list(work_root(store.store, "control").iterdir()) == []
    assert list(role_root(store.store, "control").glob("*.working")) == []
