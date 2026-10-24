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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import (
    FakeDispatcher,
    FakeGate,
    FakeMerger,
    FakeReviewer,
    KilledError,
    Rig,
    failing_gate_result,
    passing_gate_result,
    plan,
)
from orch_helpers import make_config

from physgate import roles
from physgate.orchestrator.events import (
    DecisionTaken,
    EnvironmentRecorded,
    Escalated,
    EventLog,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    OsLayerChecked,
    Resumed,
    RunStarted,
    StageEntered,
    SubtaskPlanned,
    SubtaskRemoved,
    WorktreeRemoved,
    read_events,
)
from physgate.orchestrator.exceptions import (
    CorruptEventLogError,
    ReviewUnavailableError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import WorktreeRemoval
from physgate.orchestrator.protocols import GateResult, IntegrationArtefact, RunningGateMode
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import RunState, Step, replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present
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


def planned(line: PlanEntry, *, mark: bool = False) -> dict[str, Any]:
    """A planning line's fields, with the completion owner's mark when ``mark``."""
    fields = line.model_dump()
    if mark:
        fields["owns_completion"] = True
    return fields


def integ_line() -> dict[str, Any]:
    """Integration's planning line: the owner's subtask, marked, in its own directory."""
    return planned(entry(INTEG, "integration", "modules/integration"), mark=True)


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
    # Two rules refuse it in a run with integration: nothing is planned after the completion
    # owner's subtask, and nothing about a subtask but integration's follows the call. Each is
    # held alone elsewhere: the first before the call, the second in a run without integration.
    with pytest.raises(ValueError, match=CLOSED_OR_LAST):
        loop.log.emit(SubtaskPlanned, **late.model_dump())
    # Integration's own line is taken, and still no other subtask's is.
    loop.log.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    with pytest.raises(ValueError, match=CLOSED_OR_LAST):
        loop.log.emit(SubtaskPlanned, **late.model_dump())
    loop.close()


#: The two refusals a subtask planned after the call meets in a run with integration.
CLOSED_OR_LAST = "nothing about a subtask follows the integration call|planned after"


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
    loop.start(
        [
            *plan("s1"),
            entry("named", "integration"),
            entry("owned", "closer", "modules/integration"),
        ]
    )
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
    with pytest.raises(ValueError, match=CLOSED_OR_LAST):
        loop.log.emit(SubtaskPlanned, **entry("late", "integration").model_dump())
    loop.close()


@pytest.mark.parametrize(
    ("mark", "why"),
    [(True, "two subtasks are marked"), (False, "carries the completion mark")],
    ids=["marked", "unmarked"],
)
def test_one_subtask_at_most_is_planned_for_the_role_that_owns_completion(
    tmp_path: Path, mark: bool, why: str
) -> None:
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **planned(entry("s1")))
    log.emit(SubtaskPlanned, **integ_line())
    # A second would be dispatched before the gate as an ordinary subtask, or after it as a
    # second exception.
    with pytest.raises(ValueError, match=why):
        log.emit(
            SubtaskPlanned,
            **planned(entry("again", "integration", "modules/integration"), mark=mark),
        )
    log.close()


@pytest.mark.parametrize("mark", [True, False], ids=["marked", "unmarked"])
def test_with_two_owners_of_completion_no_subtask_of_either_is_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mark: bool
) -> None:
    # Past the register's own check, as a patched register is: which of the two is the
    # exception cannot be told, so neither is planned, marked or not.
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **planned(entry("s1")))
    for role in ("integration", "closer"):
        with pytest.raises(ValueError, match="more than one role owns completion"):
            log.emit(SubtaskPlanned, **planned(entry(role, role, "modules/integration"), mark=mark))
    log.close()


# --- a kill around the call --------------------------------------------------------------------


def position(state: RunState) -> tuple[Any, ...]:
    """What a process does next, and the record it does it from."""
    return (
        state.next_step(),
        state.completion_subtask,
        state.integration,
        state.integration_escalated,
        {s: sub.status for s, sub in state.subtasks.items()},
        state.ledger,
    )


