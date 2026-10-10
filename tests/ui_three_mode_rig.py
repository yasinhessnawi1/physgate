"""The physics gate's three-mode plan, rebuilt for the operator UI's tests with the real gate.

The physics gate's three-mode test drives its stand-in drive-power plan through the command,
with the real binary on the scripted endpoint. The UI's tests need the same runs whole (the
journal, the ledger, the sessions) and in CI, where there is no binary. So the plan is driven
here through the real loop, the real store, real git and the real ``PhysicsGate``, in ``on``,
``observe`` and ``off``. Two things are stand-ins, labelled as such: the session, which writes
the plan's proposals as the scripted one does, and the reviewer, which passes as the scripted
one does. **Every gate record in these runs is the real gate's.**

What the three runs hold, each asserted where it is built so a run that no longer shows it
fails here rather than leaving a browser test with nothing to look at:

- ``drive-on``: three attempts refused on the module's power, with a thermal warning, unchecked
  records and a pass over nothing; the subtask escalated; integration not gated;
- ``drive-observe``: every check run and nothing refused, the reviewer passing, merged, and the
  integration call failing power and thermal, every line ``observe``;
- ``drive-off``: the gate skipped and said so, the reviewer passing, merged.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from knowledge_fixture import build_fixture_library
from stand_in_drive_plan import DRIVE_MODULE, POWER_BUS
from ui_rig import evaluation_rig

from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.decompose import Outcome, Plan, PlannedModule, mint_id, start_run
from physgate.orchestrator.events import (
    Escalated,
    GateRan,
    GateSkipped,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.run_config import RunConfig
from physgate.orchestrator.trajectory import seal
from physgate.state.schema import Node

SEED = 7
MODULE = ("drive", "modules/power")
MODES: tuple[str, ...] = ("on", "observe", "off")


@dataclass
class StandInSession:
    """Writes the plan's proposals into the attempt's worktree, as the scripted session does."""

    layout: RunGit
    payloads: tuple[dict[str, Any], ...]
    #: The rig's clock, which a session moves on by the time a session takes; none in real time.
    clock: TickingClock | None = None
    calls: int = 0

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[Leftover]:
        return []

    def run(self, request: SessionRequest) -> SessionReport:
        self.calls += 1
        if self.clock is not None:
            self.clock.spend(TickingClock.SESSION)
        worktree = self.layout.open_subtask(request.subtask_id)
        module = worktree / request.module_dir
        module.mkdir(parents=True, exist_ok=True)
        (module / "power.py").write_text(f"# stand-in session, attempt {request.attempt}\n")
        proposals = worktree / ".physgate" / "proposals"
        proposals.mkdir(parents=True, exist_ok=True)
        for payload in self.payloads:
            (proposals / f"{payload['id']}.json").write_text(json.dumps(payload))
        sid = f"stand-in-{uuid.uuid4().hex[:12]}"
        stream = self.layout.run_dir / "sessions" / sid / "stdout.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(json.dumps({"type": "result", "session_id": sid}) + "\n")
        commit = commit_attempt(worktree, request.subtask_id, request.attempt, sid)
        usage = Usage(
            input_tokens=1200 * self.calls,
            output_tokens=310,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=150,
        )
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=commit,
            trajectory=str(stream),
            trajectory_seal=seal(stream.read_bytes()),
            worktree=str(worktree),
            reading_verified=True,
            node_files_halted=False,
            usage=(MessageUsage(message_id=f"msg-{uuid.uuid4().hex[:8]}", usage=usage),),
        )


def _start(runs: Path, run_id: str, repo: Path, mode: str, library: Path) -> RunConfig:
    cfg: RunConfig = evaluation_rig().config(run_id, repo, gate_mode=mode, seed=SEED)
    name, module_dir = MODULE
    plan = Plan(
        modules=(
            PlannedModule(
                name=name, role="electrical", module_dir=module_dir, spec="Size the power."
            ),
        ),
        interface_nodes=(Node.model_validate(POWER_BUS),),
    )
    outcome = Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model="claude-sonnet-5",
        num_turns=1,
    )
    start_run(outcome, config=cfg, run_dir=runs / run_id, target_repo=repo, library=library).close()
    return cfg


class TickingClock:
    """A clock the rig moves itself: a tick per line the loop writes, more for a session.

    The browser tests read where the timeline draws each segment, and that follows the log's
    timestamps. Driven by the wall clock, a loaded machine stretched one step and shrank every
    other segment, so whether a label fitted depended on the machine's load that minute. Driven
    by this clock, every duration is a count of lines and sessions, the same on every machine and
    every run. A session spends ``SESSION`` on it, as a session dominates a real run.
    """

    TICK = timedelta(milliseconds=250)
    SESSION = timedelta(seconds=10)

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def __call__(self) -> datetime:
        now = self._now
        self._now += self.TICK
        return now

    def spend(self, how_long: timedelta) -> None:
        """Move the clock on by ``how_long``, as work between two lines would."""
        self._now += how_long


def _drive(
    runs: Path,
    cfg: RunConfig,
    repo: Path,
    gate: Any = None,  # noqa: ANN401 - the real physics gate, or the evaluation rig's test gate
    payloads: tuple[dict[str, Any], ...] = DRIVE_MODULE,
) -> str:
    run_dir = runs / cfg.run_id
    run = RunGit(repo=repo, run_dir=run_dir, run_id=cfg.run_id)
    keeper = StoreKeeper(run, run_dir / "store")
    clock = TickingClock()
    name, module_dir = MODULE
    loop = Loop(
        config=cfg,
        run_dir=run_dir,
        gate=PhysicsGate() if gate is None else gate,
        reviewers={
            role: evaluation_rig().Reviewer(model=m, ids="drive")
            for role, m in cfg.models.reviewers.items()
        },
        dispatcher=StandInSession(run, payloads, clock=clock),
        changes=GitChangeChecker(run, run_dir / "store", {mint_id(cfg.seed, 0, name): module_dir}),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        sleep=lambda _: None,
        clock=clock,
    )
    try:
        step = loop.run()
    finally:
        loop.close()
        keeper.close()
    return step.kind


def _require_what_the_three_mode_test_showed(run_dir: Path, mode: str, step: str) -> None:
    """The run shows what the three-mode test asserts of it, or the rig refuses to hand it over."""
    events = read_events(run_dir / "events.jsonl")
    gated = [e for e in events if isinstance(e, GateRan)]
    reviews = [e for e in events if isinstance(e, ReviewRan)]
    merged = [e for e in events if isinstance(e, Merged)]
    problems: list[str] = []
    if mode == "on":
        verdicts = [(g.result.verdict, g.result.failing_check) for g in gated]
        outcomes = {r.outcome for g in gated for r in g.result.checks}
        over_nothing = [
            r
            for g in gated
            for r in g.result.checks
            if r.outcome == "pass" and getattr(r.details, "evaluated", None) == 0
        ]
        skipped = [e for e in events if isinstance(e, IntegrationGateSkipped)]
        if verdicts != [("fail", "power")] * 3:
            problems.append(f"on: gate verdicts {verdicts}")
        if not {"pass", "fail", "warn", "unchecked"} <= outcomes:
            problems.append(f"on: outcomes {outcomes}")
        if not over_nothing:
            problems.append("on: no pass over nothing")
        escalated = [e for e in events if isinstance(e, Escalated)]
        if reviews or merged or len(escalated) != 1:
            problems.append(
                f"on: reviewed {len(reviews)}, merged {len(merged)}, escalated {len(escalated)}"
            )
        if [s.reason for s in skipped] != ["not_all_merged"]:
            problems.append("on: integration was not skipped as incomplete")
    elif mode == "observe":
        integrations = [e for e in events if isinstance(e, IntegrationGateRan)]
        failed = {
            (r.name, r.node) for e in integrations for r in e.result.checks if r.outcome == "fail"
        }
        if len(integrations) != 1:
            problems.append(f"observe: {len(integrations)} integration calls")
        if [g.result.verdict for g in gated] != ["fail"] or len(reviews) != 1 or len(merged) != 1:
            problems.append("observe: not one failing gate, one review and one merge")
        if failed != {("power", "electrical.drive"), ("thermal", "electrical.driver")}:
            problems.append(f"observe: integration failures {failed}")
        if step != "done":
            problems.append(f"observe: ended {step}")
    else:
        skipped_gate = [e for e in events if isinstance(e, GateSkipped)]
        if gated or len(skipped_gate) != 1 or len(merged) != 1 or step != "done":
            problems.append(f"off: gated {len(gated)}, skipped {len(skipped_gate)}, ended {step}")
    if {e.gate_mode for e in events} != {mode}:
        problems.append(f"{mode}: lines in other modes")
    if problems:
        msg = (
            "the rebuilt three-mode run no longer shows what the three-mode test asserts: "
            + "; ".join(problems)
        )
        raise AssertionError(msg)


def three_mode_runs(root: Path, runs: Path) -> tuple[Path, ...]:
    """Build ``drive-on``, ``drive-observe`` and ``drive-off`` under ``runs``; return them."""
    library = build_fixture_library(root / "library-drive")
    built = []
    for mode in MODES:
        repo = evaluation_rig().target_repo(root / f"target-drive-{mode}")
        run_id = f"drive-{mode}"
        cfg = _start(runs, run_id, repo, mode, library)
        step = _drive(runs, cfg, repo)
        _require_what_the_three_mode_test_showed(runs / run_id, mode, step)
        built.append(runs / run_id)
    return tuple(built)


def _node(node_id: str, domain: str, constrains: list[str]) -> dict[str, Any]:
    """A node in ``domain``, owned and written by the run's one role."""
    return {
        "id": node_id,
        "kind": "component",
        "domain": domain,
        "owner_role": "electrical",
        "quantities": {
            "power_draw": {
                "value": 2,
                "unit": "W",
                "source": "datasheet",
                "written_by": "electrical",
            }
        },
        "requirements": [],
        "constrains": constrains,
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-10-10T12:00:00Z",
    }


