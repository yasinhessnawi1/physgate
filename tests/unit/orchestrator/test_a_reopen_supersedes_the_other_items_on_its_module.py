"""A reopen supersedes every other undecided contract item on the reopened module.

A module in two failed pairs has two items. A choice on one that reopens the module changes what
the other said: its attempt numbers, which side can reopen. So at the reopen the other item is
superseded. It no longer holds the waits or completion, and a decision written on it later is
taken record-only, as ``superseded``, still bound to the line the person saw, and never acts.
While either module of its pair is neither merged nor ended rejected, sent to a person included,
the pair owes nothing; once the module settles, the retest the reopened merge owes decides, and a
pair that still fails is listed again as a new round, made from what is true then. The status route names each superseded item and the item whose reopen
superseded it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeReviewer, Rig
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (
    BOTH,
    MENDED_FW,
    again,
    choose,
    of,
    opened,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    ITEM,
    escaped,
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    CLOSING,
    DRIVE,
    FW,
    P_BACK,
    node,
)
from ui_rig import context_over, fake_ui

from physgate import roles
from physgate.orchestrator.events import Event, SubtaskReopened, read_events
from physgate.orchestrator.queue import (
    PersonDecision,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.replay import RunState, replay
from physgate.ui import readers

#: The second pair's item: fw (producer) to drive (consumer) over ``iface.tilt``.
OTHER = "run-1-contract-2"
#: Its next round, listed once fw settles and the pair still fails.
AGAIN = f"{OTHER}-r2"
#: fw deviating on both interfaces: on ``v`` (``iface.drive``) and on ``period`` (``iface.tilt``).
BOTH_LOW = node("fw.main", "firmware", *BOTH, v=11, period=9)
#: fw's reopened attempt mends ``v`` alone, so the second pair still fails at the retest.
HALF = node("fw.main", "firmware", *BOTH, v=12, period=9)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def reopened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mended: dict[str, Any] = HALF) -> Rig:
    """Both of fw's pairs fail and each has an item; a choice on the first reopens fw."""
    rig = opened(tmp_path, monkeypatch, writes={FW: [BOTH_LOW]}, mended={FW: mended})
    assert [i.item_id for i in read_queue(rig.run_dir).items] == [ITEM, OTHER]
    choose(rig.run_dir, "producer")
    assert escaped(lambda: again(rig, monkeypatch)) is None
    return rig


def status_of(tmp_path: Path, rig: Rig) -> dict[str, Any]:
    context = context_over(rig.run_dir.parent, ui_root=fake_ui(tmp_path / "checkout"))
    answer = readers.status(context, {"root": "0", "name": rig.run_dir.name})
    status: dict[str, Any] = json.loads(answer.body)
    return status


def test_a_second_item_on_a_reopened_module_is_listed_again_as_a_new_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopened(tmp_path, monkeypatch)
    rows = lines(rig)
    (reopen,) = of(rows, "subtask_reopened")
    assert reopen["subtask_id"] == FW
    # fw merged again, both pairs were retested, and the one still failing is the next round.
    raised = of(rows, "contract_item_raised")
    assert [r["item_id"] for r in raised] == [ITEM, OTHER, AGAIN]
    remerged = of(rows, "merged", subtask_id=FW)[1]
    assert rows.index(reopen) < rows.index(remerged) < rows.index(raised[-1])
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.superseded == {OTHER: ITEM}
    assert not state.undecided(OTHER)
    assert state.undecided(AGAIN)
    # The new round says what is true now: fw merged at attempt 2, so a reopen is attempt 3.
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == AGAIN)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "record_only", "consumer": "reopen"}
    assert "(attempt 3)" in item.decision_required
    assert "again (round 2)" in item.decision_required
    # A choice on it is taken, with no halt.
    choose(rig.run_dir, "producer", item_id=AGAIN)
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    taken = of(rows, "decision_taken", item_id=AGAIN)
    assert [(t["effect"], t["why_not"]) for t in taken] == [("none", "record_only_source")]
    assert of(rows, "incident") == []
    assert refusal(rows) is None


def test_a_decision_on_a_superseded_item_records_only_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopened(tmp_path, monkeypatch)
    choose(rig.run_dir, "consumer", item_id=OTHER)  # what the item offered: reopen fw
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    assert of(rows, "incident") == []
    (taken,) = of(rows, "decision_taken", item_id=OTHER)
    assert (taken["effect"], taken["acts"], taken["why_not"]) == ("none", False, "superseded")
    assert "reopens" not in taken
    assert len(of(rows, "subtask_reopened")) == 1
    assert refusal(rows) is None
    at = rows.index(taken)
    # The line is the record's: one that acts, reopens, or keeps the item's own reason is refused.
    for forged in (
        taken | {"effect": "reopen", "acts": True, "why_not": None, "reopens": FW},
        taken | {"why_not": "record_only_source"},
    ):
        why = refusal([*rows[:at], forged])
        assert why is not None and "does other than the record allows" in why, why
    # And no item that is not superseded is taken as one.
    first = of(rows, "decision_taken", item_id=ITEM)[0]
    forged = first | {"effect": "none", "acts": False, "why_not": "superseded", "reopens": None}
    why = refusal([*rows[: rows.index(first)], forged])
    assert why is not None and "does other than the record allows" in why, why


