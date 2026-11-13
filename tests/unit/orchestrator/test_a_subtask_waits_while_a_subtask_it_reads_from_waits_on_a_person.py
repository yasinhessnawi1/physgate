"""A subtask is not dispatched while a subtask it reads from waits, unmerged, on a person.

"Reads from" is the run's recorded contract pairs. In a run that acts on decisions, a pair's
consumer is held at its first dispatch while the pair's producer is escalated and its item
undecided; the hold is a line of its own. The run goes on with every subtask that does not read
from the producer, and waits on the queue when nothing else can run. Once the producer merged the
consumer runs on the merged work; once it ended without a merge the consumer runs without it, and
the release line says which. Two subtasks that read from each other are never held, and a line
says so. A kill anywhere around the wait resumes to the lines of the uninterrupted run, and a run
recorded before the hold existed, or one that records decisions only, runs and replays as before.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeDispatcher, KilledError, Rig
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of, requests_of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    DRIVE,
    FW,
    IFACE_DRIVE,
    INTEG,
    P_FW,
    comparable,
    entry,
    hooked,
    node,
    rig_for,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import _layer, decide

from physgate import roles
from physgate.orchestrator.events import read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import replay
from physgate.oslayer.probe import Present
from physgate.state.store import journal_records_after

ACTS = {
    "queue_decisions": "act",
    "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
}
#: drive's three attempts fail review: it has no attempt left and goes to a person.
SPENT = ["fail", "fail", "fail"]
WITH_BUDGET = (DRIVE, FW, BUDGET)
ALONE = (DRIVE, FW)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def begin(loop: Loop, *, budget: bool) -> None:
    """drive, then fw, which reads drive's ``iface.drive``; then budget, which reads nothing."""
    plan = [entry(DRIVE, "control", "drive"), entry(FW, "firmware", "fw")]
    plan += [entry(BUDGET, "sizing", "budget")] if budget else []
    plan.append(entry(INTEG, "integration", "integration"))
    requirement = '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
    head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
    summary = DecompositionSummary(
        session_id="decomposition",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.drive",),
        spec_commit="e" * 40,
        head_revision=head,
        interface_consumers=(InterfaceConsumers(interface="iface.drive", consumers=("fw",)),),
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=(P_FW,),
    )
    loop.record.start(plan, decomposed=summary)


def rigged(tmp_path: Path, *, acts: bool = True) -> Rig:
    rig = rig_for(
        tmp_path,
        interfaces=(IFACE_DRIVE,),
        dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"),
    )
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {
            DRIVE: [node("drive.motor", "control", "iface.drive", v=12)],
            FW: [node("fw.main", "firmware", "iface.drive", v=12)],
            BUDGET: [node("budget.supply", "sizing", "iface.drive", v=12)],
        }
    )
    rig.reviewer.verdicts[:] = SPENT
    if acts:
        rig.config_overrides.update(ACTS)
    return rig


def first_run(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget: bool,
    kill: Callable[[Any, list[Any]], bool] | None = None,
    mutual: bool = False,
) -> str:
    """The first process, until it stops: the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=WITH_BUDGET if budget else ALONE, kill=kill)
    if mutual:
        start(loop)
    else:
        begin(loop, budget=budget)
    if rig.config_overrides.get("queue_decisions") == "act":
        _layer(loop)
    try:
        return loop.run().kind
    except KilledError:
        return "killed"
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding, asserted as a step
        return f"raised {exc!r}"
    finally:
        loop.close()


def resumed(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget: bool,
    kill: Callable[[Any, list[Any]], bool] | None = None,
) -> str:
    """A fresh process takes the run over; the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=WITH_BUDGET if budget else ALONE, kill=kill)
    _layer(loop)
    try:
        return loop.resume().kind
    except KilledError:
        return "killed"
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding, asserted as a step
        return f"raised {exc!r}"
    finally:
        loop.close()


