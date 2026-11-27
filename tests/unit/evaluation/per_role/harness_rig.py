"""Harness run directories made by the real loop over the orchestrator's stand-ins.

A trial-layer row that asks whether a run ended needs a log the loop could have written: one
the replay takes as a run. A hand-written handful of lines is not one. So these runs are
made by :class:`~physgate.orchestrator.loop.Loop` itself, with the stand-in dispatcher,
reviewer, gate and merger the orchestrator's own rows use, and the stand-in dispatcher writing
each session's stream beneath ``sessions/``, where the loop's would be. Each session's and each
review's spawn is on the log as the real dispatcher and reviewer record it, and each review's
stream is beneath the run's review root.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ORCHESTRATOR_TESTS = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_TESTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_TESTS))

from loop_fakes import FakeDispatcher, FakeReviewer, KilledError, Rig  # noqa: E402

from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook  # noqa: E402
from physgate.orchestrator.protocols import Artefact, ReviewResult  # noqa: E402
from physgate.orchestrator.record import DecompositionSummary, PlanEntry  # noqa: E402
from physgate.orchestrator.review_root_record import record_review_root  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings  # noqa: E402

#: The models of a run whose one subtask is a control task's.
CONTROL_MODELS = ModelStrings(
    decomposition="claude-sonnet-5",
    roles={"control": "claude-sonnet-5"},
    reviewers={"control": "claude-opus-5-5"},
)
SUBTASK = PlanEntry(
    subtask_id="s1", spec_path="specs/s1.md", assigned_role="control", module_dir="modules/s1"
)
DECOMPOSED = DecompositionSummary(
    session_id="d1",
    model="claude-sonnet-5",
    num_turns=1,
    subtasks=1,
    interface_nodes=("iface.bus",),
    spec_commit="a" * 40,
    head_revision=1,
)


#: The start time a stand-in records at its spawn, as a held process's is recorded.
SPAWN_STARTED = "stand-in"


@dataclass
class SpawningDispatcher(FakeDispatcher):
    """The stand-in dispatcher, each session's spawn recorded first, as the real one records it."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        if on_spawn is not None:
            on_spawn(f"sess-{len(self.requests) + 1}", os.getpid(), SPAWN_STARTED)
        return super().run(request, on_spawn)


@dataclass
class SpawningReviewer(FakeReviewer):
    """The stand-in reviewer, each review's session spawned and its stream left as the real one's.

    Its stream is beneath ``review_root``, where the real reviewer leaves it.
    """

    review_root: Path | None = None
    hook: SpawnHook | None = None

    def record_spawns(self, hook: SpawnHook) -> None:
        self.hook = hook

    def review(self, artefact: Artefact) -> ReviewResult:
        sid = f"rev-{len(self.seen) + 1}"
        if self.hook is not None:
            self.hook(sid, os.getpid(), SPAWN_STARTED)
        if self.review_root is not None:
            stream = self.review_root / sid / "session" / "stdout.jsonl"
            stream.parent.mkdir(parents=True, exist_ok=True)
            stream.write_text(json.dumps({"type": "result", "session_id": sid}) + "\n")
        return super().review(artefact)


def loop_run(
    run_dir: Path,
    *,
    kill: str | None = None,
    decomposed: bool = False,
    verdicts: tuple[str, ...] = (),
    halted_on: str | None = None,
    **config: Any,  # noqa: ANN401 - a run configuration's own fields
) -> Path:
    """A run of one control subtask, ``run_id`` ``r``, made by the loop in ``run_dir``.

    ``kill`` is where a killed orchestrator stopped and never resumed: ``"session"`` (during
    the role session) or ``"review"`` (during its review), or ``None`` for a run that ends.
    ``decomposed`` records the run's decomposition line, as a run decomposed by its one call
    does. ``verdicts`` are the reviewer's, call by call; a pass after them. ``config``
    replaces fields of the run's configuration. ``halted_on`` is an infrastructure cause the
    first session ends on: with no retry scheduled the run halts on the machine, and a second
    process resumes it once, as a person or a round driver would, and lets it end on its own.
    """
    run_dir.mkdir(parents=True)
    # As the command records it before anything runs: the run reviews inside its own directory.
    record_review_root(run_dir, run_dir / "review")
    rig = Rig(
        run_dir,
        dispatcher=SpawningDispatcher(
            trajectories=run_dir / "sessions",
            kill_on=1 if kill == "session" else None,
            infra={} if halted_on is None else {1: halted_on},  # type: ignore[dict-item]
        ),
        reviewer=SpawningReviewer(
            kill_on=1 if kill == "review" else None,
            verdicts=list(verdicts),
            review_root=run_dir / "review",
        ),
        config_overrides={"run_id": "r", "models": CONTROL_MODELS, **config},
    )
    loop = rig.open()
    loop.record.start([SUBTASK], decomposed=DECOMPOSED if decomposed else None)
    loop.close()
    loop = rig.open()
    try:
        loop.run()
    except KilledError:
        if kill is None:
            raise
    finally:
        loop.close()
    if halted_on is not None:
        loop = rig.open()
        try:
            loop.resume()
        finally:
            loop.close()
    return run_dir
