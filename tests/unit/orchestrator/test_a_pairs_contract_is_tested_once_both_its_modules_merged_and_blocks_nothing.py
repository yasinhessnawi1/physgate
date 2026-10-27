"""A pair's interface contract is tested once both of its modules merged, and it blocks nothing.

In a run whose plan names its interfaces' consumers, the record owes a pair its contract result
once the subtasks its two sides name have both merged with a clean diff, and a retest after every
later clean merge in either side's module directory, as sizing's closing pass is one. The loop
takes an owed result as a step of its own, before anything else: it reads the canonical graph at
the journal revision the log records, holds the pair to the clause, and writes one line, the
pair's first marked ``first`` and no later one. A failed contract stops nothing: the merge that
owed it stands and the run goes on; completion alone is withheld, by a precondition that reads
each pair's latest result. Replay refuses a result the record does not owe, or at another head or
revision, and any dispatch or completion while one is owed. An interface node the pair cannot be
held to, or a store whose journal ends before the recorded revision, halts the run, and no result
is recorded. Before each completion line the loop takes every recorded result again over the
journal at its recorded revision: a result the journal does not give, whole, halts the run, and
no completion is written over it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeGraph, KilledError, Rig

from physgate import roles
from physgate.contracts.clause import check_pair
from physgate.contracts.graph import nodes_at
from physgate.contracts.pairs import ContractPair, Side
from physgate.orchestrator import completion
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.events import (
    CompletionDeclared,
    ContractTested,
    DiffChecked,
    EnvironmentRecorded,
    Event,
    Halted,
    Incident,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    ModuleCompleted,
    ProposalsChecked,
    Resumed,
    StageEntered,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.record import DecompositionSummary, PlanEntry
from physgate.orchestrator.replay import replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.state.store import JOURNAL_NAME, Store, journal_records_after

DRIVE, FW, BUDGET, CLOSING, INTEG = (
    "drive-0a1b2c",
    "fw-3d4e5f",
    "budget-6a7b8c",
    "budget-c-9d0e1f",
    "integ",
)
ROLES = ("control", "firmware", "integration", "sizing")


def side(subtask_id: str, role: str) -> Side:
    return Side(module=subtask_id.rsplit("-", 1)[0], subtask_id=subtask_id, role=role)


P_BUDGET = ContractPair(
    producer=side(DRIVE, "control"), consumer=side(BUDGET, "sizing"), interfaces=("iface.drive",)
)
P_FW = ContractPair(
    producer=side(DRIVE, "control"), consumer=side(FW, "firmware"), interfaces=("iface.drive",)
)
P_BACK = ContractPair(
    producer=side(FW, "firmware"), consumer=side(DRIVE, "control"), interfaces=("iface.tilt",)
)


#: The unit of each quantity the nodes here carry.
UNITS = {"v": "V", "period": "ms"}


def node(
    node_id: str, role: str, *on: str, kind: str = "component", **values: float
) -> dict[str, Any]:
    """A node payload of ``role`` constraining ``on``, its quantities in ``UNITS``."""
    domain = "cross" if kind == "interface" or role == "sizing" else role
    quantities = {
        name: {"value": v, "unit": UNITS[name], "source": "brief", "written_by": role}
        for name, v in values.items()
    }
    return {
        "id": node_id,
        "kind": kind,
        "domain": domain,
        "owner_role": role,
        "quantities": quantities,
        "requirements": [],
        "constrains": list(on),
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-26T00:00:00Z",
    }


IFACE_DRIVE = node("iface.drive", "control", kind="interface", v=12)
IFACE_TILT = node("iface.tilt", "firmware", kind="interface", period=10)


@dataclass
class StoreGraph(FakeGraph):
    """The graph port over a real canonical store: each subtask's nodes land as it merges."""

    writes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def records_after(self, revision: int) -> list[Any]:
        return journal_records_after(self.root, revision)

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        return self.writes.get(subtask_id, [])

    def write(self, payload: dict[str, Any], role: str) -> int:
        store = Store(self.root)
        written = store.write_node(payload, role)
        store.close()
        assert written.accepted, written.reason
        return int(written.revision or 0)


