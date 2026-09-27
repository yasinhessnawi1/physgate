"""Two runs' numbers side by side, refused when what answered them has drifted.

A comparison across a changed model means nothing: a baseline measured on one
model and a candidate on another differ for a reason neither run can show. So
``compare`` refuses, and does not warn, when any pinned model string differs
(the decomposition model, any role's, any reviewer's, or a role present in one
run only), when the binary's version differs, or when the endpoint differs.
The way past the refusal is a fresh baseline under the candidate's pins.

What an ablation changes on purpose is reported beside the numbers, never
refused: the gate mode, the harness commit, the auth mode, the effort level and
the output-token limit.

The check runs on the two configurations before anything else is read, so a
drifted run is refused as drifted, not for some later reason. It cannot see a
provider changing the model behind an unchanged string.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.observe.exceptions import CompareRefusedError, ManifestError
from physgate.evaluation.observe.manifest import read_run_events
from physgate.evaluation.observe.trace import read_traces
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import (
    AttemptRejected,
    Escalated,
    IntegrationGateRan,
    Merged,
    SessionEnded,
)
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.run_config import RunConfig, load_run_config

#: Reported when they differ, never refused: what an ablation varies on purpose.
REPORTED = ("gate_mode", "auth", "effort", "max_output_tokens", "harness")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RunNumbers(_Frozen):
    """One run's numbers, with the manifest id and the settings they were measured under."""

    manifest_id: str
    run_id: str
    gate_mode: str
    auth: str
    effort: str
    max_output_tokens: int
    harness_commit: str | None
    harness_clean: bool
    reportable: bool
    tokens: dict[str, int]
    sessions: int
    attempts_merged: int
    attempts_rejected: int
    subtasks_escalated: int
    #: The integration gate's verdict, or ``None`` when it did not run.
    integration: str | None
    wall_clock_s: float


class SideBySide(_Frozen):
    """A baseline and a candidate, compared: numbers side by side, what differs on purpose."""

    baseline: RunNumbers
    candidate: RunNumbers
    #: The reported settings that differ between the two, by field name.
    differs_in: tuple[str, ...]


def drift(baseline: RunConfig, candidate: RunConfig) -> list[str]:
    """Every pinned field the candidate does not share with the baseline, by path."""
    drifted = []
    if baseline.models.decomposition != candidate.models.decomposition:
        drifted.append("models.decomposition")
    for kind in ("roles", "reviewers"):
        mine: dict[str, str] = getattr(baseline.models, kind)
        theirs: dict[str, str] = getattr(candidate.models, kind)
        drifted += [
            f"models.{kind}.{k}"
            for k in sorted(mine.keys() | theirs.keys())
            if mine.get(k) != theirs.get(k)
        ]
    if baseline.claude_version != candidate.claude_version:
        drifted.append("claude_version")
    if baseline.endpoint != candidate.endpoint:
        drifted.append("endpoint")
    return drifted


def _config(run_dir: Path) -> RunConfig:
    try:
        return load_run_config(Path(run_dir) / "run.json")
    except OrchestratorError as exc:
        raise ManifestError(str(exc), **exc.context) from None


def _numbers(run_dir: Path, config: RunConfig) -> RunNumbers:
    trace = read_traces(run_dir)
    events = read_run_events(run_dir)
    integration = [e for e in events if isinstance(e, IntegrationGateRan)]
    return RunNumbers(
        manifest_id=trace.manifest_id,
        run_id=config.run_id,
        gate_mode=config.gate_mode,
        auth=config.auth,
        effort=config.effort,
        max_output_tokens=config.max_output_tokens,
        harness_commit=config.harness.commit,
        harness_clean=config.harness.clean,
        reportable=config.reportable,
        tokens={k: u.total() for k, u in TokenAccount.from_events(events).by_kind().items()},
        sessions=sum(1 for e in events if isinstance(e, SessionEnded)),
        attempts_merged=sum(1 for e in events if isinstance(e, Merged)),
        attempts_rejected=sum(1 for e in events if isinstance(e, AttemptRejected)),
        subtasks_escalated=sum(1 for e in events if isinstance(e, Escalated)),
        integration=integration[-1].result.verdict if integration else None,
        wall_clock_s=_elapsed(trace.started, trace.last),
    )


def _elapsed(start: str, end: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    return (datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds()


def compare(baseline: Path, candidate: Path) -> SideBySide:
    """The two runs' numbers side by side, unless what answered them has drifted.

    Raises:
        CompareRefusedError: a pinned model string, the binary version or the
            endpoint differs; every drifted field is named.
        ManifestError: either directory does not hold a complete run.
    """
    mine, theirs = _config(baseline), _config(candidate)
    drifted = drift(mine, theirs)
    if drifted:
        msg = (
            "the runs were answered under different pins: re-run the baseline under the "
            "candidate's before comparing"
        )
        raise CompareRefusedError(msg, drifted=",".join(drifted))
    a, b = mine.model_dump(), theirs.model_dump()
    differs: list[Any] = [k for k in REPORTED if a[k] != b[k]]
    return SideBySide(
        baseline=_numbers(baseline, mine),
        candidate=_numbers(candidate, theirs),
        differs_in=tuple(differs),
    )
