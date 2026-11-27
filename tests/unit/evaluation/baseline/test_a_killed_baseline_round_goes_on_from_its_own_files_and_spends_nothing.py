"""A baseline round killed at any step goes on from its own files, however often, spending nothing.

The round's process can be killed while a raw session runs, between a session's end and its
record, between a wait's line and the move it names, between a trial's line and its ledger line,
or while a ledger line is written. Each step's line is written before the step, so the next
start reads where the entry stands from the round's own files: a session whose place holds no
record of the raw arm's was killed before it ended; its place is cleared of the credential,
kept where a finished trial lies, named on a ``killed`` line, and the entry runs again as if it
had not run, spending neither its one more go nor anything else. A session whose record is there
is finished from its files and never run again. A stop for a cause (a pair that differs, an
error after the session started) is named on a ``stopped`` line and is never run again in its
round. A refusal before the session's ``started`` line writes nothing.

Every row runs on the stand-in store and raw arm the baseline's other rows use. A kill is a
``BaseException`` raised at the step a row names, as the process's end would leave it: nothing
after that step runs. The session a kill leaves is laid out as the raw arm lays one out before it
cleans up: its credential's files, the sentinel's record of the protected paths, the process
facts of a process that has ended, and a stream cut short.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from baseline_fixtures import (
    CHECKOUT,
    PRICES,
    RESET_EPOCH,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline import runner
from physgate.evaluation.baseline.audit import audit_raw
from physgate.evaluation.baseline.record import BaselineRecord
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    LEDGER,
    TRIALS,
    WORK,
    BaselineError,
    Ledger,
    RoundWaits,
    RunSet,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.arms.raw import RawSetup
from physgate.evaluation.tiers.store import role_root, withheld_root, work_root
from physgate.evaluation.tiers.task import Role, Task
from physgate.orchestrator.credentials import Credential, fingerprint
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import HarnessState, RunConfig

API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
BEFORE = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
AFTER = datetime(2026, 11, 13, 12, 21, tzinfo=UTC)
SECRET = "not-a-token"


class Killed(BaseException):  # noqa: N818 - stands for the process being killed
    """The round's process killed at the point a row names."""


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


def _outcome(
    made: StandInStore,
    runs: RunSet,
    out: Path,
    arm: Callable[..., dict[str, Any]],
    *,
    at: datetime = BEFORE,
    resume: bool = False,
    slept: list[float] | None = None,
    setup: Callable[[RunConfig, Role], RawSetup] = setup_for,
    development: bool = False,
) -> BaselineRecord | Exception:
    try:
        return run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=setup,
            score=lambda _t, _a: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=(slept if slept is not None else []).append,
            resume=resume,
            development=development,
            now=lambda: at,
        )
    except Exception as exc:  # noqa: BLE001 - asserted by the caller
        return exc


def _done(made: StandInStore, runs: RunSet, out: Path, arm: Any, **how: Any) -> BaselineRecord:  # noqa: ANN401
    outcome = _outcome(made, runs, out, arm, **how)
    assert isinstance(outcome, BaselineRecord), f"the round did not end: {outcome!r}"
    return outcome


def _refused(made: StandInStore, runs: RunSet, out: Path, arm: Any, **how: Any) -> BaselineError:  # noqa: ANN401
    outcome = _outcome(made, runs, out, arm, **how)
    assert isinstance(outcome, BaselineError), f"the round was not refused: {outcome!r}"
    return outcome


def _ledger(out: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (out / LEDGER).read_text().splitlines()]


def _kinds(out: Path) -> list[str]:
    return [line["kind"] for line in _ledger(out)]


def _one(tmp_path: Path, made: StandInStore, tier: str = "visible") -> RunSet:
    return run_set((harness_run(tmp_path / "runs", made.tasks[tier][0], made), 0))


