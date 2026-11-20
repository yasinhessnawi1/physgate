"""A sign-off item is raised by code at every clean merge that owes one (ARCH-130, ARCH-133).

Straight after the diff of a merge that found nothing, in a run whose first line names the
sign-off rule table, the loop lists one item for each module whose role owes a person's sign-off
and that the merge was of, or whose bound values it changed, then writes one line naming them; a
merge that raised none writes no line. An item binds the module's own nodes, every cross node that
constrains them, and every interface it reads from sizing, as the graph holds them; it shows at
most three of them in its row's order, every value with its node, and their digest. A person
decides it by approve or reject, bound to the line shown: in a run that acts an approve signs and
a reject records; a run that records decisions takes none on it. Replay refuses a sign-off line
the log does not owe, an item no write of the merge explains, and a merge that owed an item and
raised none.
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
    OTHER,
    PLANT,
    JournalGraph,
    journal_rig,
    journal_start,
    plant,
)
from test_a_queue_decision_acts_at_a_boundary import decide

from physgate.orchestrator import record
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.events import (
    DecisionTaken,
    DiffChecked,
    Event,
    Incident,
    ModuleCompleted,
    SignOffsRaised,
    parse_events,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, QueueError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    sign_off_consequence,
    sign_off_item_id,
    statuses_now,
)
from physgate.orchestrator.queue_words import decision_sentences
from physgate.orchestrator.replay import replay
from physgate.orchestrator.sign_off import Bound, values_sha256

FIRST = sign_off_item_id("run-1", CONTROL, 1)


def driven(
    tmp_path: Path,
    *,
    acts: bool = True,
    closing: bool = False,
    during: dict[int, Any] | None = None,
    graph_writes: dict[str, list[list[dict[str, Any]]]] | None = None,
) -> tuple[list[Event], JournalGraph]:
    """The run of sizing, the control module, an electrical one and integration, to its end."""
    rig, graph = journal_rig(tmp_path, acts=acts)
    graph.writes |= graph_writes or {}
    rig.dispatcher.during |= during or {}
    loop = journal_start(rig, closing=closing, acts=acts)
    loop.run()
    loop.close()
    return read_events(tmp_path / "events.jsonl"), graph


def lines(events: list[Event]) -> list[SignOffsRaised]:
    return [e for e in events if isinstance(e, SignOffsRaised)]


def completions(events: list[Event]) -> list[str]:
    return [e.subtask_id for e in events if isinstance(e, ModuleCompleted)]


def approving(tmp_path: Path, item_id: str = FIRST, verb: str = "approve") -> Any:  # noqa: ANN401
    """A person deciding ``item_id`` while a later session runs."""
    return lambda: decide(tmp_path, verb, "the margins are on the loop that runs", item_id=item_id)


def rewritten(events: list[Event], at: int, **fields: Any) -> list[Event]:
    """``events`` with line ``at``'s fields replaced, read back as the writer's bytes."""
    records = [json.loads(e.model_dump_json()) for e in events]
    records[at].update(fields)
    return parse_events(b"".join(json.dumps(r).encode() + b"\n" for r in records), log="x")


def refused(events: list[Event], reason: str) -> None:
    with pytest.raises(CorruptEventLogError) as caught:
        replay(events)
    assert reason in str(caught.value.context["reason"])


# --- the raise ---------------------------------------------------------------------------------


def test_the_module_s_own_clean_merge_raises_one_item_and_the_others_raise_none(
    tmp_path: Path,
) -> None:
    events, graph = driven(tmp_path)
    # One line, straight after the control module's clean diff. Sizing merged before it had
    # merged anything, and the electrical module's and integration's merges changed nothing it
    # binds: no line follows them.
    (line,) = lines(events)
    before = events[line.seq - 1]
    assert isinstance(before, DiffChecked)
    assert (before.subtask_id, before.divergences) == (CONTROL, ())
    assert (line.subtask_id, line.attempt) == (CONTROL, 1)
    assert [i.item_id for i in line.raised] == [FIRST]
    raised = line.raised[0]
    # Its own node, and the cross node that constrains it; never a cross node that does not.
    assert [(v.node_id, v.revision) for v in raised.bound] == [(LOOP, 3), (PLANT, 2)]
    assert OTHER not in {v.node_id for v in raised.bound}
    held = {(ln.node_id, ln.rev): ln.payload for ln in graph.journal}
    bound = tuple(
        Bound(
            node_id=v.node_id,
            revision=v.revision,
            quantities={
                n: {"value": q["value"], "unit": q["unit"]}
                for n, q in sorted(held[(v.node_id, v.revision)]["quantities"].items())
            },
        )
        for v in raised.bound
    )
    assert raised.values_sha256 == values_sha256(bound)
    state = replay(events)
    assert state.sign_offs[FIRST].values_sha256 == raised.values_sha256
    assert state.sign_off_due is None


def test_the_item_shows_the_row_s_names_first_every_bound_value_and_their_digest(
    tmp_path: Path,
) -> None:
    events, _ = driven(tmp_path)
    (item,) = [i for i in read_queue(tmp_path).items if i.source == "sign_off"]
    raised = lines(events)[0].raised[0]
    assert (item.item_id, item.subtask_id) == (FIRST, CONTROL)
    assert item.consequence == sign_off_consequence()
    assert "owes a person's sign-off on its stability margin" in item.decision_required
    # At most three, in the row's order of names: phase margin before gain margin.
    assert [(q.node_id, q.name) for q in item.quantities] == [
        (LOOP, "phase_margin"),
        (LOOP, "gain_margin"),
        (LOOP, "sample_rate"),
    ]
    for said in ('Node "ctl.loop" (revision 3)', '"phase_margin" = 0.8 "radian"', '"mass" = 0.32'):
        assert said in item.artefact_diff
    assert item.artefact_diff.endswith(f"Their digest: {raised.values_sha256}.")
    assert "measured on the loop that runs" in item.triggering_finding
    assert item.trajectories and all("sess-" in t for t in item.trajectories)
    words = decision_sentences(item)
    assert words is not None
    assert words["approve"].startswith("Approving signs the values this item shows")


# --- deciding it -------------------------------------------------------------------------------


def test_an_approve_that_acts_signs_and_the_module_is_then_complete(tmp_path: Path) -> None:
    # The person approves while the electrical module's session runs (the third).
    events, _ = driven(tmp_path, during={3: approving(tmp_path)})
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (taken.item_id, taken.verb, taken.effect, taken.acts) == (FIRST, "approve", "sign", True)
    assert (taken.subtask_id, taken.attempt, taken.attempt_commit) == (None, None, None)
    state = replay(events)
    assert state.signed == [FIRST]
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_a_reject_records_only_and_the_module_stays_not_complete(tmp_path: Path) -> None:
    events, _ = driven(tmp_path, during={3: approving(tmp_path, verb="reject")})
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (taken.effect, taken.acts, taken.why_not) == ("none", False, "record_only_source")
    state = replay(events)
    assert state.signed == []
    assert completions(events) == [ELECTRICAL]
    assert "sign_off" in dict(open_preconditions(state, CONTROL))


def test_a_run_that_records_decisions_takes_none_on_it_and_the_module_stays_not_complete(
    tmp_path: Path,
) -> None:
    events, _ = driven(tmp_path, acts=False, during={3: approving(tmp_path)})
    (item,) = [i for i in read_queue(tmp_path).items if i.source == "sign_off"]
    assert item.consequence is None
    assert "This run records decisions only" in item.decision_required
    # The person's approve is on the decisions file, and no line of the run takes it.
    assert [d.item_id for _, d in read_queue(tmp_path).decisions] == [FIRST]
    assert not [e for e in events if isinstance(e, DecisionTaken)]
    state = replay(events)
    assert completions(events) == [ELECTRICAL]
    assert "sign_off" in dict(open_preconditions(state, CONTROL))


def test_a_sign_off_item_is_decided_by_approve_or_reject_and_by_nothing_else(
    tmp_path: Path,
) -> None:
    driven(tmp_path)
    view = read_queue(tmp_path)
    shown = ShownItem(item_sha256=view.digests[FIRST], trajectories=statuses_now(tmp_path, FIRST))
    with pytest.raises(QueueError, match="decided by approve or reject"):
        record_decision(tmp_path, FIRST, decision="looks fine", resolved_by="yasin")
    with pytest.raises(QueueError):
        record_decision(
            tmp_path,
            FIRST,
            person=PersonDecision(verb="choose", position="producer", note=None),
            resolved_by="yasin",
            shown=shown,
        )
    assert read_queue(tmp_path).decisions == ()


def test_values_no_write_of_the_merge_moved_halt_the_run_before_any_item_is_raised(
    tmp_path: Path,
) -> None:
    rig, graph = journal_rig(tmp_path)

    def tamper() -> None:
        line = next(ln for ln in graph.journal if (ln.node_id, ln.rev) == (LOOP, 3))
        payload = json.loads(json.dumps(line.payload))
        payload["quantities"]["phase_margin"]["value"] = 1.2
        graph.journal[graph.journal.index(line)] = line.model_copy(update={"payload": payload})

    rig.dispatcher.during[3] = tamper
    loop = journal_start(rig)
    loop.run()
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert "module c1's sign-off binds changed at the merge of s2" in incident.detail
    assert [i.item_id for i in read_queue(tmp_path).items] == [FIRST]
    replay(events)


def test_an_item_that_is_not_the_one_the_record_builds_halts_its_decision(tmp_path: Path) -> None:
    def rewrite_and_approve() -> None:
        path = tmp_path / "queue.jsonl"
        text = path.read_text().replace('= 0.8 \\"radian\\"', '= 1.2 \\"radian\\"')
        assert "1.2" in text
        path.write_text(text)
        approving(tmp_path)()

    events, _ = driven(tmp_path, during={3: rewrite_and_approve})
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "queue_item_mismatch"
    assert incident.detail == f"item {FIRST} is not the item the run's record builds"
    assert not [e for e in events if isinstance(e, DecisionTaken)]


# --- every path that merges --------------------------------------------------------------------


def test_a_closing_pass_that_moves_a_bound_value_raises_again_and_the_signature_stops_counting(
    tmp_path: Path,
) -> None:
    events, _ = driven(
        tmp_path,
        closing=True,
        during={3: approving(tmp_path)},
        graph_writes={CLOSING: [[plant(mass=0.41)]]},
    )
    raised = [(e.subtask_id, [i.item_id for i in e.raised]) for e in lines(events)]
    second, third = (sign_off_item_id("run-1", CONTROL, n) for n in (2, 3))
    # The closing pass changed the plant's mass, which constrains the control loop: a second
    # item; the follow-up it owed the control module merged again: a third, which supersedes the
    # second, on which no decision was taken.
    assert (CLOSING, [second]) in raised
    assert raised.index((CLOSING, [second])) < raised.index((CONTROL, [third]))
    state = replay(events)
    assert state.superseded[second] == third
    assert state.signed == [FIRST]
    # The approve was of the first values, and the module's latest item shows others.
    assert state.sign_offs[FIRST].values_sha256 != state.sign_offs[third].values_sha256
    assert CONTROL not in completions(events)
    assert f"queue item {third} shows" in dict(open_preconditions(state, CONTROL))["sign_off"]


def test_a_process_killed_after_the_item_is_listed_writes_its_line_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = journal_rig(tmp_path)
    loop = journal_start(rig)
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def dies_before_the_line(event: Event) -> None:
        if isinstance(event, SignOffsRaised) and event.raised:
            raise KilledError
        emit(event)

    monkeypatch.setattr(loop, "_emit", dies_before_the_line)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    assert [i.item_id for i in read_queue(tmp_path).items] == [FIRST]
    again: Loop = rig.open()
    from sign_off_rig import layer

    layer(again)
    again.run()
    again.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [[i.item_id for i in e.raised] for e in lines(events)] == [[FIRST]]
    assert [i.item_id for i in read_queue(tmp_path).items] == [FIRST]
    replay(events)


# --- what replay refuses -----------------------------------------------------------------------


def test_replay_refuses_a_merge_whose_line_is_missing_or_names_less_than_it_owes(
    tmp_path: Path,
) -> None:
    events, _ = driven(tmp_path)
    at = next(e.seq for e in lines(events) if e.subtask_id == CONTROL)
    refused([*events[:at], *events[at + 1 :]], "nothing comes between a clean merge and the line")
    # A run that names no rule table writes no line, and replay owes it none.
    refused(rewritten(events, 0, sign_offs=None), "a sign-off line follows the clean merge")


def test_replay_refuses_an_item_no_write_of_its_merge_explains(tmp_path: Path) -> None:
    events, _ = driven(tmp_path)
    own = next(e for e in lines(events) if e.subtask_id == CONTROL)
    item = json.loads(own.raised[0].model_dump_json())
    # A second item for the control module, straight after the electrical module's clean diff,
    # which wrote nothing it binds.
    at = next(
        i for i, e in enumerate(events) if isinstance(e, DiffChecked) and e.subtask_id == ELECTRICAL
    )
    second = json.loads(own.model_dump_json()) | {
        "subtask_id": ELECTRICAL,
        "raised": [item | {"item_id": sign_off_item_id("run-1", CONTROL, 2)}],
    }
    records = [json.loads(e.model_dump_json()) for e in events]
    records.insert(at + 1, second)
    renumbered = [r | {"seq": n} for n, r in enumerate(records)]
    forged = parse_events(b"".join(json.dumps(r).encode() + b"\n" for r in renumbered), log="x")
    refused(forged, "that no write of the merge explains")
    electrical = item | {"module": ELECTRICAL}
    refused(rewritten(events, own.seq, raised=[electrical]), "names modules whose role owes one")
    wrong_id = item | {"item_id": sign_off_item_id("run-1", CONTROL, 2)}
    refused(rewritten(events, own.seq, raised=[wrong_id]), "with another id than 'c1''s next")
    moved = item | {"bound": [{"node_id": LOOP, "revision": 2}, item["bound"][1]]}
    refused(rewritten(events, own.seq, raised=[moved]), "at a revision the log does not give")


def test_a_first_line_naming_no_table_writes_no_sign_off_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)
    events, _ = driven(tmp_path)
    assert lines(events) == []
    assert not [i for i in read_queue(tmp_path).items if i.source == "sign_off"]
    assert completions(events) == [CONTROL, ELECTRICAL]


def test_replay_refuses_a_signature_in_a_run_that_records_decisions(tmp_path: Path) -> None:
    events, _ = driven(tmp_path, acts=False)
    last = events[-1]
    forged = DecisionTaken(
        seq=len(events),
        ts=last.ts,
        run_id=last.run_id,
        gate_mode=last.gate_mode,
        subtask_id=None,
        item_id=FIRST,
        verb="approve",
        note=None,
        resolved_by="yasin",
        decided_ts=last.ts,
        decision_offset=0,
        shown_sha256="5" * 64,
        attempt=None,
        attempt_commit=None,
        effect="sign",
        acts=True,
        why_not=None,
    )
    refused([*events, forged], "a decision on a sign-off item is taken in a run that acts")
