"""A sign-off owed holds the integration call, and refuses a declaration of its module (ARCH-130).

In a run that acts, the integration call waits while a module's latest sign-off item is undecided:
a person's approve then signs, or a reject leaves the module not complete, and only then is the
call made. A run that records decisions takes none on the item, so it never waits: integration is
called, the module stays not complete, and the run ends escalated, naming every owed sign-off.
Integration's issued state lists each owed sign-off, and the change check refuses a declaration
that names such a module, in either mode, by name, so integration's next attempt can leave it out.
Before every completion line the loop builds what the module's sign-off binds again from the graph
and holds it to the module's latest item: values that moved with no item raised halt the run.
Replay holds each of these from the log alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import KilledError, Rig
from sign_off_rig import (
    CLOSING,
    CONTROL,
    ELECTRICAL,
    INTEG,
    LOOP,
    JournalGraph,
    journal_rig,
    journal_start,
    layer,
    node,
    plant,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, decide
from test_a_sign_off_item_is_raised_by_code_at_every_clean_merge_that_owes_one import (
    FIRST,
    approving,
    completions,
    lines,
    refused,
    rewritten,
)

from physgate.orchestrator.declaration import DECLARATION_PATH
from physgate.orchestrator.events import (
    AttemptRejected,
    CompletionDeclared,
    DecisionTaken,
    DiffChecked,
    Event,
    Incident,
    IntegrationGateRan,
    IntegrationGateSkipped,
    IntegrationStateIssued,
    OsLayerChecked,
    ProposalsChecked,
    SignOffsRaised,
    parse_events,
    read_events,
)
from physgate.orchestrator.integration_state import issued_state
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import sign_off_item_id
from physgate.orchestrator.replay import Step, replay
from physgate.orchestrator.waiting import printed_step

SECOND = sign_off_item_id("run-1", CONTROL, 2)
THIRD = sign_off_item_id("run-1", CONTROL, 3)
#: A cross node sizing's closing pass writes that newly constrains the control module's node.
LOAD = "sizing.load"


def calls(events: list[Event]) -> list[Event]:
    """The integration call's lines: the gate run at system scope, or its skip."""
    return [e for e in events if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)]


def drive(rig: Rig, *, acts: bool = True, closing: bool = False) -> tuple[list[Event], Step]:
    loop = journal_start(rig, closing=closing, acts=acts)
    step = loop.run()
    loop.close()
    return read_events(rig.run_dir / "events.jsonl"), step


def resume(rig: Rig, **kw: Any) -> tuple[list[Event], Step]:  # noqa: ANN401
    loop = rig.open()
    layer(loop)
    step = loop.resume(**kw)
    loop.close()
    return read_events(rig.run_dir / "events.jsonl"), step


def without(events: list[Event], drop: Event) -> list[Event]:
    """``events`` with ``drop`` taken out and every later line renumbered, as the writer's bytes."""
    records = [json.loads(e.model_dump_json()) for e in events if e is not drop]
    renumbered = [r | {"seq": n} for n, r in enumerate(records)]
    return parse_events(b"".join(json.dumps(r).encode() + b"\n" for r in renumbered), log="x")


# --- the wait, in a run that acts --------------------------------------------------------------


def test_a_run_that_acts_waits_before_the_integration_call_until_a_person_decides(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path)
    events, step = drive(rig)
    # Every module merged, and the control module's item is undecided: no call is made.
    assert step.kind == "wait"
    assert [i.item_id for e in lines(events) for i in e.raised] == [FIRST]
    assert calls(events) == []
    assert completions(events) == []
    assert replay(events).next_step() == Step(kind="wait")
    # The person approves; the next process takes it at the wait, then makes the call.
    decide(tmp_path, "approve", "the margins are on the loop that runs", item_id=FIRST)
    events, step = resume(rig)
    assert step.kind == "done"
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    (call,) = calls(events)
    assert taken.seq < call.seq
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_a_reject_ends_the_wait_and_the_run_ends_escalated_naming_the_sign_off(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path, verb="reject")
    loop = journal_start(rig)
    step = loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    # The reject records only, so no approve can come: the call is made, the control module is not
    # complete, and the run ends escalated with its sign-off named.
    assert len(calls(events)) == 1
    assert completions(events) == [ELECTRICAL]
    assert step.kind == "escalated"
    state = replay(events)
    assert state.next_step() == Step(kind="escalated")
    assert state.sign_offs_open() == [CONTROL]
    printed, status = printed_step(step.kind, state)
    assert printed == {"step": "escalated", "sign_offs_owed": f"{CONTROL} (item {FIRST})"}
    assert status == 1


