"""A module of the plan is complete only as integration's accepted attempt declared it.

Merged is not complete (ARCH-051). Integration's attempt reads a declaration from the commit its
change check held, one line straight after that check: the modules it declares complete. Once
that attempt merged and its diff found nothing, the orchestrator writes one completion line per
declared module, in plan order, and only for a module every precondition of completion holds
for: an ordered registry, asked again by replay for every completion line it reads. A declared
module with a precondition open is withheld, and the run ends without its line. Replay refuses a
completion line no such attempt explains and a declaration anywhere but its one place, and the
writer holds both lines to the role register as they are written.

The loop reads the declaration from the commit its change check held: these tests have the fake
checker read one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeChanges, FakeDispatcher, FakeGate, FakeReviewer, KilledError, Rig, plan

from physgate import roles
from physgate.orchestrator import completion
from physgate.orchestrator.common import GateMode
from physgate.orchestrator.completion import Precondition, open_preconditions
from physgate.orchestrator.declaration import Declaration
from physgate.orchestrator.events import (
    CompletionDeclared,
    DiffChecked,
    EnvironmentRecorded,
    Event,
    EventLog,
    Halted,
    Incident,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    ModuleCompleted,
    ProposalsChecked,
    StageEntered,
    WorktreeRemoved,
    parse_events,
    read_events,
)
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import Artefact, GateResult, RunningGateMode
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import RunState, replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.roles import CrossCuttingRole

INTEG = "integ"
DIGEST = "d" * 64
#: A pass over ``s1``'s module after it, in its directory, as sizing's closing pass is.
CLOSING = PlanEntry(
    subtask_id="s1c", spec_path="specs/s1c.md", assigned_role="electrical", module_dir="modules/s1"
)
INTEGRATION = PlanEntry(
    subtask_id=INTEG,
    spec_path=f"specs/{INTEG}.md",
    assigned_role="integration",
    module_dir="modules/integration",
)


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


def rig_for(tmp_path: Path, mode: GateMode = "on", **fields: Any) -> Rig:
    models = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(("electrical", "integration"), "claude-sonnet-5"),
        reviewers=dict.fromkeys(("electrical", "integration"), "claude-opus-5-5"),
    )
    return Rig(tmp_path, gate_mode=mode, config_overrides={"models": models}, **fields)


def declaring(
    monkeypatch: pytest.MonkeyPatch,
    loop: Loop,
    modules: Sequence[str] | None,
    *,
    kill_at_completion: int | None = None,
) -> None:
    """Have integration's attempts declare ``modules``, as the change check reads them.

    The loop writes the declaration line straight after an accepted check.

    ``None`` declares nothing, and writes no line. With ``kill_at_completion``, the process dies
    as it is about to write that many-th completion line, counted from 0.
    """
    changes = loop._changes  # noqa: SLF001 - the rig's checker
    assert isinstance(changes, FakeChanges)
    if modules is not None:
        changes.declares[INTEG] = Declaration(modules=tuple(modules), sha256=DIGEST)
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    written = [0]

    def with_declaration(event: Event) -> None:
        if isinstance(event, ModuleCompleted):
            if written[0] == kill_at_completion:
                raise KilledError
            written[0] += 1
        emit(event)

    monkeypatch.setattr(loop, "_emit", with_declaration)


def finished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared: Sequence[str] | None = ("s1", "s2"),
    *,
    mode: GateMode = "on",
    verdict: str = "pass",
    extra: Sequence[PlanEntry] = (),
    gate: FakeGate | None = None,
    **fields: Any,
) -> list[Event]:
    """A run of ``s1``, ``s2``, any ``extra`` and integration, driven to its end; its lines."""
    gate = gate or FakeGate(integration_verdict=verdict)
    rig = rig_for(tmp_path, mode, gate=gate, **fields)
    loop = rig.open()
    declaring(monkeypatch, loop, declared)
    loop.start([*plan("s1", "s2"), *extra, INTEGRATION])
    loop.run()
    loop.close()
    return read_events(tmp_path / "events.jsonl")


def index(
    events: Sequence[Event], kind: type[Any], subtask: str | None = INTEG, **match: Any
) -> int:
    """Where the first line of ``kind`` about ``subtask`` with the ``match`` fields is."""
    return next(
        i
        for i, e in enumerate(events)
        if isinstance(e, kind)
        and getattr(e, "subtask_id", None) == subtask
        and all(getattr(e, k) == v for k, v in match.items())
    )


def before_completions(events: Sequence[Event]) -> list[Event]:
    """The lines up to integration's clean diff: where the first completion would follow."""
    return list(events[: index(events, DiffChecked) + 1])