def drive_item(rows: Sequence[dict[str, Any]]) -> str:
    (line,) = of(rows, "escalated", subtask_id=DRIVE)
    return str(line["item_id"])


def first_line(rows: Sequence[dict[str, Any]], kind: str, **match: Any) -> int:  # noqa: ANN401
    return next(i for i, r in enumerate(rows) if r["kind"] == kind and _matches(r, match))


def _matches(row: dict[str, Any], match: dict[str, Any]) -> bool:
    return all(row.get(k) == v for k, v in match.items())


def dispatched_at(rows: Sequence[dict[str, Any]], subtask: str) -> int:
    return first_line(rows, "stage_entered", subtask_id=subtask, stage="resolve")


# --- held, while an independent subtask still runs -----------------------------------------------


def test_a_reader_is_held_while_its_producer_waits_and_an_independent_subtask_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    step = first_run(rig, monkeypatch, budget=True)
    rows = lines(rig)
    item = drive_item(rows)
    assert requests_of(rig, FW) == []
    assert [r.attempt for r in requests_of(rig, BUDGET)] == [1]
    assert step == "wait"
    (held,) = of(rows, "dispatch_held")
    assert (held["subtask_id"], held["producer"], held["item_id"], held["interfaces"]) == (
        FW,
        DRIVE,
        item,
        ["iface.drive"],
    )
    # The hold comes where fw's dispatch would have, and budget's after it.
    assert first_line(rows, "escalated", subtask_id=DRIVE) < rows.index(held)
    assert rows.index(held) < dispatched_at(rows, BUDGET)
    assert of(rows, "integration_gate_ran") == of(rows, "integration_gate_skipped") == []
    assert refusal(rows) is None


def test_a_replayed_run_shows_why_nothing_was_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    step = state.next_step()
    assert (step.kind, step.subtask_id) == ("wait", FW)
    rows = lines(rig)
    assert [r["kind"] for r in rows[-2:]] == ["escalated", "dispatch_held"]
    assert refusal(rows) is None


# --- the producer merged after a decision -------------------------------------------------------


def test_the_producer_merged_after_an_approve_and_the_reader_then_runs_on_its_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    merged_when_fw_spawned: list[list[str]] = []
    # drive's three calls, budget's, then fw's: at fw's spawn the run branch holds drive's merge.
    rig.dispatcher.during[5] = lambda: merged_when_fw_spawned.append(
        [m[0] for m in rig.merger.merges]
    )
    assert first_run(rig, monkeypatch, budget=True) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    rows = lines(rig)
    (released,) = of(rows, "dispatch_released")
    assert (released["subtask_id"], released["producer"], released["outcome"]) == (
        FW,
        DRIVE,
        "merged",
    )
    assert released["item_id"] == drive_item(rows)
    merge = first_line(rows, "merged", subtask_id=DRIVE)
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [BUDGET, FW, INTEG]
    assert merged_when_fw_spawned == [[BUDGET, DRIVE]]
    assert refusal(rows) is None


# --- the producer ended without a merge ----------------------------------------------------------


def test_the_producer_ended_unmerged_and_the_reader_runs_without_it_and_the_record_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    decide(rig.run_dir, "reject", "no attempt is left", item_id=drive_item(lines(rig)))
    resumed(rig, monkeypatch, budget=False)
    rows = lines(rig)
    assert of(rows, "subtask_rejected", subtask_id=DRIVE) != []
    (released,) = of(rows, "dispatch_released")
    assert (released["subtask_id"], released["producer"], released["outcome"]) == (
        FW,
        DRIVE,
        "ended_unmerged",
    )
    assert first_line(rows, "subtask_rejected", subtask_id=DRIVE) < rows.index(released)
    assert rows.index(released) < dispatched_at(rows, FW)
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert of(rows, "merged", subtask_id=DRIVE) == []
    assert refusal(rows) is None


# --- nothing else can run: the run waits, and resumes into the reader ---------------------------


