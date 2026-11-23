"""A hold that stands after its producer left a person must not end the run in a wait on nothing.

The real run's shape (sizing, control, firmware; control reads sizing and firmware; firmware reads
sizing and builds what control designs), with the sizing-to-control contract failing and firmware's
first review giving no verdict. Firmware is with a person; a person chooses on the contract item,
which reopens control; control is held on firmware. A person then rejects firmware's item, which
orders a retry: firmware is no longer with a person, its next dispatch is held as a builder on
control, its designer, and control's hold on it stood. Nothing could be dispatched and no item was
open: the run ended in a wait with nothing to decide.

Under ``release_2`` an open hold is let go when its producer waits for the reader (directly or
through builder links and open holds) or can never run, and only then; a producer running its
retry or about to keeps its readers. The rows below take each state a person's decision leaves a
producer in, and say what its readers' holds do and how the run ends. The backstop rows say that a
run that reaches a wait with no item open halts on an incident naming what is held on what, under
the new mark alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeReviewer, Rig, plan
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_choice_on_a_failed_contract_reopens_the_other_module import choose, of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import (
    NO_VERDICT,
    _decide_quietly,
    _layer,
    _rig,
    decide,
)
from test_a_reader_is_let_go_by_a_producer_that_waits_for_it import (
    REAL,
    decided_run,
    merged_order,
    sequence,
)
from wait_cycle_rig import (
    CLOSING,
    CONTROL,
    ELECTRICAL,
    FIRMWARE,
    SIZING,
    Shape,
    first_run,
    resumed,
    resumed_before,
)

from physgate import roles
from physgate.orchestrator import record, wait_cycle
from physgate.orchestrator.events import read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.replay import replay
from physgate.orchestrator.wait_cycle import items_open, never_ran

pytestmark = pytest.mark.usefixtures("before_the_sign_off_rule")

#: Firmware builds control's design and electrical reads firmware, so electrical's hold on
#: firmware is one nothing but a person or the rule can end.
HELD_FOR_GOOD = Shape(
    order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL),
    reads=((SIZING, CONTROL), (FIRMWARE, ELECTRICAL)),
    design=((CONTROL, FIRMWARE),),
)
#: Firmware reads control, which the sizing-to-control contract can reopen after it merged.
READ_BY_FIRMWARE = Shape(
    order=(SIZING, CONTROL, FIRMWARE), reads=((SIZING, CONTROL), (CONTROL, FIRMWARE))
)
WITH_NO_ITEM = ("producer_waits_for_reader", "producer_held_for_good")


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def open_ids(rig: Rig) -> list[str]:
    return [one.item_id for one in read_queue(rig.run_dir).open_items()]


def bent(rig: Rig, subtask: str) -> None:
    """``subtask``'s node is written one value off, so the contract pairs it is in fail."""
    for made in rig.diff.writes[subtask]:  # type: ignore[attr-defined]
        for quantity in made["quantities"].values():
            quantity["value"] = 13


def state_of(rig: Rig) -> Any:  # noqa: ANN401 - the replayed state
    return replay(read_events(rig.run_dir / "events.jsonl"))


def reopens(rig: Rig) -> tuple[str, str]:
    """The failed contract's item and the position whose choice reopens a module."""
    (contract,) = [i for i in read_queue(rig.run_dir).open_items() if i.source == "contract"]
    assert contract.consequence is not None
    position = next(p for p, v in (contract.consequence.on_choose or {}).items() if v == "reopen")
    return contract.item_id, position


def reopen_then(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mark: str,
    verb: str,
    source: str,
) -> tuple[Rig, str, list[dict[str, Any]]]:
    """The real shape; control reopened by a person's choice; ``verb`` on firmware's item."""
    monkeypatch.setattr(record, "WAIT_CYCLE", mark)
    rig = REAL.rig(tmp_path, verdicts=("pass",) * 40)
    if source == "unavailable":
        rig.reviewer.unavailable[3] = NO_VERDICT  # firmware's first review gives no verdict
    else:
        rig.reviewer.results[3] = blocked_review()
    bent(rig, CONTROL)  # the sizing-to-control contract fails
    assert first_run(rig, monkeypatch, REAL) == "wait"
    item_id, position = reopens(rig)
    choose(rig.run_dir, position, item_id=item_id)
    assert resumed(rig, monkeypatch, REAL) == "wait"
    # Control is reopened and held on firmware, which is with a person.
    assert sequence(lines(rig)) == [("dispatch_held", CONTROL, FIRMWARE, "")]
    (item,) = [i for i in read_queue(rig.run_dir).open_items() if i.subtask_id == FIRMWARE]
    note = {"reject": "fix it", "approve": "it is fine" if source == "blocked" else None}[verb]
    decide(rig.run_dir, verb, note, item_id=item.item_id)
    step = resumed(rig, monkeypatch, REAL)
    return rig, step, lines(rig)


# --- H1: the producer left a person for a retry or a fix and waits for its reader ----------------


