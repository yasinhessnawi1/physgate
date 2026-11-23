"""Under ``wait_cycle: release_2`` a reader is held only on a producer that is itself with a person.

A producer merely blocked behind one holds nobody, so a hold never opens on a producer that waits
for something. A cycle release (``producer_waits_for_reader`` or ``producer_held_for_good``) is
written, and replays, only on a hold that is already open, after a person's decision took its
producer out of ``escalated``: the rows for that are in
``test_a_hold_outlives_its_producer_s_time_with_a_person_without_ending_the_run_in_a_wait.py``.
A builder held for good is planned, never escalated, so no reader is held on one as a run
begins. A run that acts and ends with a subtask that never ran ends as ``unrun``, naming it, why,
and what merged without it; recorded under ``release`` or with no mark it ends as it always did.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_queue_decision_acts_at_a_boundary import decide
from test_a_reader_is_let_go_by_a_producer_that_waits_for_it import (
    REAL,
    decided_run,
    item_of,
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
)

from physgate import roles
from physgate.orchestrator import record
from physgate.orchestrator.events import read_events
from physgate.orchestrator.replay import replay
from physgate.orchestrator.waiting import printed_step

pytestmark = pytest.mark.usefixtures("before_the_sign_off_rule")

CYCLE_OUTCOMES = ("producer_waits_for_reader", "producer_held_for_good")
#: Sizing and control go to a person; firmware builds control's design and is read by electrical.
HELD_FOR_GOOD = Shape(
    order=(SIZING, CONTROL, FIRMWARE, ELECTRICAL),
    reads=((SIZING, FIRMWARE), (FIRMWARE, ELECTRICAL)),
    design=((CONTROL, FIRMWARE),),
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def held_for_good_run(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, str, list[dict[str, Any]]]:  # noqa: ANN401
    """Control's designer is rejected, so firmware (its builder) never runs; electrical reads it."""
    shape = HELD_FOR_GOOD
    rig = shape.rig(tmp_path, verdicts=("fail",) * 6)
    assert first_run(rig, monkeypatch, shape) == "wait"
    rows = lines(rig)
    decide(rig.run_dir, "reject", "no design", item_id=item_of(rows, CONTROL))
    decide(rig.run_dir, "approve", item_id=item_of(rows, SIZING))
    step = resumed(rig, monkeypatch, shape)
    return rig, step, lines(rig)


