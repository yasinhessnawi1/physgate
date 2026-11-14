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
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (
    choose,
    mend,
    of,
    requests_of,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    DRIVE,
    FW,
    IFACE_BUDGET,
    IFACE_DRIVE,
    IFACE_TILT,
    INTEG,
    P_BUDGET,
    P_FW,
    comparable,
    entry,
    hooked,
    node,
    rig_for,
    side,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import NO_VERDICT, _layer, decide

from physgate import roles
from physgate.contracts.pairs import ContractPair
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


def rigged(
    tmp_path: Path, *, acts: bool = True, interfaces: Sequence[dict[str, Any]] = (IFACE_DRIVE,)
) -> Rig:
    rig = rig_for(
        tmp_path,
        interfaces=interfaces,
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


#: A chain: fw reads drive's ``iface.drive``, and budget reads fw's ``iface.tilt``.
P_TILT = ContractPair(
    producer=side(FW, "firmware"), consumer=side(BUDGET, "sizing"), interfaces=("iface.tilt",)
)
#: A second producer of fw: budget's ``iface.budget``.
P_SUPPLY = ContractPair(
    producer=side(BUDGET, "sizing"), consumer=side(FW, "firmware"), interfaces=("iface.budget",)
)
ROLE_OF = {DRIVE: ("control", "drive"), FW: ("firmware", "fw"), BUDGET: ("sizing", "budget")}


def planned(order: Sequence[str], pairs: Sequence[ContractPair]) -> Callable[[Loop], None]:
    """A plan of ``order`` then integration, whose recorded pairs are ``pairs``."""

    def begin_it(loop: Loop) -> None:
        plan = [entry(s, *ROLE_OF[s]) for s in order]
        plan.append(entry(INTEG, "integration", "integration"))
        interfaces = tuple(dict.fromkeys(i for p in pairs for i in p.interfaces))
        consumers = tuple(
            InterfaceConsumers(
                interface=i,
                consumers=tuple(p.consumer.module for p in pairs if i in p.interfaces),
            )
            for i in interfaces
        )
        requirement = (
            '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
        )
        head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
        summary = DecompositionSummary(
            session_id="decomposition",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(plan),
            interface_nodes=interfaces,
            spec_commit="e" * 40,
            head_revision=head,
            interface_consumers=consumers,
            system_requirements=(SystemRequirement.model_validate_json(requirement),),
            contract_pairs=tuple(pairs),
        )
        loop.record.start(plan, decomposed=summary)

    return begin_it


CHAIN = planned((DRIVE, FW, BUDGET), (P_FW, P_TILT))
TWO_PRODUCERS = planned((DRIVE, BUDGET, FW), (P_SUPPLY, P_FW))


def chained(tmp_path: Path) -> Rig:
    """Drive fails three reviews; fw reads drive, budget reads fw; every value agrees."""
    rig = rigged(tmp_path, interfaces=(IFACE_DRIVE, IFACE_TILT))
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {
            FW: [node("fw.main", "firmware", "iface.drive", "iface.tilt", v=12, period=10)],
            BUDGET: [node("budget.supply", "sizing", "iface.tilt", period=10)],
        }
    )
    return rig


def supplied(tmp_path: Path) -> Rig:
    """Drive fails three reviews and budget passes; fw reads both."""
    rig = rigged(tmp_path, interfaces=(IFACE_DRIVE, IFACE_BUDGET))
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {
            FW: [node("fw.main", "firmware", "iface.drive", "iface.budget", v=12)],
            BUDGET: [node("budget.supply", "sizing", "iface.budget", v=12)],
        }
    )
    return rig


def first_run(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget: bool,
    kill: Callable[[Any, list[Any]], bool] | None = None,
    mutual: bool = False,
    plan: Callable[[Loop], None] | None = None,
    declared: Sequence[str] | None = None,
) -> str:
    """The first process, until it stops: the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    said = declared or (WITH_BUDGET if budget else ALONE)
    hooked(monkeypatch, loop, declared=said, kill=kill)
    if plan is not None:
        plan(loop)
    elif mutual:
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
    declared: Sequence[str] | None = None,
) -> str:
    """A fresh process takes the run over; the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    said = declared or (WITH_BUDGET if budget else ALONE)
    hooked(monkeypatch, loop, declared=said, kill=kill)
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


