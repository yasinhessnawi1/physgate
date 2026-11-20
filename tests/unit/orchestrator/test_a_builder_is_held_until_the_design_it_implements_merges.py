"""A module that builds what another designs is held until the designer's node has merged.

The shape of a run whose plan ordered control before firmware and had firmware run exactly what
control wrote on control's own node, with no interface between them in that direction: control
was rejected three times and went to a person, and firmware was dispatched anyway, with nothing to
build against. Under the recorded design pairs the builder's dispatch is held instead, on a line
of its own naming the designer, its node, why, and the item a person can act on; the run waits on
the queue when nothing else can run. A person's approve merges the designer and lets the builder
go, on a release line, against the merged design. A person's reject ends the designer unmerged:
the builder stays held, on a line saying so, is never run and never failed, and the integration
call names it among the subtasks that did not merge. A person's reject of a blocked review orders
the designer's one fix: the hold stands through it, and is let go on the fix's merge; a fix not
accepted ends the designer, and a new hold line says so; a fix sent to a person again moves the
hold to the new item, on a line of its own. A run that records only holds the builder as well.
A kill at the hold resumes to the lines of the uninterrupted run, a replay refuses a builder
dispatched without the line it owed, and a run recorded without design pairs dispatches as it
always did.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import loop_fakes
import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeDispatcher, KilledError, Rig
from orch_helpers import ticking_clock
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of, requests_of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    DRIVE,
    FW,
    IFACE_DRIVE,
    IFACE_TILT,
    INTEG,
    comparable,
    entry,
    hooked,
    node,
    rig_for,
    side,
)
from test_a_queue_decision_acts_at_a_boundary import NO_VERDICT, _layer, decide
from test_a_usage_limit_is_its_own_cause_and_the_run_waits_for_its_reset import (
    NOON,
    RESETS,
    LimitDispatcher,
)
from test_design_pairs_are_read_from_the_plan_and_recorded_before_any_dispatch import balancer

from physgate import roles
from physgate.contracts.pairs import ContractPair
from physgate.orchestrator.design_pairs import DesignPair, plan_design_pairs, plan_mutual_namings
from physgate.orchestrator.design_wait import held_builders, open_holds
from physgate.orchestrator.events import read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import replay
from physgate.orchestrator.usage_limit import UsageLimit
from physgate.oslayer.probe import Present
from physgate.state.store import journal_records_after

ACTS = {
    "queue_decisions": "act",
    "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
}
#: The designer's three attempts fail review: it has no attempt left and goes to a person.
SPENT = ["fail", "fail", "fail"]
#: The designer's own node, which the builder's specification names as the design it runs.
LAW = "drive.law"
#: drive designs on ``drive.law``; fw runs it. The one interface between them goes the other way
#: (drive reads fw's ``iface.tilt``), so no reader's wait holds fw on drive.
DESIGN = DesignPair(designer=DRIVE, builder=FW, nodes=(LAW,))
P_TILT = ContractPair(
    producer=side(FW, "firmware"), consumer=side(DRIVE, "control"), interfaces=("iface.tilt",)
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def begin(
    loop: Loop,
    *,
    design: bool = True,
    pairs: tuple[DesignPair, ...] = (DESIGN,),
    mutual: tuple[DesignPair, ...] = (),
) -> None:
    """drive, then fw, then integration; fw builds what drive designs where ``design`` is set.

    ``pairs`` are the design pairs the opening records where ``design`` is set, and ``mutual``
    the namings the other way round written beside them.
    """
    plan = [entry(DRIVE, "control", "drive"), entry(FW, "firmware", "fw")]
    plan.append(entry(INTEG, "integration", "integration"))
    requirement = '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
    head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
    summary = DecompositionSummary(
        session_id="decomposition",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.tilt",),
        spec_commit="e" * 40,
        head_revision=head,
        interface_consumers=(InterfaceConsumers(interface="iface.tilt", consumers=("drive",)),),
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=(P_TILT,),
        design_pairs=pairs if design else None,
        design_mutual=mutual or None,
    )
    loop.record.start(plan, decomposed=summary)


def rigged(tmp_path: Path, *, acts: bool = True, dispatcher: FakeDispatcher | None = None) -> Rig:
    sessions = tmp_path / "run" / "sessions"
    rig = rig_for(
        tmp_path,
        interfaces=(IFACE_DRIVE, IFACE_TILT),
        dispatcher=dispatcher or FakeDispatcher(trajectories=sessions),
    )
    rig.diff.writes.update(  # type: ignore[attr-defined]
        {
            DRIVE: [node(LAW, "control", "iface.tilt", period=10)],
            FW: [node("fw.main", "firmware", "iface.tilt", period=10)],
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
    design: bool = True,
    pairs: tuple[DesignPair, ...] = (DESIGN,),
    mutual: tuple[DesignPair, ...] = (),
    kill: Callable[[Any, list[Any]], bool] | None = None,
) -> str:
    """The first process, until it stops: the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW), kill=kill)
    begin(loop, design=design, pairs=pairs, mutual=mutual)
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
    kill: Callable[[Any, list[Any]], bool] | None = None,
) -> str:
    """A fresh process takes the run over; the step it stopped at, ``killed``, or what escaped."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW), kill=kill)
    _layer(loop)
    try:
        return loop.resume().kind
    except KilledError:
        return "killed"
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding, asserted as a step
        return f"raised {exc!r}"
    finally:
        loop.close()


def drive_item(rows: list[dict[str, Any]]) -> str:
    (line,) = of(rows, "escalated", subtask_id=DRIVE)
    return str(line["item_id"])


def index_of(rows: list[dict[str, Any]], kind: str, **match: Any) -> int:  # noqa: ANN401
    return next(
        i
        for i, r in enumerate(rows)
        if r["kind"] == kind and all(r.get(k) == v for k, v in match.items())
    )


def dispatched_at(rows: list[dict[str, Any]], subtask: str) -> int:
    return index_of(rows, "stage_entered", subtask_id=subtask, stage="resolve")


def _at(kind: str) -> Callable[[Any, list[Any]], bool]:
    def pick(event: Any, written: list[Any]) -> bool:  # noqa: ANN401 - any line
        return bool(event.kind == kind)

    return pick


# --- the designer escalates: the builder is held ------------------------------------------------


def test_a_designer_with_a_person_holds_its_builder_and_the_run_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch) == "wait"
    rows = lines(rig)
    item = drive_item(rows)
    # The design pairs are on the record before anything is dispatched.
    (planned,) = of(rows, "design_pairs_planned")
    assert planned["pairs"] == [{"designer": DRIVE, "builder": FW, "nodes": [LAW]}]
    assert rows.index(planned) < dispatched_at(rows, DRIVE)
    # fw is never dispatched; one hold line stands where its dispatch would have.
    assert requests_of(rig, FW) == []
    assert of(rows, "stage_entered", subtask_id=FW) == []
    (held,) = of(rows, "builder_held")
    assert (held["subtask_id"], held["designer"], held["nodes"]) == (FW, DRIVE, [LAW])
    assert (held["why"], held["item_id"]) == ("escalated", item)
    assert index_of(rows, "escalated", subtask_id=DRIVE) < rows.index(held)
    # Not failed: no rejection, no escalation of fw, and no integration call yet.
    assert of(rows, "attempt_rejected", subtask_id=FW) == []
    assert of(rows, "escalated", subtask_id=FW) == []
    assert of(rows, "integration_gate_ran") == of(rows, "integration_gate_skipped") == []
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    step = state.next_step()
    assert (step.kind, step.subtask_id) == ("wait", FW)
    assert state.subtasks[FW].status == "planned"
    assert [(h.subtask_id, h.designer, h.why) for h in open_holds(state)] == [
        (FW, DRIVE, "escalated")
    ]
    # The run's status says so: what it prints, and what the operator page reads.
    held_now = {"subtask_id": FW, "designer": DRIVE, "nodes": (LAW,), "why": "escalated"}
    assert held_builders(state) == {"held": [{**held_now, "item_id": item}]}
    assert refusal(rows) is None


def test_taken_over_with_nothing_decided_the_run_waits_again_and_writes_no_second_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch) == "wait"
    assert resumed(rig, monkeypatch) == "wait"
    rows = lines(rig)
    assert len(of(rows, "builder_held")) == 1
    assert requests_of(rig, FW) == []
    assert refusal(rows) is None


# --- the designer merges after a decision: the builder runs on the merged design -----------------


def test_the_designer_merged_after_an_approve_and_the_builder_then_runs_on_its_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    merged_when_fw_spawned: list[list[str]] = []
    # drive's three calls, then fw's: at fw's spawn the run branch holds drive's merge.
    rig.dispatcher.during[4] = lambda: merged_when_fw_spawned.append(
        [m[0] for m in rig.merger.merges]
    )
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    (released,) = of(rows, "builder_released")
    assert (released["subtask_id"], released["designer"], released["nodes"]) == (FW, DRIVE, [LAW])
    merge = index_of(rows, "merged", subtask_id=DRIVE)
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, INTEG]
    assert merged_when_fw_spawned == [[DRIVE]]
    assert open_holds(replay(read_events(rig.run_dir / "events.jsonl"))) == []
    assert held_builders(replay(read_events(rig.run_dir / "events.jsonl"))) == {}
    assert refusal(rows) is None


#: The last run's two specifications, cut to the words that say one module runs what the other
#: designs: control's own node, which firmware's specification names as the design it implements.
CONTROL_SPEC = (
    "Design the balance controller. The firmware module implements the design. It runs after "
    "this module and reads the design from the node this module writes.\n\n"
    "## Design node written by this module\n`control.balance_design` (domain control, owner "
    "control) is this module's own node. It holds every coefficient of the controller the "
    "firmware is to run. The firmware module's acceptance criteria compare the firmware with "
    "this node.\n\n## Acceptance criteria\n\n1. It holds.\n"
)
FIRMWARE_SPEC = (
    "Run the balance controller designed by the control module. This module implements the "
    "design on `control.balance_design` and designs no controller of its own.\n"
    "- Produces `firmware.loop_io`.\n"
    "- Reads `control.balance_design` (from control) as merged: controller coefficients.\n\n"
    "## Acceptance criteria\n\n1. The coefficients the firmware runs equal those on "
    "`control.balance_design` as merged.\n"
)


def test_the_last_run_s_plan_holds_firmware_while_control_waits_and_runs_it_on_control_s_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pair is read from the plan's own words, as the decomposition reads it, not written in.
    plan = balancer(control=CONTROL_SPEC, firmware=FIRMWARE_SPEC)
    subtask = {"sizing": "sizing-000000", "control": DRIVE, "firmware": FW}
    found = plan_design_pairs(plan, subtask, ("sizing", "control", "firmware"))
    assert found == (DesignPair(designer=DRIVE, builder=FW, nodes=("control.balance_design",)),)
    rig = rigged(tmp_path)
    # Control is rejected three times and goes to a person: firmware is held, never dispatched.
    assert first_run(rig, monkeypatch, pairs=found) == "wait"
    rows = lines(rig)
    (held,) = of(rows, "builder_held")
    assert (held["subtask_id"], held["designer"], held["nodes"]) == (
        FW,
        DRIVE,
        ["control.balance_design"],
    )
    assert (held["why"], held["item_id"]) == ("escalated", drive_item(rows))
    assert requests_of(rig, FW) == []
    assert of(rows, "stage_entered", subtask_id=FW) == []
    # A person approves: control merges, and only then is firmware let go and dispatched.
    decide(rig.run_dir, "approve", item_id=drive_item(rows))
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    (released,) = of(rows, "builder_released")
    merge = index_of(rows, "merged", subtask_id=DRIVE)
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, INTEG]
    assert refusal(rows) is None


@pytest.mark.parametrize("first", ["control", "firmware"])
def test_two_modules_naming_each_other_s_node_hold_and_release_as_a_plain_pair_in_plan_order(
    first: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control also reads a node of firmware's own: no order could satisfy a refusal, so the pair
    # follows the plan's order, in either order, and the later one's own node, named by the
    # earlier, holds nothing. The module listed first is the rig's first-dispatched subtask.
    control = CONTROL_SPEC + "It reads `firmware.timing`, the firmware module's own node.\n"
    firmware = FIRMWARE_SPEC + "`firmware.timing` is this module's own node: the loop's period.\n"
    plan = balancer(control=control, firmware=firmware)
    later = "firmware" if first == "control" else "control"
    own = {"control": ("control.balance_design",), "firmware": ("firmware.timing",)}
    subtask = {"sizing": "sizing-000000", first: DRIVE, later: FW}
    order = ("sizing", first, later)
    found = plan_design_pairs(plan, subtask, order)
    assert found == (DesignPair(designer=DRIVE, builder=FW, nodes=own[first]),)
    crossed = plan_mutual_namings(plan, subtask, order)
    assert crossed == (DesignPair(designer=FW, builder=DRIVE, nodes=own[later]),)
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch, pairs=found, mutual=crossed) == "wait"
    rows = lines(rig)
    (planned,) = of(rows, "design_pairs_planned")
    assert planned["pairs"] == [{"designer": DRIVE, "builder": FW, "nodes": list(own[first])}]
    assert planned["mutual"] == [{"designer": FW, "builder": DRIVE, "nodes": list(own[later])}]
    # The first is dispatched and held by nothing; the later is held on the first's design.
    (held,) = of(rows, "builder_held")
    assert (held["subtask_id"], held["designer"], held["why"]) == (FW, DRIVE, "escalated")
    assert of(rows, "builder_held", subtask_id=DRIVE) == []
    assert requests_of(rig, FW) == []
    decide(rig.run_dir, "approve", item_id=drive_item(rows))
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    (released,) = of(rows, "builder_released")
    assert released["subtask_id"] == FW
    assert index_of(rows, "merged", subtask_id=DRIVE) < rows.index(released)
    assert rows.index(released) < dispatched_at(rows, FW)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, INTEG]
    assert refusal(rows) is None


# --- the designer ends without a merge: the builder stays held, and the run goes on -------------


def test_the_designer_ended_unmerged_and_the_builder_is_held_not_run_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch) == "wait"
    item = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "no attempt is left", item_id=item)
    step = resumed(rig, monkeypatch)
    rows = lines(rig)
    assert of(rows, "subtask_rejected", subtask_id=DRIVE) != []
    # A second hold line says why it holds now; nothing releases it.
    holds = of(rows, "builder_held")
    assert [(h["why"], h.get("item_id")) for h in holds] == [
        ("escalated", item),
        ("ended_unmerged", None),
    ]
    assert "item_id" not in holds[1]
    assert index_of(rows, "subtask_rejected", subtask_id=DRIVE) < rows.index(holds[1])
    assert of(rows, "builder_released") == []
    # Never run, never failed: no dispatch of fw, no rejection or escalation of it.
    assert requests_of(rig, FW) == []
    assert of(rows, "stage_entered", subtask_id=FW) == []
    assert of(rows, "attempt_rejected", subtask_id=FW) == of(rows, "escalated", subtask_id=FW)
    assert of(rows, "escalated", subtask_id=FW) == []
    # The run goes on to its integration call, which names fw among what did not merge.
    (skipped,) = of(rows, "integration_gate_skipped")
    assert skipped["reason"] == "not_all_merged"
    assert skipped["subtasks"] == [DRIVE, FW]
    assert rows.index(holds[1]) < rows.index(skipped)
    assert step == "done"
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert state.subtasks[FW].status == "planned"
    assert [(h.subtask_id, h.why) for h in open_holds(state)] == [(FW, "ended_unmerged")]
    assert refusal(rows) is None


def test_a_run_that_records_only_holds_the_builder_and_goes_on_to_its_integration_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path, acts=False)
    step = first_run(rig, monkeypatch)
    rows = lines(rig)
    (held,) = of(rows, "builder_held")
    assert (held["why"], held["item_id"]) == ("escalated", drive_item(rows))
    assert requests_of(rig, FW) == []
    (skipped,) = of(rows, "integration_gate_skipped")
    assert skipped["subtasks"] == [DRIVE, FW]
    assert step != "wait"
    assert refusal(rows) is None


# --- a chain of pairs: a builder whose designer is itself held for good is held for good -------

#: A third module, which builds what fw designs on fw's own node: drive designs for fw, fw for it.
THIRD = "third-7a8b9c"
FW_LAW = "fw.law"
CHAINED = (DESIGN, DesignPair(designer=FW, builder=THIRD, nodes=(FW_LAW,)))


def chained(tmp_path: Path, *, acts: bool = True, dispatcher: FakeDispatcher | None = None) -> Rig:
    """drive, fw, third and integration: drive designs for fw, and fw for third where paired."""
    rig = rigged(tmp_path, acts=acts, dispatcher=dispatcher)
    rig.diff.writes[THIRD] = [  # type: ignore[attr-defined]
        node("third.main", "firmware", "iface.tilt", period=10)
    ]
    return rig


def chain_run(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    resume: bool = False,
    kill: Callable[[Any, list[Any]], bool] | None = None,
    pairs: tuple[DesignPair, ...] = CHAINED,
) -> str:
    """The first process over the chained plan, or a fresh one taking it over.

    ``pairs`` are the design pairs the opening records; with :data:`DESIGN` alone, third is a
    module no pair holds.
    """
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW, THIRD), kill=kill)
    if not resume:
        plan = [entry(DRIVE, "control", "drive"), entry(FW, "firmware", "fw")]
        plan += [entry(THIRD, "firmware", "third"), entry(INTEG, "integration", "integration")]
        requirement = (
            '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
        )
        summary = DecompositionSummary(
            session_id="decomposition",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(plan),
            interface_nodes=("iface.tilt",),
            spec_commit="e" * 40,
            head_revision=journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev,
            interface_consumers=(InterfaceConsumers(interface="iface.tilt", consumers=("drive",)),),
            system_requirements=(SystemRequirement.model_validate_json(requirement),),
            contract_pairs=(P_TILT,),
            design_pairs=pairs,
        )
        loop.record.start(plan, decomposed=summary)
    if rig.config_overrides.get("queue_decisions") == "act":
        _layer(loop)
    try:
        return (loop.resume() if resume else loop.run()).kind
    except KilledError:
        return "killed"
    except Exception as exc:  # noqa: BLE001 - what escaped is the finding, asserted as a step
        return f"raised {exc!r}"
    finally:
        loop.close()


def test_a_designer_ended_unmerged_holds_the_builder_of_its_builder_for_good_naming_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path)
    assert chain_run(rig, monkeypatch) == "wait"
    rows = lines(rig)
    item = drive_item(rows)
    # While drive is with a person, fw waits on its item and third on fw, which has not merged.
    assert [(h["subtask_id"], h["why"], h.get("item_id")) for h in of(rows, "builder_held")] == [
        (FW, "escalated", item),
        (THIRD, "not_merged", None),
    ]
    decide(rig.run_dir, "reject", "no attempt is left", item_id=item)
    assert chain_run(rig, monkeypatch, resume=True) == "done"
    rows = lines(rig)
    holds = of(rows, "builder_held")
    # drive ended unmerged: fw is held for good, and so is third, on a line naming the chain.
    assert [(h["subtask_id"], h["why"], h.get("chain")) for h in holds] == [
        (FW, "escalated", None),
        (THIRD, "not_merged", None),
        (FW, "ended_unmerged", None),
        (THIRD, "designer_held", [FW, DRIVE]),
    ]
    assert (holds[3]["designer"], holds[3]["nodes"]) == (FW, [FW_LAW])
    assert requests_of(rig, FW) == requests_of(rig, THIRD) == []
    assert of(rows, "builder_released") == []
    (skipped,) = of(rows, "integration_gate_skipped")
    assert skipped["subtasks"] == [DRIVE, FW, THIRD]
    assert rows.index(holds[3]) < rows.index(skipped)
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    held_third = [h for h in held_builders(state)["held"] if h["subtask_id"] == THIRD]
    assert [h.get("chain") for h in held_third] == [(FW, DRIVE)]
    assert refusal(rows) is None


def test_a_run_that_records_only_holds_a_chain_for_good_and_goes_on_to_its_integration_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path, acts=False)
    step = chain_run(rig, monkeypatch)
    rows = lines(rig)
    item = drive_item(rows)
    holds = of(rows, "builder_held")
    assert [(h["subtask_id"], h["why"], h.get("item_id"), h.get("chain")) for h in holds] == [
        (FW, "escalated", item, None),
        (THIRD, "designer_held", None, [FW, DRIVE]),
    ]
    assert requests_of(rig, FW) == requests_of(rig, THIRD) == []
    (skipped,) = of(rows, "integration_gate_skipped")
    assert skipped["subtasks"] == [DRIVE, FW, THIRD]
    assert step != "wait"
    assert not step.startswith("raised")
    assert refusal(rows) is None


def test_a_chain_is_let_go_link_by_link_as_each_designer_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path)
    assert chain_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert chain_run(rig, monkeypatch, resume=True) == "done"
    rows = lines(rig)
    released = of(rows, "builder_released")
    assert [(r["subtask_id"], r["designer"]) for r in released] == [(FW, DRIVE), (THIRD, FW)]
    assert index_of(rows, "merged", subtask_id=FW) < rows.index(released[1])
    assert rows.index(released[1]) < dispatched_at(rows, THIRD)
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [FW, THIRD, INTEG]
    assert refusal(rows) is None


def test_a_hold_naming_another_chain_than_the_record_owes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path, acts=False)
    chain_run(rig, monkeypatch)
    rows = lines(rig)
    at = index_of(rows, "builder_held", subtask_id=THIRD)
    for edit in ({"chain": [FW, "drive-000000"]}, {"chain": None, "why": "not_merged"}):
        changed = {k: v for k, v in {**rows[at], **edit}.items() if v is not None}
        assert "than the record owes" in str(refusal([*rows[:at], changed]))


# --- the account's usage limit halts the run while a builder is held ----------------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The instant every loop the rig opens next starts its clock at: noon in Oslo first."""
    start = [NOON]
    monkeypatch.setattr(loop_fakes, "ticking_clock", lambda: ticking_clock(start[0]))
    return start


