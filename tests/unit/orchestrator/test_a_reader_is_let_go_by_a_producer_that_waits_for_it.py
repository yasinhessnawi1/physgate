"""A reader held on a producer is let go when the producer can never end before the reader runs.

The shape of a real run: sizing goes to a person; control reads sizing's interface and firmware's;
firmware reads sizing's, builds the design control writes, and so is held until control merged;
sizing's closing pass waits for both. Control was held on firmware, which waits on sizing's item;
once a person approved sizing, firmware was held on control, its designer, and control stayed held
on firmware: nothing could be dispatched and no item was open, and the run ended in a wait. Under
the ``wait_cycle`` mark the hold on a producer that waits, through a chain of builder and reader
holds, for the reader itself is let go (``producer_waits_for_reader``, and where none stood none is
written), and so is a hold on a builder held for good (``producer_held_for_good``). A true wait,
on a producer that waits for a person only, still holds, and a run recorded before the mark
replays as it did. Every row here starts its run under the mark ``release``.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import Rig
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of, requests_of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
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
    resumed_expecting,
    under_release,  # noqa: F401 - the fixture, by name
)

from physgate import roles
from physgate.orchestrator import record
from physgate.orchestrator.events import read_events
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.replay import replay

#: A row about the waits, not about the sign-off a merge owes: the run starts before that rule.
#: These rows are the rule as marked ``release``: the cycle releases, before they were narrowed
#: (the rule a run is started under now, ``release_2``, is in
#: ``test_a_reader_is_held_only_on_a_producer_that_is_with_a_person.py``).
pytestmark = pytest.mark.usefixtures("before_the_sign_off_rule", "under_release")

INTEG = "integ"
#: The real run: control reads firmware's interface (recorded first) and sizing's; firmware reads
#: sizing's and builds what control designs.
REAL = Shape(
    order=(SIZING, CONTROL, FIRMWARE),
    reads=((FIRMWARE, CONTROL), (SIZING, CONTROL), (SIZING, FIRMWARE)),
    design=((CONTROL, FIRMWARE),),
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def item_of(rows: Sequence[dict[str, Any]], subtask: str) -> str:
    (line,) = of(rows, "escalated", subtask_id=subtask)
    return str(line["item_id"])


def merged_order(rows: Sequence[dict[str, Any]]) -> list[str]:
    return [r["subtask_id"] for r in rows if r["kind"] == "merged"]


def open_ids(rig: Rig) -> list[str]:
    return [one.item_id for one in read_queue(rig.run_dir).open_items()]


def sequence(rows: Sequence[dict[str, Any]]) -> list[tuple[str, ...]]:
    """The wait lines as (kind, subtask, other, how) in the order written."""
    out: list[tuple[str, ...]] = []
    for r in rows:
        if r["kind"] in ("dispatch_held", "dispatch_released"):
            out.append((r["kind"], r["subtask_id"], r["producer"], r.get("outcome", "")))
        elif r["kind"] in ("builder_held", "builder_released"):
            out.append((r["kind"], r["subtask_id"], r["designer"], r.get("why", "")))
    return out


def at(rows: Sequence[dict[str, Any]], subtask: str) -> int:
    """Where the subtask's first session stage is."""
    return next(
        i
        for i, r in enumerate(rows)
        if r["kind"] == "stage_entered" and r["subtask_id"] == subtask and r["stage"] == "resolve"
    )


def decided_run(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
    shape: Shape,
    verb: str = "approve",
    verdicts: Sequence[str] = ("fail", "fail", "fail"),
) -> tuple[Rig, str, list[dict[str, Any]]]:
    """The run to its first stop, sizing's item decided by ``verb``, then resumed."""
    rig = shape.rig(tmp_path, verdicts)
    assert first_run(rig, monkeypatch, shape) == "wait"
    decide(rig.run_dir, verb, "no attempt is left" if verb == "reject" else None)
    step = resumed_expecting(
        rig,
        monkeypatch,
        shape,
        f"once sizing's item is decided ({verb}) the run stops at the step its mark gives it, and "
        "writes no incident for a wait with nothing to decide unless it began under release_2",
    )
    return rig, step, lines(rig)


