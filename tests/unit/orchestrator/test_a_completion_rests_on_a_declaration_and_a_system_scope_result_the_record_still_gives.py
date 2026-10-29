"""A completion rests on a declaration and a system-scope result that the record still gives.

The loop writes integration's declaration straight after its accepted change check, read from the
commit that check held, and no other attempt's. Before every completion line it takes three things
again, in order, and the first that differs halts the run with nothing written: the declaration,
read again from the commit the attempt merged with the change check's parser (its module list and
its digest both, since a list rewritten in place with the digest kept still replays); every
recorded contract result; and the system-scope result, the gate run again over the canonical store
with the history the log gives up to the gate's line, its place. Before every window of
integration's session the system-scope result is taken again too, beside the contract results its
state quotes. A gate that cannot be run again, as when the journal has moved past the line's
revision, halts as a difference does. Each new halt, killed between its incident and its halt,
resumes to the halt alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as runner
from loop_fakes import FakeChanges, FakeGate, FakeReviewer, KilledError, Rig, passing_gate_result
from test_integration_s_issued_state_is_built_from_the_record_and_held_to_its_line import (
    at_integrations_resolve,
    ended,
    rewrite_gate,
)

from physgate import roles
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.declaration import Declaration
from physgate.orchestrator.events import (
    CompletionDeclared,
    DiffChecked,
    Event,
    Halted,
    Incident,
    IntegrationGateRan,
    IntegrationStateIssued,
    Merged,
    ModuleCompleted,
    ProposalsChecked,
    Resumed,
    StageEntered,
    WorktreeRemoved,
    read_events,
)
from physgate.orchestrator.ports import ChangeCheck
from physgate.orchestrator.protocols import (
    Artefact,
    GateResult,
    IntegrationArtefact,
    ReviewResult,
    RunningGateMode,
)
from physgate.orchestrator.replay import replay
from physgate.roles import CrossCuttingRole
from physgate.series.seal import SessionSeries
from physgate.state.store import Store

INTEG, DRIVE, FW = runner.INTEG, runner.DRIVE, runner.FW
DECLARED = (DRIVE, FW)
DIGEST = "d" * 64
#: A second owner of completion, which only a register patched in a process can hold.
CLOSER = CrossCuttingRole(name="closer", architecture="ARCH-051", owns="completion")


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def declared(*modules: str, sha256: str = DIGEST) -> Declaration:
    return Declaration(modules=modules, sha256=sha256)


def rig_for(tmp_path: Path, **fields: Any) -> Rig:  # noqa: ANN401 - the rig's own
    """The contract rig, whose checker reads ``DECLARED`` in each of integration's attempts."""
    rig = runner.rig_for(tmp_path, **fields)
    rig.changes.declares.setdefault(INTEG, declared(*DECLARED))
    return rig


def log_of(rig: Rig) -> list[Event]:
    return read_events(rig.run_dir / "events.jsonl")


def killed(rig: Rig, kill: Callable[[Event, list[Event]], bool], **start: Any) -> list[Event]:  # noqa: ANN401
    """The rig's run, its process killed as it is about to write the line ``kill`` picks."""
    loop = rig.open()
    emit = loop._emit  # noqa: SLF001 - the loop's own writer
    written: list[Event] = []

    def emitting(event: Event) -> None:
        if kill(event, written):
            raise KilledError
        written.append(event)
        emit(event)

    loop._emit = emitting  # type: ignore[method-assign]  # noqa: SLF001
    runner.start(loop, **start)
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    return log_of(rig)


def take_over(rig: Rig, kill: Callable[[Event, list[Event]], bool] | None = None) -> str:
    """A fresh process takes the run over, as an operator would; how its drive ends."""
    fresh = rig.open()
    if kill is not None:
        emit = fresh._emit  # noqa: SLF001

        def emitting(event: Event) -> None:
            if kill(event, []):
                raise KilledError
            emit(event)

        fresh._emit = emitting  # type: ignore[method-assign]  # noqa: SLF001
    interrupted = replay(log_of(rig)).interrupted() is not None
    end = ended(fresh.resume if interrupted else fresh.run)
    fresh.close()
    return end


def completions(events: Sequence[Event]) -> list[str]:
    return [e.subtask_id for e in events if isinstance(e, ModuleCompleted)]


