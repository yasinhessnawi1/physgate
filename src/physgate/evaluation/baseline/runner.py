"""The baseline round: the raw arm on every trial a set of harness runs made on a tier version.

**What it is given.** A tier-set store, a role and a version id, and the harness run set: one
entry per harness trial, its run directory and its trial number. Nothing names a task. Each
harness run recorded the digest of the brief it was given, and the round finds the run's task
as the one task of the version, in any of its three tiers, with that brief. So the run set,
which a person writes and keeps anywhere, holds no held-out or validation id.

**Everything is refused before any session starts** (:func:`plan`), and before any
credential is read: a store a split or a session's work has not left clean; a version that
is not what its manifest says, or two of whose tasks share a brief, or that the register, read
now, marks exposed (a run may have seen it since the harness runs started); an entry whose run no
task of the version was given, that is listed twice, whose run recorded another endpoint
than the operator's (the record's endpoint is compared, never a destination for the
credential), whose run does not withhold the protected places of every role's root in the
store or did not look for the version's protected canaries and those listed under every
role's root in the store (the raw session withholds exactly what its run did, and looks
for what it looked for), or
whose run is an ablation run (never a baseline trial, in a development round too), whose
run executed another build of the session binary than another run of the set that recorded
one (the account is never compared), or whose run's token account cannot give a cap
(:func:`.arms.compare.harness_total`); and, unless the round is a development one, a
harness run that is not reportable or not from a clean checkout.

**Each trial** runs the raw arm once (:func:`.arms.raw.run_raw`) under a setup derived from
the harness run's own record (:func:`setup_from_run`), capped at that run's total, every class
of token counted. Its answer is scored harness-side by the scorer the caller gives; a session
the machine ended before an answer existed is run once more, whole, after the harness run's
own first infrastructure delay, and if the machine ends it again it is ``unscored``. The pair
is then held equal (:func:`.arms.compare.differences`): any difference but the two a
development round names (``reportable``, ``harness``) refuses the round, with the fields
named and nothing of the task. The trial is assembled by the trial layer
(:func:`.assemble.raw_trial`), excluded where its records say so.

**Where a trial lies.** Every trial, visible or protected, is made where a blind check's work
is: in the role's work root, which every run on the store withholds. Its directory holds two:
the session's own place, which alone is taken out of the run's held-out roots for its session,
and the harness's, beside it, where the copied answer, the session's record and the score are
written and which stays withheld with every other place those roots hold. The round's own
directory, where its finished visible trials and its records lie, is withheld from every
session besides. So a session reads and writes its own place and nothing else of the round. A
record in the role's root names the trial's directory before the session starts.

Once a trial is scored and compared, the harness moves it. A protected trial's whole directory
is renamed beneath the role's withheld root, ``withheld/baseline/<round id>/``: a validation or
held-out task's trial is never in a visible place, at any step. A visible trial's is moved
beneath the round's directory, ``work/<name>``, the destination made new, so one already there
refuses the move. Where the round's directory lies on another filesystem than the store, the
move is a copy, file by file: each file read as every file a session could have reached is read
(:func:`.orchestrator.session_files.open_beneath`: no link followed, a regular file with no
other name, under a size bound) and written as a new file, never through a link; a link is
copied as the link it is; anything else refuses the move; and the trial's directory is removed
only once the copy is whole. A move that fails removes what it had made beneath the round's
directory. The record is removed once the trial is moved. A round stopped at any step leaves the
trial's directory where it was, in the work root or moved whole, and the record, and nothing
starts on the store until a person has looked. A setup that cannot be made (no credential,
another binary) is refused before the record is written, so it leaves nothing. A protected
trial's records go beneath the withheld root too; the visible tier's lie in the round's own
directory.

**What it writes,** beside the visible trials: ``evaluation/tiers.json`` and ``baseline.json``
(:mod:`.record`), each a new file, counts and digests only.

**What the blind check flagged is left out.** A round on a version is refused unless the
version's blind check is recorded (:mod:`.tiers.checks`): a held-out tier nobody checked is not
scored. A harness trial of a held-out task the record flags is not run, and the held-out count
leaves it out; the tiers record says how many, with the check record's digest and its source.
The visible and validation tiers are run whole.

**An external task set** (a published benchmark's tasks, ARCH-143) is a source of its own, given
by its directory in place of a version (:func:`_external_tasks`): every task in it is an
external one of the role and of one benchmark, and the set lies outside the store. Its trials
are run as a visible tier's are, since a published task is no protected one, counted under
``external`` alone, and its round writes ``evaluation/external.json`` in place of
``tiers.json``. The store is still named and still refused when not clean, and every harness
run must still withhold its protected places and look for the canaries listed under every
role's root in the store; there is no version, so no version's own are asked for. Whether
an external number may be reported waits on its audit, which is a person's reading
(ARCH-143), never this module's.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import secrets
import shutil
import stat
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import Field, StringConstraints

from physgate.evaluation.baseline.record import (
    BASELINE_RECORD,
    EXTERNAL_RECORD,
    EXTERNAL_TIERS,
    TIERS_RECORD,
    VERSION_TIERS,
    BaselineRecord,
    ExternalSetRecord,
    SourceTier,
    TierCounts,
    pin_set,
    pin_set_sha256,
    record_bytes,
    tiers_record,
    write_new,
)
from physgate.evaluation.observe.cost import DatedSheet
from physgate.evaluation.per_role.arms.compare import ComparisonError, differences, harness_total
from physgate.evaluation.per_role.arms.raw import RawSetup, run_raw
from physgate.evaluation.per_role.assemble import (
    ExcludedTrial,
    TrialExcludedError,
    raw_ended_by_infrastructure,
    raw_trial,
)
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.report import TrialRecord
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.canaries import store_canaries
from physgate.evaluation.tiers.checks import CheckRecord, LeftOut, left_out, said
from physgate.evaluation.tiers.heldout import tier_digest
from physgate.evaluation.tiers.manifest import TierSet, read_version
from physgate.evaluation.tiers.store import (
    BASELINE_DIR as BASELINE_DIR,
)
from physgate.evaluation.tiers.store import (
    PLACE as PLACE,
)
from physgate.evaluation.tiers.store import (
    WORKING,
    WorkRootHeld,
    WorkRootUnlockable,
    holding_work_root,
    leftover_refusal,
    make_role_root,
    protected_tier_refusal,
    role_root,
    running_session,
    spelling_refusal,
    spelt_as_on_disk,
    version_dir,
    withheld_refusal,
    withheld_root,
    work_refusal,
    work_root,
)
from physgate.evaluation.tiers.task import (
    PROTECTED_TIERS,
    ExternalSource,
    Role,
    Task,
    canonical_json,
    id_digest,
    parse_task,
)
from physgate.orchestrator.binaries import ClaudeBinary, measure
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import MAX_SESSION_FILE_BYTES
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import (
    RunConfig,
    load_run_config,
    require_endpoint,
)
from physgate.orchestrator.session_files import FileRefused, open_beneath, read_bounded
from physgate.oslayer.probe import Absent, Present

#: Where a round's finished visible trials lie, beneath the round's own directory.
WORK = "work"
#: The differences a development round is held to without refusing: the harness run's own
#: state. Every other one refuses any round.
DEVELOPMENT_DIFFERENCES = frozenset({"reportable", "harness"})
TRIALS = "trials.jsonl"
SCORE = "score.json"
#: Inside a trial's directory, beside the session's own place (``PLACE``): the harness's.
HARNESS = "harness"

#: A trial's tier: one of a version's three, or ``external`` for an external set's.
TierName = SourceTier


class BaselineError(PerRoleError):
    """The round cannot be run, or was stopped, for a reason it names: no task content."""


class RunSetEntry(_Frozen):
    """One harness trial: the run's directory and the trial's number."""

    run_dir: Annotated[str, StringConstraints(pattern=r"^/.+")]
    trial: Annotated[int, Field(ge=0)]


class RunSet(_Frozen):
    """The harness trials a round is held to, each named by its run, never by its task."""

    format: Literal[1]
    trials: tuple[RunSetEntry, ...] = Field(min_length=1)


@dataclass(frozen=True)
class Planned:
    """One harness trial, read and found, ready for its raw session."""

    index: int
    entry: RunSetEntry
    config: RunConfig
    task: Task
    tier: TierName
    cap: int


#: The raw arm: one session on the task, in a new directory, capped; its record.
Arm = Callable[..., dict[str, Any]]
#: The harness-side scorer: the task and the answer's path; the score.
Scorer = Callable[[Task, Path], Mapping[str, Any]]
#: The raw arm's setup for a harness run's record and the task's role.
SetupFor = Callable[[RunConfig, Role], RawSetup]


def setup_from_run(
    config: RunConfig,
    role: Role,
    *,
    binary: str,
    credential: Credential,
    install_bin: Path,
    os_layer: Present | Absent,
    role_python: RolePython | None,
    base_url: str | None,
) -> RawSetup:
    """The raw arm's setup, every pin taken from the harness run's own record.

    What the record names, the raw session is given: the binary's version, the role's model,
    effort, output-token limit, reasoning display, bounds, held-out roots and canaries,
    network, tool environment and tool servers. What this machine supplies (the binary, the
    credential, the installation, the OS layer and the interpreter as measured now) is
    compared with the record afterwards, never assumed equal. The endpoint is the operator's,
    ``base_url``, never the record's: the credential goes where the operator says, and the
    record's endpoint is only held against it (:func:`plan`).

    Raises:
        BaselineError: the run pinned no model for the role.
    """
    model = config.models.roles.get(role)
    if model is None:
        msg = "the harness run pinned no model for the role"
        raise BaselineError(msg, role=role)
    return RawSetup(
        binary=binary,
        claude_version=config.claude_version,
        model=model,
        effort=config.effort,
        max_output_tokens=config.max_output_tokens,
        thinking_display=config.thinking_display,
        bounds=config.bounds,
        credential=credential,
        base_url=base_url,
        install_bin=install_bin,
        role_python=role_python,
        held_out=tuple(config.held_out),
        held_out_canaries=tuple(config.held_out_canaries),
        network=config.network,
        os_layer=os_layer,
        # The tools the run's sessions computed and built with, and the servers it offered
        # from them: the raw session is given both as the run recorded them, held to them
        # before and after it runs (``RawSetup``), and offered only the baseline profile's.
        tool_environment=config.tool_environment,
        tool_servers=config.tool_servers,
        held_out_sha256=tuple(config.held_out_sha256),
    )


def _tasks(directory: Path) -> dict[str, tuple[TierName, Task]]:
    """Every task of the version at ``directory``, by its brief's digest.

    Raises:
        BaselineError: a task cannot be read, or two share a brief; counts and the tier only.
    """
    found: dict[str, tuple[TierName, Task]] = {}
    for tier in VERSION_TIERS:
        here = directory / tier
        for entry in sorted(p for p in here.iterdir() if p.is_dir() and not p.is_symlink()):
            try:
                task = parse_task((entry / "task.json").read_bytes())
            except (OSError, PerRoleError) as exc:
                # The error may name the task; only its tier is said.
                msg = f"a task of the {tier} tier cannot be read"
                raise BaselineError(msg, tier=tier) from exc
            brief = hashlib.sha256(task.brief.encode()).hexdigest()
            if brief in found:
                msg = "two tasks of the version share a brief, so a run's task cannot be told"
                raise BaselineError(msg, tier=tier)
            found[brief] = (tier, task)
    return found


def _external_tasks(
    store: Path, role: Role, directory: Path
) -> tuple[ExternalSetRecord, dict[str, tuple[TierName, Task]]]:
    """The external set at ``directory``: its record, and every task by its brief's digest.

    Raises:
        BaselineError: the set holds no task, holds one that is not an external task of the
            role, mixes benchmarks, or two of its tasks share a brief.
    """
    real = directory.resolve()
    entries = sorted(p for p in real.iterdir() if p.is_dir() and not p.is_symlink())
    found: dict[str, tuple[TierName, Task]] = {}
    benchmarks: set[str] = set()
    for entry in entries:
        try:
            task = parse_task((entry / "task.json").read_bytes())
        except (OSError, PerRoleError) as exc:
            msg = "a task of the external set cannot be read"
            raise BaselineError(msg, external=str(directory)) from exc
        if not isinstance(task.source, ExternalSource) or task.role != role:
            # Not named: a tier's task put here may be a protected one.
            msg = f"the external set holds a task that is not an external one of the {role} role"
            raise BaselineError(msg, external=str(directory), tier=task.tier)
        benchmarks.add(task.source.benchmark)
        brief = hashlib.sha256(task.brief.encode()).hexdigest()
        if brief in found:
            msg = "two tasks of the external set share a brief, so a run's task cannot be told"
            raise BaselineError(msg, external=str(directory))
        found[brief] = ("external", task)
    if not found:
        msg = "the external set holds no task"
        raise BaselineError(msg, external=str(directory))
    if len(benchmarks) != 1:
        msg = "an external set is one benchmark's tasks, and this one mixes several"
        raise BaselineError(msg, external=str(directory), benchmarks=",".join(sorted(benchmarks)))
    record = ExternalSetRecord(
        format=1,
        benchmark=benchmarks.pop(),
        role=role,
        tasks=len(found),
        sha256=tier_digest(real),
    )
    return record, found


def plan(
    store: Path,
    role: Role,
    version: str | None,
    runs: RunSet,
    *,
    base_url: str | None,
    development: bool = False,
    external: Path | None = None,
) -> tuple[TierSet | ExternalSetRecord, list[Planned]]:
    """Every harness trial of ``runs``, read and found, or the round refused before it starts.

    The round's source is the store's ``version``, or the external set at ``external``: one.

    Raises:
        BaselineError: the store, the source or an entry refuses the round; it names the
            entry by its place in the run set, never by its task.
    """
    if (version is None) == (external is None):
        msg = "a round names one source: a tier version or an external task set"
        raise BaselineError(msg)
    # Before the store's own scan, which would read a set put in the store as work left there.
    if external is not None and external.resolve().is_relative_to(store.resolve()):
        msg = "an external task set is kept apart from the store's tiers, and this one is in it"
        raise BaselineError(msg, external=str(external))
    refusal = leftover_refusal(store)
    if refusal is not None:
        raise BaselineError(refusal[1], refused_because=refusal[0])
    source: TierSet | ExternalSetRecord
    leaving: frozenset[str] = frozenset()
    if version is not None:
        directory = version_dir(store, role, version)
        source = read_version(directory)
        tasks = _tasks(directory)
        _require_unexposed(store, role, version)
        leaving = _left_out_ids(store, role, source, tasks)[1]
    else:
        assert external is not None  # one of the two, checked above
        source, tasks = _external_tasks(store, role, external)
    canaries = {task.canary for _, task in tasks.values() if task.canary is not None}
    canaries |= _listed(store)
    of_what = "this version" if version is not None else "this external set"
    planned: list[Planned] = []
    seen: set[tuple[str, int]] = set()
    binary_seen: ClaudeBinary | None = None
    for index, entry in enumerate(runs.trials):
        where = {"entry": str(index)}
        key = (os.path.realpath(entry.run_dir), entry.trial)
        if key in seen:
            msg = "a harness trial is listed twice in the run set"
            raise BaselineError(msg, **where)
        seen.add(key)
        run_dir = Path(entry.run_dir)
        config = load_run_config(run_dir / "run.json")
        try:
            require_endpoint(config, base_url)
        except RunConfigError as exc:
            msg = (
                "the harness run recorded another endpoint than the one given here; the "
                "record names a place to compare with, never one a credential is sent to"
            )
            raise BaselineError(msg, **where, **exc.context) from None
        _require_withheld(store, role, config, canaries, where)
        found = tasks.get(config.brief_sha256)
        if found is None:
            msg = f"the harness run was given no task of {of_what}"
            raise BaselineError(msg, **where)
        tier, task = found
        if tier == "held_out" and task.id in leaving:
            # A task the version's check flagged is left out of every held-out count: no raw
            # trial is run on it, and the round's record says how many and which were left out.
            continue
        if config.ablation:
            # Never reportable, which a development round forgives; its own kind it does not:
            # an ablation run's numbers are of a harness with a part taken away.
            msg = "the harness run is an ablation run; no baseline is held to one"
            raise BaselineError(msg, **where)
        if not development and not (config.reportable and config.harness.clean):
            msg = (
                "the harness run is not reportable or not from a clean checkout; no baseline "
                "is held to it but a development round"
            )
            raise BaselineError(msg, **where)
        try:
            cap = harness_total(run_dir)
        except ComparisonError as exc:
            msg = f"the harness run's token account gives no cap: {exc}"
            raise BaselineError(msg, **where) from None
        # The binary is held as the build it is, its bytes and platform, never as a version
        # string: a run that recorded no build cannot be held to the raw session's.
        if config.binary is None:
            msg = "the harness run recorded no build of the session binary to hold a baseline to"
            raise BaselineError(msg, **where, refused_because="binary")
        if binary_seen is not None and binary_seen != config.binary:
            msg = "the harness runs executed different builds of the session binary"
            raise BaselineError(msg, **where, refused_because="binary")
        binary_seen = config.binary
        planned.append(Planned(index, entry, config, task, tier, cap))
    return source, planned


def _check_of(store: Path, role: Role, manifest: TierSet) -> CheckRecord:
    """The version's check record, or the round refused.

    Raises:
        BaselineError: the version has no record (``held_out_unchecked``: no round is held to a
            version whose held-out tier nobody checked), or its record refuses as read.
    """
    from physgate.evaluation.tiers.measure import checked

    try:
        return checked(store, role, manifest)
    except PerRoleError as exc:
        reason = exc.context.get("refused_because", "check_record_unreadable")
        raise BaselineError(str(exc), refused_because=reason) from None


def _left_out_ids(
    store: Path, role: Role, manifest: TierSet, tasks: Mapping[str, tuple[TierName, Task]]
) -> tuple[LeftOut, frozenset[str]]:
    """What the version's check leaves out of its held-out tier, and those tasks' ids.

    Raises:
        BaselineError: the version has no check record, its record refuses as read
            (:func:`_check_of`), or a digest it flags is not exactly one held-out task's;
            nothing is named.
    """
    record = _check_of(store, role, manifest)
    held = [task.id for tier, task in tasks.values() if tier == "held_out"]
    by_digest = Counter(id_digest(task) for task in held)
    if any(by_digest[digest] != 1 for digest in record.flagged):
        msg = "the check record flags a task that is not exactly one held-out task of the version"
        raise BaselineError(msg, refused_because="check_record_not_the_tier")
    flagged = set(record.flagged)
    return left_out(record), frozenset(t for t in held if id_digest(t) in flagged)


def _require_unexposed(store: Path, role: Role, version: str) -> None:
    """Refuse a round on a version the register, read now, marks exposed.

    Its harness runs were checked as each started; one may have been seen since (another run's
    held-out read), and a round held to it would count it.

    Raises:
        BaselineError: the version is exposed, or the register cannot be read whole.
    """
    from physgate.evaluation.tiers.exposure import exposed_versions

    try:
        exposed = exposed_versions(store, role)
    except PerRoleError as exc:
        reason = exc.context.get("refused_because", "register_unreadable")
        msg = "the register cannot be read whole, so whether the version was seen cannot be told"
        raise BaselineError(msg, refused_because=reason) from None
    if version in exposed:
        msg = (
            f"the version {version[:8]} has been seen since its harness runs started; no round "
            "is held to it until a new version is generated"
        )
        raise BaselineError(msg, refused_because="version_exposed")


def _listed(store: Path) -> set[str]:
    """Every canary the lists under every role's root in ``store`` name, its own role's or not.

    A round looks for them all, as an authoring session does
    (:func:`.tiers.canaries.store_canaries`): another role's protected tier lies in the same
    store, and a canary of it in the raw session's stream is an exposure all the same.

    Raises:
        BaselineError: a list cannot be taken whole, or a tier holds no list; it is never
            read as naming none.
    """
    try:
        return set(store_canaries(store))
    except AuthoringError as exc:
        msg = f"the store's canaries cannot all be read, so no run can be held to them: {exc}"
        raise BaselineError(msg, **exc.context) from None
    except OSError as exc:
        # Its kind and words alone: the path it names may be a protected task's directory.
        msg = "the store's canaries cannot all be read, so no run can be held to them: "
        msg += str(exc.strerror)
        raise BaselineError(msg, refused_because="canary_list_unreadable") from None


def _require_withheld(
    store: Path, role: Role, config: RunConfig, canaries: set[str], where: dict[str, str]
) -> None:
    """Refuse a harness run that does not withhold the store as every run on it must.

    The raw session withholds exactly what the harness run withheld and looks for exactly its
    canaries, since the two are held equal; so a run that left a protected place of the store
    open, or did not look for a protected task's canary, would leave it open to the raw
    session too. Every run on the store withholds, for its own role and every other role whose
    root is in the store, the withheld root and work root and the validation and held-out
    tiers of every version, each spelt as on disk, and looks for every canary of the version's
    protected tasks and of every role's root (:func:`_listed`): what it withholds is the scope
    it looks in. A role with no root in the store has nothing to withhold or to look for.

    Raises:
        BaselineError: a place or a canary is missing; places by path, canaries by count.
    """
    others = [r for r in get_args(Role) if r != role and os.path.lexists(role_root(store, r))]
    also = [(store, role), *((store, other) for other in others)]
    for refusal in (
        spelling_refusal(config.held_out, also=also),
        withheld_refusal(config.held_out, also=also),
        work_refusal(config.held_out),
        protected_tier_refusal(config.held_out, also=also),
    ):
        if refusal is not None:
            msg = (
                f"the harness run does not withhold the store as every run on it must: {refusal[1]}"
            )
            raise BaselineError(msg, refused_because=refusal[0], **where)
    missing = canaries - set(config.held_out_canaries)
    if missing:
        msg = (
            "the harness run did not look for every canary of the version's protected tasks "
            "and of every role's root in the store"
        )
        raise BaselineError(msg, missing=str(len(missing)), **where)


@dataclass
class _Tally:
    trials: int = 0
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    unscored: int = 0
    excluded: int = 0
    cap: int = 0
    spent: int = 0
    spent_not_in_binary_totals: int = 0

    def counts(self, **coverage: Any) -> TierCounts:  # noqa: ANN401
        return TierCounts(**vars(self), **coverage)


def _working(root: Path, name: str, work: Path) -> Path:
    """Record inside the role's root ``root`` that a session's work lies at ``work``.

    The record's form is the authoring session's, so the same reading of it refuses every
    later run, author and check on the store until a person has looked at the work it names.
    """
    make_role_root(root)
    record = root / f"{name}{WORKING}"
    fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps({"work": str(work)}) + "\n").encode())
    finally:
        os.close(fd)
    return record


@contextlib.contextmanager
def trial_place(store: Path, role: Role, round_id: str, name: str) -> Iterator[tuple[Path, Path]]:
    """A new trial's directory in the role's work root and its record of work, held while it lives.

    The work root is held (:func:`.tiers.store.holding_work_root`) from the trial's creation
    until the body ends, which the runner leaves only once the trial's session has ended and the
    trial has been moved out: while a trial's or a blind check's place there is held, another
    trial's creation is refused before anything is made. A second measure beside the rule that
    withholds the work root whole from the session but for its own place.

    A session whose runner was killed outright holds nothing, but its process facts lie beside
    its place: while it still runs, the creation is refused just the same.

    Raises:
        BaselineError: ``session_lives``: another place in the work root is held, or a session
            left there still runs; ``work_root_unlockable``: the volume refuses the lock call.
            Nothing is made.
    """
    root = role_root(store, role)
    try:
        with holding_work_root(store, role):
            trial_dir = work_root(store, role) / f"{BASELINE_DIR}-{round_id}-{name}"
            working = _working(root, f"{BASELINE_DIR}-{name}", trial_dir)
            trial_dir.mkdir(mode=0o700, parents=True)
            yield trial_dir, working
    except WorkRootHeld as exc:
        msg = (
            "another session's place in the role's work root is held (a trial's or a blind "
            "check's): no trial is made beside it while that session lives"
        )
        if str(exc):
            msg += f" ({exc})"
        raise BaselineError(msg, refused_because="session_lives") from None
    except WorkRootUnlockable as exc:
        msg = (
            "the role's work root cannot be held on its volume (the lock call failed: "
            f"{exc}): no trial is made where a second one could be made beside it"
        )
        raise BaselineError(msg, refused_because="work_root_unlockable") from None


def _secure(work: Path, place: Path) -> None:
    """Move a protected trial's whole directory from the work root beneath the withheld root.

    Both lie in the role's root, so the move is a rename: the directory is in one or the other.
    """
    place.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if place.exists():
        msg = "a trial's place beneath the withheld root is taken"
        raise BaselineError(msg)
    shutil.move(str(work), str(place))


def _append(path: Path, line: TrialRecord | ExcludedTrial) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("ab") as out:
        out.write(canonical_json(line.model_dump(mode="json")))
        out.flush()
        os.fsync(out.fileno())


def run_baseline(
    *,
    store: Path,
    role: Role,
    runs: RunSet,
    out: Path,
    setup_for: SetupFor,
    score: Scorer,
    prices: DatedSheet,
    arm: Arm = run_raw,
    sleep: Callable[[float], None] = time.sleep,
    development: bool = False,
    base_url: str | None = None,
    version: str | None = None,
    external: Path | None = None,
) -> BaselineRecord:
    """Run the raw arm on every trial of ``runs``, and write the round's records under ``out``.

    ``out`` is new: a round gets a directory of its own, and its records are never replaced.
    ``base_url`` is the operator's endpoint, ``None`` for the binary's default; every harness
    run must have recorded it, and ``setup_for`` must send the credential there. The round's
    source is the store's ``version`` or the external set at ``external``, exactly one.

    Raises:
        BaselineError: the round was refused before it started, or stopped by a pair that
            differs in more than the harness, or by trials that ran under different pins.
    """
    if out.exists():
        msg = "the round's directory exists; each round gets a directory of its own"
        raise BaselineError(msg, out=str(out))
    # Withheld from every session of the round, by its name: its finished trials and its records
    # lie there. So it is named as the filesystem spells it, as the store's roots are: on a
    # volume that ignores case another case names the same directory, and a session naming it
    # as it is on disk would not be matched by the name withheld.
    withheld_out = os.path.realpath(out)
    try:
        spelt = spelt_as_on_disk(Path(withheld_out))
    except OSError as exc:
        msg = "the round's directory's spelling cannot be judged: a directory on the way is unread"
        raise BaselineError(
            msg, refused_because="out_not_spelt_as_on_disk", error=str(exc.strerror)
        ) from None
    if not spelt:
        msg = (
            "the round's directory is not spelt as the filesystem spells it; name it as it is on "
            "disk, so every session is withheld the spelling that is there"
        )
        raise BaselineError(msg, out=str(out), refused_because="out_not_spelt_as_on_disk")
    # Before anything else of the store is read: a session an earlier runner left running in the
    # work root (that runner killed outright, its hold gone with it) refuses the round in words.
    living = running_session(store, role)
    if living is not None:
        msg = f"{living}: no round starts while a session left in the work root still runs"
        raise BaselineError(msg, refused_because="session_lives")
    source, planned = plan(
        store, role, version, runs, base_url=base_url, development=development, external=external
    )
    out.mkdir(mode=0o700, parents=True)
    round_id = secrets.token_hex(8)
    protected_root = withheld_root(store, role) / BASELINE_DIR / round_id
    counted = EXTERNAL_TIERS if isinstance(source, ExternalSetRecord) else VERSION_TIERS
    tallies = {tier: _Tally() for tier in counted}
    pins: dict[str, Any] | None = None
    for trial in planned:
        protected = trial.tier in PROTECTED_TIERS
        try:
            record, line = _one_trial(
                trial,
                out=out,
                withheld_out=withheld_out,
                round_id=round_id,
                store=store,
                role=role,
                protected_root=protected_root if protected else None,
                setup_for=setup_for,
                score=score,
                prices=prices,
                arm=arm,
                sleep=sleep,
                development=development,
            )
        except BaselineError:
            raise  # the runner's own: it names the entry and fields, never the task
        except Exception as exc:
            if not protected:
                raise
            # A scorer's or an arm's error may name the task, a spec or a value of it; of a
            # protected trial only the tier and the error's kind are said, and nothing chained.
            msg = f"a {trial.tier} trial stopped on an error ({type(exc).__name__}), not repeated"
            raise BaselineError(msg, tier=trial.tier, entry=str(trial.index)) from None
        these = pin_set(record["pins"])
        if pins is None:
            pins = these
        elif these != pins:
            msg = "the round's trials ran under different pins; no one baseline holds them"
            raise BaselineError(msg, entry=str(trial.index))
        _append((protected_root if protected else out) / TRIALS, line)
        tally = tallies[trial.tier]
        tally.trials += 1
        tally.cap += trial.cap
        tally.spent += int(record.get("tokens", 0))
        # Cut tokens the session's count leaves out: the spend is a lower bound by them.
        tally.spent_not_in_binary_totals += int(record.get("tokens_not_in_binary_totals") or 0)
        if isinstance(line, ExcludedTrial):
            tally.excluded += 1
        elif line.outcome == "pass":
            tally.passed += 1
        elif line.outcome == "fail":
            tally.failed += 1
        elif line.outcome == "flaky":
            tally.flaky += 1
        else:
            tally.unscored += 1
    assert pins is not None  # the run set holds at least one trial
    external_set = source if isinstance(source, ExternalSetRecord) else None
    # The record the plan held each flagged digest to one held-out task with.
    check = None if isinstance(source, ExternalSetRecord) else _check_of(store, role, source)
    tiers = (
        None
        if isinstance(source, ExternalSetRecord) or check is None
        else tiers_record(source, said(left_out(check)))
    )
    flagged = 0 if check is None else len(check.flagged)
    baseline = BaselineRecord(
        format=1,
        id=round_id,
        created=datetime.now(UTC).strftime("%Y-%m-%d"),
        tiers=tiers,
        external=external_set,
        pins=pins,
        pin_set_sha256=pin_set_sha256(pins),
        development=development,
        harness_runs=len({p.entry.run_dir for p in planned}),
        counts={
            tier: tallies[tier].counts(**_coverage(source, planned, tier, flagged))
            for tier in counted
        },
    )
    if external_set is not None:
        write_new(out / EXTERNAL_RECORD, record_bytes(external_set))
    if tiers is not None:
        write_new(out / TIERS_RECORD, record_bytes(tiers))
    write_new(out / BASELINE_RECORD, record_bytes(baseline))
    return baseline


def _coverage(
    source: TierSet | ExternalSetRecord, planned: list[Planned], tier: SourceTier, flagged: int
) -> dict[str, Any]:
    """How many of ``tier``'s tasks the round ran, of how many, and whether that is all of them.

    Of a version's held-out tier, the ``flagged`` tasks its check flagged are in neither count:
    the plan ran none of them, and no figure counts them.
    """
    if isinstance(source, ExternalSetRecord):
        of = source.tasks
    else:
        of = getattr(source, tier).count - (flagged if tier == "held_out" else 0)
    covered = len({trial.task.id for trial in planned if trial.tier == tier})
    return {"covered": covered, "of": of, "whole": covered == of}


def _one_trial(
    trial: Planned,
    *,
    out: Path,
    withheld_out: str,
    round_id: str,
    store: Path,
    role: Role,
    protected_root: Path | None,
    setup_for: SetupFor,
    score: Scorer,
    prices: DatedSheet,
    arm: Arm,
    sleep: Callable[[float], None],
    development: bool,
) -> tuple[dict[str, Any], TrialRecord | ExcludedTrial]:
    """One harness trial's raw trial, run once more if the machine ended it; its last attempt."""
    task, run_dir = trial.task, Path(trial.entry.run_dir)
    delays = trial.config.bounds.infra_retry_delays_s
    # Before any record of work: a setup refused here (no credential, another binary) leaves
    # nothing behind for the next round to refuse.
    setup = setup_for(trial.config, role)
    try:
        built = measure(setup.binary)
    except InvocationError as exc:
        raise BaselineError(str(exc), entry=str(trial.index), refused_because="binary") from None
    if built != trial.config.binary:
        msg = "the binary here is not the build the harness run executed"
        raise BaselineError(msg, entry=str(trial.index), refused_because="binary")
    for attempt in (1, 2):
        name = f"{trial.index:04d}-{attempt}"
        if attempt == 2:
            # Only a first attempt the machine ended is run again, once its trial is out.
            sleep(delays[0] if delays else 0.0)
        # Made in the work root, which every run on the store withholds, whatever the trial's
        # tier: its session is given its own place out of the run's held-out roots and nothing
        # else there, and the round's own directory is withheld from it besides. Two
        # directories, never one: the session's place, where it may leave anything, and the
        # harness's, beside it, where the copied answer, the record and the score are written.
        # The work root is held until the trial is out (:func:`trial_place`).
        with trial_place(store, role, round_id, name) as (trial_dir, working):
            given = replace(
                setup, held_out_carved=str(trial_dir / PLACE), held_out_also=(withheld_out,)
            )
            work, harness = trial_dir / PLACE, trial_dir / HARNESS
            harness.mkdir(mode=0o700)
            record = arm(task, given, work, cap=trial.cap, harness=harness)
            stream = work / "session" / "stdout.jsonl"
            answer = harness / "answer" / task.answer.path
            scored: Mapping[str, Any] | None = None
            if record.get("answer") == "found":
                scored = score(task, answer)
                write_new(harness / SCORE, canonical_json(dict(scored)))
            machine = False
            if scored is None:
                try:
                    machine = raw_ended_by_infrastructure(record, stream, task)
                except TrialExcludedError:
                    machine = False  # assembled as excluded below, with its reason
            if machine and attempt == 1:
                _finish(trial_dir, working, protected_root, out, name)
                continue
            found = differences(run_dir, work, role=role, task=task, record_dir=harness)
            allowed = DEVELOPMENT_DIFFERENCES if development else frozenset()
            named = sorted({f.split(":", 1)[0] for f in found} - allowed)
            if named:
                _finish(trial_dir, working, protected_root, out, name)
                msg = "the raw arm differs from the harness run in more than the harness: "
                raise BaselineError(msg + ", ".join(named), entry=str(trial.index))
            line = raw_trial(
                suite=f"{role}_{trial.tier}",
                task=task,
                trial=trial.entry.trial,
                record=record,
                stream=stream,
                prices=prices,
                score=scored,
                unscored=machine,
            )
            _finish(trial_dir, working, protected_root, out, name)
            return record, line
    msg = "a trial ran past its one re-run"  # unreachable: the second attempt always returns
    raise BaselineError(msg, entry=str(trial.index))


