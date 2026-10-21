"""A person's decision taken into a run is a line of the event log, replayed like every other.

ARCH-133. The ``decision_taken`` line says what the decision did, and replay holds it to what
the lines before it allow: an approve merges only an attempt every automated check let through,
of a subtask no review of which confirmed a reward-hacking indicator, and names exactly that
attempt and its checked commit; a reject retries only with budget left, orders the one fix only
after a blocked review, and otherwise ends the subtask. The fix is the subtask's last attempt and
is routed by rule, never asked about. Each decision is taken once, on the item its subtask waits
on; a subtask that comes back to the queue gets a new item, by round. What follows each effect
replays from the file alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from decision_rig import DIGEST, TS
from decision_rig import decide as _decide
from decision_rig import escalated as _escalated
from loop_fakes import (
    FakeDispatcher,
    FakeReviewer,
    Rig,
    failing_gate_result,
    sha,
)

from physgate.orchestrator.decisions import (
    decision_effect,
    item_consequence,
    source_of,
)
from physgate.orchestrator.events import (
    AttemptRejected,
    DecisionTaken,
    DiffChecked,
    Escalated,
    EscalationDecided,
    GateRan,
    Merged,
    ProposalsChecked,
    SessionEnded,
    StageEntered,
    SubtaskRejected,
    read_events,
)
from physgate.orchestrator.exceptions import (
    MergePreconditionError,
    QueueItemMismatchError,
    ReviewUnavailableError,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import QueueItem, QueueResolution, unavailable_item
from physgate.orchestrator.repair import Finding
from physgate.orchestrator.replay import replay, require_mergeable


def _replayed(loop: Loop) -> list[str]:
    """The subtask's status and next step, from a fresh read of the file alone."""
    state = replay(read_events(loop.run_dir / "events.jsonl"))
    step = state.next_step()
    return [state.subtasks["s1"].status, step.kind, str(step.attempt), str(step.point)]


# -- what each verb does -------------------------------------------------------------------


def test_an_approve_on_review_unavailable_puts_the_attempt_back_at_its_merge(
    tmp_path: Path,
) -> None:
    loop = _escalated(tmp_path, "unavailable")
    _decide(loop, "approve", note=None)
    now = loop.state.subtasks["s1"].attempts[-1]
    assert now.approved is not None and loop.state.mergeable(now)
    assert _replayed(loop) == ["active", "attempt", "1", "merge"]
    line = require_mergeable(loop.ledger.path, "s1", "on")
    assert (line.person_decision, line.queue_item, line.review_result) == (
        "approve",
        "run-1-s1",
        None,
    )


def test_an_approved_attempt_merges_exactly_its_checked_commit_and_is_done(
    tmp_path: Path,
) -> None:
    loop = _escalated(tmp_path, "review_exhausted")
    decided = _decide(loop, "approve", note=None)
    assert decided.effect == "merge"
    checked = loop.state.subtasks["s1"].attempts[-1].changes
    assert checked is not None
    other = sha("not the checked commit")
    with pytest.raises(ValueError, match="other than the one that was checked"):
        loop.record.emit(
            Merged(
                **loop.record.envelope(),
                subtask_id="s1",
                attempt=3,
                attempt_commit=other,
                merge_commit=sha("m"),
            )
        )
    loop.record.emit(
        Merged(
            **loop.record.envelope(),
            subtask_id="s1",
            attempt=3,
            attempt_commit=checked.checked_commit,
            merge_commit=sha("m"),
        )
    )
    loop.record.emit(
        StageEntered(**loop.record.envelope(), subtask_id="s1", attempt=3, stage="diff")
    )
    loop.record.emit(
        DiffChecked(**loop.record.envelope(), subtask_id="s1", attempt=3, divergences=())
    )
    assert _replayed(loop) == ["done", "integrate", "None", "None"]


