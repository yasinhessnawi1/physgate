"""An incident with no halt after it is followed by its halt, and by nothing else.

The process that finds an incident writes it, then the halt. A process killed between the two
leaves the incident on the record without its halt. Whatever the run would have done next, its
next step is then that halt, written from the recorded incident's subtask and cause: no second
incident, no environment line, no session, no contract result and no completion, even where what
the incident found is gone by the time another process takes over. The run then reads as it
would have, had the process not been killed.

Shown at the three steps that halt with no attempt in progress: a completion step and a dispatch,
each under a role register with two owners of completion (which only a register patched in a
process can hold), and a contract step over a canonical journal that ends before the recorded
revision. And with an attempt in progress, taken over by a resume: a foreign journal line found
at a session's end, which the resume's own journal check would find again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeGraph, KilledError, Rig, plan
from test_a_module_is_complete_only_as_integration_declared_it_and_every_precondition_holds import (
    INTEG,
    INTEGRATION,
    Installed,
    declaring,
)
from test_a_module_is_complete_only_as_integration_declared_it_and_every_precondition_holds import (
    rig_for as completion_rig,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    hooked,
    start,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    rig_for as contract_rig,
)

from physgate import roles
from physgate.orchestrator.events import (
    ContractTested,
    Event,
    Halted,
    Incident,
    Resumed,
    StageEntered,
    WorktreeRemoved,
    read_events,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.replay import replay
from physgate.roles import CrossCuttingRole
from physgate.state.store import JOURNAL_NAME

#: A second owner of completion, which only a register patched in a process can hold.
CLOSER = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    # The contract step's run plans sizing's role, as the register will hold it once sizing ships.
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def dies_before(monkeypatch: pytest.MonkeyPatch, loop: Loop, pick: Callable[[Event], bool]) -> None:
    """The process dies as it is about to write the first line ``pick`` chooses."""
    emit = loop._emit  # noqa: SLF001 - the loop's own writer

    def emitting(event: Event) -> None:
        if pick(event):
            raise KilledError
        emit(event)

    monkeypatch.setattr(loop, "_emit", emitting)


def before_a_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """A run killed as it was about to write its first completion line."""
    rig = completion_rig(tmp_path, dispatcher=Installed())
    loop = rig.open()
    declaring(monkeypatch, loop, ("s1", "s2"), kill_at_completion=0)
    loop.start([*plan("s1", "s2"), INTEGRATION])
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    return rig


def before_a_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """A run killed as it was about to dispatch integration's subtask, after the call."""
    rig = completion_rig(tmp_path, dispatcher=Installed())
    loop = rig.open()
    dies_before(monkeypatch, loop, lambda e: isinstance(e, StageEntered) and e.subtask_id == INTEG)
    loop.start([*plan("s1", "s2"), INTEGRATION])
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    return rig


def before_a_contract_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """A run killed as it was about to write its first contract result."""
    rig = contract_rig(tmp_path, dispatcher=Installed())
    loop = rig.open()
    hooked(monkeypatch, loop, kill=lambda e, _: isinstance(e, ContractTested))
    start(loop)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    return rig


POINTS: dict[str, Callable[[Path, pytest.MonkeyPatch], Rig]] = {
    "a completion": before_a_completion,
    "a dispatch": before_a_dispatch,
    "a contract step": before_a_contract_step,
}


def the_cause(
    point: str, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> tuple[Callable[[], Any], Callable[[], Any]]:
    """What makes the next step halt: put in place, and taken away again."""
    if point == "a contract step":
        journal = rig.diff.root / JOURNAL_NAME
        whole = journal.read_bytes()
        short = b"".join(whole.splitlines(keepends=True)[:-1])  # fw's node, the last line, gone
        return (lambda: journal.write_bytes(short)), (lambda: journal.write_bytes(whole))
    return (
        lambda: monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER),
        lambda: monkeypatch.delitem(roles.ROLES, CLOSER.name),
    )


def halting(rig: Rig, monkeypatch: pytest.MonkeyPatch, *, killed: bool) -> None:
    """The process that finds the incident: it halts, or dies between the incident and the halt."""
    loop = rig.open()
    if killed:
        dies_before(monkeypatch, loop, lambda e: isinstance(e, Halted))
        with pytest.raises(KilledError):
            loop.run()
    else:
        assert loop.run().kind == "halted"
    loop.close()