def line(events: Sequence[Event], kind: type[Any], **fields: Any) -> Any:  # noqa: ANN401
    """A line of ``kind`` that would come next after ``events``."""
    last = events[-1]
    return kind(seq=len(events), ts=last.ts, run_id=last.run_id, gate_mode=last.gate_mode, **fields)


def completed(events: Sequence[Event], module: str, **fields: Any) -> ModuleCompleted:
    values: dict[str, Any] = {"subtask_id": module, "declared_by": INTEG, "attempt": 1} | fields
    return line(events, ModuleCompleted, **values)  # type: ignore[no-any-return]


def declaration(events: Sequence[Event], *modules: str, **fields: Any) -> CompletionDeclared:
    values: dict[str, Any] = {"subtask_id": INTEG, "attempt": 1, "modules": modules}
    values |= {"declaration_sha256": DIGEST} | fields
    return line(events, CompletionDeclared, **values)  # type: ignore[no-any-return]


def refused(events: Sequence[Event], extra: Event, reason: str) -> None:
    with pytest.raises(CorruptEventLogError) as caught:
        replay([*events, extra])
    assert reason in caught.value.context["reason"]


def completions(events: Sequence[Event]) -> list[ModuleCompleted]:
    return [e for e in events if isinstance(e, ModuleCompleted)]


# --- what is written, and when ------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["on", "observe", "off"])
def test_each_declared_module_is_completed_after_integrations_clean_diff_in_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: GateMode
) -> None:
    events = finished(tmp_path, monkeypatch, mode=mode)
    diff = index(events, DiffChecked)
    assert not events[diff].divergences  # type: ignore[union-attr]
    done = completions(events)
    assert [(e.subtask_id, e.declared_by, e.attempt) for e in done] == [
        ("s1", INTEG, 1),
        ("s2", INTEG, 1),
    ]
    assert [e.seq for e in done] == [diff + 1, diff + 2]
    state = replay(events)
    assert set(state.completed) == {"s1", "s2"}
    assert state.owed_completion() is None
    assert state.next_step().kind == "done"
    # Merged and complete are two states: the subtask's own stays what merging made it.
    assert {s: state.subtasks[s].status for s in ("s1", "s2", INTEG)} == dict.fromkeys(
        ("s1", "s2", INTEG), "done"
    )


def test_a_run_with_merged_but_undeclared_modules_does_not_read_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, declared in (("none", None), ("s1 only", ("s1",))):
        events = finished(tmp_path / name, monkeypatch, declared)
        state = replay(events)
        assert all(state.subtasks[s].status == "done" for s in ("s1", "s2", INTEG))
        assert set(state.completed) == set(declared or ())
        assert "s2" not in state.completed
        assert state.owed_completion() is None
        assert state.next_step().kind == "done"


def test_nothing_is_owed_while_integrations_subtask_is_set_aside_for_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = FakeReviewer(verdicts=["pass", "pass", "fail", "fail", "fail"])
    events = finished(tmp_path, monkeypatch, reviewer=reviewer)
    # Every attempt declared, and none was accepted: the third rejection went to the queue.
    assert [e.attempt for e in events if isinstance(e, CompletionDeclared)] == [1, 2, 3]
    state = replay(events)
    assert state.subtasks[INTEG].status == "escalated"
    assert completions(events) == []
    assert state.owed_completion() is None
    assert state.next_step().kind == "done"


def test_the_completion_names_the_attempt_of_integration_that_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Integration's first attempt is refused at its change check, so it declares nothing.
    changes = FakeChanges(refuse={3: ("proposal", "a node no session writes")})
    events = finished(tmp_path, monkeypatch, changes=changes)
    assert [e.attempt for e in events if isinstance(e, CompletionDeclared)] == [2]
    assert [(e.subtask_id, e.attempt) for e in completions(events)] == [("s1", 2), ("s2", 2)]