def test_a_reject_with_budget_left_starts_the_next_attempt(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    _decide(loop, "reject", note="look again at the gain")
    assert _replayed(loop) == ["active", "attempt", "2", "resolve"]
    assert loop.ledger.find("s1") is not None


def test_a_reject_with_no_budget_ends_the_subtask_rejected(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "review_exhausted")
    decided = _decide(loop, "reject", note="split it")
    assert decided.effect == "end_subtask"
    assert _replayed(loop) == ["active", "end_subtask", "3", "None"]
    with pytest.raises(ValueError, match="another item"):
        loop.record.emit(
            SubtaskRejected(
                **loop.record.envelope(), subtask_id="s1", attempt=3, by="person", item_id="x"
            )
        )
    loop.record.emit(
        SubtaskRejected(
            **loop.record.envelope(), subtask_id="s1", attempt=3, by="person", item_id="run-1-s1"
        )
    )
    assert _replayed(loop)[:2] == ["rejected", "integrate"]


def test_a_reject_on_a_blocked_review_orders_one_fix_as_the_last_attempt(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "blocked")
    decided = _decide(loop, "reject", note="the mass is in the frame drawing")
    assert decided.effect == "fix"
    assert _replayed(loop) == ["active", "attempt", "2", "resolve"]
    loop.record.emit(
        StageEntered(**loop.record.envelope(), subtask_id="s1", attempt=2, stage="resolve")
    )
    assert loop.state.subtasks["s1"].attempts[-1].fix


# -- what the record refuses ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "verb", "override", "why"),
    [
        (
            "gate_exhausted",
            "approve",
            {"effect": "merge", "acts": True, "why_not": None},
            "other than the record allows",
        ),
        (
            "indicator_then_unavailable",
            "approve",
            {"effect": "merge", "acts": True, "why_not": None},
            "other than the record allows",
        ),
        (
            "review_exhausted",
            "approve",
            {"attempt_commit": sha("other")},
            "another attempt or commit",
        ),
        ("review_exhausted", "approve", {"attempt": 2}, "another attempt or commit"),
        ("review_exhausted", "reject", {"effect": "retry"}, "other than the record allows"),
        ("unavailable", "reject", {"effect": "fix"}, "other than the record allows"),
        ("blocked", "reject", {"effect": "retry"}, "other than the record allows"),
        ("unavailable", "approve", {"item_id": "run-1-s1-r2"}, "not waiting on"),
    ],
    ids=[
        "approve past a gate failure",
        "approve with a confirmed indicator in the history",
        "approve naming another commit",
        "approve naming another attempt",
        "retry with no budget",
        "fix without a blocked review",
        "retry after a blocked review",
        "an item the subtask is not waiting on",
    ],
)
def test_a_decision_the_record_does_not_allow_is_refused(
    tmp_path: Path, scenario: str, verb: str, override: dict[str, Any], why: str
) -> None:
    loop = _escalated(tmp_path, scenario)
    size = (loop.run_dir / "events.jsonl").stat().st_size
    with pytest.raises(ValueError, match=why):
        _decide(loop, verb, **override)
    assert (loop.run_dir / "events.jsonl").stat().st_size == size


def test_a_decision_is_taken_once_on_its_item(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "gate_exhausted")
    _decide(loop, "approve", note=None, why_not="last_rejection_automated")
    with pytest.raises(ValueError, match="taken once"):
        _decide(loop, "approve", note=None, why_not="last_rejection_automated")


