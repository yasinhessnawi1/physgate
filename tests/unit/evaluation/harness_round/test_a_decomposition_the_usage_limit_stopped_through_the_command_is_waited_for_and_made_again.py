"""A decomposition the usage limit stopped, made by the command itself, waits and is made again.

The round's other rows stand in for ``physgate decompose``. Here the round calls the command as it
calls it for a measured round (its own command driver, in this process, the command's output kept
beneath the withheld root), and the plan call in it is the real one, its binary's output scripted:
the stand-in stream a live run's stream gave when its account reached the limit, with the
refusal's reset or with none, after one message that spent tokens. Where the plan is reviewed, the
review's session is stood in for and its end read as the reviewer reads it, on the same stream. So
the core records the limit as it records it for a real round: on the failed decomposition's halt
(a plan not reviewed, or a review observed), or on the round journal's end line of rounds that
ended void (a plan reviewed); and ``decompose`` exits 75.

The round holds that to its rule for the limit: the trial is not counted, not superseded and not
unscored; the ``limit`` line names the spend the client reported; the round exits 75, saying the
instant after which it goes on. That instant is the core's: the reset the core recorded where it
read one, and otherwise the core's stated wait after the halt (or after the void rounds' end). A
restart before it makes nothing; a restart after it makes the decomposition again into a fresh
directory, and the trial goes on to a counted result. The runs are driven by the rig's real loop
with stand-in sessions, as every round row drives them.
"""

from __future__ import annotations

import functools
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ORCHESTRATOR_TESTS = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_TESTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_TESTS))

from round_rig import (  # noqa: E402
    PLAN_REVIEWER,
    SCORED,
    PlanReview,
    Rig,
    StandInDriver,
    make_rig,
)
from test_a_decomposition_stopped_by_the_usage_limit_waits_for_its_reset import (  # noqa: E402
    NO_RESET,
    real_call,
)
from test_a_usage_limit_is_its_own_cause_and_the_run_waits_for_its_reset import (  # noqa: E402
    INIT,
    SESSION_LIMIT,
    _line,
    _rate_limit,
    _result,
    _said,
    _stream,
)

import physgate.orchestrator.binaries as binaries  # noqa: E402
import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.cli import main  # noqa: E402
from physgate.evaluation import harness_round  # noqa: E402
from physgate.evaluation.harness_round import (  # noqa: E402
    HARNESS_ROUNDS,
    LEDGER,
    ROUND_RECORD,
    CommandDriver,
    Decompose,
    run_round,
)
from physgate.evaluation.tiers.store import withheld_root  # noqa: E402
from physgate.orchestrator.common import utc_stamp  # noqa: E402
from physgate.orchestrator.credentials import SECRET_VARIABLE  # noqa: E402
from physgate.orchestrator.decompose import ROUNDS_JOURNAL, Outcome  # noqa: E402
from physgate.orchestrator.design_rounds import journal_spend, rounds_on_the_limit  # noqa: E402
from physgate.orchestrator.events import Halted, read_events  # noqa: E402
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage  # noqa: E402
from physgate.orchestrator.record import ReviewInstall  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402
from physgate.orchestrator.trajectory import seal  # noqa: E402
from physgate.orchestrator.usage_limit import (  # noqa: E402
    UNREAD_RESET_WAIT,
    UsageLimit,
    stamped,
    usage_limit_of,
)
from physgate.reviewers.places import review_root_path  # noqa: E402

#: What ``physgate harness-round`` and ``physgate decompose`` exit with while waiting for the limit.
WAITING = 75
#: A credential of the parameters' mode, in the form the command takes one; no account's.
DUMMY_TOKEN = "sk-ant-oat01-test-dummy-not-a-credential"
INSTALL = ReviewInstall(path="/install", action="checked", seconds=0.0, entries=1)
#: What the plan call's one answered message spent before its next request was refused.
SPENT = Usage(
    input_tokens=40, output_tokens=12, cache_read_input_tokens=0, cache_creation_input_tokens=0
)
#: What the scripted plan call that gives a plan spent, and what a stood-in plan review spent.
PLANNED = Usage(
    input_tokens=50, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0
)
REVIEWED = Usage(
    input_tokens=5, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0
)
#: Where a decomposition is stopped by the limit: the plan's call, or the plan's review; under the
#: run's ``design_review``. A plan not reviewed, or a review observed, halts the run's record; a
#: plan reviewed ends the rounds void.
SHAPES = [("off", "call"), ("observe", "call"), ("on", "call"), ("on", "review")]


