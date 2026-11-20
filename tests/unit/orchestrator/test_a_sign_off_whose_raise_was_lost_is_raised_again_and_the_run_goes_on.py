"""A sign-off whose raise was lost is raised again on what the graph gives, and the run goes on.

A clean merge can bind a new node to a module's sign-off (a cross node it wrote that now constrains
the module's node), and only the graph says so: the log alone does not owe that raise. A process
killed between the merge's diff and its sign-off line leaves the next one to ask the graph; any
line written before it does (a halt among them) clears what owes it, and the raise is lost. The
rows model that loss by a resume that does not ask. The loop reads what each module's sign-off binds
from the graph again at every clean merge and before every completion line; where it finds other
nodes or revisions than the module's latest item bound, and no line raised them, it raises the
sign-off again on them, says where it found them, and goes on. The latest item's approve stops
counting, so no stale approve completes the module. Where the graph gives the item's own nodes at
the item's own revisions with other values, the journal was rewritten, and the run halts.

A merge whose recorded write takes a node out of a module's bound set (a cross node that no
longer constrains it) is explained by that write: the merge raises the module's next item.
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
    PLANT,
    JournalGraph,
    journal_rig,
    journal_start,
    layer,
    node,
)
from test_a_sign_off_item_is_raised_by_code_at_every_clean_merge_that_owes_one import (
    FIRST,
    approving,
    completions,
    lines,
    refused,
    rewritten,
)

from physgate.orchestrator.events import (
    DiffChecked,
    Event,
    Incident,
    ModuleCompleted,
    SignOffRaisedAgain,
    SignOffsRaised,
    read_events,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import read_queue, sign_off_item_id
from physgate.orchestrator.replay import Step, replay

SECOND = sign_off_item_id("run-1", CONTROL, 2)
#: A cross node sizing's closing pass writes that newly constrains the control module's node.
LOAD = "sizing.load"


def _closing_writes_a_new_bound(graph: JournalGraph) -> None:
    graph.writes[CLOSING] = [[node(LOAD, "cross", "sizing", (LOOP,), mass=(0.05, "kg"))]]


def _dies_at(monkeypatch: pytest.MonkeyPatch, loop: Loop, kind: type, subtask_id: str) -> None:
    """The process dies as it would write a ``kind`` line about ``subtask_id``'s merge."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies(event: Event) -> None:
        if isinstance(event, kind) and getattr(event, "subtask_id", None) == subtask_id:
            raise KilledError
        emit(event)

    monkeypatch.setattr(loop, "_emit", dies)