def test_the_first_line_of_an_acting_run_carries_release_2_in_its_place(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = REAL.rig(tmp_path)
    first_run(rig, monkeypatch, REAL)
    row = lines(rig)[0]
    keys = list(row)
    assert (row["producer_wait"], row["closing_wait"], row["wait_cycle"]) == (
        "hold",
        "hold",
        "release_2",
    )
    assert keys.index("producer_wait") < keys.index("closing_wait") < keys.index("wait_cycle")


def test_the_real_run_s_shape_holds_its_readers_on_sizing_alone_and_writes_no_cycle_line(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, step, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert step == "done"
    assert merged_order(rows) == [SIZING, CONTROL, FIRMWARE, CLOSING, "integ"]
    # Control reads firmware, which is merely blocked behind sizing (and waits for control as its
    # designer): it holds nobody. Only sizing, with a person, holds its two readers.
    assert sequence(rows) == [
        ("dispatch_held", CONTROL, SIZING, ""),
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", CONTROL, SIZING, "merged"),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
    ]
    assert not [r for r in of(rows, "dispatch_released") if r["outcome"] in CYCLE_OUTCOMES]
    assert refusal(rows) is None


def test_every_hold_names_its_producer_s_own_item(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, rows = decided_run(tmp_path, monkeypatch, REAL)
    own = {r["subtask_id"]: r["item_id"] for r in of(rows, "escalated")}
    holds = of(rows, "dispatch_held")
    assert holds
    assert all(own[h["producer"]] == h["item_id"] for h in holds)


def test_no_reader_is_held_on_a_builder_held_for_good_so_no_such_release_is_owed(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A builder held for good is planned, never escalated: nothing holds a reader on it."""
    _, step, rows = held_for_good_run(tmp_path, monkeypatch)
    assert step == "unrun"
    assert [r for r in sequence(rows) if r[0].startswith("dispatch_")] == [
        ("dispatch_held", FIRMWARE, SIZING, ""),
        ("dispatch_released", FIRMWARE, SIZING, "merged"),
    ]
    assert not [r for r in of(rows, "dispatch_released") if r["outcome"] in CYCLE_OUTCOMES]
    assert ("builder_held", FIRMWARE, CONTROL, "ended_unmerged") in sequence(rows)
    assert refusal(rows) is None


def test_a_run_that_ends_with_a_module_that_never_ran_ends_unrun_naming_it(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, step, rows = held_for_good_run(tmp_path, monkeypatch)
    assert step == "unrun"
    assert SIZING in merged_order(rows)
    assert FIRMWARE not in merged_order(rows)
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.subtasks[FIRMWARE].status == "planned"
    printed, status = printed_step("unrun", state)
    assert status == 1
    assert printed == {
        "step": "unrun",
        "never_ran": [
            {
                "subtask_id": FIRMWARE,
                "why": f"its designer {CONTROL} ended without a merge",
                "ran_without": [ELECTRICAL],
            }
        ],
    }


def test_a_sign_off_owed_still_ends_the_run_escalated_before_it_ends_unrun(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, _, _ = held_for_good_run(tmp_path, monkeypatch)
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.next_step().kind == "unrun"
    monkeypatch.setattr(type(state), "sign_offs_open", lambda _self: [CONTROL])
    assert state.next_step().kind == "escalated"


@pytest.mark.parametrize(("mark", "end"), [(None, "wait"), ("release", "done")])
def test_recorded_under_an_earlier_rule_the_same_run_ends_as_it_did(
    mark: str | None,
    end: str,
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(record, "WAIT_CYCLE", mark)
    rig, step, rows = held_for_good_run(tmp_path, monkeypatch)
    assert step == end
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.subtasks[FIRMWARE].status == "planned"
    printed, status = printed_step(end, state)
    assert "never_ran" not in printed
    assert refusal(rows) is None


def test_the_recorded_cycle_release_of_an_earlier_run_is_refused_under_release_2_only(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(record, "WAIT_CYCLE", "release")
    _, _, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert of(rows, "dispatch_released")[0]["outcome"] == "producer_waits_for_reader"
    assert refusal(rows) is None
    narrowed = copy.deepcopy(rows)
    narrowed[0]["wait_cycle"] = "release_2"
    assert refusal(narrowed) is not None


def test_a_cycle_release_forged_into_a_release_2_record_is_refused(
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, rows = decided_run(tmp_path, monkeypatch, REAL)
    assert refusal(rows) is None
    index = rows.index(of(rows, "dispatch_held")[0])
    for outcome in CYCLE_OUTCOMES:
        forged = copy.deepcopy(rows)
        forged[index] = {k: v for k, v in forged[index].items() if k != "interfaces"} | {
            "kind": "dispatch_released",
            "outcome": outcome,
        }
        assert refusal(forged) is not None, outcome


# --- the cost of the narrowing, pinned in both orders -----------------------------------------

#: Firmware goes to a person; sizing reads firmware's interface; electrical reads sizing's.
TRANSITIVE = Shape(
    order=(FIRMWARE, SIZING, ELECTRICAL),
    reads=((FIRMWARE, SIZING), (SIZING, ELECTRICAL)),
)


@pytest.mark.parametrize(
    ("mark", "order"),
    [
        ("release", [FIRMWARE, SIZING, ELECTRICAL, CLOSING, "integ"]),
        ("release_2", [ELECTRICAL, FIRMWARE, SIZING, CLOSING, "integ"]),
    ],
)
def test_a_reader_of_a_producer_blocked_behind_a_person_runs_first_only_under_release_2(
    mark: str,
    order: list[str],
    tmp_path: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cost the narrowing accepts: electrical may run on sizing's plan values.

    Sizing waits behind firmware's item and holds nobody under ``release_2``, so electrical, which
    reads sizing's interface, runs before them; under ``release`` it waits for sizing to merge.
    """
    monkeypatch.setattr(record, "WAIT_CYCLE", mark)
    rig = TRANSITIVE.rig(tmp_path)
    assert first_run(rig, monkeypatch, TRANSITIVE) == "wait"
    rows = lines(rig)
    decide(rig.run_dir, "approve", item_id=item_of(rows, FIRMWARE))
    assert resumed(rig, monkeypatch, TRANSITIVE) == "done"
    rows = lines(rig)
    assert merged_order(rows) == order
    assert refusal(rows) is None