def limited(kind: str, resets_at: int | None) -> tuple[str, dict[str, Any]]:
    """A stream that answered one message, then was refused on the limit, and its result.

    ``kind`` is the refused window: ``five_hour`` or ``seven_day``, with the refusal's reset at
    ``resets_at`` (epoch seconds), or with no reset anywhere when it is ``None``.
    """
    message = {
        "id": "msg_0",
        "model": "claude-opus-5-5",
        "role": "assistant",
        "type": "message",
        "content": [{"type": "text", "text": "Reading the brief."}],
        "usage": SPENT.model_dump(),
    }
    answered = _line(type="assistant", message=message, session_id="s")
    text = NO_RESET if resets_at is None else SESSION_LIMIT
    result = _result(text, status=429)
    refused = _rate_limit("rejected", kind=kind, resets_at=resets_at)
    return _stream(INIT, answered, refused, _said(text, "rate_limit"), json.dumps(result)), result


@dataclass
class LimitedReview(PlanReview):
    """The plan's reviewer; its session read as ended on the limit where ``limit`` says so."""

    limit: tuple[str, int | None] | None = None

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        if self.limit is None:
            return super().review_plan(under)
        stream, result = limited(*self.limit)
        raise ReviewUnavailableError(
            "the session ended with api_error",
            cause="infrastructure",
            session_id=f"plan-review-{self.n}",
            reviewer_model=PLAN_REVIEWER,
            usage=(MessageUsage(message_id=f"r{self.n}", usage=REVIEWED),),
            usage_limit=usage_limit_of(stream, result),
        )


@dataclass
class ThroughTheCommand(StandInDriver):
    """Decomposes through ``physgate decompose`` as the round's command driver calls it.

    Per decomposition, by its number across the row: ``calls`` and ``reviews`` name the plan call
    or the plan's review the limit stops, as (window, reset in epoch seconds or ``None``). Every
    other plan call gives the rig's plan of one control module, and every other review passes it.
    What the command measures of this machine is the round's parameters as given; the call, the
    run's record, the journal, the halt and what the command prints and exits with are the core's.
    """

    calls: dict[int, tuple[str, int | None]] = field(default_factory=dict)
    reviews: dict[int, tuple[str, int | None]] = field(default_factory=dict)
    #: What each decomposition's command exited with.
    exits: list[int] = field(default_factory=list)

    def decompose(self, call: Decompose) -> int:
        self.decomposed.append(call)
        n = len(self.decomposed)
        review = LimitedReview(
            self, n, review_root_path(call.review_root), limit=self.reviews.get(n)
        )

        def configured(_args: Any, _credential: Any) -> RunConfig:  # noqa: ANN401
            return self.config_of(call)

        def reviewer(_args: Any, config: RunConfig, *_rest: Any) -> Any:  # noqa: ANN401
            return None if config.design_review == "off" else (review, INSTALL)

        with pytest.MonkeyPatch.context() as patch:
            patch.setenv(SECRET_VARIABLE["subscription"], DUMMY_TOKEN)
            patch.setattr(orchestrator_cli, "_config", configured)
            patch.setattr(orchestrator_cli, "refusals", lambda _facts: [])
            patch.setattr(orchestrator_cli, "_library_root", lambda: self.library)
            patch.setattr(binaries, "require_listed", lambda _version, _binary: None)
            patch.setattr(orchestrator_cli, "_plan_reviewer", reviewer)
            patch.setattr(orchestrator_cli, "call", functools.partial(self._plan_call, n))
            code = CommandDriver().decompose(call)
        self.exits.append(code)
        return code

    def _plan_call(self, n: int, brief: str, *, workdir: Path, **given: Any) -> Outcome:  # noqa: ANN401
        config: RunConfig = given["config"]
        if n in self.calls:
            stream, _ = limited(*self.calls[n])
            return real_call(brief, workdir=workdir, stream=stream, **given)
        session = str(given.get("session_id") or f"plan-{n}")
        workdir.mkdir(parents=True, exist_ok=True)
        stream_file = workdir / "stdout.jsonl"
        stream_file.write_text(json.dumps({"type": "result", "session_id": session}) + "\n")
        prompt = given.get("prompt")
        sent = prompt.encode() if isinstance(prompt, str) else b""
        return Outcome(
            session_id=session,
            ok=True,
            cause=None,
            detail="a plan",
            plan=self.plan_of(config),
            usage=(MessageUsage(message_id=f"plan-{n}", usage=PLANNED),),
            model=config.models.decomposition,
            num_turns=1,
            stream_seal=seal(stream_file.read_bytes()),
            prompt_sha256=hashlib.sha256(sent).hexdigest() if sent else None,
            prompt_bytes=len(sent) if sent else None,
        )


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _driver(rig: Rig, **how: Any) -> ThroughTheCommand:  # noqa: ANN401
    return ThroughTheCommand(library=rig.library, answer_name=rig.task().answer.path, **how)