def test_replay_refuses_an_integration_call_while_a_sign_off_item_is_undecided(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    events, step = drive(rig)
    assert step.kind == "done"
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    refused(without(events, taken), "the integration call waits while a sign-off item is undecided")


# --- a run that records decisions --------------------------------------------------------------


def test_a_run_that_records_decisions_is_called_and_ends_escalated_naming_each_owed_sign_off(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path, acts=False)
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, acts=False)
    step = loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    # The person's approve is on the file, and the run takes none: it never waits for one.
    assert not [e for e in events if isinstance(e, DecisionTaken)]
    assert len(calls(events)) == 1
    assert completions(events) == [ELECTRICAL]
    assert step.kind == "escalated"
    state = replay(events)
    assert state.next_step() == Step(kind="escalated")
    printed, _ = printed_step(step.kind, state)
    assert printed["sign_offs_owed"] == f"{CONTROL} (item {FIRST})"


def test_a_run_whose_sign_offs_were_all_given_ends_done_as_before(tmp_path: Path) -> None:
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    events, step = drive(rig)
    assert step.kind == "done"
    assert completions(events) == [CONTROL, ELECTRICAL]
    state = replay(events)
    assert state.sign_offs_open() == []
    assert printed_step(step.kind, state) == ({"step": "done"}, 0)


# --- the change check and the issued state -----------------------------------------------------


@pytest.mark.parametrize("acts", [False, True])
def test_a_declaration_naming_a_module_whose_sign_off_is_owed_is_refused_by_name(
    tmp_path: Path, acts: bool
) -> None:
    rig, _ = journal_rig(tmp_path, acts=acts)
    # In a run that acts the control module's item is rejected, so its sign-off stays owed.
    rig.dispatcher.during[3] = approving(tmp_path, verb="reject")
    loop = journal_start(rig, acts=acts)
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    checks = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert [(c.attempt, c.refused_by, c.subject) for c in checks] == [
        (1, "declaration", DECLARATION_PATH),
        (2, None, None),
    ]
    assert checks[0].reason is not None
    assert f"module {CONTROL!r}" in checks[0].reason
    assert "stability margin owes a person's sign-off" in checks[0].reason
    (rejected,) = [e for e in events if isinstance(e, AttemptRejected) and e.subtask_id == INTEG]
    assert (rejected.attempt, rejected.finding.source) == (1, "declaration")
    (declared,) = [e for e in events if isinstance(e, CompletionDeclared)]
    assert declared.modules == (ELECTRICAL,)
    assert completions(events) == [ELECTRICAL]


def test_replay_refuses_a_declaration_naming_a_module_whose_sign_off_is_owed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A loop whose change check let the declaration through: replay refuses its line as written.
    monkeypatch.setattr(Loop, "_sign_off_refusal", lambda self, check: check)
    rig, _ = journal_rig(tmp_path, acts=False)
    loop = journal_start(rig, acts=False)
    with pytest.raises(ValueError, match=f"names {CONTROL!r}, whose stability margin owes a"):
        loop.run()
    loop.close()


def test_the_issued_state_lists_each_owed_sign_off_and_only_when_one_is_owed(
    tmp_path: Path,
) -> None:
    rig, _ = journal_rig(tmp_path, acts=False)
    loop = journal_start(rig, acts=False)
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    issued = next(e for e in events if isinstance(e, IntegrationStateIssued))
    text = issued_state(replay(events[: issued.seq])).decode()
    assert "\n## Owed sign-offs\n" in text
    assert f'- Module "{CONTROL}" of the "control" role: its stability margin.' in text
    # With the control module signed, the section is not there, and nothing else moved.
    plain = tmp_path / "signed"
    rig2, _ = journal_rig(plain)
    rig2.dispatcher.during[3] = approving(plain)
    signed, _ = drive(rig2)
    issued2 = next(e for e in signed if isinstance(e, IntegrationStateIssued))
    text2 = issued_state(replay(signed[: issued2.seq])).decode()
    assert "Owed sign-offs" not in text2
    assert text.split("\n## Owed sign-offs\n")[0] == text2


# --- the backstop before a completion line -----------------------------------------------------