def _resumed_without_asking(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> tuple[list[Event], Step]:
    """A fresh process's resume that does not ask the graph for the line the log ends owing.

    As a resume after any line that clears what owed it: a halt there leaves the raise lost.
    """
    monkeypatch.setattr(Loop, "_raise_owed_at_start", lambda self: None)
    loop = rig.open()
    layer(loop)
    step = loop.resume()
    loop.close()
    return read_events(rig.run_dir / "events.jsonl"), step


def _lost_at_the_closing_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """The closing pass's raise lost: the process killed after its diff.

    The gate is off, so no follow-up reopens the control module after the closing pass, and the
    person approved the first item while the electrical module's session ran.
    """
    rig, graph = journal_rig(tmp_path, gate_mode="off")
    _closing_writes_a_new_bound(graph)
    rig.dispatcher.during[3] = approving(tmp_path)
    loop = journal_start(rig, closing=True)
    _dies_at(monkeypatch, loop, SignOffsRaised, CLOSING)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert isinstance(events[-1], DiffChecked)
    assert events[-1].subtask_id == CLOSING
    return rig


def _again(events: list[Event]) -> list[SignOffRaisedAgain]:
    return [e for e in events if isinstance(e, SignOffRaisedAgain)]


def test_a_lost_raise_is_raised_again_at_the_next_clean_merge_and_the_run_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _lost_at_the_closing_pass(tmp_path, monkeypatch)
    events, step = _resumed_without_asking(rig, monkeypatch)
    # Nothing asked the graph for the closing pass's line.
    assert not [e for e in lines(events) if e.subtask_id == CLOSING]
    # Integration's clean merge finds the control module's values moved with no item for them,
    # raises its sign-off again on them, and the run goes on to its end.
    assert not [e for e in events if isinstance(e, Incident)]
    (again,) = _again(events)
    assert (again.found, again.subtask_id, again.raised.item_id) == ("merge", INTEG, SECOND)
    assert LOAD in {v.node_id for v in again.raised.bound}
    assert step.kind == "escalated"
    state = replay(events)
    # The first item's approve no longer counts: the module is not complete, its sign-off owed.
    assert state.signed == [FIRST]
    assert state.sign_offs_open() == [CONTROL]
    assert CONTROL not in completions(events)
    assert ELECTRICAL in completions(events)
    assert SECOND in {item.item_id for item in read_queue(tmp_path).open_items()}


def test_a_raise_lost_at_integration_s_merge_is_raised_again_before_the_completion_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _lost_at_the_closing_pass(tmp_path, monkeypatch)
    # The process that writes integration's merge dies before its sign-off lines, too.
    take = Loop._raise_sign_offs  # noqa: SLF001 - wrapped, never replaced
    calls: list[str] = []

    def dies_at_integration(self: Loop) -> None:
        due = self.state.sign_off_due or self.state.sign_off_after
        if due is not None and due[0] == INTEG and not calls:
            calls.append(INTEG)
            raise KilledError
        take(self)

    monkeypatch.setattr(Loop, "_raise_sign_offs", dies_at_integration)
    with pytest.raises(KilledError):
        _resumed_without_asking(rig, monkeypatch)
    events, step = _resumed_without_asking(rig, monkeypatch)
    assert not [e for e in events if isinstance(e, Incident)]
    (again,) = _again(events)
    assert (again.found, again.subtask_id, again.raised.item_id) == ("completion", INTEG, SECOND)
    # Raised where the control module's completion line was owed, instead of that line.
    after = events[again.seq + 1]
    assert isinstance(after, ModuleCompleted)
    assert after.subtask_id != CONTROL
    assert CONTROL not in completions(events)
    assert step.kind == "escalated"
    state = replay(events)
    assert state.sign_offs_open() == [CONTROL]


def test_a_process_killed_after_listing_the_item_raised_again_writes_its_line_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _lost_at_the_closing_pass(tmp_path, monkeypatch)
    emit = Loop._emit  # noqa: SLF001 - wrapped, never replaced
    killed: list[int] = []

    def dies_once(self: Loop, event: Event) -> None:
        if isinstance(event, SignOffRaisedAgain) and not killed:
            killed.append(1)
            raise KilledError
        emit(self, event)

    monkeypatch.setattr(Loop, "_emit", dies_once)
    with pytest.raises(KilledError):
        _resumed_without_asking(rig, monkeypatch)
    # Listed before its line, once: the next process finds it listed and writes the line.
    assert SECOND in {item.item_id for item in read_queue(tmp_path).items}
    loop = rig.open()
    layer(loop)
    step = loop.resume()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (again,) = _again(events)
    assert again.raised.item_id == SECOND
    assert [i.item_id for i in read_queue(tmp_path).items].count(SECOND) == 1
    assert step.kind == "escalated"


def test_values_rewritten_at_the_revisions_the_latest_item_bound_still_halt_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, graph = journal_rig(tmp_path)
    rig.dispatcher.during[3] = approving(tmp_path)
    complete = Loop._complete  # noqa: SLF001 - the completion step, wrapped

    def tampered(self: Loop, step: Step) -> None:
        # The control loop's line rewritten in place after the person signed what it held: the
        # same node at the same revision, other values. No merge wrote that; nothing is raised.
        line = next(ln for ln in graph.journal if (ln.node_id, ln.rev) == (LOOP, 3))
        payload = json.loads(json.dumps(line.payload))
        payload["quantities"]["phase_margin"]["value"] = 0.2
        graph.journal[graph.journal.index(line)] = line.model_copy(update={"payload": payload})
        complete(self, step)

    monkeypatch.setattr(Loop, "_complete", tampered)
    loop = journal_start(rig)
    step = loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert step.kind == "halted"
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert "rewritten" in incident.detail
    assert _again(events) == []
    assert completions(events) == []


# --- replay holds the line ---------------------------------------------------------------------


def _raised_again_at_the_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    rig = _lost_at_the_closing_pass(tmp_path, monkeypatch)
    events, _ = _resumed_without_asking(rig, monkeypatch)
    return events


def test_replay_refuses_a_sign_off_raised_again_on_the_values_its_latest_item_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _raised_again_at_the_merge(tmp_path, monkeypatch)
    (again,) = _again(events)
    first = next(e for e in lines(events) if e.raised[0].item_id == FIRST).raised[0]
    same = again.raised.model_copy(
        update={"bound": first.bound, "values_sha256": first.values_sha256}
    )
    refused(
        rewritten(events, again.seq, raised=json.loads(same.model_dump_json())),
        "raised again on the values its latest item shows",
    )


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"subtask_id": CLOSING, "attempt": 1}, "follows that clean merge"),
        (
            {"found": "completion", "subtask_id": CLOSING},
            "where that module's completion line is owed",
        ),
    ],
    ids=["another merge", "not after integration's merge"],
)
def test_replay_refuses_a_sign_off_raised_again_where_the_loop_cannot_find_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any], reason: str
) -> None:
    events = _raised_again_at_the_merge(tmp_path, monkeypatch)
    (again,) = _again(events)
    refused(rewritten(events, again.seq, **fields), reason)