def the_halt(events: Sequence[Event]) -> tuple[Incident, Halted]:
    (incident,) = [e for e in events if isinstance(e, Incident)]
    (halted,) = [e for e in events if isinstance(e, Halted)]
    return incident, halted


def at_a_completion(n: int = 0) -> Callable[[Event, list[Event]], bool]:
    """The ``n``-th completion line, counted from 0."""
    return lambda e, written: (
        isinstance(e, ModuleCompleted)
        and (sum(isinstance(w, ModuleCompleted) for w in written) == n)
    )


def rewrite_declaration(**fields: Any) -> Callable[[list[dict[str, Any]]], None]:  # noqa: ANN401
    def edit(records: list[dict[str, Any]]) -> None:
        line = next(r for r in records if r["kind"] == "completion_declared")
        line.update(fields)

    return edit


# --- the line ------------------------------------------------------------------------------------


def test_the_loop_writes_integrations_declaration_straight_after_its_accepted_change_check(
    tmp_path: Path,
) -> None:
    # Integration's first change check is refused; its second is accepted. The checker read the
    # declaration both times, and only the accepted check's attempt records it.
    rig = rig_for(tmp_path, changes=FakeChanges(refuse={3: ("proposal", "a node no one writes")}))
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    events = log_of(rig)
    lines = [e for e in events if isinstance(e, CompletionDeclared)]
    assert len(lines) == 1
    line = lines[0]
    checked, after = events[line.seq - 1], events[line.seq + 1]
    assert isinstance(checked, ProposalsChecked)
    assert (checked.subtask_id, checked.attempt, checked.refused_by) == (INTEG, 2, None)
    assert (line.subtask_id, line.attempt, line.modules, line.declaration_sha256) == (
        INTEG,
        2,
        DECLARED,
        DIGEST,
    )
    assert isinstance(after, StageEntered) and (after.subtask_id, after.stage) == (INTEG, "gate")
    # The change check's own line is as it always was: the declaration is not on it.
    assert "declaration" not in json.loads(checked.model_dump_json())
    assert completions(events) == [DRIVE, FW]


def test_only_an_accepted_integration_attempt_causes_module_completed(tmp_path: Path) -> None:
    # Attempt 1 declares both modules and fails its review; attempt 2 declares drive alone.
    changes = FakeChanges(declared={3: declared(DRIVE, FW), 4: declared(DRIVE)})
    rig = runner.rig_for(
        tmp_path, changes=changes, reviewer=FakeReviewer(verdicts=["pass", "pass", "fail"])
    )
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    events = log_of(rig)
    lines = [(e.attempt, e.modules) for e in events if isinstance(e, CompletionDeclared)]
    assert lines == [(1, (DRIVE, FW)), (2, (DRIVE,))]
    assert completions(events) == [DRIVE]


def test_a_refused_declaration_is_the_next_attempts_finding(tmp_path: Path) -> None:
    reason = ".physgate/completion/declaration.json: a later pass over drive"
    rig = rig_for(tmp_path, changes=FakeChanges(refuse={3: ("declaration", reason)}))
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    (retry,) = [r for r in rig.dispatcher.requests if (r.subtask_id, r.attempt) == (INTEG, 2)]
    assert "the completion declaration check" in str(retry.repair_instruction)
    assert reason in str(retry.repair_instruction)
    assert [e.attempt for e in log_of(rig) if isinstance(e, CompletionDeclared)] == [2]