def _stopped(where: str, limit: tuple[str, int | None]) -> dict[str, Any]:
    """The first decomposition stopped by ``limit`` at its plan call or its plan's review."""
    return {"calls" if where == "call" else "reviews": {1: limit}}


def _by_the_command(
    rig: Rig,
    driver: ThroughTheCommand,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any]]:
    """``physgate harness-round`` started once, its trials made by ``driver``: exit and line."""
    with monkeypatch.context() as patch:
        patch.setattr(harness_round, "CommandDriver", lambda: driver)
        patch.setattr("physgate.evaluation.harness_round_cli._score", _score)
        capsys.readouterr()
        code = main(
            [
                "harness-round",
                *("--store", str(rig.made.store), "--role", "control"),
                *("--version", rig.made.version, "--tier", "visible", "--trials", "1"),
                *("--seed-base", "100", "--tasks", "1"),
                *("--params", str(rig.params), "--run-root", str(rig.run_root)),
                *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
                *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
            ]
        )
        lines = capsys.readouterr().out.strip().splitlines()
    return code, (json.loads(lines[-1]) if lines else {})


def _again(
    rig: Rig, driver: StandInDriver, at: datetime, *, limit_reset: bool = False
) -> tuple[str, dict[str, Any]]:
    """The round started again at ``at`` (its clock and the runs' alike)."""
    driver.clock = lambda: at
    status, summary = run_round(
        rig.inputs(trials=1),
        driver=driver,
        scorer=_score,
        resume=True,
        limit_reset=limit_reset,
        sleep=lambda _: None,
        now=lambda: at,
    )
    return status, summary


def _place(rig: Rig) -> Path:
    summary = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    return withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / str(summary["round"])


def _ledger(rig: Rig, kind: str | None = None) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in (_place(rig) / LEDGER).read_bytes().splitlines()]
    return [x for x in lines if kind is None or x["kind"] == kind]


def _outcomes(rig: Rig) -> list[str]:
    path = rig.root / "out" / "visible.trials.jsonl"
    return (
        [json.loads(x)["outcome"] for x in path.read_text().splitlines()] if path.exists() else []
    )


def _directory(rig: Rig, name: str) -> Path:
    return rig.run_root / _place(rig).name / name


def _recorded(run_dir: Path) -> tuple[str, UsageLimit | None]:
    """When the core recorded the decomposition stopped, and the limit it recorded with it.

    The failed decomposition's halt, where a run's record was opened; otherwise the end line of
    the rounds that ended void on the limit, as the journal holds it.
    """
    log = run_dir / "events.jsonl"
    if log.exists():
        (halt,) = [e for e in read_events(log) if isinstance(e, Halted)]
        assert halt.reason == "decomposition_failed"
        assert halt.detail.split(":", 1)[0] == "usage_limit", halt.detail
        return halt.ts, halt.usage_limit
    on_limit = rounds_on_the_limit(run_dir)
    assert on_limit is not None, "the rounds did not end on the limit"
    return on_limit


def _spent(where: str) -> int:
    """What the stopped decomposition spent, as its client reported it."""
    return SPENT.total() if where == "call" else PLANNED.total() + REVIEWED.total()


def _stamp(epoch: int) -> str:
    return utc_stamp(datetime.fromtimestamp(epoch, UTC))