def before_the_hold(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, *, budget: bool, mutual: bool = False
) -> str:
    """The first process as the loop ran before the hold existed: no hold, no mark on line one."""
    with monkeypatch.context() as before:
        before.setattr("physgate.orchestrator.replay.gated", lambda *_: None, raising=False)
        before.setattr("physgate.orchestrator.replay.held_subtask", lambda _: None, raising=False)
        before.setattr("physgate.orchestrator.record.PRODUCER_WAIT", None, raising=False)
        return first_run(rig, monkeypatch, budget=budget, mutual=mutual)


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
    rig = rigged(tmp_path)
    ended = before_the_hold(rig, monkeypatch, budget=True)
    raw = (rig.run_dir / "events.jsonl").read_bytes()
    rows = lines(rig)
    assert "producer_wait" not in rows[0]
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


# --- a run started under the hold says so once, and replays strictly ------------------------------


def test_a_run_that_acts_marks_its_first_line_once_and_a_run_that_records_only_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acting = rigged(tmp_path / "acts")
    first_run(acting, monkeypatch, budget=False)
    rows = lines(acting)
    assert rows[0]["kind"] == "run_started"
    assert rows[0].get("producer_wait") == "hold"
    assert [r for r in rows[1:] if "producer_wait" in r] == []
    recording = rigged(tmp_path / "records", acts=False)
    first_run(recording, monkeypatch, budget=False)
    assert "producer_wait" not in lines(recording)[0]


def _marked(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**rows[0], "producer_wait": "hold"}, *rows[1:]]


def test_a_marked_run_whose_reader_was_dispatched_with_no_hold_does_not_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same lines a loop before the hold wrote: fw dispatched while drive waited on a person.
    rig = rigged(tmp_path)
    before_the_hold(rig, monkeypatch, budget=True)
    rows = lines(rig)
    assert of(rows, "dispatch_held") == []
    assert refusal(rows) is None
    said = refusal(_marked(rows))
    assert said is not None
    assert "with no hold line" in said, said
    # Cut just before fw's dispatch, the marked record replays: only the dispatch is refused.
    assert refusal(_marked(rows[: dispatched_at(rows, FW)])) is None


def test_a_marked_run_whose_mutual_reader_was_dispatched_with_no_release_line_does_not_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig.reviewer.verdicts[:] = SPENT
    rig.config_overrides.update(ACTS)
    before_the_hold(rig, monkeypatch, budget=False, mutual=True)
    rows = lines(rig)
    assert of(rows, "dispatch_released") == []
    assert refusal(rows) is None
    said = refusal(_marked(rows))
    assert said is not None
    assert "with no release line" in said, said


# --- a chain: a reader of a held reader waits on the item at the root --------------------------


def _held_on(rows: Sequence[dict[str, Any]]) -> list[tuple[str, str, str, list[str]]]:
    return [
        (h["subtask_id"], h["producer"], h["item_id"], h["interfaces"])
        for h in of(rows, "dispatch_held")
    ]


def test_a_reader_of_a_held_reader_is_held_on_the_item_at_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path)
    assert first_run(rig, monkeypatch, budget=True, plan=CHAIN) == "wait"
    rows = lines(rig)
    item = drive_item(rows)
    assert requests_of(rig, FW) == requests_of(rig, BUDGET) == []
    assert _held_on(rows) == [
        (FW, DRIVE, item, ["iface.drive"]),
        (BUDGET, FW, item, ["iface.tilt"]),
    ]
    assert refusal(rows) is None
    step = replay(read_events(rig.run_dir / "events.jsonl")).next_step()
    assert step.kind == "wait"


def test_a_chain_is_released_link_by_link_once_its_root_is_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path)
    assert first_run(rig, monkeypatch, budget=True, plan=CHAIN) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    rows = lines(rig)
    released = of(rows, "dispatch_released")
    assert [(r["subtask_id"], r["producer"], r["outcome"]) for r in released] == [
        (FW, DRIVE, "merged"),
        (BUDGET, FW, "merged"),
    ]
    assert first_line(rows, "merged", subtask_id=DRIVE) < rows.index(released[0])
    assert rows.index(released[0]) < dispatched_at(rows, FW)
    assert first_line(rows, "merged", subtask_id=FW) < rows.index(released[1])
    assert rows.index(released[1]) < dispatched_at(rows, BUDGET)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, BUDGET, INTEG]
    assert refusal(rows) is None


def _chain_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    rig = chained(tmp_path / "reference")
    assert first_run(rig, monkeypatch, budget=True, plan=CHAIN) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    return rig


def test_a_chain_cut_at_its_second_hold_resumes_to_the_uninterrupted_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _chain_reference(tmp_path, monkeypatch)
    rig = chained(tmp_path / "cut")

    def second_hold(event: Any, written: list[Any]) -> bool:  # noqa: ANN401 - any line
        return bool(event.kind == "dispatch_held" and event.subtask_id == BUDGET)

    assert first_run(rig, monkeypatch, budget=True, plan=CHAIN, kill=second_hold) == "killed"
    assert [h[0] for h in _held_on(lines(rig))] == [FW]
    assert resumed(rig, monkeypatch, budget=True) == "wait"
    assert [h[0] for h in _held_on(lines(rig))] == [FW, BUDGET]
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    same_lines(rig, reference)
    assert refusal(lines(rig)) is None