def test_completion_is_withheld_while_a_registered_precondition_is_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, str]] = []

    def sign_off(state: RunState, module: str) -> str | None:
        asked.append((module, state.subtasks[INTEG].status))
        return "its standing sign-off is open" if module == "s1" else None

    # One more entry, as a later precondition joins: nothing already registered is edited.
    entries = (*completion.PRECONDITIONS, Precondition("sign_off", sign_off))
    monkeypatch.setattr(completion, "PRECONDITIONS", entries)
    events = finished(tmp_path, monkeypatch)
    assert [e.subtask_id for e in completions(events)] == ["s2"]
    assert ("s1", "done") in asked
    state = replay(events)
    assert set(state.completed) == {"s2"}
    assert state.next_step().kind == "done"
    refused(events, completed(events, "s1"), "sign_off: its standing sign-off is open")


def test_under_observe_a_failed_system_scope_result_withholds_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = finished(tmp_path, monkeypatch, mode="observe", verdict="fail")
    call = next(e for e in events if isinstance(e, IntegrationGateRan))
    assert (call.result.verdict, call.result.mode) == ("fail", "observe")
    # Observe blocks no merge: integration ran and merged, and declared both.
    assert replay(events).subtasks[INTEG].status == "done"
    assert completions(events) == []
    assert replay(events).next_step().kind == "done"
    refused(events, completed(events, "s1"), "system_scope: the system-scope result failed")


def test_under_off_completion_has_no_system_scope_precondition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = finished(tmp_path, monkeypatch, mode="off")
    call = next(e for e in events if isinstance(e, IntegrationGateSkipped))
    assert call.reason == "gate_mode=off"
    assert [e.subtask_id for e in completions(events)] == ["s1", "s2"]


def test_the_registry_asks_merged_then_the_system_scope_and_each_reads_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert [p.name for p in completion.PRECONDITIONS] == ["merged", "system_scope", "contract"]
    events = finished(tmp_path / "closing", monkeypatch, extra=(CLOSING,))
    # A module is merged once every subtask planned in its directory is: a pass over it too.
    s1_done = replay(events[: index(events, DiffChecked, "s1") + 1])
    why = dict(open_preconditions(s1_done, "s1"))
    assert "s1c" in why["merged"]
    assert "s2" in dict(open_preconditions(s1_done, "s2"))["merged"]
    assert "no integration call" in why["system_scope"]
    assert open_preconditions(replay(events), "s1") == ()

    def system_scope(case: str, **kw: Any) -> str | None:
        state = replay(finished(tmp_path / case, monkeypatch, **kw))
        return dict(open_preconditions(state, "s1")).get("system_scope")

    assert system_scope("on-pass") is None
    assert system_scope("off", mode="off") is None
    assert "failed at magnitude in on" in str(system_scope("on-fail", verdict="fail"))
    observed = system_scope("observe-fail", mode="observe", verdict="fail")
    assert "failed at magnitude in observe" in str(observed)
    incomplete = system_scope(
        "incomplete", gate=FakeGate(verdicts=["pass", "fail", "fail", "fail"])
    )
    assert "skipped: not_all_merged" in str(incomplete)


# --- the declaration's one place ------------------------------------------------------------


def test_a_declaration_comes_only_from_integration_after_its_accepted_change_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = finished(tmp_path / "run", monkeypatch, declared=())
    place = "a completion declaration cannot come at this point of the attempt"
    owner = "comes only from the subtask marked as the completion owner's"
    implement = index(events, StageEntered, stage="implement")
    declared = index(events, CompletionDeclared)
    s1_checked = index(events, ProposalsChecked, "s1")
    for prefix, extra, reason in (
        (events[: implement + 1], None, place),  # before the change check
        (events[: declared + 1], None, place),  # a second line in the attempt
        (events[: index(events, StageEntered, stage="gate") + 1], None, place),
        (events[: index(events, Merged) + 1], None, place),
        (events[: s1_checked + 1], {"subtask_id": "s1"}, owner),
    ):
        refused(prefix, declaration(prefix, **(extra or {})), reason)
    # Past the change check in an attempt that has declared nothing: its gate stage, its merge.
    bare = finished(tmp_path / "undeclared", monkeypatch, declared=None)
    for after in (index(bare, StageEntered, stage="gate"), index(bare, Merged)):
        refused(bare[: after + 1], declaration(bare[: after + 1]), place)
    # After a change check that refused the attempt.
    changes = FakeChanges(refuse={3: ("proposal", "a node no session writes")})
    events = finished(tmp_path / "refused", monkeypatch, declared=(), changes=changes)
    prefix = events[: index(events, ProposalsChecked, attempt=1) + 1]
    refused(prefix, declaration(prefix), place)
    assert index(events, CompletionDeclared, attempt=2)


