"""A person's queue decision acts in a run that acts on decisions, at a boundary, in code.

ARCH-133, end to end over the loop with stand-in ports: an approve merges exactly the attempt the
item names through the loop's own merge, and the integration call then runs, a resumed run's
included; an approve never merges past an automated check, a confirmed indicator or a scan hit; a
reject starts one more attempt from the note while the budget lasts and otherwise ends the
subtask; a decision written while a session ran is taken after its attempt ends, and one written
where the session ran without the OS layer waits for the operator; free text, and an item
rewritten since its decision, act on nothing; a run that only records decisions, and every run
recorded before the switch, is unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import (
    FakeChanges,
    FakeDispatcher,
    FakeGate,
    FakeMerger,
    FakeReviewer,
    KilledError,
    Rig,
    plan,
)

from physgate.orchestrator.events import (
    DecisionTaken,
    DiffChecked,
    Event,
    Halted,
    Incident,
    IntegrationGateRan,
    IntegrationGateSkipped,
    LeftoverRead,
    Merged,
    OsLayerChecked,
    SessionEnded,
    SubtaskRejected,
    read_events,
)
from physgate.orchestrator.exceptions import (
    InvocationError,
    ReviewUnavailableError,
    RunStateError,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import IndicatorReport, ReviewResult
from physgate.orchestrator.queue import (
    QUEUE_NAME,
    PersonDecision,
    QueueResolution,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.oslayer.probe import Present

#: A run that acts on decisions, configured where the OS layer runs, as it must be.
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ACT = {"queue_decisions": "act", "os_layer": PRESENT}
NO_VERDICT = ReviewUnavailableError("no verdict", cause="invalid_verdict")


def _events(run_dir: Path) -> list[Event]:
    return list(read_events(run_dir / "events.jsonl"))


def _of(run_dir: Path, kind: type[Any]) -> list[Any]:
    return [e for e in _events(run_dir) if isinstance(e, kind)]


def _rig(run_dir: Path, **kw: Any) -> Rig:
    run_dir.mkdir(parents=True, exist_ok=True)
    kw.setdefault("dispatcher", FakeDispatcher(trajectories=run_dir / "sessions"))
    kw.setdefault("config_overrides", dict(ACT))
    return Rig(run_dir, **kw)


def _layer(loop: Loop, present: bool = True) -> None:
    """The OS layer's state, as the command records it before anything is spawned."""
    state = (
        Present(mechanism="seatbelt", claude_version="2.1.301")
        if present
        else {"state": "absent", "reason": "unsupported_platform"}
    )
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": state, "as_recorded": None}
        )
    )


def _start(rig: Rig, *ids: str, present: bool = True) -> Loop:
    loop = rig.open()
    loop.start(plan(*ids))
    _layer(loop, present)
    return loop


def decide(
    run_dir: Path, verb: str, note: str | None = None, *, item_id: str | None = None
) -> QueueResolution:
    """Decide an open item as a person does from the listing: bound to the digest it printed."""
    view = read_queue(run_dir)
    item = next(i for i in view.open_items() if item_id in (None, i.item_id))
    shown = ShownItem(
        item_sha256=view.digests[item.item_id], trajectories=statuses_now(run_dir, item.item_id)
    )
    return record_decision(
        run_dir,
        item.item_id,
        person=PersonDecision(verb=verb, note=note),  # type: ignore[arg-type]
        resolved_by="yasin",
        shown=shown,
    )


def _decide_quietly(run_dir: Path, item_id: str) -> None:
    """A person approving while a session runs: what the session's hook is told is nothing."""
    decide(run_dir, "approve", item_id=item_id)


def _resume(rig: Rig, **kw: Any) -> tuple[Loop, str]:
    loop = rig.open()
    _layer(loop)
    step = loop.resume(**kw)
    return loop, step.kind


# -- approve ---------------------------------------------------------------------------------