def _left_in_the_store(made: StandInStore) -> list[str]:
    """Whatever a round left in the role's work root and as records of work in its root."""
    works = work_root(made.store, "control")
    left = sorted(p.name for p in works.iterdir()) if works.is_dir() else []
    return left + sorted(p.name for p in role_root(made.store, "control").glob("*.working"))


@dataclass
class KilledInTheSession(StandInArm):
    """The raw arm killed while its session runs: what its place holds then, and no record."""

    kill_at: int = 1
    #: What the session's stream holds when the kill comes.
    said: str = "tool output"

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        if len(self.calls) + 1 != self.kill_at:
            return super().__call__(task, setup, work, cap=cap, harness=harness)
        self.calls.append((task.id, cap, work))
        session = work / "session"
        (work / "worktree").mkdir(parents=True)
        (session / "config").mkdir(parents=True)
        (session / "state" / "sessions" / "s-1" / "sentinel").mkdir(parents=True)
        (session / "config" / ".credentials.json").write_text(json.dumps({"token": SECRET}))
        (session / "state" / "key").write_text(SECRET)
        sentinel = session / "state" / "sessions" / "s-1" / "sentinel" / "baseline.json"
        sentinel.write_text(json.dumps({"paths": ["a protected task's directory"]}))
        # A process that has ended: no such pid runs, and no process runs in its group.
        facts = {"pid": 2**22 + 7, "started": "Thu Jan  1 00:00:00 1970", "session_id": "s-1"}
        (session / "process.json").write_text(json.dumps(facts))
        line = {"type": "user", "message": {"content": f"{self.said} {SECRET}"}}
        (session / "stdout.jsonl").write_text(json.dumps(line) + "\n" + '{"type": "assi')
        raise Killed


@dataclass
class KilledAfterItsRecord(StandInArm):
    """The raw arm's session ended and wrote its record; the kill comes before the next step."""

    def __call__(
        self, task: Task, setup: RawSetup, work: Path, *, cap: int, harness: Path | None = None
    ) -> dict[str, Any]:
        super().__call__(task, setup, work, cap=cap, harness=harness)
        raise Killed


# -- a kill while the session runs -----------------------------------------------------------------


@pytest.mark.parametrize("tier", ["visible", "held_out"])
def test_a_round_killed_while_its_session_runs_runs_it_again_and_spends_nothing(
    tmp_path: Path, store: StandInStore, tier: str
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store, tier)
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledInTheSession())
    assert _kinds(out) == ["round", "started"]
    slept: list[float] = []
    arm = StandInArm()
    record = _done(store, runs, out, arm, resume=True, slept=slept)
    counts = record.counts[tier]
    assert (counts.trials, counts.passed, counts.unscored) == (1, 1, 0)
    assert len(arm.calls) == 1 and slept == [], "run again at once, its one more go not spent"
    assert _kinds(out) == ["round", "started", "killed", "started", "moving", "recorded"]
    killed = _ledger(out)[2]
    assert killed == {
        "kind": "killed",
        "index": 0,
        "session": 1,
        "left": {"place": True, "session": True, "process": True, "stream": True},
        "held_out_seen": False,
    }
    # The killed session is kept where its tier's finished trials lie, cleared of its credential
    # and of the sentinel's record, its stream scrubbed of the secret; the store is left clean.
    kept_root = (
        out / WORK
        if tier == "visible"
        else withheld_root(store.store, "control") / BASELINE_DIR / record.id
    )
    kept = kept_root / "0000-1" / "place" / "session"
    assert not (kept / "config" / ".credentials.json").exists()
    assert not (kept / "state" / "key").exists()
    assert not (kept / "state" / "sessions" / "s-1" / "sentinel" / "baseline.json").exists()
    assert SECRET not in (kept / "stdout.jsonl").read_text()
    assert not (kept_root / "0000-1" / "harness" / "raw.json").exists()
    assert _left_in_the_store(store) == []