@pytest.mark.parametrize(
    ("mode", "verdict"),
    [("on", "pass"), ("observe", "fail"), ("off", "pass")],
    ids=["passed", "observed failing", "off, every other merged"],
)
def test_a_kill_between_the_system_gate_and_integrations_dispatch_resumes_to_one_dispatch(
    tmp_path: Path, mode: str, verdict: str
) -> None:
    gate = FakeGate(integration_verdict=verdict)
    rig = integrated_rig(tmp_path, gate_mode=mode, gate=gate)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    for subtask_id in ("s1", "s2"):
        loop._attempt(subtask_id, 1, "resolve")  # noqa: SLF001
    loop._integrate()  # noqa: SLF001
    left = position(loop.state)
    loop.close()  # the process dies with the call on the record and nothing after it
    again = rig.open()
    # The next process reads, from the file alone, the position the killed one left.
    assert position(again.state) == left
    assert again.state.next_step() == Step("attempt", INTEG, 1, "resolve")
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    # One call, never made again, and integration's subtask dispatched once, after it.
    assert len(gate.integrations) == (0 if mode == "off" else 1)
    call = the_call(events)
    assert isinstance(call, IntegrationGateSkipped if mode == "off" else IntegrationGateRan)
    assert resolves(events, INTEG) == [1]
    assert dispatched(rig).count(INTEG) == 1
    assert all(e.seq > call.seq for e in about(events, INTEG))
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
    loop.close()  # killed before the call
    killed = len(events_of(tmp_path))
    again = rig.open()
    assert again.state.next_step().kind == "integrate"
    assert again.resume().kind == "done"
    again.close()
    events = events_of(tmp_path)
    # The process that took over records where it runs, once, before integration's session.
    (recorded,) = [e for e in events[killed:] if isinstance(e, EnvironmentRecorded)]
    assert recorded.facts == FACTS
    assert recorded.seq < min(e.seq for e in about(events, INTEG))


@pytest.mark.parametrize("plan_of", ["no integration", "integration taken out of the plan"])
def test_a_process_that_takes_over_at_the_call_with_no_integration_to_run_records_no_environment(
    tmp_path: Path, plan_of: str
) -> None:
    # As before integration's subtask moved after the call: no session follows it here.
    rig = integrated_rig(tmp_path, dispatcher=_Recording())
    loop = rig.open()
    if plan_of == "no integration":
        loop.start(plan("s1"))
    else:
        loop.start(with_integration("s1"))
        loop.remove(INTEG, "no longer needed")
    loop._attempt("s1", 1, "resolve")  # noqa: SLF001
    loop.close()
    killed = len(events_of(tmp_path))
    again = rig.open()
    assert again.state.next_step().kind == "integrate"
    assert again.resume().kind == "done"
    again.close()
    assert not [e for e in events_of(tmp_path)[killed:] if isinstance(e, EnvironmentRecorded)]


@dataclass
class DiesAtTheFirstRemoval(FakeMerger):
    """A merger whose first worktree removal never returns: the process dies after the call."""

    deaths: list[int] = field(default_factory=lambda: [1])

    def remove_worktree(self, subtask_id: str) -> WorktreeRemoval:
        if self.deaths:
            self.deaths.pop()
            raise KilledError
        return super().remove_worktree(subtask_id)


def _killed_at_a_call_that_does_not_let_it_run(tmp_path: Path, case: str) -> Rig:
    """A run of ``s1``, ``s2`` and integration, killed with such a call last on its record."""
    dies = DiesAtTheFirstRemoval()
    if case == "blocking failure, not yet escalated":
        gate = FakeGate(integration_verdict="fail")
        rig = integrated_rig(tmp_path, gate=gate, dispatcher=_Recording())
    elif case == "incomplete design":
        gate = FakeGate(verdicts=["pass", "fail", "fail", "fail"])  # s1 merges, s2 escalates
        rig = integrated_rig(tmp_path, gate=gate, dispatcher=_Recording(), merger=dies)
    else:
        reviewer = FakeReviewer(verdicts=["pass", "fail", "fail", "fail"])
        rig = integrated_rig(
            tmp_path, gate_mode="off", reviewer=reviewer, dispatcher=_Recording(), merger=dies
        )
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    if case == "blocking failure, not yet escalated":
        for subtask_id in ("s1", "s2"):
            loop._attempt(subtask_id, 1, "resolve")  # noqa: SLF001
        # Written by hand, as a process killed after the failing line and before its
        # escalation leaves the log.
        loop.log.emit(IntegrationGateRan, result=failing_gate_result("on"))
    else:
        with pytest.raises(KilledError):
            loop.run()
        assert not [e for e in loop.log.events if isinstance(e, WorktreeRemoved)]
    assert loop.state.integration is not None
    loop.close()
    return rig