class Installed(FakeDispatcher):
    """A dispatcher whose installation has facts, so each process records its environment."""

    def environment(self) -> InstallFacts:  # type: ignore[override]
        return InstallFacts(
            path="/i",
            interpreter="/i/bin/python",
            owner_is_session_user=True,
            files_with_write_bits=0,
            files_with_second_links=0,
            stdlib="/lib",
            stdlib_writable=True,
            state_filesystem="apfs",
            state_on_local_disk=True,
        )


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def rig_for(
    tmp_path: Path,
    *,
    fw_volts: float = 12,
    closing_volts: float = 12,
    interfaces: Sequence[dict[str, Any]] = (IFACE_DRIVE, IFACE_TILT),
    **fields: Any,  # noqa: ANN401 - the rig's own fields
) -> Rig:
    """A loop over a real store holding the plan's interfaces; each module writes one node."""
    root = tmp_path / "store"
    root.mkdir(parents=True)
    store = Store(root)
    for payload in interfaces:
        assert store.write_node(payload, payload["owner_role"]).accepted
    store.close()
    both = ("iface.drive", "iface.tilt")
    writes = {
        BUDGET: [node("budget.supply", "sizing", "iface.drive", v=12)],
        DRIVE: [node("drive.motor", "control", *both, v=12, period=10)],
        FW: [node("fw.main", "firmware", *both, v=fw_volts, period=10)],
        CLOSING: [node("budget.supply", "sizing", "iface.drive", v=closing_volts)],
    }
    graph = StoreGraph(root=root, writes=writes)
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(ROLES, "claude-sonnet-5"),
        reviewers=dict.fromkeys(ROLES, "claude-opus-5-5"),
    )
    (tmp_path / "run").mkdir()
    return Rig(tmp_path / "run", diff=graph, config_overrides={"models": models}, **fields)


def entry(subtask_id: str, role: str, module: str) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id,
        spec_path=f"specs/{subtask_id}.md",
        assigned_role=role,
        module_dir=f"modules/{module}",
    )


def start(loop: Loop, *, sizing: bool = False, pairs: bool = True) -> None:
    """The plan: sizing's opening pass if asked, drive, fw, the closing pass, integration."""
    plan = [entry(BUDGET, "sizing", "budget")] if sizing else []
    plan += [entry(DRIVE, "control", "drive"), entry(FW, "firmware", "fw")]
    plan += [entry(CLOSING, "sizing", "budget")] if sizing else []
    plan.append(entry(INTEG, "integration", "integration"))
    if not pairs:
        loop.start(plan)
        return
    consumers = (
        InterfaceConsumers(
            interface="iface.drive", consumers=("fw", "budget") if sizing else ("fw",)
        ),
        InterfaceConsumers(interface="iface.tilt", consumers=("drive",)),
    )
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
        interface_consumers=consumers,
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=(P_BUDGET, P_FW, P_BACK) if sizing else (P_FW, P_BACK),
    )
    loop.record.start(plan, decomposed=summary)


