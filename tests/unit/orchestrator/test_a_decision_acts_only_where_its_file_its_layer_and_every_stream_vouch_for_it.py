"""A decision acts only where its file, the OS layer and every unjudged stream vouch for it.

ARCH-133, after its independent security review. Three ways a decision could act without a person
having made it, or past what the record says, each turned into a test from its working proof:

- A run that acts on decisions runs only inside the OS layer, which alone keeps a session's own
  shell from the decisions file: such a run is refused at configuration, at run and at resume
  where the layer is absent.
- The decisions file is append-only. Each spawn in a run that acts records the digest of the
  file as the session starts, and a decision is taken only while every such prefix is still the
  bytes it was; a file rewritten beneath an earlier spawn halts the run.
- An approve on a review that reached no verdict is held to the scan of every attempt no review
  judged, not only the last: an earlier attempt's work is in the commit the approve merges.

And the residuals the review named: the note's bounds and cleanliness held on every read and at
take, not only when written; the one fix refused at take, with its reason on the record, when its
reviewer could not read what it was told whole; a reportable run that would act on decisions; and
a confirmation of a decision that was taken and not held.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from escalation_states import STAND_IN, register_stand_in
from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, plan
from orch_helpers import CLEAN_HARNESS, make_config
from test_a_blocked_review_is_a_review_that_goes_to_a_person import BLOCKING, blocked_review
from test_a_queue_decision_acts_at_a_boundary import (
    ACT,
    NO_VERDICT,
    MarkingDispatcher,
    _layer,
    _of,
    _resume,
    _rig,
    _start,
    decide,
)

from physgate.orchestrator.escalation import BackendAnswer, EscalationInterface
from physgate.orchestrator.events import (
    DecisionTaken,
    Incident,
    Merged,
    StageEntered,
    SubtaskRejected,
)
from physgate.orchestrator.exceptions import QueueError, RunStateError
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    MAX_NOTE,
    PersonDecision,
    QueueResolution,
    read_queue,
)
from physgate.oslayer.probe import Absent

# -- the OS layer --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layer",
    [None, Absent(reason="unsupported_platform")],
    ids=["unrecorded", "absent"],
)
def test_a_run_that_acts_is_refused_its_configuration_without_the_os_layer(
    layer: Absent | None,
) -> None:
    with pytest.raises(ValueError, match="OS layer"):
        make_config(queue_decisions="act", os_layer=layer)
    assert make_config(queue_decisions="record", os_layer=layer).queue_decisions == "record"


def test_a_run_that_acts_runs_and_resumes_only_inside_the_os_layer(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    _layer(loop, present=False)
    with pytest.raises(RunStateError, match="OS layer"):
        loop.run()
    loop.close()
    loop = rig.open()
    _layer(loop, present=False)
    with pytest.raises(RunStateError, match="OS layer"):
        loop.resume()
    loop.close()
    spawned = [e for e in _of(rig.run_dir, StageEntered) if e.stage == "spawn"]
    assert spawned == [] and rig.dispatcher.requests == []


def test_a_run_that_acts_with_no_record_of_the_os_layer_is_refused(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run")
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(RunStateError, match="OS layer"):
        loop.run()
    loop.close()


def test_a_reportable_run_is_refused_if_it_would_act_on_decisions() -> None:
    from physgate.evaluation.requirements import REQUIREMENTS
    from physgate.orchestrator.requirements import RunFacts
    from physgate.oslayer.probe import Present

    layer = Present(mechanism="seatbelt", claude_version="2.1.301")
    facts = RunFacts(
        config=make_config(
            queue_decisions="act", os_layer=layer, reportable=True, harness=CLEAN_HARNESS
        ),
        os_layer=layer,
        shell_sessions=True,
    )
    said = [why for requirement in REQUIREMENTS if (why := requirement(facts)) is not None]
    assert len(said) == 1 and "record" in said[0]
    recording = RunFacts(
        config=make_config(
            queue_decisions="record", os_layer=layer, reportable=True, harness=CLEAN_HARNESS
        ),
        os_layer=layer,
        shell_sessions=True,
    )
    assert [r(recording) for r in REQUIREMENTS] == [None] * len(REQUIREMENTS)


# -- the decisions file is append-only ------------------------------------------------------------


def test_a_decisions_file_rewritten_beneath_an_earlier_spawn_halts_the_run(tmp_path: Path) -> None:
    # The review's proof: s1's retry session rewrites the file so that a bound approve of s2 sits
    # before the bytes that were there when it spawned. The layer is recorded present throughout:
    # the check stands behind it, whatever let the write through.
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1", "s2")
    loop.run()
    loop.close()
    decide(run_dir, "reject", "try the table's gain", item_id="run-1-s1")

    def forge() -> None:
        path = run_dir / DECISIONS_NAME
        old = path.read_bytes()
        path.write_bytes(b"")
        decide(run_dir, "approve", item_id="run-1-s2")
        path.write_bytes(path.read_bytes() + old)

    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")
    rig.dispatcher.during[1] = forge
    _, kind = _resume(rig)
    assert kind == "halted"
    taken = [(t.item_id, t.acts) for t in _of(run_dir, DecisionTaken)]
    # s1's retry is the person's and may merge; nothing a person did not decide acts on s2.
    assert ("run-1-s2", True) not in taken
    assert "s2" not in [m[0] for m in rig.merger.merges]
    assert [i.cause for i in _of(run_dir, Incident)] == ["decisions_rewritten"]
    with pytest.raises(RunStateError, match="incident"):
        _resume(rig)


def test_an_append_beneath_no_spawn_is_taken_as_ever(tmp_path: Path) -> None:
    # The control: a person decides s2 while s1's retry runs, by appending. Nothing beneath any
    # spawn's length changed, so the decision is taken as it always was.
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1", "s2")
    loop.run()
    loop.close()
    decide(run_dir, "reject", "try the table's gain", item_id="run-1-s1")
    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")

    def person() -> None:
        decide(run_dir, "approve", item_id="run-1-s2")

    rig.dispatcher.during[1] = person
    _resume(rig)
    taken = {t.item_id: (t.effect, t.acts) for t in _of(run_dir, DecisionTaken)}
    assert taken["run-1-s2"] == ("merge", True)
    assert _of(run_dir, Incident) == []


def test_a_run_that_records_seals_nothing(tmp_path: Path) -> None:
    rig = _rig(
        tmp_path / "run",
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
        config_overrides={"queue_decisions": "record"},
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    lines = (rig.run_dir / "events.jsonl").read_text().splitlines()
    assert not any(json.loads(line)["kind"] == "decisions_sealed" for line in lines)


# -- every unjudged stream ------------------------------------------------------------------------


def test_an_earlier_attempts_unjudged_scan_hit_keeps_an_approve_from_merging(
    tmp_path: Path,
) -> None:
    # The review's proof: attempt 1's stream shows a check switched off and its review reached no
    # verdict; a person retries; attempt 2's stream is clean and its review reaches none either.
    # Attempt 1's work is in the commit an approve of attempt 2 would merge.
    run_dir = tmp_path / "run"
    rig = _rig(
        run_dir,
        dispatcher=MarkingDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}),
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    first = read_queue(run_dir).items[0]
    assert first.consequence is not None and first.consequence.why_record_only == "scan_hit"
    decide(run_dir, "reject", "try again", item_id=first.item_id)
    rig.dispatcher.__class__ = FakeDispatcher  # attempt 2: same session ids go on, clean stream
    _resume(rig)
    second = read_queue(run_dir).items[1]
    assert second.consequence is not None
    assert (second.consequence.on_approve, second.consequence.why_record_only) == (
        "record_only",
        "scan_hit",
    )
    decide(run_dir, "approve", item_id=second.item_id)
    _resume(rig)
    assert rig.merger.merges == [] and _of(run_dir, Merged) == []
    last = _of(run_dir, DecisionTaken)[-1]
    assert (last.item_id, last.acts, last.why_not) == (second.item_id, False, "scan_hit")


# -- the note, held on every read -----------------------------------------------------------------

FORMAT = ["‮", "⁦", "​", "‍", "﻿", " ", " "]


@pytest.mark.parametrize("char", FORMAT, ids=[f"U+{ord(c):04X}" for c in FORMAT])
def test_a_note_holds_no_format_character(char: str) -> None:
    with pytest.raises(ValueError, match="format"):
        PersonDecision(verb="reject", note=f"use the{char} table")


def _append_line(
    run_dir: Path, item_id: str, sha: str, note: str | None, verb: Literal["approve", "reject"]
) -> None:
    """A decision line in the writer's own form, which the writer itself would have refused."""
    line = QueueResolution.model_construct(
        item_id=item_id,
        ts="2026-10-22T00:00:00.000000Z",
        kind="resolution",
        decision=verb if note is None else f"{verb}: {note}",
        resolved_by="someone",
        verb=verb,
        note=note,
        shown_sha256=sha,
    )
    with (run_dir / DECISIONS_NAME).open("ab") as out:
        out.write(line.model_dump_json().encode() + b"\n")