@pytest.mark.parametrize(
    ("modules", "reason"),
    [
        (("ghost",), "names 'ghost', which is no module of the plan"),
        ((INTEG,), f"names {INTEG!r}, which is no module of the plan"),
        (("s1c",), "names 's1c', which is no module of the plan"),
        (("s1", "s1"), "names each module once, in plan order"),
        (("s2", "s1"), "names each module once, in plan order"),
    ],
    ids=["unplanned", "integration's own", "a closing pass", "twice", "out of order"],
)
def test_a_declaration_names_only_modules_of_the_plan_once_each_in_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modules: tuple[str, ...], reason: str
) -> None:
    events = finished(tmp_path, monkeypatch, declared=(), extra=(CLOSING,))
    prefix = events[: index(events, CompletionDeclared)]
    refused(prefix, declaration(prefix, *modules), reason)
    replay([*prefix, declaration(prefix, "s1", "s2")])  # what it may name


# --- completion lines no accepted attempt explains -----------------------------------------------


def _unexplained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> tuple[Any, Any]:
    """The lines a forged completion line follows in ``case``, and that line."""
    if case == "a module not declared":
        events = finished(tmp_path, monkeypatch, declared=("s2",))
        assert [e.subtask_id for e in completions(events)] == ["s2"]
        return events, completed(events, "s1")
    if case == "no declaration":
        events = finished(tmp_path, monkeypatch, declared=None)
        return events, completed(events, "s1")
    if case == "a run without integration":
        rig = rig_for(tmp_path)
        loop = rig.open()
        loop.start(plan("s1"))
        loop.run()
        loop.close()
        events = read_events(tmp_path / "events.jsonl")
        return events, completed(events, "s1", declared_by="s1")
    if case == "an earlier attempt than the merged one":
        # Integration's first attempt is refused at its change check; its second merges.
        changes = FakeChanges(refuse={3: ("proposal", "a node no session writes")})
        base = before_completions(finished(tmp_path, monkeypatch, changes=changes))
        return base, completed(base, "s1", attempt=1)
    full = finished(tmp_path, monkeypatch)
    owed = before_completions(full)
    if case == "over a diff that found divergences":
        # Integration's diff named a divergence: its subtask is not done, whatever it declared.
        diff = owed[-1]
        assert isinstance(diff, DiffChecked)
        owed[-1] = diff.model_copy(update={"divergences": ("motor.left: written by s1",)})
        return owed, completed(owed, "s1")
    if case == "in a halted run":
        halted = [*owed, line(owed, Halted, reason="incident", detail="duty_breach")]
        return halted, completed(halted, "s1")
    if case == "before integration's diff":
        base = full[: index(full, Merged) + 1]
        return base, completed(base, "s1")
    if case == "before integration ran":
        base = full[: index(full, IntegrationGateRan, None) + 1]
        return base, completed(base, "s1")
    if case == "a module completed already":
        base = full[: index(full, ModuleCompleted, "s1") + 1]
        return base, completed(base, "s1")
    forged: dict[str, dict[str, Any]] = {
        "a module owed later": {"module": "s2"},
        "declared by another subtask": {"module": "s1", "declared_by": "s2"},
        "another attempt": {"module": "s1", "attempt": 2},
        "integration's own": {"module": INTEG},
        "an unplanned module": {"module": "ghost"},
    }
    fields = dict(forged[case])
    module = fields.pop("module")
    return owed, completed(owed, str(module), **fields)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("a module owed later", "'s1' is owed its completion line first"),
        ("declared by another subtask", "declared only by the subtask marked as the completion"),
        ("another attempt", "names the attempt of integration that merged"),
        ("an earlier attempt than the merged one", "names the attempt of integration that merged"),
        ("over a diff that found divergences", "follows integration's accepted attempt"),
        ("in a halted run", "the run is halted"),
        ("integration's own", f"{INTEG!r} is not a module the merged attempt declared complete"),
        ("an unplanned module", "'ghost' is not a module the merged attempt declared complete"),
        ("before integration's diff", "follows integration's accepted attempt"),
        ("before integration ran", "follows integration's accepted attempt"),
        ("a module completed already", "'s1' is recorded complete once"),
        ("a module not declared", "'s1' is not a module the merged attempt declared complete"),
        ("no declaration", "'s1' is not a module the merged attempt declared complete"),
        ("a run without integration", "declared only by the subtask marked as the completion"),
    ],
)
def test_replay_refuses_a_completion_no_integration_attempt_explains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, reason: str
) -> None:
    base, extra = _unexplained(tmp_path, monkeypatch, case)
    refused(base, extra, reason)


