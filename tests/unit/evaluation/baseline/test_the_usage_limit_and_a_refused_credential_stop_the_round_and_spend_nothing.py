"""The account's usage limit and a refused credential stop the baseline round, and spend nothing.

A raw session the account's usage limit ended is no trial's end: the round stops as waiting for
the reset, read from the session's stream as the harness arm reads a role session's (the refusal
event's instant; else the result's wall-clock text; else the core's stated wait or a person's
word). A session whose credential was refused stops the round as waiting for a person. Neither
spends the entry's one more go, neither is ever unscored, and each is kept where a finished trial
lies with no trial record. The round returns at once with the harness round driver's words and
exit statuses (75 for the limit, 77 for a person) and goes on from its own ledger when started
again: a start before the reset makes and writes nothing.

Every row runs on the stand-in store and the stand-in raw arm the baseline's other rows use. The
streams are stand-ins in the shape a live run's stream gave at the limit. No session is started.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from baseline_fixtures import (
    PRICES,
    RESET_EPOCH,
    RESET_STAMP,
    SCORED,
    StandInArm,
    StandInStore,
    copied,
    harness_run,
    run_set,
    setup_for,
    stand_in_store,
)

from physgate.evaluation.baseline.record import BASELINE_RECORD, BaselineRecord
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    EXIT_WAITING_FOR_A_PERSON,
    LEDGER,
    ROUND_RECORD,
    TRIALS,
    WORK,
    BaselineError,
    RoundWaits,
    RunSet,
    Status,
    machine_end,
    run_baseline,
)
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.tiers.store import withheld_root
from physgate.evaluation.tiers.task import Task
from physgate.orchestrator.run_config import load_run_config
from physgate.orchestrator.usage_limit import UNREAD_RESET_WAIT
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT

API_ERROR = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
#: Before the stand-in limit's reset, and after it.
BEFORE = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
AFTER = datetime(2026, 11, 13, 12, 21, tzinfo=UTC)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> StandInStore:
    return stand_in_store(tmp_path_factory.mktemp("store"))


@pytest.fixture
def store(tmp_path: Path, made: StandInStore) -> StandInStore:
    return copied(made, tmp_path / "store")


class Scorer:
    """The harness-side scorer, counting what it was asked to score."""

    def __init__(self) -> None:
        self.scored: list[Path] = []

    def __call__(self, task: Task, answer: Path) -> dict[str, Any]:
        assert answer.is_file()
        self.scored.append(answer)
        return dict(SCORED)


def _outcome(
    made: StandInStore,
    runs: RunSet,
    out: Path,
    arm: StandInArm,
    *,
    at: datetime,
    resume: bool = False,
    word: bool = False,
    slept: list[float] | None = None,
    scorer: Callable[[Task, Path], dict[str, Any]] | None = None,
) -> BaselineRecord | Exception:
    """What the round gave: its record, or what it raised (a wait, a refusal), as a value."""
    try:
        return run_baseline(
            store=made.store,
            role="control",
            version=made.version,
            runs=runs,
            out=out,
            setup_for=setup_for,
            score=scorer if scorer is not None else Scorer(),
            prices=load_price_sheet(PRICES),
            arm=arm,
            sleep=(slept if slept is not None else []).append,
            resume=resume,
            limit_reset=word,
            now=lambda: at,
        )
    except Exception as exc:  # noqa: BLE001 - asserted by the caller, so a stop is a failed row
        return exc


def _start(
    made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any
) -> BaselineRecord:  # noqa: ANN401
    outcome = _outcome(made, runs, out, arm, **how)
    assert isinstance(outcome, BaselineRecord), f"the round did not end: {outcome!r}"
    return outcome


def _waits(made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any) -> RoundWaits:  # noqa: ANN401
    outcome = _outcome(made, runs, out, arm, **how)
    assert isinstance(outcome, RoundWaits), f"the round did not wait: {outcome!r}"
    return outcome


def _refused(
    made: StandInStore, runs: RunSet, out: Path, arm: StandInArm, **how: Any
) -> BaselineError:  # noqa: ANN401
    outcome = _outcome(made, runs, out, arm, **how)
    assert isinstance(outcome, BaselineError), f"the round was not refused: {outcome!r}"
    return outcome


def _ledger(out: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (out / LEDGER).read_text().splitlines()]


def _kinds(out: Path) -> list[str]:
    return [line["kind"] for line in _ledger(out)]


def _snapshot(*roots: Path) -> dict[str, bytes | None]:
    """Every path beneath ``roots`` and the bytes of each file."""
    seen: dict[str, bytes | None] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            seen[str(path)] = (
                path.read_bytes() if path.is_file() and not path.is_symlink() else None
            )
    return seen


def _one(tmp_path: Path, made: StandInStore, tier: str = "visible") -> RunSet:
    run = harness_run(tmp_path / "runs", made.tasks[tier][0], made)
    return run_set((run, 0))


# -- the usage limit ------------------------------------------------------------------------------


def test_a_session_the_limit_ended_stops_the_round_as_waiting_for_its_reset(
    tmp_path: Path, store: StandInStore
) -> None:
    out = tmp_path / "round"
    arm = StandInArm(limited={1: RESET_EPOCH})
    waits = _waits(store, _one(tmp_path, store), out, arm, at=BEFORE)
    assert waits.status == "waiting_for_limit"
    assert waits.exit_code == EXIT_WAITING_FOR_LIMIT == 75
    assert waits.waiting == {
        "index": 0,
        "why": "usage_limit",
        "resume_after": RESET_STAMP,
        "word_helps": False,
    }
    # Said where a wrapper reads it, as well as raised: the same line.
    assert json.loads((out / ROUND_RECORD).read_text()) == waits.printed()
    # No trial: no trial record, no baseline record, the session kept with its spend named.
    assert not (out / TRIALS).exists() and not (out / BASELINE_RECORD).exists()
    assert _kinds(out) == ["round", "started", "limit"]
    assert _ledger(out)[-1]["tokens"] == 400
    assert (out / WORK / "0000-1" / "harness" / "raw.json").is_file()


def test_a_start_before_the_reset_makes_nothing_and_writes_nothing(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH})
    first = _waits(store, runs, out, arm, at=BEFORE)
    before = _snapshot(out, store.store)
    again = _waits(store, runs, out, arm, at=BEFORE, resume=True)
    assert again.printed() == first.printed()
    assert len(arm.calls) == 1, "no session was started"
    assert _snapshot(out, store.store) == before, "nothing was written or made"


def test_a_start_after_the_reset_runs_the_session_again_and_spends_no_re_run(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH})
    slept: list[float] = []
    _waits(store, runs, out, arm, at=BEFORE)
    record = _start(store, runs, out, arm, at=AFTER, resume=True, slept=slept)
    assert record.counts["visible"].passed == 1
    assert (record.counts["visible"].trials, record.counts["visible"].unscored) == (1, 0)
    assert slept == [], "the limit is no machine end: no delay, no one more go"
    assert _kinds(out) == ["round", "started", "limit", "started", "moving", "recorded"]
    assert _ledger(out)[3]["limit_reset"] == "waited"
    assert json.loads((out / ROUND_RECORD).read_text())["status"] == "done"


def test_the_limit_met_twice_waits_twice_and_never_makes_the_trial_unscored(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store, "held_out")
    arm = StandInArm(limited={1: RESET_EPOCH, 2: RESET_EPOCH + 3600})
    _waits(store, runs, out, arm, at=BEFORE)
    second = _waits(store, runs, out, arm, at=AFTER, resume=True)
    assert second.waiting["resume_after"] == "2026-11-13T13:20:00.000000Z"
    record = _start(
        store, runs, out, arm, at=datetime(2026, 11, 13, 13, 21, tzinfo=UTC), resume=True
    )
    counts = record.counts["held_out"]
    assert (counts.trials, counts.passed, counts.unscored) == (1, 1, 0)
    assert len(arm.calls) == 3
    # Every session of a protected trial lies beneath the withheld root, the waited ones too.
    beneath = withheld_root(store.store, "control") / BASELINE_DIR / record.id
    assert sorted(p.name for p in beneath.iterdir() if p.is_dir()) == [
        "0000-1",
        "0000-2",
        "0000-3",
    ]
    assert not (out / WORK).exists()


def test_a_limit_between_two_machine_ends_spends_nothing_and_the_second_machine_end_is_unscored(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(ended={1: API_ERROR, 3: API_ERROR}, limited={2: RESET_EPOCH})
    slept: list[float] = []
    _waits(store, runs, out, arm, at=BEFORE, slept=slept)
    assert slept == [60.0], "the machine's first end is given its one more go"
    record = _start(store, runs, out, arm, at=AFTER, resume=True, slept=slept)
    assert slept == [60.0]
    assert record.counts["visible"].unscored == 1


def test_a_limit_then_one_machine_end_is_given_the_one_more_go_still(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH}, ended={2: API_ERROR})
    slept: list[float] = []
    _waits(store, runs, out, arm, at=BEFORE)
    record = _start(store, runs, out, arm, at=AFTER, resume=True, slept=slept)
    assert slept == [60.0] and len(arm.calls) == 3
    assert (record.counts["visible"].passed, record.counts["visible"].unscored) == (1, 0)


def test_a_session_the_limit_ended_after_it_wrote_its_answer_is_waited_on_and_never_scored(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH}, answered_first={1})
    scorer = Scorer()
    _waits(store, runs, out, arm, at=BEFORE, scorer=scorer)
    assert scorer.scored == []
    assert not (out / WORK / "0000-1" / "harness" / "score.json").exists()


def test_a_canary_in_a_stream_the_limit_ended_still_excludes_the_trial(
    tmp_path: Path, store: StandInStore
) -> None:
    """Read before the limit: such a session is no wait, it is assembled as excluded."""
    task = store.tasks["held_out"][0]
    run = harness_run(tmp_path / "runs", task, store)
    setup = setup_for(load_run_config(run / "run.json"), "control")
    harness = tmp_path / "harness"
    harness.mkdir()
    arm = StandInArm(limited={1: RESET_EPOCH}, seen={1})
    record = arm(task, setup, tmp_path / "place", cap=1000, harness=harness)
    stream = tmp_path / "place" / "session" / "stdout.jsonl"
    assert machine_end(record, stream, task) == (None, None)
    # The same stream without the canary is the limit, read as the harness arm reads it.
    unseen = StandInArm(limited={1: RESET_EPOCH})
    (tmp_path / "h2").mkdir()
    record = unseen(task, setup, tmp_path / "place2", cap=1000, harness=tmp_path / "h2")
    end, limit = machine_end(record, tmp_path / "place2" / "session" / "stdout.jsonl", task)
    assert end == "usage_limit" and limit is not None and limit.resets_at == RESET_STAMP


def test_a_reset_the_stream_did_not_give_waits_the_core_s_stated_time_or_a_person_s_word(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: None})
    waits = _waits(store, runs, out, arm, at=BEFORE)
    assert waits.waiting["word_helps"] is True
    assert waits.waiting["resume_after"] == "2026-11-13T16:00:00.000000Z"
    assert UNREAD_RESET_WAIT.total_seconds() == 5 * 3600
    record = _start(store, runs, out, arm, at=BEFORE, resume=True, word=True)
    assert record.counts["visible"].passed == 1
    assert _ledger(out)[3]["limit_reset"] == "operator"


def test_a_reset_the_stream_gave_only_as_its_wall_clock_text_is_read_from_the_text(
    tmp_path: Path, store: StandInStore
) -> None:
    """No refusal event: the result's text is read as the next such time after the halt."""
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH}, text_only={1})
    waits = _waits(store, runs, out, arm, at=BEFORE)
    assert waits.waiting == {
        "index": 0,
        "why": "usage_limit",
        "resume_after": RESET_STAMP,
        "word_helps": False,
    }
    assert _ledger(out)[-1]["limit"]["resets_at"] == RESET_STAMP
    record = _start(store, runs, out, arm, at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1


def test_a_person_s_word_does_not_shorten_a_reset_the_stream_gave(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH})
    _waits(store, runs, out, arm, at=BEFORE)
    _waits(store, runs, out, arm, at=BEFORE, resume=True, word=True)
    assert len(arm.calls) == 1


