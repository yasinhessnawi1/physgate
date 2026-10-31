"""A contract item holds to the line a person saw, and to what the record gives, in either mode.

A run that records only seals the decisions file at every spawn while a contract item is open, as a
run that acts does, so a session cannot move its own line ahead of its window and close the item;
a run with no failed contract writes no seal. A decision on the item is bound to the line shown in
either mode. Replay refuses a decision on it taken as not held where its line was written while a
session ran without the OS layer. A clause a joined side is missing from names that side as
deviating. A gate that only observed refuses nothing, so a person is asked. A pair's later failure,
held back while its item was open, gets its own item once that item is decided, whatever results
landed after it. The item's quantities, its quantity names and its one item per result hold too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    ACTS,
    ITEM,
    decide,
    escaped,
    failed_at,
    first_of,
    item_of,
    kinds,
    lines,
    ran,
    refusal,
    resumed,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    CLOSING,
    DRIVE,
    FW,
    IFACE_DRIVE,
    IFACE_TILT,
    INTEG,
    entry,
    hooked,
    node,
    rig_for,
)
from test_a_queue_decision_acts_at_a_boundary import _layer

from physgate import roles
from physgate.contracts.pairs import group
from physgate.orchestrator.arbitration import ContractConflict, contract_standing
from physgate.orchestrator.events import ContractItemRaised, Event, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.protocols import QuantityRef
from physgate.orchestrator.queue import (
    DECISIONS_NAME,
    PersonDecision,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import replay
from physgate.state.store import journal_records_after

ONE, TWO = "run-1-contract-1", "run-1-contract-2"


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def of(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["kind"] == kind]


# --- ORANGE-1: a run that records only seals the file while a contract item is open --------------


def _two_items_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, acts: bool, rewrite: bool
) -> list[dict[str, Any]]:
    """Both pairs on iface.drive fail, two items, and a line deciding one appears in a session.

    A person decides TWO between sessions; during the closing pass's session, without the OS
    layer, a line deciding ONE appears: moved ahead of the person's line (``rewrite``), or appended.
    """
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    low = node("budget.supply", "sizing", "iface.drive", v=11)
    rig = rig_for(
        tmp_path, fw_volts=11, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions")
    )
    if acts:
        rig.config_overrides.update(ACTS)
    rig.diff.writes.update({BUDGET: [low]})  # type: ignore[attr-defined]
    path = rig.run_dir / DECISIONS_NAME

    def forged() -> None:
        decide(rig.run_dir, "approve", item_id=ONE)
        if rewrite:
            first, second = path.read_bytes().splitlines(keepends=True)
            path.write_bytes(second + first)

    rig.dispatcher.during[4] = forged
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(BUDGET, DRIVE, FW))
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def emitting(event: Event) -> None:
        emit(event)
        if isinstance(event, ContractItemRaised) and event.item_id == TWO:
            decide(rig.run_dir, "reject", item_id=TWO)  # the person, between sessions

    monkeypatch.setattr(loop, "_emit", emitting)
    from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
        start,
    )

    start(loop, sizing=True)
    _layer(loop, present=False)
    assert escaped(loop.run) is None
    loop.close()
    return lines(rig)


def test_a_session_s_line_moved_ahead_of_its_window_halts_a_run_that_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As in a run that acts, which seals at every spawn (and here waits before the closing pass).
    rows = _two_items_run(tmp_path, monkeypatch, acts=False, rewrite=True)
    assert [i["cause"] for i in of(rows, "incident")] == ["decisions_rewritten"]
    assert ONE not in [t["item_id"] for t in of(rows, "decision_taken")]
    assert of(rows, "module_completed") == []


def test_a_session_s_line_appended_in_its_window_is_held_in_a_run_that_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _two_items_run(tmp_path, monkeypatch, acts=False, rewrite=False)
    taken = {t["item_id"]: t["why_not"] for t in of(rows, "decision_taken")}
    assert taken[ONE] == "held_os_layer_off"
    assert BUDGET not in [r["subtask_id"] for r in of(rows, "module_completed")]
    # Sealed from the first item on, at each spawn while one is open; never before.
    first_item = kinds(rows).index("contract_item_raised")
    sealed = [r["seq"] for r in of(rows, "decisions_sealed")]
    assert sealed and min(sealed) > first_item
    assert refusal(rows) is None


def test_a_run_that_records_only_and_has_no_failed_contract_writes_no_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = lines(ran(tmp_path, monkeypatch, declared=(DRIVE, FW)))
    assert [r["result"]["outcome"] for r in of(rows, "contract_tested")] == ["pass", "pass"]
    assert "decisions_sealed" not in kinds(rows)


# --- YELLOW-1: a decision is bound to the line shown, in either mode -----------------------------


@pytest.mark.parametrize("acts", [False, True], ids=["records", "acts"])
def test_a_decision_on_a_line_since_put_back_is_not_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acts: bool
) -> None:
    rig = ran(tmp_path, monkeypatch, acts=acts, fw_volts=11, declared=(DRIVE, FW))
    path = rig.run_dir / "queue.jsonl"
    original = path.read_bytes()
    raw = original.splitlines()
    at = [json.loads(line)["item_id"] for line in raw].index(ITEM)
    item = QueueItem.model_validate_json(raw[at])
    rewritten = item.model_copy(update={"triggering_finding": "REWRITTEN: choose the producer"})
    raw[at] = rewritten.model_dump_json().encode()
    path.write_bytes(b"\n".join(raw) + b"\n")
    decide(rig.run_dir, "choose", position="consumer")
    path.write_bytes(original)
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    rows = lines(rig)
    assert of(rows, "decision_taken") == []
    assert [i["cause"] for i in of(rows, "incident")] == ["queue_item_mismatch"]


# --- YELLOW-2: replay holds a contract decision to the window its line was written in ------------


def test_replay_refuses_a_held_contract_decision_rewritten_as_not_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
        start,
    )

    low = node("budget.supply", "sizing", "iface.drive", v=11)
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig.diff.writes.update({BUDGET: [low]})  # type: ignore[attr-defined]
    rig.dispatcher.during[3] = lambda: decide(rig.run_dir, "approve")
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(BUDGET, DRIVE, FW))
    start(loop, sizing=True)
    _layer(loop, present=False)
    assert escaped(loop.run) is None
    loop.close()
    rows = lines(rig)
    at = kinds(rows).index("decision_taken")
    assert rows[at]["why_not"] == "held_os_layer_off"
    assert refusal(rows) is None
    for why in ("legacy_item", "not_bound"):
        said = refusal([*rows[:at], rows[at] | {"why_not": why}])
        assert said is not None and "held" in said, (why, said)
    # And the other way: a line written between sessions is never taken as held.
    clean = lines(ran(tmp_path / "between", monkeypatch, fw_volts=11, declared=(DRIVE, FW)))
    assert "contract_item_raised" in kinds(clean)


# --- YELLOW-3: a side missing from a failed clause's nodes deviates ------------------------------


def test_a_clause_a_joined_side_is_missing_from_names_that_side_and_crashes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11, kill=first_of("contract_ruled"))
    path = rig.run_dir / "events.jsonl"
    rows = lines(rig)
    at = failed_at(rows)
    for check in rows[at]["result"]["interfaces"]:
        if check["interface"] == "iface.drive":
            assert check["producer_nodes"]
            for clause in check["clauses"]:
                clause["nodes"] = [
                    n | {"outcome": "pass", "reason": None}
                    for n in clause["nodes"]
                    if n["side"] == "consumer"
                ]
    path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in rows))
    state = replay(read_events(path))
    owed = state.owed_ruling()
    assert owed is not None and owed.sides == ("producer",), owed
    assert escaped(lambda: resumed(rig, monkeypatch)) is None
    assert "The producer's nodes deviate from the interface." in item_of(rig).decision_required


# --- YELLOW-4: a gate that only observed refuses nothing -----------------------------------------


@pytest.mark.parametrize(("mode", "refused"), [("observe", False), ("on", True)])
def test_a_contract_clause_is_the_gate_s_only_where_the_gate_blocks(
    mode: str, refused: bool
) -> None:
    from loop_fakes import failing_gate_result

    named = QuantityRef(node_id="fw.main", name="v", value=11, unit="V")
    gate = failing_gate_result(mode).model_copy(update={"quantities": (named,)})  # type: ignore[arg-type]
    standing = contract_standing(
        ContractConflict(interface="iface.drive", quantity="v"),
        gate=gate,
        nodes=("fw.main",),
        earlier=(),
        attempt_left=True,
    )
    assert standing.gate_refused is refused


# --- YELLOW-5: a pair's held-back failure gets its item, whatever landed after it ----------------


def _two_sizing_pairs(loop: Loop) -> tuple[Any, ...]:
    """Sizing consumes both interfaces: drive to budget and fw to budget are both pairs."""
    plan = [
        entry(BUDGET, "sizing", "budget"),
        entry(DRIVE, "control", "drive"),
        entry(FW, "firmware", "fw"),
        entry(CLOSING, "sizing", "budget"),
        entry(INTEG, "integration", "integration"),
    ]
    consumers = {"iface.drive": ("fw", "budget"), "iface.tilt": ("drive", "budget")}
    from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
        side,
    )

    sides = {
        "budget": side(BUDGET, "sizing"),
        "drive": side(DRIVE, "control"),
        "fw": side(FW, "firmware"),
    }
    pairs = group({"iface.drive": "drive", "iface.tilt": "fw"}, consumers, sides)
    requirement = '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
    head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
    summary = DecompositionSummary(
        session_id="decomposition",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.drive", "iface.tilt"),
        spec_commit="e" * 40,
        head_revision=head,
        interface_consumers=tuple(
            InterfaceConsumers(interface=i, consumers=c) for i, c in consumers.items()
        ),
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=pairs,
        brief_words=None,
    )
    loop.record.start(plan, decomposed=summary)
    return pairs


def test_a_pairs_held_back_failure_gets_its_item_whatever_results_landed_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both = ("iface.drive", "iface.tilt")
    low = node("budget.supply", "sizing", *both, v=11, period=10)
    rig = rig_for(
        tmp_path,
        fw_volts=12,
        closing_volts=11,
        dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"),
    )
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {BUDGET: [low], CLOSING: [node("budget.supply", "sizing", *both, v=11, period=10)]}
    )
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(BUDGET, DRIVE, FW))
    pairs = _two_sizing_pairs(loop)
    loop.run()
    loop.close()
    budget_pair = next(
        i
        for i, p in enumerate(pairs)
        if (p.producer.module, p.consumer.module) == ("drive", "budget")
    )
    item = f"run-1-contract-{budget_pair + 1}"
    rows = lines(rig)
    tested = [
        (r["result"]["pair"]["producer"]["module"], r["result"]["pair"]["consumer"]["module"])
        for r in of(rows, "contract_tested")
    ]
    # The closing pass's merge owes a retest of both of sizing's pairs: drive's fails again,
    # held back while its item is open, and fw's lands after it.
    assert tested[-2:] == [("drive", "budget"), ("fw", "budget")], tested
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [item]
    decide(rig.run_dir, "approve", item_id=item)
    resumed(rig, monkeypatch, declared=(BUDGET, DRIVE, FW))
    rows = lines(rig)
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [item, f"{item}-r2"]
    assert refusal(rows) is None


# --- YELLOW-7: the rules the review's surviving mutants changed ----------------------------------


def test_a_run_that_records_only_takes_a_decision_on_a_contract_item_and_on_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Integration's review blocks: its item is an O3 item, beside the open contract item.
    rig = rig_for(
        tmp_path, fw_volts=11, dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions")
    )
    rig.reviewer.results[3] = blocked_review()
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW))
    from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
        start,
    )

    start(loop)
    loop.run()
    loop.close()
    view = read_queue(rig.run_dir)
    blocked = [i for i in view.items if i.subtask_id == INTEG]
    assert len(blocked) == 1
    record_decision(
        rig.run_dir,
        blocked[0].item_id,
        person=PersonDecision(verb="reject", note="give the pole", position=None),
        resolved_by="yasin",
        shown=ShownItem(
            item_sha256=view.digests[blocked[0].item_id],
            trajectories=statuses_now(rig.run_dir, blocked[0].item_id),
        ),
    )
    decide(rig.run_dir, "approve")
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    assert [t["item_id"] for t in of(lines(rig), "decision_taken")] == [ITEM]


def test_an_interface_value_in_a_refused_unit_is_named_and_never_listed_as_a_quantity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worded = json.loads(json.dumps(IFACE_DRIVE))
    worded["quantities"]["v"]["unit"] = "UNITWORD"
    rig = ran(tmp_path, monkeypatch, interfaces=(worded, IFACE_TILT))
    item = item_of(rig)
    assert item.quantities == ()
    assert "the interface holds 12, in a unit the gate's parser refuses" in item.triggering_finding


def test_an_interface_quantity_named_as_no_dispute_names_one_is_not_quoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def named(payload: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = json.loads(json.dumps(payload))
        out["quantities"]["Vmax"] = out["quantities"].pop("v")
        return out

    fw = named(node("fw.main", "firmware", "iface.drive", "iface.tilt", v=11, period=10))
    rig = ran(tmp_path, monkeypatch, interfaces=(named(IFACE_DRIVE), IFACE_TILT), writes={FW: [fw]})
    finding = item_of(rig).triggering_finding
    assert "quantity a quantity name the dispute path refuses" in finding, finding
    assert '"Vmax"' not in finding


def test_a_decided_item_s_result_gets_no_second_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pair's failed result is still the latest when the person's choice records only.
    rig = ran(tmp_path, monkeypatch, acts=True, fw_volts=11, declared=(DRIVE, FW))
    decide(rig.run_dir, "choose", position="consumer")
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    rows = lines(rig)
    assert [r["item_id"] for r in of(rows, "contract_item_raised")] == [ITEM]
    assert [i.item_id for i in read_queue(rig.run_dir).items if i.source == "contract"] == [ITEM]
