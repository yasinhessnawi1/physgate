"""Integration's subtask runs after the system-scope gate, and only its lines may follow that call.

Integration's session reads the system-scope result, so the subtask of the role that owns
completion is dispatched only once the integration call has passed, or failed under
``observe``, or been skipped because the gate is off, and then only when every other subtask
merged. After a blocking failure, or a design found incomplete, it is never dispatched.
Once the call is on the record the plan stays closed for every other subtask: the one exception
is integration's own subtask, found in the role register by what its role owns, never by its
name. A run without that role is driven and replayed as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import (
    FakeDispatcher,
    FakeGate,
    FakeReviewer,
    KilledError,
    Rig,
    plan,
)
from orch_helpers import make_config

from physgate import roles
from physgate.orchestrator.events import (
    EnvironmentRecorded,
    Escalated,
    EventLog,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    Resumed,
    RunStarted,
    StageEntered,
    SubtaskPlanned,
    SubtaskRemoved,
    WorktreeRemoved,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError, RunStateError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.protocols import GateResult, IntegrationArtefact, RunningGateMode
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import RunState, Step, replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.roles import CrossCuttingRole, Role
from physgate.state.task_ledger import TaskLedger

#: Integration's subtask in these plans: the role that owns completion, in its own directory.
INTEG = "integ"


def models(*names: str) -> ModelStrings:
    """The run's model strings for ``names``: each implemented on one pin, reviewed on another."""
    return ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(names, "claude-sonnet-5"),
        reviewers=dict.fromkeys(names, "claude-opus-5-5"),
    )


def integrated_rig(tmp_path: Path, owner: str = "integration", **fields: Any) -> Rig:
    """A rig whose run has the stand-in domain role and ``owner``, every role reviewed."""
    return Rig(tmp_path, config_overrides={"models": models("electrical", owner)}, **fields)


def entry(subtask_id: str, role: str = "electrical", module_dir: str | None = None) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id,
        spec_path=f"specs/{subtask_id}.md",
        assigned_role=role,
        module_dir=module_dir or f"modules/{subtask_id}",
    )


def with_integration(*ids: str, owner: str = "integration") -> list[PlanEntry]:
    """The domain subtasks ``ids``, then integration's, last, as the harness plans it."""
    return [*plan(*ids), entry(INTEG, owner, "modules/integration")]


def events_of(run_dir: Path) -> list[Any]:
    return read_events(run_dir / "events.jsonl")


def about(events: list[Any], subtask_id: str) -> list[Any]:
    """Every line about ``subtask_id`` but its planning and its worktree's removal."""
    return [
        e
        for e in events
        if getattr(e, "subtask_id", None) == subtask_id
        and not isinstance(e, SubtaskPlanned | WorktreeRemoved)
    ]


def the_call(events: list[Any]) -> Any:  # noqa: ANN401 - one of the two call lines
    (call,) = [e for e in events if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)]
    return call


def dispatched(rig: Rig) -> list[str]:
    return [r.subtask_id for r in rig.dispatcher.requests]


def resolves(events: list[Any], subtask_id: str) -> list[int]:
    return [
        e.attempt
        for e in events
        if isinstance(e, StageEntered) and e.subtask_id == subtask_id and e.stage == "resolve"
    ]


def started_log(tmp_path: Path, gate_mode: str = "on") -> EventLog:
    """A run's log with its start line, followed by a fresh run state."""
    config = make_config(gate_mode=gate_mode)
    log = EventLog(
        tmp_path / "events.jsonl",
        run_id=config.run_id,
        gate_mode=config.gate_mode,
        state=RunState(),
    )
    log.emit(RunStarted, config_sha256="a" * 64)
    return log


# --- when the loop dispatches integration's subtask -------------------------------------------


@pytest.mark.parametrize(
    ("mode", "verdict"),
    [("on", "pass"), ("observe", "pass"), ("observe", "fail")],
    ids=["passed", "observed passing", "observed failing"],
)
def test_the_integration_subtask_is_dispatched_only_after_the_system_gate(
    tmp_path: Path, mode: RunningGateMode, verdict: str
) -> None:
    gate = FakeGate(integration_verdict=verdict)
    rig = integrated_rig(tmp_path, gate_mode=mode, gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateRan)
    assert (call.result.verdict, call.result.mode) == (verdict, mode)
    # Every line about integration's subtask follows the call, and every other subtask's
    # precedes it: the gate judged the design the other subtasks merged.
    assert about(events, INTEG) and all(e.seq > call.seq for e in about(events, INTEG))
    assert all(e.seq < call.seq for sid in ("s1", "s2") for e in about(events, sid))
    assert dispatched(rig) == ["s1", "s2", INTEG]
    (judged,) = gate.integrations
    merged = {e.subtask_id: e.merge_commit for e in events if isinstance(e, Merged)}
    assert judged.run_head == merged["s2"]
    assert set(merged) == {"s1", "s2", INTEG}
    # A fresh process reads the same position from the file alone.
    state = replay(events)
    assert state.subtasks[INTEG].status == "done"
    assert state.next_step().kind == "done"
    assert state.ledger == TaskLedger(tmp_path / "ledger.jsonl").read_all()