def test_values_moved_after_the_signature_halt_the_run_before_the_module_s_completion_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, graph = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)

    complete = Loop._complete  # noqa: SLF001 - the completion step, wrapped

    def tampered(self: Loop, step: Step) -> None:
        # Once integration's merge was diffed: the control loop's line rewritten in place, after
        # the person signed the values it held.
        line = next(ln for ln in graph.journal if (ln.node_id, ln.rev) == (LOOP, 3))
        payload = json.loads(json.dumps(line.payload))
        payload["quantities"]["phase_margin"]["value"] = 0.2
        graph.journal[graph.journal.index(line)] = line.model_copy(update={"payload": payload})
        complete(self, step)

    monkeypatch.setattr(Loop, "_complete", tampered)
    events, step = drive(rig)
    assert step.kind == "halted"
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert f"module {CONTROL}'s sign-off binds" in incident.detail
    assert f"its latest item {FIRST}" in incident.detail
    assert completions(events) == []
    replay(events)


def _closing_writes_a_new_bound(graph: JournalGraph) -> None:
    """Sizing's closing pass writes a cross node that newly constrains the control loop."""
    graph.writes[CLOSING] = [[node(LOAD, "cross", "sizing", (LOOP,), mass=(0.05, "kg"))]]


def _dies_before_the_closing_line(monkeypatch: pytest.MonkeyPatch, loop: Loop) -> None:
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies(event: Event) -> None:
        if isinstance(event, SignOffsRaised) and event.subtask_id == CLOSING:
            raise KilledError
        emit(event)

    monkeypatch.setattr(loop, "_emit", dies)


def test_a_process_killed_before_a_new_bound_node_s_raise_writes_it_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, graph = journal_rig(tmp_path)
    _closing_writes_a_new_bound(graph)
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, closing=True)
    _dies_before_the_closing_line(monkeypatch, loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert isinstance(events[-1], DiffChecked)
    assert events[-1].subtask_id == CLOSING
    # The log alone does not owe the line: the closing pass wrote nothing the first item binds.
    assert replay(events).sign_off_due is None
    events, step = resume(rig)
    # The fresh process asks the graph before any line but its first, and the line follows.
    at = next(
        i for i, e in enumerate(events) if isinstance(e, DiffChecked) and e.subtask_id == CLOSING
    )
    # Only the new process's record of the OS layer comes between them.
    assert isinstance(events[at + 1], OsLayerChecked)
    line = events[at + 2]
    assert isinstance(line, SignOffsRaised)
    assert [i.item_id for i in line.raised] == [SECOND]
    assert LOAD in {v.node_id for v in line.raised[0].bound}
    state = replay(events)
    assert state.signed == [FIRST]
    assert "sign_off" in {name for name, _ in _open(state)}
    assert CONTROL not in completions(events)
    assert step.kind == "wait"


def test_a_raise_lost_for_a_new_bound_node_halts_the_run_before_the_stale_approve_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The gate is off, so no follow-up reopens the control module after the closing pass.
    rig, graph = journal_rig(tmp_path, gate_mode="off")
    _closing_writes_a_new_bound(graph)
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, closing=True)
    _dies_before_the_closing_line(monkeypatch, loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    # A process that does not ask the graph on resume, as one written before the backstop.
    monkeypatch.setattr(Loop, "_raise_owed_at_start", lambda self: None)
    events, step = resume(rig)
    assert not [e for e in lines(events) if e.subtask_id == CLOSING]
    # The first item's approve still counts by the log alone; the graph says otherwise, and the
    # next clean merge, integration's, finds the values moved with no write of its own: halted.
    assert step.kind == "halted"
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert f"module {CONTROL}'s sign-off binds changed at the merge of {INTEG}" in incident.detail
    assert completions(events) == []


def _open(state: Any) -> tuple[tuple[str, str], ...]:  # noqa: ANN401
    from physgate.orchestrator.completion import open_preconditions

    return open_preconditions(state, CONTROL)


# --- a held approve, and an earlier approve of the same values --------------------------------


def test_a_held_approve_confirmed_after_a_later_item_superseded_it_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The person approves the first item while a session runs without the OS layer: held. The
    # closing pass then moves the plant's mass, and the module's second item supersedes the first.
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    rig, graph = journal_rig(tmp_path)
    graph.writes[CLOSING] = [[plant(mass=0.41)]]
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, closing=True, acts=False)
    _layer(loop, present=False)
    assert loop.run().kind == "wait"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (held,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (held.item_id, held.effect, held.acts, held.why_not) == (
        FIRST,
        "sign",
        False,
        "held_os_layer_off",
    )
    # The closing pass's raise supersedes the first item, and the follow-up's merge the second.
    assert replay(events).superseded == {FIRST: SECOND, SECOND: THIRD}
    # The operator confirms it: what it signed is no longer the module's, so it records only.
    resumed = rig.open()
    _layer(resumed, present=False)
    step = resumed.resume(confirm=(FIRST,), confirmed_by="operator")
    resumed.close()
    events = read_events(tmp_path / "events.jsonl")
    confirmed = [e for e in events if isinstance(e, DecisionTaken)][1]
    assert (confirmed.item_id, confirmed.confirmed_by) == (FIRST, "operator")
    assert (confirmed.verb, confirmed.decision_offset) == (held.verb, held.decision_offset)
    assert (confirmed.effect, confirmed.acts, confirmed.why_not) == ("none", False, "superseded")
    state = replay(events)
    assert state.signed == []
    assert FIRST in state.confirmed
    assert step.kind == "wait"
    assert state.undecided(THIRD)


def test_a_run_halted_at_a_merge_s_sign_off_line_is_not_asked_again_by_the_next_process(
    tmp_path: Path,
) -> None:
    rig, graph = journal_rig(tmp_path)

    def tamper() -> None:
        # While the electrical module's session runs: the control loop's line rewritten in place.
        line = next(ln for ln in graph.journal if (ln.node_id, ln.rev) == (LOOP, 3))
        payload = json.loads(json.dumps(line.payload))
        payload["quantities"]["phase_margin"]["value"] = 1.2
        graph.journal[graph.journal.index(line)] = line.model_copy(update={"payload": payload})

    rig.dispatcher.during[3] = tamper
    events, step = drive(rig)
    assert step.kind == "halted"
    before = len(events)
    # The log still ends at the electrical module's merge and the halt the raise wrote: a fresh
    # process finds the run halted and writes nothing, not the same incident again.
    again = rig.open()
    assert again.run().kind == "halted"
    again.close()
    events = read_events(tmp_path / "events.jsonl")
    assert len(events) == before
    assert len([e for e in events if isinstance(e, Incident)]) == 1


def _held_on_the_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """A run whose control module's one item a person approved while a session ran unconfined.

    The session ran without the OS layer, so the approve is held; no later item supersedes it.
    """
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    rig, _ = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, acts=False)
    _layer(loop, present=False)
    assert loop.run().kind == "wait"
    loop.close()
    return rig


