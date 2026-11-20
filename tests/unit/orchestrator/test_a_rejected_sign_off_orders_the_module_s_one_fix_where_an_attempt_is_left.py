"""A rejected sign-off orders the module's one fix, where an attempt is left (ARCH-130, ARCH-133).

In a run that acts, a person's reject of a module's sign-off item reopens the module for one fix,
outside its repair budget: a fresh session of its role, told by a fixed template the values the
person did not sign and the note, gated and reviewed like any attempt, its reviewer told a person
ordered it. If it merges, the module's next item is raised on the values it merged; if not, its
end is recorded, its earlier merge stands, and the run ends with the sign-off owed. The fix is
once per module per run: a reject of a later item records only, and so does one where the module
has no attempt left, as attempt numbers stop at the run's last, or where the integration call is
made. Each item says which, as the record gave it where it was raised, and replay refuses a
decision, a reopen or an end the record does not allow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import refusal
from loop_fakes import FakeGate, FakeReviewer
from sign_off_rig import (
    CLOSING,
    CONTROL,
    ELECTRICAL,
    JournalGraph,
    journal_rig,
    journal_start,
    plant,
)
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_sign_off_item_is_raised_by_code_at_every_clean_merge_that_owes_one import (
    FIRST,
    approving,
    completions,
    lines,
)
from test_a_sign_off_owed_holds_the_integration_call_and_refuses_a_declaration_of_its_module import (  # noqa: E501
    calls,
    drive,
    resume,
)

from physgate.orchestrator.escalation import TO_THE_QUEUE, bind
from physgate.orchestrator.escalation_state import escalation_state
from physgate.orchestrator.events import (
    AttemptRejected,
    DecisionTaken,
    Escalated,
    EscalationDecided,
    Event,
    FollowUpEnded,
    GateRan,
    Merged,
    NoFollowUpOwed,
    SignOffFixEnded,
    SubtaskReopened,
    read_events,
)
from physgate.orchestrator.protocols import PersonOrder
from physgate.orchestrator.queue import QueueItem, read_queue, sign_off_item_id
from physgate.orchestrator.queue_words import decision_sentences
from physgate.orchestrator.repair import sign_off_fix_instruction
from physgate.orchestrator.replay import Step, replay
from physgate.reviewers.packet import fits_one_read, person_order_text

NOTE = "the phase margin is taken on the loop before the filter"
SECOND = sign_off_item_id("run-1", CONTROL, 2)
THIRD = sign_off_item_id("run-1", CONTROL, 3)
FOURTH = sign_off_item_id("run-1", CONTROL, 4)


def rejecting(tmp_path: Path, item_id: str = FIRST) -> Any:  # noqa: ANN401
    """A person rejecting ``item_id`` with :data:`NOTE` while a later session runs."""
    return lambda: decide(tmp_path, "reject", NOTE, item_id=item_id)


def taken(events: list[Event], item_id: str) -> list[DecisionTaken]:
    return [e for e in events if isinstance(e, DecisionTaken) and e.item_id == item_id]


def reopens(events: list[Event]) -> list[SubtaskReopened]:
    return [e for e in events if isinstance(e, SubtaskReopened)]


def item(run_dir: Path, item_id: str) -> QueueItem:
    return next(i for i in read_queue(run_dir).items if i.item_id == item_id)


def gated(events: list[Event], subtask_id: str) -> list[int]:
    return [e.attempt for e in events if isinstance(e, GateRan) and e.subtask_id == subtask_id]


def merged_at(events: list[Event], subtask_id: str) -> list[int]:
    return [e.attempt for e in events if isinstance(e, Merged) and e.subtask_id == subtask_id]


def _closing_moves_the_plant(graph: JournalGraph) -> None:
    """Sizing's closing pass changes the plant's mass, which constrains the control loop."""
    graph.writes[CLOSING] = [[plant(0.40)]]


def rewritten(events: list[Event], line: Event, **fields: Any) -> list[Event]:
    """``events`` with ``line``'s fields replaced, every other line as it was."""
    swapped = type(line).model_validate({**json.loads(line.model_dump_json()), **fields})
    return [swapped if e is line else e for e in events]


# --- the reject orders the one fix ------------------------------------------------------------


