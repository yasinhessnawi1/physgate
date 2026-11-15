"""Two runs' numbers side by side, refused when what answered them has drifted.

A comparison across a changed model means nothing: a baseline measured on one
model and a candidate on another differ for a reason neither run can show. So
``compare`` refuses, and does not warn, when any pinned model string differs
(the decomposition model, any role's, any reviewer's, or a role present in one
run only), when a pinned model setting differs (the effort level, the
output-token limit and whether role sessions' reasoning is summarized into their
trajectories, which set what every request asks the model for; a run recorded
before the last existed reads as not summarized), when the
binary's version differs, when the git binary both runs recorded differs (its
path or its version; a run recorded before git was recorded is not compared on
it, since nothing was measured), or when the endpoint differs. The way past the
refusal is a fresh baseline under the candidate's pins.

It refuses as well when the two runs were not asked the same thing from the same
place: another brief, another commit of the target, other session bounds, another
always-loaded ceiling, another network setting or another held-out tier.

What an ablation changes on purpose is reported beside the numbers, never
refused: the gate mode and every other flag, the run's kind, the OS layer, the
harness commit and the auth mode.

**No field is equal by being overlooked.** Every field of a run's configuration,
and each kind of model string, is in exactly one of :data:`DRIFT`,
:data:`REPORTED` and :data:`PER_RUN`; :func:`census_problems` names any that is
not, so a switch or a pin added later is classed before two runs are compared
across it.

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

#: Refused when they differ, in the order they are named: what answered the run, then what it
#: was asked and from where. Each kind of model string has its own entry.
DRIFT: tuple[str, ...] = (
    "models.decomposition",
    "models.roles",
    "models.reviewers",
    "effort",
    "max_output_tokens",
    "thinking_display",
    "role_python",
    "claude_version",
    "binary",
    "git_binary",
    "endpoint",
    "brief_sha256",
    "target_head",
    "bounds",
    "token_ceiling",
    "network",
    "held_out_sha256",
)

#: Reported when they differ, never refused: what an ablation varies on purpose.
REPORTED: tuple[str, ...] = (
    "gate_mode",
    "auth",
    "harness",
    "escalation_backend",
    "queue_decisions",
    "design_review",
    "parts_on_hand",
    "reportable",
    "ablation",
    "os_layer",
    "os_layer_absent",
    "reviewers",
    "skills",
    "hooks",
)

#: Never compared: what names one run (its id and seed), where its held-out tier was and the
#: tokens its tasks carry (the tier's digests are compared), and what is measured from the
#: network setting and the OS layer, which are both classed above. The account is left out on
#: purpose: runs spread over several accounts of one plan compare.
PER_RUN: tuple[str, ...] = (
    "run_id",
    "seed",
    "held_out",
    "held_out_canaries",
    "network_enforced",
    "account",
)

#: Compared only where both runs recorded it: ``None`` is a run that measured nothing. The
#: binary's bytes as well as its version: another platform's build, or a replaced binary, is
#: another tool under measurement.
_WHERE_BOTH_RECORDED = frozenset({"binary", "git_binary"})


def census_problems(model: type[RunConfig] = RunConfig) -> list[str]:
    """Every way the three lists fail to class each field of ``model`` exactly once, by name.

    A field of the model nested as ``models`` is named by its path, so a model string of a new
    kind is a field with no decision like one added at the top.
    """
    kinds: dict[str, Any] = getattr(model.model_fields["models"].annotation, "model_fields", {})
    fields = set(model.model_fields) - {"models"} | {f"models.{kind}" for kind in kinds}
    classed = [*DRIFT, *REPORTED, *PER_RUN]
    found = [
        f"{name}: in no list, so two runs that differ on it would compare as equal"
        for name in fields - set(classed)
    ]
    found += [f"{name}: in more than one list" for name in set(classed) if classed.count(name) > 1]
    found += [f"{name}: names no field of a run's configuration" for name in set(classed) - fields]
    return sorted(found)


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
    thinking_display: str
    #: The escalation backend the run was bound to; ``None`` for a run recorded before the
    #: binding existed.
    escalation_backend: str | None
    queue_decisions: str
    design_review: str
    reviewers: str
    skills: str
    hooks: str
    ablation: bool
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
    """Every field of :data:`DRIFT` the candidate does not share with the baseline, by path.

    A set of model strings is compared name by name: a role or a reviewer present in one run
    only is named like one pinned to another string.
    """
    drifted = []
    for path in DRIFT:
        mine, theirs = _at(baseline, path), _at(candidate, path)
        if isinstance(mine, dict) and isinstance(theirs, dict):
            drifted += [
                f"{path}.{key}"
                for key in sorted(mine.keys() | theirs.keys())
                if mine.get(key) != theirs.get(key)
            ]
        elif path in _WHERE_BOTH_RECORDED and (mine is None or theirs is None):
            continue
        elif mine != theirs:
            drifted.append(path)
    return drifted


def _at(config: RunConfig, path: str) -> Any:  # noqa: ANN401 - each field's own type
    """The value of ``config`` at a dotted ``path``."""
    value: Any = config
    for part in path.split("."):
        value = getattr(value, part)
    return value


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
        thinking_display=config.thinking_display,
        escalation_backend=config.escalation_backend,
        queue_decisions=config.queue_decisions,
        design_review=config.design_review,
        reviewers=config.reviewers,
        skills=config.skills,
        hooks=config.hooks,
        ablation=config.ablation,
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
        CompareRefusedError: a field of :data:`DRIFT` differs (a pinned model string or
            setting, the binary, the endpoint, or what the run was asked and from where);
            every drifted field is named.
        ManifestError: either directory does not hold a complete run.
    """
    mine, theirs = _config(baseline), _config(candidate)
    drifted = drift(mine, theirs)
    if drifted:
        msg = (
            "the runs were answered under different pins, or asked different things: re-run "
            "the baseline under the candidate's before comparing"
        )
        raise CompareRefusedError(msg, drifted=",".join(drifted))
    a, b = mine.model_dump(), theirs.model_dump()
    differs: list[Any] = [k for k in REPORTED if a[k] != b[k]]
    return SideBySide(
        baseline=_numbers(baseline, mine),
        candidate=_numbers(candidate, theirs),
        differs_in=tuple(differs),
    )
