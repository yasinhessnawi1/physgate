"""A module review the machine ended after it spent leaves a trial the round assembles.

Through the round, on the real loop. A review's try the machine ends after it has spent tokens,
where the loop then halts the run with the review still owed, is every shape the machine has: the
usage limit, a refused credential, an OS layer that would not start, and the retry ladder spent
(once, after which the round's one resume lets the review pass; and every time, after which the
trial is unscored). Each such try ends on the run's log with a line of its own, the
``review_unavailable`` a retried try has, written after its tokens and before the halt. So the
session-end rule, the cost reader and the assembler all read a closed try, its spend is the
reviewer's and counted once, and the round ends or waits by its own rules: the limit waits, a
refused credential stops for a person, the ladder spent halts and is resumed once (then the trial
is unscored); the trial is assembled with its figure, the cost line's tokens, and nothing needs a
hand.

The same shapes recorded as the loop wrote them before (the try's tokens and then the halt, with
no line of the try's own) are read the same way by the readers: a run recorded so is assembled
too, its halted try priced at its role's reviewer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import round_rig
from observe_rig import SPAWN_STARTED
from observe_rig import Reviewer as RealReviewer
from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import run_round
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    Event,
    Halted,
    ReviewRan,
    ReviewUnavailable,
    SessionSpawned,
    StageEntered,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.session_ends import ended_by, open_sessions
from physgate.orchestrator.usage_limit import UsageLimit


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


class _EndingReviewer:
    """The rig's reviewer, whose first ``first`` tries (counted across the row) the machine ends.

    Each ended try is spawned on the run's log first, as the real reviewer's is, and spends one
    message unless ``spend`` is false; every later try is the rig's passing reviewer.
    """

    how: dict[str, Any] = {}  # noqa: RUF012 - set per row by ``_ending``
    tries = [0]  # noqa: RUF012 - across every drive of the row

    def __init__(self, **rig: Any) -> None:  # noqa: ANN401
        self.real = RealReviewer(**{k: v for k, v in rig.items() if k != "machine_ended"})
        self.model = self.real.model
        self.hook: Any = None

    def record_spawns(self, hook: Any) -> None:  # noqa: ANN401
        self.hook = hook
        self.real.record_spawns(hook)

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        _EndingReviewer.tries[0] += 1
        n = _EndingReviewer.tries[0]
        how = _EndingReviewer.how
        if n > how["first"]:
            return self.real.review(artefact)
        sid = f"rev-ended-{n}"
        if self.hook is not None:
            self.hook(sid, os.getpid(), SPAWN_STARTED)
        spent = Usage(
            input_tokens=25,
            output_tokens=4,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        raise ReviewUnavailableError(
            f"the review's session ended with {how['cause']}",
            cause="infrastructure",
            session_id=sid,
            reviewer_model=self.model,
            usage=(MessageUsage(message_id=f"ended-{n}", usage=spent),) if how["spend"] else (),
            session_cause=how["cause"],
            usage_limit=UsageLimit(resets="later") if how["cause"] == "usage_limit" else None,
        )


def _ending(monkeypatch: pytest.MonkeyPatch, first: int, cause: str, *, spend: bool) -> None:
    _EndingReviewer.how = {"first": first, "cause": cause, "spend": spend}
    _EndingReviewer.tries = [0]
    monkeypatch.setattr(round_rig, "Reviewer", _EndingReviewer)


def _as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop as it wrote these shapes before: the try's tokens and the halt, nothing between."""
    monkeypatch.setattr(Loop, "_owed_again", lambda *_a, **_k: None)


def _ledger(rig: Rig) -> list[dict[str, Any]]:
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _start(rig: Rig, driver: StandInDriver, **how: Any) -> tuple[str, str | None]:  # noqa: ANN401
    """One start of the round: how it left off and why it waits, or what stopped it."""
    try:
        status, summary = run_round(
            rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None, **how
        )
    except Exception as exc:  # noqa: BLE001 - a stop of any kind is what the row says
        return f"stopped: {type(exc).__name__}", str(exc)
    return status, (summary.get("waiting") or {}).get("why")


def _drive_to_its_end(rig: Rig, driver: StandInDriver) -> list[tuple[str, str | None]]:
    """The round started, then started again with only the words its waits ask for."""
    said = [_start(rig, driver)]
    for _again in range(3):
        status = said[-1][0]
        if status in ("done", "done_without_caps") or status.startswith("stopped"):
            break
        words = {"limit_reset": True} if status == "waiting_for_limit" else {}
        said.append(_start(rig, driver, resume=True, **words))
    return said


def _reviews_spawned(events: list[Event]) -> list[str]:
    stage = None
    found: list[str] = []
    for event in events:
        if isinstance(event, StageEntered):
            stage = event.stage
        elif isinstance(event, SessionSpawned) and stage == "review":
            found.append(event.session_id)
    return found


#: Each shape: the review's first tries the machine ends, its cause, how the round said it stood
#: at each start, the halts the run's log holds, and whether the trial is unscored.
SHAPES = {
    "the usage limit, then the review passes after the reset": (
        1,
        "usage_limit",
        [("waiting_for_limit", "usage_limit"), ("done", None)],
        ["usage_limit"],
        False,
    ),
    "a refused credential, then the review passes once a person starts the round again": (
        1,
        "credential_refused",
        [("waiting_for_a_person", "credential_refused"), ("done", None)],
        ["credential_refused"],
        False,
    ),
    "an OS layer that would not start, then the review passes after the round's resume": (
        1,
        "sandbox_unavailable",
        [("done", None)],
        ["os_layer_unavailable"],
        False,
    ),
    "the ladder spent once, then the review passes after the round's resume": (
        3,
        "api_error",
        [("done", None)],
        ["infrastructure_exhausted"],
        False,
    ),
    "the ladder spent at every drive, so the trial is unscored after its one resume": (
        99,
        "api_error",
        [("done_without_caps", None)],
        ["infrastructure_exhausted", "infrastructure_exhausted"],
        True,
    ),
}