@pytest.mark.parametrize(
    "case",
    ["blocking failure, not yet escalated", "incomplete design", "off over an unmerged subtask"],
)
def test_a_kill_after_a_call_that_does_not_let_integration_run_resumes_without_dispatching_it(
    tmp_path: Path, case: str
) -> None:
    rig = _killed_at_a_call_that_does_not_let_it_run(tmp_path, case)
    killed = len(events_of(tmp_path))
    again = rig.open()
    ending = "escalated" if case.startswith("blocking") else "done"
    assert again.resume().kind == ending
    assert again.run().kind == ending  # and on every later pass
    again.close()
    events = events_of(tmp_path)
    call = the_call(events)  # made once
    assert INTEG not in dispatched(rig)
    assert about(events, INTEG) == []
    escalations = [e for e in events if isinstance(e, IntegrationEscalated)]
    assert len(escalations) == (1 if case.startswith("blocking") else 0)
    # No session can follow such a call, so the process that took over at it recorded no
    # environment for one.
    assert not [e for e in events[killed:] if isinstance(e, EnvironmentRecorded)]
    state = replay(events)
    assert state.subtasks[INTEG].status == "planned"
    assert state.integration == call
    assert state.next_step().kind == ending


#: The OS layer as the command records it where it runs; a run that acts on decisions needs it.
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")


def _layer_present(loop: Loop) -> None:
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": PRESENT, "as_recorded": None}
        )
    )


def _approve_the_open_item(run_dir: Path) -> None:
    """A person approves the one open item from the listing, bound to the digest it printed."""
    view = read_queue(run_dir)
    (item,) = view.open_items()
    shown = ShownItem(
        item_sha256=view.digests[item.item_id], trajectories=statuses_now(run_dir, item.item_id)
    )
    record_decision(
        run_dir,
        item.item_id,
        person=PersonDecision(verb="approve", note=None),
        resolved_by="yasin",
        shown=shown,
    )


def test_an_approve_that_completes_an_incomplete_design_dispatches_integration_after_its_call(
    tmp_path: Path,
) -> None:
    # s2's review reaches no verdict, so s2 waits for a person and the design is incomplete:
    # integration's subtask stays planned. The person's approve merges s2; the design is then
    # judged again, once, and integration's subtask runs after that call.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gate = FakeGate()
    no_verdict = ReviewUnavailableError("no verdict", cause="invalid_verdict")
    rig = Rig(
        run_dir,
        gate=gate,
        dispatcher=FakeDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={2: no_verdict}),
        config_overrides={
            "queue_decisions": "act",
            "os_layer": PRESENT,
            "models": models("electrical", "integration"),
        },
    )
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    _layer_present(loop)
    assert loop.run().kind == "done"
    assert loop.state.subtasks[INTEG].status == "planned"
    loop.close()
    _approve_the_open_item(run_dir)
    again = rig.open()
    _layer_present(again)
    assert again.resume().kind == "done"
    again.close()
    events = events_of(run_dir)
    calls = [e for e in events if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)]
    assert [type(c).__name__ for c in calls] == ["IntegrationGateSkipped", "IntegrationGateRan"]
    skipped = calls[0]
    assert isinstance(skipped, IntegrationGateSkipped)
    assert (skipped.reason, skipped.subtasks) == ("not_all_merged", ("s2",))
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (taken.subtask_id, taken.effect) == ("s2", "merge")
    assert len(gate.integrations) == 1
    assert dispatched(rig) == ["s1", "s2", INTEG]
    assert resolves(events, INTEG) == [1]
    assert all(e.seq > calls[1].seq for e in about(events, INTEG))
    state = replay(events)
    assert (state.subtasks["s2"].status, state.subtasks[INTEG].status) == ("done", "done")
    assert state.ledger == TaskLedger(run_dir / "ledger.jsonl").read_all()