def _waiting(rig: Rig) -> dict[str, Any]:
    written = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    waiting: dict[str, Any] = written.get("waiting") or {}
    return waiting


def _stopped_and_named(
    rig: Rig,
    driver: ThroughTheCommand,
    where: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The first start: the command exits 75; the trial named, not counted; its ``limit`` line."""
    code, printed = _by_the_command(rig, driver, monkeypatch, capsys)
    assert driver.exits == [WAITING], driver.exits
    assert code == WAITING, printed
    assert printed.get("status") == "waiting_for_limit", printed
    # Not an attempt, not counted, not unscored: nothing superseded, assembled or scored.
    assert _ledger(rig, "superseded") == [] and _ledger(rig, "assembled") == []
    assert _ledger(rig, "left") == []
    assert _outcomes(rig) == []
    lines = _ledger(rig, "limit")
    assert [(x["attempt"], x["tokens"]) for x in lines] == [(1, _spent(where))], lines
    return printed, lines[0]


def _made_again_and_counted(rig: Rig, late: StandInDriver, at: datetime, spent: int) -> None:
    """A start after the instant: one fresh directory, a counted pass, and the limit named apart."""
    status, said = _again(rig, late, at)
    assert status == "done", said
    assert [c.run_dir.name for c in late.decomposed] == ["0000-2"]
    placed = [x for x in _ledger(rig, "placed") if x["attempt"] == 2]
    assert [x.get("limit_reset") for x in placed] == ["waited"]
    assert _outcomes(rig) == ["pass"]
    record = json.loads((_place(rig) / ROUND_RECORD).read_bytes())
    assert record["superseded"] == []
    assert [(x["attempt"], x["tokens"]) for x in record["usage_limit"]] == [(1, spent)]


# -- the reset the core read ---------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "where"), SHAPES)
def test_a_stopped_decomposition_waits_for_the_reset_the_core_read_and_is_then_made_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    where: str,
) -> None:
    rig = make_rig(tmp_path, design_review=mode)
    epoch = int(time.time()) + 2 * 3600
    reset = _stamp(epoch)
    first = _driver(rig, **_stopped(where, ("five_hour", epoch)))
    printed, line = _stopped_and_named(rig, first, where, monkeypatch, capsys)
    stopped_at, limit = _recorded(_directory(rig, "0000-1"))
    assert limit is not None and limit.resets_at == reset, limit
    # The core's reset, not the stated wait after the halt: the word does not let it on sooner.
    waiting = {"index": 0, "why": "usage_limit", "resume_after": reset, "word_helps": False}
    assert printed.get("waiting") == waiting
    assert _waiting(rig) == waiting
    assert (line.get("halted_at"), line.get("resume_after")) == (stopped_at, reset)
    # Started again a minute before the reset, with the person's word: nothing is made.
    held = (_place(rig) / LEDGER).read_bytes()
    early = _driver(rig)
    status, said = _again(rig, early, stamped(reset) - timedelta(minutes=1), limit_reset=True)
    assert status == "waiting_for_limit", said
    assert early.decomposed == [] and early.drives == []
    assert (_place(rig) / LEDGER).read_bytes() == held
    # A minute after the reset, hours before the stated wait after the halt would have ended.
    later = stamped(reset) + timedelta(minutes=1)
    assert later < stamped(stopped_at) + UNREAD_RESET_WAIT
    _made_again_and_counted(rig, _driver(rig), later, _spent(where))


@pytest.mark.parametrize(("mode", "where"), [("off", "call"), ("on", "call")])
def test_a_reset_read_beyond_the_stated_wait_is_waited_for_past_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    where: str,
) -> None:
    rig = make_rig(tmp_path, design_review=mode)
    epoch = int(time.time()) + 7 * 3600
    reset = _stamp(epoch)
    first = _driver(rig, **_stopped(where, ("seven_day", epoch)))
    _stopped_and_named(rig, first, where, monkeypatch, capsys)
    stopped_at, _ = _recorded(_directory(rig, "0000-1"))
    # Past the stated wait after the halt and before the reset: nothing is made.
    between = stamped(stopped_at) + UNREAD_RESET_WAIT + timedelta(minutes=1)
    assert between < stamped(reset)
    early = _driver(rig)
    status, said = _again(rig, early, between)
    assert status == "waiting_for_limit", said
    assert early.decomposed == []
    assert said.get("waiting", {}).get("resume_after") == reset
    _made_again_and_counted(rig, _driver(rig), stamped(reset) + timedelta(seconds=1), _spent(where))


# -- no reset read -------------------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "where"), SHAPES)
def test_a_stopped_decomposition_with_no_reset_read_waits_the_stated_wait_after_it_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    where: str,
) -> None:
    rig = make_rig(tmp_path, design_review=mode)
    first = _driver(rig, **_stopped(where, ("five_hour", None)))
    printed, line = _stopped_and_named(rig, first, where, monkeypatch, capsys)
    stopped_at, limit = _recorded(_directory(rig, "0000-1"))
    assert limit is not None and limit.resets_at is None, limit
    after = utc_stamp(stamped(stopped_at) + UNREAD_RESET_WAIT)
    waiting = {"index": 0, "why": "usage_limit", "resume_after": after, "word_helps": True}
    assert printed.get("waiting") == waiting
    assert (line.get("halted_at"), line.get("resume_after")) == (stopped_at, after)
    held = (_place(rig) / LEDGER).read_bytes()
    early = _driver(rig)
    status, said = _again(rig, early, stamped(after) - timedelta(minutes=1))
    assert status == "waiting_for_limit", said
    assert early.decomposed == [] and (_place(rig) / LEDGER).read_bytes() == held
    _made_again_and_counted(rig, _driver(rig), stamped(after) + timedelta(seconds=1), _spent(where))


# -- an observed review on the limit is no stop --------------------------------------------------


def test_an_observed_plan_review_on_the_limit_starts_the_run_and_the_trial_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(tmp_path, design_review="observe")
    driver = _driver(rig, reviews={1: ("five_hour", int(time.time()) + 2 * 3600)})
    code, printed = _by_the_command(rig, driver, monkeypatch, capsys)
    # An observed review's end never holds the run: it starts, and the round goes on with it.
    assert driver.exits == [0]
    assert code == 0, printed
    assert _ledger(rig, "limit") == [] and _ledger(rig, "superseded") == []
    assert _outcomes(rig) == ["pass"]
    events = read_events(_directory(rig, "0000-1") / "events.jsonl")
    (ran,) = [e for e in events if e.kind == "design_review_ran"]
    unavailable = getattr(ran, "unavailable", None)
    assert unavailable is not None and unavailable.usage_limit is not None


# -- the journal's spend, as the round reads it --------------------------------------------------

#: Round journals as the writer before the limit was carried wrote them (that tree's own replan
#: rig, a plan reviewed): a plan call ended on an API error, and a plan review on infrastructure,
#: as a call and a review the limit stopped were recorded then.
BEFORE = Path(__file__).resolve().parent / "journals_before_the_limit"


def test_the_spend_is_read_from_a_journal_whose_end_line_carries_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig(tmp_path, design_review="on")
    driver = _driver(rig, reviews={1: ("five_hour", int(time.time()) + 2 * 3600)})
    _by_the_command(rig, driver, monkeypatch, capsys)
    assert driver.exits[:1] == [WAITING]
    run_dir = _directory(rig, "0000-1")
    raw = (run_dir / ROUNDS_JOURNAL).read_bytes().splitlines()
    ended = [json.loads(x) for x in raw if json.loads(x)["kind"] == "round_ended"]
    assert [("usage_limit" in x) for x in ended] == [True]
    # Every line read: the cause the rounds ended on, and the call's and the review's spend.
    assert journal_spend(run_dir) == ("usage_limit", PLANNED.total() + REVIEWED.total())


@pytest.mark.parametrize(
    ("name", "read"), [("call", ("api_error", 20)), ("review", ("infrastructure", 30))]
)
def test_the_spend_is_read_from_a_journal_written_before_the_limit_was_carried(
    tmp_path: Path, name: str, read: tuple[str, int]
) -> None:
    run_dir = tmp_path / name
    shutil.copytree(BEFORE / name, run_dir)
    assert journal_spend(run_dir) == read
    # Such rounds ended on no limit the journal names: the round reads them as it always has.
    assert rounds_on_the_limit(run_dir) is None