def test_a_reject_orders_the_module_s_one_fix_told_the_values_and_the_note(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = rejecting(tmp_path)
    events, step = drive(rig)
    first = item(tmp_path, FIRST)
    # The item said what a reject does, and the reject did it.
    assert first.consequence is not None
    assert first.consequence.on_reject == "reopen_fix"
    assert "to order the module's one fix" in first.decision_required
    said = decision_sentences(first)
    assert said is not None
    assert said["reject"].startswith("Rejecting orders the module's one fix")
    (decision,) = taken(events, FIRST)
    assert (decision.verb, decision.effect, decision.acts, decision.why_not) == (
        "reject",
        "reopen",
        True,
        None,
    )
    assert decision.reopens == CONTROL
    assert (decision.subtask_id, decision.attempt, decision.order_too_long) == (None, None, False)
    # The reopen is the next line about any subtask: the item, the view, the module's last merge.
    (reopen,) = reopens(events)
    # Only the merged worktree's removal comes between: the fix works in a fresh one.
    assert [e.kind for e in events[decision.seq + 1 : reopen.seq]] == ["worktree_removed"]
    (merge,) = [e for e in events if isinstance(e, Merged) and e.subtask_id == CONTROL][:1]
    assert (reopen.subtask_id, reopen.item_id, reopen.shown_sha256) == (
        CONTROL,
        FIRST,
        decision.shown_sha256,
    )
    assert (reopen.merge_commit, reopen.attempt, reopen.cause) == (merge.merge_commit, 2, None)
    # One session of the module's role, told by the template what it did not sign, and why.
    (request,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == (CONTROL, 2)]
    told = sign_off_fix_instruction(FIRST, 1, first.artefact_diff, NOTE)
    assert request.repair_instruction == told
    assert request.kind == "fix"
    assert request.assigned_role == "control"
    # Gated and reviewed as any attempt; its reviewer told a person ordered it, and what.
    assert gated(events, CONTROL) == [1, 2]
    (artefact,) = [a for a in rig.reviewer.seen if (a.subtask_id, a.attempt) == (CONTROL, 2)]
    order = artefact.ordered_by_person
    assert order == PersonOrder(kind="sign_off_fix", item_id=FIRST, of_attempt=1, instruction=told)
    # Merged: the module's next item is raised on the values the fix merged, and the run waits.
    assert merged_at(events, CONTROL) == [1, 2]
    raised = [(e.subtask_id, e.attempt, i.item_id) for e in lines(events) for i in e.raised]
    assert raised == [(CONTROL, 1, FIRST), (CONTROL, 2, SECOND)]
    assert step.kind == "wait"
    state = replay(events)
    assert state.next_step() == Step(kind="wait")
    assert state.undecided(SECOND)
    assert calls(events) == []
    # The person signs the fix's values; the module is then complete.
    decide(tmp_path, "approve", NOTE, item_id=SECOND)
    events, step = resume(rig)
    assert step.kind == "done"
    assert replay(events).signed == [SECOND]
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_a_reject_before_the_closing_pass_is_fixed_first_and_the_follow_up_comes_after_it(
    tmp_path: Path,
) -> None:
    rig, graph = journal_rig(tmp_path)
    _closing_moves_the_plant(graph)
    # Rejected while the electrical module's session runs: taken before sizing's closing pass.
    rig.dispatcher.during[3] = rejecting(tmp_path)
    events, step = drive(rig, closing=True)
    fix, follow_up = reopens(events)
    assert (fix.subtask_id, fix.attempt, fix.item_id, fix.cause) == (CONTROL, 2, FIRST, None)
    assert (follow_up.subtask_id, follow_up.attempt, follow_up.cause) == (CONTROL, 3, "follow_up")
    closing = next(e for e in events if isinstance(e, Merged) and e.subtask_id == CLOSING)
    fixed = next(
        e for e in events if isinstance(e, Merged) and (e.subtask_id, e.attempt) == (CONTROL, 2)
    )
    assert fixed.seq < closing.seq < follow_up.seq
    # The follow-up is code's, told its edges; the fix's order is its own attempt's alone.
    (request,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == (CONTROL, 3)]
    assert request.kind == "attempt"
    (artefact,) = [a for a in rig.reviewer.seen if (a.subtask_id, a.attempt) == (CONTROL, 3)]
    assert artefact.ordered_by_person is not None
    assert artefact.ordered_by_person.kind == "follow_up"
    # Each merge raised the module's next item: the fix's, the closing pass's, the follow-up's.
    raised = [(e.subtask_id, i.item_id) for e in lines(events) for i in e.raised]
    assert raised == [(CONTROL, FIRST), (CONTROL, SECOND), (CLOSING, THIRD), (CONTROL, FOURTH)]
    state = replay(events)
    assert state.superseded == {SECOND: THIRD, THIRD: FOURTH}
    assert step.kind == "wait"
    # Its fix is spent: the latest item says a reject of it records only.
    latest = item(tmp_path, FOURTH)
    assert latest.consequence is not None
    assert latest.consequence.on_reject == "record_only"
    assert "ordered already in this run" in latest.decision_required
    decide(tmp_path, "approve", NOTE, item_id=FOURTH)
    events, step = resume(rig)
    assert step.kind == "done"
    assert completions(events) == [CONTROL, ELECTRICAL]


@pytest.mark.parametrize("by", ["gate", "review"])
def test_a_fix_its_gate_or_review_rejects_ends_and_the_run_ends_with_the_sign_off_owed(
    tmp_path: Path, by: str
) -> None:
    # The fix is the fourth attempt judged, after sizing's, the control module's and the electrical.
    failing = ["pass", "pass", "pass", "fail"]
    gate = FakeGate(verdicts=failing) if by == "gate" else FakeGate()
    reviewer = FakeReviewer(verdicts=failing) if by == "review" else FakeReviewer()
    rig, _ = journal_rig(tmp_path, gate=gate, reviewer=reviewer)
    rig.dispatcher.during[3] = rejecting(tmp_path)
    events, step = drive(rig)
    (rejected,) = [e for e in events if isinstance(e, AttemptRejected) and e.subtask_id == CONTROL]
    assert (rejected.attempt, rejected.finding.source) == (2, by)
    # No retry, no escalation question, no queue item: its end, then the run goes on.
    (end,) = [e for e in events if isinstance(e, SignOffFixEnded)]
    assert (end.subtask_id, end.attempt, end.why) == (CONTROL, 2, "rejected")
    assert end.seq == rejected.seq + 1
    assert not [e for e in events if isinstance(e, EscalationDecided) and e.subtask_id == CONTROL]
    assert not [e for e in events if isinstance(e, Escalated)]
    assert merged_at(events, CONTROL) == [1]
    assert [i.item_id for e in lines(events) for i in e.raised] == [FIRST]
    state = replay(events)
    # The earlier merge stands; the module is not complete, and the run ends naming its sign-off.
    assert state.subtasks[CONTROL].status == "done"
    assert state.sign_offs_open() == [CONTROL]
    assert not [e for e in events if isinstance(e, NoFollowUpOwed)]
    assert len(calls(events)) == 1
    assert completions(events) == [ELECTRICAL]
    assert step.kind == "escalated"
    (line,) = [ln for ln in state.ledger if ln.id == CONTROL][-1:]
    first_merge = next(e for e in events if isinstance(e, Merged) and e.subtask_id == CONTROL)
    assert (line.merge_commit, line.gate_result, line.review_result) == (
        first_merge.merge_commit,
        "pass",
        "pass",
    )


def test_a_reject_of_the_fix_s_item_records_only_the_fix_is_once_per_module_per_run(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = rejecting(tmp_path)
    _, step = drive(rig)
    assert step.kind == "wait"
    second = item(tmp_path, SECOND)
    assert second.consequence is not None
    assert second.consequence.on_reject == "record_only"
    assert "Its one fix after a rejected sign-off was ordered already in this run" in (
        second.decision_required
    )
    decide(tmp_path, "reject", NOTE, item_id=SECOND)
    events, step = resume(rig)
    (decision,) = taken(events, SECOND)
    assert (decision.effect, decision.acts, decision.why_not, decision.reopens) == (
        "none",
        False,
        "record_only_source",
        None,
    )
    assert len(reopens(events)) == 1
    assert step.kind == "escalated"
    assert replay(events).sign_offs_open() == [CONTROL]
    assert completions(events) == [ELECTRICAL]


# --- where no attempt is left -------------------------------------------------------------------


def test_a_reject_where_the_module_is_at_the_last_attempt_number_records_only(
    tmp_path: Path,
) -> None:
    # The control module merges at its third attempt, its follow-up at its fourth, the last.
    rig, graph = journal_rig(tmp_path, gate=FakeGate(verdicts=["pass", "fail", "fail"]))
    _closing_moves_the_plant(graph)
    events, step = drive(rig, closing=True)
    assert merged_at(events, CONTROL) == [3, 4]
    assert step.kind == "wait"
    latest = item(tmp_path, THIRD)
    assert latest.consequence is not None
    assert latest.consequence.on_reject == "record_only"
    assert "It has no attempt left to fix them at" in latest.decision_required
    decide(tmp_path, "reject", NOTE, item_id=THIRD)
    events, step = resume(rig)
    (decision,) = taken(events, THIRD)
    assert (decision.effect, decision.why_not) == ("none", "record_only_source")
    assert [r.cause for r in reopens(events)] == ["follow_up"]
    assert step.kind == "escalated"
    assert replay(events).sign_offs_open() == [CONTROL]


def test_a_reject_where_the_module_merged_on_its_one_fix_after_a_blocked_review_records_only(
    tmp_path: Path,
) -> None:
    # The control module's first review blocks; the person orders its one fix, which merges.
    rig, _ = journal_rig(tmp_path, reviewer=FakeReviewer(results={2: blocked_review()}))
    events, _ = drive(rig)
    assert [e.item_id for e in events if isinstance(e, Escalated)] == [f"run-1-{CONTROL}"]
    decide(tmp_path, "reject", "the pole is the plant's own", item_id=f"run-1-{CONTROL}")
    events, step = resume(rig)
    assert merged_at(events, CONTROL) == [2]
    assert step.kind == "wait"
    # The fix a blocked review ordered is the subtask's last attempt: no fix of its sign-off.
    first = item(tmp_path, FIRST)
    assert first.consequence is not None
    assert first.consequence.on_reject == "record_only"
    assert "It has no attempt left to fix them at" in first.decision_required
    decide(tmp_path, "reject", NOTE, item_id=FIRST)
    events, step = resume(rig)
    (decision,) = taken(events, FIRST)
    assert (decision.effect, decision.why_not) == ("none", "record_only_source")
    assert step.kind == "escalated"


def test_a_module_fixed_at_the_last_attempt_number_is_owed_no_follow_up(tmp_path: Path) -> None:
    # Merged at its third attempt, rejected, fixed at its fourth: the closing pass then reaches it,
    # and no follow-up can reopen it past the last attempt number.
    rig, graph = journal_rig(tmp_path, gate=FakeGate(verdicts=["pass", "fail", "fail"]))
    _closing_moves_the_plant(graph)
    rig.dispatcher.during[5] = rejecting(tmp_path)
    events, step = drive(rig, closing=True)
    (fix,) = reopens(events)
    assert (fix.attempt, fix.item_id) == (4, FIRST)
    assert merged_at(events, CONTROL) == [3, 4]
    # The integration step finds none owed and says so; the person then signs the latest values.
    assert len([e for e in events if isinstance(e, NoFollowUpOwed)]) == 1
    assert step.kind == "wait"
    decide(tmp_path, "approve", NOTE, item_id=THIRD)
    events, step = resume(rig)
    assert step.kind == "done"
    assert completions(events) == [CONTROL, ELECTRICAL]


# --- where the record no longer allows the fix the item said --------------------------------


def test_a_reject_taken_while_its_module_is_reopened_by_its_follow_up_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, graph = journal_rig(tmp_path)
    _closing_moves_the_plant(graph)
    loop = journal_start(rig, closing=True)
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def rejects_after_the_follow_up(event: Event) -> None:
        emit(event)
        if isinstance(event, SubtaskReopened) and event.cause is not None:
            decide(tmp_path, "reject", NOTE, item_id=SECOND)

    monkeypatch.setattr(loop, "_emit", rejects_after_the_follow_up)
    step = loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    # The item said a reject orders the fix; the follow-up reopened the module before the decision
    # was taken, so what it said is no longer true, and the reject records only.
    assert item(tmp_path, SECOND).consequence is not None
    (decision,) = taken(events, SECOND)
    (follow_up,) = reopens(events)
    assert follow_up.seq < decision.seq
    assert (decision.effect, decision.acts, decision.why_not) == ("none", False, "superseded")
    assert step.kind == "wait"
    replay(events)


def test_a_reject_after_its_module_s_follow_up_ended_unmerged_records_only(tmp_path: Path) -> None:
    # Sizing, the control module, the electrical, the closing pass pass the gate; the follow-up
    # does not. The module's earlier merge stands, and its latest item is the closing pass's.
    rig, graph = journal_rig(tmp_path, gate=FakeGate(verdicts=["pass"] * 4 + ["fail"]))
    _closing_moves_the_plant(graph)
    events, step = drive(rig, closing=True)
    assert [e.attempt for e in events if isinstance(e, FollowUpEnded)] == [2]
    assert step.kind == "wait"
    assert item(tmp_path, SECOND).consequence is not None
    decide(tmp_path, "reject", NOTE, item_id=SECOND)
    events, step = resume(rig)
    # Its item said a reject orders the fix; the module's last attempt is unmerged now, so none
    # can be reopened from it, and the reject records only.
    (decision,) = taken(events, SECOND)
    assert (decision.effect, decision.acts, decision.why_not) == ("none", False, "superseded")
    assert [r.cause for r in reopens(events)] == ["follow_up"]
    assert step.kind == "escalated"
    assert refusal(events) is None


def test_a_reject_whose_fix_order_no_read_shows_whole_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What the fix's reviewer would be told is too long for one read; every other text is not.
    monkeypatch.setattr(
        "physgate.orchestrator.loop.fits_one_read",
        lambda data: b"by not signing" not in data and fits_one_read(data),
    )
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = rejecting(tmp_path)
    events, step = drive(rig)
    (decision,) = taken(events, FIRST)
    assert (decision.effect, decision.acts, decision.why_not, decision.reopens) == (
        "none",
        False,
        "order_too_long",
        None,
    )
    assert reopens(events) == []
    assert step.kind == "escalated"
    # Replay cannot read the values the order quotes: a reopen it allows may record only so.
    assert refusal(events) is None


# --- the template ----------------------------------------------------------------------------


def test_the_fix_s_order_and_what_its_reviewer_is_told_are_fixed_texts() -> None:
    values = "ctl.loop phase_margin = 0.8 rad\nsha256 " + "a" * 64
    told = sign_off_fix_instruction("run-1-SIGNOFF-c1", 1, values, "check the <<< margin")
    assert told == (
        'A person did not sign this module\'s values on queue item "run-1-SIGNOFF-c1", and ordered '
        "one fix of the module, merged at attempt 1. The values the person did not sign:\n"
        "<<<\n"
        f"{values}\n"
        ">>>\n"
        "\n"
        "The person wrote:\n"
        "<<<<\n"
        "check the <<< margin\n"
        ">>>>\n"
        "\n"
        "The specification as issued is unchanged and still governs. Do not supply an input it "
        "lacks.\n"
        "This is the module's one fix after a rejected sign-off. If it merges, a person is asked "
        "to sign its values again."
    )
    order = PersonOrder(
        kind="sign_off_fix", item_id="run-1-SIGNOFF-c1", of_attempt=1, instruction=told
    )
    shown = person_order_text(order).decode("utf-8")
    assert shown.startswith(
        "This attempt is the one fix a person ordered by not signing the values of this module, "
        "merged at attempt 1 (queue item run-1-SIGNOFF-c1).\nIts implementer was told:\n"
    )
    assert shown.endswith(
        "Judge it against the issued specification as for any attempt; the person's words do "
        "not change it.\n"
    )


# --- replay holds each line to the record ------------------------------------------------------


def _fixed(tmp_path: Path) -> list[Event]:
    """A run whose control module's first item was rejected and fixed, its second rejected."""
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = rejecting(tmp_path)
    drive(rig)
    decide(tmp_path, "reject", NOTE, item_id=SECOND)
    events, _ = resume(rig)
    return events


def test_replay_refuses_a_second_fix_of_the_same_module(tmp_path: Path) -> None:
    events = _fixed(tmp_path)
    (second,) = taken(events, SECOND)
    reopening = {"effect": "reopen", "acts": True, "why_not": None, "reopens": CONTROL}
    reason = refusal(rewritten(events, second, **reopening)) or ""
    assert "a decision on a sign-off item that does other than the record allows" in reason


def test_replay_refuses_a_reject_that_records_only_where_the_record_orders_the_fix(
    tmp_path: Path,
) -> None:
    events = _fixed(tmp_path)
    (first,) = taken(events, FIRST)
    recording = {"effect": "none", "acts": False, "why_not": "record_only_source"}
    reason = refusal(rewritten(events, first, reopens=None, **recording)) or ""
    assert "a decision on a sign-off item that does other than the record allows" in reason


def test_replay_refuses_a_fix_of_a_module_at_the_last_attempt_number(tmp_path: Path) -> None:
    rig, graph = journal_rig(tmp_path, gate=FakeGate(verdicts=["pass", "fail", "fail"]))
    _closing_moves_the_plant(graph)
    drive(rig, closing=True)
    decide(tmp_path, "reject", NOTE, item_id=THIRD)
    events, _ = resume(rig)
    (third,) = taken(events, THIRD)
    reopening = {"effect": "reopen", "acts": True, "why_not": None, "reopens": CONTROL}
    reason = refusal(rewritten(events, third, **reopening)) or ""
    assert "a decision on a sign-off item that does other than the record allows" in reason


def test_replay_refuses_an_order_too_long_where_the_record_orders_no_fix(tmp_path: Path) -> None:
    events = _fixed(tmp_path)
    (second,) = taken(events, SECOND)
    reason = refusal(rewritten(events, second, why_not="order_too_long")) or ""
    assert "a decision on a sign-off item that does other than the record allows" in reason


def test_replay_refuses_a_fix_s_end_on_an_attempt_that_is_no_failed_fix(tmp_path: Path) -> None:
    events = _fixed(tmp_path)
    merged = next(
        e for e in events if isinstance(e, Merged) and (e.subtask_id, e.attempt) == (CONTROL, 2)
    )
    diff = events[merged.seq + 1]
    end = SignOffFixEnded(
        seq=0, ts=diff.ts, run_id=diff.run_id, gate_mode=diff.gate_mode,
        subtask_id=CONTROL, attempt=2, why="rejected",
    )  # fmt: skip
    at = merged.seq + 2
    assert "a sign-off fix's end" in (refusal([*events[:at], end, *events[at:]]) or "")
    # Before its merge, while it is still being judged, as on the module's first attempt.
    gate = next(
        e for e in events if isinstance(e, GateRan) and (e.subtask_id, e.attempt) == (CONTROL, 1)
    )
    early = end.model_copy(update={"attempt": 1})
    assert refusal([*events[: gate.seq + 1], early, *events[gate.seq + 1 :]]) is not None


def test_replay_refuses_a_follow_up_s_end_for_a_fix_and_an_escalation_question_on_it(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path, gate=FakeGate(verdicts=["pass", "pass", "pass", "fail"]))
    rig.dispatcher.during[3] = rejecting(tmp_path)
    events, _ = drive(rig)
    (end,) = [e for e in events if isinstance(e, SignOffFixEnded)]
    as_follow_up = FollowUpEnded.model_validate({**end.model_dump(), "kind": "follow_up_ended"})
    swapped = [as_follow_up if e is end else e for e in events]
    assert "a follow-up's end" in (refusal(swapped) or "")
    before = events[: end.seq]
    state = escalation_state(replay(before), CONTROL)
    envelope = {k: getattr(end, k) for k in ("seq", "ts", "run_id", "gate_mode")}
    asked = EscalationDecided(
        **envelope,
        subtask_id=CONTROL,
        attempt=2,
        decision=bind("rules").decide(TO_THE_QUEUE, state),
        state=state,
    )
    assert "an escalation decision" in (refusal([*before, asked]) or "")


def test_replay_refuses_a_reopen_of_the_module_no_reject_ordered(tmp_path: Path) -> None:
    events = _fixed(tmp_path)
    (first,) = taken(events, FIRST)
    assert "a reopen that no taken decision explains" in (
        refusal([e for e in events if e is not first]) or ""
    )


def test_a_run_that_records_decisions_orders_no_fix(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path, acts=False)
    rig.dispatcher.during[3] = approving(tmp_path, verb="reject")
    events, step = drive(rig, acts=False)
    assert item(tmp_path, FIRST).consequence is None
    assert not [e for e in events if isinstance(e, DecisionTaken)]
    assert reopens(events) == []
    assert step.kind == "escalated"
