"""A declared quantity at the journal's head that no landed parts write wrote halts the run.

ARCH-122. Only the parts writer declares a quantity, through the store's ``declare``, and each
of its writes lands on the record with the digest of its whole payload. After an attempt's
journal step, and whenever a process accounts for the journal, every declared quantity at the
head must be one a landed parts write wrote, field for field, at the node it wrote. One that is
not reached the journal past the store's guard: an integrity fault, an incident and a halt that
names it, never a repair and never a merge. A process killed between the landed write and the
check makes the check when it next starts, and the log alone rebuilds the halted state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import refusal
from loop_fakes import FakeGraph, KilledError, Rig, plan

from physgate.orchestrator.events import (
    EventLog,
    Halted,
    Incident,
    Merged,
    WriteDone,
    read_events,
)
from physgate.orchestrator.replay import RunState
from physgate.state.divergence import Divergence
from physgate.state.schema import DECLARED_SOURCE
from physgate.state.store import JournalLine

RECORD = {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "yasin"}


def q(value: float, unit: str, source: str = "datasheet", **more: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"value": value, "unit": unit, "source": source, "written_by": "electrical", **more}


def declared(value: float, unit: str) -> dict[str, Any]:
    return q(value, unit, DECLARED_SOURCE, declared=dict(RECORD))


def node(node_id: str, quantities: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": quantities,
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "none",
        "updated": "2026-11-14",
    }


HONEST = node("electrical.motor", {"stall_current": q(2.4, "A")})
FORGED = node("electrical.motor", {"stall_current": q(2.4, "A"), "mass": declared(0.4, "kg")})


@dataclass
class Journal(FakeGraph):
    """A canonical journal the attempt's writes land in, each as the store would append it."""

    lines: list[JournalLine] = field(default_factory=list)
    writes: list[dict[str, Any]] = field(default_factory=list)
    #: Kill the process once, right after the store accepted a write and before its done line.
    kill_after_write: bool = False

    def records_after(self, revision: int) -> list[Any]:
        return [line for line in self.lines if line.rev > revision]

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        return [json.loads(json.dumps(p)) for p in self.writes]

    def write(self, payload: dict[str, Any], role: str) -> int:
        node_id = str(payload["id"])
        version = 1 + sum(1 for line in self.lines if line.node_id == node_id)
        rev = len(self.lines) + 1
        op = "create" if version == 1 else "write"
        self.lines.append(
            JournalLine(rev=rev, op=op, node_id=node_id, version=version, payload=payload)  # type: ignore[arg-type]
        )
        if self.kill_after_write:
            self.kill_after_write = False
            raise KilledError("after the store accepted the write, before its done line")
        return rev


def rig_of(tmp_path: Path, written: dict[str, Any], *, kill: bool = False) -> Rig:
    return Rig(tmp_path, diff=Journal(writes=[written], kill_after_write=kill))


def events(tmp_path: Path) -> list[Any]:
    return list(read_events(tmp_path / "events.jsonl"))


def incidents(tmp_path: Path) -> list[Incident]:
    return [e for e in events(tmp_path) if isinstance(e, Incident)]


def merged(tmp_path: Path) -> list[Merged]:
    return [e for e in events(tmp_path) if isinstance(e, Merged)]


def test_an_attempt_whose_journal_step_lands_a_declared_quantity_halts_before_its_merge(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path, FORGED)
    loop = rig.open()
    loop.start(plan("s1"))
    kind = loop.run().kind
    loop.close()
    assert kind == "halted"
    (incident,) = incidents(tmp_path)
    assert incident.cause == "foreign_journal_line"
    assert incident.subtask_id == "s1"
    assert "electrical.motor" in incident.detail and "mass" in incident.detail
    assert merged(tmp_path) == []
    (halted,) = [e for e in events(tmp_path) if isinstance(e, Halted)]
    assert halted.reason == "incident"


def test_an_attempt_that_lands_no_declared_quantity_merges_as_before(tmp_path: Path) -> None:
    rig = rig_of(tmp_path, HONEST)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    assert incidents(tmp_path) == []
    assert len(merged(tmp_path)) == 1


def test_a_process_killed_between_the_landed_write_and_the_check_halts_when_it_resumes(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path, FORGED, kill=True)
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    assert [e for e in events(tmp_path) if isinstance(e, WriteDone)] == []
    again = rig.open()
    kind = again.resume().kind
    again.close()
    assert kind == "halted"
    (incident,) = incidents(tmp_path)
    assert incident.cause == "foreign_journal_line"
    assert "mass" in incident.detail
    assert merged(tmp_path) == []
    # The write is the run's own and is accounted for before the check names what it holds.
    assert len(rig.diff.lines) == 1  # type: ignore[attr-defined]


def test_a_process_killed_after_an_honest_landed_write_resumes_and_merges(tmp_path: Path) -> None:
    rig = rig_of(tmp_path, HONEST, kill=True)
    loop = rig.open()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    assert incidents(tmp_path) == []
    assert len(merged(tmp_path)) == 1


def test_the_log_alone_rebuilds_the_halted_state_and_no_process_names_it_twice(
    tmp_path: Path,
) -> None:
    rig = rig_of(tmp_path, FORGED)
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    live = loop.state.halted
    loop.close()
    replayed = RunState()
    EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on", state=replayed).close()
    assert live is not None and replayed.halted == live
    assert replayed.next_step().kind == "halted"
    assert refusal(events(tmp_path)) is None
    again = rig.open()
    with pytest.raises(Exception, match="foreign_journal_line"):
        again.resume()
    again.close()
    assert len(incidents(tmp_path)) == 1


@pytest.mark.parametrize("reason", ["declared_fixed", "declared_forged"])
def test_a_step_the_second_line_names_for_a_declared_quantity_halts_as_an_integrity_fault(
    tmp_path: Path, reason: str
) -> None:
    named = Divergence(
        node_id="electrical.motor",
        revision=1,
        owner_role="electrical",
        acting_role="electrical",
        reason=reason,
        detail="mass",
    )
    rig = Rig(tmp_path, diff=FakeGraph(divergent={1: (named,)}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = incidents(tmp_path)
    assert incident.cause == "foreign_journal_line"
    assert reason in incident.detail
