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
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as pairs
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from arbitration_runs import CLOSING, PerAttempt, events_of, refusal, resume
from loop_fakes import FakeReviewer, KilledError, Rig
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
from physgate.orchestrator.escalation import TO_THE_QUEUE, bind
from physgate.orchestrator.escalation_state import escalation_state
from physgate.orchestrator.events import (
    EnvironmentRecorded,
    EscalationDecided,
    Event,
    OsLayerChecked,
    Resumed,
)
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
    # And on an attempt still being judged: the line is the follow-up's, only once it ended.
    merged = slice_rig(tmp_path / "merged")
    assert ended(merged, plan=CLOSING) == "done"
    kept = events_of(merged)
    after = kinds(kept).index("session_ended", kinds(kept).index("subtask_reopened"))
    # With the reason an attempt still in progress would give, so only the placement refuses it.
    early = type(line).model_validate({**line.model_dump(), "why": "for_a_person"})
    assert "a follow-up's end" in (refusal([*kept[: after + 1], early, *kept[after + 1 :]]) or "")
    # Nor is its end asked about: an escalation decision there is refused, built as the loop
    # builds one for any other attempt that did not merge.
    before = events[:place]
    state = escalation_state(replay(before), "s1")
    envelope = {k: getattr(line, k) for k in ("seq", "ts", "run_id", "gate_mode")}
    asked = EscalationDecided(
        **envelope,
        subtask_id="s1",
        attempt=2,
        decision=bind("rules").decide(TO_THE_QUEUE, state),
        state=state,
    )
    assert "an escalation decision" in (refusal([*before, asked]) or "")


def test_a_follow_up_rewritten_before_any_of_its_attempts_halts_before_one_begins(
    tmp_path: Path,
) -> None:
    # Killed right after the follow-up line, its edges rewritten: the resumed process halts at
    # once, and the follow-up's session never runs.
    rig = slice_rig(tmp_path)
    killed = ended(
        rig,
        plan=CLOSING,
        kill=lambda e: (
            e.kind == "stage_entered" and follow_ups([e]) == [] and e.model_dump()["attempt"] == 2
        ),
    )
    assert killed == "killed"
    path = rig.run_dir / "events.jsonl"
    raw = path.read_text().splitlines()
    (place,) = [i for i, ln in enumerate(raw) if '"follow_up"' in ln]
    data = json.loads(raw[place])
    data["owed"] = [{"source": BUS, "target": "electrical.other"}]
    raw[place] = json.dumps(data, separators=(",", ":"))
    path.write_text("\n".join(raw) + "\n")
    assert ended(rig, how=resume) == "halted"
    events = events_of(rig)
    assert not at(events, "stage_entered", "s1", 2), "the follow-up began on a rewritten record"
    assert [e.model_dump()["cause"] for e in events if e.kind == "incident"] == [
        "foreign_journal_line"
    ]


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


def _decided(events: list[Event]) -> list[Any]:
    """What the run decided about its follow-ups, and where each subtask ended.

    A resumed attempt enters its stages again, and judges again, where it restarts (the resume
    path of every attempt); what it owed, merged and ended is the same.
    """
    kept = ("subtask_reopened", "follow_up_ended", "merged", "integration_gate_ran")
    steps = [
        {k: v for k, v in d.items() if k not in ("seq", "ts", "merge_commit", "attempt_commit")}
        for e in events
        if e.kind in kept and (d := e.model_dump(mode="json"))
    ]
    state = replay(events)
    return [*steps, {s: state.subtasks[s].status for s in state.order}]


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


def test_a_follow_up_of_a_module_with_no_attempt_left_is_refused(tmp_path: Path) -> None:
    # s1 merged on the fix a person ordered after its first review blocked: a follow-up line
    # written for it anyway, before the integration call, is not one the record can owe.
    owed_run = slice_rig(tmp_path / "owed")
    assert ended(owed_run, plan=CLOSING) == "done"
    (line,) = [e for e in events_of(owed_run) if e.kind == "subtask_reopened"]
    rig = slice_rig(tmp_path / "fixed")
    rig.reviewer = FakeReviewer(verdicts=["pass"], results={2: blocked_review()})
    starts_zc = lambda e: e.kind == "stage_entered" and e.model_dump()["subtask_id"] == "zc"  # noqa: E731
    assert ended(rig, plan=CLOSING, kill=starts_zc) == "killed"
    decide(rig.run_dir, "reject", "the pole is the one the linearisation gives")
    assert ended(rig, how=resume) == "done"
    events = events_of(rig)
    merged = at(events, "merged", "s1", 2)
    assert merged, "the fix did not merge"
    forged = type(line).model_validate(
        {**line.model_dump(), "merge_commit": merged[-1]["merge_commit"], "attempt": 3}
    )
    call = kinds(events).index("integration_gate_ran")
    assert "no attempt left" in (refusal([*events[:call], forged]) or "")


# --- an order no read shows whole ----------------------------------------------------------


def test_a_follow_up_whose_order_no_read_shows_whole_is_owed_none(tmp_path: Path) -> None:
    # The closing pass writes the bus with so many values that the order would not fit one read
    # of its reviewer: no follow-up is written, and the propagation check judges the edge as is.
    rig = slice_rig(tmp_path)
    bus = node(BUS, "sizing", constrains=[DRIVER], amps=3.0)
    one = bus["quantities"]["peak_current"]
    bus["quantities"] |= {f"rail_current_{k}": one for k in range(700)}
    rig.diff.writes["zc"] = [bus]  # type: ignore[attr-defined]
    assert ended(rig, plan=CLOSING) == "done"
    events = events_of(rig)
    assert follow_ups(events) == []
    assert "integration_gate_ran" in kinds(events)


