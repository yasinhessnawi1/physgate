"""The escalation decision's state is copied from the records it names, and from nothing else.

ARCH-131's state is the subtask record at the end of an attempt: the task-ledger line,
the gate result, the reviewer verdict and the changed-node summary, with no free text.
Each run here plants a distinctive value in each source record, then builds the state
from the replayed event log (as the loop will) and checks every field against the
record it says it comes from. A field copied from the wrong record, or a part left
out, shows as a planted value missing or misplaced.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeChanges, FakeDispatcher, FakeGate, FakeReviewer, Rig, plan
from pydantic import BaseModel

from physgate.orchestrator.escalation_state import (
    SOURCES,
    EscalationState,
    escalation_state,
)
from physgate.orchestrator.events import (
    AttemptRejected,
    Event,
    GateRan,
    ProposalsChecked,
    ReviewRan,
    ReviewUnavailable,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError, RunStateError
from physgate.orchestrator.protocols import (
    CriterionDefect,
    CriterionVerdict,
    IndicatorReport,
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    UnavailableCause,
    Usage,
)
from physgate.orchestrator.replay import RunState, replay

#: The only string fields the state may carry: identifiers, never prose.
IDENTIFIERS = {
    "LedgerPart.subtask_id",
    "LedgerPart.assigned_role",
    "ChangesPart.proposed",
    "ReviewPart.failing_item",
    "ReviewItem.item",
}


def _usage() -> tuple[MessageUsage, ...]:
    return (
        MessageUsage(
            message_id="r",
            usage=Usage(
                input_tokens=1,
                output_tokens=1,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        ),
    )


def rich_rejection(n: int) -> ReviewResult:
    """A rejecting review with something in every structured field the state copies."""
    return ReviewResult(
        verdict="fail",
        finding="the gain changed silently",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=_usage(),
        failing_item="DS-2",
        items=(
            ItemVerdict(item="DS-2", section="domain_standards", result="unmet", evidence="a:1"),
            ItemVerdict(item="AC-1", section="acceptance_criteria", result="met", evidence="a:2"),
            ItemVerdict(item="RH-1", section="reward_hacking", result="noted", evidence="a:3"),
        ),
        criteria=(
            CriterionVerdict(criterion="1", result="met", evidence="x"),
            CriterionVerdict(criterion="2", result="met", evidence="x"),
            CriterionVerdict(criterion="3", result="unmet", evidence="x"),
            CriterionVerdict(
                criterion="4",
                result="not evaluable",
                evidence="x",
                defect=CriterionDefect(finding="no load is given", blocking=False),
            ),
        ),
        indicators=(
            IndicatorReport(
                kind="hard_coded_values", evidence="e", disposition="noted", reason="r"
            ),
        ),
        spec_defects=(SpecDefect(finding="stated twice", blocking=False),),
        rubric_kind="paired",
        reading_verified=True,
    )


def blocked_review(n: int) -> ReviewResult:
    return ReviewResult(
        verdict="blocked",
        finding="no unstable pole is given",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=_usage(),
        spec_defects=(
            SpecDefect(finding="no unstable pole is given", blocking=True, item="DS-4"),
            SpecDefect(finding="stated twice", blocking=False),
        ),
    )


def unavailable(cause: UnavailableCause) -> ReviewUnavailableError:
    return ReviewUnavailableError(
        "no verdict", cause=cause, session_id=f"rev-{cause}", reviewer_model="claude-opus-5-5"
    )


def run(tmp_path: Path, rig: Rig) -> list[Event]:
    loop = rig.open()
    try:
        loop.start(plan("s1"))
        loop.run()
    finally:
        loop.close()
    return read_events(tmp_path / "events.jsonl")


def state_after(
    events: list[Event], ends: Callable[[Event], bool]
) -> tuple[EscalationState, Event]:
    """The state built from the log up to and including the first line ``ends`` picks."""
    at = next(i for i, e in enumerate(events) if ends(e))
    replayed = replay(events[: at + 1])
    return escalation_state(replayed, "s1"), events[at]


def _last[E](events: list[Event], kind: type[E], before: Event) -> E:
    found = [e for e in events if isinstance(e, kind) and e.seq <= before.seq]
    return found[-1]


def test_a_rejection_s_state_copies_each_part_from_its_own_record(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        gate_mode="observe",
        gate=FakeGate(verdicts=["fail", "fail"]),
        changes=FakeChanges(proposed={1: ("motor.left",), 2: ("motor.left", "power.budget")}),
        reviewer=FakeReviewer(results={1: rich_rejection(1), 2: rich_rejection(2)}),
    )
    events = run(tmp_path, rig)
    state, ended = state_after(events, lambda e: isinstance(e, AttemptRejected) and e.attempt == 2)
    assert isinstance(ended, AttemptRejected)
    replayed = replay(events[: ended.seq + 1])
    line = [ln for ln in replayed.ledger if ln.id == "s1"][-1]
    assert state.ledger.model_dump() == {
        "subtask_id": line.id,
        "assigned_role": line.assigned_role,
        "attempt_count": line.attempt_count,
        "gate_result": line.gate_result,
        "review_result": line.review_result,
    }
    assert (state.ledger.attempt_count, state.ledger.gate_result) == (2, "fail")
    assert state.ended.model_dump() == {
        "kind": "rejected",
        "rejected_by": ended.finding.source,
        "repeats_previous": ended.repeats_previous,
        "unavailable_cause": None,
        "review_retried": False,
    }
    assert (state.ended.rejected_by, state.ended.repeats_previous) == ("review", True)
    checked = _last(events, ProposalsChecked, ended)
    assert state.changes is not None
    assert state.changes.proposed == checked.proposed == ("motor.left", "power.budget")
    gate = _last(events, GateRan, ended).result
    assert state.gate is not None
    assert (state.gate.ran, state.gate.mode, state.gate.verdict) == (True, "observe", "fail")
    assert state.gate.failing_check == gate.failing_check == "magnitude"
    assert [(c.check, c.scope, c.outcome, c.blocking) for c in state.gate.checks] == [
        (r.name, r.scope, r.outcome, r.blocking) for r in gate.checks
    ]
    review = _last(events, ReviewRan, ended).result
    assert state.review is not None
    assert state.review.verdict == review.verdict == "fail"
    assert (state.review.rubric_kind, state.review.reading_verified) == ("paired", True)
    assert state.review.failing_item == "DS-2"
    assert [(i.item, i.section, i.result) for i in state.review.items] == [
        (i.item, i.section, i.result) for i in review.items
    ]
    assert state.review.criteria.model_dump() == {"met": 2, "unmet": 1, "not_evaluable": 1}
    assert [(i.kind, i.disposition) for i in state.review.indicators] == [
        ("hard_coded_values", "noted")
    ]
    assert (state.review.spec_defects, state.review.blocking_spec_defects) == (1, 0)
    assert (state.attempt_end, state.attempt_count) == ("rejected", 2)


def test_a_blocked_review_s_state(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer(results={1: blocked_review(1)}))
    events = run(tmp_path, rig)
    state, _ = state_after(
        events, lambda e: isinstance(e, ReviewRan) and e.result.verdict == "blocked"
    )
    assert state.ended.kind == "review_blocked"
    assert state.ledger.review_result == "blocked"
    assert state.review is not None
    assert (
        state.review.verdict,
        state.review.spec_defects,
        state.review.blocking_spec_defects,
    ) == (
        "blocked",
        2,
        1,
    )
    assert state.gate is not None and state.gate.verdict == "pass"


def test_a_review_with_no_verdict_after_its_retry(tmp_path: Path) -> None:
    rig = Rig(
        tmp_path,
        reviewer=FakeReviewer(
            unavailable={1: unavailable("infrastructure"), 2: unavailable("infrastructure")}
        ),
    )
    events = run(tmp_path, rig)
    state, ended = state_after(events, lambda e: isinstance(e, ReviewUnavailable) and not e.retry)
    assert isinstance(ended, ReviewUnavailable)
    assert state.ended.model_dump() == {
        "kind": "review_unavailable",
        "rejected_by": None,
        "repeats_previous": None,
        "unavailable_cause": ended.cause,
        "review_retried": True,
    }
    assert state.review is None
    assert state.ledger.review_result is None


def test_an_attempt_that_never_read_its_specification_has_no_later_parts(tmp_path: Path) -> None:
    events = run(tmp_path, Rig(tmp_path, dispatcher=FakeDispatcher(unread={1, 2, 3})))
    state, _ = state_after(events, lambda e: isinstance(e, AttemptRejected))
    assert (state.changes, state.gate, state.review) == (None, None, None)
    assert state.ended.rejected_by == "reading"
    assert state.ended.repeats_previous is False


def test_a_write_scope_refusal_proposed_nothing_and_the_gate_never_ran(tmp_path: Path) -> None:
    rig = Rig(tmp_path, changes=FakeChanges(refuse={1: ("write_scope", "outside")}))
    events = run(tmp_path, rig)
    state, _ = state_after(events, lambda e: isinstance(e, AttemptRejected))
    assert state.changes is not None
    assert (state.changes.refused_by, state.changes.proposed) == ("write_scope", ())
    assert state.gate is None


def test_a_skipped_gate_is_recorded_as_skipped_under_off(tmp_path: Path) -> None:
    rig = Rig(tmp_path, gate_mode="off", reviewer=FakeReviewer(verdicts=["fail"]))
    events = run(tmp_path, rig)
    state, _ = state_after(events, lambda e: isinstance(e, AttemptRejected))
    assert state.gate is not None
    assert state.gate.model_dump() == {
        "ran": False,
        "mode": "off",
        "verdict": None,
        "failing_check": None,
        "checks": (),
    }
    assert state.ledger.gate_result == "skipped"


def test_the_state_is_built_only_at_an_attempt_end_that_did_not_merge(tmp_path: Path) -> None:
    events = run(tmp_path, Rig(tmp_path))
    with pytest.raises(RunStateError):
        escalation_state(replay(events), "s1")
    with pytest.raises(RunStateError):
        escalation_state(RunState(), "s1")


def test_a_ledger_line_that_disagrees_with_the_attempt_is_refused(tmp_path: Path) -> None:
    events = run(tmp_path, Rig(tmp_path, reviewer=FakeReviewer(verdicts=["fail"] * 3)))
    replayed = replay(events)
    replayed.ledger = [
        ln.model_copy(update={"attempt_count": 1}) if ln is replayed.ledger[-1] else ln
        for ln in replayed.ledger
    ]
    with pytest.raises(RunStateError):
        escalation_state(replayed, "s1")


def test_every_part_names_its_source_record() -> None:
    assert set(SOURCES) == set(EscalationState.model_fields)
    assert all(SOURCES.values())


def _string_fields(model: type[BaseModel], seen: set[type[BaseModel]]) -> set[str]:
    found: set[str] = set()
    if model in seen:
        return found
    seen.add(model)
    for name, info in model.model_fields.items():
        for leaf in _leaves(info.annotation):
            if isinstance(leaf, type) and issubclass(leaf, BaseModel):
                found |= _string_fields(leaf, seen)
            elif leaf is str:
                found.add(f"{model.__name__}.{name}")
    return found


def _leaves(annotation: Any) -> list[Any]:  # noqa: ANN401 - any type annotation
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _leaves(typing.get_args(annotation)[0])
    if origin is typing.Literal:
        return []
    if origin in (typing.Union, types.UnionType, tuple, list, dict):
        return [leaf for arg in typing.get_args(annotation) for leaf in _leaves(arg)]
    return [annotation]


def test_the_state_carries_no_free_text_only_identifiers() -> None:
    assert _string_fields(EscalationState, set()) == IDENTIFIERS


def test_the_change_check_reads_the_proposed_nodes_from_the_real_proposals(
    tmp_path: Path,
) -> None:
    from stand_in_drive_plan import DRIVE_MODULE  # noqa: PLC0415 - the real-git rig's plan
    from ui_three_mode_rig import three_mode_runs  # noqa: PLC0415 - real git, store and gate

    expected = tuple(sorted(str(p["id"]) for p in DRIVE_MODULE))
    seen = 0
    for run_dir in three_mode_runs(tmp_path, tmp_path / "runs"):
        for line in read_events(run_dir / "events.jsonl"):
            if isinstance(line, ProposalsChecked):
                assert line.refused_by is None
                assert line.proposed == expected
                seen += 1
    assert seen >= 3
    assert expected