#: A graph across three domains: a supply constrains a balance loop, which constrains a loop in
#: firmware. It exists so the design graph's domain filter is seen across domains in a browser.
TWO_DOMAINS: tuple[dict[str, Any], ...] = (
    _node("electrical.supply", "electrical", ["control.balance"]),
    _node("control.balance", "control", ["firmware.loop"]),
    _node("firmware.loop", "firmware", []),
)


def two_domain_run(root: Path, runs: Path) -> Path:
    """``domains``: a gated run whose merged graph spans electrical, control and firmware.

    Driven by the evaluation rig's test gate, which passes, so the nodes merge; the gate here is
    not under test, the graph's domains are.
    """
    library = build_fixture_library(root / "library-domains")
    repo = evaluation_rig().target_repo(root / "target-domains")
    cfg = _start(runs, "domains", repo, "on", library)
    step = _drive(runs, cfg, repo, gate=evaluation_rig().Gate(), payloads=TWO_DOMAINS)
    events = read_events(runs / "domains" / "events.jsonl")
    if step != "done" or len([e for e in events if isinstance(e, Merged)]) != 1:
        msg = f"the two-domain run did not merge: ended {step}"
        raise AssertionError(msg)
    return runs / "domains"


def cut_after_first_gate_stage(source: Path, target: Path) -> Path:
    """A copy of ``source`` whose log ends right after its first gate stage line.

    What a process killed while the gate checked would leave: the stage was entered and no
    result was written. Nothing else in the copy changes.
    """
    shutil.copytree(source, target, symlinks=True)
    log = target / "events.jsonl"
    lines = log.read_text().splitlines(keepends=True)
    cut = next(
        i
        for i, line in enumerate(lines)
        if json.loads(line)["kind"] == "stage_entered" and json.loads(line)["stage"] == "gate"
    )
    log.write_text("".join(lines[: cut + 1]))
    return target