def test_a_round_killed_again_and_again_goes_on_each_time_and_spends_nothing(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledInTheSession())
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledInTheSession(), resume=True)
    record = _done(store, runs, out, StandInArm(), resume=True)
    assert (record.counts["visible"].passed, record.counts["visible"].unscored) == (1, 0)
    assert [k for k in _kinds(out) if k in ("killed", "machine")] == ["killed", "killed"]


def test_a_killed_session_given_another_credential_since_is_kept_without_its_streams(
    tmp_path: Path, store: StandInStore
) -> None:
    """The secret it held cannot be scrubbed with another: its streams go, after the canary scan."""
    out, runs = tmp_path / "round", _one(tmp_path, store)
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledInTheSession())

    def replaced(config: RunConfig, role: Role) -> RawSetup:
        from dataclasses import replace

        return replace(setup_for(config, role), credential=Credential("subscription", "new-one"))

    _done(store, runs, out, StandInArm(), resume=True, setup=replaced)
    killed = _ledger(out)[2]
    assert killed["left"]["streams_removed"] is True
    assert not (out / WORK / "0000-1" / "place" / "session" / "stdout.jsonl").exists()
    started = [line for line in _ledger(out) if line["kind"] == "started"]
    assert started[0]["credential"] == fingerprint(Credential("subscription", SECRET))
    assert started[1]["credential"] == fingerprint(Credential("subscription", "new-one"))


def test_a_killed_session_whose_stream_shows_a_held_out_canary_stops_the_round(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    canary = store.tasks["held_out"][0].canary
    assert canary is not None
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledInTheSession(said=f"read {canary}"))
    arm = StandInArm()
    refused = _refused(store, runs, out, arm, resume=True)
    assert refused.context["refused_because"] == "held_out_seen"
    assert arm.calls == []
    assert _kinds(out)[-2:] == ["killed", "stopped"]
    assert _ledger(out)[-2]["held_out_seen"] is True
    again = _refused(store, runs, out, arm, resume=True)
    assert again.context["refused_because"] == "entry_stopped" and arm.calls == []


# -- a kill after the session ended ----------------------------------------------------------------


