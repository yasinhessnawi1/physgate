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
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, get_args

from pydantic import Field, StringConstraints

from physgate.evaluation.baseline.caps import CellTrial, NoCapError, RawCap, raw_cap
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
from physgate.evaluation.per_role.arms.raw import (
    RawArmError,
    RawSetup,
    clean_left_session,
    held_out_seen,
    hold_tools,
    run_raw,
)
from physgate.evaluation.per_role.assemble import (
    OWN_ENDS,
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
from physgate.evaluation.tiers.manifest import TierSet, practice_refusal, read_version
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
    living_session,
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
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.credentials import Credential, fingerprint
from physgate.orchestrator.dispatch import MAX_SESSION_FILE_BYTES, read_captured, read_stream_file
from physgate.orchestrator.exceptions import InvocationError, RunConfigError, RunStateError
from physgate.orchestrator.managed import answering_models
from physgate.orchestrator.review_root_record import recorded_review_root
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import (
    HarnessState,
    RunConfig,
    load_run_config,
    require_endpoint,
)
from physgate.orchestrator.session_files import (
    FileRefused,
    open_beneath,
    read_beneath,
    read_bounded,
)
from physgate.orchestrator.usage_limit import (
    UsageLimit,
    held_at,
    resume_after,
    resume_refusal,
    session_end,
)
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT as EXIT_WAITING_FOR_LIMIT
from physgate.oslayer.probe import Absent, Present
from physgate.reviewers.places import standing_review_material

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


#: The round's own account of where it stands, in its directory: one line per step, each
#: appended and synced before the step it names goes on. It names entries by their place in
#: the run set and sessions by their number, never a task, and holds no outcome.
LEDGER = "ledger.jsonl"
LEDGER_FORMAT = 1
#: How the round left off, in its directory, written whole at each stop: its status and wait.
ROUND_RECORD = "round.json"
#: The exit status while the round waits for a person (a refused credential to replace): the
#: harness round driver's value and name, so one launch script reads both arms alike.
EXIT_WAITING_FOR_A_PERSON = 77
#: The causes a raw session's end is waited on for, as the harness arm names them.
USAGE_LIMIT = "usage_limit"
CREDENTIAL_REFUSED = "credential_refused"
#: How a round left off: every trial recorded, waiting for the account's usage limit to reset,
#: or waiting for a person. The harness round driver's words.
Status = Literal["done", "waiting_for_limit", "waiting_for_a_person"]
#: How the machine ended a raw session, as the round reads it: the account's usage limit, a
#: refused credential, or any other end of the machine's before an answer existed.
MachineEnd = Literal["usage_limit", "credential_refused", "machine"]
#: What the round does after a session (:func:`next_step`).
Step = Literal["wait_for_limit", "wait_for_a_person", "once_more", "record"]


class BaselineError(PerRoleError):
    """The round cannot be run, or was stopped, for a reason it names: no task content."""


class RoundWaits(Exception):  # noqa: N818 - a state the round stops in, not a fault
    """The round stopped to wait: for the account's usage limit to reset, or for a person.

    Nothing is spent by it. ``waiting`` names the entry by its place in the run set and why,
    and for the limit the instant after which a start goes on (``resume_after``) and whether a
    person's word would let it go on sooner (``word_helps``).
    """

    def __init__(self, status: Status, round_id: str, waiting: dict[str, Any]) -> None:
        """A wait of the round ``round_id``, of ``status``, at ``waiting``."""
        super().__init__(f"the round waits: {status}")
        self.status = status
        self.round_id = round_id
        self.waiting = waiting

    @property
    def exit_code(self) -> int:
        """The status the command exits with: the harness round driver's for the same wait."""
        if self.status == "waiting_for_limit":
            return EXIT_WAITING_FOR_LIMIT
        return EXIT_WAITING_FOR_A_PERSON

    def printed(self) -> dict[str, Any]:
        """The line the command prints, and the round's record says: the status and the wait."""
        return {"format": 1, "round": self.round_id, "status": self.status, "waiting": self.waiting}


def machine_end(
    record: Mapping[str, Any], stream: Path, task: Task
) -> tuple[MachineEnd | None, UsageLimit | None]:
    """How the machine ended a raw session, read from its own record and stream; ``None`` if not.

    A session whose records exclude it is no machine end: it is assembled as excluded, whatever
    else its stream says, so a canary in a stream the limit ended still excludes the trial. Of
    the rest, a session the arm itself stopped (its cap, its wall clock) is the arm's own end.
    Every other session is read as the harness arm reads a role session's end
    (:func:`.orchestrator.usage_limit.session_end`, on the stream's bytes): an end the stream
    names as the account's usage limit is the limit, with the limit as the stream gave it, and
    one whose request was refused for its credential is that; each whether or not the session
    wrote an answer first, since neither is a trial's end. Any other end of the machine's before
    an answer existed (:func:`.per_role.assemble.raw_ended_by_infrastructure`) is ``machine``.

    Raises:
        ReportError: the record is not of ``task``.
    """
    try:
        machine = raw_ended_by_infrastructure(record, stream, task)
    except TrialExcludedError:
        return None, None
    if record.get("end") in OWN_ENDS:
        return None, None
    end, limit = session_end(
        read_stream_file(stream),
        read_captured(stream).result,
        exit_code=record.get("exit_code"),
        stopped_at_wall_clock=False,
    )
    if end.cause == USAGE_LIMIT and limit is not None:
        return "usage_limit", limit
    if end.cause == CREDENTIAL_REFUSED:
        return "credential_refused", None
    return ("machine" if machine else None), None


def next_step(end: MachineEnd | None, once_more_spent: bool) -> Step:
    """What the round does after a session that ended so: the one place its rule is held.

    The account's usage limit and a refused credential are never a trial's end and never spend
    its one more go, however often they come: the round waits, for the reset or for a person,
    and then runs the session again as if it had not run. Any other end of the machine's before
    an answer existed is run once more, once; after that it is recorded, as ``unscored``. Every
    other end is recorded as it is.
    """
    if end == "usage_limit":
        return "wait_for_limit"
    if end == "credential_refused":
        return "wait_for_a_person"
    if end == "machine" and not once_more_spent:
        return "once_more"
    return "record"


def stopped_entry_refusal(index: int, because: str) -> NoReturn:
    """Refuse to go on past an entry the round stopped on for a cause, after its session started.

    The round's ledger names the stop (a ``stopped`` line): a pair that differs, other pins, an
    error, or a move that failed. A stop is never a kill: a killed round is resumed and its
    entry run again, spending nothing, but an entry stopped for a cause is never given to the
    raw arm again in this round. It may be run once more only as a new round of its one entry,
    once the cause is removed (``--rerun-of`` names this round there), and its first session's
    records are never read.

    Raises:
        BaselineError: always (``entry_stopped``).
    """
    msg = (
        f"the round stopped on this entry after its session started ({because}); a stopped entry "
        "is never run again in its round, only once more as a new round of its one entry"
    )
    raise BaselineError(
        msg,
        entry=str(index),
        refused_because="entry_stopped",
        because=because,
        session_started="true",
    )


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
    #: Where the harness run's reviews ran, as it recorded it: inside its own run directory
    #: (:func:`_require_reviewed_inside`), withheld from the raw session whole.
    review_root: Path
    #: The step of the cap rule that gave ``cap``, and its inputs (:mod:`.caps`).
    cap_rule: RawCap

    @property
    def no_figure(self) -> bool:
        """Whether its harness trial gave no figure: its raw trial runs at the end of the cell."""
        return self.cap_rule.rule != "pair"


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
    harness: HarnessState | None,
) -> RawSetup:
    """The raw arm's setup, every pin taken from the harness run's own record.

    What the record names, the raw session is given: the binary's version, the role's model,
    effort, output-token limit, reasoning display, bounds, held-out roots and canaries,
    network, tool environment and tool servers. What this machine supplies (the binary, the
    credential, the installation, the OS layer and the interpreter as measured now) is
    compared with the record afterwards, never assumed equal; ``harness`` is the checkout the
    round runs from, recorded with every session and held to the harness run's. The endpoint is
    the operator's, ``base_url``, never the record's: the credential goes where the operator
    says, and the record's endpoint is only held against it (:func:`plan`).

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
        # The run roots the harness run withheld whole, where the round's harness runs lie.
        withheld_whole=tuple(config.withheld_whole),
        # The standing review root, where a run made by hand reviews by convention: refused to
        # the raw session whole, every packet, reviewer's record and the key for labels there,
        # where the harness run names a held-out tier. The harness run's own review root is
        # added for each trial (:func:`_one_trial`).
        withheld_reads=standing_review_material(config.held_out),
        harness=harness,
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
    cell: RunSet | None = None,
    shakedown: bool = False,
    own_places: frozenset[Path] = frozenset(),
) -> tuple[TierSet | ExternalSetRecord, list[Planned]]:
    """Every harness trial of ``runs``, read and found, or the round refused before it starts.

    The round's source is the store's ``version``, or the external set at ``external``: one.
    Each entry's cap is taken by the rule of :mod:`.caps` from ``cell``, the run set of every
    harness trial of the cell (the round's own run set where none is given): its harness run's
    total, or for one that gives no figure the largest of its task's other trials, else the
    cell's median. Whether ``cell`` holds every trial of the cell is the caller's to say; the
    rule's inputs are recorded with each trial. A practice version is refused unless the round is
    told it is a shakedown (``shakedown``). ``own_places``: what a round being resumed left in
    the store's work root and role root itself, which it settles, so they do not refuse it.

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
    refusal = leftover_refusal(store, ignoring=own_places)
    if refusal is not None:
        raise BaselineError(refusal[1], refused_because=refusal[0])
    source: TierSet | ExternalSetRecord
    leaving: frozenset[str] = frozenset()
    if version is not None:
        directory = version_dir(store, role, version)
        source = read_version(directory)
        practice = practice_refusal(source, shakedown=shakedown)
        if practice is not None:
            raise BaselineError(practice[1], refused_because=practice[0])
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
    found_trials: list[tuple[int, RunSetEntry, RunConfig, Task, TierName, Path]] = []
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
        reviewed = _require_reviewed_inside(run_dir, where)
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
        # The binary is held as the build it is, its bytes and platform, never as a version
        # string: a run that recorded no build cannot be held to the raw session's.
        if config.binary is None:
            msg = "the harness run recorded no build of the session binary to hold a baseline to"
            raise BaselineError(msg, **where, refused_because="binary")
        if binary_seen is not None and binary_seen != config.binary:
            msg = "the harness runs executed different builds of the session binary"
            raise BaselineError(msg, **where, refused_because="binary")
        binary_seen = config.binary
        found_trials.append((index, entry, config, task, tier, reviewed))
    trials = _cell_trials(runs, cell, tasks, leaving)
    for index, entry, config, task, tier, reviewed in found_trials:
        own = trials.own(entry, tier, index)
        try:
            rule = raw_cap(own, trials.of(tier))
        except NoCapError as exc:
            raise BaselineError(str(exc), entry=str(index), **exc.context) from None
        planned.append(Planned(index, entry, config, task, tier, rule.cap, reviewed, rule))
    return source, planned


def harness_figure(run_dir: Path) -> int | None:
    """The harness run's token total, or ``None`` where it gives no figure: the one reading.

    A run gives no figure where its token account cannot show every token it spent
    (:func:`.arms.compare.harness_total` refuses it): it was ended for good by the machine, it
    stopped where nothing continues it, or a session a killed orchestrator left was read
    without a result. Its raw trial is then capped by the rule of :mod:`.caps`.
    """
    try:
        return harness_total(run_dir)
    except ComparisonError:
        return None


@dataclass(frozen=True)
class _Cell:
    """The cell's harness trials, as the cap rule reads them, and where each entry stands in it."""

    trials: tuple[tuple[TierName, CellTrial], ...]
    #: Each trial of the cell by its run directory (resolved) and trial number.
    places: Mapping[tuple[str, int], int]

    def of(self, tier: TierName) -> list[CellTrial]:
        return [trial for here, trial in self.trials if here == tier]

    def own(self, entry: RunSetEntry, tier: TierName, index: int) -> CellTrial:
        place = self.places.get((os.path.realpath(entry.run_dir), entry.trial))
        if place is None:
            msg = "the harness trial is not one of the cell's its cap is taken from"
            raise BaselineError(msg, entry=str(index), refused_because="not_in_the_cell")
        return next(trial for here, trial in self.trials if trial.place == place and here == tier)


def _cell_trials(
    runs: RunSet,
    cell: RunSet | None,
    tasks: Mapping[str, tuple[TierName, Task]],
    leaving: frozenset[str],
) -> _Cell:
    """The cell's harness trials: ``cell``'s, or the round's own run set's where none is given.

    Each is read as the plan reads an entry: its run's task by its brief, its tier, its figure. A
    held-out task the version's check flagged is in no cell.

    Raises:
        BaselineError: a trial of the cell is listed twice, or its run was given no task of
            the source; it is named by its place in the cell's run set.
    """
    given = runs if cell is None else cell
    trials: list[tuple[TierName, CellTrial]] = []
    places: dict[tuple[str, int], int] = {}
    for place, entry in enumerate(given.trials):
        key = (os.path.realpath(entry.run_dir), entry.trial)
        if key in places:
            msg = "a harness trial is listed twice in the cell's run set"
            raise BaselineError(msg, cell_entry=str(place))
        run_dir = Path(entry.run_dir)
        brief = load_run_config(run_dir / "run.json").brief_sha256
        found = tasks.get(brief)
        if found is None:
            msg = "a harness trial of the cell was given no task of the round's source"
            raise BaselineError(msg, cell_entry=str(place))
        tier, task = found
        if tier == "held_out" and task.id in leaving:
            continue
        places[key] = place
        trials.append((tier, CellTrial(place, brief, harness_figure(run_dir))))
    return _Cell(tuple(trials), places)


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
    from physgate.evaluation.tiers.exposure import run_roots_refusal

    others = [r for r in get_args(Role) if r != role and os.path.lexists(role_root(store, r))]
    also = [(store, role), *((store, other) for other in others)]
    for refusal in (
        spelling_refusal(config.held_out, also=also),
        withheld_refusal(config.held_out, also=also),
        work_refusal(config.held_out),
        protected_tier_refusal(config.held_out, also=also),
        # The run roots, whole, where the round's harness runs lie: the raw session is given
        # them as the harness run withheld them.
        run_roots_refusal(config, None),
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


def _require_reviewed_inside(run_dir: Path, where: dict[str, str]) -> Path:
    """The harness run's review root, as it recorded it, if it lies inside its run directory.

    Its reviews leave the brief, the specification and the answer in each packet, each
    reviewer's record, and the key for labels under its review root. A raw session is withheld
    that root whole, and every later session is withheld it with the run roots, only where it
    lies strictly inside the run's own directory, which is where a measured run reviews
    (:func:`physgate.evaluation.tiers.exposure.review_root_refusal`). A development round is held
    to it too.

    Raises:
        BaselineError: the run recorded no review root, or one that cannot be read, so where its
            reviews ran is unknown; or one outside its directory. Said by what it is, never by
            the path.
    """
    from physgate.evaluation.tiers.exposure import review_root_refusal

    try:
        recorded = recorded_review_root(run_dir)
    except RunStateError:
        recorded = None
    if recorded is None:
        msg = (
            "the harness run recorded no review root that can be read, so where its reviews left "
            "the brief and the answer is unknown and nothing could withhold it from the raw "
            "session"
        )
        raise BaselineError(msg, refused_because="review_root_unrecorded", **where)
    refusal = review_root_refusal(run_dir, recorded, reviewing=True)
    if refusal is not None:
        msg = f"the harness run did not review where every run on the store must: {refusal[1]}"
        raise BaselineError(msg, refused_because=refusal[0], **where)
    return Path(os.path.realpath(recorded))


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


def _now() -> datetime:
    return datetime.now(UTC)


def _inputs_sha256(
    store: Path,
    role: Role,
    version: str | None,
    external: Path | None,
    runs: RunSet,
    development: bool,
    base_url: str | None,
    *,
    cell: RunSet | None = None,
    shakedown: bool = False,
    rerun_of: str | None = None,
) -> str:
    """The digest a round's inputs are held to across its starts.

    The cell's run set, the shakedown word and the round re-run are held only where given, so a
    round given none of them is held to the digest its inputs always had.
    """
    given: dict[str, Any] = {
        "store": str(store),
        "role": role,
        "version": version,
        "external": None if external is None else str(external),
        "runs": runs.model_dump(mode="json"),
        "development": development,
        "base_url": base_url,
    }
    if cell is not None:
        given["cell"] = cell.model_dump(mode="json")
    if shakedown:
        given["shakedown"] = True
    if rerun_of is not None:
        given["rerun_of"] = rerun_of
    return hashlib.sha256(canonical_json(given)).hexdigest()


class Ledger:
    """The round's ledger: its lines as read, and each new one appended and synced."""

    def __init__(self, path: Path, lines: list[dict[str, Any]]) -> None:
        """The ledger at ``path``, holding ``lines``."""
        self.path = path
        self.lines = lines

    @classmethod
    def read(cls, out: Path, *, mend: bool = False) -> Ledger:
        """The ledger of the round in ``out``.

        ``mend``: a last line a kill cut off as it was written is dropped from the file and a
        ``cut`` line says how many bytes it held and their digest. Each line is written before
        the step it names is taken, so a cut line's step was never taken. Only the round itself
        mends its ledger; every reader of a finished round reads it as it is.

        Raises:
            BaselineError: there is none, or a line of it is not whole JSON (``ledger_unread``).
        """
        path = out / LEDGER
        cut = b""
        if mend:
            try:
                cut = _drop_a_cut_line(path)
            except OSError as exc:
                msg = "the round's ledger cannot be read, so where it stands is not known"
                raise BaselineError(
                    msg, refused_because="ledger_unread", error=str(exc.strerror)
                ) from None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = "the round's ledger cannot be read, so where it stands is not known"
            raise BaselineError(
                msg, refused_because="ledger_unread", error=str(exc.strerror)
            ) from None
        try:
            lines = [json.loads(line) for line in text.splitlines()]
        except ValueError:
            msg = "a line of the round's ledger is not whole, so where it stands is not known"
            raise BaselineError(msg, refused_because="ledger_unread") from None
        if not lines or lines[0].get("kind") != "round":
            msg = "the round's ledger does not begin with the round's own line"
            raise BaselineError(msg, refused_because="ledger_unread")
        ledger = cls(path, lines)
        if cut:
            ledger.add(
                {"kind": "cut", "bytes": len(cut), "sha256": hashlib.sha256(cut).hexdigest()}
            )
        return ledger

    def add(self, line: Mapping[str, Any]) -> None:
        """Append ``line``, synced before the step it names goes on."""
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, canonical_json(dict(line)))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.lines.append(dict(line))

    def of(self, index: int) -> list[dict[str, Any]]:
        """The entry's lines, in order."""
        return [line for line in self.lines if line.get("index") == index]

    def sessions(self, index: int) -> int:
        """How many sessions of the entry were started."""
        return sum(1 for line in self.of(index) if line["kind"] == "started")

    def recorded(self) -> list[dict[str, Any]]:
        """Every entry's ``recorded`` line, in the order the round recorded them."""
        return [line for line in self.lines if line["kind"] == "recorded"]

    def once_more_spent(self, index: int) -> bool:
        """Whether the entry's one more go was taken: a session the machine ended otherwise."""
        return any(line["kind"] == "machine" for line in self.of(index))

    def stopped(self, index: int) -> dict[str, Any] | None:
        """The entry's ``stopped`` line, if the round stopped on it for a cause."""
        return next((line for line in self.of(index) if line["kind"] == "stopped"), None)

    def last(self, index: int, *, skipping: frozenset[str] = frozenset()) -> dict[str, Any] | None:
        """The entry's last line but those of the kinds ``skipping``, or ``None``."""
        lines = [line for line in self.of(index) if line["kind"] not in skipping]
        return lines[-1] if lines else None


def _drop_a_cut_line(path: Path) -> bytes:
    """Cut off the file's last line where it is not whole; the bytes cut, or none.

    Raises:
        OSError: the file cannot be read or cut.
    """
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return b""
    keep = data.rfind(b"\n") + 1
    with path.open("r+b") as handle:
        handle.truncate(keep)
        handle.flush()
        os.fsync(handle.fileno())
    return data[keep:]


def _waiting_for_limit(
    line: Mapping[str, Any], now: datetime, *, word: bool
) -> dict[str, Any] | None:
    """The wait a ``limit`` line stands at, held to the core's rule at ``now``; ``None`` to go on.

    A reset the client's stream gave is waited for whatever the word says; one it did not give
    is waited for until the core's stated wait after the halt, or until a person's word.
    """
    limit = (
        None
        if line.get("limit") is None
        else UsageLimit.model_validate_json(json.dumps(line["limit"]))
    )
    halted = str(line["halted_at"])
    if resume_refusal(halted, limit, now, limit_reset=word) is None:
        return None
    return {
        "index": line["index"],
        "why": USAGE_LIMIT,
        "resume_after": resume_after(halted, limit),
        "word_helps": resume_refusal(halted, limit, now, limit_reset=True) is None,
    }


def _write_whole(path: Path, data: bytes) -> None:
    """Write ``path`` whole: a new file beside it, synced, renamed over it."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


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
    resume: bool = False,
    limit_reset: bool = False,
    now: Callable[[], datetime] = _now,
    cell: RunSet | None = None,
    shakedown: bool = False,
) -> BaselineRecord:
    """Run the raw arm on every trial of ``runs``, and write the round's records under ``out``.

    ``out`` is new: a round gets a directory of its own, and its records are never replaced;
    ``resume`` goes on with the round ``out`` holds, given the same inputs. A round that has
    ended, started again, gives the record it wrote and does nothing else. ``base_url`` is the
    operator's endpoint, ``None`` for the binary's default; every harness run must have recorded
    it, and ``setup_for`` must send the credential there. The round's source is the store's
    ``version`` or the external set at ``external``, exactly one. ``cell`` is the run set of
    every harness trial of the cell the entries' caps are taken from (:func:`plan`); an entry
    whose harness trial gave no figure runs after every other entry of the round. ``shakedown``
    is the word that lets the round run on a practice version.

    **The round waits, and spends nothing for it.** A session the account's usage limit ended
    stops the round as waiting for the reset (:class:`RoundWaits`, ``waiting_for_limit``); one
    whose credential was refused stops it as waiting for a person (``waiting_for_a_person``).
    Each is kept where a finished trial lies, named in the ledger with its spend, and is no
    trial: it has no trial record, is never scored, and spends neither the entry's one more go
    nor anything else, however often it comes. Started again with ``resume``, the round runs that
    entry's session again as if it had not run: at once after a refused credential; after the
    limit, only once the core would resume a run halted on it (the reset the client's stream
    gave; where it gave none, the core's stated wait or ``limit_reset``, a person's word, used
    once). A start before then makes nothing and writes nothing, and raises the same wait.

    **A killed round goes on from its own files, however often, and that spends nothing.** Each
    step's ledger line is written before the step: a session's ``started`` line before its
    session, the line that ends it (``limit``, ``credential``, ``machine``, ``moving`` for a trial
    scored and held equal, ``stopped`` for a stop) before its move. Started again, the round
    reads where its entry stands (:func:`_one_trial`): a session whose place holds no record of
    the raw arm's was killed before it ended; its place is cleared of the credential, kept
    where a finished trial lies, named on a ``killed`` line with what it left, and the entry runs
    again as if it had not run. A session whose record is there is finished from its files and
    never run again. A move a kill cut short is finished; a trial line the ledger does not name
    yet is taken as the entry's own where it is the one its files give; a ledger line a kill cut
    is dropped (a ``cut`` line). An entry stopped for a cause is never run again in its round
    (:func:`stopped_entry_refusal`).

    Raises:
        BaselineError: the round was refused before it started, or stopped for a cause (a pair
            that differs, other pins, an error, a move that failed); ``session_started`` says
            whether a session of the entry had started.
        RoundWaits: the round waits for the usage limit's reset or for a person.
    """
    given = _inputs_sha256(
        store, role, version, external, runs, development, base_url, cell=cell, shakedown=shakedown
    )
    if resume:
        ledger = Ledger.read(out, mend=True)
        header = ledger.lines[0]
        if header.get("inputs_sha256") != given:
            msg = "the round is started again on other inputs than it began with"
            raise BaselineError(msg, refused_because="inputs_changed")
        if (out / BASELINE_RECORD).exists():
            # A round that ended is done: started again, it says so with its own record.
            return BaselineRecord.model_validate_json((out / BASELINE_RECORD).read_bytes())
        round_id = str(header["round"])
    elif out.exists():
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
    own = own_places(store, role, round_id) if resume else frozenset()
    source, planned = plan(
        store,
        role,
        version,
        runs,
        base_url=base_url,
        development=development,
        external=external,
        cell=cell,
        shakedown=shakedown,
        own_places=own,
    )
    if not resume:
        out.mkdir(mode=0o700, parents=True)
        round_id = secrets.token_hex(8)
        ledger = Ledger(out / LEDGER, [])
        ledger.add(
            {
                "kind": "round",
                "format": LEDGER_FORMAT,
                "round": round_id,
                "inputs_sha256": given,
                "started": utc_stamp(now()),
            }
        )
    protected_root = withheld_root(store, role) / BASELINE_DIR / round_id
    counted = EXTERNAL_TIERS if isinstance(source, ExternalSetRecord) else VERSION_TIERS
    order = in_order(planned)
    done = {int(line["index"]) for line in ledger.recorded()}
    standing = next((trial for trial in order if trial.index not in done), None)
    stood = None if standing is None else ledger.last(standing.index, skipping=PASSING)
    if limit_reset and (stood is None or stood["kind"] != "limit"):
        msg = "the round stands waiting for no usage limit; the word is for none"
        raise BaselineError(msg, refused_because="limit_reset_not_waiting")
    held = _Round(
        store=store,
        role=role,
        out=out,
        withheld_out=withheld_out,
        round_id=round_id,
        protected_root=protected_root,
        ledger=ledger,
        score=score,
        prices=prices,
        arm=arm,
        sleep=sleep,
        development=development,
        now=now,
        by_index={trial.index: trial for trial in planned},
        pins=_first_pins(ledger, planned, out, protected_root),
    )
    for trial in order:
        if trial.index in done:
            continue
        protected = trial.tier in PROTECTED_TIERS
        try:
            ended = _one_trial(trial, held, setup_for, word=limit_reset)
        except BaselineError:
            raise  # the runner's own: it names the entry and fields, never the task
        except Exception as exc:
            started = _stopped_on_an_error(ledger, trial.index, exc)
            if not protected:
                raise
            # A scorer's or an arm's error may name the task, a spec or a value of it; of a
            # protected trial only the tier and the error's kind are said, and nothing chained.
            msg = f"a {trial.tier} trial stopped on an error ({type(exc).__name__}), not repeated"
            raise BaselineError(
                msg,
                tier=trial.tier,
                entry=str(trial.index),
                refused_because="error",
                session_started=str(started).lower(),
            ) from None
        if isinstance(ended, RoundWaits):
            _write_whole(out / ROUND_RECORD, canonical_json(ended.printed()))
            raise ended
    pins = held.pins
    assert pins is not None  # the run set holds at least one trial
    tallies = _tallies(ledger, planned, counted, out, protected_root)
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
        created=now().strftime("%Y-%m-%d"),
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
        practice=True if isinstance(source, TierSet) and source.practice else None,
    )
    if external_set is not None:
        write_new(out / EXTERNAL_RECORD, record_bytes(external_set))
    if tiers is not None:
        write_new(out / TIERS_RECORD, record_bytes(tiers))
    write_new(out / BASELINE_RECORD, record_bytes(baseline))
    _write_whole(
        out / ROUND_RECORD, canonical_json({"format": 1, "round": round_id, "status": "done"})
    )
    return baseline


def in_order(planned: Sequence[Planned]) -> list[Planned]:
    """The order a round runs its entries in: the run set's, every entry with no figure last.

    An entry whose harness trial gave no figure is capped from its cell's other trials
    (:mod:`.caps`), so it runs after them, at the end of the cell, as the draft orders it. An
    entry keeps its place in the run set as its index whatever its turn.
    """
    return [t for t in planned if not t.no_figure] + [t for t in planned if t.no_figure]


def _stopped_on_an_error(ledger: Ledger, index: int, exc: Exception) -> bool:
    """Name on the ledger a stop on an error after the entry's session started; whether it had.

    An error before the ``started`` line (a setup refused, an arm that refuses before it makes
    anything) is a refusal before start, and no line is written.
    """
    last = ledger.last(index, skipping=PASSING)
    if last is None or last["kind"] != "started":
        return False
    ledger.add(
        {
            "kind": "stopped",
            "index": index,
            "session": last["session"],
            "because": "error",
            "error": type(exc).__name__,
        }
    )
    return True


def own_places(store: Path, role: Role, round_id: str) -> frozenset[Path]:
    """What the round ``round_id`` left in the role's work root and role root itself.

    Its trials' places in the work root, by the round's id in their names, and every record of
    work in the role's root that names one of them. The round settles them itself
    (:func:`_one_trial`); every other entry there still refuses it as work left.
    """
    works, root = work_root(store, role), role_root(store, role)
    prefix = f"{BASELINE_DIR}-{round_id}-"
    found: set[Path] = set()
    with contextlib.suppress(FileNotFoundError):
        found |= {works / name for name in os.listdir(works) if name.startswith(prefix)}
    with contextlib.suppress(FileNotFoundError):
        for name in os.listdir(root):
            if not (name.startswith(f"{BASELINE_DIR}-") and name.endswith(WORKING)):
                continue
            try:
                named = json.loads(read_beneath(root, (name,), limit=4096)).get("work")
            except (OSError, FileRefused, ValueError, AttributeError):
                continue
            if (
                isinstance(named, str)
                and Path(named).parent == works
                and Path(named).name.startswith(prefix)
            ):
                found.add(root / name)
    return frozenset(found)


#: The lines a step passes over when it asks where an entry stands: a never-started place
#: cleared away is no step of the entry's.
PASSING = frozenset({"cleared"})


def _how_it_goes_on(
    ledger: Ledger, index: int, round_id: str, now: datetime, *, word: bool
) -> str | None:
    """How the entry's next session may start, as the ledger leaves it; or the round stays put.

    ``None`` for a fresh start; ``waited`` or ``operator`` past a usage limit (the core's rule,
    the person's word used once). Asked once the entry's last session is settled.

    Raises:
        RoundWaits: the entry stands at a usage limit the core would still wait for.
    """
    last = ledger.last(index, skipping=PASSING)
    if last is None or last["kind"] != "limit":
        return None
    if _waiting_for_limit(last, now, word=False) is None:
        return "waited"
    waiting = _waiting_for_limit(last, now, word=word)
    if waiting is None:
        return "operator"
    raise RoundWaits("waiting_for_limit", round_id, waiting)


def _trial_files(
    planned: Planned, session: int, out: Path, protected_root: Path
) -> tuple[Path, Path, Path]:
    """Where a recorded session of ``planned`` lies once moved: its directory, harness, stream."""
    name = f"{planned.index:04d}-{session}"
    directory = protected_root / name if planned.tier in PROTECTED_TIERS else out / WORK / name
    return directory, directory / HARNESS, directory / PLACE / "session" / "stdout.jsonl"


def read_record(harness: Path) -> dict[str, Any]:
    """The raw arm's record a finished session left in its harness directory.

    Read as every file of a finished trial is read: no link followed, under the session file
    bound.

    Raises:
        BaselineError: it cannot be read whole (``record_unread``), naming no path.
    """
    try:
        fd = open_beneath(harness, ("raw.json",))
        try:
            data = read_bounded(fd, MAX_SESSION_FILE_BYTES)
        finally:
            os.close(fd)
        record = json.loads(data)
    except (OSError, FileRefused, ValueError) as exc:
        msg = "a finished session's record cannot be read whole"
        raise BaselineError(
            msg, refused_because="record_unread", error=type(exc).__name__
        ) from None
    if not isinstance(record, dict):
        msg = "a finished session's record is not a record"
        raise BaselineError(msg, refused_because="record_unread")
    return record


def _first_pins(
    ledger: Ledger, planned: list[Planned], out: Path, protected_root: Path
) -> dict[str, Any] | None:
    """The pin set the round's first recorded trial ran under, from its own record; or ``None``."""
    first = next(iter(ledger.recorded()), None)
    if first is None:
        return None
    by_index = {trial.index: trial for trial in planned}
    _, harness, _ = _trial_files(
        by_index[int(first["index"])], int(first["session"]), out, protected_root
    )
    return pin_set(read_record(harness)["pins"])


def read_lines(path: Path) -> list[TrialRecord | ExcludedTrial]:
    """The trial records a round wrote at ``path``, in order; none if it wrote none there."""
    if not path.exists():
        return []
    lines: list[TrialRecord | ExcludedTrial] = []
    for text in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(text)
        model = ExcludedTrial if "reason" in raw and "outcome" not in raw else TrialRecord
        lines.append(model.model_validate_json(text))
    return lines


def tallied(
    recorded: Sequence[tuple[Planned, Mapping[str, Any], TrialRecord | ExcludedTrial]],
    counted: tuple[SourceTier, ...],
) -> dict[SourceTier, _Tally]:
    """Each tier's counts from its recorded trials' records and lines: summed here alone."""
    tallies = {tier: _Tally() for tier in counted}
    for trial, record, line in recorded:
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
    return tallies


def _tallies(
    ledger: Ledger,
    planned: list[Planned],
    counted: tuple[SourceTier, ...],
    out: Path,
    protected_root: Path,
) -> dict[SourceTier, _Tally]:
    """Each tier's counts, from the records the round wrote and its sessions' own records.

    Read from the files, never from what this process holds, so a round started again counts
    the trials its earlier starts recorded. The lines of each place are in the order the
    ledger recorded its entries.
    """
    by_index = {trial.index: trial for trial in planned}
    written = {
        False: iter(read_lines(out / TRIALS)),
        True: iter(read_lines(protected_root / TRIALS)),
    }
    recorded: list[tuple[Planned, Mapping[str, Any], TrialRecord | ExcludedTrial]] = []
    for line in ledger.recorded():
        trial = by_index[int(line["index"])]
        _, harness, _ = _trial_files(trial, int(line["session"]), out, protected_root)
        trial_line = next(written[trial.tier in PROTECTED_TIERS], None)
        if trial_line is None:
            msg = "the round's ledger records a trial its records do not hold; a person must look"
            raise BaselineError(msg, refused_because="records_short", entry=str(trial.index))
        recorded.append((trial, read_record(harness), trial_line))
    return tallied(recorded, counted)


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


def trial_line(
    trial: Planned,
    role: Role,
    record: Mapping[str, Any],
    stream: Path,
    prices: DatedSheet,
    scored: Mapping[str, Any] | None,
    *,
    unscored: bool,
) -> TrialRecord | ExcludedTrial:
    """The record of a raw trial from its session's own record, stream and score."""
    return raw_trial(
        suite=f"{role}_{trial.tier}",
        task=trial.task,
        trial=trial.entry.trial,
        record=record,
        stream=stream,
        prices=prices,
        score=scored,
        unscored=unscored,
    )


@dataclass
class _Round:
    """A round as one trial's steps need it: where it lies, what it writes with, what it holds."""

    store: Path
    role: Role
    out: Path
    withheld_out: str
    round_id: str
    protected_root: Path
    ledger: Ledger
    score: Scorer
    prices: DatedSheet
    arm: Arm
    sleep: Callable[[float], None]
    development: bool
    now: Callable[[], datetime]
    by_index: dict[int, Planned]
    #: The pin set of the round's first recorded trial; ``None`` until one is recorded.
    pins: dict[str, Any] | None

    def place(self, index: int, session: int) -> Path:
        """Where a session of the entry is made: its trial's directory in the work root."""
        return (
            work_root(self.store, self.role)
            / f"{BASELINE_DIR}-{self.round_id}-{index:04d}-{session}"
        )

    def working(self, index: int, session: int) -> Path:
        """The record in the role's root that names that place while it lies there."""
        name = f"{BASELINE_DIR}-{index:04d}-{session}{WORKING}"
        return role_root(self.store, self.role) / name

    def kept(self, trial: Planned, session: int) -> Path:
        """Where the session's directory lies once moved out: a finished trial's place."""
        return _trial_files(trial, session, self.out, self.protected_root)[0]

    def protected_root_of(self, trial: Planned) -> Path | None:
        return self.protected_root if trial.tier in PROTECTED_TIERS else None


#: What a trial's steps give back: its session's record and number once the trial is recorded,
#: a wait, or ``again`` where the machine's first end is given its one more go.
Ended = tuple[dict[str, Any], int] | RoundWaits


def _one_trial(trial: Planned, held: _Round, setup_for: SetupFor, *, word: bool) -> Ended:
    """One harness trial's raw trial, until it is recorded or the round waits.

    Each session is named by its number among the entry's (``<index>-<n>``) and is started only
    once the ledger says so. What follows each is :func:`next_step`'s: a wait, the one more go
    after the run's own first infrastructure delay, or the record of the trial. Before any
    session, the entry's last session is settled from the round's own files
    (:func:`_settled`): a session a kill left is finished, or named and run again.
    """
    index, ledger = trial.index, held.ledger
    # Before any record of work: a setup refused here (no credential, another binary) leaves
    # nothing behind for the next round to refuse.
    setup = setup_for(trial.config, held.role)
    try:
        built = measure(setup.binary)
    except InvocationError as exc:
        raise BaselineError(str(exc), entry=str(index), refused_because="binary") from None
    if built != trial.config.binary:
        msg = "the binary here is not the build the harness run executed"
        raise BaselineError(msg, entry=str(index), refused_because="binary")
    if not isinstance(setup.os_layer, Present):
        # Before the session, never only after it (``differences``): every raw session is
        # withheld a root whole (the work root around its trial's place, and the run roots), and
        # with the hooks alone a path a command builds as it runs reaches it. The installer
        # refuses such a session too; here the round stops before it makes any place.
        msg = (
            "the OS layer is absent here, and every raw session is withheld a root whole (its "
            "trial's place in the work root, the run roots), which the hooks alone do not hold; "
            "no raw session runs without the layer"
        )
        raise BaselineError(msg, entry=str(index), refused_because="os_layer_absent")
    _require_the_round_s_checkout(ledger, setup, index)
    stopped = ledger.stopped(index)
    if stopped is not None:
        stopped_entry_refusal(index, str(stopped.get("because")))
    _require_before_started(trial, setup, held)
    settled = _settled(trial, held, setup)
    if settled is not None and settled != "again":
        return settled
    if settled is None:
        last = ledger.last(index, skipping=PASSING)
        if last is not None and last["kind"] == "machine":
            # Stopped between the session the machine ended and its one more go: its delay again.
            held.sleep(float(last["delay_s"]))
    try:
        how = _how_it_goes_on(ledger, index, held.round_id, held.now(), word=word)
    except RoundWaits as waits:
        return waits
    while True:
        session = ledger.sessions(index) + 1
        name = f"{index:04d}-{session}"
        # Made in the work root, which every run on the store withholds, whatever the trial's
        # tier: its session is given its own place out of the run's held-out roots and nothing
        # else there, and the round's own directory is withheld from it besides. Two
        # directories, never one: the session's place, where it may leave anything, and the
        # harness's, beside it, where the copied answer, the record and the score are written.
        # The work root is held until the trial is out (:func:`trial_place`).
        with trial_place(held.store, held.role, held.round_id, name) as (trial_dir, working):
            started: dict[str, Any] = {"kind": "started", "index": index, "session": session}
            if how is not None:
                started["limit_reset"] = how
            # The checkout this session runs from, and the credential it is given, by its
            # fingerprint: a later start is held to the first, and a session a kill left is
            # cleared knowing whether the credential it held is the one in hand.
            started["harness"] = _checkout(setup)
            started["credential"] = fingerprint(setup.credential)
            ledger.add(started)
            how = None
            given = replace(
                setup,
                held_out_carved=str(trial_dir / PLACE),
                held_out_also=(held.withheld_out,),
                # The harness run's own review root, whole: where its reviews left the brief and
                # the answer, refused to the raw session wherever its run lies.
                withheld_reads=(*setup.withheld_reads, str(trial.review_root)),
            )
            work, harness = trial_dir / PLACE, trial_dir / HARNESS
            harness.mkdir(mode=0o700)
            # The cap the session runs under, the step of the rule that gave it and its inputs:
            # with the trial, where its records lie.
            write_new(harness / CAP, canonical_json(trial.cap_rule.recorded()))
            record = held.arm(trial.task, given, work, cap=trial.cap, harness=harness)
            ended = _after_session(trial, held, session, record, trial_dir, working, halted_at=None)
        if ended == "again":
            continue
        return ended


#: Beside a trial's record in its harness directory: the cap it ran under, and the rule's step.
CAP = "cap.json"


def _checkout(setup: RawSetup) -> dict[str, Any] | None:
    """The harness checkout a session runs from, as its record holds it: commit, and clean."""
    if setup.harness is None:
        return None
    return {"commit": setup.harness.commit, "clean": setup.harness.clean}


def _require_the_round_s_checkout(ledger: Ledger, setup: RawSetup, index: int) -> None:
    """Refuse a start on another checkout than the round's earlier sessions ran from.

    Every ``started`` line holds the checkout its session ran from; a line written before lines
    held one holds none, which is no checkout this code can be held to.

    Raises:
        BaselineError: ``harness_differs``, before anything of the entry is touched.
    """
    now = _checkout(setup)
    for line in ledger.lines:
        if line.get("kind") == "started" and line.get("harness", "unrecorded") != now:
            msg = (
                "the round is started again from another checkout of the harness than its "
                "sessions ran from; a round continued on other code is two rounds under one name"
            )
            raise BaselineError(msg, entry=str(index), refused_because="harness_differs")


def _require_before_started(trial: Planned, setup: RawSetup, held: _Round) -> None:
    """Hold the interpreter and the tool environment to the harness run's, before any line.

    The pair check holds both after the session too (:func:`.arms.compare.differences`); here a
    drift is a refusal before start, which spends nothing and leaves nothing, never a session.

    Raises:
        BaselineError: ``interpreter_differs`` or ``tool_environment_differs``.
    """
    index = trial.index
    here = None if setup.role_python is None else setup.role_python.model_dump(mode="json")
    recorded = trial.config.role_python
    if here != (None if recorded is None else recorded.model_dump(mode="json")):
        msg = "the role's interpreter here is not the one the harness run recorded"
        raise BaselineError(msg, entry=str(index), refused_because="interpreter_differs")
    try:
        hold_tools(setup, held.place(index, held.ledger.sessions(index) + 1) / PLACE)
    except RawArmError as exc:
        msg = f"the tool environment here is not the one the harness run recorded: {exc}"
        raise BaselineError(
            msg, entry=str(index), refused_because="tool_environment_differs"
        ) from None


def _settled(trial: Planned, held: _Round, setup: RawSetup) -> Ended | Literal["again"] | None:
    """Settle the entry's last session from the round's own files; what it then stands at.

    ``None`` where the entry goes on to its next session; ``again`` where that session follows a
    machine end whose delay was slept here; a record or a wait where the last session gives one.

    - last line ``started`` (the session's own line, nothing after it): its place holds the raw
      arm's record, so the session ended and is finished from its files, never run again; or it
      holds none, so it was killed before it ended (:func:`_killed`);
    - last line ``moving``: the trial was scored and held equal; its move is finished and its
      line recorded (:func:`_record_line`);
    - a wait's or a machine end's line, or ``killed``: a move a kill cut short is finished.

    A place for the entry's next session that a kill left before its ``started`` line holds
    nothing of a session, and is cleared away (a ``cleared`` line).
    """
    index, ledger = trial.index, held.ledger
    last = ledger.last(index, skipping=PASSING)
    session = ledger.sessions(index)
    outcome: Ended | Literal["again"] | None = None
    if last is not None and last["kind"] == "started":
        place = held.place(index, session)
        record_file = place / HARNESS / "raw.json"
        if os.path.lexists(record_file):
            record = read_record(place / HARNESS)
            halted = utc_stamp(datetime.fromtimestamp(os.lstat(record_file).st_mtime, UTC))
            outcome = _after_session(
                trial, held, session, record, place, held.working(index, session), halted_at=halted
            )
        else:
            _killed(trial, held, setup, session, last)
    elif last is not None and last["kind"] == "moving":
        _move_if_left(trial, held, session)
        return _finish_recorded(trial, held, session)
    elif last is not None and last["kind"] in ("limit", "credential", "machine", "killed"):
        _move_if_left(trial, held, session)
    _clear_unstarted(trial, held, ledger.sessions(index) + 1)
    return outcome


def _killed(
    trial: Planned, held: _Round, setup: RawSetup, session: int, started: Mapping[str, Any]
) -> None:
    """Name and keep a session a kill left before it ended; the entry then runs again.

    The session left no record of the raw arm's, so it was never scored and no score of it can
    have been read: it is no trial and spends nothing. Its process ended (a session that still
    runs refuses the round first); a session whose runner was killed before its process facts
    were written never left the hold it is spawned in, so it ran nothing. What its place holds is
    cleared as a finished session's is (:func:`.arms.raw.clean_left_session`: the credential
    files, the sentinel's record of the protected paths, the secret in its streams), its streams
    scanned for the run's held-out canaries, and the place kept where a finished trial lies. Its
    streams are removed instead where the credential in hand is not the one the session was
    given, since that one could not be scrubbed from them. A canary in them stops the round.

    Raises:
        BaselineError: the place could not be cleared or moved (``left_session_not_cleared``,
            ``move``), or its stream showed a held-out canary (``held_out_seen``).
    """
    index, ledger = trial.index, held.ledger
    place = held.place(index, session)
    work = place / PLACE
    stream = work / "session" / "stdout.jsonl"
    left: dict[str, Any] = {
        "place": os.path.lexists(place),
        "session": os.path.lexists(work / "session"),
        "process": os.path.lexists(work / "session" / "process.json"),
        "stream": os.path.lexists(stream),
    }
    seen: bool | None = False
    if left["process"]:
        # It left its process facts, so it left the hold and ran: it must be known to have ended.
        living = living_session(held.store, held.role)
        if living is not None:
            msg = f"{living}: a session a kill left is not known to have ended"
            raise BaselineError(msg, entry=str(index), refused_because="session_lives")
    if left["session"]:
        try:
            clean_left_session(work, setup.credential.secret)
        except PerRoleError as exc:
            msg = (
                "a session a kill left could not be cleared of its credential; it is left where it "
                "ran for a person to look at"
            )
            raise BaselineError(
                msg, entry=str(index), refused_because="left_session_not_cleared", error=str(exc)
            ) from None
        if left["stream"]:
            seen = held_out_seen(stream, tuple(trial.config.held_out_canaries))
        if started.get("credential") != fingerprint(setup.credential):
            for name in ("stdout.jsonl", "stderr.txt"):
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(work / "session" / name)
            left["streams_removed"] = True
    ledger.add(
        {"kind": "killed", "index": index, "session": session, "left": left, "held_out_seen": seen}
    )
    if seen:
        ledger.add(
            {"kind": "stopped", "index": index, "session": session, "because": "held_out_seen"}
        )
    if left["place"]:
        _move_or_stop(trial, held, session, place, held.working(index, session))
    else:
        held.working(index, session).unlink(missing_ok=True)
    if seen:
        msg = (
            "a session a kill left showed a held-out canary in its stream; the round stops, as "
            "every exposure stops it"
        )
        raise BaselineError(
            msg, entry=str(index), refused_because="held_out_seen", session_started="true"
        )


def _move_if_left(trial: Planned, held: _Round, session: int) -> None:
    """Finish the move of the entry's session a kill cut short; clear its record of work.

    The ledger named the step before the move began. Where the place still lies in the work
    root the move had not ended: what a copy across filesystems made at the destination is
    removed (the place is whole until the copy is), and the move is made again.
    """
    index = trial.index
    place, working = held.place(index, session), held.working(index, session)
    if os.path.lexists(place):
        kept = held.kept(trial, session)
        if held.protected_root_of(trial) is None and os.path.lexists(kept):
            shutil.rmtree(kept)
        _move_or_stop(trial, held, session, place, working)
    else:
        working.unlink(missing_ok=True)


def _clear_unstarted(trial: Planned, held: _Round, session: int) -> None:
    """Clear away the place of a session a kill left before its ``started`` line.

    The line is written before anything of the session is made in the place, so such a place is
    empty: it is removed with its record of work and named on a ``cleared`` line. One that holds
    anything is no place this round left so, and refuses.

    Raises:
        BaselineError: the place holds something (``unstarted_place_holds``).
    """
    index = trial.index
    place, working = held.place(index, session), held.working(index, session)
    there = os.path.lexists(place)
    if not there and not os.path.lexists(working):
        return
    if there:
        if not place.is_dir() or place.is_symlink() or any(os.scandir(place)):
            msg = (
                "a place in the work root that no session of the round started in holds "
                "something; a person must look"
            )
            raise BaselineError(msg, entry=str(index), refused_because="unstarted_place_holds")
        os.rmdir(place)
    working.unlink(missing_ok=True)
    held.ledger.add({"kind": "cleared", "index": index, "session": session})


def _move_or_stop(
    trial: Planned, held: _Round, session: int, trial_dir: Path, working: Path
) -> None:
    """Move a session's directory out of the work root, or name the failed move as a stop.

    Raises:
        BaselineError: the move failed (``move``); the ledger names it as the entry's stop.
    """
    try:
        _finish(
            trial_dir,
            working,
            held.protected_root_of(trial),
            held.out,
            f"{trial.index:04d}-{session}",
        )
    except BaselineError as exc:
        if held.ledger.stopped(trial.index) is None:
            held.ledger.add(
                {"kind": "stopped", "index": trial.index, "session": session, "because": "move"}
            )
        exc.context.setdefault("entry", str(trial.index))
        exc.context["session_started"] = "true"
        raise


def _after_session(
    trial: Planned,
    held: _Round,
    session: int,
    record: dict[str, Any],
    trial_dir: Path,
    working: Path,
    *,
    halted_at: str | None,
) -> Ended | Literal["again"]:
    """What follows a session that ended with ``record``, its directory still in the work root.

    ``halted_at``: when a session finished from its files ended (its record's time), where a
    limit's reset given only as wall-clock text is read from; ``None`` for now.
    """
    task, index, ledger = trial.task, trial.index, held.ledger
    run_dir = Path(trial.entry.run_dir)
    work, harness = trial_dir / PLACE, trial_dir / HARNESS
    stream = work / "session" / "stdout.jsonl"
    end, limit = machine_end(record, stream, task)
    step = next_step(end, ledger.once_more_spent(index))
    spent = {"index": index, "session": session, "tokens": int(record.get("tokens", 0))}
    if step == "wait_for_limit":
        at = halted_at if halted_at is not None else utc_stamp(held.now())
        limited = held_at(limit, at)
        line = {
            "kind": "limit",
            **spent,
            "halted_at": at,
            "resume_after": resume_after(at, limited),
            "limit": None if limited is None else limited.model_dump(mode="json"),
        }
        ledger.add(line)
        _move_or_stop(trial, held, session, trial_dir, working)
        waiting = _waiting_for_limit(line, held.now(), word=False)
        if waiting is None:  # its reset is past already: the next start goes on
            waiting = {
                "index": index,
                "why": USAGE_LIMIT,
                "resume_after": line["resume_after"],
                "word_helps": False,
            }
        return RoundWaits("waiting_for_limit", held.round_id, waiting)
    if step == "wait_for_a_person":
        ledger.add({"kind": "credential", **spent})
        _move_or_stop(trial, held, session, trial_dir, working)
        return RoundWaits(
            "waiting_for_a_person", held.round_id, {"index": index, "why": CREDENTIAL_REFUSED}
        )
    if step == "once_more":
        delays = trial.config.bounds.infra_retry_delays_s
        delay = delays[0] if delays else 0.0
        ledger.add({"kind": "machine", **spent, "delay_s": delay})
        _move_or_stop(trial, held, session, trial_dir, working)
        # Only a session the machine ended is run again, once its trial is out.
        held.sleep(delay)
        return "again"
    scored = _scored(trial, held, record, harness)
    found = differences(run_dir, work, role=held.role, task=task, record_dir=harness, cap=trial.cap)
    allowed = DEVELOPMENT_DIFFERENCES if held.development else frozenset()
    if end == "machine" and not answering_models(read_captured(stream).answered):
        # No model answered: the machine's end, as it was on the first go; there is no
        # model to hold to the pin, and the trial is recorded unscored, never a stop.
        allowed |= {"answered_by"}
    named = sorted({f.split(":", 1)[0] for f in found} - allowed)
    if named:
        ledger.add(
            {
                "kind": "stopped",
                "index": index,
                "session": session,
                "because": "pair",
                "fields": named,
            }
        )
        _move_or_stop(trial, held, session, trial_dir, working)
        msg = "the raw arm differs from the harness run in more than the harness: "
        raise BaselineError(
            msg + ", ".join(named),
            entry=str(index),
            refused_because="pair_differs",
            session_started="true",
        )
    these = pin_set(record["pins"])
    if held.pins is not None and these != held.pins:
        ledger.add({"kind": "stopped", "index": index, "session": session, "because": "pins"})
        _move_or_stop(trial, held, session, trial_dir, working)
        msg = "the round's trials ran under different pins; no one baseline holds them"
        raise BaselineError(
            msg, entry=str(index), refused_because="pins_differ", session_started="true"
        )
    line_of = trial_line(
        trial, held.role, record, stream, held.prices, scored, unscored=end == "machine"
    )
    ledger.add({"kind": "moving", "index": index, "session": session})
    _move_or_stop(trial, held, session, trial_dir, working)
    _record_line(trial, held, line_of, session)
    if held.pins is None:
        held.pins = these
    return record, session


def _scored(
    trial: Planned, held: _Round, record: Mapping[str, Any], harness: Path
) -> Mapping[str, Any] | None:
    """The session's score: the one its harness directory holds, or scored now and written."""
    if record.get("answer") != "found":
        return None
    kept = harness / SCORE
    if os.path.lexists(kept):
        found: Mapping[str, Any] = json.loads(
            read_beneath(harness, (SCORE,), limit=MAX_SESSION_FILE_BYTES)
        )
        return found
    scored = held.score(trial.task, harness / "answer" / trial.task.answer.path)
    write_new(kept, canonical_json(dict(scored)))
    return scored


def _finish_recorded(trial: Planned, held: _Round, session: int) -> Ended:
    """Record a trial whose ``moving`` line was written, from the files it was moved with."""
    kept = held.kept(trial, session)
    record = read_record(kept / HARNESS)
    stream = kept / PLACE / "session" / "stdout.jsonl"
    end, _ = machine_end(record, stream, trial.task)
    scored = _scored(trial, held, record, kept / HARNESS)
    line = trial_line(
        trial, held.role, record, stream, held.prices, scored, unscored=end == "machine"
    )
    _record_line(trial, held, line, session)
    if held.pins is None:
        held.pins = pin_set(record["pins"])
    return record, session


def _record_line(
    trial: Planned, held: _Round, line: TrialRecord | ExcludedTrial, session: int
) -> None:
    """Append the trial's line to its tier's records, then its ``recorded`` ledger line.

    Each place's records hold one line per entry the ledger records there, in that order. A
    line the ledger does not name yet is this entry's, written before a kill: it is kept where
    it is the line the files give, a line a kill cut is dropped (a ``cut`` line), and any other
    line refuses.

    Raises:
        BaselineError: the records hold lines the ledger does not account for
            (``records_differ``).
    """
    protected = trial.tier in PROTECTED_TIERS
    path = (held.protected_root if protected else held.out) / TRIALS
    here = sum(
        1
        for done in held.ledger.recorded()
        if (held.by_index[int(done["index"])].tier in PROTECTED_TIERS) == protected
    )
    written: list[Any] = []
    if path.exists():
        cut = _drop_a_cut_line(path)
        if cut:
            held.ledger.add(
                {
                    "kind": "cut",
                    "file": "protected" if protected else "visible",
                    "bytes": len(cut),
                    "sha256": hashlib.sha256(cut).hexdigest(),
                }
            )
        written = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    if len(written) == here + 1 and written[-1] == line.model_dump(mode="json"):
        pass  # written before a kill, and the line the files give: kept
    elif len(written) == here:
        _append(path, line)
    else:
        msg = (
            "the round's trial records hold a line its ledger does not account for; a person "
            "must look"
        )
        raise BaselineError(
            msg, entry=str(trial.index), refused_because="records_differ", session_started="true"
        )
    held.ledger.add({"kind": "recorded", "index": trial.index, "session": session})


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
    working.unlink(missing_ok=True)


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