def hooked(
    monkeypatch: pytest.MonkeyPatch,
    loop: Loop,
    *,
    declared: Sequence[str] | None = None,
    kill: Callable[[Event, list[Event]], bool] | None = None,
) -> None:
    """Write integration's declaration where the loop will; die before the line ``kill`` picks."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    written: list[Event] = []

    def emitting(event: Event) -> None:
        if kill is not None and kill(event, written):
            raise KilledError
        written.append(event)
        emit(event)
        if isinstance(event, ProposalsChecked) and event.subtask_id == INTEG and declared:
            emit(
                CompletionDeclared(
                    **loop._env(),  # noqa: SLF001
                    subtask_id=INTEG,
                    attempt=event.attempt,
                    modules=tuple(declared),
                    declaration_sha256="d" * 64,
                )
            )

    monkeypatch.setattr(loop, "_emit", emitting)


def finished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sizing: bool = False,
    pairs: bool = True,
    declared: Sequence[str] | None = None,
    **fields: Any,  # noqa: ANN401 - the rig's own
) -> tuple[Rig, list[Event]]:
    rig = rig_for(tmp_path, **fields)
    loop = rig.open()
    hooked(monkeypatch, loop, declared=declared)
    start(loop, sizing=sizing, pairs=pairs)
    loop.run()
    loop.close()
    return rig, read_events(rig.run_dir / "events.jsonl")


def contracts(events: Sequence[Event]) -> list[ContractTested]:
    return [e for e in events if isinstance(e, ContractTested)]


def at(events: Sequence[Event], kind: type[Any], subtask: str) -> int:
    return next(i for i, e in enumerate(events) if isinstance(e, kind) and e.subtask_id == subtask)


def next_line(events: Sequence[Event], line: Event) -> Event:
    """``line`` moved to where the next line of ``events`` goes."""
    return line.model_copy(update={"seq": len(events)})


def refused(events: Sequence[Event], line: Event, reason: str) -> None:
    with pytest.raises(CorruptEventLogError) as caught:
        replay([*events, next_line(events, line)])
    assert reason in caught.value.context["reason"]


# --- when a result is owed, and what it says ------------------------------------------------------


@pytest.mark.parametrize("mode", ["on", "observe", "off"])
def test_a_pairs_contract_runs_when_its_second_module_merges_and_is_marked_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    _, events = finished(tmp_path, monkeypatch, declared=(DRIVE, FW), gate_mode=mode)
    fw_diff = at(events, DiffChecked, FW)
    tested = contracts(events)
    # Nothing is owed while drive alone has merged; both of fw's pairs, in order, once fw has.
    assert [e.seq for e in tested] == [fw_diff + 1, fw_diff + 2]
    assert [(e.result.pair, e.first, e.result.outcome) for e in tested] == [
        (P_FW, True, "pass"),
        (P_BACK, True, "pass"),
    ]
    assert [e.result.clauses_checked for e in tested] == [1, 1]
    merge = events[at(events, Merged, FW)]
    assert {(e.commit, e.revision) for e in tested} == {(merge.merge_commit, 4)}  # type: ignore[union-attr]
    # The run goes on to the integration call, and both modules complete.
    assert not isinstance(events[fw_diff + 3], ContractTested | StageEntered)
    assert [e.subtask_id for e in events if isinstance(e, ModuleCompleted)] == [DRIVE, FW]
    assert replay(events).next_step().kind == "done"


def test_a_failed_contract_never_blocks_the_merge_that_triggered_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = finished(tmp_path, monkeypatch, declared=(DRIVE, FW), fw_volts=11)
    tested = contracts(events)
    assert [(e.result.pair, e.result.outcome) for e in tested] == [(P_FW, "fail"), (P_BACK, "pass")]
    checked = tested[0].result.interfaces[0].clauses[0].nodes
    assert [(n.node, n.outcome) for n in checked] == [("drive.motor", "pass"), ("fw.main", "value")]
    state = replay(events)
    # The merge stands, the run went on, and integration's attempt merged after it.
    assert {state.subtasks[s].status for s in (DRIVE, FW, INTEG)} == {"done"}
    assert isinstance(state.integration, IntegrationGateRan)
    assert state.next_step().kind == "done"
    # Completion alone is withheld, from both modules of the failed pair.
    assert not [e for e in events if isinstance(e, ModuleCompleted)]
    for module in (DRIVE, FW):
        why = dict(open_preconditions(state, module))["contract"]
        assert why == "drive to fw: its latest contract result failed"


def test_the_closing_pass_owes_sizings_pair_a_retest_never_marked_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = finished(
        tmp_path, monkeypatch, sizing=True, closing_volts=11, declared=(BUDGET, DRIVE, FW)
    )
    drive, fw, closing = (at(events, DiffChecked, s) for s in (DRIVE, FW, CLOSING))
    assert [(e.seq, e.result.pair, e.first, e.result.outcome) for e in contracts(events)] == [
        (drive + 1, P_BUDGET, True, "pass"),
        (fw + 1, P_FW, True, "pass"),
        (fw + 2, P_BACK, True, "pass"),
        (closing + 1, P_BUDGET, False, "fail"),
    ]
    # Completion reads each pair's latest result: the pair the closing pass broke withholds both.
    assert [e.subtask_id for e in events if isinstance(e, ModuleCompleted)] == [FW]
    assert dict(open_preconditions(replay(events), BUDGET))["contract"] == (
        "drive to budget: its latest contract result failed"
    )


def test_contract_results_are_rebuilt_from_the_event_log_by_a_fresh_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, events = finished(tmp_path, monkeypatch, sizing=True, closing_volts=11)
    code = (
        "import sys\n"
        "from physgate.orchestrator.events import read_events\n"
        "from physgate.orchestrator.replay import replay\n"
        "for line in replay(read_events(sys.argv[1])).contracts:\n"
        "    print(line.model_dump_json())\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(rig.run_dir / "events.jsonl")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rebuilt = [ContractTested.model_validate_json(raw) for raw in out.splitlines()]
    assert rebuilt == contracts(events)
    assert [e.revision for e in rebuilt] == [4, 5, 5, 6]
    # Each is what the clause gives over the canonical journal at the revision it records.
    for line in rebuilt:
        assert check_pair(line.result.pair, nodes_at(rig.diff.root, line.revision)) == line.result


def test_completion_waits_on_every_pair_of_the_module_and_holds_in_a_run_without_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert [p.name for p in completion.PRECONDITIONS][-1] == "contract"
    _, events = finished(tmp_path / "pairs", monkeypatch)
    owed = replay(events[: at(events, DiffChecked, FW) + 1])
    assert owed.next_step().kind == "contract"
    assert dict(open_preconditions(owed, DRIVE))["contract"] == (
        "drive to fw: no contract result; fw to drive: no contract result"
    )
    _, plain = finished(
        tmp_path / "plain", monkeypatch, pairs=False, declared=(DRIVE, FW), interfaces=()
    )
    assert not contracts(plain)
    assert [e.subtask_id for e in plain if isinstance(e, ModuleCompleted)] == [DRIVE, FW]


# --- what replay refuses ------------------------------------------------------------------------


def test_replay_refuses_a_contract_result_the_record_does_not_owe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = finished(tmp_path / "pairs", monkeypatch)
    first, second = contracts(events)
    owed = events[: at(events, DiffChecked, FW) + 1]
    refused(owed, first.model_copy(update={"result": second.result}), "owed next is drive to fw")
    refused(owed, first.model_copy(update={"first": False}), "first result is marked first")
    refused(owed, first.model_copy(update={"commit": "0" * 40}), "the run's recorded head")
    refused(owed, first.model_copy(update={"revision": 3}), "the run's recorded head")
    # None is owed before both modules merged, or after the integration call: a forged line.
    refused(events[: at(events, DiffChecked, DRIVE) + 1], first, "where none is owed")
    call = next(i for i, e in enumerate(events) if isinstance(e, IntegrationGateRan))
    refused(events[: call + 1], second, "where none is owed")
    refused(events, second, "where none is owed")
    _, plain = finished(tmp_path / "plain", monkeypatch, pairs=False, interfaces=())
    refused(plain[: at(plain, DiffChecked, FW) + 1], first, "records no contract pairs")


def test_nothing_is_dispatched_or_completed_while_a_result_is_owed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = finished(tmp_path, monkeypatch, declared=(DRIVE, FW))
    owed = events[: at(events, DiffChecked, FW) + 1]
    call = next(e for e in events if isinstance(e, IntegrationGateRan))
    resolve = events[at(events, StageEntered, INTEG)]
    done = next(e for e in events if isinstance(e, ModuleCompleted))
    for line in (call, resolve, done):
        refused(owed, line, "while a pair's contract result is owed")


# --- halts --------------------------------------------------------------------------------------


def halt_of(events: Sequence[Event]) -> tuple[Event, Incident, Halted]:
    """The line before the run's one incident, that incident, naming no subtask, and the halt."""
    (where,) = [i for i, e in enumerate(events) if isinstance(e, Incident)]
    incident, halted = events[where], events[where + 1]
    assert isinstance(incident, Incident) and incident.subtask_id is None
    assert isinstance(halted, Halted)
    return events[where - 1], incident, halted