def test_a_person_s_word_for_a_round_that_waits_for_no_limit_is_refused(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(refused={1})
    _waits(store, runs, out, arm, at=BEFORE)
    refused = _refused(store, runs, out, arm, at=BEFORE, resume=True, word=True)
    assert refused.context["refused_because"] == "limit_reset_not_waiting"
    assert len(arm.calls) == 1


def test_a_round_killed_while_it_waits_goes_on_from_its_own_ledger(
    tmp_path: Path, store: StandInStore
) -> None:
    """The process gone between the wait it recorded and the line it printed: the ledger holds."""
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH})
    _waits(store, runs, out, arm, at=BEFORE)
    (out / ROUND_RECORD).unlink()
    again = _waits(store, runs, out, arm, at=BEFORE, resume=True)
    assert again.waiting["resume_after"] == RESET_STAMP and len(arm.calls) == 1
    record = _start(store, runs, out, arm, at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1


# -- a refused credential --------------------------------------------------------------------------


def test_a_refused_credential_stops_the_round_for_a_person_and_spends_nothing(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store, "held_out")
    arm = StandInArm(refused={1})
    slept: list[float] = []
    waits = _waits(store, runs, out, arm, at=BEFORE, slept=slept)
    assert waits.status == "waiting_for_a_person"
    assert waits.exit_code == EXIT_WAITING_FOR_A_PERSON == 77
    assert waits.waiting == {"index": 0, "why": "credential_refused"}
    assert slept == [] and len(arm.calls) == 1, "not run again after the first delay"
    assert _kinds(out) == ["round", "started", "credential"]
    # Its next start runs the session again as if it had not run, at once.
    record = _start(store, runs, out, arm, at=BEFORE, resume=True, slept=slept)
    counts = record.counts["held_out"]
    assert (counts.trials, counts.passed, counts.unscored) == (1, 1, 0)
    assert slept == []


def test_a_credential_refused_twice_never_makes_the_trial_unscored(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(refused={1, 2})
    _waits(store, runs, out, arm, at=BEFORE)
    _waits(store, runs, out, arm, at=BEFORE, resume=True)
    record = _start(store, runs, out, arm, at=BEFORE, resume=True)
    assert (record.counts["visible"].passed, record.counts["visible"].unscored) == (1, 0)


def test_the_limit_then_a_refused_credential_each_wait_and_the_trial_then_runs(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(limited={1: RESET_EPOCH}, refused={2})
    assert _waits(store, runs, out, arm, at=BEFORE).status == "waiting_for_limit"
    assert _waits(store, runs, out, arm, at=AFTER, resume=True).status == "waiting_for_a_person"
    record = _start(store, runs, out, arm, at=AFTER, resume=True)
    assert record.counts["visible"].passed == 1
    assert _kinds(out) == [
        "round",
        "started",
        "limit",
        "started",
        "credential",
        "started",
        "moving",
        "recorded",
    ]


def test_earlier_trials_stay_recorded_and_are_counted_once_across_starts(
    tmp_path: Path, store: StandInStore
) -> None:
    runs_dir = tmp_path / "runs"
    first = harness_run(runs_dir, store.tasks["visible"][0], store)
    second = harness_run(runs_dir, store.tasks["held_out"][0], store)
    out, runs = tmp_path / "round", run_set((first, 0), (second, 0))
    arm = StandInArm(limited={2: RESET_EPOCH})
    _waits(store, runs, out, arm, at=BEFORE)
    assert len((out / TRIALS).read_text().splitlines()) == 1
    record = _start(store, runs, out, arm, at=AFTER, resume=True)
    assert (record.counts["visible"].trials, record.counts["held_out"].trials) == (1, 1)
    assert len((out / TRIALS).read_text().splitlines()) == 1
    assert record.counts["visible"].spent == record.counts["held_out"].spent == 400


# -- what a start again refuses --------------------------------------------------------------------


def test_a_start_again_on_other_inputs_is_refused(tmp_path: Path, store: StandInStore) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    _waits(store, runs, out, StandInArm(limited={1: RESET_EPOCH}), at=BEFORE)
    other = harness_run(tmp_path / "other", store.tasks["visible"][1], store)
    refused = _refused(store, run_set((other, 0)), out, StandInArm(), at=AFTER, resume=True)
    assert refused.context["refused_because"] == "inputs_changed"


def test_a_round_that_ended_started_again_gives_its_record_and_runs_nothing(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    first = _start(store, runs, out, StandInArm(), at=BEFORE)
    before = _snapshot(out, store.store)
    arm = StandInArm()
    again = _start(store, runs, out, arm, at=BEFORE, resume=True)
    assert again == first and arm.calls == []
    assert _snapshot(out, store.store) == before


def test_an_entry_the_round_stopped_on_for_a_cause_is_never_run_again_in_its_round(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store)
    arm = StandInArm(answered={1: "claude-other"})
    stopped = _refused(store, runs, out, arm, at=BEFORE)
    assert "differs from the harness run" in str(stopped)
    assert stopped.context["refused_because"] == "pair_differs"
    assert stopped.context["session_started"] == "true"
    assert _ledger(out)[-1] == {
        "kind": "stopped",
        "index": 0,
        "session": 1,
        "because": "pair",
        "fields": ["answered_by"],
    }
    again = StandInArm()
    refused = _refused(store, runs, out, again, at=BEFORE, resume=True)
    assert refused.context["refused_because"] == "entry_stopped"
    assert refused.context["because"] == "pair" and again.calls == []


# -- the command -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "waiting", "code"),
    [
        (
            "waiting_for_limit",
            {"index": 3, "why": "usage_limit", "resume_after": RESET_STAMP, "word_helps": False},
            75,
        ),
        ("waiting_for_a_person", {"index": 3, "why": "credential_refused"}, 77),
    ],
    ids=["the limit", "a person"],
)
def test_the_command_prints_the_wait_and_exits_with_the_driver_s_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    waiting: dict[str, Any],
    code: int,
) -> None:
    import physgate.evaluation.baseline.runner as runner
    import physgate.orchestrator.install as install
    from physgate.cli import main

    def waits(**given: Any) -> None:  # noqa: ANN401
        assert given["resume"] is True and given["limit_reset"] is False
        raise RoundWaits(status, "0" * 16, waiting)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "run_baseline", waits)
    # The scorer's libraries are the evaluation environment's; the command only names it here.
    import types

    scorer = types.ModuleType("physgate.evaluation.per_role.scorers.control")
    scorer.score = Scorer()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, scorer.__name__, scorer)
    monkeypatch.setattr(install, "prepare_install", lambda *_: tmp_path / "bin")
    (tmp_path / "runs.json").write_text(
        json.dumps({"format": 1, "trials": [{"run_dir": "/r", "trial": 0}]})
    )
    argv = ["baseline", "run", "--store", str(tmp_path), "--role", "control", "--version", "v"]
    argv += ["--runs", str(tmp_path / "runs.json"), "--out", str(tmp_path / "o")]
    argv += ["--prices", PRICES, "--resume"]
    assert main(argv) == code
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"format": 1, "round": "0" * 16, "status": status, "waiting": waiting}


def test_a_waited_session_is_kept_whole_where_its_tier_s_trials_lie(
    tmp_path: Path, store: StandInStore
) -> None:
    out, runs = tmp_path / "round", _one(tmp_path, store, "held_out")
    _waits(store, runs, out, StandInArm(refused={1}), at=BEFORE)
    round_id = _ledger(out)[0]["round"]
    kept = withheld_root(store.store, "control") / BASELINE_DIR / round_id / "0000-1"
    assert (kept / "harness" / "raw.json").is_file()
    assert not (kept.parent / TRIALS).exists(), "no trial record of a waited session"


def test_the_round_s_exit_statuses_are_the_harness_round_s() -> None:
    """One launch script reads both arms' waits alike: the same values under the same names."""
    from physgate.evaluation import harness_round

    assert EXIT_WAITING_FOR_A_PERSON == harness_round.EXIT_WAITING_FOR_A_PERSON
    assert RoundWaits("waiting_for_limit", "0" * 16, {}).exit_code == EXIT_WAITING_FOR_LIMIT
    assert set(get_args(Status)) <= set(get_args(harness_round.Status))
