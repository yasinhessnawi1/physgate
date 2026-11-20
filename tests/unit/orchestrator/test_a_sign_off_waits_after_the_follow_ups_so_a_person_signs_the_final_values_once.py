"""A sign-off waits after the follow-ups, so a person signs the values the call is made on, once.

The follow-ups sizing's closing pass owes the domain modules are decided at the integration step,
from the journal, which replay cannot read. So where a run that acts has a sign-off undecided
there, the step decides them first: it writes each follow-up owed, or, where none is, a line
saying no follow-up is owed. Only then does the run wait for the person, who signs the values the
follow-ups left, on the module's latest item; every earlier item is superseded. Replay refuses
that line anywhere but there, a second one, and a follow-up after it; the loop holds it to the
journal as it holds a follow-up. A sign-off decided before the step needs no line, and a run that
records decisions never waits: neither writes it, and each keeps its lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import KilledError
from sign_off_rig import (
    CLOSING,
    CONTROL,
    ELECTRICAL,
    LOOP,
    PLANT,
    JournalGraph,
    journal_rig,
    journal_start,
    plant,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_sign_off_item_is_raised_by_code_at_every_clean_merge_that_owes_one import (
    FIRST,
    approving,
    completions,
    lines,
    refused,
)
from test_a_sign_off_owed_holds_the_integration_call_and_refuses_a_declaration_of_its_module import (  # noqa: E501
    calls,
    drive,
    resume,
)

from physgate.orchestrator.events import (
    DecisionTaken,
    Event,
    Incident,
    IntegrationGateSkipped,
    NoFollowUpOwed,
    OwedEdge,
    SignOffsRaised,
    SubtaskReopened,
    parse_events,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import sign_off_item_id
from physgate.orchestrator.replay import Step, replay

NOTE = "the margins are on the loop that runs"


def none_owed(events: list[Event]) -> list[NoFollowUpOwed]:
    return [e for e in events if isinstance(e, NoFollowUpOwed)]


def follow_ups(events: list[Event]) -> list[SubtaskReopened]:
    return [e for e in events if isinstance(e, SubtaskReopened) and e.cause is not None]


def inserted(events: list[Event], at: int, line: Event) -> list[Event]:
    """``events`` with ``line`` put in at index ``at`` and every line renumbered, as written."""
    records = [json.loads(e.model_dump_json()) for e in events]
    records.insert(at, json.loads(line.model_dump_json()))
    renumbered = [r | {"seq": n} for n, r in enumerate(records)]
    return parse_events(b"".join(json.dumps(r).encode() + b"\n" for r in renumbered), log="x")


def _closing_moves_the_plant(graph: JournalGraph) -> None:
    """Sizing's closing pass changes the plant's mass, which constrains the control loop."""
    graph.writes[CLOSING] = [[plant(0.40)]]


# --- the wait comes after the follow-ups ------------------------------------------------------


def test_the_wait_comes_after_the_follow_ups_and_the_person_signs_their_values_once(
    tmp_path: Path,
) -> None:
    rig, graph = journal_rig(tmp_path)
    _closing_moves_the_plant(graph)
    events, step = drive(rig, closing=True)
    # The control module's item is undecided at the integration step: the follow-up is written
    # and run first, and the run waits only once it merged.
    assert step.kind == "wait"
    (follow_up,) = follow_ups(events)
    assert follow_up.subtask_id == CONTROL
    assert none_owed(events) == []
    assert calls(events) == []
    raised = [(e.seq, i.item_id) for e in lines(events) for i in e.raised if i.module == CONTROL]
    seq, latest = raised[-1]
    assert latest == sign_off_item_id("run-1", CONTROL, 3)
    assert seq > follow_up.seq  # raised by the follow-up's own merge
    state = replay(events)
    assert state.next_step() == Step(kind="wait")
    # Every earlier item is superseded: the only one a decision counts on is the latest.
    assert [i for _, i in raised if state.undecided(i)] == [latest]
    assert {i for _, i in raised[:-1]} <= set(state.superseded)
    decide(tmp_path, "approve", NOTE, item_id=latest)
    events, step = resume(rig)
    assert step.kind == "done"
    assert [e.item_id for e in events if isinstance(e, DecisionTaken)] == [latest]
    (call,) = calls(events)
    assert call.seq > max(s for s, _ in raised)
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_where_no_follow_up_is_owed_a_line_says_so_and_the_wait_follows_it(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path)
    events, step = drive(rig)
    assert step.kind == "wait"
    (line,) = none_owed(events)
    assert follow_ups(events) == []
    # The integration step decided the follow-ups; the wait comes after its line.
    assert replay(events[: line.seq]).next_step() == Step(kind="integrate")
    assert replay(events[: line.seq + 1]).next_step() == Step(kind="wait")
    assert calls(events) == []
    # A fresh process at the wait writes no second line.
    events, step = resume(rig)
    assert step.kind == "wait"
    assert len(none_owed(events)) == 1
    decide(tmp_path, "approve", NOTE, item_id=FIRST)
    events, step = resume(rig)
    assert step.kind == "done"
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    (call,) = calls(events)
    assert line.seq < taken.seq < call.seq
    assert len(none_owed(events)) == 1
    assert follow_ups(events) == []
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_under_gate_off_the_line_comes_before_the_wait_and_the_skip_after_the_decision(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path, gate_mode="off")
    events, step = drive(rig)
    assert step.kind == "wait"
    assert len(none_owed(events)) == 1
    assert calls(events) == []
    decide(tmp_path, "approve", NOTE, item_id=FIRST)
    events, _ = resume(rig)
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    (call,) = calls(events)
    assert isinstance(call, IntegrationGateSkipped)
    assert call.reason == "gate_mode=off"
    assert taken.seq < call.seq


def test_under_gate_off_a_closing_pass_that_moved_what_a_module_reads_owes_no_follow_up(
    tmp_path: Path,
) -> None:
    # Sizing's closing pass moves the plant the control loop reads. With the gate on that owes the
    # control module a follow-up; under off the call is skipped, and a skipped call is owed none,
    # so the line says so and the person signs the closing pass's values. Held to the journal
    # where integration's state is issued, the line is borne out: no follow-up is owed a skip.
    rig, graph = journal_rig(tmp_path, gate_mode="off")
    _closing_moves_the_plant(graph)
    events, step = drive(rig, closing=True)
    assert step.kind == "wait"
    assert len(none_owed(events)) == 1
    assert follow_ups(events) == []
    latest = sign_off_item_id("run-1", CONTROL, 2)
    assert replay(events).undecided(latest)
    decide(tmp_path, "approve", NOTE, item_id=latest)
    events, step = resume(rig)
    assert not [e for e in events if isinstance(e, Incident)]
    assert step.kind == "done"
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_a_process_killed_after_the_line_waits_on_resume_and_writes_it_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = journal_rig(tmp_path)
    loop = journal_start(rig)
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies(event: Event) -> None:
        emit(event)
        if isinstance(event, NoFollowUpOwed):
            raise KilledError

    monkeypatch.setattr(loop, "_emit", dies)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    events, step = resume(rig)
    assert step.kind == "wait"
    assert len(none_owed(events)) == 1


# --- where the line is not written --------------------------------------------------------------


def test_a_sign_off_decided_before_the_integration_step_writes_no_line(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    events, step = drive(rig)
    assert step.kind == "done"
    assert none_owed(events) == []


def test_a_run_that_records_decisions_writes_no_line(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path, acts=False)
    events, step = drive(rig, acts=False)
    assert step.kind == "escalated"
    assert none_owed(events) == []
    assert len(calls(events)) == 1


# --- replay holds the line to its place ---------------------------------------------------------


def _waiting_run(tmp_path: Path) -> tuple[list[Event], NoFollowUpOwed]:
    rig, _ = journal_rig(tmp_path)
    events, _ = drive(rig)
    (line,) = none_owed(events)
    return events, line


def test_replay_refuses_a_second_line(tmp_path: Path) -> None:
    events, line = _waiting_run(tmp_path)
    refused(inserted(events, line.seq + 1, line), "a line that no follow-up is owed comes once")


def test_replay_refuses_the_line_before_every_module_is_resolved(tmp_path: Path) -> None:
    events, line = _waiting_run(tmp_path)
    first = next(e for e in events if isinstance(e, SignOffsRaised))
    # Straight after the control module's raise, while the electrical module is still to run:
    # a sign-off waits and nothing is decided of the follow-ups, but the step is no call's.
    early = events[: first.seq + 1]
    refused(inserted(early, first.seq + 1, line), "a line that no follow-up is owed comes once")


def test_replay_refuses_the_line_where_no_sign_off_waits(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    events, _ = drive(rig)
    (call,) = calls(events)
    line = NoFollowUpOwed(seq=0, ts=call.ts, run_id=call.run_id, gate_mode=call.gate_mode)
    refused(inserted(events, call.seq, line), "a line that no follow-up is owed comes once")


def test_replay_refuses_the_line_after_the_integration_call(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path)
    events, _ = drive(rig)
    (line,) = none_owed(events)
    decide(tmp_path, "approve", NOTE, item_id=FIRST)
    events, _ = resume(rig)
    (call,) = calls(events)
    refused(inserted(events, call.seq + 1, line), "a line that no follow-up is owed comes once")


def test_replay_refuses_a_follow_up_after_the_line(tmp_path: Path) -> None:
    rig, graph = journal_rig(tmp_path)
    _closing_moves_the_plant(graph)
    events, _ = drive(rig, closing=True)
    (follow_up,) = follow_ups(events)
    before = events[follow_up.seq - 1]
    line = NoFollowUpOwed(seq=0, ts=before.ts, run_id=before.run_id, gate_mode=before.gate_mode)
    # In its place, where the integration step decides the follow-ups, the line is taken; a
    # follow-up after it is not.
    refused(inserted(events, follow_up.seq, line), "no follow-up comes after the line")


# --- the loop holds the line to the journal ----------------------------------------------------


def test_a_line_the_journal_does_not_bear_out_halts_the_run_before_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = journal_rig(tmp_path)
    events, _ = drive(rig)
    assert len(none_owed(events)) == 1
    decide(tmp_path, "approve", NOTE, item_id=FIRST)
    owed = {CONTROL: (OwedEdge(source=PLANT, target=LOOP),)}

    def journal_owes(self: Loop, events: Any, *, every: bool = False) -> Any:  # noqa: ANN401
        return owed

    # What the journal owed where the line was written, as a journal that says otherwise.
    monkeypatch.setattr(Loop, "_owed", journal_owes)
    events, step = resume(rig)
    assert step.kind == "halted"
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert "no follow-up is owed" in incident.detail
    assert calls(events) == []
    replay(events)