# --- the real run's sequence ----------------------------------------------------------------------


def test_the_real_run_s_sequence_ends_with_every_module_merged_and_not_in_a_wait(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, step, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert (step, open_ids(rig)) != ("wait", []), sequence(rows)
    assert step == "done", step
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CLOSING, INTEG]
    # Control is let go from firmware, which waits for it as its designer, and no hold is written;
    # it and firmware are held on sizing's item, a true wait, and let go once it merged.
    assert sequence(rows) == [
        ("dispatch_released", CONTROL, FIRMWARE, "producer_waits_for_reader"),
        ("dispatch_held", CONTROL, SIZING, ""),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", CONTROL, SIZING, "merged"),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
    ]
    first = of(rows, "dispatch_released")[0]
    assert first["item_id"] == item_of(rows, SIZING)
    # Firmware runs after control merged: its designer, so no builder's hold is ever written.
    merges = [r["subtask_id"] for r in rows if r["kind"] == "merged"]
    assert merges.index(CONTROL) < rows.index(of(rows, "stage_entered", subtask_id=FIRMWARE)[0])
    assert at(rows, CONTROL) > rows.index(of(rows, "escalated", subtask_id=SIZING)[0])
    assert of(rows, "builder_held") == []
    assert requests_of(rig, CONTROL) != []
    assert refusal(rows) is None


