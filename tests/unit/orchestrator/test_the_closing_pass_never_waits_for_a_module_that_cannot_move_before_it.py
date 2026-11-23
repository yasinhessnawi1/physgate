"""The closing pass waits only for a module something can still move, through the real loop.

A module is held on what it reads from (a producer hold) or on the design it builds (a designer
hold). The closing pass waits for such a module only while the chain it is held on ends in a
person's open item or in a module that will run. A chain that ends in a module waiting for the
closing pass itself, or in one held for good, ends nowhere a person can act: the closing pass
runs, and the modules held on it go on once it merged. The plan here has four modules: a domain
module whose value a person chooses (it then waits for the closing pass), a builder that reads
its interface and builds its design, and a module that reads the builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import (
    CLOSING,
    JournalGraph,
    Scripted,
    entry,
    events_of,
    refusal,
    resume,
    rig_of,
)
from loop_fakes import FakeReviewer, Rig
from sign_off_rig import before_the_sign_off_rule  # noqa: F401 - the fixture, by name
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_follow_up_after_the_closing_pass_is_recorded_and_replayed_as_the_record_owes import (
    ended,
    follow_ups,
    slice_rig,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    node,
    side,
)
from test_a_person_chooses_a_position_only_on_an_arbitration_item import chose
from test_a_queue_decision_acts_at_a_boundary import _layer, decide
from test_how_each_follow_up_ended_is_told_by_the_integration_item_and_the_ledger import (
    _integration_item,
)
from wait_cycle_rig import under_release  # noqa: F401 - the fixture, by name

from physgate import roles
from physgate.contracts.pairs import ContractPair
from physgate.orchestrator import closing_wait
from physgate.orchestrator.design_pairs import DesignPair
from physgate.orchestrator.design_wait import held_for_good
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.ports import ChangeCheck
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.replay import RunState, replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.orchestrator.waiting import printed_step
from physgate.series.seal import SessionSeries

#: Rows about the order, not about the sign-off a merge owes: the run starts as one before the rule.
pytestmark = pytest.mark.usefixtures("before_the_sign_off_rule")

U, FW, MM, Z0, ZC = "bus-a1b2c3", "fw-3d4e5f", "mm-6a7b8c", "z0", "zc"
LAW = "bus.law"


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


@pytest.fixture(autouse=True)
def _no_contract_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake graph holds no canonical store to test a contract on; the rows are about order."""
    monkeypatch.setattr(RunState, "owed_contract", lambda self: None)


@dataclass
class ScriptedU(Scripted):
    """The domain module's disputes, in place of ``s1``'s."""

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
        follows: int | None = None,
    ) -> ChangeCheck:
        if subtask_id == U:
            self.disputes[U] = self.script[min(self.checked, len(self.script) - 1)]
            self.checked += 1
        return super(Scripted, self).check(subtask_id, attempt_commit, role, series=series)


def rigged(tmp_path: Path) -> Rig:
    rig = rig_of(tmp_path / "run")
    names = ("electrical", "firmware", "control", "sizing")
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(names, "claude-sonnet-5"),
        reviewers=dict.fromkeys(names, "claude-opus-5-5"),
    )
    rig.config_overrides["models"] = models
    rig.changes = ScriptedU(script=list(rig.changes.script))  # type: ignore[attr-defined]
    assert isinstance(rig.diff, JournalGraph)
    # Each module writes a node of its own, so the contract test finds a journal to read.
    rig.diff.writes[U] = [node(LAW, "electrical", v=12)]
    rig.diff.writes[FW] = [node("fw.main", "firmware", v=12)]
    rig.diff.writes[MM] = [node("mm.main", "control", v=12)]
    return rig


PAIRS = (
    ContractPair(
        producer=side(U, "electrical"), consumer=side(FW, "firmware"), interfaces=("iface.bus",)
    ),
    ContractPair(
        producer=side(FW, "firmware"), consumer=side(MM, "control"), interfaces=("iface.fw",)
    ),
)


READER = (
    ContractPair(
        producer=side(U, "electrical"), consumer=side(MM, "control"), interfaces=("iface.bus",)
    ),
)


BOTH = (PAIRS[0], READER[0], PAIRS[1])  # the builder's reader reads the chooser as well