class Patching(FakeChanges):
    """A checker during whose check of integration's attempt the register gains a second owner.

    Past the register's own check, as only a register patched in a process can be: the run was
    opened under one owner, and the register changes between the check and the line.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, armed: bool = True) -> None:
        super().__init__()
        self.monkeypatch = monkeypatch
        self.armed = armed

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
    ) -> ChangeCheck:
        if subtask_id == INTEG and self.armed:
            self.monkeypatch.setitem(roles.ROLES, CLOSER.name, CLOSER)
        return super().check(subtask_id, attempt_commit, role, series=series)


def test_the_completion_owner_lookup_refuses_two_owners_in_the_loop_before_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The writer would refuse the line and leave nothing on the record: asked first, the loop
    # halts with the cause on the record, and no declaration is written.
    rig = rig_for(tmp_path, changes=Patching(monkeypatch))
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "halted"
    loop.close()
    events = log_of(rig)
    incident, halted = the_halt(events)
    assert (incident.subtask_id, incident.cause) == (INTEG, "duty_breach")
    assert "more than one role owns completion" in incident.detail
    assert halted.detail == f"duty_breach in {INTEG}"
    assert isinstance(events[incident.seq - 1], ProposalsChecked)
    assert not [e for e in events if isinstance(e, CompletionDeclared)]


# --- the declaration taken again ----------------------------------------------------------------


def test_a_declarations_module_list_rewritten_with_its_digest_kept_halts_before_any_completion(
    tmp_path: Path,
) -> None:
    rig = rig_for(tmp_path)
    killed(rig, at_a_completion())
    runner.rewritten(rig.run_dir / "events.jsonl", rewrite_declaration(modules=[DRIVE]))
    assert replay(log_of(rig)).owed_completion() == DRIVE  # the log still reads
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == []
    incident, halted = the_halt(events)
    assert (incident.subtask_id, incident.cause) == (None, "declaration_mismatch")
    assert halted.detail == "declaration_mismatch"
    assert "declaration" in incident.detail


def test_a_declarations_digest_rewritten_halts_before_any_completion(tmp_path: Path) -> None:
    rig = rig_for(tmp_path)
    killed(rig, at_a_completion())
    runner.rewritten(rig.run_dir / "events.jsonl", rewrite_declaration(declaration_sha256="e" * 64))
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == []
    assert the_halt(events)[0].cause == "declaration_mismatch"


def test_a_merged_commit_that_holds_no_declaration_now_halts_before_any_completion(
    tmp_path: Path,
) -> None:
    rig = rig_for(tmp_path)
    events = killed(rig, at_a_completion())
    (merged,) = [e for e in events if isinstance(e, Merged) and e.subtask_id == INTEG]
    rig.changes.held[merged.merge_commit] = None
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == []
    assert the_halt(events)[0].cause == "declaration_mismatch"
    assert rig.changes.read_at[-1] == (merged.merge_commit, INTEG)


def test_a_declaration_rewritten_between_two_completions_halts_before_the_second(
    tmp_path: Path,
) -> None:
    rig = rig_for(tmp_path)
    killed(rig, at_a_completion(1))
    runner.rewritten(rig.run_dir / "events.jsonl", rewrite_declaration(declaration_sha256="e" * 64))
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == [DRIVE]
    assert the_halt(events)[0].cause == "declaration_mismatch"


# --- the system-scope result taken again --------------------------------------------------------


def as_a_pass(records: list[dict[str, Any]]) -> None:
    ran = next(r for r in records if r["kind"] == "integration_gate_ran")
    assert ran["result"]["verdict"] == "fail"
    ran["result"] = json.loads(passing_gate_result("observe").model_dump_json())


def test_a_system_scope_verdict_rewritten_from_fail_to_pass_halts_before_any_completion(
    tmp_path: Path,
) -> None:
    # Observed and failed, the result withholds every completion. Rewritten as a pass after
    # integration's state was issued, it would let both through: the gate run again says not.
    rig = rig_for(tmp_path, gate_mode="observe", gate=FakeGate(integration_verdict="fail"))
    killed(rig, lambda e, _: isinstance(e, DiffChecked) and e.subtask_id == INTEG)
    runner.rewritten(rig.run_dir / "events.jsonl", as_a_pass)
    assert replay(log_of(rig)).integration is not None
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == []
    incident, halted = the_halt(events)
    assert (incident.subtask_id, incident.cause) == (None, "foreign_journal_line")
    assert halted.detail == "foreign_journal_line"
    assert "system-scope result" in incident.detail


def a_check_rewritten(records: list[dict[str, Any]]) -> None:
    ran = next(r for r in records if r["kind"] == "integration_gate_ran")
    ran["result"]["checks"][0]["message"] = "rewritten"


@pytest.mark.parametrize(
    "edit", [rewrite_gate, a_check_rewritten], ids=["its catalogue digest", "a check's words"]
)
def test_a_gate_line_with_its_verdict_kept_and_a_check_rewritten_halts(
    tmp_path: Path, edit: Callable[[list[dict[str, Any]]], None]
) -> None:
    rig = rig_for(tmp_path)
    killed(rig, at_a_completion())
    runner.rewritten(rig.run_dir / "events.jsonl", edit)
    assert take_over(rig) == "halted"
    events = log_of(rig)
    assert completions(events) == []
    incident, _ = the_halt(events)
    assert incident.cause == "foreign_journal_line" and "system-scope result" in incident.detail


@pytest.mark.parametrize(
    ("edits", "cause"),
    [
        ((rewrite_declaration(modules=[DRIVE]), rewrite_gate), "declaration_mismatch"),
        ((rewrite_gate,), "foreign_journal_line"),
    ],
    ids=["both rewritten", "the gate line alone"],
)
def test_a_rewritten_declaration_and_a_rewritten_gate_line_halt_on_the_declaration_first(
    tmp_path: Path, edits: tuple[Callable[[list[dict[str, Any]]], None], ...], cause: str
) -> None:
    rig = rig_for(tmp_path)
    killed(rig, at_a_completion())
    for edit in edits:
        runner.rewritten(rig.run_dir / "events.jsonl", edit)
    assert take_over(rig) == "halted"
    incident, _ = the_halt(log_of(rig))
    assert incident.cause == cause


class RealSystemGate(FakeGate):
    """The real gate at system scope over the run's own store, recording what it gave."""

    def __init__(self) -> None:
        super().__init__()
        self.gave: list[GateResult] = []

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        self.integrations.append(artefact)
        self.gave.append(PhysicsGate().check_integration(artefact, mode=mode))
        return self.gave[-1]