def test_an_ended_run_resumed_takes_its_approve_then_runs_the_integration_gate(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    assert loop.run().kind == "done"
    assert isinstance(loop.state.integration, IntegrationGateSkipped)
    loop.close()
    item = read_queue(rig.run_dir).items[0]
    assert item.consequence is not None and item.consequence.on_approve == "merge_attempt"
    decide(rig.run_dir, "approve")
    again, kind = _resume(rig)
    assert kind == "done"
    taken = _of(rig.run_dir, DecisionTaken)
    assert [(t.verb, t.effect, t.acts) for t in taken] == [("approve", "merge", True)]
    merged = _of(rig.run_dir, Merged)
    assert [m.attempt_commit for m in merged] == [item.consequence.attempt_commit]
    assert rig.merger.merges == [("s1", 1, item.consequence.attempt_commit)]
    assert len(_of(rig.run_dir, IntegrationGateRan)) == 1
    assert "approved by" in rig.merger.messages[-1].lower()
    assert again.state.subtasks["s1"].status == "done"


def test_a_failing_integration_after_an_approve_opens_an_integration_item_that_records_only(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    assert rig.gate is not None
    rig.gate.integration_verdict = "fail"
    _, kind = _resume(rig)
    assert kind == "escalated"
    integration = read_queue(rig.run_dir).open_items()[0]
    assert integration.item_id == "run-1-integration"
    assert integration.consequence is not None
    assert integration.consequence.on_approve == integration.consequence.on_reject == "record_only"


@pytest.mark.parametrize(
    ("setup", "why"),
    [
        ({"gate": FakeGate(verdicts=["fail"] * 3)}, "last_rejection_automated"),
        ({"changes": FakeChanges(refuse={n: ("proposal", "refused") for n in (1, 2, 3)})},
         "last_rejection_automated"),
        ({"changes": FakeChanges(refuse={n: ("write_scope", "outside") for n in (1, 2, 3)})},
         "last_rejection_automated"),
        ({"changes": FakeChanges(refuse={n: ("series", "a record") for n in (1, 2, 3)})},
         "last_rejection_automated"),
        ({"dispatcher": "unread"}, "last_rejection_automated"),
    ],
    ids=["gate", "proposal", "write scope", "series", "reading"],
)  # fmt: skip
def test_an_approve_never_merges_past_an_automated_check(
    tmp_path: Path, setup: dict[str, Any], why: str
) -> None:
    run_dir = tmp_path / "run"
    if setup.get("dispatcher") == "unread":
        setup = {"dispatcher": FakeDispatcher(trajectories=run_dir / "sessions", unread={1, 2, 3})}
    rig = _rig(run_dir, **setup)
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(run_dir, "approve")
    _, kind = _resume(rig)
    taken = _of(run_dir, DecisionTaken)
    assert [(t.effect, t.acts, t.why_not) for t in taken] == [("none", False, why)]
    assert _of(run_dir, Merged) == [] and rig.merger.merges == []
    assert kind == "done"


def _confirmed(n: int) -> ReviewResult:
    return ReviewResult(
        verdict="fail",
        finding="a check switched off",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=(),
        indicators=(
            IndicatorReport(
                kind="disabled_checks", evidence="t1", disposition="confirmed", reason="a skip"
            ),
        ),
    )


def test_an_approve_never_merges_with_a_confirmed_indicator(tmp_path: Path) -> None:
    rig = _rig(
        tmp_path / "run",
        reviewer=FakeReviewer(results={1: _confirmed(1)}, unavailable={2: NO_VERDICT}),
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    item = read_queue(rig.run_dir).items[0]
    assert item.consequence is not None
    assert item.consequence.why_record_only == "indicator_in_history"
    decide(rig.run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(rig.run_dir, DecisionTaken)] == ["indicator_in_history"]
    assert rig.merger.merges == []


@dataclass
class MarkingDispatcher(FakeDispatcher):
    """A dispatcher whose sessions' streams show a test switched off, as the scan finds it."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        if report.trajectory is None or self.trajectories is None:
            return report
        from physgate.orchestrator.trajectory import seal

        written = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_skip",
                        "name": "Write",
                        "input": {"file_path": "t.py", "content": "@pytest.mark.skip\n"},
                    }
                ],
            },
        }
        path = Path(report.trajectory)
        path.write_bytes(json.dumps(written).encode() + b"\n" + path.read_bytes())
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


def test_an_approve_never_merges_with_a_scan_hit_no_review_judged(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(
        run_dir,
        dispatcher=MarkingDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    item = read_queue(run_dir).items[0]
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert [h.evidence for h in item.consequence.scan_hits] == ["toolu_skip"]
    decide(run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []


def test_a_free_text_decision_is_recorded_and_never_acts(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    record_decision(rig.run_dir, "run-1-s1", decision="approve", resolved_by="yasin")
    _resume(rig)
    taken = _of(rig.run_dir, DecisionTaken)
    assert [(t.verb, t.acts, t.why_not) for t in taken] == [(None, False, "not_bound")]
    assert rig.merger.merges == []


def test_an_item_rewritten_after_its_approve_halts_the_run(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    items = rig.run_dir / QUEUE_NAME
    items.write_bytes(items.read_bytes().replace(b"reached no verdict", b"was fine, really"))
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["queue_item_mismatch"]
    assert rig.merger.merges == [] and _of(rig.run_dir, DecisionTaken) == []
    # Its decision was never taken, so its worktree is left for the person who looks first.
    assert "s1" not in rig.merger.removed


def test_an_approve_on_a_trajectory_that_changed_since_it_was_shown_halts_the_run(
    tmp_path: Path,
) -> None:
    # A review judged it, so no scan reads the stream: the hold before the merge is what sees it.
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(verdicts=["fail"] * 3))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    stream = Path(read_queue(rig.run_dir).items[0].trajectories[-1])
    stream.write_bytes(stream.read_bytes() + b"{}\n")
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["trajectory_tampered"]
    assert rig.merger.merges == [] and _of(rig.run_dir, DecisionTaken) == []


def test_an_approve_on_an_earlier_attempts_trajectory_changed_since_it_was_shown_halts(
    tmp_path: Path,
) -> None:
    # The item links every attempt's stream; the one merged is the last attempt's, and the
    # person was shown them all, so every one is held again before the merge.
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(verdicts=["fail"] * 3))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    linked = read_queue(rig.run_dir).items[0].trajectories
    assert len(linked) == 3
    first = Path(linked[0])
    first.write_bytes(first.read_bytes() + b"{}\n")
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["trajectory_tampered"]
    assert rig.merger.merges == [] and _of(rig.run_dir, DecisionTaken) == []


def test_two_approves_are_taken_one_boundary_at_a_time(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1", "s2")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve", item_id="run-1-s1")
    decide(rig.run_dir, "approve", item_id="run-1-s2")
    _, kind = _resume(rig)
    assert kind == "done"
    events = _events(rig.run_dir)
    order = [
        (type(e).__name__, e.subtask_id)
        for e in events
        if isinstance(e, DecisionTaken | Merged | DiffChecked)
    ]
    assert order == [
        ("DecisionTaken", "s1"),
        ("Merged", "s1"),
        ("DiffChecked", "s1"),
        ("DecisionTaken", "s2"),
        ("Merged", "s2"),
        ("DiffChecked", "s2"),
    ]


def test_replay_refuses_a_decision_taken_while_an_attempt_is_in_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1", "s2")
    loop.run()
    loop.close()
    decide(run_dir, "approve", item_id="run-1-s1")
    decide(run_dir, "approve", item_id="run-1-s2")
    # The line the loop writes for s2's decision where it may: after s1's merge, on a copy.
    copy = tmp_path / "copy"
    shutil.copytree(run_dir, copy)
    _resume(_rig(copy))
    line = next(t for t in _of(copy, DecisionTaken) if t.subtask_id == "s2")
    assert line.acts

    def killed(self: Loop, *args: Any, **kw: Any) -> bool:
        raise KilledError

    # Here the process dies with s1's approved merge still to do: s1's attempt is in progress.
    monkeypatch.setattr(Loop, "_merge_attempt", killed)
    with pytest.raises(KilledError):
        _resume(rig)
    stopped = rig.open()
    assert stopped.state.next_step().point == "merge"
    with pytest.raises(ValueError, match="no attempt is in progress"):
        stopped.state.check(line)
    stopped.close()


def test_a_diff_that_changed_since_the_item_halts_the_run(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    rig.merger = ChangedDiff()
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["queue_item_mismatch"]
    assert rig.merger.merges == []


@dataclass
class ChangedDiff(FakeMerger):
    def artefact_diff(self, attempt_commit: str) -> str:
        return "diff --git a/x b/x\n+ something else\n"


# -- reject ----------------------------------------------------------------------------------


def test_a_reject_with_budget_left_dispatches_one_attempt_quoting_the_note(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "reject", "the gain must come from the specification's table")
    rig.reviewer = FakeReviewer()
    _, kind = _resume(rig)
    assert kind == "done"
    requests = rig.dispatcher.requests
    assert [r.attempt for r in requests] == [1, 2]
    instruction = requests[-1].repair_instruction
    assert instruction is not None
    assert "a person deciding the approval queue" in instruction
    assert "the gain must come from the specification's table" in instruction
    assert "The specification as issued is unchanged and still governs." in instruction
    assert rig.merger.merges == [
        ("s1", 2, requests[-1] and _of(rig.run_dir, Merged)[0].attempt_commit)
    ]


def test_a_reject_with_no_budget_ends_the_subtask_rejected(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(verdicts=["fail"] * 3))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "reject", "split it")
    again, kind = _resume(rig)
    assert kind == "done"
    ended = _of(rig.run_dir, SubtaskRejected)
    assert [(e.by, e.item_id, e.attempt) for e in ended] == [("person", "run-1-s1", 3)]
    assert len(rig.dispatcher.requests) == 3
    assert again.state.subtasks["s1"].status == "rejected"
    skipped = _of(rig.run_dir, IntegrationGateSkipped)
    assert [s.subtasks for s in skipped][-1] == ("s1",)


# -- when a decision is taken ----------------------------------------------------------------


def test_a_decision_written_during_a_session_is_taken_after_its_attempt_ends(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    rig.dispatcher.during[2] = lambda: _decide_quietly(run_dir, "run-1-s1")
    loop = _start(rig, "s1", "s2")
    loop.run()
    events = _events(run_dir)
    taken = next(n for n, e in enumerate(events) if isinstance(e, DecisionTaken))
    ended = next(
        n for n, e in enumerate(events) if isinstance(e, SessionEnded) and e.subtask_id == "s2"
    )
    s2_done = next(
        n for n, e in enumerate(events) if isinstance(e, DiffChecked) and e.subtask_id == "s2"
    )
    assert taken > ended and taken > s2_done
    line = events[taken]
    assert isinstance(line, DecisionTaken) and line.acts
    assert loop.state.subtasks["s1"].status == "done"


@pytest.fixture
def entry_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's refusal to act without the OS layer, switched off.

    A run that acts on decisions is refused where the layer is absent, at its configuration and
    at every run and resume. The held window stands behind that refusal: these tests reach it by
    switching the refusal off, as a run would reach it if the refusal were ever bypassed.
    """
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)


@pytest.mark.usefixtures("entry_check_off")
def test_a_decision_in_the_window_of_a_session_without_the_os_layer_is_held_until_confirmed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    rig.dispatcher.during[2] = lambda: _decide_quietly(run_dir, "run-1-s1")
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    _layer(loop, present=False)
    loop.run()
    loop.close()
    taken = _of(run_dir, DecisionTaken)
    assert [(t.acts, t.why_not) for t in taken] == [(False, "held_os_layer_off")]
    assert [m[0] for m in rig.merger.merges] == ["s2"]
    # Held, it may still act: its worktree is left until it is confirmed and has ended.
    assert "s1" not in rig.merger.removed
    with pytest.raises(RunStateError, match="not held"):
        _resume(rig, confirm=("run-1-s2",), confirmed_by="operator")
    _, kind = _resume(rig, confirm=("run-1-s1",), confirmed_by="operator")
    taken = _of(run_dir, DecisionTaken)
    assert [(t.acts, t.confirmed_by) for t in taken] == [(False, None), (True, "operator")]
    assert [m[0] for m in rig.merger.merges] == ["s2", "s1"] and kind == "done"


@pytest.mark.usefixtures("entry_check_off")
@pytest.mark.parametrize("when", ["before", "after"])
def test_a_leftovers_window_closes_at_its_leftover_read(tmp_path: Path, when: str) -> None:
    # s2's session runs without the OS layer and its orchestrator dies in it, so its window
    # stays open until a resume reads it left over. A decision written before that read may be
    # the session's own and is held; one written after it acts.
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    rig.dispatcher.kill_on = 2
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    _layer(loop, present=False)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    if when == "before":
        decide(run_dir, "approve", item_id="run-1-s1")
    left = [Leftover(session_id="sess-2", pid=7, killed=0, stopped=False)]
    rig.dispatcher = LeftoverDispatcher(trajectories=run_dir / "sessions", left=lambda: left)
    # A resume refused for its confirmation of an item with no decision: by then it has read
    # the leftover, which closes the window, and has taken nothing.
    with pytest.raises(RunStateError, match="not held"):
        _resume(rig, confirm=("run-1-s2",), confirmed_by="operator")
    assert _of(run_dir, DecisionTaken) == []
    read = _of(run_dir, LeftoverRead)
    assert [r.session_id for r in read] == ["sess-2"]
    if when == "after":
        decide(run_dir, "approve", item_id="run-1-s1")
    rig.dispatcher = FakeDispatcher(trajectories=run_dir / "sessions")
    _, kind = _resume(rig)
    taken = _of(run_dir, DecisionTaken)
    if when == "before":
        assert [(t.acts, t.why_not) for t in taken] == [(False, "held_os_layer_off")]
        assert "s1" not in [m[0] for m in rig.merger.merges]
    else:
        assert [(t.acts, t.why_not) for t in taken] == [(True, None)]
        assert "s1" in [m[0] for m in rig.merger.merges] and kind == "done"


def test_a_subtask_that_escalates_again_gets_a_new_item_id(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT, 2: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "reject", "use the table's gain")
    _, kind = _resume(rig)
    assert kind == "done"
    items = read_queue(rig.run_dir).items
    assert [i.item_id for i in items] == ["run-1-s1", "run-1-s1-r2"]
    second = items[1]
    assert second.consequence is not None and second.consequence.attempt == 2
    decide(rig.run_dir, "approve", item_id="run-1-s1-r2")
    again, _ = _resume(rig)
    assert [(m[0], m[1]) for m in rig.merger.merges] == [("s1", 2)]
    assert again.state.subtasks["s1"].status == "done"


# -- resume after the leftovers --------------------------------------------------------------


@dataclass
class LeftoverDispatcher(FakeDispatcher):
    """Stops leftovers as the resume's first phase does: one gone stream, or one set aside."""

    left: Callable[[], list[Leftover]] = field(default=lambda: [])

    def stop_leftovers(self) -> list[Leftover]:
        return self.left()


def _decided_run(tmp_path: Path, dispatcher: FakeDispatcher) -> Rig:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    rig.dispatcher = dispatcher
    return rig


def test_no_decision_is_taken_when_a_leftover_stream_cannot_be_read(tmp_path: Path) -> None:
    def gone() -> list[Leftover]:
        raise InvocationError("the stream of leftover session(s) x cannot be read")

    rig = _decided_run(tmp_path, LeftoverDispatcher(left=gone))
    with pytest.raises(InvocationError):
        _resume(rig)
    assert _of(rig.run_dir, DecisionTaken) == [] and rig.merger.merges == []


def test_a_resume_that_quarantines_a_stream_takes_no_decision(tmp_path: Path) -> None:
    def set_aside() -> list[Leftover]:
        return [
            Leftover(
                session_id="left",
                pid=1,
                killed=0,
                stopped=False,
                quarantine="operator: the disk was replaced",
                scan="unscanned (stream gone)",
            )
        ]

    rig = _decided_run(tmp_path, LeftoverDispatcher(left=set_aside))
    with pytest.raises(RunStateError, match="a person resolves that"):
        _resume(rig, confirm=("run-1-s1",), confirmed_by="operator")
    assert _of(rig.run_dir, DecisionTaken) == [] and rig.merger.merges == []
    assert [h.detail for h in _of(rig.run_dir, Halted)][-1].startswith("stream_quarantined")


# -- killed ----------------------------------------------------------------------------------


@dataclass
class KilledAfterMerge(FakeMerger):
    """Merges, then the orchestrator dies before recording it; the branch has moved."""

    moved: bool = False
    #: Killed on the merge of this subtask, once.
    kill: str | None = "s1"

    def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
        commit = super().merge(subtask_id, attempt, attempt_commit, message)
        if subtask_id == self.kill:
            self.kill = None
            self.moved = True
            raise KilledError
        return commit

    def run_branch_moved(self, expected: str, pending: str | None) -> str | None:
        if not self.moved:
            return None
        if pending is not None and pending == self.merges[-1][2]:
            return None
        return "the run branch moved"


def test_killed_between_the_merge_and_its_record_resumes_to_one_merge(tmp_path: Path) -> None:
    merger = KilledAfterMerge()
    # A first subtask merges, so the run branch has a recorded head the resume holds it to.
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={2: NO_VERDICT}), merger=merger)
    loop = _start(rig, "s0", "s1")
    loop.run()
    loop.close()
    assert [m[0] for m in merger.merges] == ["s0"]
    merger.moved = False
    decide(rig.run_dir, "approve", item_id="run-1-s1")
    with pytest.raises(KilledError):
        _resume(rig)
    assert merger.moved and len(_of(rig.run_dir, Merged)) == 1  # merged in git, not recorded
    _, kind = _resume(rig)
    assert kind == "done"
    assert [m[0] for m in merger.merges] == ["s0", "s1"]
    assert [m.subtask_id for m in _of(rig.run_dir, Merged)] == ["s0", "s1"]
    assert _of(rig.run_dir, Incident) == []