def test_a_superseded_items_pair_that_holds_at_the_retest_lists_nothing_and_completion_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopened(tmp_path, monkeypatch, mended=MENDED_FW)
    rows = lines(rig)
    retests = of(rows, "contract_tested")[2:]
    assert [r["result"]["outcome"] for r in retests] == ["pass", "pass"]
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [ITEM, OTHER]
    planned = [r["subtask_id"] for r in of(rows, "subtask_planned")]
    completed = [r["subtask_id"] for r in of(rows, "module_completed")]
    assert completed == [s for s in planned if s != "integ"]
    assert refusal(rows) is None


def test_the_status_names_each_superseded_item_and_its_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopened(tmp_path / "a", monkeypatch)
    assert status_of(tmp_path / "a", rig).get("superseded") == {OTHER: ITEM}
    fresh = opened(tmp_path / "b", monkeypatch, writes={FW: [BOTH_LOW]})
    assert status_of(tmp_path / "b", fresh).get("superseded") == {}


def _at_the_reopen(event: Event, written: list[Event]) -> bool:
    return isinstance(event, SubtaskReopened)


def test_a_kill_at_the_reopen_resumes_to_exactly_one_new_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch, writes={FW: [BOTH_LOW]}, mended={FW: HALF})
    choose(rig.run_dir, "producer")
    assert again(rig, monkeypatch, kill=_at_the_reopen) == "killed"
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    assert len(of(rows, "subtask_reopened")) == 1
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [ITEM, OTHER, AGAIN]
    assert replay(read_events(rig.run_dir / "events.jsonl")).superseded == {OTHER: ITEM}
    assert refusal(rows) is None


#: fw's verdicts when its reopened attempts 2 and 3 are refused by review and it goes to a person.
REFUSED_TWICE = ("pass", "pass", "fail", "fail", "pass", "pass")


def escalated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """fw, reopened by the choice on the first item, goes to a person unmerged."""
    rig = opened(
        tmp_path,
        monkeypatch,
        writes={FW: [BOTH_LOW]},
        mended={FW: HALF},
        reviewer=FakeReviewer(verdicts=list(REFUSED_TWICE)),
    )
    choose(rig.run_dir, "producer")
    assert escaped(lambda: again(rig, monkeypatch)) is None
    return rig


def settle(rig: Rig, verb: str) -> None:
    """A person's ``verb`` on fw's escalation item, bound to the view as it stands."""
    item_id = replay(read_events(rig.run_dir / "events.jsonl")).subtasks[FW].queue_item
    assert item_id is not None
    shown = ShownItem(
        item_sha256=read_queue(rig.run_dir).digests[item_id],
        trajectories=statuses_now(rig.run_dir, item_id),
    )
    note = "fw stays as it is" if verb == "reject" else None
    record_decision(
        rig.run_dir,
        item_id,
        person=PersonDecision(verb=verb, note=note),  # type: ignore[arg-type]
        resolved_by="yasin",
        shown=shown,
    )


def test_a_pair_owes_no_new_round_while_its_reopened_module_waits_for_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Merged at 1 and reopened, fw's attempts 2 and 3 are refused by review and go to a person.
    # fw may still merge, so the pair it still fails with is not listed again while it waits.
    rig = escalated(tmp_path, monkeypatch)
    rows = lines(rig)
    assert [r["attempt"] for r in of(rows, "attempt_rejected", subtask_id=FW)] == [2, 3]
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.subtasks[FW].status == "escalated"
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [ITEM, OTHER]
    assert state.superseded == {OTHER: ITEM}
    assert refusal(rows) is None


def test_a_superseded_item_is_listed_again_from_the_retest_once_its_module_is_merged_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The person approves fw's attempt 3: fw is merged again, the pair is retested and still
    # fails, and exactly one new round is listed, made from that retest. A choice on it is taken
    # with no halt.
    rig = escalated(tmp_path, monkeypatch)
    settle(rig, "approve")
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    assert len(of(rows, "merged", subtask_id=FW)) == 2
    tested = of(rows, "contract_tested")
    assert [r["result"]["outcome"] for r in tested] == ["fail", "fail", "pass", "fail"]
    raised = of(rows, "contract_item_raised")
    assert [r["item_id"] for r in raised] == [ITEM, OTHER, AGAIN]
    assert rows.index(tested[-1]) < rows.index(raised[-1])
    assert replay(read_events(rig.run_dir / "events.jsonl")).undecided(AGAIN)
    choose(rig.run_dir, "producer", item_id=AGAIN)
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    assert of(rows, "incident") == []
    assert len(of(rows, "decision_taken", item_id=AGAIN)) == 1
    assert refusal(rows) is None


