"""A run's manifest: every input and every artefact a number from the run is traced back to.

The manifest is not a second file beside the run: it is assembled from the run's
own records and validated whole. ``run.json`` holds the resolved configuration
(seed, every pinned model string, bounds, gate mode, effort level, output-token
limit, endpoint, auth mode, binary version, the target's head and the harness
checkout); the event log holds what the run observed and produced; git holds the
trees. A copy of any of these would be a second record that could disagree with
the first, so the manifest only reads them.

The manifest's id is the sha256 of ``run.json`` as written. The run's first event
line carries the same digest, and the manifest refuses a run where the two
differ: the configuration a number names must be the one the run started under.

Two request fields the pinned binary sends are not a run's to choose, because no
setting pins them: its thinking mode and its beta list. They are constants of the
binary's version, measured, and recorded here beside the version they belong to.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from physgate.evaluation.observe.exceptions import ManifestError
from physgate.orchestrator.common import first_problem
from physgate.orchestrator.events import (
    Decomposed,
    EnvironmentRecorded,
    Event,
    Merged,
    RunStarted,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.exceptions import GitError, OrchestratorError
from physgate.orchestrator.git import git
from physgate.orchestrator.install import InstallFacts
from physgate.orchestrator.managed import ObservedTraffic
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.state.exceptions import DesignStateError
from physgate.state.store import journal_records_after

Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BinaryDefaults(_Frozen):
    """What the pinned binary sends that no run setting pins: constants of its version."""

    claude_version: str
    # The request fields as the binary sends them, recorded whole: JSON objects.
    thinking: dict[str, Any]
    context_management: dict[str, Any]
    anthropic_beta: tuple[str, ...]
    measured: str


#: Measured at the scripted endpoint on 27.09.2026, identical across the decomposition
#: call and role sessions and across repeated runs; with ``--output-format json`` the
#: thinking field also carried ``display: omitted``, which no invocation here uses.
BINARY_DEFAULTS: dict[str, BinaryDefaults] = {
    "2.1.272": BinaryDefaults(
        claude_version="2.1.272",
        thinking={"type": "adaptive"},
        context_management={"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        anthropic_beta=(
            "claude-code-20250219",
            "interleaved-thinking-2025-05-14",
            "thinking-token-count-2026-05-13",
            "context-management-2025-06-27",
            "prompt-caching-scope-2026-01-05",
            "mid-conversation-system-2026-04-07",
            "effort-2025-11-24",
        ),
        measured="request bodies at the scripted endpoint, Claude Code 2.1.272, 27.09.2026",
    ),
    #: Measured separately at the scripted endpoint on 28.09.2026 (T9's binary bump,
    #: evidence/t9): every field below is identical to 2.1.272's, across the
    #: decomposition call, a tool-using role session and a resumed session. This is
    #: a distinct, independently measured entry, not an alias of 2.1.272's, because
    #: the manifest states what was actually measured for the version a run used.
    #: A small, reproducible stream-ordering difference was found alongside this
    #: (the decomposition call's tool-result event moves relative to its message's
    #: own closing events); it does not touch any field recorded here, or the
    #: result object's fields, and is recorded in MAINTENANCE.md, not here.
    "2.1.283": BinaryDefaults(
        claude_version="2.1.283",
        thinking={"type": "adaptive"},
        context_management={"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        anthropic_beta=(
            "claude-code-20250219",
            "interleaved-thinking-2025-05-14",
            "thinking-token-count-2026-05-13",
            "context-management-2025-06-27",
            "prompt-caching-scope-2026-01-05",
            "mid-conversation-system-2026-04-07",
            "effort-2025-11-24",
        ),
        measured="request bodies at the scripted endpoint, Claude Code 2.1.283, 28.09.2026",
    ),
}


class MergedArtefact(_Frozen):
    """One accepted attempt: the commit the session made, the merge, and both trees."""

    subtask_id: str
    attempt: Annotated[int, Field(ge=1)]
    attempt_commit: Sha1
    attempt_tree: Sha1
    merge_commit: Sha1
    merge_tree: Sha1


class TrajectoryHash(_Frozen):
    """A session's captured stream, as its seal recorded it when the session ended."""

    session_id: str
    subtask_id: str
    attempt: Annotated[int, Field(ge=1)]
    sha256: Sha256
    length: Annotated[int, Field(ge=0)]


class ArtefactHashes(_Frozen):
    """Every artefact of the run, by content hash."""

    brief_sha256: Sha256
    #: The specifications written at decomposition; ``None`` when decomposition failed.
    spec_commit: Sha1 | None
    spec_tree: Sha1 | None
    merged: tuple[MergedArtefact, ...]
    #: The run branch as the log leaves it: its last merge, else its start.
    run_branch_head: Sha1 | None
    run_branch_tree: Sha1 | None
    #: The design-state graph: its journal's digest and newest revision, and the store
    #: repository's last commit and tree.
    journal_sha256: Sha256 | None
    journal_head_revision: Annotated[int, Field(ge=0)]
    store_commit: Sha1 | None
    store_tree: Sha1 | None
    trajectories: tuple[TrajectoryHash, ...]
    #: The hooks' installation manifest digest each driving process recorded.
    install_manifests: tuple[Sha256, ...]


class RunManifest(_Frozen):
    """What a run's numbers are traced back to: its inputs, the machine, its artefacts."""

    #: The sha256 of ``run.json`` as written; every number the commands print carries it.
    manifest_id: Sha256
    config: RunConfig
    binary_defaults: BinaryDefaults
    #: The binary's served catalog and remote flags as the decomposition call observed them.
    observed_traffic: ObservedTraffic | None
    policy_limits_sha256: Sha256 | None
    environments: tuple[InstallFacts, ...]
    artefacts: ArtefactHashes