# --- a kill, the register, and lines written past the writer ---------------------------------


@pytest.mark.parametrize("written", [0, 1], ids=["none written", "one written"])
def test_a_kill_between_integrations_diff_and_its_last_completion_resumes_to_one_line_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, written: int
) -> None:
    rig = rig_for(tmp_path, dispatcher=Installed())
    loop = rig.open()
    declaring(monkeypatch, loop, ("s1", "s2"), kill_at_completion=written)
    loop.start([*plan("s1", "s2"), INTEGRATION])
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    cut = len(read_events(tmp_path / "events.jsonl"))
    state = replay(read_events(tmp_path / "events.jsonl"))
    assert state.next_step().kind == "complete"
    assert state.next_step().subtask_id == ("s1", "s2")[written]
    sessions = len(rig.dispatcher.requests)
    fresh = rig.open()
    assert fresh.run().kind == "done"
    fresh.close()
    events = read_events(tmp_path / "events.jsonl")
    assert [e.subtask_id for e in completions(events)] == ["s1", "s2"]
    # The process that took over spawned nothing, so it recorded no environment for it; the one
    # before it did, for its sessions.
    assert [e for e in events[:cut] if isinstance(e, EnvironmentRecorded)]
    assert not [e for e in events[cut:] if isinstance(e, EnvironmentRecorded)]
    assert len(rig.dispatcher.requests) == sessions


class KillingGate(FakeGate):
    """A gate that kills the orchestrator once, inside its ``n``-th check of an attempt."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        if len(self.seen) + 1 == self.n:
            self.n = 0
            self.seen.append(artefact)
            raise KilledError
        return super().check(artefact, mode=mode)


def test_a_kill_after_integrations_declaration_resumes_to_a_fresh_one_for_the_rechecked_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rig_for(tmp_path, gate=KillingGate(3))  # integration's is the third attempt gated
    loop = rig.open()
    declaring(monkeypatch, loop, ("s1", "s2"))
    loop.start([*plan("s1", "s2"), INTEGRATION])
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    # Killed at the gate of integration's first attempt, its declaration already on the record.
    last = read_events(tmp_path / "events.jsonl")[-3:]
    assert [type(e) for e in last] == [ProposalsChecked, CompletionDeclared, StageEntered]
    assert [getattr(e, "attempt", None) for e in last] == [1, 1, 1]
    fresh = rig.open()
    declaring(monkeypatch, fresh, ("s1", "s2"))
    assert fresh.resume().kind == "done"
    fresh.close()
    events = read_events(tmp_path / "events.jsonl")
    # The resumed attempt checks its changes again, and reads its declaration again with them.
    assert len([e for e in events if isinstance(e, CompletionDeclared)]) == 2
    assert [e.subtask_id for e in completions(events)] == ["s1", "s2"]


def _prefix_log(tmp_path: Path, events: Sequence[Event]) -> EventLog:
    """A run's log holding ``events``, opened by the writer, which follows a run state."""
    path = tmp_path / "prefix" / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"".join(e.model_dump_json().encode() + b"\n" for e in events))
    first = events[0]
    return EventLog(path, run_id=first.run_id, gate_mode=first.gate_mode, state=RunState())