def test_with_nothing_else_to_run_the_run_waits_and_resumes_into_the_reader_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    before = lines(rig)
    # Taken over with nothing decided: it waits again, and writes no second hold.
    assert resumed(rig, monkeypatch, budget=False) == "wait"
    again = lines(rig)
    assert len(of(again, "dispatch_held")) == 1
    assert [r["kind"] for r in again[len(before) :]] in ([], ["os_layer_checked"])
    assert requests_of(rig, FW) == []
    decide(rig.run_dir, "approve", item_id=drive_item(again))
    assert resumed(rig, monkeypatch, budget=False) == "done"
    rows = lines(rig)
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert [r["outcome"] for r in of(rows, "dispatch_released")] == ["merged"]
    assert of(rows, "integration_gate_ran") != []
    assert refusal(rows) is None


# --- mutual readers -------------------------------------------------------------------------------


def test_two_subtasks_that_read_from_each_other_are_dispatched_as_before_and_the_record_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pair rig's plan: drive reads fw's iface.tilt and fw reads drive's iface.drive.
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig.reviewer.verdicts[:] = SPENT
    rig.config_overrides.update(ACTS)
    first_run(rig, monkeypatch, budget=False, mutual=True)
    rows = lines(rig)
    item = drive_item(rows)
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert of(rows, "dispatch_held") == []
    said = of(rows, "dispatch_released")
    assert len(said) == 1, said
    released = said[0]
    assert (
        released["subtask_id"],
        released["producer"],
        released["item_id"],
        released["outcome"],
    ) == (FW, DRIVE, item, "mutual_readers")
    assert rows.index(released) < dispatched_at(rows, FW)
    assert refusal(rows) is None


# --- a kill around the wait -----------------------------------------------------------------------


def _at(kind: str) -> Callable[[Any, list[Any]], bool]:
    def pick(event: Any, written: list[Any]) -> bool:  # noqa: ANN401 - any line
        return bool(event.kind == kind)

    return pick


def same_lines(rig: Rig, reference: Rig) -> None:
    """The two runs wrote the same lines, but for the clock and what each run directory adds."""

    def text(of_rig: Rig) -> list[str]:
        out = []
        for line in comparable(read_events(of_rig.run_dir / "events.jsonl")):
            if line["kind"] == "os_layer_checked":
                continue  # each process taking over records the layer it runs under
            line.pop("decided_ts", None)
            if line["kind"] == "decisions_sealed":
                line.pop("sha256")  # the decisions file holds the run's own paths
            if isinstance(line.get("decision"), dict):
                line["decision"].pop("latency_ms", None)  # the escalation call's clock
            said = json.dumps(line, default=str).replace(str(of_rig.run_dir), "RUN")
            out.append(re.sub(r'"shown_sha256": "[0-9a-f]{64}"', '"shown_sha256": "SHOWN"', said))
        return out

    assert text(rig) == text(reference)


def _reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    rig = rigged(tmp_path / "reference")
    assert first_run(rig, monkeypatch, budget=True) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    return rig


def test_a_kill_at_the_hold_resumes_to_the_lines_of_the_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _reference(tmp_path, monkeypatch)
    rig = rigged(tmp_path / "cut")
    assert first_run(rig, monkeypatch, budget=True, kill=_at("dispatch_held")) == "killed"
    assert of(lines(rig), "dispatch_held") == []
    assert resumed(rig, monkeypatch, budget=True) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    same_lines(rig, reference)
    assert refusal(lines(rig)) is None


def test_a_kill_between_the_decision_and_the_release_resumes_to_the_uninterrupted_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _reference(tmp_path, monkeypatch)
    rig = rigged(tmp_path / "cut")
    assert first_run(rig, monkeypatch, budget=True) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True, kill=_at("dispatch_released")) == "killed"
    cut = lines(rig)
    assert of(cut, "merged", subtask_id=DRIVE) != []
    assert of(cut, "dispatch_released") == []
    # Replayed at the cut, the record owes the release before anything of fw.
    step = replay(read_events(rig.run_dir / "events.jsonl")).next_step()
    assert (step.kind, step.subtask_id) == ("release", FW)
    assert resumed(rig, monkeypatch, budget=True) == "done"
    same_lines(rig, reference)
    assert refusal(lines(rig)) is None