def test_a_session_whose_record_was_written_before_the_kill_is_finished_and_never_run_again(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    with pytest.raises(Killed):
        _outcome(store, runs, out, KilledAfterItsRecord())
    arm = StandInArm()
    record = _done(store, runs, out, arm, resume=True)
    assert arm.calls == [], "a session with a record is never given to the raw arm again"
    assert record.counts["visible"].passed == 1
    assert _kinds(out) == ["round", "started", "moving", "recorded"]
    assert _left_in_the_store(store) == []


def test_a_limit_a_kill_left_before_its_line_is_read_from_the_session_s_own_time(
    tmp_path: Path, store: StandInStore
) -> None:
    """Finished from its files later, a limit's reset is read against its record's time."""
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = KilledAfterItsRecord(limited={1: RESET_EPOCH}, text_only={1})
    with pytest.raises(Killed):
        _outcome(store, runs, out, arm, at=BEFORE)
    late = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    outcome = _outcome(store, runs, out, StandInArm(), at=late, resume=True)
    # The record was written moments ago (the row's wall clock): its 1:20pm is the next such time
    # after that, today, and the reset given is never pushed to the day after the late start.
    assert isinstance(outcome, RoundWaits | BaselineRecord)
    limit = next(line for line in _ledger(out) if line["kind"] == "limit")
    assert limit["halted_at"] != "2026-11-14T09:00:00.000000Z"


def test_a_round_killed_between_a_wait_s_line_and_its_move_finishes_the_move(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    real = runner._finish

    def killed(*_a: Any, **_k: Any) -> None:  # noqa: ANN401
        raise Killed

    monkeypatch.setattr(runner, "_finish", killed)
    with pytest.raises(Killed):
        _outcome(store, runs, out, StandInArm(limited={1: RESET_EPOCH}))
    monkeypatch.setattr(runner, "_finish", real)
    assert _kinds(out) == ["round", "started", "limit"]
    arm = StandInArm()
    record = _done(store, runs, out, arm, at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1 and len(arm.calls) == 1
    assert _kinds(out) == ["round", "started", "limit", "started", "moving", "recorded"]
    assert (out / WORK / "0000-1" / "harness" / "raw.json").is_file()
    assert _left_in_the_store(store) == []


def test_a_round_killed_between_a_trial_s_line_and_its_ledger_line_records_it_once(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    real = Ledger.add

    def add(self: Ledger, line: Any) -> None:  # noqa: ANN401
        if line.get("kind") == "recorded":
            raise Killed
        real(self, line)

    monkeypatch.setattr(Ledger, "add", add)
    with pytest.raises(Killed):
        _outcome(store, runs, out, StandInArm())
    monkeypatch.setattr(Ledger, "add", real)
    assert len((out / TRIALS).read_text().splitlines()) == 1
    arm = StandInArm()
    record = _done(store, runs, out, arm, resume=True)
    assert arm.calls == [] and record.counts["visible"].passed == 1
    assert len((out / TRIALS).read_text().splitlines()) == 1
    assert _kinds(out) == ["round", "started", "moving", "recorded"]
    found = audit_raw(
        store=store.store,
        role="control",
        version=store.version,
        runs=runs,
        out=out,
        prices=load_price_sheet(PRICES),
        score=lambda _t, _a: dict(SCORED),
    )
    assert found == []


def test_a_trial_line_a_kill_cut_is_dropped_and_written_whole(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)

    def cut(path: Path, line: Any) -> None:  # noqa: ANN401
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"arm": "raw", "cos')
        raise Killed

    monkeypatch.setattr(runner, "_append", cut)
    with pytest.raises(Killed):
        _outcome(store, runs, out, StandInArm())
    monkeypatch.undo()
    record = _done(store, runs, out, StandInArm(), resume=True)
    assert record.counts["visible"].passed == 1
    assert [json.loads(x)["arm"] for x in (out / TRIALS).read_text().splitlines()] == ["raw"]
    assert [line["kind"] for line in _ledger(out)][-3:] == ["moving", "cut", "recorded"]


def test_a_ledger_line_a_kill_cut_is_dropped_with_a_line_that_says_so(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    outcome = _outcome(store, runs, out, StandInArm(limited={1: RESET_EPOCH}))
    assert isinstance(outcome, RoundWaits)
    with (out / LEDGER).open("ab") as handle:
        handle.write(b'{"kind":"start')
    record = _done(store, runs, out, StandInArm(), at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1
    cut = next(line for line in _ledger(out) if line["kind"] == "cut")
    assert cut["bytes"] == len(b'{"kind":"start')


def test_a_place_a_kill_left_before_its_started_line_is_cleared_and_the_session_run(
    tmp_path: Path, store: StandInStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    real = Ledger.add

    def add(self: Ledger, line: Any) -> None:  # noqa: ANN401
        if line.get("kind") == "started":
            raise Killed
        real(self, line)

    monkeypatch.setattr(Ledger, "add", add)
    arm = StandInArm()
    with pytest.raises(Killed):
        _outcome(store, runs, out, arm)
    monkeypatch.setattr(Ledger, "add", real)
    assert arm.calls == [] and _left_in_the_store(store) != []
    record = _done(store, runs, out, arm, resume=True)
    assert record.counts["visible"].passed == 1 and len(arm.calls) == 1
    assert _kinds(out) == ["round", "cleared", "started", "moving", "recorded"]


def test_a_round_killed_after_a_machine_end_sleeps_that_line_s_delay_before_the_next_session(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)

    def asleep(_seconds: float) -> None:
        raise Killed

    with pytest.raises(Killed):
        run_baseline(
            store=store.store,
            role="control",
            version=store.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=lambda _t, _a: dict(SCORED),
            prices=load_price_sheet(PRICES),
            arm=StandInArm(ended={1: API_ERROR}),
            sleep=asleep,
            now=lambda: BEFORE,
        )
    assert _kinds(out) == ["round", "started", "machine"]
    slept: list[float] = []
    arm = StandInArm()
    record = _done(store, runs, out, arm, resume=True, slept=slept)
    assert slept == [60.0], "the machine line's delay is slept before its one more go"
    assert (record.counts["visible"].passed, record.counts["visible"].unscored) == (1, 0)


# -- a stop for a cause, and a refusal before start ------------------------------------------------


def test_an_arm_s_error_after_its_session_started_is_a_stop_never_a_kill(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    outcome = _outcome(store, runs, out, StandInArm(raises={1: RuntimeError("tools changed")}))
    assert isinstance(outcome, RuntimeError)
    assert _ledger(out)[-1] == {
        "kind": "stopped",
        "index": 0,
        "session": 1,
        "because": "error",
        "error": "RuntimeError",
    }
    arm = StandInArm()
    refused = _refused(store, runs, out, arm, resume=True)
    assert refused.context["refused_because"] == "entry_stopped" and arm.calls == []


def test_a_protected_trial_s_error_says_its_session_had_started(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store, "held_out")
    refused = _refused(store, runs, out, StandInArm(raises={1: RuntimeError("x")}))
    assert refused.context["refused_because"] == "error"
    assert refused.context["session_started"] == "true"


def _with_python(config: RunConfig, role: Role) -> RawSetup:
    from dataclasses import replace

    other = RolePython(
        path="/opt/py/bin/python3",
        resolved="/opt/py/bin/python3.12",
        version="3.12.4",
        prefix="/opt/py",
        distributions=(),
    )
    return replace(setup_for(config, role), role_python=other)


def test_an_interpreter_other_than_the_run_s_is_refused_before_any_line(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm()
    refused = _refused(store, runs, out, arm, setup=_with_python)
    assert refused.context["refused_because"] == "interpreter_differs"
    assert "session_started" not in refused.context
    assert arm.calls == [] and _kinds(out) == ["round"]
    assert _left_in_the_store(store) == []


# -- the checkout the round runs from --------------------------------------------------------------


def _from(commit: str) -> Callable[[RunConfig, Role], RawSetup]:
    def setup(config: RunConfig, role: Role) -> RawSetup:
        from dataclasses import replace

        checkout = HarnessState(commit=commit, clean=True, uncommitted_sha256=None)
        return replace(setup_for(config, role), harness=checkout)

    return setup


def test_a_round_started_again_from_another_checkout_is_refused_before_anything(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    outcome = _outcome(store, runs, out, StandInArm(limited={1: RESET_EPOCH}))
    assert isinstance(outcome, RoundWaits)
    arm = StandInArm()
    refused = _refused(store, runs, out, arm, at=AFTER, resume=True, setup=_from("d" * 40))
    assert refused.context["refused_because"] == "harness_differs"
    assert arm.calls == [] and _kinds(out) == ["round", "started", "limit"]
    record = _done(store, runs, out, arm, at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1


def test_a_raw_session_from_another_checkout_than_its_harness_run_s_is_a_pair_that_differs(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    refused = _refused(store, runs, out, StandInArm(), setup=_from("d" * 40))
    assert refused.context["refused_because"] == "pair_differs"
    assert "harness" in str(refused)
    # A development round forgives the harness's own state, as it always has.
    dev = _done(
        store, runs, tmp_path / "dev", StandInArm(), setup=_from("d" * 40), development=True
    )
    assert dev.development is True
    assert dev.pins["harness"] == {"commit": "d" * 40, "clean": True}


def test_the_session_after_a_reset_is_named_on_a_whole_started_line(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH})
    assert isinstance(_outcome(store, runs, out, arm), RoundWaits)
    _done(store, runs, out, arm, at=AFTER, resume=True)
    assert _ledger(out)[3] == {
        "kind": "started",
        "index": 0,
        "session": 2,
        "limit_reset": "waited",
        "harness": {"commit": CHECKOUT.commit, "clean": True},
        "credential": fingerprint(Credential("subscription", SECRET)),
    }