def limited_on(call: int, tmp_path: Path) -> LimitDispatcher:
    """A dispatcher whose session on ``call`` ends on the account's usage limit."""
    return LimitDispatcher(
        trajectories=tmp_path / "run" / "sessions",
        infra={call: "usage_limit"},
        limits={call: UsageLimit(resets=RESETS)},
    )


def test_a_usage_limit_halt_while_a_builder_is_held_resumes_to_the_same_hold_and_its_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[datetime]
) -> None:
    # drive goes to a person and fw is held; third, which no pair holds, runs and meets the limit.
    rig = chained(tmp_path, dispatcher=limited_on(4, tmp_path))
    assert chain_run(rig, monkeypatch, pairs=(DESIGN,)) == "halted"
    rows = lines(rig)
    item = drive_item(rows)
    (halt,) = of(rows, "halted")
    assert halt["reason"] == "usage_limit"
    (held,) = of(rows, "builder_held")
    assert (held["subtask_id"], held["why"], held["item_id"]) == (FW, "escalated", item)
    assert rows.index(held) < dispatched_at(rows, THIRD) < rows.index(halt)
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert [(h.subtask_id, h.why) for h in open_holds(state)] == [(FW, "escalated")]
    # A resume before the reset starts nothing; one after it finishes third and waits on drive.
    clock[0] = NOON + timedelta(hours=1)
    assert "LimitNotResetError" in chain_run(rig, monkeypatch, resume=True)
    assert len(rig.dispatcher.requests) == 4
    clock[0] = NOON + timedelta(hours=1, minutes=21)
    assert chain_run(rig, monkeypatch, resume=True) == "wait"
    rows = lines(rig)
    assert len(of(rows, "builder_held")) == 1, "the hold stands: no second line"
    assert [r.subtask_id for r in rig.dispatcher.requests] == [DRIVE] * 3 + [THIRD, THIRD]
    assert of(rows, "merged", subtask_id=THIRD) != []
    assert requests_of(rig, FW) == []
    # A person approves drive: it merges, and only then is fw let go and dispatched.
    decide(rig.run_dir, "approve", item_id=item)
    assert chain_run(rig, monkeypatch, resume=True) == "done"
    rows = lines(rig)
    (released,) = of(rows, "builder_released")
    merge = index_of(rows, "merged", subtask_id=DRIVE)
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert refusal(rows) is None


