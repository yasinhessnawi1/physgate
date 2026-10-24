"""A process killed while it carries out a person's approve resumes where it stopped.

An approve merges the attempt it names, then checks the graph for divergence, as a review's
pass does. The attempt had ended without a merge, so no resume line restarts it: the next
process carries the approve on from the record, with the merge if none is recorded, or else the
check. Killed between the check's stage line and the check itself, it makes the check under the
stage already on the record. It never enters that stage twice and never leaves the check out.

Every line is synced before the loop acts on it, and the fakes give the same answers to any
process, so a log cut after line k is what a process killed between lines k and k+1 leaves.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    DecisionTaken,
    DiffChecked,
    EnvironmentRecorded,
    IntegrationGateRan,
    IntegrationGateSkipped,
    OsLayerChecked,
    Resumed,
    SessionSpawned,
    StageEntered,
    SubtaskPlanned,
    WorktreeRemoved,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import Artefact, ReviewResult
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.replay import replay
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present
from physgate.state.task_ledger import TaskLedger

INTEG = "integ"
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
#: The OS layer as the command records it where it runs; a run that acts on decisions needs it.
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")


class Recording(FakeDispatcher):
    """A dispatcher whose installation has facts to record."""

    def environment(self) -> InstallFacts:  # type: ignore[override]
        return FACTS


@dataclass
class NoVerdictOn(FakeReviewer):
    """Reaches no verdict on one subtask's attempt, whichever process asks, and passes the rest."""

    on: tuple[str, int] = ("s1", 1)

    def review(self, artefact: Artefact) -> ReviewResult:
        if (artefact.subtask_id, artefact.attempt) == self.on:
            self.seen.append(artefact)
            raise ReviewUnavailableError("no verdict", cause="invalid_verdict")
        return super().review(artefact)


def models() -> ModelStrings:
    names = ("electrical", "integration")
    return ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(names, "claude-sonnet-5"),
        reviewers=dict.fromkeys(names, "claude-opus-5-5"),
    )


def with_integration(*ids: str) -> list[PlanEntry]:
    integ = PlanEntry(
        subtask_id=INTEG,
        spec_path="specs/integ.md",
        assigned_role="integration",
        module_dir="modules/integration",
    )
    return [*plan(*ids), integ]


#: Each run: its gate mode, its plan, and the attempt whose review reaches no verdict, which a
#: person then approves.
SCENARIOS: dict[str, tuple[str, list[PlanEntry], tuple[str, int]]] = {
    "on, a run without integration, s2 waits": ("on", plan("s1", "s2"), ("s2", 1)),
    "on, s2 waits": ("on", with_integration("s1", "s2"), ("s2", 1)),
    "observe, s2 waits": ("observe", with_integration("s1", "s2"), ("s2", 1)),
    "off, s2 waits": ("off", with_integration("s1", "s2"), ("s2", 1)),
    "on, integration waits": ("on", with_integration("s1"), (INTEG, 1)),
    "off, integration waits": ("off", with_integration("s1"), (INTEG, 1)),
}


def rig_for(run_dir: Path, scenario: str) -> Rig:
    mode, _, waits = SCENARIOS[scenario]
    return Rig(
        run_dir,
        gate_mode=mode,  # type: ignore[arg-type]
        gate=FakeGate(),
        dispatcher=Recording(trajectories=run_dir / "sessions"),
        reviewer=NoVerdictOn(on=waits),
        config_overrides={"queue_decisions": "act", "os_layer": PRESENT, "models": models()},
    )


def layer(loop: Loop) -> Loop:
    """The OS layer recorded where this process runs."""
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": PRESENT, "as_recorded": None}
        )
    )
    return loop


def decided(run_dir: Path, scenario: str) -> tuple[Rig, int]:
    """The run driven to its end with one attempt waiting, then approved; and its line count."""
    run_dir.mkdir(parents=True)
    rig = rig_for(run_dir, scenario)
    loop = rig.open()
    loop.start(SCENARIOS[scenario][1])
    layer(loop)
    assert loop.run().kind == "done"
    loop.close()
    view = read_queue(run_dir)
    (item,) = view.open_items()
    record_decision(
        run_dir,
        item.item_id,
        person=PersonDecision(verb="approve", note=None),
        resolved_by="yasin",
        shown=ShownItem(
            item_sha256=view.digests[item.item_id],
            trajectories=statuses_now(run_dir, item.item_id),
        ),
    )
    return rig, len(read_events(run_dir / "events.jsonl"))


def carry_out(rig: Rig) -> str:
    """The process that takes the decision and acts on it: how the run ends."""
    loop = layer(rig.open())
    try:
        return loop.resume().kind
    finally:
        loop.close()


def cut(full: Path, into: Path, lines: int) -> Path:
    """``full`` as a process killed after its first ``lines`` log lines left it."""
    shutil.copytree(full, into, ignore=shutil.ignore_patterns("events.jsonl", "ledger.jsonl"))
    kept = (full / "events.jsonl").read_bytes().splitlines(keepends=True)[:lines]
    (into / "events.jsonl").write_bytes(b"".join(kept))
    return into


