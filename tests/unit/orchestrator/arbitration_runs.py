"""Runs over fakes whose attempts dispute a cross node's values, for the arbitration stage's rows.

The canonical journal is a list the fake graph serves: revision 1 is the bus node as it stood
before the run, and a sizing subtask planned first writes it again at revision 2. ``s1`` is the
domain subtask, which the gate judges by attempt (``gate`` lists its verdicts), and whose change
checks read the disputes ``script`` gives, one entry per check.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loop_fakes import (
    FakeChanges,
    FakeDispatcher,
    FakeGate,
    FakeGraph,
    FakeReviewer,
    Rig,
    failing_gate_result,
    passing_gate_result,
)
from test_a_queue_decision_acts_at_a_boundary import _layer

from physgate.orchestrator.dispute import Dispute
from physgate.orchestrator.events import Event, parse_events, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import ChangeCheck
from physgate.orchestrator.protocols import Artefact, GateResult, QuantityRef, RunningGateMode
from physgate.orchestrator.record import DecompositionSummary, PlanEntry
from physgate.orchestrator.replay import replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.orchestrator.trajectory import seal
from physgate.oslayer.probe import Present
from physgate.series.seal import SessionSeries
from physgate.state.store import JournalLine

NODE = "sizing.bus"
BIG = 10**399 + 7
#: What the sessions' own words carry, so a row can say where they never reach.
REASON = "REASON-CANARY the domain needs more headroom"
SOURCE = "SOURCE-CANARY datasheet table 4"
WRITER = "WRITER-CANARY sizing pass"
STREAM = b'{"type": "assistant", "text": "STREAM-CANARY sizing worked this out"}\n'
CANARIES = ("REASON-CANARY", "SOURCE-CANARY", "WRITER-CANARY", "STREAM-CANARY")


def dispute(name: str, value: float, unit: str) -> Dispute:
    position = QuantityRef(node_id=NODE, name=name, value=value, unit=unit)
    return Dispute(position=position, reason=REASON)


RAIL = dispute("peak_current", 5, "A")
BUS = dispute("supply_voltage", 24, "V")
TWO = (RAIL, BUS)


def bus(
    volts: float,
    amps: float,
    *,
    source: str = "datasheet",
    by: str = "sizing",
    unit: str | None = None,
) -> dict[str, Any]:
    """The bus node; with ``unit``, both quantities are written in that unit as it is spelt."""

    def q(value: float, named: str) -> dict[str, Any]:
        return {"value": value, "unit": unit or named, "source": source, "written_by": by}

    return {
        "id": NODE,
        "kind": "component",
        "domain": "cross",
        "owner_role": "sizing",
        "quantities": {"peak_current": q(amps, "A"), "supply_voltage": q(volts, "V")},
        "geometry_hash": "g0",
        "updated": "2026-10-30T00:00:00Z",
    }


#: The node before the run, and as the sizing subtask writes it.
BEFORE = bus(12, 2)
SIZED = bus(BIG, 3, source=SOURCE, by=WRITER)


@dataclass
class JournalGraph(FakeGraph):
    """The fake graph with a canonical journal, and the sizing subtask's one write."""

    journal: list[JournalLine] = field(
        default_factory=lambda: [
            JournalLine(rev=1, op="create", node_id=NODE, version=1, payload=BEFORE)
        ]
    )
    writes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def records_after(self, revision: int) -> list[Any]:
        return [line for line in self.journal if line.rev > revision]

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        return list(self.writes.get(subtask_id, ()))

    def write(self, payload: dict[str, Any], role: str) -> int:
        node = payload["id"]
        version = 1 + max((ln.version for ln in self.journal if ln.node_id == node), default=0)
        rev = len(self.journal) + 1
        op = "create" if version == 1 else "write"
        self.journal.append(
            JournalLine(rev=rev, op=op, node_id=node, version=version, payload=payload)  # type: ignore[arg-type]
        )
        return rev


@dataclass
class PerAttempt(FakeGate):
    """The gate's verdict on ``s1`` by attempt, the same however often an attempt is judged."""

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.seen.append(artefact)
        at = artefact.attempt - 1
        failing = artefact.subtask_id == "s1" and at < len(self.verdicts)
        if failing and self.verdicts[at] == "fail":
            return failing_gate_result(mode)
        return passing_gate_result(mode)


@dataclass
class Scripted(FakeChanges):
    """``s1``'s disputes, one entry per change check of it; the last entry repeats."""

    script: list[tuple[Dispute, ...]] = field(default_factory=lambda: [TWO])
    checked: int = 0

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
    ) -> ChangeCheck:
        if subtask_id == "s1":
            self.disputes["s1"] = self.script[min(self.checked, len(self.script) - 1)]
            self.checked += 1
        return super().check(subtask_id, attempt_commit, role, series=series)