@pytest.mark.parametrize("writer", ["now", "before"])
@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_review_try_the_machine_ended_after_it_spent_is_assembled_by_the_round_s_own_rules(
    shape: str, writer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, cause, said, halts, unscored = SHAPES[shape]
    _ending(monkeypatch, first, cause, spend=True)
    if writer == "before":
        _as_before(monkeypatch)
    rig = make_rig(tmp_path)
    driver = rig.driver()
    assert _drive_to_its_end(rig, driver) == said
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    run_dir = Path(assembled["run_dir"])
    events = list(read_events(run_dir / "events.jsonl"))
    assert [e.reason for e in events if isinstance(e, Halted)] == halts
    assert open_sessions(events, run_dir) == ()
    # Every ended try's spend is on the log, the reviewer's, once.
    account = TokenAccount.from_events(events)
    ended = sorted({s for s in _reviews_spawned(events) if s.startswith("rev-ended-")})
    assert ended and all(f"reviewer:{s}" in account.by_attribution() for s in ended)
    spent = [e.message_id for e in events if isinstance(e, TokensUsed)]
    assert len(spent) == len(set(spent)), "a message counted twice"
    cost = assembled["record"]["cost"]["tokens"]
    assert cost == account.total().total()
    if unscored:
        assert (assembled["outcome"], assembled["unscored"]) == ("unscored", True)
        assert assembled["harness_total"] is None
        assert assembled["no_figure"]["because"] == "unscored"
    else:
        assert (assembled["outcome"], assembled["unscored"]) == ("pass", False)
        assert assembled["no_figure"] is None
        assert assembled["harness_total"] == cost
    if writer == "now":
        # Each try the review spawned ends on a line that names it, never on the halt alone.
        for session_id in _reviews_spawned(events):
            end = ended_by(session_id, events)
            assert isinstance(end, ReviewRan | ReviewUnavailable), (session_id, end)
        before_halts = [
            events[k - 1] for k, e in enumerate(events) if isinstance(e, Halted) and k > 0
        ]
        assert all(isinstance(e, ReviewUnavailable) and e.retry for e in before_halts)
    else:
        assert len([e for e in events if isinstance(e, ReviewUnavailable)]) < len(ended)


@pytest.mark.parametrize(
    ("first", "cause", "unscored"),
    [(1, "credential_refused", False), (99, "api_error", True)],
)
def test_a_review_try_the_machine_ended_before_it_spent_is_no_session_left_open(
    first: int, cause: str, unscored: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A try that spent nothing (its credential refused at its first request) has no tokens to
    # end it: its own line does, so the trial gives its figure rather than "a session left open".
    _ending(monkeypatch, first, cause, spend=False)
    rig = make_rig(tmp_path)
    _drive_to_its_end(rig, rig.driver())
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    run_dir = Path(assembled["run_dir"])
    events = list(read_events(run_dir / "events.jsonl"))
    assert open_sessions(events, run_dir) == ()
    if unscored:
        assert assembled["no_figure"]["because"] == "unscored"
    else:
        assert assembled["no_figure"] is None
        assert assembled["harness_total"] == assembled["record"]["cost"]["tokens"]


def test_a_try_that_spent_nothing_recorded_on_the_halt_alone_is_a_session_left_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As a run recorded before every halting try had its own line: a try that spent nothing left
    # no tokens for the end rule to read, so its spawn is open, and the trial says so as the
    # reason it gives no figure (the real dispatcher reads such a session again at the resume).
    _ending(monkeypatch, 1, "credential_refused", spend=False)
    _as_before(monkeypatch)
    rig = make_rig(tmp_path)
    _drive_to_its_end(rig, rig.driver())
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    run_dir = Path(assembled["run_dir"])
    events = list(read_events(run_dir / "events.jsonl"))
    assert [s.session_id for s in open_sessions(events, run_dir)] == ["rev-ended-1"]
    assert assembled["outcome"] == "pass" and assembled["harness_total"] is None
    assert assembled["no_figure"]["because"] == "leftover_unread"


@pytest.mark.parametrize("tier", ["visible", "held_out"])
def test_the_command_waits_for_the_limit_a_review_met_after_it_spent_and_then_ends_the_round(
    tier: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from physgate.cli import main  # noqa: PLC0415 - the command, as a launch script calls it
    from physgate.evaluation import harness_round  # noqa: PLC0415

    _ending(monkeypatch, 1, "usage_limit", spend=True)
    rig = make_rig(tmp_path)
    driver = rig.driver()
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _scorer)
    argv = [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", tier, "--trials", "1", "--seed-base", "1", "--tasks", "1"),
        *("--order-seed", "1124", "--only", "0"),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
    ]
    said = []
    for more in ((), ("--resume", "--limit-reset")):
        code = main([*argv, *more])
        printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        said.append((code, printed.get("status") or printed.get("refused_because")))
    assert said == [(75, "waiting_for_limit"), (0, "done")]
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    assert assembled["harness_total"] == assembled["record"]["cost"]["tokens"]