def test_no_decision_is_taken_while_an_attempt_is_in_progress(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    _decide(loop, "reject", note="again")
    loop.record.emit(
        StageEntered(**loop.record.envelope(), subtask_id="s1", attempt=2, stage="resolve")
    )
    forged = DecisionTaken(
        **loop.record.envelope(),
        subtask_id="s1",
        item_id="run-1-s1-r2",
        verb="reject",
        note="again",
        resolved_by="yasin",
        decided_ts=TS,
        decision_offset=0,
        shown_sha256=DIGEST,
        attempt=2,
        attempt_commit=None,
        effect="retry",
        acts=True,
        why_not=None,
    )
    with pytest.raises(ValueError, match="not waiting on"):
        loop.record.emit(forged)


# -- the fix is routed by rule -------------------------------------------------------------


def _start_fix(tmp_path: Path) -> Loop:
    loop = _escalated(tmp_path, "blocked")
    _decide(loop, "reject", note="the mass is in the frame drawing")
    return loop


def _fix_attempt_rejected_by_the_gate(loop: Loop) -> None:
    """Write the fix attempt's lines as the loop writes them, to a gate failure."""
    env = loop.record.envelope
    emit = loop.record.emit
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="resolve"))
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="spawn", decisions_bytes=0))
    commit = sha("fix")
    emit(
        SessionEnded(
            **env(),
            subtask_id="s1",
            attempt=2,
            session_id="sess-fix",
            outcome="completed",
            cause=None,
            attempt_commit=commit,
            trajectory="sessions/sess-fix/stdout.jsonl",
            decisions_bytes=0,
            worktree="worktrees/s1",
            reading_verified=True,
        )
    )
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="verify_reading"))
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="implement"))
    emit(
        ProposalsChecked(
            **env(),
            subtask_id="s1",
            attempt=2,
            checked_commit=commit,
            refused_by=None,
            reason=None,
            subject=None,
            graph_root="scratch/graph",
        )
    )
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="gate"))
    result = failing_gate_result("on")
    emit(GateRan(**env(), subtask_id="s1", attempt=2, result=result))
    emit(StageEntered(**env(), subtask_id="s1", attempt=2, stage="decide"))
    finding = Finding.from_gate(result)
    emit(
        AttemptRejected(
            **env(),
            subtask_id="s1",
            attempt=2,
            finding=finding,
            finding_key=finding.key(),
            repeats_previous=False,
        )
    )


def test_a_fix_not_accepted_ends_the_subtask_with_no_escalation_question(tmp_path: Path) -> None:
    loop = _start_fix(tmp_path)
    _fix_attempt_rejected_by_the_gate(loop)
    sub = loop.state.subtasks["s1"]
    assert sub.ending == "fix_not_accepted"
    assert sub.attempts[-1].routed is None  # never asked
    assert _replayed(loop) == ["active", "end_subtask", "2", "None"]
    state = loop.state
    decided = EscalationDecided(
        **loop.record.envelope(),
        subtask_id="s1",
        attempt=2,
        decision=state.subtasks["s1"].attempts[0].decided.decision,  # type: ignore[union-attr]
        state=state.subtasks["s1"].attempts[0].decided.state,  # type: ignore[union-attr]
    )
    with pytest.raises(ValueError, match="escalation decision"):
        state.check(decided)
    with pytest.raises(ValueError, match="another item"):
        state.check(
            SubtaskRejected(
                **loop.record.envelope(),
                subtask_id="s1",
                attempt=2,
                by="fix_not_accepted",
                item_id="run-1-s1",
            )
        )
    loop.record.emit(
        SubtaskRejected(
            **loop.record.envelope(),
            subtask_id="s1",
            attempt=2,
            by="fix_not_accepted",
            item_id=None,
        )
    )
    assert _replayed(loop)[:2] == ["rejected", "integrate"]


def test_no_attempt_follows_the_fix(tmp_path: Path) -> None:
    loop = _start_fix(tmp_path)
    _fix_attempt_rejected_by_the_gate(loop)
    loop.state.subtasks["s1"].next_resolve = 3  # as a forged line would claim
    with pytest.raises(ValueError, match="last attempt"):
        loop.state.check(
            StageEntered(**loop.record.envelope(), subtask_id="s1", attempt=3, stage="resolve")
        )


# -- rounds --------------------------------------------------------------------------------