@pytest.mark.parametrize(
    ("register", "why"),
    [("two owners", "more than one role owns completion"), ("none", "no role owns completion")],
)
def test_a_completion_line_is_refused_as_it_is_written_unless_the_register_names_its_one_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, register: str, why: str
) -> None:
    events = finished(tmp_path / "run", monkeypatch)
    owed = before_completions(events)
    unchecked = events[: index(events, CompletionDeclared)]
    # Under the register the run was planned under, both lines are written.
    for prefix, extra in ((owed, completed(owed, "s1")), (unchecked, declaration(unchecked))):
        log = _prefix_log(tmp_path / f"ok-{type(extra).__name__}", prefix)
        log.append(extra)
        log.close()
    log = _prefix_log(tmp_path / "another role", owed)
    with pytest.raises(ValueError, match="only a subtask of the integration role, which owns"):
        log.append(completed(owed, "s1", declared_by="s2"))
    log.close()
    # Past the register's own check, as a patched register is.
    if register == "two owners":
        closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
        monkeypatch.setitem(roles.ROLES, closer.name, closer)
    else:
        monkeypatch.delitem(roles.ROLES, "integration")
    for prefix, extra in ((owed, completed(owed, "s1")), (unchecked, declaration(unchecked))):
        log = _prefix_log(tmp_path / f"refused-{type(extra).__name__}", prefix)
        with pytest.raises(ValueError, match=why):
            log.append(extra)
        log.close()
    # Replay reads the mark and never the register: the recorded run reads as it did.
    assert set(replay(read_events(tmp_path / "run" / "events.jsonl")).completed) == {"s1", "s2"}


