"""A process killed after a divergence check that named divergences halts where the run would have.

A step's check of the graph that finds a divergence writes three lines: the check, the incident
under its cause, and the halt. A kill can split them. The check then stands on the record without
the incident, or the incident without the halt. Nothing resumes the attempt, since its check is
made, and a clean check would have made the subtask done. With the check alone on the record,
the next process takes the attempt up at its diff point and finds the check already there; with
the incident on it too, the incident's halt is the run's next step. Either way it writes what
the uninterrupted process would have written next, and nothing else: the incident, under the
same cause rule and with the same detail, then the halt; or the halt alone. It never makes the
check twice.

Every line is synced before the loop acts on it, and the fakes give the same answers to any
process, so a log cut after line k is what a process killed between lines k and k+1 leaves.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGraph, Rig, plan
from test_a_module_is_complete_only_as_integration_declared_it_and_every_precondition_holds import (
    INTEG,
    INTEGRATION,
    Installed,
    completions,
    declaring,
    rig_for,
)

from physgate.orchestrator.events import (
    DiffChecked,
    EnvironmentRecorded,
    Event,
    Halted,
    Incident,
    read_events,
)
from physgate.orchestrator.replay import replay
from physgate.state.divergence import COMPLETION_OWNER_NODE, CROSS_NODE, Divergence

#: A node of another role, changed during the step: a write past the store's own guard.
FOREIGN = Divergence(
    node_id="control.motor", revision=7, owner_role="control", acting_role="electrical"
)
#: A cross node changed by a domain role: a duty's breach, which the store accepts.
CROSS = Divergence(
    node_id="electrical.motor_current",
    revision=8,
    owner_role="electrical",
    acting_role="electrical",
    reason=CROSS_NODE,
    detail="electrical.motor_current is of the cross domain; only the sizing role writes them",
)
#: The same two kinds in a step of integration's subtask.
FOREIGN_INTEGRATION = Divergence(
    node_id="electrical.motor", revision=9, owner_role="electrical", acting_role="integration"
)
COMPLETION = Divergence(
    node_id="integration.check",
    revision=9,
    owner_role="integration",
    acting_role="integration",
    reason=COMPLETION_OWNER_NODE,
    detail="the integration role owns the completion declaration; it writes no node",
)

#: Each run: the subtask whose step diverges, its role, what the check finds, and the cause.
CASES: dict[str, tuple[str, str, Divergence, str]] = {
    "a domain subtask, a write past the store's guard": (
        "s1",
        "electrical",
        FOREIGN,
        "cross_role_write",
    ),
    "a domain subtask, a duty's breach": ("s1", "electrical", CROSS, "duty_breach"),
    "integration's subtask, a write past the store's guard": (
        INTEG,
        "integration",
        FOREIGN_INTEGRATION,
        "cross_role_write",
    ),
    "integration's subtask, a duty's breach": (INTEG, "integration", COMPLETION, "duty_breach"),
}


@dataclass
class Diverging(FakeGraph):
    """Names ``found`` at every check of a step of ``role``, whichever process asks.

    The graph keeps a write once it is made, so a check made again finds it again.
    """

    role: str = "electrical"
    found: tuple[Divergence, ...] = field(default_factory=tuple)

    def divergences(self, since: int, acting_role: str) -> tuple[Divergence, ...]:
        self.calls.append((since, acting_role))
        return self.found if acting_role == self.role else ()


def _rig(run_dir: Path, case: str) -> Rig:
    _, role, found, _ = CASES[case]
    return rig_for(run_dir, dispatcher=Installed(), diff=Diverging(role=role, found=(found,)))


def reference(run_dir: Path, case: str, monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    """The run without a kill: it halts at the diverging step's check."""
    subtask = CASES[case][0]
    rig = _rig(run_dir, case)
    loop = rig.open()
    if subtask == INTEG:
        declaring(monkeypatch, loop, ("s1", "s2"))
        loop.start([*plan("s1", "s2"), INTEGRATION])
    else:
        loop.start(plan("s1", "s2"))
    assert loop.run().kind == "halted"
    loop.close()
    return read_events(run_dir / "events.jsonl")


def cut(full: Path, into: Path, lines: int) -> Path:
    """``full`` as a process killed after its first ``lines`` log lines left it."""
    shutil.copytree(full, into, ignore=shutil.ignore_patterns("events.jsonl", "ledger.jsonl"))
    kept = (full / "events.jsonl").read_bytes().splitlines(keepends=True)[:lines]
    (into / "events.jsonl").write_bytes(b"".join(kept))
    return into


def as_written(events: list[Event]) -> list[dict[str, Any]]:
    """Each line as its fields say it, without its place in the file or its time."""
    return [e.model_dump(mode="json", exclude={"seq", "ts"}) for e in events]


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("left", ["the check", "the check and its incident"])
def test_a_kill_after_a_check_that_named_divergences_resumes_to_the_runs_own_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, left: str
) -> None:
    subtask, _, found, cause = CASES[case]
    full = reference(tmp_path / "full", case, monkeypatch)
    (check,) = [e for e in full if isinstance(e, DiffChecked) and e.divergences]
    assert check.subtask_id == subtask and check.divergences == (str(found),)
    # Then the incident and the halt; a run that merged subtasks before it also removes their
    # worktrees as it stops.
    incident, halted = full[check.seq + 1 : check.seq + 3]
    assert isinstance(incident, Incident) and isinstance(halted, Halted)
    assert (incident.subtask_id, incident.cause, incident.detail) == (subtask, cause, str(found))
    k = check.seq + 1 if left == "the check" else check.seq + 2
    run_dir = cut(tmp_path / "full", tmp_path / "cut", k)
    state = replay(read_events(run_dir / "events.jsonl"))
    step = state.next_step()
    if left == "the check":
        assert (step.kind, step.subtask_id, step.point) == ("attempt", subtask, "diff")
    else:
        assert step.kind == "halt"  # the incident's halt is owed, and nothing else
    assert state.interrupted() is None
    rig = _rig(run_dir, case)
    fresh = rig.open()
    assert fresh.run().kind == "halted"
    fresh.close()
    events = read_events(run_dir / "events.jsonl")
    # What differs from the run without a kill: the process that took over at the attempt's
    # diff point recorded its environment, once, before that first step of an attempt, as every
    # process does; one whose first step is the owed halt spawns nothing and records none. Each
    # line after it sits one place later and carries this process's time.
    added = events[k:]
    environment = [e for e in added if isinstance(e, EnvironmentRecorded)]
    assert len(environment) == (1 if left == "the check" else 0)
    assert added[: len(environment)] == environment
    rest = added[len(environment) :]
    assert as_written(rest) == as_written(full[k:])
    # So the check stands once, the incident once, under the same cause and detail, and the halt.
    assert [e.seq for e in events if isinstance(e, DiffChecked) and e.divergences] == [check.seq]
    assert len([e for e in events if isinstance(e, Incident)]) == 1
    assert replay(events).next_step().kind == "halted"
    assert completions(events) == []
    # The graph was asked again only where the incident was owed: its cause is read from it.
    assert len(rig.diff.calls) == (1 if left == "the check" else 0)