def test_under_off_the_integration_subtask_follows_the_skip_once_every_other_subtask_merged(
    tmp_path: Path,
) -> None:
    gate = FakeGate()
    rig = integrated_rig(tmp_path, gate_mode="off", gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateSkipped)
    assert (call.reason, call.subtasks) == ("gate_mode=off", ())
    assert about(events, INTEG) and all(e.seq > call.seq for e in about(events, INTEG))
    assert dispatched(rig) == ["s1", "s2", INTEG]
    assert gate.integrations == []
    assert replay(events).subtasks[INTEG].status == "done"


def test_the_integration_subtask_is_not_dispatched_after_a_blocking_failure(
    tmp_path: Path,
) -> None:
    rig = integrated_rig(tmp_path, gate=FakeGate(integration_verdict="fail"))
    loop = rig.open()
    loop.start(with_integration("s1"))
    assert loop.run().kind == "escalated"
    assert loop.run().kind == "escalated"  # and on every later pass
    loop.close()
    events = events_of(tmp_path)
    kinds = [type(e).__name__ for e in events if isinstance(e, IntegrationGateRan)]
    assert kinds == ["IntegrationGateRan"]
    assert [e for e in events if isinstance(e, IntegrationEscalated)]
    assert dispatched(rig) == ["s1"]
    assert about(events, INTEG) == []
    state = replay(events)
    assert state.subtasks[INTEG].status == "planned"
    assert state.next_step().kind == "escalated"


def test_the_integration_subtask_is_not_dispatched_after_an_incomplete_design(
    tmp_path: Path,
) -> None:
    gate = FakeGate(verdicts=["pass", "fail", "fail", "fail"])  # s1 merges, s2 escalates
    rig = integrated_rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateSkipped)
    # The incomplete design names the subtask that did not merge, and not integration's own.
    assert (call.reason, call.subtasks) == ("not_all_merged", ("s2",))
    assert INTEG not in dispatched(rig)
    assert about(events, INTEG) == []
    state = replay(events)
    assert state.subtasks[INTEG].status == "planned"
    assert state.next_step().kind == "done"


def test_under_off_the_integration_subtask_is_not_dispatched_over_a_subtask_that_did_not_merge(
    tmp_path: Path,
) -> None:
    # Under off the call is skipped as off whether or not every subtask merged, so the skip line
    # does not say the design is complete: the subtasks' own states do.
    reviewer = FakeReviewer(verdicts=["pass", "fail", "fail", "fail"])  # s1 merges, s2 does not
    rig = integrated_rig(tmp_path, gate_mode="off", reviewer=reviewer)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateSkipped)
    assert (call.reason, call.subtasks) == ("gate_mode=off", ())
    assert INTEG not in dispatched(rig)
    assert about(events, INTEG) == []
    state = replay(events)
    assert (state.subtasks["s2"].status, state.subtasks[INTEG].status) == ("escalated", "planned")
    assert state.next_step().kind == "done"


@pytest.mark.parametrize("mode", ["on", "off"])
def test_a_plan_of_integration_alone_never_dispatches_it(tmp_path: Path, mode: str) -> None:
    rig = integrated_rig(tmp_path, gate_mode=mode)
    loop = rig.open()
    loop.start([entry(INTEG, "integration", "modules/integration")])
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    reason = "nothing_planned" if mode == "on" else "gate_mode=off"
    assert the_call(events).reason == reason
    assert dispatched(rig) == []