def test_killed_between_decision_taken_and_merge_resumes_to_one_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    real = Loop._merge_attempt

    def killed(self: Loop, *args: Any, **kw: Any) -> bool:
        raise KilledError

    monkeypatch.setattr(Loop, "_merge_attempt", killed)
    with pytest.raises(KilledError):
        _resume(rig)
    assert len(_of(rig.run_dir, DecisionTaken)) == 1
    monkeypatch.setattr(Loop, "_merge_attempt", real)
    _, kind = _resume(rig)
    assert kind == "done"
    assert len(_of(rig.run_dir, DecisionTaken)) == 1 and len(rig.merger.merges) == 1


# -- two faults at once ----------------------------------------------------------------------


def test_an_approve_past_a_gate_failure_on_a_rewritten_item_halts_and_never_merges(
    tmp_path: Path,
) -> None:
    # The binding is checked whatever else the item says: a rewritten line is an incident even
    # where the gate alone would have made the approve record only.
    rig = _rig(tmp_path / "run", gate=FakeGate(verdicts=["fail"] * 3))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    items = rig.run_dir / QUEUE_NAME
    data = items.read_bytes()
    assert b"exceeds the driver's rating" in data
    items.write_bytes(data.replace(b"exceeds the driver's rating", b"is within the rating"))
    _, kind = _resume(rig)
    assert kind == "halted"
    assert [i.cause for i in _of(rig.run_dir, Incident)] == ["queue_item_mismatch"]
    assert rig.merger.merges == [] and _of(rig.run_dir, DecisionTaken) == []