# --- every kill resumes to the uninterrupted run ---------------------------------------------


def test_a_kill_at_any_line_from_the_closing_pass_s_merge_resumes_to_the_same_log(
    tmp_path: Path,
) -> None:
    # Before the first follow-up line, between the two, mid follow-up session, between a merge
    # and the next follow-up, and before the integration call: each resumes to the same
    # decisions and the same ends (the lines exactly where no attempt restarts: the row above).
    whole = slice_rig(tmp_path / "whole", loop=True)
    assert ended(whole, plan=TWO_MODULES) == "done"
    lines = events_of(whole)
    first = kinds(lines).index("subtask_reopened") - 1
    differ = []
    for cut in range(first, kinds(lines).index("integration_gate_ran") + 1):
        if isinstance(lines[cut], EnvironmentRecorded | OsLayerChecked | Resumed):
            continue
        rig = slice_rig(tmp_path / f"cut{cut}", loop=True)
        key = _taken_over([lines[cut]])[0]
        nth = sum(1 for k in _taken_over(lines[:cut]) if k == key)
        seen: list[tuple[str, str | None, int | None]] = []

        def at_cut(line: Event, seen: list[Any] = seen, key: Any = key, nth: int = nth) -> bool:  # noqa: ANN401
            here = _taken_over([line])
            seen.extend(here)
            return bool(here) and here[0] == key and seen.count(key) == nth + 1

        assert ended(rig, plan=TWO_MODULES, kill=at_cut) == "killed", cut
        outcome = ended(rig, how=resume)
        if outcome != "done" or _decided(events_of(rig)) != _decided(lines):
            differ.append((cut, lines[cut].kind, outcome))
    assert differ == [], differ


# --- contracts and integration's record ----------------------------------------------------


def _pairs_rig(tmp_path: Path) -> Rig:
    """The pairs runner's slice, its budget constraining control's node: a follow-up is owed."""
    rig = pairs.rig_for(tmp_path, closing_volts=11)
    graph = rig.diff
    assert isinstance(graph, pairs.StoreGraph)
    supply = ("budget.supply", "sizing", "iface.drive", "drive.motor")
    graph.writes[pairs.BUDGET] = [pairs.node(*supply, v=12)]
    graph.writes[pairs.CLOSING] = [pairs.node(*supply, v=11)]
    return rig


def _pairs_run(rig: Rig, mp: pytest.MonkeyPatch, kill: Any = None, how: str = "run") -> str:  # noqa: ANN401
    loop = rig.open()
    pairs.hooked(mp, loop, declared=(pairs.BUDGET, pairs.DRIVE, pairs.FW), kill=kill)
    try:
        if how == "run":
            pairs.start(loop, sizing=True)
            return str(loop.run().kind)
        return str(loop.resume().kind)
    except KilledError:
        return "killed"
    finally:
        loop.close()


def test_a_follow_up_merge_retests_its_module_s_pairs_never_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _pairs_rig(tmp_path)
    assert _pairs_run(rig, monkeypatch) == "done"
    events = events_of(rig)
    assert [(f["subtask_id"], f["owed"]) for f in follow_ups(events)] == [
        (pairs.DRIVE, [{"source": "budget.supply", "target": "drive.motor"}])
    ]
    merged = max(i for i, e in enumerate(events) if e.kind == "diff_checked")
    after = [e for e in pairs.contracts(events) if e.seq > events[at_line(events, merged)].seq]
    assert {e.result.pair for e in after} == {pairs.P_BUDGET, pairs.P_FW, pairs.P_BACK}
    assert not any(e.first for e in after)


def at_line(events: list[Event], index: int) -> int:
    """The follow-up's own diff line: the last diff of the drive module."""
    return max(
        i
        for i, e in enumerate(events[: index + 1])
        if e.kind == "diff_checked" and e.model_dump()["subtask_id"] == pairs.DRIVE
    )


def test_a_follow_up_rewritten_before_integration_s_session_halts_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Killed after the integration call, before integration's own session: the follow-up's
    # edges rewritten on disk. Only the record's holds before the session can find it.
    rig = _pairs_rig(tmp_path)
    integ = pairs.INTEG
    starts = lambda e, _: e.kind == "stage_entered" and e.subtask_id == integ  # noqa: E731
    assert _pairs_run(rig, monkeypatch, kill=starts) == "killed"
    path = rig.run_dir / "events.jsonl"
    raw = path.read_text().splitlines()
    (place,) = [i for i, ln in enumerate(raw) if '"follow_up"' in ln]
    data = json.loads(raw[place])
    data["owed"] = [{"source": "budget.supply", "target": "drive.other"}]
    raw[place] = json.dumps(data, separators=(",", ":"))
    path.write_text("\n".join(raw) + "\n")
    outcome = _pairs_run(rig, monkeypatch, how="resume")
    events = events_of(rig)
    assert outcome == "halted", outcome
    assert [e.model_dump()["cause"] for e in events if e.kind == "incident"] == [
        "foreign_journal_line"
    ]
    assert "integration_state_issued" not in kinds(events)
