"""A rerun of a recorded run, and the comparison that says whether it reproduced.

A rerun is the recorded run made again from its own record: the same brief (held
to its recorded digest), the same seed and parameters, on the same harness
commit, against the same target head and endpoint, under a new run id. It goes
through the orchestrator's own commands, ``decompose`` then ``run``, so nothing
about how a run is made is reimplemented here. Anything the rerun cannot hold
equal is refused before a model is called: a rerun on other code, another
binary or another endpoint is a second run, not a rerun.

The comparison is ``compare_runs``, at the level ``sequence.level_of`` sets from
the recorded endpoint. Both levels are always computed and reported; the
verdict is the one the level names.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.observe.exceptions import RerunError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.sequence import (
    RECORDS,
    Divergence,
    Level,
    RunView,
    decisions,
    event_position,
    first_divergence,
    level_of,
)
from physgate.orchestrator.cli import Registrations, _harness_root
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.run_config import (
    RunConfig,
    harness_state,
    require_endpoint,
    require_harness,
)

#: The configuration fields ``decompose`` measures or is given on its command line;
#: every other field is a parameter, passed as the recorded run had it.
MEASURED = frozenset(
    {"run_id", "seed", "brief_sha256", "target_head", "claude_version", "endpoint", "harness"}
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Comparison(_Frozen):
    """Two runs' records side by side: where each parts, and whether that is a reproduction."""

    recorded_manifest_id: str
    rerun_manifest_id: str
    recorded_run_id: str
    rerun_run_id: str
    level: Level
    #: Per record of the exact level, its first divergence, or ``None``.
    exact: dict[str, Divergence | None]
    #: The first divergence in the decision sequence, or ``None``.
    decisions: Divergence | None
    decisions_compared: int

    @property
    def reproduced(self) -> bool:
        """Whether the rerun reproduced the run, at the level the run's endpoint sets."""
        if self.level == "decisions":
            return self.decisions is None
        return self.decisions is None and all(d is None for d in self.exact.values())

    @property
    def first(self) -> Divergence | None:
        """The divergence that decides the verdict, if there is one."""
        if self.level == "exact":
            found = next((self.exact[r] for r in RECORDS if self.exact[r] is not None), None)
            return found or self.decisions
        return self.decisions


def compare_runs(recorded: Path, rerun: Path) -> Comparison:
    """Compare a rerun's records with the recorded run's.

    Raises:
        ManifestError: either directory does not hold a complete run.
    """
    mine, theirs = read_manifest(recorded), read_manifest(rerun)
    a, b = RunView(recorded), RunView(rerun)
    ra, rb = a.records(), b.records()
    exact: dict[str, Divergence | None] = {}
    for name in RECORDS:
        where = event_position(ra["events"]) if name == "events" else None
        exact[name] = first_divergence(name, ra[name], rb[name], where)
    da, db = decisions(a.events), decisions(b.events)
    return Comparison(
        recorded_manifest_id=mine.manifest_id,
        rerun_manifest_id=theirs.manifest_id,
        recorded_run_id=mine.config.run_id,
        rerun_run_id=theirs.config.run_id,
        level=level_of(mine.config),
        exact=exact,
        decisions=first_divergence(
            "decisions",
            [{k: v for k, v in d.items() if k != "seq"} for d in da],
            [{k: v for k, v in d.items() if k != "seq"} for d in db],
            event_position(a.events, [d["seq"] for d in da]),
        ),
        decisions_compared=max(len(da), len(db)),
    )


@dataclass(frozen=True)
class RerunPlan:
    """What a rerun is driven with: the recorded run's inputs under a new run id."""

    recorded: RunConfig
    brief: Path
    run_id: str
    run_dir: Path
    target: Path
    install: Path

    def params(self) -> dict[str, Any]:
        """The parameters file ``decompose`` takes, as the recorded run had it."""
        dumped: dict[str, Any] = self.recorded.model_dump(mode="json", exclude=set(MEASURED))
        return dumped


#: Drives a rerun to its end; the default goes through the ``physgate`` command.
Driver = Callable[[RerunPlan], None]


def through_the_command(registrations: Registrations | None = None) -> Driver:
    """A driver that runs ``physgate decompose`` then ``physgate run``, as a person would."""

    def drive(plan: RerunPlan) -> None:
        from physgate.cli import main
        from physgate.orchestrator.decompose import binary_version

        try:
            now = binary_version()
        except OrchestratorError as exc:
            raise RerunError(str(exc), **exc.context) from None
        if now != plan.recorded.claude_version:
            msg = "the binary is not the version the recorded run used"
            raise RerunError(msg, recorded=plan.recorded.claude_version, now=now)
        with tempfile.TemporaryDirectory() as scratch:
            params = Path(scratch) / "params.json"
            params.write_text(json.dumps(plan.params()))
            steps = (
                (
                    "decompose",
                    [
                        "decompose",
                        str(plan.brief),
                        "--seed",
                        str(plan.recorded.seed),
                        "--run-id",
                        plan.run_id,
                        "--params",
                        str(params),
                        "--target",
                        str(plan.target),
                        "--run-dir",
                        str(plan.run_dir),
                    ],
                ),
                (
                    "run",
                    [
                        "run",
                        "--run-dir",
                        str(plan.run_dir),
                        "--target",
                        str(plan.target),
                        "--install",
                        str(plan.install),
                    ],
                ),
            )
            for name, argv in steps:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = main(argv, registrations)
                if code == 2:  # a refusal: the rerun did not happen as recorded
                    msg = "the orchestrator refused the rerun"
                    raise RerunError(msg, step=name, detail=err.getvalue().strip())
                if name == "decompose" and code != 0:
                    return  # decomposition failed; the comparison says where

    return drive


def rerun(
    recorded_dir: Path,
    *,
    brief: Path,
    run_id: str,
    run_dir: Path,
    target: Path,
    install: Path,
    driver: Driver | None = None,
) -> Comparison:
    """Make the recorded run again under ``run_id`` and compare the two.

    Raises:
        RerunError: the brief, the harness, the target head or the endpoint is not
            what the run recorded, the run id is the recorded one, or the orchestrator
            refused the rerun.
        ManifestError: the recorded run is not a complete run.
    """
    config = read_manifest(recorded_dir).config
    if run_id == config.run_id:
        msg = "a rerun needs a run id of its own"
        raise RerunError(msg, run_id=run_id)
    digest = hashlib.sha256(Path(brief).read_bytes()).hexdigest()
    if digest != config.brief_sha256:
        msg = "the brief is not the one the recorded run was decomposed from"
        raise RerunError(msg, recorded=config.brief_sha256, now=digest)
    head = head_of(Path(target).resolve(), "HEAD")
    if head != config.target_head:
        msg = "the target's head is not the one the recorded run started from"
        raise RerunError(msg, recorded=config.target_head, now=head)
    try:
        require_harness(config, harness_state(_harness_root()))
        require_endpoint(config, os.environ.get("ANTHROPIC_BASE_URL"))
    except OrchestratorError as exc:
        raise RerunError(str(exc), **exc.context) from None
    plan = RerunPlan(
        recorded=config,
        brief=Path(brief).resolve(),
        run_id=run_id,
        run_dir=Path(run_dir).resolve(),
        target=Path(target).resolve(),
        install=Path(install).resolve(),
    )
    (driver or through_the_command())(plan)
    return compare_runs(recorded_dir, plan.run_dir)