@dataclass
class Streaming(FakeDispatcher):
    """Seals a canary into the sizing subtask's own stream."""

    def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's types
        report = super().run(request, on_spawn)
        if request.subtask_id == "z0" and self.trajectories is not None and report.trajectory:
            path = Path(report.trajectory)
            path.write_bytes(path.read_bytes() + STREAM)
            return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})
        return report


PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ACT = {"queue_decisions": "act", "os_layer": PRESENT}


def entry(subtask_id: str, role: str) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id, spec_path=f"specs/{subtask_id}.md", assigned_role=role,
        module_dir=f"modules/{subtask_id}",
    )  # fmt: skip


def entries(sizing: bool) -> list[PlanEntry]:
    return [entry("z0", "sizing"), entry("s1", "electrical")][0 if sizing else 1 :]


def rig_of(
    run_dir: Path,
    *,
    mode: str = "on",
    gate: Sequence[str] = (),
    review: Sequence[str] = (),
    reviewer: FakeReviewer | None = None,
    script: Sequence[tuple[Dispute, ...]] = (TWO,),
    sizing: bool = True,
) -> Rig:
    run_dir.mkdir(parents=True, exist_ok=True)
    roles = {"electrical": "claude-sonnet-5"} | ({"sizing": "claude-sonnet-5"} if sizing else {})
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=roles,
        reviewers=dict.fromkeys(roles, "claude-opus-5-5"),
    )
    graph = JournalGraph()
    graph.writes["z0"] = [SIZED]
    return Rig(
        run_dir,
        gate_mode=mode,  # type: ignore[arg-type]
        gate=PerAttempt(verdicts=list(gate)),
        reviewer=reviewer or FakeReviewer(verdicts=list(review)),
        dispatcher=Streaming(trajectories=run_dir / "sessions"),
        changes=Scripted(script=list(script)),
        diff=graph,
        config_overrides={"models": models, **ACT},
    )


def started(
    rig: Rig, *, sizing: bool = True, plan: list[PlanEntry] | None = None, head: int = 1
) -> Loop:
    """The run started on ``plan`` (by default ``s1``, after ``z0`` with ``sizing``) at ``head``."""
    loop = rig.open()
    plan = plan or entries(sizing)
    summary = DecompositionSummary(
        session_id="decomp-1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.bus",),
        spec_commit="a" * 40,
        head_revision=head,
    )
    loop.record.start(plan, decomposed=summary)
    _layer(loop)
    return loop


def run(
    rig: Rig,
    *,
    sizing: bool = True,
    kill: Callable[[Event], bool] | None = None,
    plan: list[PlanEntry] | None = None,
    head: int = 1,
) -> str:
    """Drive the run to its end; with ``kill``, the process dies before the first line it names."""
    loop = started(rig, sizing=sizing, plan=plan, head=head)
    if kill is not None:
        emit = loop._emit
        died: list[bool] = []

        def dies(line: Event) -> None:
            if not died and kill(line):
                died.append(True)
                raise KilledByRowError
            emit(line)

        setattr(loop, "_emit", dies)  # noqa: B010 - a process that dies at a line
        try:
            loop.run()
        except KilledByRowError:
            loop.close()
            return "killed"
    kind = loop.run().kind
    loop.close()
    return kind


def resume(rig: Rig) -> str:
    loop = rig.open()
    _layer(loop)
    kind = loop.resume().kind
    loop.close()
    return kind


def driven(rig: Rig, how: Callable[[Rig], object] = run) -> None:
    """Drive the run to its end; a line the replay refuses to the loop's own face is a finding."""
    try:
        how(rig)
    except Exception as exc:  # noqa: BLE001 - any escape is the finding
        raise AssertionError(f"the loop's own run escaped: {exc!r}") from None


class KilledByRowError(Exception):
    """The process a row kills, at the line it names."""


def events_of(rig: Rig) -> list[Event]:
    return read_events(rig.run_dir / "events.jsonl")


def resequenced(events: Sequence[Event]) -> list[Event]:
    return [e.model_copy(update={"seq": i}) for i, e in enumerate(events)]


def refusal(events: Sequence[Event]) -> str | None:
    """Why the lines, read from disk as a fresh process reads them, do not replay; or ``None``."""
    data = b"".join(e.model_dump_json().encode() + b"\n" for e in resequenced(events))
    try:
        replay(parse_events(data, log="events.jsonl"))
    except CorruptEventLogError as exc:
        reason: str = exc.context.get("reason", str(exc))
        return reason
    except Exception as exc:  # noqa: BLE001 - any other escape is a refusal no rule gave
        return f"raised {type(exc).__name__}: {exc}"
    return None