def test_a_usage_limit_halt_in_the_designer_s_fix_keeps_the_hold_until_the_fix_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: list[datetime]
) -> None:
    # drive's third review blocks; a reject orders its fix, whose session meets the limit.
    rig = rigged(tmp_path, dispatcher=limited_on(4, tmp_path))
    rig.reviewer.verdicts[:] = ["fail", "fail", "pass", "pass"]
    rig.reviewer.results[3] = blocked_review()
    assert first_run(rig, monkeypatch) == "wait"
    item = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "fix the law", item_id=item)
    assert resumed(rig, monkeypatch) == "halted"
    rows = lines(rig)
    assert [h["reason"] for h in of(rows, "halted")] == ["usage_limit"]
    assert [(h["why"], h.get("item_id")) for h in of(rows, "builder_held")] == [("escalated", item)]
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert [(h.subtask_id, h.why) for h in open_holds(state)] == [(FW, "escalated")]
    clock[0] = NOON + timedelta(hours=1, minutes=21)
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    assert len(of(rows, "builder_held")) == 1
    assert [(r.subtask_id, r.attempt, r.kind) for r in rig.dispatcher.requests] == [
        (DRIVE, 1, "attempt"),
        (DRIVE, 2, "attempt"),
        (DRIVE, 3, "attempt"),
        (DRIVE, 4, "fix"),
        (DRIVE, 4, "fix"),
        (FW, 1, "attempt"),
        (INTEG, 1, "attempt"),
    ]
    (released,) = of(rows, "builder_released")
    merge = index_of(rows, "merged", subtask_id=DRIVE)
    assert rows[merge]["attempt"] == 4
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert refusal(rows) is None