def test_a_completion_step_under_a_register_with_two_owners_of_completion_halts_on_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process that writes a completion asks the register first, as a dispatch does.

    The writer would refuse the line and the process would end with nothing on the record, and
    so would every process after it. Asked first, the process records why as an incident and
    halts, so an operator reads the cause in the run's own log.
    """
    rig = rig_for(tmp_path, dispatcher=Installed())
    loop = rig.open()
    declaring(monkeypatch, loop, ("s1", "s2"), kill_at_completion=0)
    loop.start([*plan("s1", "s2"), INTEGRATION])
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    cut = len(read_events(tmp_path / "events.jsonl"))
    assert replay(read_events(tmp_path / "events.jsonl")).next_step().kind == "complete"
    # The process that takes over runs under a register with a second owner of completion. (With
    # none, the run's own role is not registered, and no process opens the run at all.)
    closer = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")
    monkeypatch.setitem(roles.ROLES, closer.name, closer)
    fresh = rig.open()
    assert fresh.run().kind == "halted"
    fresh.close()
    events = read_events(tmp_path / "events.jsonl")
    # The incident and the halt; then, as at any halt, the merged subtasks' worktrees are removed.
    incident, halted, *removed = events[cut:]
    assert isinstance(incident, Incident) and isinstance(halted, Halted)
    assert all(isinstance(e, WorktreeRemoved) for e in removed)
    assert (incident.subtask_id, incident.cause) == (None, "duty_breach")
    assert incident.detail == (
        f"subtask {INTEG}: more than one role owns completion, so no module is declared or "
        "recorded complete: closer,integration"
    )
    assert (halted.reason, halted.detail) == ("incident", "duty_breach")
    assert completions(events) == []
    assert replay(events).next_step().kind == "halted"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("a module not declared", "'s2' is not a module the merged attempt declared complete"),
        ("a second completion", "'s1' is recorded complete once"),
        # Refused by the rule that holds every subtask's lines to an attempt in progress.
        ("a declaration after the merge", "subtask 'integ' has no attempt in progress"),
        ("observed", "system_scope: the system-scope result failed"),
    ],
)
def test_a_completion_line_appended_straight_to_the_event_log_halts_the_next_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, reason: str
) -> None:
    declared: tuple[str, ...] | None = ("s1", "s2")
    mode: GateMode = "observe" if case == "observed" else "on"
    verdict = "fail" if case == "observed" else "pass"
    if case == "a module not declared":
        declared = ("s1",)
    elif case == "a declaration after the merge":
        declared = None
    rig = rig_for(tmp_path, mode, gate=FakeGate(integration_verdict=verdict))
    loop = rig.open()
    declaring(monkeypatch, loop, declared)
    loop.start([*plan("s1", "s2"), INTEGRATION])
    assert loop.run().kind == "done"
    loop.close()
    sessions = len(rig.dispatcher.requests)
    # Appended past the loop's record, as anything else on the machine could: the line-level
    # checks alone take it.
    raw = EventLog(tmp_path / "events.jsonl", run_id="run-1", gate_mode=mode)
    if case == "a declaration after the merge":
        raw.emit(
            CompletionDeclared,
            subtask_id=INTEG,
            attempt=1,
            modules=("s1", "s2"),
            declaration_sha256=DIGEST,
        )
    module = "s2" if case == "a module not declared" else "s1"
    raw.emit(ModuleCompleted, subtask_id=module, declared_by=INTEG, attempt=1)
    raw.close()
    with pytest.raises(CorruptEventLogError) as opened:
        rig.open()
    assert reason in opened.value.context["reason"]
    with pytest.raises(CorruptEventLogError):
        replay(read_events(tmp_path / "events.jsonl"))
    assert len(rig.dispatcher.requests) == sessions


@pytest.mark.parametrize("mode", ["on", "observe", "off"])
def test_a_run_without_integration_or_its_declaration_writes_no_completion_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: GateMode
) -> None:
    rig = rig_for(tmp_path / "plain", mode)
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "done"
    loop.close()
    for events in (
        read_events(tmp_path / "plain" / "events.jsonl"),
        finished(tmp_path / "undeclared", monkeypatch, declared=None, mode=mode),
    ):
        assert not [e for e in events if isinstance(e, CompletionDeclared | ModuleCompleted)]
        state = replay(events)
        assert state.completed == {}
        assert state.next_step().kind == "done"


# --- every recorded run with a completion replays under the whole registry ---------------------

#: The repository's root. The injected corpus is pinned by its manifest and predates completion
#: lines.
ROOT = Path(__file__).resolve().parents[3]
#: Where the tests keep recorded material, each of which the search must reach: a run's parameters
#: recorded before a parameter existed, the reviewer's replayed submissions and schemas, and the
#: golden escalation runs, whose cases hold event lists.
STORES = (
    Path("tests/unit/orchestrator/recorded"),
    Path("tests/integration/orchestrator/replayed"),
    Path("tests/unit/orchestrator/escalation_paths.golden.json"),
)
GOLDEN = STORES[-1]
#: Installed dependencies, never a recorded run: the hook tests' pinned binary lives under one.
NOT_RECORDED = "node_modules"


def _decoded(raw: bytes) -> object:
    """``raw`` as JSON, or ``None`` if it is not JSON."""
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _event_lists(document: object) -> Iterator[list[Any]]:
    """Every ``events`` list in a decoded JSON document, at any depth."""
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "events" and isinstance(value, list):
                yield value
            else:
                yield from _event_lists(value)
    elif isinstance(document, list):
        for value in document:
            yield from _event_lists(value)


def recorded_runs(tests: Path) -> tuple[list[Path], list[tuple[Path, list[Any]]]]:
    """Every file decoded under ``tests``, and every run in them, as its records decoded.

    A ``*.jsonl`` file is one run, a record per line. A ``*.json`` document holds one wherever it
    has an ``events`` list, at the top or nested, as the golden file holds one per case.
    """
    examined: list[Path] = []
    runs: list[tuple[Path, list[Any]]] = []
    for path in sorted(tests.rglob("*")):
        if NOT_RECORDED in path.parts or not path.is_file():
            continue
        if path.suffix == ".jsonl":
            examined.append(path)
            lines = [_decoded(raw) for raw in path.read_bytes().splitlines() if raw.strip()]
            runs.append((path, lines))
        elif path.suffix == ".json":
            document = _decoded(path.read_bytes())
            if document is not None:
                examined.append(path)
                runs.extend((path, events) for events in _event_lists(document))
    return examined, runs


def with_completions(runs: list[tuple[Path, list[Any]]]) -> list[tuple[Path, list[Any]]]:
    """The runs with a completion line, read by each record's ``kind``, whatever its layout."""
    return [
        (path, records)
        for path, records in runs
        if any(isinstance(r, dict) and r.get("kind") == "module_completed" for r in records)
    ]