@pytest.mark.parametrize("mark", ["release", "release_2"])
@pytest.mark.parametrize("source", ["unavailable", "blocked"])
def test_a_reject_ordering_a_retry_or_a_fix_after_a_reopen_does_not_wait_on_nothing(
    mark: str, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, step, rows = reopen_then(tmp_path, monkeypatch, mark=mark, verb="reject", source=source)
    assert (step, open_ids(rig)) != ("wait", []), sequence(rows)
    assert refusal(rows) is None
    # Control's hold on firmware is let go: firmware, with its retry or fix ordered, waits for
    # control as its builder, and control for firmware. Control runs again and merges, and firmware
    # builds on it.
    assert sequence(rows) == [
        ("dispatch_held", CONTROL, FIRMWARE, ""),
        ("dispatch_released", CONTROL, FIRMWARE, "producer_waits_for_reader"),
    ]
    (hold,) = of(rows, "dispatch_held")
    assert of(rows, "dispatch_released")[0]["item_id"] == hold["item_id"]
    assert merged_order(rows) == [SIZING, CONTROL, CONTROL, FIRMWARE]
    assert of(rows, "incident") == []
    # Control's rerun leaves the contract failing again, an item a person decides: not a wait on
    # nothing.
    assert step == "wait"
    assert open_ids(rig)


def test_an_approve_after_a_reopen_lets_control_go_on_firmware_s_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, step, rows = reopen_then(
        tmp_path, monkeypatch, mark="release_2", verb="approve", source="unavailable"
    )
    assert sequence(rows) == [
        ("dispatch_held", CONTROL, FIRMWARE, ""),
        ("dispatch_released", CONTROL, FIRMWARE, "merged"),
    ]
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CONTROL]
    assert refusal(rows) is None
    assert step == "wait"
    assert open_ids(rig)


# --- the states a person's decision leaves a producer in ----------------------------------------


def test_a_reject_that_ends_the_producer_lets_its_readers_go_ended_unmerged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, step, rows = decided_run(tmp_path, monkeypatch, REAL, verb="reject")
    assert step == "done"
    assert [r[3] for r in sequence(rows)[2:]] == ["ended_unmerged", "ended_unmerged"]
    assert of(rows, "subtask_rejected", subtask_id=SIZING)
    assert refusal(rows) is None