def _tree(repo: Path, commit: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip()
    except GitError:
        msg = "the run records a commit its repository does not hold"
        raise ManifestError(msg, commit=commit, repository=str(repo)) from None


def _artefacts(run_dir: Path, config: RunConfig, events: list[Event]) -> ArtefactHashes:
    integration = run_dir / "worktrees" / "_integration"
    decomposed = next((e for e in events if isinstance(e, Decomposed)), None)
    spec_commit = decomposed.spec_commit if decomposed else None
    merged = tuple(
        MergedArtefact(
            subtask_id=e.subtask_id,
            attempt=e.attempt,
            attempt_commit=e.attempt_commit,
            attempt_tree=_tree(integration, e.attempt_commit),
            merge_commit=e.merge_commit,
            merge_tree=_tree(integration, e.merge_commit),
        )
        for e in events
        if isinstance(e, Merged)
    )
    head = merged[-1].merge_commit if merged else spec_commit
    store = run_dir / "store"
    journal = store / "journal.jsonl"
    try:
        records = journal_records_after(store, 0)
    except DesignStateError as exc:
        msg = "the run's graph journal holds a line the store could not have written"
        raise ManifestError(msg, journal=str(journal), reason=str(exc)) from None
    store_commit = store_tree = None
    if (store / ".git").exists():
        store_commit = git(store, "rev-parse", "HEAD").strip()
        store_tree = _tree(store, store_commit)
    return ArtefactHashes(
        brief_sha256=config.brief_sha256,
        spec_commit=spec_commit,
        spec_tree=_tree(integration, spec_commit) if spec_commit else None,
        merged=merged,
        run_branch_head=head,
        run_branch_tree=_tree(integration, head) if head else None,
        journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest()
        if journal.exists()
        else None,
        journal_head_revision=records[-1].rev if records else 0,
        store_commit=store_commit,
        store_tree=store_tree,
        trajectories=tuple(
            TrajectoryHash(
                session_id=e.session_id,
                subtask_id=e.subtask_id,
                attempt=e.attempt,
                sha256=e.trajectory_seal.sha256,
                length=e.trajectory_seal.length,
            )
            for e in events
            if isinstance(e, SessionEnded) and e.trajectory_seal is not None
        ),
        install_manifests=tuple(
            dict.fromkeys(
                e.facts.manifest_sha256
                for e in events
                if isinstance(e, EnvironmentRecorded) and e.facts.manifest_sha256 is not None
            )
        ),
    )


def manifest_id_of(run_dir: Path, events: list[Event]) -> str:
    """The run's manifest id, held to the digest its first event line carries.

    Every reader that prints a number takes the id from here.

    Raises:
        ManifestError: there is no configuration, or it is not the one the run started under.
    """
    try:
        manifest_id = hashlib.sha256((Path(run_dir) / "run.json").read_bytes()).hexdigest()
    except FileNotFoundError:
        msg = "the run directory holds no configuration"
        raise ManifestError(msg, run_dir=str(run_dir)) from None
    started = events[0] if events else None
    if not isinstance(started, RunStarted) or started.config_sha256 != manifest_id:
        msg = "the run's first line does not name the configuration recorded beside it"
        raise ManifestError(msg, run_dir=str(run_dir), manifest_id=manifest_id)
    return manifest_id


def read_run_events(run_dir: Path) -> list[Event]:
    """The run's event log, read fresh; a missing or damaged log is a domain error.

    Raises:
        ManifestError: the log is missing, or holds a line the orchestrator could not
            have written.
    """
    try:
        return read_events(Path(run_dir) / "events.jsonl")
    except FileNotFoundError:
        msg = "the run directory holds no event log"
        raise ManifestError(msg, run_dir=str(run_dir)) from None
    except OrchestratorError as exc:
        raise ManifestError(str(exc), **exc.context) from None


def read_manifest(run_dir: Path) -> RunManifest:
    """The run's manifest, assembled from its records and validated whole.

    The one reader of the format: the command and any other consumer call this.

    Raises:
        ManifestError: a record is missing, damaged, or disagrees with another: the
            configuration with the run's first line, a commit with its repository.
    """
    run_dir = Path(run_dir)
    events = read_run_events(run_dir)
    try:
        config = load_run_config(run_dir / "run.json")
    except OrchestratorError as exc:
        raise ManifestError(str(exc), **exc.context) from None
    manifest_id = manifest_id_of(run_dir, events)
    defaults = BINARY_DEFAULTS.get(config.claude_version)
    if defaults is None:
        msg = "no measured defaults are recorded for the binary version this run used"
        raise ManifestError(msg, claude_version=config.claude_version)
    decomposed = next((e for e in events if isinstance(e, Decomposed)), None)
    try:
        return RunManifest(
            manifest_id=manifest_id,
            config=config,
            binary_defaults=defaults,
            observed_traffic=decomposed.observed_traffic if decomposed else None,
            policy_limits_sha256=decomposed.policy_limits_sha256 if decomposed else None,
            environments=tuple(e.facts for e in events if isinstance(e, EnvironmentRecorded)),
            artefacts=_artefacts(run_dir, config, events),
        )
    except ValidationError as exc:
        msg = "the run's records do not make a complete manifest"
        raise ManifestError(msg, reason=first_problem(exc)) from None