def test_a_held_approve_on_the_latest_item_holds_the_wait_until_confirmed_then_signs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _held_on_the_latest(tmp_path, monkeypatch)
    events = read_events(tmp_path / "events.jsonl")
    (held,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (held.item_id, held.effect, held.acts) == (FIRST, "sign", False)
    state = replay(events)
    # Held is not decided: the wait stands, after the line that no follow-up is owed.
    assert state.undecided(FIRST)
    assert state.signed == []
    assert state.next_step() == Step(kind="wait")
    assert calls(events) == []
    resumed = rig.open()
    _layer(resumed, present=False)
    step = resumed.resume(confirm=(FIRST,), confirmed_by="operator")
    resumed.close()
    events = read_events(tmp_path / "events.jsonl")
    confirmed = [e for e in events if isinstance(e, DecisionTaken)][1]
    assert (confirmed.effect, confirmed.acts, confirmed.why_not) == ("sign", True, None)
    assert replay(events).signed == [FIRST]
    assert step.kind == "done"
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_replay_refuses_a_confirmation_of_a_held_approve_that_does_other_than_its_item_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _held_on_the_latest(tmp_path, monkeypatch)
    resumed = rig.open()
    _layer(resumed, present=False)
    resumed.resume(confirm=(FIRST,), confirmed_by="operator")
    resumed.close()
    events = read_events(tmp_path / "events.jsonl")
    confirmed = [e for e in events if isinstance(e, DecisionTaken)][1]
    # The item was not superseded: a confirmation that records only, as a lapsed one does, is
    # not the decision that was held.
    lapsed = {"effect": "none", "acts": False, "why_not": "superseded"}
    refused(rewritten(events, confirmed.seq, **lapsed), "a confirmation is of the decision")


def test_replay_refuses_a_confirmation_that_signs_an_item_a_later_raise_superseded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    rig, graph = journal_rig(tmp_path)
    graph.writes[CLOSING] = [[plant(mass=0.41)]]
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, closing=True, acts=False)
    _layer(loop, present=False)
    assert loop.run().kind == "wait"
    loop.close()
    resumed = rig.open()
    _layer(resumed, present=False)
    resumed.resume(confirm=(FIRST,), confirmed_by="operator")
    resumed.close()
    events = read_events(tmp_path / "events.jsonl")
    confirmed = [e for e in events if isinstance(e, DecisionTaken)][1]
    assert confirmed.why_not == "superseded"
    # Signing what the module no longer holds is refused, however the line says it.
    signs = {"effect": "sign", "acts": True, "why_not": None}
    refused(rewritten(events, confirmed.seq, **signs), "a confirmation is of the decision")
