"""Node proposals against the real store and real git: applied, never trusted.

Proposals are read from the attempt commit; the role is the plan's; all of an
attempt's proposals are pre-checked on a scratch copy and applied all or none;
an owner change is refused; a refusal is a rejected attempt with the store's
reason. A journal line the orchestrator did not write halts the run and the
store is never reopened over it; a crash between the intent, the append and the
record resumes without a false incident; a node-file halt is repaired before
anything reads the graph.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from git_rig import DispatchPort, Gate, GitDispatcher, Reviewer, config, run_layout, sh

from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.events import (
    AttemptRejected,
    Incident,
    NodeFilesRepaired,
    StageEntered,
    WriteDone,
    WriteIntended,
    read_events,
)
from physgate.orchestrator.git import head_of
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit
from physgate.orchestrator.record import (
    DecompositionCall,
    DecompositionSummary,
    PlanEntry,
    RunRecord,
)
from physgate.state.store import JOURNAL_NAME, Store, journal_records_after, node_file_body

pytestmark = pytest.mark.integration

MODULE = "modules/power"


def node(
    node_id: str, owner: str = "electrical", kind: str = "component", amps: float = 2.4
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": "electrical",
        "owner_role": owner,
        "quantities": {
            "current": {"value": amps, "unit": "A", "source": "datasheet", "written_by": owner}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-26T00:00:00Z",
    }


class Rig:
    """A decomposed run: a real repository, a real store holding two nodes, a real loop."""

    def __init__(self, root: Path) -> None:
        self.run: RunGit = run_layout(root)
        self.store_root = self.run.run_dir / "store"
        store = Store(self.store_root)
        assert store.write_node(node("electrical.motor"), "electrical").accepted
        bus = node("iface.power_bus", kind="interface")
        assert store.write_node(bus, "electrical").accepted
        head = store.head_revision()
        store.close()
        self.gate = Gate()
        self.keeper: StoreKeeper = StoreKeeper(self.run, self.store_root)
        cfg = config()
        record = RunRecord(cfg, self.run.run_dir)
        record.start(
            [
                PlanEntry(
                    subtask_id="s1",
                    spec_path=".physgate/specs/s1.md",
                    assigned_role="electrical",
                    module_dir=MODULE,
                )
            ],
            call=DecompositionCall(session_id="decomp", usage=()),
            decomposed=DecompositionSummary(
                session_id="decomp",
                model="claude-sonnet-5",
                num_turns=2,
                subtasks=1,
                interface_nodes=("iface.power_bus",),
                spec_commit=head_of(self.run.repo, self.run.run_branch),
                head_revision=head,
            ),
        )
        record.close()

    def loop(self, dispatcher: GitDispatcher, keeper: StoreKeeper | None = None) -> Loop:
        return Loop(
            config=config(),
            run_dir=self.run.run_dir,
            gate=self.gate,
            reviewers={"electrical": Reviewer()},
            dispatcher=DispatchPort(dispatcher),
            changes=GitChangeChecker(self.run, self.store_root, {"s1": MODULE}),
            merger=GitMerger(self.run, removal_timeout_s=60.0),
            graph=keeper or self.keeper,
            sleep=lambda _: None,
        )

    def events(self) -> list[Any]:
        return read_events(self.run.run_dir / "events.jsonl")

    def canonical(self) -> dict[str, Any]:
        return {line.node_id: line.payload for line in journal_records_after(self.store_root, 0)}


def foreign_append(store_root: Path) -> None:
    """A write that got past the first layer: a second handle appends a valid line."""
    other = Store(store_root)
    assert other.write_node(node("electrical.motor", amps=9.9), "electrical").accepted
    other.close()


def test_proposals_are_read_from_the_commit_and_applied_behind_intents(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    committed = node("electrical.driver", amps=1.5)

    def tamper(worktree: Path) -> None:
        path = worktree / ".physgate" / "proposals" / "electrical.driver.json"
        path.write_text(json.dumps(node("electrical.driver", amps=99.0)))

    dispatcher = GitDispatcher(
        rig.run, proposals={1: {"electrical.driver": committed}}, after_commit={1: tamper}
    )
    loop = rig.loop(dispatcher)
    assert loop.run().kind == "done"
    loop.close()
    rig.keeper.close()
    assert rig.canonical()["electrical.driver"] == committed
    events = rig.events()
    (intent,) = [e for e in events if isinstance(e, WriteIntended)]
    (done,) = [e for e in events if isinstance(e, WriteDone)]
    assert intent.seq < done.seq and done.revision == intent.expected_revision == 3
    assert intent.actor_role == "electrical"
    shown = sh(rig.store_root, "show", f"HEAD:{JOURNAL_NAME}")
    assert shown == (rig.store_root / JOURNAL_NAME).read_text()


@pytest.mark.parametrize(
    ("proposals", "reason"),
    [
        ({"control.loop": node("control.loop", owner="control")}, "cross_role_write"),
        (
            {
                "electrical.driver": node("electrical.driver"),
                "iface.power_bus": node("iface.power_bus", kind="interface", amps=5.0),
            },
            "interface_immutable",
        ),
        ({"electrical.motor": node("electrical.motor", owner="control")}, "changes the owner"),
        ({"electrical.wrong": node("electrical.driver")}, "named for its file"),
    ],
    ids=[
        "a node owned by another role",
        "all or none: the second proposal writes an interface",
        "an owner change, even from the owner",
        "a file named for another node",
    ],
)
def test_a_proposal_the_store_would_refuse_rejects_the_attempt_and_applies_nothing(
    tmp_path: Path, proposals: dict[str, dict[str, Any]], reason: str
) -> None:
    rig = Rig(tmp_path)
    before = rig.canonical()

    def withdraw(worktree: Path) -> None:
        # The repair session takes the refused proposals back; until it does, they
        # stay on the subtask's branch and every attempt carries them.
        for path in (worktree / ".physgate" / "proposals").iterdir():
            path.unlink()

    dispatcher = GitDispatcher(rig.run, proposals={1: proposals}, during={2: withdraw})
    loop = rig.loop(dispatcher)
    loop.run()
    loop.close()
    rig.keeper.close()
    (first, *_) = [e for e in rig.events() if isinstance(e, AttemptRejected)]
    assert first.finding.source == "proposal" and reason in first.finding.text
    assert rig.canonical() == before
    assert rig.gate.calls == 1  # only the second, clean attempt reached the gate
    second = dispatcher.requests[1].repair_instruction
    assert second is not None and reason in second


def test_a_journal_line_written_during_the_session_halts_the_run_before_the_gate(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path)
    dispatcher = GitDispatcher(rig.run, during={1: lambda _: foreign_append(rig.store_root)})
    loop = rig.loop(dispatcher)
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = [e for e in rig.events() if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line" and "revision 3" in incident.detail
    assert rig.gate.calls == 0


def test_a_journal_line_appended_after_the_check_makes_the_write_refuse(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    class AppendingGate(Gate):
        def check(self, artefact: Any, *, mode: Any) -> Any:
            foreign_append(rig.store_root)
            return super().check(artefact, mode=mode)

    rig.gate = AppendingGate()
    dispatcher = GitDispatcher(
        rig.run, proposals={1: {"electrical.driver": node("electrical.driver")}}
    )
    loop = rig.loop(dispatcher)
    assert loop.run().kind == "halted"
    loop.close()
    rig.keeper.close()
    events = rig.events()
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "foreign_journal_line"
    assert [e for e in events if isinstance(e, WriteDone)] == []
    assert "electrical.driver" not in rig.canonical()


class _Crash(StoreKeeper):
    def __init__(self, run: RunGit, root: Path, *, after_append: bool) -> None:
        super().__init__(run, root)
        self.after_append = after_append

    def write(self, payload: dict[str, Any], role: str) -> int:
        if not self.after_append:
            raise KeyboardInterrupt
        super().write(payload, role)
        raise KeyboardInterrupt


@pytest.mark.parametrize(
    "after_append", [False, True], ids=["before the append", "after the append"]
)
def test_a_crash_around_the_write_resumes_without_a_false_incident_or_a_second_write(
    tmp_path: Path, after_append: bool
) -> None:
    rig = Rig(tmp_path)
    dispatcher = GitDispatcher(
        rig.run, proposals={1: {"electrical.driver": node("electrical.driver")}}
    )
    crashing = _Crash(rig.run, rig.store_root, after_append=after_append)
    loop = rig.loop(dispatcher, crashing)
    with pytest.raises(KeyboardInterrupt):
        loop.run()
    loop.close()
    crashing.close()
    again = rig.loop(dispatcher, StoreKeeper(rig.run, rig.store_root))
    assert again.resume().kind == "done"
    again.close()
    events = rig.events()
    assert [e for e in events if isinstance(e, Incident)] == []
    writes = [
        line
        for line in journal_records_after(rig.store_root, 0)
        if line.node_id == "electrical.driver"
    ]
    assert len(writes) == 1
    assert len([e for e in events if isinstance(e, WriteDone)]) == 1
    assert len([e for e in events if isinstance(e, WriteIntended)]) == (1 if after_append else 2)
    assert len(dispatcher.requests) == 1


def test_a_node_file_halt_is_repaired_before_anything_reads_the_graph(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    def tamper(_: Path) -> None:
        (rig.store_root / "nodes" / "electrical.motor.json").write_text('{"forged": true}')

    dispatcher = GitDispatcher(rig.run, during={1: tamper}, halted={1})
    loop = rig.loop(dispatcher)
    assert loop.run().kind == "done"
    loop.close()
    rig.keeper.close()
    events = rig.events()
    (repair,) = [e for e in events if isinstance(e, NodeFilesRepaired)]
    assert repair.repaired >= 1
    first_read = min(
        e.seq for e in events if isinstance(e, StageEntered) and e.stage == "verify_reading"
    )
    assert repair.seq < first_read
    line = journal_records_after(rig.store_root, 0)[0]
    expected = node_file_body(line.rev, line.version, line.payload)
    assert (rig.store_root / "nodes" / "electrical.motor.json").read_text() == expected


def test_the_diff_names_a_write_by_a_role_that_does_not_own_the_node(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    store = Store(rig.store_root)
    assert store.write_node(node("control.loop", owner="control"), "control").accepted
    store.close()
    found = rig.keeper.divergences(2, "electrical")
    rig.keeper.close()
    assert len(found) == 1 and "control.loop" in found[0] and "'control'" in found[0]
    assert (rig.store_root / JOURNAL_NAME).exists()


def test_an_unwithdrawn_proposal_is_the_same_finding_on_every_attempt(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    dispatcher = GitDispatcher(
        rig.run, proposals={1: {"control.loop": node("control.loop", owner="control")}}
    )
    loop = rig.loop(dispatcher)
    loop.run()
    open_items = loop.queue.open_items()
    loop.close()
    rejected = [e for e in rig.events() if isinstance(e, AttemptRejected)]
    assert [e.repeats_previous for e in rejected] == [False, True, True]
    assert {e.finding_key for e in rejected} == {"proposal|control.loop|-"}
    assert len(open_items) == 1 and rig.gate.calls == 0
