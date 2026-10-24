"""Every role session a process spawns follows that process's own environment line.

The environment a session runs in is the installation of the process that spawns it, so each
process records it before its first spawn, whatever led there: the run's first step, a retry,
a resumed session, the integration call a process took over at, or a person's decision taken
by a process that started at a run's end. A process that spawns no session records none at
the call, as before.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from decision_rig import BLOCKED
from loop_fakes import FakeDispatcher, FakeGate, FakeReviewer, KilledError, Rig, plan

from physgate.orchestrator.events import (
    EnvironmentRecorded,
    OsLayerChecked,
    StageEntered,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.protocols import GateResult, IntegrationArtefact, RunningGateMode
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present

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
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
NO_VERDICT = ReviewUnavailableError("no verdict", cause="invalid_verdict")


class Recording(FakeDispatcher):
    """A dispatcher whose installation has facts to record."""

    def environment(self) -> InstallFacts:  # type: ignore[override]
        return FACTS


def models() -> ModelStrings:
    names = ("electrical", "integration")
    return ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(names, "claude-sonnet-5"),
        reviewers=dict.fromkeys(names, "claude-opus-5-5"),
    )


def with_integration(*ids: str) -> list[PlanEntry]:
    integ = PlanEntry(
        subtask_id="integ",
        spec_path="specs/integ.md",
        assigned_role="integration",
        module_dir="modules/integration",
    )
    return [*plan(*ids), integ]


class Run:
    """A run driven process by process, each process's first line noted."""

    def __init__(self, run_dir: Path, *, acts: bool = False, **fields: Any) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        overrides: dict[str, Any] = {"models": models()}
        if acts:
            overrides |= {"queue_decisions": "act", "os_layer": PRESENT}
        fields.setdefault("dispatcher", Recording(trajectories=run_dir / "sessions"))
        self.acts = acts
        self.rig = Rig(run_dir, config_overrides=overrides, **fields)
        self.starts: list[int] = []

    def process(self) -> Loop:
        """A new process opening the run: a fresh loop over the file."""
        path = self.rig.run_dir / "events.jsonl"
        self.starts.append(len(read_events(path)) if path.exists() else 0)
        loop = self.rig.open()
        return loop

    def layer(self, loop: Loop) -> None:
        if self.acts:
            loop.record.emit(
                OsLayerChecked.model_validate(
                    {**loop.record.envelope(), "state": PRESENT, "as_recorded": None}
                )
            )

    def decide(self, verb: str) -> None:
        """A person decides the one open item from the listing, bound to what it printed."""
        run_dir = self.rig.run_dir
        view = read_queue(run_dir)
        (item,) = view.open_items()
        record_decision(
            run_dir,
            item.item_id,
            person=PersonDecision(verb=verb, note="once more"),  # type: ignore[arg-type]
            resolved_by="yasin",
            shown=ShownItem(
                item_sha256=view.digests[item.item_id],
                trajectories=statuses_now(run_dir, item.item_id),
            ),
        )


def _a_fresh_run_with_a_retry(run_dir: Path) -> Run:
    run = Run(run_dir, reviewer=FakeReviewer(verdicts=["fail", "pass"]))
    loop = run.process()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    return run


def _a_session_killed_and_resumed(run_dir: Path) -> Run:
    run = Run(run_dir, dispatcher=Recording(trajectories=run_dir / "sessions", kill_on=1))
    loop = run.process()
    loop.start(plan("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    run.rig.dispatcher.kill_on = None
    again = run.process()
    assert again.resume().kind == "done"
    again.close()
    return run


class DiesAtTheCall(FakeGate):
    """A gate whose first whole-design call never returns: the process dies inside it."""

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        if not getattr(self, "died", False):
            self.died = True
            raise KilledError
        return super().check_integration(artefact, mode=mode)


def _a_process_that_takes_over_at_the_call(run_dir: Path) -> Run:
    run = Run(run_dir, gate=DiesAtTheCall())
    loop = run.process()
    loop.start(with_integration("s1"))
    with pytest.raises(KilledError):
        loop.run()
    loop.close()
    again = run.process()
    assert again.state.next_step().kind == "integrate"
    assert again.resume().kind == "done"
    again.close()
    return run


def _decided_at_a_runs_end(run_dir: Path, *, plan_of: list[PlanEntry], verb: str, **f: Any) -> Run:
    run = Run(run_dir, acts=True, **f)
    loop = run.process()
    loop.start(plan_of)
    run.layer(loop)
    assert loop.run().kind == "done"
    loop.close()
    run.decide(verb)
    again = run.process()
    run.layer(again)
    assert again.resume().kind == "done"
    again.close()
    return run


SCENARIOS: dict[str, Callable[[Path], Run]] = {
    "a fresh run, and a retry in the same process": _a_fresh_run_with_a_retry,
    "a session killed, then resumed": _a_session_killed_and_resumed,
    "a process that takes over at the integration call": _a_process_that_takes_over_at_the_call,
    "integration after an approve completes a design": lambda d: _decided_at_a_runs_end(
        d,
        plan_of=with_integration("s1", "s2"),
        verb="approve",
        reviewer=FakeReviewer(unavailable={2: NO_VERDICT}),
    ),
    "a reject's retry in a run without integration": lambda d: _decided_at_a_runs_end(
        d, plan_of=plan("s1"), verb="reject", reviewer=FakeReviewer(unavailable={1: NO_VERDICT})
    ),
    "the fix a person orders after a blocked review": lambda d: _decided_at_a_runs_end(
        d, plan_of=plan("s1"), verb="reject", reviewer=FakeReviewer(results={1: BLOCKED})
    ),
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_spawn_follows_an_environment_line_of_its_own_process(
    tmp_path: Path, scenario: str
) -> None:
    run = SCENARIOS[scenario](tmp_path / "run")
    events = read_events(run.rig.run_dir / "events.jsonl")
    bounds = [*run.starts, len(events)]
    spawns = 0
    for start, end in zip(bounds, bounds[1:], strict=False):
        recorded = False
        for event in events[start:end]:
            if isinstance(event, EnvironmentRecorded):
                assert event.facts == FACTS
                recorded = True
            if isinstance(event, StageEntered) and event.stage == "spawn":
                spawns += 1
                assert recorded, (
                    f"{scenario}: the spawn at line {event.seq} follows no environment line "
                    f"of the process that began at line {start}"
                )
    # Every process drove at least one spawn after the first, so the invariant was exercised
    # in each, and each process records its environment once.
    assert spawns >= len(run.starts)
    for start, end in zip(bounds, bounds[1:], strict=False):
        lines = [e for e in events[start:end] if isinstance(e, EnvironmentRecorded)]
        assert len(lines) == 1, f"{scenario}: {len(lines)} environment lines from one process"
