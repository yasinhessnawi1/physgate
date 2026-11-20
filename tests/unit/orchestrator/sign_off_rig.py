"""A run with a module whose role owes a person's sign-off, over the loop's fakes.

``c1`` is a control module, ``s2`` an electrical one, and integration declares both complete.
The loop and replay are the real ones; the sessions, gate, reviewer and graph are the fakes every
loop test uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeChanges, FakeDispatcher, FakeGate, Rig

from physgate.orchestrator import record
from physgate.orchestrator.declaration import Declaration
from physgate.orchestrator.events import Event, OsLayerChecked, read_events
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present

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


def declaring(loop: Loop, modules: Sequence[str]) -> None:
    """Have integration's attempts declare ``modules``, as the change check reads them."""
    changes = loop._changes  # noqa: SLF001 - the rig's checker
    assert isinstance(changes, FakeChanges)
    changes.declares[INTEG] = Declaration(modules=tuple(modules), sha256=DIGEST)


def finished(
    tmp_path: Path,
    *,
    plan: Sequence[PlanEntry] = PLAN,
    declared: Sequence[str] = (CONTROL, ELECTRICAL),
    gate: FakeGate | None = None,
    acts: bool = False,
    **fields: Any,
) -> list[Event]:
    """The run of ``plan`` driven to its end, integration declaring ``declared``; its lines."""
    rig = rig_for(tmp_path, acts=acts, gate=gate or FakeGate(), **fields)
    loop = rig.open()
    declaring(loop, declared)
    loop.start(list(plan))
    if acts:
        layer(loop)
    loop.run()
    loop.close()
    return read_events(tmp_path / "events.jsonl")


@pytest.fixture
def before_the_sign_off_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each run as one recorded before the sign-off rule table: it owes no sign-off.

    For tests about another precondition or another path, whose runs plan a control module and
    hold its completion to that alone; what a sign-off does is tested with the rule in force.
    """
    monkeypatch.setattr(record, "SIGN_OFF_RULES", None)