def test_a_confirmed_indicator_in_a_run_that_records_takes_nothing_and_writes_nothing(
    tmp_path: Path,
) -> None:
    rig = _rig(
        tmp_path / "run",
        reviewer=FakeReviewer(results={1: _confirmed(1)}, unavailable={2: NO_VERDICT}),
        config_overrides={"queue_decisions": "record"},
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    assert read_queue(rig.run_dir).items[0].consequence is None
    decide(rig.run_dir, "approve")
    _resume(rig)
    assert _of(rig.run_dir, DecisionTaken) == [] and rig.merger.merges == []


# -- the operator's flag ---------------------------------------------------------------------


def test_confirm_is_an_operator_flag_of_resume_recorded_with_the_os_user() -> None:
    import argparse
    import getpass

    from physgate.orchestrator.cli import _confirm_request, add_parsers

    top = argparse.ArgumentParser()
    add_parsers(top.add_subparsers(dest="cmd"))
    base = ["--run-dir", "r", "--target", "t", "--install", "i", "--review-root", "x"]
    args = top.parse_args(["resume", *base, "--confirm", "a", "--confirm", "b"])
    assert _confirm_request(args) == (("a", "b"), getpass.getuser())
    assert _confirm_request(top.parse_args(["resume", *base])) == ((), None)
    with pytest.raises(SystemExit):
        top.parse_args(["run", *base, "--confirm", "a"])


# -- a run that only records -----------------------------------------------------------------


def test_a_record_mode_run_takes_no_decision_and_writes_no_consequence(tmp_path: Path) -> None:
    rig = _rig(
        tmp_path / "run",
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
        config_overrides={"queue_decisions": "record"},
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    assert read_queue(rig.run_dir).items[0].consequence is None
    record_decision(rig.run_dir, "run-1-s1", decision="approve", resolved_by="yasin")
    _resume(rig)
    assert _of(rig.run_dir, DecisionTaken) == [] and rig.merger.merges == []
    with pytest.raises(RunStateError, match="only records"):
        _resume(rig, confirm=("run-1-s1",), confirmed_by="operator")


# -- what the listing says the run did ---------------------------------------------------------


def _decided(run_dir: Path) -> list[dict[str, Any]]:
    from physgate.orchestrator.queue import queue_listing

    decided = queue_listing(run_dir)["decided"]
    assert isinstance(decided, list)
    return decided


def test_the_listing_says_what_the_run_did_with_each_decision_it_took(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    decide(rig.run_dir, "approve")
    (before,) = _decided(rig.run_dir)
    assert "taken" not in before  # not taken yet
    _resume(rig)
    (after,) = _decided(rig.run_dir)
    assert after["taken"] == {
        "effect": "merge",
        "acts": True,
        "why_not": None,
        "confirmed_by": None,
        "order_too_long": False,
    }


def test_a_record_runs_listing_is_as_it_always_was(tmp_path: Path) -> None:
    rig = _rig(
        tmp_path / "run",
        reviewer=FakeReviewer(unavailable={1: NO_VERDICT}),
        config_overrides={"queue_decisions": "record"},
    )
    loop = _start(rig, "s1")
    loop.run()
    loop.close()
    record_decision(rig.run_dir, "run-1-s1", decision="approve", resolved_by="yasin")
    _resume(rig)
    (decided,) = _decided(rig.run_dir)
    assert set(decided) == {"item_id", "ts", "kind", "decision", "resolved_by", "flag"}
