"""Stand-ins for the register's rows: a store of one or two versions, runs on them, the requirement.

The store is the baseline round's stand-in (twenty-four fixture tasks split by the real split),
so a run's task, and so its version, is found by its brief. A second version is split from a
second pool whose tasks have briefs of their own. Runs are laid out as the loop leaves one;
an incident is appended to a run's log as the loop appends it.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

BASELINE_TESTS = Path(__file__).resolve().parents[1] / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import (  # noqa: E402
    LAYER,
    TIERS,
    StandInStore,
    config,
    harness_run,
    stand_in_store,
)
from task_fixtures import controller, own_task, write_task_dir  # noqa: E402

from physgate.evaluation.tiers.store import withheld_root, work_root, write_version  # noqa: E402
from physgate.evaluation.tiers.task import Task, canonical_json, parse_task  # noqa: E402
from physgate.orchestrator.events import EventLog, Incident  # noqa: E402
from physgate.orchestrator.requirements import RunFacts  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402

__all__ = [
    "LAYER",
    "StandInStore",
    "api",
    "config",
    "facts",
    "harness_run",
    "incident_in",
    "refusal",
    "second_version",
    "stand_in_store",
    "with_run_root",
]

REQUIREMENT = "physgate.evaluation.requirements.a_measured_run_is_on_a_known_unexposed_version"


def api(name: str) -> Any:  # noqa: ANN401
    """``module.attribute``, or the row fails: what it names is not built yet."""
    module, _, attribute = name.rpartition(".")
    try:
        found = getattr(importlib.import_module(module), attribute, None)
    except ImportError:
        found = None
    assert found is not None, f"{name} is not built"
    return found


def facts(run: RunConfig, run_dir: Path | None, *, new_run: bool = True) -> RunFacts:
    """What the command shows a requirement, the run's directory among it."""
    try:
        return RunFacts(
            config=run, os_layer=LAYER, shell_sessions=True, new_run=new_run, run_dir=run_dir
        )
    except TypeError:
        pytest.fail("a requirement is not shown the run's directory (RunFacts.run_dir)")


def refusal(run: RunConfig, run_dir: Path | None, *, new_run: bool = True) -> str | None:
    """What the registered requirement says of the run: ``None``, or why it may not go on."""
    requirement = api(REQUIREMENT)
    registered = api("physgate.evaluation.requirements.REQUIREMENTS")
    assert requirement in registered, "the command does not hold runs to it"
    found: str | None = requirement(facts(run, run_dir, new_run=new_run))
    return found


def with_run_root(made: StandInStore, root: Path) -> Path:
    """``root``, made and added to the control role's run roots."""
    root.mkdir(parents=True, exist_ok=True)
    api("physgate.evaluation.tiers.exposure.add_run_root")(made.store, "control", root)
    return root.resolve()


def incident_in(run_dir: Path) -> None:
    """Append a held-out read to the run's log, as the loop records one."""
    log = EventLog(run_dir / "events.jsonl", run_id="r", gate_mode="on")
    log.append(
        Incident(
            **log.envelope(),
            subtask_id=None,
            cause="held_out_read",
            detail="held-out material in the stream of session role-1",
        )
    )
    log.close()


def second_version(
    made: StandInStore, brief: str = "Hold plant number {i} steady. Answer here."
) -> StandInStore:
    """A second version of the control role, split from a pool of tasks with briefs of their own.

    The run it gives withholds both versions' protected tiers and looks for both's canaries, as
    every run on the role must. ``brief`` gives task ``i``'s brief; the default is none of the
    first version's.
    """
    pool = made.store / "control" / "withheld" / "pool"
    for i in range(24):
        write_task_dir(
            pool / f"control.u{i:02d}",
            own_task(id=f"control.u{i:02d}", brief=brief.format(i=i)),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    manifest, _ = write_version(
        made.store / "control",
        sorted(p for p in pool.iterdir() if p.is_dir()),
        role="control",
        seed=6,
        model="claude-sonnet-5",
        runtime="2.1.301",
        provenance=canonical_json({"sessions": [{"session_id": "s-2", "end": "ended"}]}),
        retire=pool,
        generated="2026-11-09",
    )
    directory = made.store / "control" / manifest.version
    tasks: dict[str, list[Task]] = {
        tier: [
            parse_task((d / "task.json").read_bytes())
            for d in sorted((directory / tier).iterdir())
            if d.is_dir()
        ]
        for tier in TIERS
    }
    canaries = tuple(
        c
        for tier in TIERS[1:]
        for c in json.loads((directory / tier / "canaries.json").read_text())
    )
    held_out = (
        str(withheld_root(made.store, "control")),
        str(work_root(made.store, "control")),
        *(str(made.store / "control" / made.version / tier) for tier in TIERS[1:]),
        *(str(directory / tier) for tier in TIERS[1:]),
    )
    return StandInStore(made.store, manifest.version, tasks, made.canaries + canaries, held_out)