@pytest.mark.parametrize("source", ["unavailable", "blocked"])
def test_a_retry_or_a_fix_that_runs_keeps_the_readers_until_it_merges(
    source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The producer running its retry is about to merge new values: its readers wait for them."""
    rig = REAL.rig(tmp_path, verdicts=("pass",) * 40)
    if source == "unavailable":
        rig.reviewer.unavailable[1] = NO_VERDICT
    else:
        rig.reviewer.results[1] = blocked_review()
    assert first_run(rig, monkeypatch, REAL) == "wait"
    decide(rig.run_dir, "reject", "again")
    assert resumed(rig, monkeypatch, REAL) == "done"
    rows = lines(rig)
    assert [r[0] for r in sequence(rows)] == ["dispatch_held"] * 2 + ["dispatch_released"] * 2
    assert {r[3] for r in sequence(rows)[2:]} == {"merged"}
    assert not [r for r in of(rows, "dispatch_released") if r["outcome"] in WITH_NO_ITEM]
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CLOSING, "integ"]
    # Control and firmware were let go only once sizing's retry or fix had merged.
    merged = rows.index(of(rows, "merged", subtask_id=SIZING)[0])
    assert merged < rows.index(of(rows, "dispatch_released")[0])
    assert refusal(rows) is None


def test_an_approve_merges_the_producer_and_its_readers_are_released_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, step, rows = decided_run(tmp_path, monkeypatch, REAL, verb="approve")
    assert step == "done"
    assert [r[3] for r in sequence(rows)[2:]] == ["merged", "merged"]
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CLOSING, "integ"]


def test_a_reopen_after_the_merge_keeps_a_reader_held_until_the_reopened_module_merges_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A choice that reopens control between its merge and firmware's release line."""
    shape = READ_BY_FIRMWARE
    rig = shape.rig(tmp_path, verdicts=("pass", "fail", "fail", "fail", *("pass",) * 30))
    bent(rig, CONTROL)
    assert first_run(rig, monkeypatch, shape) == "wait"
    (item,) = [i for i in read_queue(rig.run_dir).open_items() if i.subtask_id == CONTROL]
    decide(rig.run_dir, "approve", item_id=item.item_id)
    resumed_before(rig, monkeypatch, shape, lambda event: event.kind == "dispatch_released")
    item_id, position = reopens(rig)
    choose(rig.run_dir, position, item_id=item_id)
    assert resumed(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    # Firmware's hold on control stands through the reopen; control, running again, is about to
    # merge new values, so no cycle outcome is written; firmware is released on that merge.
    assert sequence(rows) == [
        ("dispatch_held", FIRMWARE, CONTROL, ""),
        ("dispatch_released", FIRMWARE, CONTROL, "merged"),
    ]
    assert merged_order(rows) == [SIZING, CONTROL, CONTROL, FIRMWARE]
    assert refusal(rows) is None


def test_a_producer_held_for_good_lets_its_reader_go_and_the_run_ends_unrun_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Firmware's retry is held on control, which is then rejected: electrical is let go."""
    shape = HELD_FOR_GOOD
    verdicts = ("pass", "pass", "pass", "fail", "fail", "fail", *("pass",) * 30)
    rig = shape.rig(tmp_path, verdicts=verdicts)
    rig.reviewer.unavailable[3] = NO_VERDICT
    bent(rig, CONTROL)
    assert first_run(rig, monkeypatch, shape) == "wait"
    item_id, position = reopens(rig)
    choose(rig.run_dir, position, item_id=item_id)
    assert resumed(rig, monkeypatch, shape) == "wait"
    (item,) = [i for i in read_queue(rig.run_dir).open_items() if i.subtask_id == FIRMWARE]
    decide(rig.run_dir, "reject", "again", item_id=item.item_id)
    assert resumed(rig, monkeypatch, shape) == "wait"
    # Firmware waits on control, with a person again: electrical's hold stands, a true wait.
    assert sequence(lines(rig)) == [
        ("dispatch_held", ELECTRICAL, FIRMWARE, ""),
        ("builder_held", FIRMWARE, CONTROL, "escalated"),
    ]
    (item,) = [i for i in read_queue(rig.run_dir).open_items() if i.subtask_id == CONTROL]
    decide(rig.run_dir, "reject", "no attempt is left", item_id=item.item_id)
    assert resumed(rig, monkeypatch, shape) == "unrun"
    rows = lines(rig)
    assert sequence(rows)[2:] == [
        ("builder_held", FIRMWARE, CONTROL, "ended_unmerged"),
        ("dispatch_released", ELECTRICAL, FIRMWARE, "producer_held_for_good"),
    ]
    assert refusal(rows) is None
    named = never_ran(state_of(rig))
    assert [n["subtask_id"] for n in named] == [FIRMWARE]
    assert named[0]["why"] == (
        f"its ordered retry never ran: its designer {CONTROL} ended without a merge"
    )
    assert named[0]["ran_without"] == [ELECTRICAL]
    assert of(rows, "incident") == []


# --- the backstop: a wait with no item open halts, whatever the rules do -------------------------


def broken_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule that lets an open hold go does nothing: the deadlock of H1 forms again."""
    monkeypatch.setattr(wait_cycle, "letting_go", lambda *_a: None)


def test_a_run_that_waits_with_no_item_open_halts_on_an_incident_naming_what_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_rule(monkeypatch)
    rig, step, rows = reopen_then(
        tmp_path, monkeypatch, mark="release_2", verb="reject", source="unavailable"
    )
    assert step == "halted"
    (incident,) = of(rows, "incident")
    assert incident["cause"] == "waits_on_nothing"
    assert incident["subtask_id"] is None
    assert f"{CONTROL} is held on {FIRMWARE}" in incident["detail"]
    assert f"{FIRMWARE} is held on {CONTROL}" in incident["detail"]
    assert "final" in incident["detail"]
    halt = of(rows, "halted")[-1]
    assert (halt["reason"], halt["detail"]) == ("incident", "waits_on_nothing")
    assert rows.index(halt) == rows.index(incident) + 1
    assert refusal(rows) is None
    assert state_of(rig).next_step().kind == "halted"


def test_a_resume_after_the_backstop_is_refused_and_writes_nothing_that_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_rule(monkeypatch)
    rig, step, rows = reopen_then(
        tmp_path, monkeypatch, mark="release_2", verb="reject", source="unavailable"
    )
    assert step == "halted"
    for _ in range(2):
        with pytest.raises(Exception, match="halted for incident"):
            resumed(rig, monkeypatch, REAL)
    after = lines(rig)
    assert [r["kind"] for r in after[len(rows) :]] == ["os_layer_checked"] * 2
    assert len(of(after, "incident")) == 1


def test_the_backstop_is_only_for_a_run_started_under_release_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ``release`` the run ends in the wait it always ended in: no incident, no halt."""
    broken_rule(monkeypatch)
    rig, step, rows = reopen_then(
        tmp_path, monkeypatch, mark="release", verb="reject", source="unavailable"
    )
    assert (step, open_ids(rig)) == ("wait", [])
    assert of(rows, "incident") == [] and of(rows, "halted") == []


def test_a_wait_with_an_item_open_is_no_backstop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_rule(monkeypatch)
    rig = REAL.rig(tmp_path)
    assert first_run(rig, monkeypatch, REAL) == "wait"
    assert open_ids(rig)
    assert of(lines(rig), "incident") == []


def test_a_decision_held_for_an_operator_s_confirmation_counts_as_an_item_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decided in the window of a session without the OS layer, the item stays open to confirm."""
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    rig.dispatcher.during[2] = lambda: _decide_quietly(run_dir, "run-1-s1")
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    _layer(loop, present=False)
    step = loop.run().kind
    loop.close()
    state = replay(read_events(run_dir / "events.jsonl"))
    held = state.taken["run-1-s1"]
    assert (held.acts, held.why_not) == (False, "held_os_layer_off")
    assert items_open(state) == ["run-1-s1"]
    assert step != "halted"
    assert not [e for e in read_events(run_dir / "events.jsonl") if e.kind == "incident"]