def test_the_real_gate_gives_one_result_twice_over_one_store(tmp_path: Path) -> None:
    gate = RealSystemGate()
    rig = rig_for(tmp_path, gate=gate)
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    first = gate.integrations[0]
    assert PhysicsGate().check_integration(first, mode="on") == gate.gave[0]
    assert PhysicsGate().check_integration(first, mode="on") == gate.gave[0]


def test_an_honest_run_reaches_completion_with_the_system_scope_taken_again_and_equal(
    tmp_path: Path,
) -> None:
    # Over the real gate and the canonical store: the call, then one re-run before integration's
    # window and one before each of the two completion lines, each the same question and answer.
    gate = RealSystemGate()
    rig = rig_for(tmp_path, gate=gate)
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    events = log_of(rig)
    (ran,) = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert ran.result.verdict == "pass"
    assert completions(events) == [DRIVE, FW]
    assert len(gate.integrations) == 4
    assert all(a == gate.integrations[0] for a in gate.integrations)
    assert all(r == ran.result for r in gate.gave)


class Appending(FakeReviewer):
    """A reviewer during whose review of integration a line is appended to the canonical journal."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

    def review(self, artefact: Artefact) -> ReviewResult:
        if artefact.subtask_id == INTEG:
            store = Store(self.root)
            payload = runner.node(
                "fw.main", "firmware", "iface.drive", "iface.tilt", v=12, period=10
            )
            assert store.write_node(payload, "firmware").accepted
            store.close()
        return super().review(artefact)


def test_a_journal_past_the_gate_lines_revision_halts_at_completion(tmp_path: Path) -> None:
    # Nothing honest writes the store after the gate's line in this harness. A journal that has
    # moved past the line's revision cannot give the result again at its place: the run halts.
    gate = RealSystemGate()
    rig = rig_for(tmp_path, gate=gate, reviewer=Appending(tmp_path / "store"))
    loop = rig.open()
    runner.start(loop)
    assert ended(loop.run) == "halted"
    loop.close()
    events = log_of(rig)
    assert completions(events) == []
    assert [e.subtask_id for e in events if isinstance(e, Merged)][-1] == INTEG
    incident, _ = the_halt(events)
    assert (incident.subtask_id, incident.cause) == (None, "foreign_journal_line")
    assert "system-scope result" in incident.detail


# --- kill points --------------------------------------------------------------------------------


def comparable(events: Sequence[Event]) -> list[dict[str, Any]]:
    return runner.comparable(events)


def at_the_declaration(event: Event, _: list[Event]) -> bool:
    return isinstance(event, CompletionDeclared)


def arm(rig: Rig) -> None:
    assert isinstance(rig.changes, Patching)
    rig.changes.armed = True


def in_the_log(edit: Callable[[list[dict[str, Any]]], None]) -> Callable[[Rig], None]:
    return lambda rig: runner.rewritten(rig.run_dir / "events.jsonl", edit)


#: Where the first process dies, what then makes the next step halt, and the halt's cause.
HOLDS: dict[str, tuple[Callable[[Event, list[Event]], bool], str, str]] = {
    "the declaration at a completion": (at_a_completion(), "declaration", "declaration_mismatch"),
    "the system scope before integration's state": (
        at_integrations_resolve,
        "gate",
        "foreign_journal_line",
    ),
    "the system scope at a completion": (at_a_completion(), "gate", "foreign_journal_line"),
    "the register at the declaration": (at_the_declaration, "register", "duty_breach"),
}


@pytest.mark.parametrize("hold", HOLDS)
def test_a_kill_between_a_holds_incident_and_its_halt_resumes_to_the_halt_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hold: str
) -> None:
    kill, what, cause = HOLDS[hold]
    put = {
        "declaration": in_the_log(rewrite_declaration(modules=[DRIVE])),
        "gate": in_the_log(rewrite_gate),
        "register": arm,
    }[what]

    def made(path: Path) -> Rig:
        armed = Patching(monkeypatch, armed=False) if what == "register" else FakeChanges()
        return rig_for(path, changes=armed)

    def over(rig: Rig, kill: Callable[[Event, list[Event]], bool] | None = None) -> str:
        # A register patched in one process is not the next one's: it opens under one owner.
        end = take_over(rig, kill)
        monkeypatch.delitem(roles.ROLES, CLOSER.name, raising=False)
        return end

    # The run as it would have been: the process that finds the incident is not killed.
    reference = made(tmp_path / "reference")
    killed(reference, kill)
    put(reference)
    assert over(reference) == "halted"
    # The same run, with that process killed between its incident and its halt.
    rig = made(tmp_path / "cut")
    killed(rig, kill)
    put(rig)
    assert over(rig, lambda e, _: isinstance(e, Halted)).startswith("raised KilledError")
    cut = log_of(rig)
    assert isinstance(cut[-1], Incident) and cut[-1].cause == cause
    assert replay(cut).next_step().kind == "halt"
    assert over(rig) == "halted"
    events = log_of(rig)
    assert [type(e) for e in events if isinstance(e, Incident | Halted)] == [Incident, Halted]
    later = [e for e in events[len(cut) :] if not isinstance(e, Resumed)]
    assert isinstance(later[0], Halted)
    assert all(isinstance(e, WorktreeRemoved) for e in later[1:])
    assert comparable(events) == comparable(log_of(reference))
    assert replay(events).next_step().kind == "halted"


def at_integrations_stage(stage: str) -> Callable[[Event, list[Event]], bool]:
    return lambda e, _: isinstance(e, StageEntered) and (e.subtask_id, e.stage) == (INTEG, stage)


@pytest.mark.parametrize(
    "kill",
    [at_the_declaration, at_integrations_stage("gate")],
    ids=["between the change check and the declaration", "between the declaration and the gate"],
)
def test_a_kill_around_the_declaration_resumes_to_the_uninterrupted_tail(
    tmp_path: Path, kill: Callable[[Event, list[Event]], bool]
) -> None:
    reference = rig_for(tmp_path / "reference")
    loop = reference.open()
    runner.start(loop)
    assert ended(loop.run) == "done"
    loop.close()
    honest = log_of(reference)
    rig = rig_for(tmp_path / "cut")
    cut = killed(rig, kill)
    assert take_over(rig) == "done"
    events = log_of(rig)
    (resume,) = [e for e in events if isinstance(e, Resumed)]
    assert (resume.subtask_id, resume.point) == (INTEG, "verify_reading")
    # The attempt is checked again and its declaration read again: from there on, the run
    # writes what the uninterrupted one wrote.
    start = next(
        i
        for i, e in enumerate(honest)
        if isinstance(e, StageEntered) and (e.subtask_id, e.stage) == (INTEG, "verify_reading")
    )
    assert comparable(events[resume.seq + 1 :]) == comparable(honest[start:])
    assert (
        len([e for e in events if isinstance(e, CompletionDeclared)])
        == len([e for e in cut if isinstance(e, CompletionDeclared)]) + 1
    )
    assert completions(events) == [DRIVE, FW]
    assert not [e for e in events if isinstance(e, IntegrationStateIssued)][1:]
