"""A failed contract is ruled clause by clause, and what the gate did not decide goes to a person.

After a pair's contract result fails, the record owes one ruling per failed clause, in the
result's order, before anything else: the precedence table rules each one (ARCH-040), at the gate
where the merging attempt's gate failed naming the clause's quantity, and otherwise for a person.
The ruling states both positions as the journal held them: the interface's value and each failing
node's, with their revisions, never a node's free-text provenance. An interface with no quantity
that a side is not joined to is one conflict with no quantity. If a clause went to a person, one
item follows, listed in the queue with the positions ``producer`` and ``consumer``, unless the pair
already has an item no decision was taken on. In this build every verb on it records only, the item
says so, and the item is rebuilt from the log and compared whole when a decision is taken. A module
is not recorded complete while an item about one of its pairs is undecided.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeGate, KilledError, Rig, failing_gate_result
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    DRIVE,
    FW,
    IFACE_DRIVE,
    IFACE_TILT,
    P_BUDGET,
    comparable,
    hooked,
    node,
    rig_for,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import _layer

from physgate import roles
from physgate.evaluation.observe.sequence import decisions
from physgate.orchestrator import completion
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.decisions import SCANNED_SOURCES
from physgate.orchestrator.events import Event, parse_events, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.protocols import Artefact, GateResult, QuantityRef, RunningGateMode
from physgate.orchestrator.queue import (
    PersonDecision,
    QueueError,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.replay import replay
from physgate.oslayer.probe import Present

ITEM = "run-1-contract-1"
SPAN = "e" * 40
ACTS = {
    "queue_decisions": "act",
    "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
}


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def lines(rig: Rig) -> list[dict[str, Any]]:
    raw = (rig.run_dir / "events.jsonl").read_bytes().splitlines()
    return [json.loads(line) for line in raw]


def kinds(rows: Sequence[dict[str, Any]]) -> list[str]:
    return [row["kind"] for row in rows]


def failed_at(rows: Sequence[dict[str, Any]]) -> int:
    """Where the first failed contract result is."""
    return next(
        i
        for i, row in enumerate(rows)
        if row["kind"] == "contract_tested" and row["result"]["outcome"] == "fail"
    )


def refusal(rows: Sequence[dict[str, Any]]) -> str | None:
    """Why ``rows``, renumbered and read as a fresh process reads them, do not replay; or None."""
    data = b"".join(json.dumps(row | {"seq": i}).encode() + b"\n" for i, row in enumerate(rows))
    try:
        replay(parse_events(data, log="events.jsonl"))
    except CorruptEventLogError as exc:
        return str(exc.context.get("reason", exc))
    except Exception as exc:  # noqa: BLE001 - any other escape is a refusal no rule gave
        return f"raised {type(exc).__name__}: {exc}"
    return None


def ran(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    acts: bool = False,
    sizing: bool = False,
    declared: Sequence[str] | None = None,
    writes: dict[str, list[dict[str, Any]]] | None = None,
    kill: Callable[[Event, list[Event]], bool] | None = None,
    **fields: Any,  # noqa: ANN401 - the rig's own
) -> Rig:
    """The contract rig, driven to its end (or to the line ``kill`` picks)."""
    # A person binds a decision to the streams the item links, each held to its seal.
    fields.setdefault("dispatcher", FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig = rig_for(tmp_path, **fields)
    if acts:
        rig.config_overrides.update(ACTS)
    rig.diff.writes.update(writes or {})  # type: ignore[attr-defined]
    loop = rig.open()
    hooked(monkeypatch, loop, declared=declared, kill=kill)
    start(loop, sizing=sizing)
    if acts:
        _layer(loop)
    with contextlib.suppress(KilledError):
        loop.run()
    loop.close()
    return rig


def resumed(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, declared: Sequence[str] | None = None
) -> str:
    loop = rig.open()
    hooked(monkeypatch, loop, declared=declared)
    if rig.config_overrides.get("queue_decisions") == "act":
        _layer(loop)
    kind = loop.resume().kind
    loop.close()
    return kind


def decide(run_dir: Path, verb: str, *, position: str | None = None, item_id: str = ITEM) -> None:
    view = read_queue(run_dir)
    shown = ShownItem(
        item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
    )
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(
            verb=verb,  # type: ignore[arg-type]
            note="the interface stands" if verb == "reject" else None,
            position=position,  # type: ignore[arg-type]
        ),
        resolved_by="yasin",
        shown=shown,
    )


def value(node_id: str, name: str, amount: float, unit: str, revision: int) -> dict[str, Any]:
    return {
        "position": {"node_id": node_id, "name": name, "value": amount, "unit": unit},
        "revision": revision,
    }


# --- the rulings and the item -------------------------------------------------------------------


def test_a_failed_contract_is_ruled_one_line_per_failed_clause_and_goes_to_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11)
    rows = lines(rig)
    at = failed_at(rows)
    assert kinds(rows[at : at + 4]) == [
        "contract_tested",
        "contract_ruled",
        "contract_item_raised",
        "contract_tested",
    ]
    ruled, raised = rows[at + 1], rows[at + 2]
    assert "tested" not in ruled  # it rules the latest result, which the line follows
    assert ruled["conflict"] == {"kind": "contract", "interface": "iface.drive", "quantity": "v"}
    assert ruled["standing"] == {"gate_refused": False, "counted_before": 0, "attempt_left": True}
    assert ruled["level"] == "queue"
    assert ruled["wanted"] == value("iface.drive", "v", 12, "V", 1)
    assert ruled["found"] == [value("fw.main", "v", 11, "V", 4)]
    # A node's free-text provenance is never on the line.
    assert "brief" not in json.dumps(ruled) and "written_by" not in json.dumps(ruled)
    assert set(raised) - {"seq", "ts", "run_id", "gate_mode"} == {"kind", "item_id"}
    assert raised["item_id"] == ITEM
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    assert (item.source, item.subtask_id, item.run_id) == ("contract", "contract", "run-1")
    assert refusal(rows) is None


def test_the_contract_item_says_what_failed_from_the_record_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11)
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    head = next(row for row in lines(rig) if row["kind"] == "contract_tested")["commit"]
    assert item.decision_required == (
        'The interface contract of module "drive" (producer, subtask "drive-0a1b2c") to module '
        '"fw" (consumer, subtask "fw-3d4e5f") failed after both merged. The interfaces are fixed '
        "at decomposition, and no run changes them. The consumer's nodes deviate from the "
        "interface. "
        "Decide whose merged work stands: choose producer or choose consumer. In this build a "
        "choice is recorded, and no merged module is reopened."
    )
    assert item.triggering_finding == (
        'Interface "iface.drive", quantity "v": the interface holds 12 "volt" (revision 1); node '
        '"fw.main" holds 11 "volt" (revision 4). Ruled for a person.'
    )
    assert item.quantities == (QuantityRef(node_id="iface.drive", name="v", value=12, unit="V"),)
    assert item.artefact_diff == (
        f"The run branch from {SPAN} to {head}: see `git diff {SPAN} {head}` in the target "
        "repository."
    )
    streams = rig.run_dir / "sessions"
    assert item.trajectories == tuple(
        str(streams / s / "stdout.jsonl") for s in ("sess-1", "sess-2")
    )
    # A run that records only lists it with no consequence.
    assert item.consequence is None


def test_an_interface_with_no_quantity_a_side_never_joined_is_one_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = {**IFACE_DRIVE, "quantities": {}}
    alone = node("fw.main", "firmware", "iface.tilt", v=12, period=10)
    rig = ran(tmp_path, monkeypatch, interfaces=(bare, IFACE_TILT), writes={FW: [alone]})
    rows = lines(rig)
    at = failed_at(rows)
    ruled = rows[at + 1]
    assert ruled["kind"] == "contract_ruled"
    assert ruled["conflict"] == {"kind": "contract", "interface": "iface.drive", "quantity": None}
    assert (ruled["wanted"], ruled["found"], ruled["level"]) == (None, [], "queue")
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    assert item.triggering_finding == (
        'Interface "iface.drive" has no quantity, and the consumer is not joined to it. Ruled for '
        "a person."
    )
    assert refusal(rows) is None


class NamingGate(FakeGate):
    """Under ``observe``, fw's attempt fails naming its own node's ``v``."""

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.seen.append(artefact)
        if artefact.subtask_id != FW:
            return super().check(artefact, mode=mode)
        named = QuantityRef(node_id="fw.main", name="v", value=11, unit="V")
        return failing_gate_result(mode).model_copy(update={"quantities": (named,)})


def test_a_clause_the_merging_attempt_s_gate_named_is_the_gate_s_and_raises_no_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11, gate_mode="observe", gate=NamingGate())
    rows = lines(rig)
    at = failed_at(rows)
    ruled = rows[at + 1]
    assert (ruled["kind"], ruled["level"]) == ("contract_ruled", "gate")
    assert ruled["standing"]["gate_refused"] is True
    assert "contract_item_raised" not in kinds(rows)
    assert not [i for i in read_queue(rig.run_dir).items if i.source == "contract"]
    assert refusal(rows) is None


def test_a_pair_has_one_undecided_item_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sizing's opening pass breaks drive's interface, and its closing pass leaves it broken: the
    # second failure is ruled, and the item already open stands for it.
    low = node("budget.supply", "sizing", "iface.drive", v=11)
    rig = ran(tmp_path, monkeypatch, sizing=True, closing_volts=11, writes={BUDGET: [low]})
    rows = lines(rig)
    failed = [
        r for r in rows if r["kind"] == "contract_tested" and r["result"]["outcome"] == "fail"
    ]
    assert [r["result"]["pair"] for r in failed] == [json.loads(P_BUDGET.model_dump_json())] * 2
    # Each failed result is followed by its ruling.
    assert [rows[r["seq"] + 1]["kind"] for r in failed] == ["contract_ruled"] * 2
    assert [
        r["counted_before"] for r in (x["standing"] for x in rows if x["kind"] == "contract_ruled")
    ] == [0, 1]
    raised = [r for r in rows if r["kind"] == "contract_item_raised"]
    assert [(r["item_id"], r["seq"]) for r in raised] == [(ITEM, failed[0]["seq"] + 2)]
    assert refusal(rows) is None


# --- what replay refuses ------------------------------------------------------------------------


def test_replay_refuses_a_ruling_or_an_item_the_record_does_not_give(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = lines(ran(tmp_path, monkeypatch, fw_volts=11))
    at = failed_at(rows)
    head, ruled, raised = rows[: at + 1], rows[at + 1], rows[at + 2]

    def said(*tail: dict[str, Any]) -> str:
        why = refusal([*head, *tail])
        assert why is not None
        return why

    period = {
        "conflict": ruled["conflict"] | {"quantity": "period"},
        "wanted": value("iface.drive", "period", 10, "ms", 1),
        "found": [value("fw.main", "period", 10, "ms", 4)],
    }
    assert "ruled next" in said(ruled | period)
    assert "standing" in said(ruled | {"standing": ruled["standing"] | {"attempt_left": False}})
    assert "level" in said(ruled | {"level": "gate"})
    assert "level" in said(ruled | {"level": "sizing"})
    assert "nodes" in said(ruled | {"found": []})
    moved = [value("fw.main", "v", 11, "V", 3)]
    assert "revision" in said(ruled | {"found": moved})
    assert "revision" in said(ruled | {"wanted": value("iface.drive", "v", 12, "V", 9)})
    # Nothing else follows a failed result before its rulings and its item.
    assert "rulings and its item" in said(rows[at + 3])
    assert "rulings and its item" in said(ruled, rows[at + 3])
    # An item that is not the pair's next, or that no ruling sent to a person.
    assert "item" in said(ruled, raised | {"item_id": "run-1-contract-2"})
    assert "item" in said(ruled, raised | {"item_id": f"{ITEM}-r2"})
    gate_ruled = ruled | {"level": "gate", "standing": ruled["standing"] | {"gate_refused": True}}
    assert said(gate_ruled, raised) is not None
    # A ruling where none is owed: after the item, or in a run whose results all passed.
    assert "none is owed" in said(ruled, raised, ruled)


# --- kills --------------------------------------------------------------------------------------


def first_of(kind: str) -> Callable[[Event, list[Event]], bool]:
    return lambda event, _: event.kind == kind


@pytest.mark.parametrize(
    "kind", ["contract_ruled", "contract_item_raised"], ids=["before the ruling", "before the item"]
)
def test_a_kill_on_the_way_to_the_item_resumes_to_the_uninterrupted_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    reference = ran(tmp_path / "reference", monkeypatch, fw_volts=11, declared=(DRIVE, FW))
    rig = ran(tmp_path / "cut", monkeypatch, fw_volts=11, declared=(DRIVE, FW), kill=first_of(kind))
    assert kind not in kinds(lines(rig))
    assert resumed(rig, monkeypatch, declared=(DRIVE, FW)) == "done"
    events = read_events(rig.run_dir / "events.jsonl")
    # The same lines, each run's streams under its own directory.
    ours = json.dumps(comparable(events), default=str).replace(str(rig.run_dir), "RUN")
    theirs = comparable(read_events(reference.run_dir / "events.jsonl"))
    assert ours == json.dumps(theirs, default=str).replace(str(reference.run_dir), "RUN")
    # The item is listed once, however often the process got to it.
    assert [i.item_id for i in read_queue(rig.run_dir).items] == [ITEM]


def test_a_ruling_rewritten_before_its_item_halts_and_raises_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11, kill=first_of("contract_item_raised"))
    path = rig.run_dir / "events.jsonl"
    raw = path.read_bytes().splitlines()
    rows = [json.loads(line) for line in raw]
    at = next(i for i, row in enumerate(rows) if row["kind"] == "contract_ruled")
    rows[at]["found"] = [value("fw.main", "v", 12, "V", 4)]
    raw[at] = json.dumps(rows[at]).encode()
    path.write_bytes(b"\n".join(raw) + b"\n")
    assert refusal(rows) is None  # the log alone cannot tell
    resumed(rig, monkeypatch)
    after = lines(rig)
    incident = next(row for row in after if row["kind"] == "incident")
    assert incident["cause"] == "foreign_journal_line"
    assert "contract_item_raised" not in kinds(after)
    # The item the killed process listed holds the journal's values, never the rewritten line's.
    (listed,) = read_queue(rig.run_dir).items
    assert 'node "fw.main" holds 11 "volt"' in listed.triggering_finding


# --- decisions on the item ----------------------------------------------------------------------


def acted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str, position: str | None) -> Rig:
    rig = ran(tmp_path, monkeypatch, acts=True, fw_volts=11, declared=(DRIVE, FW))
    decide(rig.run_dir, verb, position=position)
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    return rig


@pytest.mark.parametrize(
    ("verb", "position"),
    [("approve", None), ("reject", None), ("choose", "producer"), ("choose", "consumer")],
)
def test_approve_and_reject_on_a_contract_item_still_record_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str, position: str | None
) -> None:
    rig = acted(tmp_path, monkeypatch, verb, position)
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    consequence = item.consequence
    assert consequence is not None
    assert (consequence.on_approve, consequence.on_reject, consequence.why_record_only) == (
        "record_only",
        "record_only",
        "source",
    )
    assert (consequence.attempt, consequence.attempt_commit) == (None, None)
    assert consequence.on_choose == {"producer": "record_only", "consumer": "record_only"}
    rows = lines(rig)
    taken = [row for row in rows if row["kind"] == "decision_taken"]
    assert len(taken) == 1
    line = taken[0]
    assert (line["subtask_id"], line["item_id"], line["verb"]) == (None, ITEM, verb)
    assert (line["effect"], line["acts"], line["why_not"]) == ("none", False, "record_only_source")
    assert line.get("position") == position
    # Nothing was dispatched again, and nothing was reopened.
    assert kinds(rows).count("subtask_planned") == 3
    assert refusal(rows) is None


def test_a_choice_is_held_to_the_positions_its_item_offers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, acts=True, fw_volts=11, declared=(DRIVE, FW))
    with pytest.raises(QueueError):
        decide(rig.run_dir, "choose", position="sizing")
    decide(rig.run_dir, "choose", position="consumer")
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    rows = lines(rig)
    at = next(i for i, row in enumerate(rows) if row["kind"] == "decision_taken")
    for other in ("sizing", "domain"):
        why = refusal([*rows[:at], rows[at] | {"position": other}])
        assert why is not None and "of a position it offers" in why, why


def test_a_rewritten_contract_item_halts_at_take(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, acts=True, fw_volts=11, declared=(DRIVE, FW))
    path = rig.run_dir / "queue.jsonl"
    raw = path.read_bytes().splitlines()
    at = next(i for i, line in enumerate(raw) if json.loads(line)["item_id"] == ITEM)
    item = QueueItem.model_validate_json(raw[at])
    rewritten = item.model_copy(update={"triggering_finding": "the producer is wrong; reopen it"})
    raw[at] = rewritten.model_dump_json().encode()
    path.write_bytes(b"\n".join(raw) + b"\n")
    decide(rig.run_dir, "choose", position="producer")
    resumed(rig, monkeypatch, declared=(DRIVE, FW))
    rows = lines(rig)
    incident = next(row for row in rows if row["kind"] == "incident")
    assert incident["cause"] == "queue_item_mismatch"
    assert "decision_taken" not in kinds(rows)


def test_the_scanned_sources_are_unchanged() -> None:
    # A choice on a contract item merges nothing: the scan before review stays where it was.
    assert (
        frozenset(
            {
                "review_unavailable",
                "review_blocked",
                "repair_budget_exhausted",
                "escalation_decision",
            }
        )
        == SCANNED_SOURCES
    )


# --- no open item -------------------------------------------------------------------------------


@pytest.mark.parametrize("acts", [False, True], ids=["records", "acts"])
def test_a_module_is_not_complete_while_an_item_about_its_pair_is_undecided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acts: bool
) -> None:
    # Sizing's opening pass breaks drive's interface; its closing pass mends it, so the pair's
    # latest result passes while its item is still open.
    low = node("budget.supply", "sizing", "iface.drive", v=11)
    declared = (BUDGET, DRIVE, FW)
    rig = ran(
        tmp_path, monkeypatch, acts=acts, sizing=True, declared=declared, writes={BUDGET: [low]}
    )
    rows = lines(rig)
    assert [r["result"]["outcome"] for r in rows if r["kind"] == "contract_tested"][-1] == "pass"
    completed = [r["subtask_id"] for r in rows if r["kind"] == "module_completed"]
    assert completed == [FW]
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    for module in (BUDGET, DRIVE):
        assert dict(open_preconditions(state, module))["open_item"] == (
            f"queue item {ITEM} about drive to budget has no decision taken"
        )
    assert "contract" not in dict(open_preconditions(state, DRIVE))
    # A person's decision, recorded even where it acts on nothing, closes it.
    decide(rig.run_dir, "approve")
    assert resumed(rig, monkeypatch, declared=declared) == "done"
    rows = lines(rig)
    assert [r["subtask_id"] for r in rows if r["kind"] == "module_completed"] == [FW, BUDGET, DRIVE]
    assert refusal(rows) is None


def test_the_open_item_precondition_is_registered_after_the_contract_s() -> None:
    names = [p.name for p in completion.PRECONDITIONS]
    assert names == ["merged", "system_scope", "contract", "open_item"]


# --- the decision sequence ----------------------------------------------------------------------


def test_the_decision_sequence_carries_each_ruling_and_the_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ran(tmp_path, monkeypatch, fw_volts=11)
    steps = [s for s in decisions(lines(rig)) if s["step"] in ("contract_ruled", "contract_item")]
    assert steps == [
        {
            "step": "contract_ruled",
            "seq": steps[0]["seq"],
            "interface": "iface.drive",
            "quantity": "v",
            "level": "queue",
        },
        {"step": "contract_item", "seq": steps[1]["seq"], "item_id": ITEM},
    ]


def test_a_choice_on_an_arbitration_item_is_held_to_its_positions_now_another_set_exists(
    tmp_path: Path,
) -> None:
    from arbitration_runs import driven, resume
    from test_a_person_chooses_a_position_only_on_an_arbitration_item import chose
    from test_choosing_the_domain_s_value_waits_for_the_closing_pass_and_returns_to_the_gate import (  # noqa: E501
        at_the_item,
    )

    rig = at_the_item(tmp_path)
    chose(rig.run_dir, "sizing")
    driven(rig, resume)
    rows = lines(rig)
    at = next(i for i, row in enumerate(rows) if row["kind"] == "decision_taken")
    assert refusal(rows) is None
    for other in ("producer", "consumer"):
        why = refusal([*rows[:at], rows[at] | {"position": other}])
        assert why is not None and "of a position it offers" in why, why


def test_no_session_s_words_reach_the_contract_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # fw's node carries its provenance as free text, and its value in a unit word no registry
    # defines, which the clause's own reason quotes on the result's line.
    worded = node("fw.main", "firmware", "iface.drive", "iface.tilt", v=12, period=10)
    worded["quantities"]["v"] |= {
        "unit": "UNITCANARY",
        "source": "SOURCE-CANARY datasheet",
        "written_by": "WRITER-CANARY firmware pass",
    }
    rig = ran(tmp_path, monkeypatch, acts=True, writes={FW: [worded]})
    rows = lines(rig)
    at = failed_at(rows)
    ruled = rows[at + 1]
    assert (ruled["kind"], ruled["found"][0]["position"]["unit"]) == (
        "contract_ruled",
        "UNITCANARY",
    )
    queue = (rig.run_dir / "queue.jsonl").read_text()
    assert ITEM in queue
    for canary in ("UNITCANARY", "SOURCE-CANARY", "WRITER-CANARY"):
        assert canary not in queue, canary
        assert canary not in json.dumps(ruled) or canary == "UNITCANARY", canary
    item = next(i for i in read_queue(rig.run_dir).items if i.item_id == ITEM)
    assert 'node "fw.main" holds 12, in a unit the gate\'s parser refuses (revision 4)' in (
        item.triggering_finding
    )
    assert item.quantities == (QuantityRef(node_id="iface.drive", name="v", value=12, unit="V"),)