def experiment_logs_with_completions(root: Path) -> list[Path]:
    """Every experiment run's event log under ``root`` that holds a completion line."""
    return sorted(
        path
        for path in root.rglob("events.jsonl")
        if b'"kind":"module_completed"' in path.read_bytes()
    )


def replayed(path: Path, records: list[Any]) -> RunState:
    """The run ``records`` hold, read as the writer's lines and replayed."""
    data = b"".join(json.dumps(record).encode() + b"\n" for record in records)
    return replay(parse_events(data, log=str(path)))


def unreached(root: Path, examined: list[Path]) -> list[Path]:
    """Each of the stores, under ``root``, that no file examined lies in or is."""
    return [
        store
        for store in STORES
        if not any(path == root / store or root / store in path.parents for path in examined)
    ]


def test_every_recorded_run_with_a_completion_line_replays_under_the_whole_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay asks the registry as it stands for every completion line it reads.

    So a precondition added later must hold on every run recorded before it: one that is open on
    an old run makes that run unreadable, and this test fails on it. It can only fail on a run it
    finds, so a recorded run with a completion line is committed where it looks:

    - under ``tests/``, as a ``*.jsonl`` log, or as a ``*.json`` document whose ``events`` list
      holds the log's records as the writer wrote them (any layout, at any depth). Each record is
      decoded and a completion is found by its ``kind``, never by its bytes. Every store the tests
      keep recorded material in must be among the files examined, so a store moved or renamed
      fails here until this test names it;
    - under ``experiments/``, as a run's ``events.jsonl`` in the writer's own bytes.

    A record replay cannot read fails here too: the golden escalation runs drop the timestamps
    and the run's parameters, so a completion line in that form fails this test. Those runs are
    rebuilt through the loop by their own test, whose writer asks the registry for each line.

    At the commit that adds the registry no committed run has a completion line, so the
    repository part passes on nothing; the first part shows the search finds such a run in each
    form and that an entry open on it fails.
    """
    events = finished(tmp_path / "run", monkeypatch)
    records = [json.loads(e.model_dump_json()) for e in events]
    shaped = tmp_path / "repo"
    forms = {
        # A document with its log at the top, laid out by hand: a space after every colon.
        STORES[0] / "a_run.json": json.dumps({"events": records}, indent=2),
        # A log line by line, not named as the writer names one, nor in its bytes.
        STORES[1] / "a_run.jsonl": "".join(json.dumps(r) + "\n" for r in records),
        # One case of several, as the golden file holds them.
        GOLDEN: json.dumps({"a case/on": {"config": [], "events": records}, "other": {}}),
    }
    for where, text in forms.items():
        (shaped / where).parent.mkdir(parents=True, exist_ok=True)
        (shaped / where).write_text(text)
    examined, runs = recorded_runs(shaped / "tests")
    found = with_completions(runs)
    assert sorted(path for path, _ in found) == sorted(shaped / where for where in forms)
    assert unreached(shaped, examined) == []
    for path, run in found:
        assert set(replayed(path, run).completed) == {"s1", "s2"}
    later = Precondition("later", lambda state, module: "open on a run recorded before it")
    monkeypatch.setattr(completion, "PRECONDITIONS", (*completion.PRECONDITIONS, later))
    for path, run in found:
        with pytest.raises(CorruptEventLogError):
            replayed(path, run)
    monkeypatch.undo()
    # The repository's own: every store reached, the golden file's cases decoded.
    examined, runs = recorded_runs(ROOT / "tests")
    assert unreached(ROOT, examined) == []
    assert any(path == ROOT / GOLDEN for path, _ in runs)
    for path, run in with_completions(runs):
        replayed(path, run)
    for log in experiment_logs_with_completions(ROOT / "experiments"):
        replay(read_events(log))