@pytest.mark.parametrize("mode", ["on", "off"])
def test_a_subtask_taken_out_of_the_plan_holds_integration_back_as_one_that_did_not_merge(
    tmp_path: Path, mode: str
) -> None:
    rig = integrated_rig(tmp_path, gate_mode=mode)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    loop.remove("s2", "no longer needed")
    assert loop.run().kind == "done"
    loop.close()
    events = events_of(tmp_path)
    call = the_call(events)
    expected = ("gate_mode=off", ()) if mode == "off" else ("not_all_merged", ("s2",))
    assert (call.reason, call.subtasks) == expected
    assert dispatched(rig) == ["s1"]
    assert about(events, INTEG) == []
    state = replay(events)
    assert state.subtasks[INTEG].status == "planned"
    assert state.next_step().kind == "done"


def test_a_gate_line_on_a_plan_of_integration_alone_is_refused(tmp_path: Path) -> None:
    # A forged passing result over no design would let integration's subtask run over
    # nothing: the call judges every subtask but integration's own, and there is none.
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **integ_line())
    with pytest.raises(ValueError, match="planned nothing"):
        log.emit(IntegrationGateRan, result=passing_gate_result("on"))
    with pytest.raises(ValueError, match="after the system gate"):
        log.emit(StageEntered, subtask_id=INTEG, attempt=1, stage="resolve")
    log.close()


# --- the completion owner's subtask is marked on its planning line ----------------------------
#
# Which subtask is integration's is read from the line that planned it, never from the register
# at replay: the register is asked once, when the line is written, and a later register (a role
# renamed, an owner moved) cannot change how a recorded run replays.

#: The fields every planning line carried before the mark existed.
PLANNING_FIELDS = {"seq", "ts", "run_id", "gate_mode", "kind"} | set(PlanEntry.model_fields)


def test_the_planning_line_marks_the_completion_owners_subtask_and_leaves_the_others_as_they_were(
    tmp_path: Path,
) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    loop.close()
    lines = [json.loads(raw) for raw in (tmp_path / "events.jsonl").read_text().splitlines()]
    planning = {line["subtask_id"]: line for line in lines if line["kind"] == "subtask_planned"}
    assert planning[INTEG]["owns_completion"] is True
    assert set(planning[INTEG]) == PLANNING_FIELDS | {"owns_completion"}
    # The others carry no mark at all, so their bytes are what they always were.
    assert set(planning["s1"]) == set(planning["s2"]) == PLANNING_FIELDS


@pytest.mark.parametrize(
    "case",
    ["a domain subtask", "no owner of completion", "two owners of completion", "owner unmarked"],
)
def test_a_planning_line_whose_mark_the_register_does_not_bear_out_is_refused_when_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **planned(entry("s1")))
    line = integ_line()
    if case == "a domain subtask":
        line, why = (
            planned(entry("s2", "electrical", "modules/integration"), mark=True),
            ("only a subtask of the role that owns completion is marked"),
        )
    elif case == "no owner of completion":
        monkeypatch.setitem(
            roles.ROLES,
            "integration",
            Role(name="integration", domain="electrical", architecture="ARCH-050"),
        )
        why = "no role owns completion"
    elif case == "two owners of completion":
        closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
        monkeypatch.setitem(roles.ROLES, closer.name, closer)
        why = "more than one role owns completion"
    else:
        line.pop("owns_completion")
        why = "carries the completion mark"
    with pytest.raises(ValueError, match=why):
        log.emit(SubtaskPlanned, **line)
    log.close()
    assert [e.subtask_id for e in events_of(tmp_path) if isinstance(e, SubtaskPlanned)] == ["s1"]