def begin(rig: Rig, *, reader: bool = False, reads_both: bool = False) -> Any:  # noqa: ANN401 - the loop
    """Sizing, the chooser, its builder, the builder's reader, the closing pass.

    With ``reader``, no builder: sizing, the chooser, a module that reads it, the closing pass.
    With ``reads_both``, the builder's reader reads the chooser as well as the builder.
    """
    loop = rig.open()
    plan = [entry(Z0, "sizing", "modules/z0"), entry(U, "electrical", "modules/bus")]
    if not reader:
        plan.append(entry(FW, "firmware", "modules/fw"))
    plan += [entry(MM, "control", "modules/mm"), entry(ZC, "sizing", "modules/z0")]
    summary = DecompositionSummary(
        session_id="decomp-1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.bus",) if reader else ("iface.bus", "iface.fw"),
        spec_commit="a" * 40,
        head_revision=1,
        interface_consumers=(
            (InterfaceConsumers(interface="iface.bus", consumers=("mm",)),)
            if reader
            else (
                InterfaceConsumers(
                    interface="iface.bus", consumers=("fw", "mm") if reads_both else ("fw",)
                ),
                InterfaceConsumers(interface="iface.fw", consumers=("mm",)),
            )
        ),
        system_requirements=(
            SystemRequirement.model_validate_json(
                '{"requirement": "1", "contributing": [{"module": "bus", "criterion": "1"}]}'
            ),
        ),
        contract_pairs=READER if reader else BOTH if reads_both else PAIRS,
        design_pairs=None if reader else (DesignPair(designer=U, builder=FW, nodes=(LAW,)),),
    )
    loop.record.start(plan, decomposed=summary)
    _layer(loop)
    return loop


def drive(rig: Rig, *, first: bool = False, reader: bool = False, reads_both: bool = False) -> str:
    if not first:
        return resume(rig)
    loop = begin(rig, reader=reader, reads_both=reads_both)
    try:
        return str(loop.run().kind)
    finally:
        loop.close()


def state_of(rig: Rig) -> RunState:
    return replay(events_of(rig))


def merged(rig: Rig) -> list[str]:
    return [e.model_dump()["subtask_id"] for e in events_of(rig) if e.kind == "merged"]


def open_items(rig: Rig) -> list[str]:
    return [i.item_id for i in read_queue(rig.run_dir).open_items()]


@pytest.mark.usefixtures("under_release")
def test_the_closing_pass_waits_for_every_module_held_on_a_person_s_item(tmp_path: Path) -> None:
    rig = rigged(tmp_path)
    assert drive(rig, first=True) == "wait"
    state = state_of(rig)
    sessions = [r.subtask_id for r in rig.dispatcher.requests]
    assert ZC not in sessions
    assert len(open_items(rig)) == 1
    assert closing_wait.closing_waits(state) == {
        "closing_waits": [{"subtask_id": ZC, "pending": [U, FW, MM]}]
    }


@pytest.mark.usefixtures("under_release")
def test_the_run_command_prints_the_closing_pass_it_holds_and_what_it_waits_for(
    tmp_path: Path,
) -> None:
    rig = rigged(tmp_path)
    assert drive(rig, first=True) == "wait"
    state = state_of(rig)
    printed, status = printed_step(state.next_step().kind, state)
    assert status == 1
    assert printed == {
        "step": "wait",
        "closing_waits": [{"subtask_id": ZC, "pending": [U, FW, MM]}],
    }
    chose(rig.run_dir, "domain")
    drive(rig)
    state = state_of(rig)
    assert printed_step(state.next_step().kind, state) == ({"step": "done"}, 0)


@pytest.mark.usefixtures("under_release")
def test_a_chain_that_ends_in_a_module_waiting_for_the_closing_pass_does_not_hold_it(
    tmp_path: Path,
) -> None:
    rig = rigged(tmp_path)
    assert drive(rig, first=True) == "wait"
    chose(rig.run_dir, "domain")
    drive(rig)
    state = state_of(rig)
    # The closing pass ran first, then the chooser returned and the modules held on it went on:
    # the run is not left waiting on a chain that ends back at the closing pass.
    done = merged(rig)
    assert set(done) == {Z0, ZC, U, FW, MM}, {s: v.status for s, v in state.subtasks.items()}
    assert done.index(ZC) < done.index(U) < done.index(FW) < done.index(MM)
    assert open_items(rig) == []
    assert state.next_step().kind == "done"
    assert refusal(events_of(rig)) is None


def test_a_reader_of_a_module_waiting_for_the_closing_pass_runs_first_and_is_waited_for(
    tmp_path: Path,
) -> None:
    rig = rigged(tmp_path)
    assert drive(rig, first=True, reader=True) == "wait"
    chose(rig.run_dir, "domain")
    drive(rig)
    state = state_of(rig)
    # The producer waits for the closing pass, which lets its reader go; the reader is a module
    # the closing pass closes over, so it merges first, then the closing pass, then the producer.
    assert merged(rig) == [Z0, MM, ZC, U], {s: v.status for s, v in state.subtasks.items()}
    assert state.next_step().kind == "done"