@pytest.mark.parametrize(
    "interfaces",
    [
        (IFACE_TILT,),
        (IFACE_DRIVE | {"kind": "component"}, IFACE_TILT),
        (IFACE_DRIVE | {"owner_role": "firmware"}, IFACE_TILT),
    ],
    ids=["missing", "not an interface", "another role's"],
)
def test_an_interface_node_its_pair_cannot_be_held_to_halts_the_run_with_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interfaces: tuple[dict[str, Any], ...]
) -> None:
    _, events = finished(tmp_path, monkeypatch, interfaces=interfaces)
    assert not contracts(events)
    diff, incident, halted = halt_of(events)
    assert isinstance(diff, DiffChecked) and diff.subtask_id == FW
    assert (incident.cause, "iface.drive" in incident.detail) == ("interface_mismatch", True)
    assert halted.detail == "interface_mismatch"


def test_a_store_whose_journal_ends_before_the_recorded_revision_halts_with_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rig_for(tmp_path)
    loop = rig.open()
    hooked(monkeypatch, loop, kill=lambda e, _: isinstance(e, ContractTested))
    start(loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    journal = rig.diff.root / JOURNAL_NAME
    lines = journal.read_bytes().splitlines(keepends=True)
    journal.write_bytes(b"".join(lines[:-1]))  # fw's node is gone from the journal
    fresh = rig.open()
    assert fresh.resume().kind == "halted"
    fresh.close()
    events = read_events(rig.run_dir / "events.jsonl")
    assert not contracts(events)
    _, incident, halted = halt_of(events)
    assert (incident.cause, halted.detail) == ("foreign_journal_line", "foreign_journal_line")
    assert "journal revision 4" in incident.detail


# --- a kill at each cut -------------------------------------------------------------------------


def nth_contract(n: int, *, first: bool | None = None) -> Callable[[Event, list[Event]], bool]:
    def pick(event: Event, written: list[Event]) -> bool:
        before = [e for e in written if isinstance(e, ContractTested)]
        return (
            isinstance(event, ContractTested) and len(before) == n and first in (None, event.first)
        )

    return pick


CUTS: dict[str, Callable[[Event, list[Event]], bool]] = {
    "clean diff, first result": nth_contract(0),
    "two results of one merge": nth_contract(2),
    "a merge and its diff": lambda e, _: (
        isinstance(e, StageEntered) and e.subtask_id == FW and e.stage == "diff"
    ),
    "closing diff, its retest": nth_contract(3, first=False),
}


def comparable(events: Sequence[Event]) -> list[dict[str, Any]]:
    """The lines a run writes, without what a process taking over adds or a clock gives."""
    return [
        e.model_dump(exclude={"seq", "ts"})
        for e in events
        if not isinstance(e, EnvironmentRecorded | Resumed)
    ]


@pytest.mark.parametrize("cut", CUTS)
def test_a_kill_at_each_cut_resumes_to_the_lines_of_the_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    kw: dict[str, Any] = {"sizing": True, "closing_volts": 11, "declared": (BUDGET, DRIVE, FW)}
    _, reference = finished(tmp_path / "reference", monkeypatch, **kw)
    assert [e.first for e in contracts(reference)] == [True, True, True, False]
    rig = rig_for(tmp_path / "cut", closing_volts=11, dispatcher=Installed())
    loop = rig.open()
    hooked(monkeypatch, loop, declared=kw["declared"], kill=CUTS[cut])
    start(loop, sizing=True)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    cut_at = len(read_events(rig.run_dir / "events.jsonl"))
    fresh = rig.open()
    hooked(monkeypatch, fresh, declared=kw["declared"])
    assert fresh.resume().kind == "done"
    fresh.close()
    events = read_events(rig.run_dir / "events.jsonl")
    assert comparable(events) == comparable(reference)
    if cut != "a merge and its diff":
        # The result is the process's first step: it spawns nothing, so it records no environment.
        assert isinstance(events[cut_at], ContractTested)


def test_a_kill_between_the_incident_and_its_halt_resumes_to_the_halt_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, reference = finished(tmp_path / "reference", monkeypatch, interfaces=(IFACE_TILT,))
    rig = rig_for(tmp_path / "cut", interfaces=(IFACE_TILT,))
    loop = rig.open()
    hooked(monkeypatch, loop, kill=lambda e, _: isinstance(e, Halted))
    start(loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    fresh = rig.open()
    assert fresh.resume().kind == "halted"
    fresh.close()
    events = read_events(rig.run_dir / "events.jsonl")
    assert comparable(events) == comparable(reference)
    assert len([e for e in events if isinstance(e, Incident)]) == 1


# --- the order results are owed in, and where a retest is owed ----------------------------------


def start_with(
    loop: Loop,
    plan: Sequence[PlanEntry],
    consumers: dict[str, tuple[str, ...]],
    pairs: tuple[ContractPair, ...],
) -> None:
    """Start ``plan`` with its interfaces' ``consumers`` and the ``pairs`` they give."""
    requirement = '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
    summary = DecompositionSummary(
        session_id="decomposition",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=tuple(consumers),
        spec_commit="e" * 40,
        head_revision=journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev,
        interface_consumers=tuple(
            InterfaceConsumers(interface=interface, consumers=modules)
            for interface, modules in consumers.items()
        ),
        system_requirements=(SystemRequirement.model_validate_json(requirement),),
        contract_pairs=pairs,
    )
    loop.record.start(list(plan), decomposed=summary)


def test_a_ready_pair_behind_one_not_yet_ready_is_owed_at_its_own_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sizing's module is named so that its pair with drive comes after drive's pair with fw.
    zbudget, zclosing = "zbudget-6a7b8c", "zbudget-c-9d0e1f"
    rig = rig_for(tmp_path)
    graph = rig.diff
    assert isinstance(graph, StoreGraph)
    graph.writes[zbudget], graph.writes[zclosing] = (
        graph.writes.pop(BUDGET),
        graph.writes.pop(CLOSING),
    )
    loop = rig.open()
    hooked(monkeypatch, loop)
    sized = ContractPair(
        producer=side(DRIVE, "control"),
        consumer=side(zbudget, "sizing"),
        interfaces=("iface.drive",),
    )
    plan = [
        entry(zbudget, "sizing", "zbudget"),
        entry(DRIVE, "control", "drive"),
        entry(FW, "firmware", "fw"),
        entry(zclosing, "sizing", "zbudget"),
        entry(INTEG, "integration", "integration"),
    ]
    consumers = {"iface.drive": ("fw", "zbudget"), "iface.tilt": ("drive",)}
    start_with(loop, plan, consumers, (P_FW, sized, P_BACK))
    loop.run()
    loop.close()
    events = read_events(rig.run_dir / "events.jsonl")
    drive = at(events, DiffChecked, DRIVE)
    # Drive to fw is first in the recorded order and not ready at drive's merge; drive to zbudget
    # is ready there, and is owed there.
    assert (contracts(events)[0].seq, contracts(events)[0].result.pair) == (drive + 1, sized)


#: An interface sizing produces, which drive reads.
IFACE_BUDGET = node("iface.budget", "sizing", kind="interface", v=12)
P_SIZED = ContractPair(
    producer=side(BUDGET, "sizing"), consumer=side(DRIVE, "control"), interfaces=("iface.budget",)
)


def test_a_later_merge_in_the_producers_directory_owes_a_retest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rig_for(tmp_path, interfaces=(IFACE_BUDGET,))
    assert isinstance(rig.diff, StoreGraph)
    rig.diff.writes.update(
        {
            BUDGET: [node("budget.supply", "sizing", "iface.budget", v=12)],
            DRIVE: [node("drive.motor", "control", "iface.budget", v=12)],
            FW: [node("fw.main", "firmware")],
            CLOSING: [node("budget.supply", "sizing", "iface.budget", v=11)],
        }
    )
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(BUDGET, DRIVE))
    plan = [
        entry(BUDGET, "sizing", "budget"),
        entry(DRIVE, "control", "drive"),
        entry(FW, "firmware", "fw"),
        entry(CLOSING, "sizing", "budget"),
        entry(INTEG, "integration", "integration"),
    ]
    start_with(loop, plan, {"iface.budget": ("drive",)}, (P_SIZED,))
    loop.run()
    loop.close()
    events = read_events(rig.run_dir / "events.jsonl")
    drive, closing = (at(events, DiffChecked, s) for s in (DRIVE, CLOSING))
    # The closing pass merges in the producer's directory, and owes the pair its retest there.
    assert [(e.seq, e.result.pair, e.first, e.result.outcome) for e in contracts(events)] == [
        (drive + 1, P_SIZED, True, "pass"),
        (closing + 1, P_SIZED, False, "fail"),
    ]
    assert [e for e in events if isinstance(e, ModuleCompleted)] == []


# --- what replay refuses, after a halt and under off ----------------------------------------------


def test_a_contract_result_after_the_halt_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, honest = finished(tmp_path / "honest", monkeypatch)
    _, halted = finished(tmp_path / "halted", monkeypatch, interfaces=(IFACE_TILT,))
    state = replay(halted)
    assert state.halted is not None and state.owed_contract() == P_FW
    # The pair's honest result, at the halted run's own head and revision.
    forged = contracts(honest)[0].model_copy(
        update={"commit": state.run_head, "revision": state.journal_head}
    )
    refused(halted, forged, "the run is halted")


def test_no_integration_skip_is_taken_under_off_while_a_result_is_owed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, events = finished(tmp_path, monkeypatch, declared=(DRIVE, FW), gate_mode="off")
    owed = events[: at(events, DiffChecked, FW) + 1]
    skip = next(e for e in events if isinstance(e, IntegrationGateSkipped))
    assert skip.reason == "gate_mode=off"
    refused(owed, skip, "while a pair's contract result is owed")


# --- every recorded result is taken again before a completion -----------------------------------


def rewritten(log: Path, edit: Callable[[list[dict[str, Any]]], None]) -> None:
    """The log with lines rewritten in place by ``edit``, as anything on the machine could."""
    records = [json.loads(raw) for raw in log.read_bytes().splitlines()]
    edit(records)
    log.write_bytes(
        b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in records)
    )