def test_the_run_started_before_the_mark_ends_in_the_wait_it_always_ended_in(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old ending was the defect: pinned as a record that replays as it did, not as a rule."""
    monkeypatch.setattr(record, "WAIT_CYCLE", None)
    rig, step, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert "wait_cycle" not in rows[0]
    assert (step, open_ids(rig)) == ("wait", [])
    assert sequence(rows) == [
        ("dispatch_held", CONTROL, FIRMWARE, ""),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
        ("builder_held", FIRMWARE, CONTROL, "not_merged"),
    ]
    assert refusal(rows) is None
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    nxt = state.next_step()
    assert nxt.kind == "wait"
    assert merged_order(rows) == [SIZING]


def test_the_first_line_of_a_run_that_acts_carries_the_mark_and_one_that_only_records_does_not(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = REAL.rig(tmp_path)
    first_run(rig, monkeypatch, REAL)
    row = lines(rig)[0]
    assert (row["producer_wait"], row["closing_wait"], row["wait_cycle"]) == (
        "hold",
        "hold",
        "release",
    )


# --- no hold stood: the run as before ----------------------------------------------------------


def test_with_sizing_merging_without_an_item_nothing_is_held_and_the_order_is_the_plan_s(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = REAL.rig(tmp_path, verdicts=())
    assert first_run(rig, monkeypatch, REAL) == "done"
    rows = lines(rig)
    assert sequence(rows) == []
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CLOSING, INTEG]
    assert refusal(rows) is None


# --- the item is rejected: sizing ended without a merge -------------------------------------------


def test_with_sizing_ended_unmerged_the_readers_run_without_it_control_before_firmware(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, step, rows = decided_run(tmp_path, monkeypatch, REAL, "reject")
    assert (step, open_ids(rig)) != ("wait", [])
    assert sequence(rows) == [
        ("dispatch_released", CONTROL, FIRMWARE, "producer_waits_for_reader"),
        ("dispatch_held", CONTROL, SIZING, ""),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", CONTROL, SIZING, "ended_unmerged"),
        ("dispatch_released", FIRMWARE, SIZING, "ended_unmerged"),
    ]
    merged = merged_order(rows)
    assert SIZING not in merged
    assert merged.index(CONTROL) < merged.index(FIRMWARE)
    assert refusal(rows) is None


# --- a chain of three: a reader of a reader of a builder ----------------------------------------


#: control reads electrical, electrical reads firmware, firmware builds control's design and reads
#: sizing, which goes to a person.
CHAIN = (
    (ELECTRICAL, CONTROL),
    (FIRMWARE, ELECTRICAL),
    (SIZING, FIRMWARE),
)


def test_a_chain_of_three_runs_the_reader_first_and_the_rest_after_sizing_in_the_plan_order(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = Shape(
        order=(SIZING, CONTROL, ELECTRICAL, FIRMWARE), reads=CHAIN, design=((CONTROL, FIRMWARE),)
    )
    rig, step, rows = decided_run(tmp_path, monkeypatch, shape)
    assert step == "done", sequence(rows)
    assert merged_order(rows) == [CONTROL, SIZING, FIRMWARE, ELECTRICAL, CLOSING, INTEG]
    assert sequence(rows) == [
        ("dispatch_released", CONTROL, ELECTRICAL, "producer_waits_for_reader"),
        ("dispatch_held", ELECTRICAL, FIRMWARE, ""),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
        ("dispatch_released", ELECTRICAL, FIRMWARE, "merged"),
    ]
    assert refusal(rows) is None
    assert open_ids(rig) == []


def test_a_chain_of_three_planned_the_other_way_round_runs_its_middle_first(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = Shape(
        order=(SIZING, ELECTRICAL, CONTROL, FIRMWARE), reads=CHAIN, design=((CONTROL, FIRMWARE),)
    )
    rig, step, rows = decided_run(tmp_path, monkeypatch, shape)
    assert step == "done", sequence(rows)
    assert sequence(rows)[0] == (
        "dispatch_released",
        ELECTRICAL,
        FIRMWARE,
        "producer_waits_for_reader",
    )
    assert merged_order(rows) == [ELECTRICAL, CONTROL, SIZING, FIRMWARE, CLOSING, INTEG]
    assert sequence(rows) == [
        ("dispatch_released", ELECTRICAL, FIRMWARE, "producer_waits_for_reader"),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
    ]
    assert refusal(rows) is None
    assert open_ids(rig) == []


# --- a true wait still holds ----------------------------------------------------------------------


def test_a_reader_whose_producer_waits_on_a_person_only_stays_held_until_the_item_is_decided(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = Shape(order=(SIZING, CONTROL), reads=((SIZING, CONTROL),))
    rig = shape.rig(tmp_path)
    assert first_run(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    assert sequence(rows) == [("dispatch_held", CONTROL, SIZING, "")]
    assert requests_of(rig, CONTROL) == []
    assert open_ids(rig) == [item_of(rows, SIZING)]
    decide(rig.run_dir, "approve")
    assert resumed(rig, monkeypatch, shape) == "done"
    assert sequence(lines(rig)) == [
        ("dispatch_held", CONTROL, SIZING, ""),
        ("dispatch_released", CONTROL, SIZING, "merged"),
    ]


def test_two_readers_of_each_other_are_dispatched_as_before_under_the_mark(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = Shape(
        order=(SIZING, CONTROL, FIRMWARE),
        reads=((CONTROL, FIRMWARE), (FIRMWARE, CONTROL), (SIZING, FIRMWARE)),
    )
    rig = shape.rig(tmp_path)
    first_run(rig, monkeypatch, shape)
    rows = lines(rig)
    assert sequence(rows)[0] == ("dispatch_released", CONTROL, FIRMWARE, "mutual_readers")
    assert not [r for r in sequence(rows) if r[3] == "producer_waits_for_reader"]
    assert refusal(rows) is None


#: Control reads firmware's interface; firmware and electrical read each other's and sizing's;
#: electrical builds control's design. Control waits for firmware, which waits for sizing's item,
#: and electrical waits for control: but firmware's wait on electrical is a mutual read, no
#: link of a chain, so firmware does not wait for control and control's hold on it is a true wait.
MUTUAL_IN_THE_CHAIN = Shape(
    order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL),
    reads=(
        (SIZING, FIRMWARE),
        (SIZING, ELECTRICAL),
        (FIRMWARE, CONTROL),
        (FIRMWARE, ELECTRICAL),
        (ELECTRICAL, FIRMWARE),
    ),
    design=((CONTROL, ELECTRICAL),),
)


def test_a_reader_of_a_producer_that_is_in_a_mutual_read_with_its_own_builder_stays_held(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chain does not run through two readers of each other: the hold on firmware is true.

    Electrical builds control's design, so electrical waits for control; if firmware's read of
    electrical counted as a link, firmware would wait for control and control would be let go of
    firmware, which can still run first. It is not: control is held on firmware until sizing is
    decided, and runs after firmware.
    """
    rig, step, rows = decided_run(tmp_path, monkeypatch, MUTUAL_IN_THE_CHAIN)
    assert step == "done", sequence(rows)
    assert sequence(rows) == [
        ("dispatch_held", CONTROL, FIRMWARE, ""),
        ("dispatch_released", FIRMWARE, ELECTRICAL, "mutual_readers"),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", ELECTRICAL, FIRMWARE, "mutual_readers"),
        ("dispatch_held", ELECTRICAL, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
        ("dispatch_released", CONTROL, FIRMWARE, "merged"),
        ("dispatch_released", ELECTRICAL, SIZING, "merged"),
    ]
    assert not [r for r in sequence(rows) if r[3] == "producer_waits_for_reader"]
    assert merged_order(rows) == [SIZING, FIRMWARE, CONTROL, ELECTRICAL, CLOSING, INTEG]
    assert open_ids(rig) == []
    assert refusal(rows) is None


#: Control reads firmware's interface and sizing's, firmware reads sizing's; control designs
#: electrical's, which designs firmware's: firmware waits, through electrical, for control, so
#: control is let go of firmware whenever it is dispatched while the cycle stands.
TWO_BUILDERS_IN_A_CYCLE = Shape(
    order=(SIZING, CONTROL, ELECTRICAL, FIRMWARE),
    reads=((FIRMWARE, CONTROL), (SIZING, FIRMWARE)),
    design=((CONTROL, ELECTRICAL), (ELECTRICAL, FIRMWARE)),
)


def test_a_reader_let_go_is_let_go_again_on_each_dispatch_while_the_cycle_stands(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One release line for each dispatch of the reader, its second attempt included.

    Sizing goes to a person (three failed reviews). Control, let go of firmware, runs: its first
    review fails, its second passes. Firmware still waits for control through electrical when
    control is dispatched the second time, so the release is written again, before that attempt.
    """
    verdicts = ("fail", "fail", "fail", "fail", "pass")
    rig, step, rows = decided_run(tmp_path, monkeypatch, TWO_BUILDERS_IN_A_CYCLE, verdicts=verdicts)
    assert step == "done", sequence(rows)
    assert sequence(rows) == [
        ("dispatch_released", CONTROL, FIRMWARE, "producer_waits_for_reader"),
        ("dispatch_released", CONTROL, FIRMWARE, "producer_waits_for_reader"),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
    ]
    attempts = [
        i
        for i, r in enumerate(rows)
        if r["kind"] == "stage_entered" and r["subtask_id"] == CONTROL and r["stage"] == "resolve"
    ]
    assert len(attempts) == 2
    for i in attempts:
        assert rows[i - 1]["kind"] == "dispatch_released", f"no release before attempt at line {i}"
        assert (rows[i - 1]["subtask_id"], rows[i - 1]["producer"]) == (CONTROL, FIRMWARE)
    assert open_ids(rig) == []
    assert refusal(rows) is None


# --- a producer held for good ------------------------------------------------------------------


def test_a_reader_held_on_a_builder_held_for_good_is_let_go_and_runs_without_it(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader held on a builder that never ends is let go and runs without it.

    The old ending, a wait with no item, was the defect; it is the ending as after a producer that
    ended unmerged.
    """
    shape = Shape(
        order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL),
        reads=((SIZING, FIRMWARE), (FIRMWARE, ELECTRICAL)),
        design=((CONTROL, FIRMWARE),),
    )
    rig = shape.rig(tmp_path, verdicts=("fail",) * 6)
    assert first_run(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    decide(rig.run_dir, "reject", "no design", item_id=item_of(rows, CONTROL))
    decide(rig.run_dir, "approve", item_id=item_of(rows, SIZING))
    step = resumed(rig, monkeypatch, shape)
    rows = lines(rig)
    assert step == "done"
    assert sequence(rows) == [
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_held", ELECTRICAL, FIRMWARE, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
        ("builder_held", FIRMWARE, CONTROL, "ended_unmerged"),
        ("dispatch_released", ELECTRICAL, FIRMWARE, "producer_held_for_good"),
    ]
    assert merged_order(rows) == [SIZING, ELECTRICAL, CLOSING]
    assert refusal(rows) is None


def test_replay_takes_a_cycle_release_after_a_hold_and_lets_the_reader_be_dispatched(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hold, the release that lets it go, the dispatch: the record the loop would write next.

    The run is killed before it writes the release, and the release and the dispatch are added
    here by hand, so the row reads the record only: the loop is not asked to write either. A
    release takes its hold off the record; one that left it would leave the reader held, and
    the dispatch that follows would be refused.
    """
    shape = Shape(
        order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL),
        reads=((SIZING, FIRMWARE), (FIRMWARE, ELECTRICAL)),
        design=((CONTROL, FIRMWARE),),
    )
    rig = shape.rig(tmp_path, verdicts=("fail",) * 6)
    assert first_run(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    decide(rig.run_dir, "reject", "no design", item_id=item_of(rows, CONTROL))
    decide(rig.run_dir, "approve", item_id=item_of(rows, SIZING))
    resumed_before(
        rig,
        monkeypatch,
        shape,
        lambda e: e.kind == "dispatch_released" and e.outcome == "producer_held_for_good",
    )
    rows = lines(rig)
    assert refusal(rows) is None
    assert [r for r in sequence(rows) if r[0] == "dispatch_held" and r[1] == ELECTRICAL] == [
        ("dispatch_held", ELECTRICAL, FIRMWARE, "")
    ]
    assert not [r for r in rows if r.get("outcome") in ("producer_held_for_good",)]
    assert of(rows, "builder_held") != []
    (hold,) = of(rows, "dispatch_held", subtask_id=ELECTRICAL)
    release = {k: v for k, v in hold.items() if k != "interfaces"} | {
        "kind": "dispatch_released",
        "outcome": "producer_held_for_good",
    }
    (first,) = of(rows, "stage_entered", subtask_id=SIZING, attempt=1, stage="resolve")
    dispatch = first | {"subtask_id": ELECTRICAL}
    assert refusal([*rows, dispatch]) is not None, "a dispatch while the hold stands"
    assert refusal([*rows, release]) is None
    assert refusal([*rows, release, dispatch]) is None


# --- replay ---------------------------------------------------------------------------------------


def _renumbered(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(list(rows))


def test_replay_refuses_a_release_the_record_does_not_owe(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, _, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert refusal(rows) is None
    index = rows.index(of(rows, "dispatch_released")[0])
    # Another outcome than the one owed.
    wrong = _renumbered(rows)
    wrong[index]["outcome"] = "producer_held_for_good"
    assert refusal(wrong) is not None
    wrong[index]["outcome"] = "merged"
    assert refusal(wrong) is not None
    # The line left out: control is dispatched where its release was owed.
    left = _renumbered(rows)
    del left[index]
    assert refusal(left) is not None
    # A second copy of it, where none is owed.
    twice = _renumbered(rows)
    twice.insert(index + 1, copy.deepcopy(twice[index]))
    assert refusal(twice) is not None
    # The mark taken off: a record that did not start under the rule owes none of its lines.
    unmarked = _renumbered(rows)
    del unmarked[0]["wait_cycle"]
    assert refusal(unmarked) is not None


def test_replay_refuses_a_cycle_release_in_a_run_that_has_no_cycle(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shape = Shape(order=(SIZING, CONTROL), reads=((SIZING, CONTROL),))
    rig = shape.rig(tmp_path)
    first_run(rig, monkeypatch, shape)
    rows = lines(rig)
    assert refusal(rows) is None
    held = rows.index(of(rows, "dispatch_held")[0])
    forged = _renumbered(rows)
    forged[held] = {
        **forged[held],
        "kind": "dispatch_released",
        "outcome": "producer_waits_for_reader",
    }
    del forged[held]["interfaces"]
    assert refusal(forged) is not None