@pytest.mark.usefixtures("under_release")
def test_a_reader_of_a_builder_held_for_good_does_not_hold_the_closing_pass(
    tmp_path: Path,
) -> None:
    rig = rigged(tmp_path)
    assert drive(rig, first=True) == "wait"
    # A decision that ends the chooser's item acting on nothing: the builder, which builds its
    # design, is held for good, and the module that reads the builder stays held on it.
    decide(rig.run_dir, "reject", "no value is chosen")
    drive(rig)
    state = state_of(rig)
    # The hold on a builder held for good is let go: the reader runs without it, then the closing
    # pass. What this hold used to end in, a wait on the held reader with no item open, was the
    # defect (a producer that never ends), not a rule this row meant to pin.
    assert merged(rig) == [Z0, MM, ZC], {s: v.status for s, v in state.subtasks.items()}
    assert state.subtasks[FW].status == "planned"
    released = [e for e in events_of(rig) if e.kind == "dispatch_released"]
    assert (MM, FW, "producer_held_for_good") in [
        (e.subtask_id, e.producer, e.outcome) for e in released
    ]
    assert open_items(rig) == []
    assert refusal(events_of(rig)) is None
    # What the run does next: nothing is left that any decision or any module can move, so it is
    # over, with the builder held for good never run (not a wait on it, which was the defect).
    assert state.next_step().kind == "done"


def test_under_release_2_the_closing_pass_waits_for_a_reader_of_a_builder_held_for_good(
    tmp_path: Path,
) -> None:
    # Under ``release_2`` a reader of a producer that cannot move is not held on it: it runs
    # without it. So it is a module that can still move, and the closing pass, which reads the
    # graph the reader's work goes into, waits for it, from the moment the producer is held for
    # good until the reader has merged.
    rig = rigged(tmp_path)
    # The reader reads the chooser too, so it is held on the chooser's open item until it is
    # decided, and has not run when its other producer, the builder, is held for good.
    assert drive(rig, first=True, reads_both=True) == "wait"
    decide(rig.run_dir, "reject", "no value is chosen")
    drive(rig)
    events = events_of(rig)
    state = replay(events)
    assert merged(rig) == [Z0, MM, ZC], {s: v.status for s, v in state.subtasks.items()}
    assert state.producer_waits.narrow, "the run began under release_2"
    # The log as it stood at the first line after which the builder is held for good (its
    # designer ended): its reader has not run.
    at = next(i for i in range(len(events)) if held_for_good(replay(events[: i + 1]), FW))
    then = replay(events[: at + 1])
    assert then.subtasks[FW].status == "planned" and then.subtasks[MM].status == "planned"
    assert closing_wait.pending(then, ZC) == [MM], "the closing pass waits for the reader"
    assert closing_wait.closing_waits(then) == {
        "closing_waits": [{"subtask_id": ZC, "pending": [MM]}]
    }
    # Once the reader merged nothing is pending, and the closing pass goes ahead.
    assert closing_wait.pending(state, ZC) == []
    assert state.next_step().kind == "unrun", "and the builder held for good is named as never run"


def test_a_module_merged_on_a_fix_a_person_ordered_is_owed_no_follow_up_and_the_run_ends_escalated(
    tmp_path: Path,
) -> None:
    """Pins what the order now gives, so a change to it is a decision.

    The module merged on the fix a person ordered, so it has no attempt left; the closing pass,
    which now runs after it, changed a value that constrains its nodes, and nobody can rewrite
    them. No follow-up is owed, the integration call fails the magnitude check, and the run ends
    escalated on one item that names the module as owed none.
    """
    rig = slice_rig(tmp_path)
    rig.reviewer = FakeReviewer(verdicts=["pass"], results={2: blocked_review()})
    assert rig.gate is not None
    rig.gate.integration_verdict = "fail"
    assert ended(rig, plan=CLOSING) == "wait"
    decide(rig.run_dir, "reject", "the pole is the one the linearisation gives")
    assert ended(rig, how=resume) == "escalated"
    assert follow_ups(events_of(rig)) == []
    assert _integration_item(rig)["decision_required"] == (
        "The integrated design failed the physics gate's magnitude check at system scope, after "
        "every subtask had merged. No one subtask owns this. Decide which module changes, or "
        "whether to accept the design as it stands. Sizing's closing pass changed values nodes of "
        'these modules depend on: "s1" (owed "sizing.bus" -> "electrical.driver"): none owed: it '
        "merged on its fix."
    )