def test_a_failed_result_rewritten_as_its_pairs_pass_halts_the_run_before_any_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, passing = finished(tmp_path / "pass", monkeypatch)
    honest = json.loads(contracts(passing)[0].model_dump_json())["result"]
    rig = rig_for(tmp_path / "fail", fw_volts=11)
    loop = rig.open()
    hooked(monkeypatch, loop, declared=(DRIVE, FW), kill=nth_contract(1))
    start(loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    log = rig.run_dir / "events.jsonl"

    def as_a_pass(records: list[dict[str, Any]]) -> None:
        failed = records[-1]
        assert (failed["kind"], failed["result"]["outcome"]) == ("contract_tested", "fail")
        assert failed["result"]["pair"] == honest["pair"]
        failed["result"] = honest

    rewritten(log, as_a_pass)
    # Its pair, interfaces, counts, digest, commit and revision are consistent: replay takes it.
    assert replay(read_events(log)).contracts[0].result.outcome == "pass"
    fresh = rig.open()
    hooked(monkeypatch, fresh, declared=(DRIVE, FW))
    assert fresh.resume().kind == "halted"
    fresh.close()
    events = read_events(log)
    assert [e for e in events if isinstance(e, ModuleCompleted)] == []
    before, incident, halted = halt_of(events)
    # Integration merged with its diff clean, and the first completion step found the result.
    assert isinstance(before, DiffChecked) and before.subtask_id == INTEG
    assert (incident.cause, halted.detail) == ("foreign_journal_line", "foreign_journal_line")
    assert "drive to fw" in incident.detail and "revision 4" in incident.detail


def test_a_result_rewritten_in_its_detail_with_its_outcome_kept_halts_the_run_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Uninterrupted, the closing pass breaks sizing's pair and fw alone is completed.
    rig = rig_for(tmp_path, closing_volts=11)
    loop = rig.open()
    hooked(
        monkeypatch,
        loop,
        declared=(BUDGET, DRIVE, FW),
        kill=lambda e, _: isinstance(e, ModuleCompleted),
    )
    start(loop, sizing=True)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    log = rig.run_dir / "events.jsonl"

    def another_failure(records: list[dict[str, Any]]) -> None:
        retest = [r for r in records if r["kind"] == "contract_tested"][-1]
        assert (retest["first"], retest["result"]["outcome"]) == (False, "fail")
        (budget,) = [
            n
            for n in retest["result"]["interfaces"][0]["clauses"][0]["nodes"]
            if n["node"] == "budget.supply"
        ]
        assert budget["outcome"] == "value"
        budget["outcome"] = "missing"  # the clause, the interface and the pair still fail

    rewritten(log, another_failure)
    fresh = rig.open()
    assert fresh.run().kind == "halted"
    fresh.close()
    events = read_events(log)
    assert [e for e in events if isinstance(e, ModuleCompleted)] == []
    _, incident, _ = halt_of(events)
    assert incident.cause == "foreign_journal_line"
    assert "drive to budget" in incident.detail and "revision 6" in incident.detail