def comparable(events: list[Event]) -> list[dict[str, Any]]:
    """Every line but its place and its time."""
    return [e.model_dump(exclude={"seq", "ts"}) for e in events]


@pytest.mark.parametrize("gone", [False, True], ids=["the cause still there", "the cause gone"])
@pytest.mark.parametrize("point", POINTS)
def test_a_kill_between_an_incident_and_its_halt_resumes_to_the_halt_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, gone: bool
) -> None:
    # The run as it would have been: the process that finds the incident is not killed.
    reference = POINTS[point](tmp_path / "reference", monkeypatch)
    put, take = the_cause(point, reference, monkeypatch)
    put()
    halting(reference, monkeypatch, killed=False)
    take()
    # The same run, with that process killed between its incident and its halt.
    rig = POINTS[point](tmp_path / "cut", monkeypatch)
    put, take = the_cause(point, rig, monkeypatch)
    put()
    halting(rig, monkeypatch, killed=True)
    cut = read_events(rig.run_dir / "events.jsonl")
    assert isinstance(cut[-1], Incident)
    owed = replay(cut).next_step().kind
    if gone:
        take()
    fresh = rig.open()
    assert fresh.run().kind == "halted"
    fresh.close()
    if not gone:
        take()
    events = read_events(rig.run_dir / "events.jsonl")
    assert [type(e) for e in events if isinstance(e, Incident | Halted)] == [Incident, Halted]
    # The process that took over wrote the halt, then removed the merged subtasks' worktrees, as
    # at any halt. It wrote nothing else: no environment line, since it spawns nothing.
    later = events[len(cut) :]
    assert isinstance(later[0], Halted)
    assert all(isinstance(e, WorktreeRemoved) for e in later[1:])
    assert comparable(events) == comparable(read_events(reference.run_dir / "events.jsonl"))
    assert (owed, replay(events).next_step().kind) == ("halt", "halted")


@dataclass
class _Journal(FakeGraph):
    """A canonical journal a line can be appended to while a session runs."""

    lines: list[Any] = field(default_factory=list)

    def records_after(self, revision: int) -> list[Any]:
        return [line for line in self.lines if line.rev > revision]


def foreign_at_a_session_end(tmp_path: Path) -> Rig:
    """A run whose first session leaves a journal line nobody intended: found at its end."""
    journal = _Journal()
    foreign = SimpleNamespace(rev=1, op="write", node_id="electrical.x", payload={})
    rig = Rig(
        tmp_path,
        diff=journal,
        dispatcher=FakeDispatcher(during={1: lambda: journal.lines.append(foreign)}),
    )
    loop = rig.open()
    loop.start(plan("s1"))
    loop.close()
    return rig


def test_a_kill_between_a_session_end_s_incident_and_its_halt_resumes_to_the_halt_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = foreign_at_a_session_end(tmp_path / "reference")
    halting(reference, monkeypatch, killed=False)
    rig = foreign_at_a_session_end(tmp_path / "cut")
    halting(rig, monkeypatch, killed=True)
    cut = read_events(rig.run_dir / "events.jsonl")
    assert isinstance(cut[-1], Incident) and cut[-1].cause == "foreign_journal_line"
    assert cut[-1].subtask_id == "s1"
    state = replay(cut)
    assert state.next_step().kind == "halt"
    assert state.interrupted() is not None, "the attempt is in progress: a resume takes it over"
    fresh = rig.open()
    try:
        said = fresh.resume().kind
    except Exception as exc:  # noqa: BLE001 - any escape is the finding
        said = f"raised {exc!r}"
    finally:
        fresh.close()
    assert said == "halted", said
    events = read_events(rig.run_dir / "events.jsonl")
    assert [type(e) for e in events if isinstance(e, Incident | Halted)] == [Incident, Halted]
    later = events[len(cut) :]
    assert [type(e) for e in later] == [Halted], [e.kind for e in later]
    assert not any(isinstance(e, Resumed) for e in later)
    assert comparable(events) == comparable(read_events(reference.run_dir / "events.jsonl"))
    assert replay(events).next_step().kind == "halted"