def test_integrations_own_rejections_and_its_queue_item_follow_the_call(tmp_path: Path) -> None:
    # Its review fails three times: every attempt, the decisions and the escalation are lines
    # about integration's subtask after the call, and each is taken.
    reviewer = FakeReviewer(verdicts=["pass", "fail", "fail", "fail"])
    rig = integrated_rig(tmp_path, reviewer=reviewer)
    loop = rig.open()
    loop.start(with_integration("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateRan)
    assert resolves(events, INTEG) == [1, 2, 3]
    assert all(e.seq > call.seq for e in about(events, INTEG))
    (escalated,) = [e for e in events if isinstance(e, Escalated)]
    assert escalated.subtask_id == INTEG
    state = replay(events)
    assert state.subtasks[INTEG].status == "escalated"
    assert state.next_step().kind == "done"


# --- the replay keeps the exception narrow ----------------------------------------------------


@pytest.mark.parametrize(
    "merged", [(), ("s1",), ("s1", "s2")], ids=["nothing merged", "one merged", "all merged"]
)
def test_a_forged_integration_line_before_the_system_gate_is_refused(
    tmp_path: Path, merged: tuple[str, ...]
) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    for subtask_id in merged:
        loop._attempt(subtask_id, 1, "resolve")  # noqa: SLF001
    with pytest.raises(ValueError, match="after the system gate"):
        loop.log.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    loop.close()


def test_a_forged_integration_line_appended_before_the_system_gate_halts_the_next_open(
    tmp_path: Path,
) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1"))
    loop._attempt("s1", 1, "resolve")  # noqa: SLF001
    loop.close()
    # Appended past the loop's record, as anything else on the machine could: the line-level
    # checks alone take it.
    raw = EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode="on")
    raw.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    raw.close()
    with pytest.raises(CorruptEventLogError):
        rig.open()
    with pytest.raises(CorruptEventLogError):
        replay(read_events(tmp_path / "events.jsonl"))
    assert dispatched(rig) == ["s1"]


def _ended(tmp_path: Path, case: str) -> Rig:
    """A run of ``s1``, ``s2`` and integration, ended where the call lets integration not run."""
    if case == "blocking failure":
        rig = integrated_rig(tmp_path, gate=FakeGate(integration_verdict="fail"))
    elif case == "incomplete design":
        rig = integrated_rig(tmp_path, gate=FakeGate(verdicts=["pass", "fail", "fail", "fail"]))
    else:
        reviewer = FakeReviewer(verdicts=["pass", "fail", "fail", "fail"])
        rig = integrated_rig(tmp_path, gate_mode="off", reviewer=reviewer)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    loop.run()
    loop.close()
    return rig


@pytest.mark.parametrize(
    "case", ["blocking failure", "incomplete design", "off over an unmerged subtask"]
)
def test_a_forged_integration_line_after_a_call_that_does_not_let_it_run_is_refused(
    tmp_path: Path, case: str
) -> None:
    rig = _ended(tmp_path, case)
    loop = rig.open()
    assert loop.state.integration is not None
    with pytest.raises(ValueError, match="after the system gate"):
        loop.log.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    # Where the call does not let it run, integration's subtask is held to the closed plan
    # like any other: even a line its own rules would take is refused.
    with pytest.raises(ValueError, match="nothing about a subtask follows the integration call"):
        loop.log.emit(SubtaskRemoved, subtask_id=INTEG, reason="no longer needed")
    loop.close()
    assert INTEG not in dispatched(rig)


def test_a_forged_domain_line_after_the_system_gate_is_refused(tmp_path: Path) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1"))
    loop._attempt("s1", 1, "resolve")  # noqa: SLF001
    loop._integrate()  # noqa: SLF001
    late = entry("late")
    with pytest.raises(ValueError, match="nothing about a subtask follows the integration call"):
        loop.log.emit(SubtaskPlanned, **late.model_dump())
    # Integration's own line is taken, and still no other subtask's is.
    loop.log.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    with pytest.raises(ValueError, match="nothing about a subtask follows the integration call"):
        loop.log.emit(SubtaskPlanned, **late.model_dump())
    loop.close()


@pytest.mark.parametrize("named", ["integration", "integrations", "integration_2"])
def test_a_line_of_a_role_only_named_like_the_owner_after_the_gate_is_refused(
    tmp_path: Path, named: str
) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1"))
    loop._attempt("s1", 1, "resolve")  # noqa: SLF001
    loop._integrate()  # noqa: SLF001
    # A second subtask of the owner's role, or one of a role named like it: neither is the
    # subtask the exception is for.
    with pytest.raises(ValueError, match="integration call|completion"):
        loop.log.emit(SubtaskPlanned, **entry("late", named, f"modules/{named}").model_dump())
    loop.close()


def test_the_exception_follows_the_owner_of_completion_never_the_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The register as renamed: completion is owned by ``closer``, and a role that is only
    # named ``integration`` owns nothing.
    monkeypatch.setitem(
        roles.ROLES,
        "integration",
        Role(name="integration", domain="electrical", architecture="ARCH-050"),
    )
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    rig = Rig(tmp_path, config_overrides={"models": models("electrical", "integration", "closer")})
    loop = rig.open()
    loop.start([*plan("s1"), entry("named", "integration"), entry("owned", "closer")])
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    # The subtask of the role named integration is an ordinary subtask: done before the call.
    # The owner's runs after it.
    assert about(events, "named") and all(e.seq < call.seq for e in about(events, "named"))
    assert about(events, "owned") and all(e.seq > call.seq for e in about(events, "owned"))
    assert dispatched(rig) == ["s1", "named", "owned"]
    loop = rig.open()
    with pytest.raises(ValueError, match="nothing about a subtask follows the integration call"):
        loop.log.emit(SubtaskPlanned, **entry("late", "integration").model_dump())
    loop.close()


def test_one_subtask_at_most_is_planned_for_the_role_that_owns_completion(tmp_path: Path) -> None:
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **entry("s1").model_dump())
    log.emit(SubtaskPlanned, **entry(INTEG, "integration", "modules/integration").model_dump())
    # A second would be dispatched before the gate as an ordinary subtask, or after it as a
    # second exception.
    with pytest.raises(ValueError, match="one subtask"):
        log.emit(SubtaskPlanned, **entry("again", "integration", "modules/again").model_dump())
    log.close()