#: A planning line's timestamp, for lines written past the writer.
TS = "2026-09-26T12:00:00.000000Z"


def appended_past_the_writer(run_dir: Path, *lines: dict[str, Any]) -> None:
    """Planning lines appended to the file as bytes, past the writer and its register check."""
    path = run_dir / "events.jsonl"
    seq = len(read_events(path))
    with path.open("ab") as handle:
        for i, fields in enumerate(lines):
            line = SubtaskPlanned(seq=seq + i, ts=TS, run_id="run-1", gate_mode="on", **fields)
            handle.write(line.model_dump_json().encode() + b"\n")


@pytest.mark.parametrize(
    ("case", "why"),
    [
        ("a domain subtask marked, planned last", "integration module directory"),
        ("the marked subtask not planned last", "planned after"),
        ("two marked subtasks", "two subtasks are marked"),
        ("a second subtask of the marked role, before it", "a second subtask of the marked role"),
    ],
)
def test_a_forged_mark_is_refused_at_replay_whatever_the_register_says(
    tmp_path: Path, case: str, why: str
) -> None:
    log = started_log(tmp_path)
    log.emit(SubtaskPlanned, **planned(entry("s1")))
    log.close()
    lines = {
        "a domain subtask marked, planned last": [planned(entry("s2"), mark=True)],
        "the marked subtask not planned last": [integ_line(), planned(entry("s2"))],
        "two marked subtasks": [
            integ_line(),
            planned(entry("again", "integration", "modules/integration"), mark=True),
        ],
        "a second subtask of the marked role, before it": [
            planned(entry("early", "integration", "modules/early")),
            integ_line(),
        ],
    }[case]
    appended_past_the_writer(tmp_path, *lines)
    with pytest.raises(CorruptEventLogError) as refused:
        replay(read_events(tmp_path / "events.jsonl"))
    assert why in refused.value.context["reason"]


def test_a_log_whose_completion_owner_was_renamed_since_still_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    loop.start(with_integration("s1", "s2"))
    assert loop.run().kind == "done"
    left = position(loop.state)
    loop.close()
    assert left[1] == INTEG and loop.state.subtasks[INTEG].status == "done"
    # The register as a later version might hold it: completion owned by a role of another
    # name, and a role still named integration that owns nothing.
    monkeypatch.setitem(
        roles.ROLES,
        "integration",
        Role(name="integration", domain="electrical", architecture="ARCH-050"),
    )
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    assert roles.owners_of("completion") == ("closer",)
    # A fresh process reads the run as it was recorded, from the mark on its planning line.
    assert position(replay(events_of(tmp_path))) == left
    again = rig.open()
    assert position(again.state) == left
    assert again.run().kind == "done"
    again.close()


# --- under off, a decision that acts after the skip reopens an incomplete design -------------