def _finish(
    trial_dir: Path, working: Path, protected_root: Path | None, out: Path, name: str
) -> None:
    """Move a finished trial out of the work root, then clear its record of work.

    A protected trial beneath the withheld root; a visible one beneath the round's directory.

    Raises:
        BaselineError: the move failed; the trial is where it ran, with its record.
    """
    if protected_root is not None:
        _secure(trial_dir, protected_root / name)
    else:
        _move_out(trial_dir, out / WORK, name)
    working.unlink()


def _move_out(trial_dir: Path, work: Path, name: str) -> None:
    """Move a visible trial's whole directory to ``work/name``, made new, nothing followed.

    The destination is made first, so one already there refuses the move; the directory is then
    renamed over that empty one, which only an empty directory lets happen. Across filesystems
    it is copied (:func:`_copy_tree`, at most :data:`MAX_COPY_DEPTH` deep) and removed only once
    the copy is whole. Whatever stops a move, what it made is removed and the trial is left where
    it ran; an interrupt or an exit is then raised on as it came.

    Raises:
        BaselineError: the move failed or was refused; it names no path.
    """
    try:
        os.mkdir(work, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        msg = "the round's directory for its finished trials cannot be made"
        raise BaselineError(msg, refused_because="move", error=str(exc.strerror)) from None
    if not stat.S_ISDIR(os.lstat(work).st_mode):
        msg = "the round's directory for its finished trials is not a directory"
        raise BaselineError(msg, refused_because="move")
    destination = work / name
    try:
        os.mkdir(destination, 0o700)
    except OSError as exc:
        msg = "a visible trial's place beneath the round's directory is taken or cannot be made"
        raise BaselineError(msg, refused_because="move", error=str(exc.strerror)) from None
    # What lands at ``work/<name>/place`` is session-made content, links included (they are made
    # again as links, never followed, as a rename on one filesystem carries them): the harness
    # never reads it by path and never gives it to git. Whoever reads it later reads files a
    # session could have shaped.
    try:
        try:
            os.rename(trial_dir, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _copy_tree(trial_dir, destination)
        else:
            return
    except BaseException as exc:
        # Any failure of the move, not only the filesystem's or a refused file's (a recursion or
        # memory limit, an interrupt): what it made beneath the round's directory is removed and
        # the trial stays in the work root with its record.
        shutil.rmtree(destination, ignore_errors=True)
        if not isinstance(exc, Exception):
            raise  # an interrupt or an exit stops the round as it would at any other step
        msg = "a visible trial could not be moved beneath the round's directory; it is left "
        msg += "in the store's work root with its record"
        raise BaselineError(msg, refused_because="move", error=_why_not_moved(exc)) from None
    try:
        shutil.rmtree(trial_dir)
    except OSError as exc:
        msg = "a visible trial was copied beneath the round's directory, but its directory in "
        msg += "the store's work root could not be removed; it is left there with its record"
        raise BaselineError(msg, refused_because="move", error=str(exc.strerror)) from None


def _why_not_moved(exc: Exception) -> str:
    """What a failed move's refusal says of its cause: a kind or the filesystem's words, no path."""
    if isinstance(exc, FileRefused):
        return exc.kind
    if isinstance(exc, _TooDeep):
        return "too_deep"
    if isinstance(exc, OSError):
        return str(exc.strerror)
    return type(exc).__name__  # its message may carry a path; its kind is enough


#: Opening a directory to walk it: never through a link.
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

#: How many directories deep beneath a trial's directory the copy across filesystems goes;
#: a deeper one refuses the move. What the harness itself leaves there (the place's worktree,
#: the role's python environment, the session's records) lies well under 32 levels; 64 keeps a
#: margin over that for what a session makes, while the walk holds at most two descriptors per
#: level (128 at most, half of the smallest usual per-process limit, 256) and a session's
#: ``mkdir x; cd x`` loop cannot make it exhaust descriptors, memory or a recursion limit. A
#: rename on one filesystem moves the tree whole, at any depth, and needs no bound.
MAX_COPY_DEPTH = 64


class _TooDeep(Exception):  # noqa: N818 - a refusal, as FileRefused is
    """A directory beneath a trial lies deeper than :data:`MAX_COPY_DEPTH`."""


@dataclass
class _Level:
    """One directory on the copy's way down: its names beneath the source, both descriptors."""

    names: tuple[str, ...]
    source_fd: int
    destination_fd: int
    #: Its entries not yet copied, the next one last.
    left: list[tuple[str, int]]


def _entries(directory_fd: int) -> list[tuple[str, int]]:
    """A directory's entries and their modes, never following a link; the first name last."""
    with os.scandir(directory_fd) as entries:
        return sorted(
            ((e.name, e.stat(follow_symlinks=False).st_mode) for e in entries), reverse=True
        )


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy everything beneath ``source`` into the empty directory ``destination``.

    Walked without recursion, one directory at a time, at most :data:`MAX_COPY_DEPTH` deep;
    each directory opened from its parent's descriptor without following a link, and held open
    only while the walk is beneath it. Each regular file is read as a session's files are read
    (:func:`.session_files.open_beneath`, under the session file bound) and written as a new
    file; a link is made again as the link it is, never followed; anything else is refused.

    Raises:
        FileRefused: an entry is neither a directory, a regular file with one name nor a link,
            or a file is larger than the bound.
        _TooDeep: a directory lies deeper than the bound.
        OSError: the filesystem refused a step.
    """
    opened: list[int] = []  # every descriptor the walk holds, in the order opened
    try:
        opened.append(os.open(source, _DIRECTORY))
        opened.append(os.open(destination, _DIRECTORY))
        way = [_Level((), opened[0], opened[1], _entries(opened[0]))]
        while way:
            level = way[-1]
            if not level.left:
                way.pop()
                os.close(opened.pop())  # its destination's descriptor, then its source's
                os.close(opened.pop())
                continue
            name, mode = level.left.pop()
            names = (*level.names, name)
            if stat.S_ISDIR(mode):
                if len(names) > MAX_COPY_DEPTH:
                    raise _TooDeep
                os.mkdir(name, 0o700, dir_fd=level.destination_fd)
                opened.append(os.open(name, _DIRECTORY, dir_fd=level.source_fd))
                opened.append(os.open(name, _DIRECTORY, dir_fd=level.destination_fd))
                way.append(_Level(names, opened[-2], opened[-1], _entries(opened[-2])))
            else:
                _copy_entry(source, names, mode, level.source_fd, level.destination_fd)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _copy_entry(
    anchor: Path, names: tuple[str, ...], mode: int, source_fd: int, destination_fd: int
) -> None:
    """Copy the one entry ``names`` beneath ``anchor`` that is not a directory, or refuse it."""
    name = names[-1]
    if stat.S_ISLNK(mode):
        os.symlink(os.readlink(name, dir_fd=source_fd), name, dir_fd=destination_fd)
    elif stat.S_ISREG(mode):
        fd = open_beneath(anchor, names)
        try:
            data = read_bounded(fd, MAX_SESSION_FILE_BYTES)
            kept = os.fstat(fd).st_mode & 0o700
        finally:
            os.close(fd)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        out = os.open(name, flags, kept | 0o600, dir_fd=destination_fd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(out, view) :]
        finally:
            os.close(out)
    else:
        raise FileRefused("not_a_file", "neither a directory, a regular file nor a link")