def test_replay_refuses_a_sign_off_raised_again_at_a_revision_the_log_does_not_give(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _raised_again_at_the_merge(tmp_path, monkeypatch)
    (again,) = _again(events)
    raised = json.loads(again.raised.model_dump_json())
    raised["bound"][0]["revision"] = 99
    refused(rewritten(events, again.seq, raised=raised), "a revision the log does not give")


def test_replay_refuses_a_sign_off_raised_again_with_another_id_than_the_module_s_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _raised_again_at_the_merge(tmp_path, monkeypatch)
    (again,) = _again(events)
    raised = json.loads(again.raised.model_dump_json())
    raised["item_id"] = FIRST
    refused(rewritten(events, again.seq, raised=raised), "another id")


# --- a merge whose write shrinks the bound set -------------------------------------------------


def test_a_merge_whose_write_takes_a_node_out_of_the_bound_set_raises_the_module_s_next_item(
    tmp_path: Path,
) -> None:
    # Sizing's plant constrains the control loop, so the first item binds it. Sizing's closing
    # pass then writes the plant constraining nothing: the plant leaves what the control module's
    # sign-off binds, through a write on the record, and that write explains the next item.
    rig, graph = journal_rig(tmp_path, gate_mode="off")
    graph.writes[CLOSING] = [[node(PLANT, "cross", "sizing", (), mass=(0.32, "kg"))]]
    loop = journal_start(rig, closing=True)
    step = loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    assert not [e for e in events if isinstance(e, Incident)]
    first, second = (i for e in lines(events) for i in e.raised)
    assert (first.item_id, second.item_id) == (FIRST, SECOND)
    assert PLANT in {v.node_id for v in first.bound}
    assert PLANT not in {v.node_id for v in second.bound}
    (closing,) = [e for e in lines(events) if e.subtask_id == CLOSING]
    assert closing.raised == (second,)
    assert _again(events) == []
    assert step.kind == "wait"
    assert replay(events).undecided(SECOND)
