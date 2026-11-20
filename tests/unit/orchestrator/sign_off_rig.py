"""A run with a module whose role owes a person's sign-off, over the loop's fakes.

``c1`` is a control module, ``s2`` an electrical one, and integration declares both complete.
The loop and replay are the real ones; the sessions, gate, reviewer and graph are the fakes every
loop test uses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeChanges, FakeDispatcher, FakeGate, FakeGraph, Rig

from physgate.orchestrator import record
from physgate.orchestrator.declaration import Declaration
from physgate.orchestrator.events import Event, OsLayerChecked, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import DecompositionSummary, PlanEntry
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present
from physgate.state.store import JournalLine

INTEG = "integ"
CONTROL = "c1"
ELECTRICAL = "s2"
DIGEST = "d" * 64
ROLES = ("control", "electrical", "integration")
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")


def entry(subtask_id: str, role: str, module_dir: str | None = None) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id,
        spec_path=f"specs/{subtask_id}.md",
        assigned_role=role,
        module_dir=module_dir or f"modules/{subtask_id}",
    )


INTEGRATION = entry(INTEG, "integration", "modules/integration")
PLAN = (entry(CONTROL, "control"), entry(ELECTRICAL, "electrical"), INTEGRATION)


def rig_for(tmp_path: Path, *, acts: bool = False, **fields: Any) -> Rig:
    """A rig whose run pins every role of :data:`PLAN`, acting on decisions or recording them.

    ``config`` replaces fields of the run's configuration.
    """
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(ROLES, "claude-sonnet-5"),
        reviewers=dict.fromkeys(ROLES, "claude-opus-5-5"),
    )
    config: dict[str, Any] = {"models": models}
    if acts:
        config |= {"queue_decisions": "act", "os_layer": PRESENT}
    config |= fields.pop("config", {})
    tmp_path.mkdir(parents=True, exist_ok=True)
    fields.setdefault("dispatcher", FakeDispatcher(trajectories=tmp_path / "sessions"))
    return Rig(tmp_path, config_overrides=config, **fields)


def layer(loop: Loop) -> None:
    """The OS layer, present, as the command records it before anything is driven."""
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": PRESENT, "as_recorded": None}
        )
    )


def declaring(
    loop: Loop, modules: Sequence[str], then: Sequence[str] | None = (ELECTRICAL,)
) -> None:
    """Have integration's attempts declare ``modules``, as the change check reads them.

    With ``then``, every attempt after integration's first declares ``then`` instead: an
    integration told by the change check that a module's sign-off is owed leaves it out.
    """
    changes = loop._changes  # noqa: SLF001 - the rig's checker
    assert isinstance(changes, FakeChanges)
    changes.declares[INTEG] = Declaration(modules=tuple(modules), sha256=DIGEST)
    if then is None:
        return
    check = changes.check
    seen: list[str] = []

    def checked(subtask_id: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if subtask_id == INTEG:
            if seen:
                changes.declares[INTEG] = Declaration(modules=tuple(then), sha256=DIGEST)
            seen.append(subtask_id)
        return check(subtask_id, *args, **kwargs)

    changes.check = checked  # type: ignore[method-assign]


def finished(
    tmp_path: Path,
    *,
    plan: Sequence[PlanEntry] = PLAN,
    declared: Sequence[str] = (CONTROL, ELECTRICAL),
    gate: FakeGate | None = None,
    acts: bool = False,
    then: Sequence[str] | None = (ELECTRICAL,),
    **fields: Any,
) -> list[Event]:
    """The run of ``plan`` driven to its end, integration declaring ``declared``; its lines.

    An attempt of integration after its first declares ``then`` (:func:`declaring`).
    """
    rig = rig_for(tmp_path, acts=acts, gate=gate or FakeGate(), **fields)
    loop = rig.open()
    declaring(loop, declared, then)
    loop.start(list(plan))
    if acts:
        layer(loop)
    loop.run()
    loop.close()
    return read_events(tmp_path / "events.jsonl")


# --- a run whose modules write values -----------------------------------------------------------

SIZING = "z0"
CLOSING = "zc"
LOOP = "ctl.loop"
PLANT = "sizing.plant"
OTHER = "sizing.bus"


def node(
    node_id: str, domain: str, owner: str, constrains: Sequence[str] = (), **quantities: Any
) -> dict[str, Any]:
    """A node as a session proposes it; each quantity ``name=(value, unit)``."""
    return {
        "id": node_id,
        "kind": "component" if domain == "cross" else "module",
        "domain": domain,
        "owner_role": owner,
        "quantities": {
            name: {"value": v, "unit": u, "source": "derived", "written_by": owner}
            for name, (v, u) in quantities.items()
        },
        "constrains": list(constrains),
        "geometry_hash": "g0",
        "updated": "2026-11-20T00:00:00Z",
    }


def control_loop(phase: float = 0.8, gain: float = 2.4) -> dict[str, Any]:
    return node(
        LOOP, "control", "control", phase_margin=(phase, "rad"), gain_margin=(gain, "1"),
        loop_gain=(3.0, "1"), sample_rate=(200, "Hz"),
    )  # fmt: skip


def plant(mass: float = 0.32) -> dict[str, Any]:
    return node(PLANT, "cross", "sizing", (LOOP,), mass=(mass, "kg"))


#: A cross node that bounds no module: written by sizing, constraining nothing.
BUS = node(OTHER, "cross", "sizing", (), supply_voltage=(7.4, "V"))


@dataclass
class JournalGraph(FakeGraph):
    """The fake graph with a canonical journal: each subtask's proposals, written as merged."""

    journal: list[JournalLine] = field(default_factory=list)
    #: Per subtask, what each of its attempts proposes, in turn; the last repeats.
    writes: dict[str, list[list[dict[str, Any]]]] = field(default_factory=dict)
    asked: dict[str, int] = field(default_factory=dict)

    def records_after(self, revision: int) -> list[Any]:
        return [line for line in self.journal if line.rev > revision]

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        script = self.writes.get(subtask_id, [])
        if not script:
            return []
        n = self.asked.get(subtask_id, 0)
        self.asked[subtask_id] = n + 1
        return [dict(p) for p in script[min(n, len(script) - 1)]]

    def write(self, payload: dict[str, Any], role: str) -> int:
        node_id = payload["id"]
        version = 1 + max((ln.version for ln in self.journal if ln.node_id == node_id), default=0)
        rev = len(self.journal) + 1
        op = "create" if version == 1 else "write"
        self.journal.append(
            JournalLine(rev=rev, op=op, node_id=node_id, version=version, payload=payload)  # type: ignore[arg-type]
        )
        return rev


