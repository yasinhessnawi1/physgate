"""Harness run directories made by the real loop over the orchestrator's stand-ins.

A trial-layer row that asks whether a run ended needs a log the loop could have written: one
the replay takes as a run. A hand-written handful of lines is not one. So these runs are
made by :class:`~physgate.orchestrator.loop.Loop` itself, with the stand-in dispatcher,
reviewer, gate and merger the orchestrator's own rows use, and the stand-in dispatcher writing
each session's stream beneath ``sessions/``, where the loop's would be.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ORCHESTRATOR_TESTS = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_TESTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_TESTS))

from loop_fakes import FakeDispatcher, FakeReviewer, KilledError, Rig  # noqa: E402

from physgate.orchestrator.record import DecompositionSummary, PlanEntry  # noqa: E402
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


def loop_run(
    run_dir: Path,
    *,
    kill: str | None = None,
    decomposed: bool = False,
    **config: Any,  # noqa: ANN401 - a run configuration's own fields
) -> Path:
    """A run of one control subtask, ``run_id`` ``r``, made by the loop in ``run_dir``.

    ``kill`` is where a killed orchestrator stopped and never resumed: ``"session"`` (during
    the role session) or ``"review"`` (during its review), or ``None`` for a run that ends.
    ``decomposed`` records the run's decomposition line, as a run decomposed by its one call
    does. ``config`` replaces fields of the run's configuration.
    """
    run_dir.mkdir(parents=True)
    rig = Rig(
        run_dir,
        dispatcher=FakeDispatcher(
            trajectories=run_dir / "sessions", kill_on=1 if kill == "session" else None
        ),
        reviewer=FakeReviewer(kill_on=1 if kill == "review" else None),
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
    return run_dir
