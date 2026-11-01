"""The follow-up session after sizing's closing pass: told by code, judged once, never retried.

A follow-up reopens a domain module the closing pass reached (its record and its replay are the
rows beside this one). Its one attempt is told, by code and as data, each edge it owes and the
changed node's values as the closing pass left them in the journal, and what to do: rewrite the
named node to agree, or keep its values and write ``no_change_justified`` under the changed node's
id. Never a session's words, nor a node's free-text provenance. Its reviewer is told it reviews a
follow-up and what the session was told.

It is gated, reviewed and merged like any attempt. Not merged (a gate fail, a review reject, a
block, no verdict, a dispute for a person), it ends: no further attempt, no fix, no item; the
earlier merge stands and the integration call comes next, which the propagation check then fails
under ``on``. It is no fix at attempt four, and a module with no attempt left (it merged on its
fix) is owed none. A process killed between two follow-up lines writes the rest on resume.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import CLOSING, PerAttempt, events_of, refusal, resume
from loop_fakes import FakeReviewer, Rig
from pydantic import ValidationError
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_follow_up_after_the_closing_pass_is_recorded_and_replayed_as_the_record_owes import (
    BUS,
    DRIVER,
    LOOP,
    TWO_MODULES,
    ended,
    follow_ups,
    kinds,
    node,
    slice_rig,
)
from test_a_queue_decision_acts_at_a_boundary import decide

from physgate.evaluation.observe.sequence import decisions
from physgate.orchestrator.events import EnvironmentRecorded, Event, OsLayerChecked, Resumed
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import Artefact, PersonOrder
from physgate.orchestrator.replay import replay
from physgate.reviewers.packet import person_order_text

SOURCE = "SOURCE-CANARY datasheet table 4"
WRITER = "WRITER-CANARY sizing pass"


def canaried(rig: Rig) -> Rig:
    """The closing pass writes the bus at 3 A with free text in its provenance."""
    bus = node(BUS, "sizing", constrains=[DRIVER], amps=3.0)
    bus["quantities"]["peak_current"] |= {"source": SOURCE, "written_by": WRITER}
    rig.diff.writes["zc"] = [bus]  # type: ignore[attr-defined]
    return rig


def at(events: list[Event], kind: str, subtask_id: str, attempt: int) -> list[dict[str, Any]]:
    return [
        d
        for e in events
        if e.kind == kind
        and (d := e.model_dump(mode="json")).get("subtask_id") == subtask_id
        and d.get("attempt") == attempt
    ]


def reviewed(rig: Rig, subtask_id: str, attempt: int) -> Artefact:
    return next(a for a in rig.reviewer.seen if (a.subtask_id, a.attempt) == (subtask_id, attempt))


# --- what the session and its reviewer are told ----------------------------------------------


def test_the_follow_up_is_told_each_owed_edge_and_the_changed_values_by_code(
    tmp_path: Path,
) -> None:
    rig = canaried(slice_rig(tmp_path))
    assert ended(rig, plan=CLOSING) == "done"
    (request,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == ("s1", 2)]
    told = request.repair_instruction or ""
    assert f'"{BUS}"' in told and f'"{DRIVER}"' in told, told
    assert '"peak_current"' in told and '3.0 "ampere"' in told, told
    assert "no_change_justified" in told and "rewrite" in told, told
    assert "SOURCE-CANARY" not in told and "WRITER-CANARY" not in told
    assert request.kind == "attempt"


def test_the_follow_up_s_reviewer_is_told_it_reviews_a_follow_up_and_what_was_told(
    tmp_path: Path,
) -> None:
    rig = canaried(slice_rig(tmp_path))
    assert ended(rig, plan=CLOSING) == "done"
    (request,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == ("s1", 2)]
    order = reviewed(rig, "s1", 2).ordered_by_person
    assert order is not None, "the follow-up's reviewer is told nothing of it"
    assert order.kind == "follow_up"
    assert order.instruction == request.repair_instruction
    assert "item_id" not in order.model_dump()
    text = person_order_text(order).decode()
    assert "follow-up" in text and "by code" in text, text
    assert "person's words" not in text
    # Every other attempt's review is told no order, as before.
    assert reviewed(rig, "s1", 1).ordered_by_person is None


def test_a_follow_up_order_carries_no_item_and_every_other_order_carries_one() -> None:
    try:
        order = PersonOrder(kind="follow_up", of_attempt=1, instruction="told")
    except ValidationError as exc:
        pytest.fail(f"a follow-up's order does not read: {exc}")
    assert json.loads(order.model_dump_json()) == {
        "kind": "follow_up",
        "of_attempt": 1,
        "instruction": "told",
    }
    with pytest.raises(ValidationError):
        PersonOrder(kind="follow_up", item_id="r1-s1-1", of_attempt=1, instruction="told")
    with pytest.raises(ValidationError):
        PersonOrder(kind="fix_after_block", of_attempt=1, instruction="told")
    kept = PersonOrder(kind="fix_after_block", item_id="r1-s1-1", of_attempt=1, instruction="t")
    assert set(json.loads(kept.model_dump_json())) == {
        "kind",
        "item_id",
        "of_attempt",
        "instruction",
    }


def test_a_follow_up_at_attempt_four_is_no_fix(tmp_path: Path) -> None:
    # s1 merges on attempt 3 (the gate failed 1 and 2): its follow-up is attempt 4, the fix slot.
    rig = slice_rig(tmp_path)
    rig.gate = PerAttempt(verdicts=["fail", "fail"])
    outcome = ended(rig, plan=CLOSING)
    events = events_of(rig)
    assert outcome == "done", outcome
    assert [f["attempt"] for f in follow_ups(events)] == [4]
    (request,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == ("s1", 4)]
    assert request.kind == "attempt"
    assert at(events, "merged", "s1", 4), "the follow-up at attempt four did not merge"
    assert refusal(events) is None


# --- not merged, it ends --------------------------------------------------------------------


def _unavailable() -> ReviewUnavailableError:
    return ReviewUnavailableError("no verdict", cause="invalid_verdict")


# The reviews are called in order: z0, s1, the closing pass, then s1's follow-up (the fourth).
ENDINGS: dict[str, tuple[str, dict[str, Any]]] = {
    "gate": ("rejected", {"gate": ["pass", "fail"]}),
    "review": ("rejected", {"verdicts": ["pass", "pass", "pass", "fail"]}),
    "blocked": ("blocked", {"results": {4: blocked_review()}}),
    "no verdict": ("no_verdict", {"unavailable": {4: _unavailable()}}),
}


@pytest.mark.parametrize("how", list(ENDINGS))
def test_a_follow_up_not_merged_ends_once_and_the_integration_call_follows(
    tmp_path: Path, how: str
) -> None:
    why, setup = ENDINGS[how]
    rig = slice_rig(tmp_path)
    if "gate" in setup:
        rig.gate = PerAttempt(verdicts=setup["gate"])
    else:
        rig.reviewer = FakeReviewer(
            verdicts=setup.get("verdicts", []),
            results=setup.get("results", {}),
            unavailable=setup.get("unavailable", {}),
        )
    outcome = ended(rig, plan=CLOSING)
    events = events_of(rig)
    assert outcome == "done", outcome
    ends = at(events, "follow_up_ended", "s1", 2)
    assert [end["why"] for end in ends] == [why]
    assert not at(events, "stage_entered", "s1", 3), "the follow-up was retried"
    assert not at(events, "escalation_decided", "s1", 2) and not at(events, "escalated", "s1", 2)
    assert kinds(events).index("follow_up_ended") < kinds(events).index("integration_gate_ran")
    assert replay(events).subtasks["s1"].status == "done"
    assert refusal(events) is None


def test_a_follow_up_not_merged_leaves_the_run_escalated_at_integration(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path)
    rig.reviewer = FakeReviewer(verdicts=["pass", "pass", "pass", "fail"])
    assert rig.gate is not None
    rig.gate.integration_verdict = "fail"  # what the propagation check gives the unwritten edge
    outcome = ended(rig, plan=CLOSING)
    events = events_of(rig)
    assert outcome == "escalated", outcome
    assert "follow_up_ended" in kinds(events)
    assert kinds(events).index("follow_up_ended") < kinds(events).index("integration_escalated")


def test_a_follow_up_end_replay_cannot_place_is_refused(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path)
    rig.reviewer = FakeReviewer(verdicts=["pass", "pass", "pass", "fail"])
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    assert "follow_up_ended" in kinds(events), "no follow-up end was recorded"
    place = kinds(events).index("follow_up_ended")
    line = events[place]
    wrong = type(line).model_validate({**line.model_dump(), "why": "blocked"})
    assert refusal([*events[:place], wrong, *events[place + 1 :]]) is not None
    # And on an attempt that merged: the line is the follow-up's, only where it did not.
    merged = slice_rig(tmp_path / "merged")
    assert ended(merged, plan=CLOSING) == "done"
    kept = events_of(merged)
    after = kinds(kept).index("diff_checked", kinds(kept).index("subtask_reopened"))
    assert refusal([*kept[: after + 1], line, *kept[after + 1 :]]) is not None


# --- what is owed, and to whom -------------------------------------------------------------


@pytest.mark.parametrize("blocked_at", [1, 3])
def test_a_module_merged_on_its_fix_is_owed_no_follow_up(tmp_path: Path, blocked_at: int) -> None:
    # s1's review of attempt ``blocked_at`` blocks; a person orders the fix before the closing
    # pass starts, and it merges: no attempt is left after a fix, so none is owed (a stated limit).
    rig = slice_rig(tmp_path)
    s1 = [2 + k for k in range(blocked_at)]  # z0's review is the first call
    rig.reviewer = FakeReviewer(
        verdicts=["pass", *(["fail"] * (blocked_at - 1))], results={s1[-1]: blocked_review()}
    )
    killed = ended(
        rig,
        plan=CLOSING,
        kill=lambda e: e.kind == "stage_entered" and e.model_dump()["subtask_id"] == "zc",
    )
    assert killed == "killed"
    decide(rig.run_dir, "reject", "the pole is the one the linearisation gives")
    outcome = ended(rig, how=resume)
    events = events_of(rig)
    assert at(events, "merged", "s1", blocked_at + 1), "the fix did not merge"
    assert outcome == "done", outcome
    assert follow_ups(events) == []
    assert "integration_gate_ran" in kinds(events)


# --- kill points ---------------------------------------------------------------------------


def _taken_over(events: list[Event]) -> list[tuple[str, str | None, int | None]]:
    """The log as the uninterrupted run wrote it: no line a process taking over adds."""
    return [
        (e.kind, e.model_dump().get("subtask_id"), e.model_dump().get("attempt"))
        for e in events
        if not isinstance(e, EnvironmentRecorded | OsLayerChecked | Resumed)
    ]


def test_a_kill_between_two_follow_up_lines_writes_the_rest_on_resume(tmp_path: Path) -> None:
    whole = slice_rig(tmp_path / "whole", loop=True)
    assert ended(whole, plan=TWO_MODULES) == "done"
    rig = slice_rig(tmp_path / "killed", loop=True)
    written: list[Event] = []

    def second(line: Event) -> bool:
        if line.kind == "subtask_reopened" and follow_ups(written):
            return True
        written.append(line)
        return False

    assert ended(rig, plan=TWO_MODULES, kill=second) == "killed"
    outcome = ended(rig, how=resume)
    events = events_of(rig)
    assert outcome == "done", outcome
    assert [(f["subtask_id"], f["owed"]) for f in follow_ups(events)] == [
        ("s1", [{"source": BUS, "target": DRIVER}]),
        ("s2", [{"source": BUS, "target": LOOP}]),
    ]
    assert _taken_over(events) == _taken_over(events_of(whole))
    assert refusal(events) is None


# --- readers of the line -------------------------------------------------------------------


def test_the_decision_sequence_reads_a_follow_up_as_a_reopen_with_its_cause_and_edges(
    tmp_path: Path,
) -> None:
    rig = slice_rig(tmp_path)
    assert ended(rig, plan=CLOSING) == "done"
    lines = [e.model_dump(mode="json") for e in events_of(rig)]
    try:
        steps = decisions(lines)
    except KeyError as exc:
        pytest.fail(f"the decision sequence does not read a follow-up: {exc!r}")
    (step,) = [s for s in steps if s["step"] == "reopened"]
    assert step["cause"] == "follow_up"
    assert step["owed"] == [{"source": BUS, "target": DRIVER}]
    assert "item_id" not in step