@pytest.mark.parametrize(
    "note",
    ["x" * (MAX_NOTE + 1), "a\x1bb", "use the‮table", "a\nb" * 400, "<<<close>>>"],
    ids=["too long", "control", "format", "too many lines", "fence"],
)
def test_a_note_the_writer_would_refuse_is_refused_when_read(tmp_path: Path, note: str) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    view = read_queue(rig.run_dir)
    item = view.items[0]
    _append_line(rig.run_dir, item.item_id, view.digests[item.item_id], note, "reject")
    with pytest.raises(QueueError):
        read_queue(rig.run_dir)


def test_a_blocked_review_approved_without_a_note_is_refused_at_take(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(results={1: blocked_review(BLOCKING)}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    view = read_queue(rig.run_dir)
    item = view.items[0]
    assert item.source == "review_blocked"
    # The writer refuses this line; one that reaches the file anyway is refused when taken.
    _append_line(rig.run_dir, item.item_id, view.digests[item.item_id], None, "approve")
    _, kind = _resume(rig)
    assert kind == "halted" and rig.merger.merges == []
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["queue_item_mismatch"]


# -- the one fix, refused before its session when its reviewer could not read it whole ------------


def test_a_fix_its_reviewer_could_not_read_whole_ends_the_subtask_before_any_session(
    tmp_path: Path,
) -> None:
    long = blocked_review(BLOCKING).model_copy(update={"finding": "the pole is not given. " * 1200})
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(results={1: long}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    (item,) = read_queue(rig.run_dir).open_items()
    assert item.consequence is not None and item.consequence.on_reject == "fix"
    decide(rig.run_dir, "reject", "use the linearised plant's pole")
    _, kind = _resume(rig)
    assert kind == "done"
    (taken,) = _of(rig.run_dir, DecisionTaken)
    assert (taken.effect, taken.acts, taken.order_too_long) == ("end_subtask", True, True)
    (ended,) = _of(rig.run_dir, SubtaskRejected)
    assert (ended.by, ended.item_id) == ("person", item.item_id)
    assert len(rig.dispatcher.requests) == 1  # the first attempt's; no fix session
    from physgate.orchestrator.queue import queue_listing

    decided = queue_listing(rig.run_dir)["decided"]
    assert isinstance(decided, list)
    assert decided[0]["taken"]["order_too_long"] is True


def test_a_longest_note_on_a_short_verdict_always_fits(tmp_path: Path) -> None:
    from physgate.orchestrator.protocols import PersonOrder
    from physgate.orchestrator.repair import fix_instruction
    from physgate.reviewers.packet import fits_one_read, person_order_text

    worst = "\U0001f600" * MAX_NOTE  # the longest note in bytes: four per character
    note = PersonDecision(verb="reject", note=worst).note
    assert note is not None
    order = PersonOrder(
        kind="fix_after_block",
        item_id="run-1-s1",
        of_attempt=3,
        instruction=fix_instruction(3, blocked_review().finding, (BLOCKING.finding,), note),
    )
    assert fits_one_read(person_order_text(order))


# -- a confirmation of a decision that was taken and not held -------------------------------------


def test_a_confirmation_of_a_decision_taken_and_not_held_is_refused(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    _resume(rig)
    (taken,) = _of(rig.run_dir, DecisionTaken)
    assert taken.acts
    with pytest.raises(RunStateError, match="not held"):
        _resume(rig, confirm=("run-1-s1",), confirmed_by="operator")


# -- one read of the file, sealed up to its last whole line ------------------------------------


def _forge_prefix(run_dir: Path) -> None:
    """A bound approve of s2 put before the bytes already in the decisions file."""
    path = run_dir / DECISIONS_NAME
    old = path.read_bytes()
    path.write_bytes(b"")
    decide(run_dir, "approve", item_id="run-1-s2")
    path.write_bytes(path.read_bytes() + old)


def _two_items_then_reject(run_dir: Path) -> Any:
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1", "s2")
    loop.run()
    loop.close()
    decide(run_dir, "reject", "try the table's gain", item_id="run-1-s1")
    return rig


def test_the_decisions_taken_are_parsed_from_the_bytes_the_seals_were_checked_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The review's proof: the file is swapped in the gap after the seals were checked on one
    # read of it and before the decisions were parsed from another.
    import inspect

    from physgate.orchestrator.queue import decisions_file_bytes as real

    run_dir = tmp_path / "run"
    rig = _two_items_then_reject(run_dir)
    state = {"armed": False, "fired": False}

    def read_then_swap(where: Path) -> bytes:
        data = real(where)
        if inspect.stack()[1].function == "_session":
            state["armed"] = True  # the seal of s1's retry, as it spawns
        elif state["armed"] and not state["fired"]:
            state["fired"] = True
            _forge_prefix(run_dir)  # what a race in the gap would do
        return data

    monkeypatch.setattr("physgate.orchestrator.loop.decisions_file_bytes", read_then_swap)
    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")
    _resume(rig)
    assert state["fired"]
    taken = [(t.item_id, t.acts) for t in _of(run_dir, DecisionTaken)]
    assert ("run-1-s2", True) not in taken
    assert "s2" not in [m[0] for m in rig.merger.merges]
    # Read again at the next boundary, the rewritten file halts the run.
    assert [i.cause for i in _of(run_dir, Incident)] == ["decisions_rewritten"]


def test_a_torn_tail_the_writer_cuts_does_not_trip_the_seal(tmp_path: Path) -> None:
    # A person's decision died mid-line before the retry spawned; the next decision, written
    # while the retry runs, cuts that torn tail as the writer always does. Only whole lines
    # are sealed, so the cut is no rewrite.
    from physgate.orchestrator.queue import record_decision

    run_dir = tmp_path / "run"
    rig = _two_items_then_reject(run_dir)
    with (run_dir / DECISIONS_NAME).open("ab") as torn:
        torn.write(b'{"item_id":"zz')
    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")

    def person() -> None:
        record_decision(run_dir, "run-1-s2", decision="later", resolved_by="yasin")

    rig.dispatcher.during[1] = person
    _resume(rig)
    assert "decisions_rewritten" not in [i.cause for i in _of(run_dir, Incident)]
    (seal,) = [
        record
        for record in map(json.loads, (run_dir / "events.jsonl").read_text().splitlines())
        if record["kind"] == "decisions_sealed"
        and (record["subtask_id"], record["attempt"]) == ("s1", 2)
    ]
    # The retry's seal covers the reject's whole line, not the torn bytes after it.
    assert seal["length"] == (run_dir / DECISIONS_NAME).read_bytes().index(b"\n") + 1


# -- every unjudged stream, whatever sent the subtask to a person -----------------------------


@pytest.mark.parametrize("marked", [True, False], ids=["marked", "clean"])
def test_an_exhausted_budgets_unreviewed_attempt_is_scanned_before_an_approve(
    tmp_path: Path, marked: bool
) -> None:
    # Attempt 1 failed at the gate, so no review judged its stream, which shows a check switched
    # off; attempts 2 and 3 were rejected by the reviewer. The commit an approve would merge
    # holds attempt 1's work.
    run_dir = tmp_path / "run"
    dispatcher = (MarkingDispatcher if marked else FakeDispatcher)(
        trajectories=run_dir / "sessions"
    )
    rig = _rig(
        run_dir,
        dispatcher=dispatcher,
        gate=FakeGate(verdicts=["fail", "pass", "pass"]),
        reviewer=FakeReviewer(verdicts=["fail", "fail"]),
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    (item,) = read_queue(run_dir).open_items()
    assert item.source == "repair_budget_exhausted" and item.consequence is not None
    if not marked:
        assert item.consequence.on_approve == "merge_attempt"
        return
    assert (item.consequence.on_approve, item.consequence.why_record_only) == (
        "record_only",
        "scan_hit",
    )
    decide(run_dir, "approve")
    _resume(rig)
    (taken,) = _of(run_dir, DecisionTaken)
    assert (taken.acts, taken.why_not) == (False, "scan_hit") and rig.merger.merges == []


def test_a_blocked_reviews_earlier_unreviewed_attempt_is_scanned_before_an_approve(
    tmp_path: Path,
) -> None:
    # Attempt 1 failed at the gate, unreviewed, its stream showing a check switched off; the
    # review of attempt 2 blocked. That review judged attempt 2's streams, not attempt 1's, and
    # an approve would merge both attempts' work.
    run_dir = tmp_path / "run"
    rig = _rig(
        run_dir,
        dispatcher=MarkingDispatcher(trajectories=run_dir / "sessions"),
        gate=FakeGate(verdicts=["fail", "pass"]),
        reviewer=FakeReviewer(results={1: blocked_review(BLOCKING)}),
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    (item,) = read_queue(run_dir).open_items()
    assert item.source == "review_blocked" and item.consequence is not None
    assert (item.consequence.on_approve, item.consequence.why_record_only) == (
        "record_only",
        "scan_hit",
    )
    decide(run_dir, "approve", "the pole is the linearised plant's")
    _resume(rig)
    (taken,) = _of(run_dir, DecisionTaken)
    assert (taken.acts, taken.why_not) == (False, "scan_hit") and rig.merger.merges == []


def test_a_confirmation_is_judged_on_a_decisions_file_its_seals_hold(tmp_path: Path) -> None:
    # The confirmation's own check reads the decisions file too: a file rewritten beneath a
    # session's start is refused there, before any confirmation is judged on what it now says.
    run_dir = tmp_path / "run"
    rig = _two_items_then_reject(run_dir)
    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")
    _resume(rig)  # s1's retry spawns beside the reject, and the run waits on s2
    _forge_prefix(run_dir)
    with pytest.raises(RunStateError, match="rewritten"):
        _resume(rig, confirm=("run-1-s2",), confirmed_by="operator")
    assert [i.cause for i in _of(run_dir, Incident)] == ["decisions_rewritten"]
    assert ("run-1-s2", True) not in [(t.item_id, t.acts) for t in _of(run_dir, DecisionTaken)]


class _YesOnTheSecondEnd:
    """An escalation backend that sends the subtask to a person at its second attempt's end."""

    def __init__(self) -> None:
        self.asked = 0

    def decide(self, question: object, state: object) -> BackendAnswer:
        self.asked += 1
        return BackendAnswer(answer="yes" if self.asked == 2 else "no", confidence=1.0)


@pytest.mark.parametrize("marked", [True, False], ids=["marked", "clean"])
def test_an_escalation_decisions_unreviewed_attempt_is_scanned_before_an_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    # Attempt 1 failed at the gate, so no review judged its stream; attempt 2 was rejected by the
    # reviewer and the escalation decision sent it to a person with attempts left. The commit an
    # approve would merge holds attempt 1's work.
    register_stand_in(monkeypatch)
    run_dir = tmp_path / "run"
    kind = MarkingDispatcher if marked else FakeDispatcher
    rig = _rig(
        run_dir,
        dispatcher=kind(trajectories=run_dir / "sessions"),
        gate=FakeGate(verdicts=["fail", "pass"]),
        reviewer=FakeReviewer(verdicts=["fail"]),
        escalation=EscalationInterface(_YesOnTheSecondEnd(), STAND_IN),
        config_overrides={**ACT, "escalation_backend": "stand_in"},
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    (item,) = read_queue(run_dir).open_items()
    assert item.source == "escalation_decision" and item.consequence is not None
    if marked:
        assert (item.consequence.on_approve, item.consequence.why_record_only) == (
            "record_only",
            "scan_hit",
        )
    else:
        assert item.consequence.on_approve == "merge_attempt"