def test_a_superseded_item_is_listed_again_once_its_module_ends_without_merging_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The person rejects fw's attempt 3, so fw ends without merging again: no retest is owed and
    # the old failed result is the pair's latest. It is listed again, saying what is true then:
    # fw cannot be reopened.
    rig = escalated(tmp_path, monkeypatch)
    settle(rig, "reject")
    assert escaped(lambda: again(rig, monkeypatch)) is None
    rows = lines(rig)
    assert replay(read_events(rig.run_dir / "events.jsonl")).subtasks[FW].status == "rejected"
    assert len(of(rows, "contract_tested")) == 2  # no retest: fw never merged again
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [ITEM, OTHER, AGAIN]
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == AGAIN)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "record_only", "consumer": "record_only"}
    assert refusal(rows) is None


# --- which items a reopen supersedes, and what a superseded item is still bound to -------------


def test_a_reopen_leaves_an_item_on_a_pair_without_the_reopened_module_open_and_holding_the_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sizing's plan: its opening pass breaks drive's interface too, so drive to budget has an item
    # of its own. A choice on fw's first pair reopens fw: its other pair's item is superseded,
    # and the one on a pair fw is not in stays undecided, so the closing pass still waits for it.
    on_budget, on_fw, on_back = (f"run-1-contract-{n}" for n in (1, 2, 3))
    low = node("budget.supply", "sizing", "iface.drive", v=11)
    rig = opened(
        tmp_path,
        monkeypatch,
        sizing=True,
        writes={BUDGET: [low], FW: [BOTH_LOW]},
        declared=(BUDGET, DRIVE, FW),
    )
    assert [i.item_id for i in read_queue(rig.run_dir).items] == [on_budget, on_fw, on_back]
    choose(rig.run_dir, "producer", item_id=on_fw)
    assert escaped(lambda: again(rig, monkeypatch, declared=(BUDGET, DRIVE, FW))) is None
    rows = lines(rig)
    assert [r["subtask_id"] for r in of(rows, "subtask_reopened")] == [FW]
    assert [r["result"]["outcome"] for r in of(rows, "contract_tested")][-2:] == ["pass", "pass"]
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.superseded == {on_back: on_fw}
    assert state.undecided(on_budget)
    assert of(rows, "stage_entered", subtask_id=CLOSING) == []
    step = state.next_step()
    assert (step.kind, step.subtask_id) == ("wait", CLOSING)
    assert refusal(rows) is None


def test_a_decision_on_a_superseded_item_whose_line_changed_since_it_was_shown_is_not_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = reopened(tmp_path, monkeypatch)
    path = rig.run_dir / "queue.jsonl"
    original = path.read_bytes()
    raw = original.splitlines()
    at = [json.loads(line)["item_id"] for line in raw].index(OTHER)
    item = QueueItem.model_validate_json(raw[at])
    rewritten = item.model_copy(update={"triggering_finding": "REWRITTEN: choose the consumer"})
    raw[at] = rewritten.model_dump_json().encode()
    path.write_bytes(b"\n".join(raw) + b"\n")
    choose(rig.run_dir, "consumer", item_id=OTHER)
    path.write_bytes(original)
    again(rig, monkeypatch)
    rows = lines(rig)
    assert of(rows, "decision_taken", item_id=OTHER) == []
    assert [i["cause"] for i in of(rows, "incident")] == ["queue_item_mismatch"]


# --- a pair owes no round while a module of it is unsettled --------------------------------------


def _up_to(rig: Rig, last: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> RunState:
    """The run as its log replays through the line ``last`` picks, that line included."""
    events = read_events(rig.run_dir / "events.jsonl")
    return replay(events[: lines(rig).index(last(lines(rig))) + 1])


@pytest.mark.parametrize(
    ("status", "owed"),
    [
        ("planned", False),
        ("active", False),
        ("waiting", False),
        ("escalated", False),
        ("rejected", True),
        ("done", True),
    ],
)
def test_a_pair_owes_no_round_while_either_module_is_neither_merged_nor_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, owed: bool
) -> None:
    # Two points of one record: just after fw's reopen, where its pair's latest failure has a
    # superseded item; and just after the retest once fw is merged again, before the new round,
    # where the failure has no item yet. Whichever module of the pair is unsettled, a reopened
    # module that waits for sizing's closing pass or for a person included, nothing is owed.
    rig = escalated(tmp_path, monkeypatch)
    settle(rig, "approve")
    assert escaped(lambda: again(rig, monkeypatch)) is None
    points = (
        lambda rows: of(rows, "subtask_reopened")[0],
        lambda rows: of(rows, "contract_ruled")[-1],
    )
    for point in points:
        for side, other in ((FW, DRIVE), (DRIVE, FW)):
            state = _up_to(rig, point)
            latest = state.latest_contract(P_BACK)
            assert latest is not None and latest.result.outcome == "fail"
            state.subtasks[other].status = "done"
            state.subtasks[side].status = status  # type: ignore[assignment]
            assert state.owed_item() is (latest if owed else None), (side, status)