def test_a_subtask_that_escalates_again_gets_a_new_item_id(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    _decide(loop, "reject", note="again")
    loop.close()
    rig = Rig(
        loop.run_dir,
        dispatcher=FakeDispatcher(trajectories=loop.run_dir / "sessions"),
        reviewer=FakeReviewer(
            unavailable={1: ReviewUnavailableError("no verdict", cause="invalid_verdict")}
        ),
    )
    again = rig.open()
    assert again.run().kind in ("done", "escalated")
    escalations = [
        e for e in read_events(again.run_dir / "events.jsonl") if isinstance(e, Escalated)
    ]
    assert [e.item_id for e in escalations] == ["run-1-s1", "run-1-s1-r2"]


def test_an_escalation_that_reuses_an_item_id_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _escalated(tmp_path, "unavailable")
    _decide(loop, "reject", note="again")
    loop.close()
    rig = Rig(
        loop.run_dir,
        dispatcher=FakeDispatcher(trajectories=loop.run_dir / "sessions"),
        reviewer=FakeReviewer(
            unavailable={1: ReviewUnavailableError("no verdict", cause="invalid_verdict")}
        ),
    )
    again = rig.open()
    # The id items had before they carried a round: the second escalation reuses the first's.
    monkeypatch.setattr(Loop, "_next_item_id", lambda self, subtask_id: f"run-1-{subtask_id}")
    with pytest.raises(ValueError, match="next round"):
        again.run()


# -- integration ---------------------------------------------------------------------------


def test_a_decision_that_acts_reopens_an_integration_skipped_as_incomplete(
    tmp_path: Path,
) -> None:
    loop = _escalated(tmp_path, "unavailable")
    skipped = loop.state.integration
    assert skipped is not None and skipped.kind == "integration_gate_skipped"
    _decide(loop, "approve", note=None)
    assert loop.state.integration is None


def test_a_decision_that_does_not_act_leaves_integration_closed(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "gate_exhausted")
    _decide(loop, "approve", note=None, why_not="last_rejection_automated")
    assert loop.state.integration is not None
    assert _replayed(loop)[:2] == ["escalated", "done"]


# -- the effect the loop computes ----------------------------------------------------------


def _item(loop: Loop, *, consequence: object = "computed") -> QueueItem:
    sub = loop.state.subtasks["s1"]
    computed = item_consequence(loop.state, "s1", source=source_of(sub), scan_hits=())
    return unavailable_item(
        item_id=str(sub.queue_item),
        run_id="run-1",
        subtask_id="s1",
        attempt=sub.attempts[-1].number,
        source="review_unavailable",
        cause="invalid_verdict",
        detail="no verdict",
        spec_defects=(),
        artefact_diff="diff",
        trajectory="sessions/sess-1/stdout.jsonl",
        ts=TS,
        consequence=computed if consequence == "computed" else consequence,  # type: ignore[arg-type]
    )


def _resolution(verb: str | None, shown: str | None = DIGEST) -> QueueResolution:
    return QueueResolution(
        item_id="run-1-s1",
        ts=TS,
        decision={"approve": "approve", "reject": "reject: split it"}.get(verb or "", "free text"),
        resolved_by="yasin",
        verb=verb,  # type: ignore[arg-type]
        note="split it" if verb == "reject" else None,
        shown_sha256=shown if verb else None,
    )


def test_the_effect_of_a_bound_approve_is_the_merge_the_item_names(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    taken = decision_effect(
        loop.state,
        _item(loop),
        _resolution("approve"),
        line_sha256=DIGEST,
        scan_hits=(),
        held=False,
    )
    assert (taken.effect, taken.acts, taken.why_not) == ("merge", True, None)
    held = decision_effect(
        loop.state, _item(loop), _resolution("approve"), line_sha256=DIGEST, held=True, scan_hits=()
    )
    assert (held.effect, held.acts, held.why_not) == ("merge", False, "held_os_layer_off")


def test_a_free_text_or_legacy_decision_never_acts(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    unbound = decision_effect(
        loop.state, _item(loop), _resolution(None), line_sha256=DIGEST, scan_hits=(), held=False
    )
    assert (unbound.acts, unbound.why_not) == (False, "not_bound")
    legacy = decision_effect(
        loop.state,
        _item(loop, consequence=None),
        _resolution("approve"),
        line_sha256=DIGEST,
        scan_hits=(),
        held=False,
    )
    assert (legacy.acts, legacy.why_not) == (False, "legacy_item")


def test_an_item_rewritten_after_its_decision_is_a_mismatch(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "unavailable")
    with pytest.raises(QueueItemMismatchError, match="not the one the decision"):
        decision_effect(
            loop.state,
            _item(loop),
            _resolution("approve"),
            line_sha256="b" * 64,
            scan_hits=(),
            held=False,
        )
    lying = _item(loop).consequence
    assert lying is not None
    forged = lying.model_copy(update={"on_reject": "end_subtask"})
    with pytest.raises(QueueItemMismatchError, match="another consequence"):
        decision_effect(
            loop.state,
            _item(loop, consequence=forged),
            _resolution("reject"),
            line_sha256=DIGEST,
            scan_hits=(),
            held=False,
        )


def test_a_confirmed_indicator_on_any_earlier_attempt_makes_approve_record_only(
    tmp_path: Path,
) -> None:
    loop = _escalated(tmp_path, "indicator_then_unavailable")
    consequence = _item(loop).consequence
    assert consequence is not None
    assert consequence.on_approve == "record_only"
    assert consequence.why_record_only == "indicator_in_history"
    assert [(c.attempt, c.kind) for c in consequence.confirmed_indicators] == [
        (1, "disabled_checks")
    ]
    taken = decision_effect(
        loop.state,
        _item(loop),
        _resolution("approve"),
        line_sha256=DIGEST,
        scan_hits=(),
        held=False,
    )
    assert (taken.acts, taken.why_not) == (False, "indicator_in_history")


def test_a_ledger_line_a_person_approved_permits_the_merge_and_no_other(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "review_exhausted")
    with pytest.raises(MergePreconditionError):
        require_mergeable(loop.ledger.path, "s1", "on")
    _decide(loop, "approve", note=None)
    line = require_mergeable(loop.ledger.path, "s1", "on")
    assert (line.review_result, line.person_decision) == ("fail", "approve")


@pytest.mark.parametrize(
    ("scenario", "why"),
    [
        ("gate_exhausted", "gate"),
        ("indicator_then_unavailable", "indicator_in_history"),
        ("review_exhausted", None),
        ("unavailable", None),
        ("blocked", None),
    ],
)
def test_the_item_says_approve_records_only_where_an_automated_check_or_an_indicator_refused(
    tmp_path: Path, scenario: str, why: str | None
) -> None:
    loop = _escalated(tmp_path, scenario)
    sub = loop.state.subtasks["s1"]
    consequence = item_consequence(loop.state, "s1", source=source_of(sub), scan_hits=())
    assert consequence.why_record_only == why
    assert consequence.on_approve == ("record_only" if why else "merge_attempt")


def test_a_scan_hit_on_an_item_no_review_judged_makes_approve_record_only(tmp_path: Path) -> None:
    from physgate.reviewers.scan import ScanHit

    loop = _escalated(tmp_path, "unavailable")
    hit = ScanHit(kind="disabled_checks", evidence="toolu_9", what="a test skipped")
    consequence = item_consequence(loop.state, "s1", source="review_unavailable", scan_hits=(hit,))
    assert (consequence.on_approve, consequence.why_record_only) == ("record_only", "scan_hit")
    # The same hit on an item whose review judged the scan changes nothing: the review did.
    judged = _escalated(tmp_path / "judged", "review_exhausted")
    sub = judged.state.subtasks["s1"]
    assert (
        item_consequence(judged.state, "s1", source=source_of(sub), scan_hits=(hit,)).scan_hits
        == ()
    )


def test_a_gate_failure_and_a_stale_digest_together_halt_on_the_digest(tmp_path: Path) -> None:
    loop = _escalated(tmp_path, "gate_exhausted")
    sub = loop.state.subtasks["s1"]
    item = escalation_item_of(loop)
    with pytest.raises(QueueItemMismatchError, match="not the one the decision"):
        decision_effect(
            loop.state, item, _resolution("approve"), line_sha256="c" * 64, scan_hits=(), held=False
        )
    taken = decision_effect(
        loop.state, item, _resolution("approve"), line_sha256=DIGEST, scan_hits=(), held=False
    )
    assert (taken.acts, taken.why_not) == (False, "last_rejection_automated")
    assert sub.status == "escalated"


def escalation_item_of(loop: Loop) -> QueueItem:
    from physgate.orchestrator.queue import escalation_item

    sub = loop.state.subtasks["s1"]
    return escalation_item(
        item_id=str(sub.queue_item),
        run_id="run-1",
        subtask_id="s1",
        findings=tuple(a.rejected.finding for a in sub.attempts if a.rejected is not None),
        artefact_diff="diff",
        trajectories=tuple(f"sessions/sess-{n}/stdout.jsonl" for n in (1, 2, 3)),
        ts=TS,
        consequence=item_consequence(loop.state, "s1", source=source_of(sub), scan_hits=()),
    )