def test_with_two_owners_of_completion_no_subtask_of_either_is_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Past the register's own check, as a patched register is: which of the two is the
    # exception cannot be told, so neither is planned.
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **entry("s1").model_dump())
    for role in ("integration", "closer"):
        with pytest.raises(ValueError, match="more than one role owns completion"):
            log.emit(SubtaskPlanned, **entry(role, role, f"modules/{role}").model_dump())
    log.close()


# --- a kill around the call --------------------------------------------------------------------


def test_a_kill_between_the_system_gate_and_integrations_dispatch_resumes_to_one_dispatch(
    tmp_path: Path,
) -> None:
    gate = FakeGate()
    rig = integrated_rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    for subtask_id in ("s1", "s2"):
        loop._attempt(subtask_id, 1, "resolve")  # noqa: SLF001
    loop._integrate()  # noqa: SLF001
    loop.close()  # the process dies with the call on the record and nothing after it
    again = rig.open()
    assert again.state.next_step() == Step("attempt", INTEG, 1, "resolve")
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    assert len(gate.integrations) == 1
    assert [type(the_call(events)).__name__] == ["IntegrationGateRan"]
    assert resolves(events, INTEG) == [1]
    assert dispatched(rig).count(INTEG) == 1
    assert all(e.seq > the_call(events).seq for e in about(events, INTEG))
    assert replay(events).ledger == TaskLedger(tmp_path / "ledger.jsonl").read_all()


@dataclass
class DiesAtTheCall(FakeGate):
    """A gate whose first integration call never returns: the process dies inside it."""

    deaths: list[int] = field(default_factory=lambda: [1])

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        if self.deaths:
            self.deaths.pop()
            raise KilledError
        return super().check_integration(artefact, mode=mode)


def test_a_kill_inside_the_system_gate_call_resumes_to_one_call_line_before_integration(
    tmp_path: Path,
) -> None:
    gate = DiesAtTheCall()
    rig = integrated_rig(tmp_path, gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    before = events_of(tmp_path)
    assert about(before, INTEG) == []
    assert not [e for e in before if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)]
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    call = the_call(events)  # one line: the call that returned
    assert isinstance(call, IntegrationGateRan)
    assert resolves(events, INTEG) == [1]
    assert all(e.seq > call.seq for e in about(events, INTEG))
    assert dispatched(rig) == ["s1", "s2", INTEG]


def test_a_kill_inside_integrations_session_resumes_it_after_the_gate_without_a_second_call(
    tmp_path: Path,
) -> None:
    gate = FakeGate()
    rig = integrated_rig(tmp_path, gate=gate, dispatcher=FakeDispatcher(kill_on=3))
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    rig.dispatcher.kill_on = None
    again = rig.open()
    with pytest.raises(RunStateError, match="interrupted"):
        again.run()
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    call = the_call(events)
    assert isinstance(call, IntegrationGateRan)
    assert len(gate.integrations) == 1
    (resumed,) = [e for e in events if isinstance(e, Resumed)]
    assert (resumed.subtask_id, resumed.attempt, resumed.point) == (INTEG, 1, "resolve")
    assert resumed.seq > call.seq
    # A fresh session on the same attempt, as for any subtask.
    assert [r.attempt for r in rig.dispatcher.requests if r.subtask_id == INTEG] == [1, 1]
    assert replay(events).subtasks[INTEG].status == "done"


FACTS = InstallFacts(
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


class _Recording(FakeDispatcher):
    def environment(self) -> InstallFacts:  # type: ignore[override]
        return FACTS


def test_a_process_that_takes_over_at_the_call_records_its_environment_before_integration_runs(
    tmp_path: Path,
) -> None:
    rig = integrated_rig(tmp_path, dispatcher=_Recording())
    loop = rig.open()
    loop.start(with_integration("s1"))
    loop._attempt("s1", 1, "resolve")  # noqa: SLF001
    loop.close()  # killed before the call: no process has recorded where it runs
    again = rig.open()
    assert again.state.next_step().kind == "integrate"
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    (recorded,) = [e for e in events if isinstance(e, EnvironmentRecorded)]
    assert recorded.facts == FACTS
    assert recorded.seq < min(e.seq for e in about(events, INTEG))