def test_a_marked_chain_whose_second_reader_ran_with_no_hold_does_not_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path)
    assert first_run(rig, monkeypatch, budget=True, plan=CHAIN) == "wait"
    rows = lines(rig)
    seconds = [h for h in of(rows, "dispatch_held") if h["subtask_id"] == BUDGET]
    assert len(seconds) == 1, _held_on(rows)
    at = rows.index(seconds[0])
    resolve = {k: rows[-1][k] for k in ("ts", "run_id", "gate_mode")}
    dispatch = {**resolve, "kind": "stage_entered", "subtask_id": BUDGET, "attempt": 1}
    said = refusal([*rows[:at], {**dispatch, "stage": "resolve"}])
    assert said is not None
    assert "with no hold line" in said, said


# --- two producers, two items, a halt -------------------------------------------------------------


def test_a_reader_of_one_merged_and_one_waiting_producer_is_held_on_the_waiting_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = supplied(tmp_path)
    order = (DRIVE, BUDGET, FW)
    assert first_run(rig, monkeypatch, budget=True, plan=TWO_PRODUCERS, declared=order) == "wait"
    rows = lines(rig)
    item = drive_item(rows)
    assert of(rows, "merged", subtask_id=BUDGET) != []
    assert _held_on(rows) == [(FW, DRIVE, item, ["iface.drive"])]
    assert requests_of(rig, FW) == []
    decide(rig.run_dir, "approve", item_id=item)
    assert resumed(rig, monkeypatch, budget=True, declared=order) == "done"
    rows = lines(rig)
    assert [(r["producer"], r["outcome"]) for r in of(rows, "dispatch_released")] == [
        (DRIVE, "merged")
    ]
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert refusal(rows) is None


def test_a_reader_stays_held_until_both_of_its_producers_items_are_decided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # drive's first review gives no verdict: it goes to a person. A reject orders one attempt,
    # whose review gives none either: a second item. fw waits through both.
    rig = rigged(tmp_path)
    rig.reviewer.verdicts[:] = []
    rig.reviewer.unavailable.update({1: NO_VERDICT, 2: NO_VERDICT})  # type: ignore[attr-defined]
    assert first_run(rig, monkeypatch, budget=False) == "wait"
    first = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "take the gain from the table", item_id=first)
    assert resumed(rig, monkeypatch, budget=False) == "wait"
    rows = lines(rig)
    escalations = of(rows, "escalated", subtask_id=DRIVE)
    assert len(escalations) == 2
    assert requests_of(rig, FW) == []
    assert len(of(rows, "dispatch_held")) == 1
    assert of(rows, "dispatch_released") == []
    decide(rig.run_dir, "approve", item_id=str(escalations[1]["item_id"]))
    assert resumed(rig, monkeypatch, budget=False) == "done"
    rows = lines(rig)
    (released,) = of(rows, "dispatch_released")
    assert (released["outcome"], released["item_id"]) == ("merged", first)
    assert first_line(rows, "merged", subtask_id=DRIVE) < rows.index(released)
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert refusal(rows) is None


def test_a_producer_that_halts_holds_nothing_and_its_reader_is_never_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    rig.dispatcher.infra[1] = "disk_full"  # type: ignore[attr-defined]
    assert first_run(rig, monkeypatch, budget=False) == "halted"
    rows = lines(rig)
    assert requests_of(rig, FW) == []
    assert of(rows, "dispatch_held") == of(rows, "dispatch_released") == []
    assert refusal(rows) is None


# --- every dispatch: a reader's next attempt waits while a producer reopened after it waits ------

#: drive, fw and budget; fw and budget each read drive's ``iface.drive``.
REOPENED = planned((DRIVE, FW, BUDGET), (P_BUDGET, P_FW))
#: drive and fw's contract item: their pair is the run's second.
CONTRACT_ITEM = "run-1-contract-2"


def reopenable(tmp_path: Path) -> Rig:
    """A contract that fails, a reader that fails its first review, and a reopen that fails.

    drive merges off the interface's ``v`` and fw merges on it: their contract fails, and its item
    goes to a person. budget, which reads drive, fails its first review. Reopened, drive writes the
    interface's value but fails two reviews, its last attempts: it goes to a person.
    """
    rig = rigged(tmp_path)
    rig.diff.writes[DRIVE] = [node("drive.motor", "control", "iface.drive", v=11)]  # type: ignore[attr-defined]
    mend(rig, {DRIVE: node("drive.motor", "control", "iface.drive", v=12)})
    rig.reviewer.verdicts[:] = ["pass", "pass", "fail", "fail", "fail", "pass"]
    return rig


