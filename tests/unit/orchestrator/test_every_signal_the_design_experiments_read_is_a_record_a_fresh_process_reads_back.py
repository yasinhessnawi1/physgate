"""Every signal the two design experiments read is a record a fresh process reads back.

The plan-only experiment reads each round of a reviewed decomposition: the arm from the recorded
configuration, each round's proposal and review line, the tokens of each round's sessions, each
round's plan file, the plan's item and the line that holds the run on it, the count of re-plans,
and, from the round journal, each round's canary result and monotonic times. An attempt that ended
void has no run record, so its rounds are read from the journal alone, its arm included. The
downstream experiment reads, in a run started from a reviewed plan, each dispute and its ruling,
each contract result and whether it was the first, each module's completion, integration's issued
state, and the attempt, rejection, gate and review lines, an integration failure among them, all
in one log whose one decomposition line names the reviewed plan's digest.

Each is read here from the files a fresh process opens: the run's configuration and event log
through the record, which replays the log and holds the journal to it, or the journal through its
own reader. Nothing is taken from the process that wrote them.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as runner
from journal_helper import one_round, plan_digest
from loop_fakes import FakeGate, FakeReviewer, usage
from replan_rig import RUBRIC, Step, decompose, item_of

from physgate import roles
from physgate.orchestrator.design_rounds import RoundEnded, RoundsEnded, RoundStarted, read_journal
from physgate.orchestrator.dispute import Dispute
from physgate.orchestrator.events import Event
from physgate.orchestrator.protocols import MessageUsage, QuantityRef, ReviewResult, Usage
from physgate.orchestrator.record import DecompositionCall, PlanReviewed, ReviewInstall, RunRecord
from physgate.orchestrator.replay import RunState
from physgate.orchestrator.run_config import ModelStrings, RunConfig, load_run_config
from physgate.orchestrator.trajectory import seal

STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


def _of(events: list[Event], kind: str) -> list[Any]:
    return [e for e in events if e.kind == kind]


def _fresh(run_dir: Path) -> tuple[RunConfig, list[Event], RunState, list[str]]:
    """The run as a fresh process opens it: its config, its log, its replayed state, its items.

    Opening replays the log and holds the round journal to it, so each is read as checked.
    """
    record = RunRecord(load_run_config(run_dir / "run.json"), run_dir)
    try:
        items = [item.item_id for item in record.queue.items()]
        return record.config, list(record.log.events), record.state, items
    finally:
        record.close()


def _spent(events: list[Event], who: str) -> list[Any]:
    return [e for e in events if e.kind == "tokens_used" and e.attribution == who]


def _tokens(n: int) -> Usage:
    return Usage(
        input_tokens=n, output_tokens=n, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


def _usage_of(events: list[Event], who: str) -> list[tuple[str, Usage]]:
    """Each token line of ``who``: its message and what it spent."""
    return [(e.message_id, e.usage) for e in _spent(events, who)]


def test_a_completed_reviewed_decomposition_s_signals_are_lines_a_fresh_process_replays(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "repair:2", [Step(), Step(review="blocked"), Step(review="canary")])
    assert ran.code == 0, ran.code
    config, events, state, items = _fresh(ran.run_dir)
    # The arm: the recorded configuration, and the run's first line naming its mode.
    brief = hashlib.sha256((tmp_path / "brief.md").read_bytes()).hexdigest()
    assert (config.design_review, config.brief_sha256) == ("repair:2", brief)
    assert config.models.decomposition == "claude-sonnet-5"
    assert config.models.reviewers["design"] == "claude-opus-5-5"
    assert events[0].kind == "run_started" and events[0].design_review == "repair:2"
    # One proposal and one review line per round, each round's plan file its digest, and the
    # tokens of each round's call and review on lines of their own sessions.
    proposals, reviews = state.proposals, [*state.earlier_reviews, state.design_review]
    assert [p.round for p in proposals] == [r.round for r in reviews if r] == [1, 2, 3]
    assert len(proposals) - 1 == 2, "re-plans"
    kinds = ["fail", "blocked", "canary"]
    for proposal, review, kind in zip(proposals, reviews, kinds, strict=True):
        assert review is not None and review.result is not None
        assert (proposal.model, proposal.num_turns) == ("claude-sonnet-5", 1)
        assert all(STAMP.match(t) for t in (proposal.started, proposal.ended))
        assert all(STAMP.match(str(t)) for t in (review.started, review.ended))
        plan = ran.run_dir / "decomposition" / f"round-{proposal.round}" / "plan.json"
        assert hashlib.sha256(plan.read_bytes()).hexdigest() == proposal.plan_sha256
        assert review.plan_sha256 == proposal.plan_sha256
        assert review.result.reviewer_model == config.models.reviewers["design"]
        # The rubric it was judged by and its per-item results, on the line itself.
        assert review.result.rubric_sha256 == RUBRIC
        assert review.result.items == (item_of(proposal.round, kind),)
        # Each round's call and review spent what the script spent, by message, on its own lines.
        k = proposal.round
        assert _usage_of(events, f"decomposition:{proposal.session_id}") == [(f"d{k}", _tokens(10))]
        assert _usage_of(events, f"reviewer:{review.result.session_id}") == [(f"r{k}", _tokens(5))]
    assert [r.result.verdict for r in reviews if r and r.result] == ["fail", "blocked", "fail"]
    # The plan's item, and the review line that holds the run on it.
    held = reviews[-1]
    assert held is not None and held.held_item is not None
    assert items == [held.held_item]
    # From the journal, which the open held to the log: each round's canary and its times.
    journal = read_journal(ran.run_dir, last=3).lines
    ended = [line for line in journal if isinstance(line, RoundEnded)]
    assert [line.ending.canary for line in ended] == [None, None, "held_out"]
    for line in ended:
        assert line.elapsed.ended - line.elapsed.started >= 0
        assert line.elapsed.call_ended - line.elapsed.started >= 0


def test_a_round_with_no_plan_is_read_with_its_cause_and_the_halt_that_ends_the_run(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "repair:2", [Step(), Step(call="no_structured_output")])
    _, events, state, _ = _fresh(ran.run_dir)
    assert [(p.round, p.cause) for p in state.proposals] == [(1, None), (2, "no_structured_output")]
    assert state.proposals[0].plan_sha256 is not None and state.proposals[1].plan_sha256 is None
    assert state.last_halt is not None and state.last_halt.reason == "decomposition_failed"
    assert events[-1].kind == "halted" and not _of(events, "decomposed")


def test_a_review_that_reached_no_verdict_is_read_with_its_cause_and_its_hold(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "on", [Step(review="no_verdict")])
    assert ran.code == 0, ran.code
    _, events, state, items = _fresh(ran.run_dir)
    review = state.design_review
    assert review is not None and review.result is None and review.unavailable is not None
    assert review.unavailable.cause == "no_verdict"
    assert review.held_item is not None and items == [review.held_item]
    assert _usage_of(events, f"reviewer:{review.unavailable.session_id}") == [("r1", _tokens(5))]


def test_a_void_attempt_s_rounds_are_read_from_its_journal_alone(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:3", [Step(), Step(review="infrastructure")])
    assert not (ran.run_dir / "run.json").exists() and not (ran.run_dir / "events.jsonl").exists()
    journal = read_journal(ran.run_dir, last=4)
    assert journal.complete
    first, *rest = journal.lines
    brief = hashlib.sha256((tmp_path / "brief.md").read_bytes()).hexdigest()
    assert isinstance(first, RoundStarted)
    assert (first.design_review, first.decomposition_model, first.brief_sha256) == (
        "repair:3",
        "claude-sonnet-5",
        brief,
    )
    ended = [line for line in rest if isinstance(line, RoundEnded)]
    assert [line.round for line in ended] == [1, 2]
    for line in ended:
        assert line.plan_sha256 is not None and line.usage and line.num_turns >= 1
        plan = ran.run_dir / "decomposition" / f"round-{line.round}" / "plan.json"
        assert hashlib.sha256(plan.read_bytes()).hexdigest() == line.plan_sha256
        assert all(STAMP.match(str(t)) for t in (line.started, line.call_ended, line.ended))
        assert line.review is not None and line.review.session_id and line.review.usage
        assert line.elapsed.review_started is not None and line.review_started is not None
    assert ended[0].review.result is not None  # type: ignore[union-attr]
    assert ended[0].review.result.reviewer_model == "claude-opus-5-5"  # type: ignore[union-attr]
    assert ended[0].ending.canary is None
    assert ended[1].review.unavailable is not None  # type: ignore[union-attr]
    assert ended[1].review.unavailable.cause == "infrastructure"  # type: ignore[union-attr]
    terminal = journal.lines[-1]
    assert isinstance(terminal, RoundsEnded) and terminal.follows == "void"


DISPUTED = Dispute(
    position=QuantityRef(node_id="budget.supply", name="v", value=24, unit="V"),
    reason="the drive needs more headroom",
)
PLAN = b"the reviewed plan"


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def _downstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, integration: str) -> Path:
    """The contract rig's run, started from a plan its review passed under ``observe``.

    The drive's first attempt disputes sizing's supply and fails the gate; the firmware's first
    attempt is rejected by its reviewer; integration's system gate gives ``integration``.
    """
    rig = runner.rig_for(
        tmp_path,
        gate=FakeGate(verdicts=["pass", "fail"], integration_verdict=integration),
        reviewer=FakeReviewer(verdicts=["pass", "pass", "fail"]),
    )
    reviewers = {**dict.fromkeys(runner.ROLES, "claude-opus-5-5"), "design": "claude-opus-5-5"}
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(runner.ROLES, "claude-sonnet-5"),
        reviewers=reviewers,
    )
    rig.config_overrides |= {"models": models, "design_review": "observe"}
    checks, check = [], rig.changes.check

    def disputed_once(subtask_id: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if subtask_id == runner.DRIVE:
            checks.append(subtask_id)
            rig.changes.disputes[runner.DRIVE] = (DISPUTED,) if len(checks) == 1 else ()
        return check(subtask_id, *args, **kwargs)

    monkeypatch.setattr(rig.changes, "check", disputed_once)
    loop = rig.open()
    runner.hooked(monkeypatch, loop, declared=(runner.BUDGET, runner.DRIVE, runner.FW))
    stream = rig.run_dir / "decomposition" / "stdout.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"type": "assistant"}\n')
    spent = (MessageUsage(message_id="r1", usage=usage(5)),)
    passed = ReviewResult(
        verdict="pass",
        finding="the plan holds",
        reviewer_model="claude-opus-5-5",
        session_id="review-1",
        usage=spent,
    )
    install = ReviewInstall(path="/i", action="checked", seconds=0.0, entries=1)
    reviewed = PlanReviewed(
        install=install, stream_seal=seal(stream.read_bytes()), session_id="review-1",
        usage=spent, result=passed,
    )  # fmt: skip
    called = (MessageUsage(message_id="d1", usage=usage(10)),)
    proposals = one_round(
        rig.run_dir, session="decomposition", plan=PLAN, reviewed=reviewed, spent=called,
        design_review="observe", holds=False,
    )  # fmt: skip
    start = loop.record.start

    def reviewed_start(entries: Any, *, decomposed: Any, **_: Any) -> None:  # noqa: ANN401
        summary = decomposed.model_copy(update={"plan_sha256": plan_digest(PLAN)})
        call = DecompositionCall(session_id="decomposition", usage=called)
        start(entries, decomposed=summary, call=call, reviewed=reviewed, proposals=proposals)

    monkeypatch.setattr(loop.record, "start", reviewed_start)
    runner.start(loop, sizing=True)
    loop.run()
    loop.close()
    return rig.run_dir


@pytest.mark.parametrize("integration", ["pass", "fail"])
def test_every_downstream_signal_is_a_line_of_the_reviewed_plan_s_one_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, integration: str
) -> None:
    run_dir = _downstream(tmp_path, monkeypatch, integration)
    _, events, state, _ = _fresh(run_dir)
    # One decomposition line, naming the digest its round proposed and its review judged.
    [decomposed] = _of(events, "decomposed")
    [proposed] = _of(events, "plan_proposed")
    [review] = _of(events, "design_review_ran")
    assert decomposed.plan_sha256 == proposed.plan_sha256 == review.plan_sha256 == plan_digest(PLAN)
    assert state.plan_sha256 == decomposed.plan_sha256
    after = events[events.index(decomposed) + 1 :]
    # The dispute and its ruling, with its level.
    [dispute] = _of(after, "dispute_recorded")
    assert (dispute.subtask_id, dispute.position) == (runner.DRIVE, DISPUTED.position)
    [ruling] = _of(after, "arbitration_decided")
    assert (ruling.subtask_id, ruling.attempt, ruling.level) == (runner.DRIVE, 1, "gate")
    # The attempts, the gate failure and its repair, and the reviewer's rejection and its repair.
    gates = [(e.subtask_id, e.attempt, e.result.verdict) for e in _of(after, "gate_ran")]
    assert (runner.DRIVE, 1, "fail") in gates and (runner.DRIVE, 2, "pass") in gates
    reviewed = [(e.subtask_id, e.attempt, e.result.verdict) for e in _of(after, "review_ran")]
    assert (runner.FW, 1, "fail") in reviewed and (runner.FW, 2, "pass") in reviewed
    rejected = [(e.subtask_id, e.attempt) for e in _of(after, "attempt_rejected")]
    assert (runner.DRIVE, 1) in rejected and (runner.FW, 1) in rejected
    # Each contract result, the first of each pair marked, and a later one not.
    assert [e.first for e in _of(after, "contract_tested")] == [True, True, True, False]
    [system] = _of(after, "integration_gate_ran")
    assert system.result.verdict == integration
    if integration == "fail":
        assert _of(after, "integration_escalated")
        assert not _of(after, "module_completed") and not _of(after, "integration_state_issued")
        return
    [issued] = _of(after, "integration_state_issued")
    assert issued.subtask_id == runner.INTEG and issued.length > 0
    completed = [e.subtask_id for e in _of(after, "module_completed")]
    assert completed == [runner.BUDGET, runner.DRIVE, runner.FW]