# --- a person orders the designer's one fix: the hold stands through it ---------------------------


def blocked_on_its_last_attempt(tmp_path: Path, *, fix: str) -> Rig:
    """The designer's third review blocks, so a reject orders its one fix, reviewed ``fix``."""
    rig = rigged(tmp_path)
    rig.reviewer.verdicts[:] = ["fail", "fail", "pass", fix]
    rig.reviewer.results[3] = blocked_review()
    return rig


def test_the_designer_s_fix_merges_and_only_then_is_the_builder_let_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = blocked_on_its_last_attempt(tmp_path, fix="pass")
    assert first_run(rig, monkeypatch) == "wait"
    item = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "fix the law", item_id=item)
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    # The fix runs while the hold stands: no second hold line, and fw waits for the fix's merge.
    assert [(h["why"], h.get("item_id")) for h in of(rows, "builder_held")] == [("escalated", item)]
    assert [(r.subtask_id, r.attempt, r.kind) for r in rig.dispatcher.requests] == [
        (DRIVE, 1, "attempt"),
        (DRIVE, 2, "attempt"),
        (DRIVE, 3, "attempt"),
        (DRIVE, 4, "fix"),
        (FW, 1, "attempt"),
        (INTEG, 1, "attempt"),
    ]
    (released,) = of(rows, "builder_released")
    merge = index_of(rows, "merged", subtask_id=DRIVE)
    assert rows[merge]["attempt"] == 4
    assert merge < rows.index(released) < dispatched_at(rows, FW)
    assert refusal(rows) is None