def test_a_decision_on_record_where_the_hold_would_go_is_taken_there_and_no_hold_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The hold stands where fw's dispatch would: a boundary, so a decision already written is taken
    # first, as at that dispatch, and drive merges before fw is ever held.
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False, kill=_at("dispatch_held")) == "killed"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=False) == "done"
    rows = lines(rig)
    assert of(rows, "dispatch_held") == of(rows, "dispatch_released") == []
    taken = first_line(rows, "decision_taken")
    assert taken < first_line(rows, "merged", subtask_id=DRIVE) < dispatched_at(rows, FW)
    assert refusal(rows) is None


# --- the record holds the hold ----------------------------------------------------------------


def test_replay_refuses_the_reader_dispatched_while_its_hold_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    rows = lines(rig)
    assert of(rows, "dispatch_held") != []
    envelope = {k: rows[-1][k] for k in ("seq", "ts", "run_id", "gate_mode")}
    resolve = {**envelope, "kind": "stage_entered", "subtask_id": FW, "attempt": 1}
    said = refusal([*rows, {**resolve, "stage": "resolve"}])
    assert said is not None
    assert "is held while" in said


def test_replay_refuses_a_hold_or_a_release_the_record_does_not_owe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    rows = lines(rig)
    (held,) = of(rows, "dispatch_held")
    at = rows.index(held)
    released = {k: v for k, v in held.items() if k != "interfaces"}
    for forged, why in (
        ({**held, "producer": BUDGET}, "another producer"),
        ({**held, "interfaces": ["iface.other"]}, "another producer"),
        ({**released, "kind": "dispatch_released", "outcome": "merged"}, "is owed"),
        ({**released, "kind": "dispatch_released", "outcome": "mutual_readers"}, "is owed"),
    ):
        said = refusal([*rows[:at], forged])
        assert said is not None, forged
        assert why in said, (forged, said)
    # A second hold of the same producer, once one is open, is owed by nothing.
    said = refusal([*rows, held])
    assert said is not None
    assert "is owed" in said


# --- a run before the hold, and a run that records only ---------------------------------------


def test_a_run_that_records_only_dispatches_the_reader_as_before_with_no_hold_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path, acts=False)
    first_run(rig, monkeypatch, budget=True)
    rows = lines(rig)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, BUDGET]
    assert of(rows, "dispatch_held") == of(rows, "dispatch_released") == []
    assert refusal(rows) is None


def test_a_log_recorded_before_the_hold_replays_as_before_and_keeps_its_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Written as the loop wrote it before the hold existed: fw dispatched while drive waited.
    rig = rigged(tmp_path)
    with monkeypatch.context() as before:
        before.setattr("physgate.orchestrator.replay.gated", lambda *_: None, raising=False)
        before.setattr("physgate.orchestrator.replay.held_subtask", lambda _: None, raising=False)
        ended = first_run(rig, monkeypatch, budget=True)
    raw = (rig.run_dir / "events.jsonl").read_bytes()
    rows = lines(rig)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, BUDGET]
    assert of(rows, "dispatch_held") == of(rows, "dispatch_released") == []
    events = read_events(rig.run_dir / "events.jsonl")
    assert b"".join(e.model_dump_json().encode() + b"\n" for e in events) == raw
    state = replay(events)
    assert refusal(rows) is None
    # Its run ends where it ended: nothing the hold adds is owed by a record that has none.
    assert state.next_step().kind == ended
    assert resumed(rig, monkeypatch, budget=True) == ended
    after = lines(rig)
    assert of(after, "dispatch_held") == of(after, "dispatch_released") == []
    assert json.dumps(after[: len(rows)]) == json.dumps(rows)