def _off_run_acting(run_dir: Path, *, with_integ: bool, no_verdict_on: int) -> Rig:
    """An off run that acts on decisions, driven to its end.

    Its review number ``no_verdict_on`` reaches no verdict, so that subtask waits for a person.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    no_verdict = ReviewUnavailableError("no verdict", cause="invalid_verdict")
    rig = Rig(
        run_dir,
        gate_mode="off",
        dispatcher=FakeDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(unavailable={no_verdict_on: no_verdict}),
        config_overrides={
            "queue_decisions": "act",
            "os_layer": PRESENT,
            "models": models("electrical", "integration"),
        },
    )
    loop = rig.open()
    loop.start(with_integration("s1", "s2") if with_integ else plan("s1", "s2"))
    _layer_present(loop)
    assert loop.run().kind == "done"
    loop.close()
    return rig


def _calls(events: list[Any]) -> list[Any]:
    return [e for e in events if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)]


@pytest.mark.parametrize("with_integ", [True, False], ids=["with integration", "without"])
def test_under_off_an_approve_that_completes_the_design_reopens_it(
    tmp_path: Path, with_integ: bool
) -> None:
    # s2's review reaches no verdict and s2 waits; the call is skipped as off over it. The
    # person's approve merges s2, so the design changes and is judged again, once, as after
    # an incomplete design under on; with integration, its subtask runs after that call.
    run_dir = tmp_path / "run"
    rig = _off_run_acting(run_dir, with_integ=with_integ, no_verdict_on=2)
    assert len(_calls(events_of(run_dir))) == 1
    _approve_the_open_item(run_dir)
    again = rig.open()
    _layer_present(again)
    assert again.resume().kind == "done"
    again.close()
    events = events_of(run_dir)
    calls = _calls(events)
    assert [(type(c).__name__, c.reason) for c in calls] == [
        ("IntegrationGateSkipped", "gate_mode=off"),
        ("IntegrationGateSkipped", "gate_mode=off"),
    ]
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert taken.seq > calls[0].seq and (taken.subtask_id, taken.effect) == ("s2", "merge")
    state = replay(events)
    assert state.subtasks["s2"].status == "done"
    if with_integ:
        assert dispatched(rig) == ["s1", "s2", INTEG]
        assert all(e.seq > calls[1].seq for e in about(events, INTEG))
        assert state.subtasks[INTEG].status == "done"
    assert state.ledger == TaskLedger(run_dir / "ledger.jsonl").read_all()


def test_under_off_a_decision_on_integrations_own_item_reopens_nothing(tmp_path: Path) -> None:
    # Every other subtask merged, so the skip line was all the design needed: integration ran,
    # and its own review reached no verdict. The person's approve merges integration's attempt
    # and judges the design no second time; the plan stays closed to every other subtask.
    run_dir = tmp_path / "run"
    rig = _off_run_acting(run_dir, with_integ=True, no_verdict_on=3)
    (call,) = _calls(events_of(run_dir))
    _approve_the_open_item(run_dir)
    again = rig.open()
    _layer_present(again)
    assert again.resume().kind == "done"
    assert again.state.integration == call
    with pytest.raises(ValueError, match=CLOSED_OR_LAST):
        again.log.emit(SubtaskPlanned, **planned(entry("late")))
    again.close()
    events = events_of(run_dir)
    assert _calls(events) == [call]
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert (taken.subtask_id, taken.effect) == (INTEG, "merge")
    assert replay(events).subtasks[INTEG].status == "done"


def test_a_recorded_off_run_without_integration_replays_unchanged(tmp_path: Path) -> None:
    # An off run that ended with a subtask waiting: the file is read back to the position the
    # recording process left, and opening it changes no byte.
    run_dir = tmp_path / "run"
    rig = _off_run_acting(run_dir, with_integ=False, no_verdict_on=2)
    path = run_dir / "events.jsonl"
    recorded = path.read_bytes()
    state = replay(events_of(run_dir))
    assert state.next_step().kind == "done"
    assert isinstance(state.integration, IntegrationGateSkipped)
    assert (state.subtasks["s1"].status, state.subtasks["s2"].status) == ("done", "escalated")
    rig.open().close()
    assert path.read_bytes() == recorded
    # A log the earlier code left where it took a decision and then could not carry it out
    # (its next line was refused, so the decision is the last line) still replays.
    _approve_the_open_item(run_dir)
    loop = rig.open()
    _layer_present(loop)
    assert loop._take_decisions()  # noqa: SLF001 - taken, and the process dies before it acts
    loop.close()
    events = events_of(run_dir)
    assert isinstance(events[-1], DecisionTaken)
    assert replay(events).subtasks["s2"].status == "active"


def test_a_plan_the_register_does_not_bear_out_leaves_nothing_of_itself_on_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two owners of completion: which of them runs after the call cannot be told, so the plan
    # is refused before its first line, not part way through it.
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    rig = integrated_rig(tmp_path)
    loop = rig.open()
    with pytest.raises(RunConfigError, match="more than one role owns completion"):
        loop.start(with_integration("s1", "s2"))
    loop.close()
    assert not [e for e in events_of(tmp_path) if isinstance(e, SubtaskPlanned)]