#: The plan of a run whose modules write: sizing, the control module, an electrical one, and
#: integration; with ``closing``, sizing's closing pass after the domain modules.
def journal_plan(*, closing: bool = False) -> list[PlanEntry]:
    first = [entry(SIZING, "sizing"), entry(CONTROL, "control"), entry(ELECTRICAL, "electrical")]
    tail = [entry(CLOSING, "sizing", f"modules/{SIZING}")] if closing else []
    return [*first, *tail, INTEGRATION]


def journal_rig(tmp_path: Path, *, acts: bool = True, **fields: Any) -> tuple[Rig, JournalGraph]:
    graph = JournalGraph(
        journal=[JournalLine(rev=1, op="create", node_id=OTHER, version=1, payload=BUS)]
    )
    graph.writes[SIZING] = [[plant()]]
    graph.writes[CONTROL] = [[control_loop()]]
    roles = (*ROLES, "sizing")
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(roles, "claude-sonnet-5"),
        reviewers=dict.fromkeys(roles, "claude-opus-5-5"),
    )
    config = {"models": models, **fields.pop("config", {})}
    rig = rig_for(tmp_path, acts=acts, diff=graph, config=config, **fields)
    return rig, graph


def journal_start(rig: Rig, *, closing: bool = False, acts: bool = True) -> Loop:
    """The run started on :func:`journal_plan` at the journal's head, ready to drive."""
    loop = rig.open()
    declaring(loop, (CONTROL, ELECTRICAL))
    plan = journal_plan(closing=closing)
    summary = DecompositionSummary(
        session_id="decomp-1",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=len(plan),
        interface_nodes=("iface.none",),
        spec_commit="a" * 40,
        head_revision=1,
    )
    loop.record.start(plan, decomposed=summary)
    if acts:
        layer(loop)
    return loop


@pytest.fixture
def before_the_sign_off_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each run as one recorded before the sign-off rule table: it owes no sign-off.

    For tests about another precondition or another path, whose runs plan a control module and
    hold its completion to that alone; what a sign-off does is tested with the rule in force.
    """
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)


def sign_every_open_item(run_dir: Path, note: str | None = None) -> list[str]:
    """A person approves every sign-off item no decision was recorded on; their ids, in order.

    Each bound to the line the listing gives, as a person decides it from the listing.
    """
    view = read_queue(run_dir)
    signed = []
    for item in view.open_items():
        if item.source != "sign_off":
            continue
        shown = ShownItem(
            item_sha256=view.digests[item.item_id],
            trajectories=statuses_now(run_dir, item.item_id),
        )
        record_decision(
            run_dir,
            item.item_id,
            person=PersonDecision(verb="approve", note=note),
            resolved_by="yasin",
            shown=shown,
        )
        signed.append(item.item_id)
    return signed


def signing(drive: Callable[[], str], run_dir: Path) -> str:
    """How the run ends when a person signs every sign-off item each time it waits on one.

    ``drive`` runs a fresh process to the step it ends at. A wait with no sign-off item open is
    another wait, and ends it as it is.
    """
    step = drive()
    while step == "wait" and sign_every_open_item(run_dir):
        step = drive()
    return step


@pytest.fixture
def a_person_signing_at_every_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person who approves every open sign-off item each time the loop may take a decision.

    For tests of another path through a run that acts and plans a control module, which must go
    on past the sign-off's wait in one process: the approves are on the record, and each is taken
    where any decision is.
    """
    take = Loop._take_decisions  # noqa: SLF001 - wrapped, never replaced

    def signed_first(self: Loop) -> bool:
        sign_every_open_item(self.run_dir)
        return take(self)

    monkeypatch.setattr(Loop, "_take_decisions", signed_first)