def test_a_fix_not_accepted_ends_the_designer_and_the_hold_says_so_with_no_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = blocked_on_its_last_attempt(tmp_path, fix="fail")
    assert first_run(rig, monkeypatch) == "wait"
    item = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "fix the law", item_id=item)
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    (ended,) = of(rows, "subtask_rejected", subtask_id=DRIVE)
    assert ended["by"] == "fix_not_accepted"
    holds = of(rows, "builder_held")
    assert [(h["why"], h.get("item_id")) for h in holds] == [
        ("escalated", item),
        ("ended_unmerged", None),
    ]
    assert rows.index(ended) < rows.index(holds[1])
    assert requests_of(rig, FW) == []
    assert of(rows, "builder_released") == of(rows, "attempt_rejected", subtask_id=FW) == []
    (skipped,) = of(rows, "integration_gate_skipped")
    assert skipped["subtasks"] == [DRIVE, FW]
    assert refusal(rows) is None


def test_the_fix_goes_to_a_person_again_and_the_hold_moves_to_the_new_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = blocked_on_its_last_attempt(tmp_path, fix="pass")
    rig.reviewer.unavailable.update({4: NO_VERDICT, 5: NO_VERDICT})
    assert first_run(rig, monkeypatch) == "wait"
    first = drive_item(lines(rig))
    decide(rig.run_dir, "reject", "fix the law", item_id=first)
    assert resumed(rig, monkeypatch) == "wait"
    rows = lines(rig)
    second = of(rows, "escalated", subtask_id=DRIVE)[-1]["item_id"]
    assert second != first
    # Why it holds is the same, the item a person can act on is not: a new line says so.
    holds = of(rows, "builder_held")
    assert [(h["why"], h["item_id"]) for h in holds] == [
        ("escalated", first),
        ("escalated", second),
    ]
    assert requests_of(rig, FW) == []
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    assert (state.next_step().kind, state.next_step().subtask_id) == ("wait", FW)
    decide(rig.run_dir, "approve", item_id=second)
    assert resumed(rig, monkeypatch) == "done"
    rows = lines(rig)
    (released,) = of(rows, "builder_released")
    assert (
        index_of(rows, "merged", subtask_id=DRIVE) < rows.index(released) < dispatched_at(rows, FW)
    )
    assert refusal(rows) is None


