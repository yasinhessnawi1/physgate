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
always-loaded ceiling, another network setting or another held-out tier. A held-out tier is
compared by the digests each run recorded of its roots (:func:`compared_digests`), less those of
a tier-set store's withheld and work roots: they hold no task of a version, only what is written
beside the tiers (the register, the vectors, the gap trend, the baseline rounds' records, the
blind check's work), so any such write would make two honest runs read as drifted. Whether a
run named those two roots is compared all the same (:func:`compared_held_out`): a run that did
not name them did not withhold what lies there from its sessions. And when
they were measured on different tier versions: the evaluation's record beside each run,
``evaluation/tiers.json``, names the version and each tier's digest; absent from both, nothing
is held; present in one only, differing, or not a record, the comparison is refused. Two
records of one version that left out what different check records flagged (compared by the
record's digest, ``held_out_left_out``), or of which one left out nothing, are refused in words
of their own: their held-out counts are not of one tier.

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

import os
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from physgate.evaluation.baseline.record import TIERS_RECORD, TiersRecord
from physgate.evaluation.observe.exceptions import CompareRefusedError, ManifestError
from physgate.evaluation.observe.manifest import read_run_events
from physgate.evaluation.observe.trace import read_traces
from physgate.evaluation.tiers.task import Role
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
from physgate.toolenv.record import ToolEnvironment

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
    # Compared as :func:`compared_held_out`: the protected tiers' digests, not every root's,
    # and whether each role root's withheld and work roots were named.
    "held_out_sha256",
    # The tools the sessions had: the environment as measured (its interpreter, libraries,
    # roots and manifest digest) and the servers each profile was offered from the register. A
    # run with tools and one without were not asked the same thing.
    "tool_environment",
    "tool_servers",
    # Whether the sessions were denied the binary's search tool: denied, every tool is offered
    # directly; offered, tools are held back behind the search step.
    "tool_search",
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
    "review_compaction",
    "reportable",
    "ablation",
    "os_layer",
    "os_layer_absent",
    "reviewers",
    "skills",
    "hooks",
)

#: Never compared: what names one run (its id and seed), where its held-out tier was and the
#: tokens its tasks carry (the tiers' digests are compared), and what is measured from the
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
    #: What a reader must know before taking the numbers, in words: the tier version both runs
    #: were measured on has been seen since, or whether it was cannot be told.
    notes: tuple[str, ...] = ()


def _role_roots_with_tiers(roots: list[PurePath]) -> set[PurePath]:
    """The role roots, by the spelling recorded, of which ``roots`` names a protected tier."""
    from physgate.evaluation.tiers.manifest import VERSION_NAME
    from physgate.evaluation.tiers.store import PROTECTED

    roles = set(get_args(Role))
    return {
        root.parent.parent
        for root in roots
        if root.name in PROTECTED
        and VERSION_NAME.fullmatch(root.parent.name) is not None
        and root.parent.parent.name in roles
    }


def compared_digests(config: RunConfig) -> tuple[str, ...]:
    """The held-out digests ``config`` is compared on, in the order recorded.

    Each digest the run recorded but those of a tier-set store's withheld and work roots. A root
    is set aside when, by the spelling the run recorded, it is ``<role root>/withheld`` or
    ``<role root>/work`` and the run also names a validation or held-out tier of a version of
    that same role root: those two roots hold no task of a version, and every register line,
    vector, trend line, baseline round and blind check written there changes their digests.
    Every other root is compared: each protected tier, a held-out root outside any store, and a
    root that holds a role's root whole (its digest covers the withheld root, so runs either
    side of a write there still read as drifted). Only what the run recorded is read, nothing
    on disk, so a run recorded before this rule is compared by it as it stands. A run's
    configuration pairs one digest with each root, or it is not one.
    """
    from physgate.evaluation.tiers.store import WITHHELD, WORK

    roots = [PurePath(entry) for entry in config.held_out]
    with_tiers = _role_roots_with_tiers(roots)
    return tuple(
        digest
        for root, digest in zip(roots, config.held_out_sha256, strict=True)
        if not (root.name in (WITHHELD, WORK) and root.parent in with_tiers)
    )


def named_beside_tiers(config: RunConfig) -> tuple[tuple[str, bool, bool], ...]:
    """Whether ``config`` named the withheld and work roots of each role root it names a tier of.

    One ``(role, withheld named, work named)`` for each such role root, sorted. A run that did
    not name either root did not withhold what lies there (the pool, the authoring and check
    streams, the blind check's work) from its sessions, so it was not run as one that did, though
    the two roots' digests are set aside (:func:`compared_digests`). The role root is told by its
    role, not by where the store lay, as the digests are compared and not the paths.
    """
    from physgate.evaluation.tiers.store import WITHHELD, WORK

    roots = [PurePath(entry) for entry in config.held_out]
    named = set(roots)
    return tuple(
        sorted(
            (role_root.name, role_root / WITHHELD in named, role_root / WORK in named)
            for role_root in _role_roots_with_tiers(roots)
        )
    )


def compared_held_out(
    config: RunConfig,
) -> tuple[tuple[str, ...], tuple[tuple[str, bool, bool], ...]]:
    """The held-out roots as two runs are compared on them.

    The digests of :func:`compared_digests`, and :func:`named_beside_tiers`.
    """
    return compared_digests(config), named_beside_tiers(config)


def normal_tool_environment(environment: ToolEnvironment | None) -> dict[str, Any] | None:
    """A tool environment's record with each path relative to the root that holds it.

    Two machines running the same environment place it at other roots, so absolute paths are
    not identity: what is compared is the digest over every file, the counts, the
    interpreter's version, every distribution and every tool's version, and where each path
    lies inside the environment. A path outside every root is another program, kept as named.
    Two runs (:func:`drift`) and the two arms of a per-role pair are held to this one form.
    """
    if environment is None:
        return None
    roots = [PurePosixPath(root) for root in environment.roots]

    def where(path: str) -> str:
        for index, root in enumerate(roots):
            if PurePosixPath(path).is_relative_to(root):
                return f"{index}:{PurePosixPath(path).relative_to(root)}"
        return path

    return {
        "interpreter": where(environment.interpreter),
        "resolved": where(environment.resolved),
        "python_version": environment.python_version,
        "prefix": where(environment.prefix),
        "distributions": [d.model_dump() for d in environment.distributions],
        "native_tools": [
            {**t.model_dump(), "path": where(t.path), "resolved": where(t.resolved)}
            for t in environment.native_tools
        ],
        "roots": len(roots),
        "manifest_digest": environment.manifest_digest,
        "entries": environment.entries,
        "total_bytes": environment.total_bytes,
    }


def drift(baseline: RunConfig, candidate: RunConfig) -> list[str]:
    """Every field of :data:`DRIFT` the candidate does not share with the baseline, by path.

    A set of model strings is compared name by name: a role or a reviewer present in one run
    only is named like one pinned to another string. The held-out roots are compared as
    :func:`compared_held_out` gives them.
    """
    drifted = []
    for path in DRIFT:
        mine, theirs = _at(baseline, path), _at(candidate, path)
        if path == "held_out_sha256":
            mine, theirs = compared_held_out(baseline), compared_held_out(candidate)
        if path == "tool_environment":
            mine, theirs = normal_tool_environment(mine), normal_tool_environment(theirs)
            if mine != theirs:
                drifted.append(path)
        elif isinstance(mine, dict) and isinstance(theirs, dict):
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


def _check_of(tiers: TiersRecord) -> str | None:
    """The digest of the check record whose flagged tasks a run's tiers record left out."""
    left = tiers.held_out_left_out
    return None if left is None else left.check_sha256


def _tiers(run_dir: Path) -> TiersRecord | None:
    """The tier version recorded beside the run, ``evaluation/tiers.json``; ``None`` if none.

    Raises:
        CompareRefusedError: the record is there and is not one, so the version it names cannot
            be held against the other run's.
    """
    path = Path(run_dir) / TIERS_RECORD
    if not os.path.lexists(path):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            return TiersRecord.model_validate_json(handle.read(1024 * 1024))
    except (OSError, ValidationError):
        msg = "a run's tier record is not one, so the version it was measured on is unknown"
        raise CompareRefusedError(msg, drifted=TIERS_RECORD.as_posix()) from None


def _exposed_now(run_dir: Path, config: RunConfig) -> str | None:
    """In words, when the tier version recorded beside the run is marked exposed now; else ``None``.

    The run was checked as it started; its version may have been seen since. The register is
    read in the store the run's held-out roots lie in. Nothing is refused here: the comparison
    stands, with what is known about its tiers said beside it.
    """
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers.exposure import exposed_versions
    from physgate.evaluation.tiers.store import role_roots

    tiers = _tiers(run_dir)
    if tiers is None:
        return None
    for store, role in role_roots(tuple(config.held_out)):
        if role != tiers.role:
            continue
        try:
            exposed = exposed_versions(store, role)
        except PerRoleError:
            return (
                f"whether the tier version {tiers.version[:8]} has been seen since cannot be "
                "told: its register cannot be read whole"
            )
        if tiers.version in exposed:
            return (
                f"the tier version {tiers.version[:8]} has been exposed since: these numbers are "
                "no measurement on it"
            )
    return None


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
    ours, others = _tiers(baseline), _tiers(candidate)
    if (
        ours is not None
        and others is not None
        and (ours.role, ours.version) == (others.role, others.version)
        # One left-out set is one check record: the two are compared by the record's digest.
        and _check_of(ours) != _check_of(others)
    ):
        msg = (
            "the runs were measured on one tier version but left out what different check records "
            "flagged (compared by the record's digest), or one left out what its version's check "
            "flagged and the other did not: their held-out counts are not of one tier, so they are "
            "no comparison"
        )
        raise CompareRefusedError(msg, drifted=f"{TIERS_RECORD.as_posix()}:held_out_left_out")
    if ours != others:
        msg = (
            "the runs were measured on different tier versions, or one names a tier version and "
            "the other none: they are no comparison"
        )
        raise CompareRefusedError(msg, drifted=TIERS_RECORD.as_posix())
    a, b = mine.model_dump(), theirs.model_dump()
    differs: list[Any] = [k for k in REPORTED if a[k] != b[k]]
    notes = [_exposed_now(baseline, mine), _exposed_now(candidate, theirs)]
    return SideBySide(
        baseline=_numbers(baseline, mine),
        candidate=_numbers(candidate, theirs),
        differs_in=tuple(differs),
        notes=tuple(dict.fromkeys(n for n in notes if n is not None)),
    )