def _budget_again(event: Any, written: list[Any]) -> bool:  # noqa: ANN401 - any line
    return bool(
        event.kind == "stage_entered"
        and event.subtask_id == BUDGET
        and event.attempt == 2  # noqa: PLR2004 - budget's second attempt
        and event.stage == "resolve"
    )


def reopened(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kill: Callable[[Any, list[Any]], bool] | None = None,
) -> str:
    """Stopped where budget's second attempt starts, a person keeps fw's work: drive reopens.

    The choice is taken at that boundary, and drive runs before budget's next attempt.
    """
    assert first_run(rig, monkeypatch, budget=True, plan=REOPENED, kill=_budget_again) == "killed"
    choose(rig.run_dir, "consumer", item_id=CONTRACT_ITEM)
    return resumed(rig, monkeypatch, budget=True, kill=kill)


def second_dispatch(rows: Sequence[dict[str, Any]], subtask: str) -> int:
    return first_line(rows, "stage_entered", subtask_id=subtask, stage="resolve", attempt=2)


def test_a_readers_next_attempt_is_held_while_a_producer_reopened_after_it_waits_on_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopenable(tmp_path)
    step = reopened(rig, monkeypatch)
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken")
    assert taken.get("reopens") == DRIVE
    assert [r.attempt for r in requests_of(rig, DRIVE)] == [1, 2, 3]
    item = drive_item(rows)
    assert [r.attempt for r in requests_of(rig, BUDGET)] == [1]
    assert step == "wait"
    assert _held_on(rows) == [(BUDGET, DRIVE, item, ["iface.drive"])]
    (held,) = of(rows, "dispatch_held")
    assert first_line(rows, "escalated", subtask_id=DRIVE) < rows.index(held)
    assert refusal(rows) is None
    # Rebuilt from the log alone, the hold keeps budget back on an item a person can still act on.
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    step_now = state.next_step()
    assert (step_now.kind, step_now.subtask_id) == ("wait", BUDGET)
    assert state.undecided(item)


def test_the_reopened_producer_approved_merges_and_the_readers_next_attempt_runs_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopenable(tmp_path)
    assert reopened(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    rows = lines(rig)
    (released,) = of(rows, "dispatch_released")
    assert (released["subtask_id"], released["producer"], released["outcome"]) == (
        BUDGET,
        DRIVE,
        "merged",
    )
    merges = of(rows, "merged", subtask_id=DRIVE)
    assert len(merges) == 2  # noqa: PLR2004 - its first merge, then the reopened one
    assert rows.index(merges[1]) < rows.index(released) < second_dispatch(rows, BUDGET)
    assert [r.attempt for r in requests_of(rig, BUDGET)] == [1, 2]
    assert refusal(rows) is None


def _reopened_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    rig = reopenable(tmp_path / "reference")
    assert reopened(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    return rig


def test_a_kill_at_a_later_hold_resumes_to_the_lines_of_the_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _reopened_reference(tmp_path, monkeypatch)
    rig = reopenable(tmp_path / "cut")
    assert reopened(rig, monkeypatch, kill=_at("dispatch_held")) == "killed"
    assert of(lines(rig), "dispatch_held") == []
    assert of(lines(rig), "escalated", subtask_id=DRIVE) != []
    assert resumed(rig, monkeypatch, budget=True) == "wait"
    assert [h[0] for h in _held_on(lines(rig))] == [BUDGET]
    assert [r.attempt for r in requests_of(rig, BUDGET)] == [1]
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch, budget=True) == "done"
    same_lines(rig, reference)
    assert refusal(lines(rig)) is None


def test_replay_refuses_a_readers_next_attempt_under_its_hold_or_in_place_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopenable(tmp_path)
    assert reopened(rig, monkeypatch) == "wait"
    rows = lines(rig)
    (held,) = of(rows, "dispatch_held")
    at = rows.index(held)
    envelope = {k: rows[-1][k] for k in ("ts", "run_id", "gate_mode")}
    dispatch = {
        **envelope,
        "kind": "stage_entered",
        "subtask_id": BUDGET,
        "attempt": 2,
        "stage": "resolve",
    }
    said = refusal([*rows, dispatch])
    assert said is not None
    assert "is held while" in said, said
    # In place of the hold: refused in a run started under it, and as before in a log without it.
    said = refusal([*rows[:at], dispatch])
    assert said is not None
    assert "with no hold line" in said, said
    unmarked = {k: v for k, v in rows[0].items() if k != "producer_wait"}
    assert refusal([unmarked, *rows[1:at], dispatch]) is None