# --- a run without design pairs dispatches as before ---------------------------------------------


def test_a_run_recorded_without_design_pairs_dispatches_the_builder_as_it_always_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    first_run(rig, monkeypatch, design=False)
    rows = lines(rig)
    assert of(rows, "design_pairs_planned") == of(rows, "builder_held") == []
    assert [r.attempt for r in requests_of(rig, FW)] == [1]
    assert index_of(rows, "escalated", subtask_id=DRIVE) < dispatched_at(rows, FW)
    assert refusal(rows) is None


# --- a kill around the hold, and what replay refuses ---------------------------------------------


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


def test_a_kill_at_the_hold_or_the_release_resumes_to_the_lines_of_the_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = rigged(tmp_path / "reference")
    assert first_run(reference, monkeypatch) == "wait"
    decide(reference.run_dir, "approve", item_id=drive_item(lines(reference)))
    assert resumed(reference, monkeypatch) == "done"
    for cut in ("builder_held", "builder_released"):
        rig = rigged(tmp_path / cut)
        killed_first = cut == "builder_held"
        step = first_run(rig, monkeypatch, kill=_at(cut) if killed_first else None)
        assert step == ("killed" if killed_first else "wait")
        if killed_first:
            assert of(lines(rig), "builder_held") == []
            assert resumed(rig, monkeypatch) == "wait"
        decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
        if not killed_first:
            assert resumed(rig, monkeypatch, kill=_at(cut)) == "killed"
            assert of(lines(rig), "merged", subtask_id=DRIVE) != []
            step_now = replay(read_events(rig.run_dir / "events.jsonl")).next_step()
            assert (step_now.kind, step_now.subtask_id) == ("release", FW)
        assert resumed(rig, monkeypatch) == "done"
        same_lines(rig, reference)
        assert refusal(lines(rig)) is None


def test_replay_refuses_a_builder_dispatched_without_the_line_it_owed_or_while_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch) == "wait"
    rows = lines(rig)
    (held,) = of(rows, "builder_held")
    envelope = {k: held[k] for k in ("seq", "ts", "run_id", "gate_mode")}
    dispatch = {**envelope, "kind": "stage_entered", "subtask_id": FW, "attempt": 1}
    dispatch["stage"] = "resolve"
    # Held: fw's dispatch is refused after the hold, and in its place.
    assert "is held while" in str(refusal([*rows, dispatch]))
    without = [r for r in rows if r["kind"] != "builder_held"]
    assert "with no hold line on the record" in str(refusal([*without, dispatch]))
    # A hold that names another reason, item or node than the record owes is refused.
    for edit in ({"why": "not_merged", "item_id": None}, {"nodes": ["drive.other"]}):
        changed = {k: v for k, v in {**held, **edit}.items() if v is not None}
        assert "than the record owes" in str(refusal([*without, changed]))
    # A release while the designer has not merged is no line the record owes.
    release = {**envelope, "kind": "builder_released", "subtask_id": FW, "designer": DRIVE}
    release["nodes"] = [LAW]
    assert "is owed" in str(refusal([*rows, release]))