def calls(events: list[Any]) -> list[tuple[str, str | None]]:
    return [
        (type(e).__name__, getattr(e, "reason", None))
        for e in events
        if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)
    ]


def statuses(events: list[Any]) -> dict[str, str]:
    return {s: sub.status for s, sub in replay(events).subtasks.items()}


def approved(events: list[Any]) -> tuple[str, int]:
    (taken,) = [e for e in events if isinstance(e, DecisionTaken)]
    assert taken.effect == "merge" and taken.subtask_id is not None and taken.attempt is not None
    return taken.subtask_id, taken.attempt


def diffs_of(events: list[Any], attempt: tuple[str, int]) -> tuple[list[Any], list[Any]]:
    """The attempt's ``diff`` stage lines and its divergence checks."""
    mine = [
        e for e in events if (getattr(e, "subtask_id", None), getattr(e, "attempt", 0)) == attempt
    ]
    stages = [e for e in mine if isinstance(e, StageEntered) and e.stage == "diff"]
    return stages, [e for e in mine if isinstance(e, DiffChecked)]


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_a_kill_between_an_approved_attempts_diff_stage_and_its_check_resumes_to_one_of_each(
    tmp_path: Path, scenario: str
) -> None:
    rig, _ = decided(tmp_path / "full", scenario)
    end = carry_out(rig)
    full = read_events(tmp_path / "full" / "events.jsonl")
    attempt = approved(full)
    (stage,), _ = diffs_of(full, attempt)
    # The log ends at the stage line: the merge is recorded, the check is not.
    run_dir = cut(tmp_path / "full", tmp_path / "cut", stage.seq + 1)
    assert carry_out(rig_for(run_dir, scenario)) == end
    events = read_events(run_dir / "events.jsonl")
    stages, checks = diffs_of(events, attempt)
    assert [s.seq for s in stages] == [stage.seq]  # never entered twice
    assert len(checks) == 1 and checks[0].seq > stage.seq  # and checked, once
    assert not [e for e in events if isinstance(e, Resumed)]
    assert statuses(events) == statuses(full)
    assert calls(events) == calls(full)
    assert replay(events).ledger == TaskLedger(run_dir / "ledger.jsonl").read_all()


def _spawn(event: Any) -> bool:  # noqa: ANN401 - any line of the log
    """A line a session's spawn follows at once: a role session's or a reviewer's."""
    return (isinstance(event, StageEntered) and event.stage in ("spawn", "review")) or isinstance(
        event, SessionSpawned
    )


def _about(events: list[Any], subtask_id: str) -> list[Any]:
    return [
        e
        for e in events
        if getattr(e, "subtask_id", None) == subtask_id
        and not isinstance(e, SubtaskPlanned | WorktreeRemoved)
    ]


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_a_kill_after_any_line_of_the_process_that_carries_out_an_approve_resumes_to_its_end(
    tmp_path: Path, scenario: str
) -> None:
    rig, decided_at = decided(tmp_path / "full", scenario)
    end = carry_out(rig)
    full = read_events(tmp_path / "full" / "events.jsonl")
    attempt = approved(full)
    (stage,), _ = diffs_of(full, attempt)
    points = range(decided_at, len(full))
    # The sweep reaches the cut that leaves the stage line last, and every other cut of the
    # deciding process.
    assert len(points) > 1 and stage.seq + 1 in points
    problems: list[str] = []
    for k in points:
        run_dir = cut(tmp_path / "full", tmp_path / f"k{k}", k)
        try:
            kind = carry_out(rig_for(run_dir, scenario))
        except Exception as exc:  # noqa: BLE001 - every cut that does not resume is reported
            problems.append(f"k={k}: {type(exc).__name__}: {exc}")
            continue
        events = read_events(run_dir / "events.jsonl")
        if kind != end:
            problems.append(f"k={k}: ended {kind}, the run without a kill ended {end}")
        if calls(events) != calls(full):
            problems.append(f"k={k}: calls {calls(events)}, not {calls(full)}")
        if len([e for e in events if isinstance(e, DecisionTaken)]) != 1:
            problems.append(f"k={k}: the decision was not taken exactly once")
        if statuses(events) != statuses(full):
            problems.append(f"k={k}: statuses {statuses(events)}, not {statuses(full)}")
        stages, checks = diffs_of(events, attempt)
        if (len(stages), len(checks)) != (1, 1):
            problems.append(
                f"k={k}: the approved attempt's diff: {len(stages)} stages, {len(checks)} checks"
            )
        first_call = next(
            (e.seq for e in events if isinstance(e, IntegrationGateRan | IntegrationGateSkipped)),
            None,
        )
        if first_call is not None and any(e.seq < first_call for e in _about(events, INTEG)):
            problems.append(f"k={k}: a line of integration's subtask before the first call")
        if replay(events).ledger != TaskLedger(run_dir / "ledger.jsonl").read_all():
            problems.append(f"k={k}: the ledger is not the log's projection")
        recorded = False
        for event in events[k:]:
            recorded = recorded or isinstance(event, EnvironmentRecorded)
            if _spawn(event) and not recorded:
                problems.append(f"k={k}: a spawn at line {event.seq} before its environment line")
    assert not problems, "\n".join(problems)
