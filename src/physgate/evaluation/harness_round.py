"""The harness-arm round: every task and trial of a tier version, one harness trial each.

**What it is given.** A tier-set store, a role and a version, the tiers to run, how many trials
of each task, a seed base, the run parameters, a registered run root, a pristine target
repository to clone, the hooks' installation and the price sheet's date. Nothing names a task:
the tasks are read from the version (:func:`_version_tasks`, this module's one reader of the
store), and every place a protected task's brief, answer, score or record is written lies
beneath the role's withheld root, which every run on the store withholds.

**What the round's own earlier process left is dealt with first** each time it is started again
(:func:`_what_its_earlier_process_left`): once the round is found by its output directory and its
lock held, every directory its ledger placed has its left review stopped, its sessions'
credentials removed and its exposure written, before anything below can refuse the start; a left
review that showed held-out material then refuses it. Only a start from inside a session, an
output directory that names no round, a round another driver holds, and a ledger that cannot be
read are refused before it: the round's own directories are then not known, or not this
process's to touch.

**Everything is refused before the first trial** (:func:`_refusals`), and again each time the
round is started: inside a harness session's environment; while a session left in the work
root still runs; a store a split or a session's work has not left clean; a version the role does
not have, that the register marks exposed, or that has no record of its blind check; a run root
that is not its real path spelt as the disk spells it, that is not one of the role's registered
run roots, or beneath which the core would refuse a trial's review root (a word in its path that
tells a reviewer what it reads, or a git checkout around it); parameters that are not
reportable, that do not withhold every protected place of the store or do not look for every
canary of the version and the store; parameters of any tier whose trials are not withheld from
one another (``withheld_whole`` naming every registered run root of the store and nothing else,
the run roots spelt as on disk, by the core's own rule, checked and never written); a target
that is not a clean repository, or whose top holds a run's configuration; a
harness checkout that is not a clean commit; an output directory inside the run root, the target
or the store; a person's word (``set_aside``, ``limit_reset``) for a wait the round does not stand
at. The core refuses what it refuses besides, at each decomposition, before its call.

**One driver drives a round.** It takes the round's lock before it reads the ledger and holds it
for its life; a second is refused at once and writes nothing. A lock a dead driver left (the
kernel's lock free, its pid still in the lock's file) is taken over, and the ledger says so.

**The code, the client and the tools are held.** The harness checkout and every field the census
holds equal across a tier's runs that the command measures afresh for each run (:data:`PINNED`:
the client binary and its version, the git, the role sessions' interpreter, the tool environment
and its servers, the endpoint, the tool search) are measured as the round starts and recorded in
its ledger's first line; a restart on others is refused, naming what differs. The census's other
fields are the parameters', held by their digest, or each trial's own.

**The order is fixed, and written once** in the round's ledger before the first trial: the
named tiers in the version's order (visible, validation, held out), within each the tasks by
their brief's digest (a held-out task the check flagged is left out), within each task its
trials from 0; trial ``i`` has the seed ``seed base + i``. Given an order seed, a round runs one
cell in the registered order instead (:func:`_registered_order`): the cell's (id digest, trial)
pairs shuffled once by the seed string, trial ``n`` of a task seeded ``seed base + n``. A call
may name one place of the order (``only``): it takes that trial on until it is assembled and
stops there. Every trial's one-entry run set and its sheet (``trials/``) are written once it is
assembled, in every mode.

**Each trial** is one harness run on a fresh clone of the target placed inside the trial's run
directory, ``<run root>/<round>/<iiii>-<n>``, with its review root beside the clone in the same
directory: so every place a trial's sessions and reviewers write lies in one run directory
beneath a registered run root. The trial's brief is the task's brief, byte for byte, written
beneath the withheld root. The run is decomposed and driven through the ``physgate`` command
in this process (:class:`CommandDriver`), its output written beneath the withheld root and
never relayed: ``decompose`` prints the planner's module names. Once the run has ended, its
answer is extracted from its run branch (:func:`.per_role.arms.harness.extract`), scored,
priced and assembled into the trial's record (:func:`.per_role.assemble.harness_trial`).

**The ledger** (``ledger.jsonl`` beneath the withheld root) is appended to and synced before
each step it names is taken, never rewritten, and is the round's only state besides the runs'
own records: every output is written from it whole. A round that was killed is started again
with the same inputs and ``resume``: each trial's state is read from its run's own lines, so a
trial is never repeated and never skipped, and a killed run is resumed, never restarted.

**How a trial ends** (each read from the run's own records, never from what this process holds):

- a run that has not ended is resumed (``physgate resume``), however often it was killed;
- the account's usage limit is never an end and never an attempt: a run halted on it is resumed
  past it, and a decomposition that ended on it (its run's record halted on the failed
  decomposition, or its rounds ended void on the limit, as the core records each) is named in the
  ledger with its spend and made afresh in a new directory, each once the limit has reset (the
  round stops as waiting for the limit, exit 75, naming the trial and the instant after which it
  goes on: the reset the client's message gave, where the core read one and recorded it on the
  halt or the rounds' end line, else the core's stated wait after the halt or that line; started
  again before then it makes nothing, unless no reset was read and a person gives the word, which
  is used once and named on the line of the directory it makes), however often and in whatever
  order with the machine's other ends;
- a refused credential is no attempt either: the round stops as waiting for a person (exit 77),
  and started again once the credential is replaced resumes the run, or names the
  decomposition's directory with its spend and decomposes afresh;
- a trial the machine ended otherwise is given its one more go: a run halted on the machine with
  one such halt in its log (the limit's and a credential's not counted) is resumed once, after
  its first registered retry delay; a run whose decomposition call ended on the machine, and a
  decomposition that spent its call and left no run (killed after the call or during its plan's
  review, or ended void on anything but the limit; or killed while its run was started, or its
  start raising, so that it left a log the core will never dispatch, as the core's own opening of
  the record says), are superseded by one fresh decomposition into a new directory, after
  the same delay. A superseded directory stays where it is, for the exposure scan, named in the
  ledger and the round's record with its cause (the machine's, ``killed``, or the void's) and its
  spend (``unread`` where no record holds it), and is in no run set and no cap;
- after the one more go, a trial whose run ended on the machine is ``unscored``; a decomposition
  that spent its call and left no run has nothing to count, and stops the round for a person
  (exit 77, naming the trial, its directory, its cause and its spend), until a restart that names
  the trial sets the directory aside as the person's act and decomposes afresh;
- a directory whose records show no call and no session (the parameters recorded, nothing else)
  is set aside, named in the ledger with what it held, and made again in a fresh one, once per
  trial and free; a second stops the round for a person, as above;
- before a directory is left behind, what the core's commands do first with one a killed
  decomposition left is done: the credential files of its sessions no process runs as are
  removed, and a plan review session left running is stopped, its streams scanned for the
  held-out canaries; one that showed one stops the round (a restart does it first, above);
- any other end is the run's own, and is assembled as it is: its answer is the one file of the
  task's answer name directly inside the module directory its own recorded plan names; a draw
  whose record excludes it for an instrument's fault (by its reason's field alone,
  :mod:`.harness_round_reruns`) is named on an ``excluded`` line and run once more into a fresh
  directory with the same seed, the trial's one more go of the machine's rule one per trial;
- a trial's directory reached through a link at any part of its path is never read or touched:
  the round is refused (``run_dir_linked``).

**What it writes:** the run set and the trial records of each tier, ``<tier>.runs.json`` and
``<tier>.trials.jsonl``, the visible tier's in the round's output directory and the protected
tiers' beneath the withheld root; one combined run set of every tier beneath the withheld root,
for ``physgate baseline run``; the round's record beneath the withheld root (the version, the
check record's and the parameters' digests, the protected tiers' digests, every trial's seed,
run, total and outcome, the superseded and set-aside runs, the pins the runs share, the
register's head before and after, and how many of each tier's trials give the baseline no figure);
and in the output directory a copy of it with counts and digests only: of a protected tier, how
many trials it has and how many are assembled, and nothing else. A trial that gives no figure is
stated so in one recorded form, ``no_figure`` (why, read from the run's own records, and the
refusal in words), and never blocks its pair: the cap rule takes the largest figure among the
same task's other trials, else the middle figure of the cell. So a complete round ends ``done``
wherever a trial of the same tier gives a figure, and ``done_without_caps`` (exit 3) only where a
tier has a no-figure trial and no figure at all. It writes no line of the register.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from physgate.evaluation.baseline.record import VERSION_TIERS
from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round_reruns import reason_field, rerun_cause
from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.observe.cost import DatedSheet, price_run
from physgate.evaluation.observe.manifest import manifest_id_of, read_run_events
from physgate.evaluation.per_role.arms.compare import (
    ENDED_STEPS,
    ComparisonError,
    harness_total,
    next_step,
)
from physgate.evaluation.per_role.arms.harness import extract, planned_module_dirs
from physgate.evaluation.per_role.assemble import (
    INFRASTRUCTURE_CAUSES,
    INFRASTRUCTURE_HALTS,
    ExcludedTrial,
    TrialExcludedError,
    decomposition_cause,
    harness_ended_by_infrastructure,
    harness_trial,
    machine_end,
)
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.report import TrialRecord
from physgate.evaluation.tiers.canaries import store_canaries
from physgate.evaluation.tiers.checks import check_path
from physgate.evaluation.tiers.manifest import TierSet, read_version
from physgate.evaluation.tiers.store import (
    leftover_refusal,
    protected_tier_refusal,
    role_root,
    running_session,
    spelling_refusal,
    version_dir,
    withheld_refusal,
    withheld_root,
    work_refusal,
)
from physgate.evaluation.tiers.task import (
    PROTECTED_TIERS,
    Role,
    Task,
    canonical_json,
    id_digest,
    parse_task,
)
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.common import utc_now, utc_stamp
from physgate.orchestrator.credentials import SECRET_VARIABLE
from physgate.orchestrator.decomposition_review import stop_left_review
from physgate.orchestrator.design_rounds import journal_spend, rounds_on_the_limit
from physgate.orchestrator.events import (
    Event,
    Halted,
    LeftoverRead,
    Resumed,
    TokensUsed,
    parse_events,
)
from physgate.orchestrator.exceptions import OrchestratorError, RunStateError
from physgate.orchestrator.params_record import RECORD_NAME as PARAMS_RECORD
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.replay import replay
from physgate.orchestrator.review_root_record import RECORD_NAME as REVIEW_ROOT_RECORD
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.orchestrator.session_ends import open_sessions
from physgate.orchestrator.stop_signals import remove_left_credentials
from physgate.orchestrator.usage_limit import UsageLimit, resume_after, resume_refusal, stamped
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT, limit_wait
from physgate.reviewers.exceptions import ReviewRootError
from physgate.reviewers.places import require_review_root, review_root_path
from physgate.toolenv.exceptions import ToolEnvironmentError

#: Beneath the role's withheld root: every round's own directory.
HARNESS_ROUNDS = "harness"
LEDGER = "ledger.jsonl"
ROUND_RECORD = "round.json"
COMBINED = "all.runs.json"
#: Inside a trial's run directory: the target's clone and the run's review root.
TARGET = "target"
REVIEW = "review"
LEDGER_FORMAT = 1
#: Beneath the round's directory: the lock one driver holds for its life.
LOCK = "driver.lock"
#: The tier whose run set and records lie in the output directory; the others' are withheld.
VISIBLE = "visible"
#: Of what the census holds equal across a tier's runs (:data:`DRIFT`): what a run takes from its
#: parameters as they are, held at a restart by their digest.
FROM_THE_PARAMETERS: tuple[str, ...] = (
    "models.decomposition",
    "models.roles",
    "models.reviewers",
    "effort",
    "max_output_tokens",
    "thinking_display",
    "bounds",
    "token_ceiling",
    "network",
    "held_out_sha256",
)
#: ... and what is each trial's own: its brief (held by the round's order) and the target's
#: commit (held by the inputs).
THE_TRIAL_S_OWN: tuple[str, ...] = ("brief_sha256", "target_head")
#: The rest of it the command measures afresh for every run: measured as the round starts,
#: recorded in its ledger's first line, and held at every restart, so drift is refused then and
#: not after the round is spent at the census. Read from the census's own list.
PINNED: tuple[str, ...] = tuple(
    name for name in DRIFT if name not in FROM_THE_PARAMETERS + THE_TRIAL_S_OWN
)

Tier = Literal["visible", "validation", "held_out"]
#: How a round left off: every trial assembled (and whether every one gives the baseline its
#: cap), waiting for the account's usage limit, or waiting for a person (a refused credential
#: to replace, or a word on a trial's directory).
Status = Literal[
    "done", "done_without_caps", "trial_assembled", "waiting_for_limit", "waiting_for_a_person"
]
#: The status the command exits with while the round waits for a person: a refused credential
#: to replace, or a trial's directory a restart naming the trial sets aside.
EXIT_WAITING_FOR_A_PERSON = 77
#: The status the command exits with once every trial is assembled but a tier with a trial that
#: gives no figure has no figure at all: the cap rule has nothing to give such a trial's pair.
EXIT_DONE_WITHOUT_CAPS = 3
#: The cause a refused credential is recorded under, as a halt's reason and a call's cause.
CREDENTIAL_REFUSED = "credential_refused"
#: The cause the account's usage limit is recorded under, as a halt's reason and a call's cause.
USAGE_LIMIT = "usage_limit"
#: The least a round waiting for the usage limit says to wait: where the instant after which it
#: goes on is already past (the reset the client gave passed before the halt was read) or none
#: was read, the command says this long from now, so a wrapper that sleeps until the instant it
#: is told never starts again at once against an account that still refuses.
LIMIT_WAIT_FLOOR = timedelta(minutes=5)
#: The cause of a decomposition that spent its call and left no run, where no void is recorded.
KILLED = "killed"
#: The scorer: the task and the answer's path; the score.
Scorer = Callable[[Task, Path], Mapping[str, Any]]


class RoundError(PerRoleError):
    """The round is refused or stopped, for a reason it names: never a task's content."""


@dataclass(frozen=True)
class Decompose:
    """One ``physgate decompose``, as its command line names it."""

    brief: Path
    seed: int
    run_id: str
    params: Path
    target: Path
    run_dir: Path
    install: Path
    review_root: Path
    #: Where the command's output goes, beneath the withheld root.
    log: Path


@dataclass(frozen=True)
class Drive:
    """One ``physgate run`` (or ``resume``), as its command line names it."""

    resume: bool
    run_dir: Path
    target: Path
    install: Path
    review_root: Path
    #: The person's word that the account's usage limit reset (``--limit-reset``).
    limit_reset: bool
    log: Path
    #: The person's word that the refused credential the run halted on was replaced
    #: (``--credential-replaced``).
    credential_replaced: bool = False


class Driver(Protocol):
    """Decomposes and drives one harness run: the command's exit status, nothing else."""

    def pins(self, inputs: Inputs) -> dict[str, Any]:
        """The harness checkout and every :data:`PINNED` field the round's runs would be made on."""
        ...

    def decompose(self, call: Decompose) -> int:
        """Make the run's one call and start it."""
        ...

    def drive(self, call: Drive) -> int:
        """Drive the run, or take it over and drive it."""
        ...


@contextlib.contextmanager
def _output_to(log: Path) -> Iterator[None]:
    """Everything this process and its children print, into ``log``, a new file or appended.

    Both the descriptors and Python's streams: a child the command starts writes to the former.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(log, flags, 0o600)
    saved = (os.dup(1), os.dup(2))
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        with (
            os.fdopen(os.dup(fd), "w", buffering=1) as text,
            contextlib.redirect_stdout(text),
            contextlib.redirect_stderr(text),
        ):
            yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for one in (*saved, fd):
            os.close(one)


@dataclass(frozen=True)
class CommandDriver:
    """The ``physgate`` command itself, called in this process, its output kept beneath the root.

    ``registrations`` is for tests; the command runs with the orchestrator's defaults.
    """

    registrations: Any = None

    def pins(self, inputs: Inputs) -> dict[str, Any]:
        """The checkout this process runs from, and every :data:`PINNED` field a run would record.

        Each measured as the command measures it for a run's record, by the same functions, from
        the round's parameters: the run's directory and target a tool environment may not lie in
        are the run root and the target the trials are cloned from.

        Raises:
            RoundError: a field the census holds equal that nothing here measures.
        """
        from physgate.hooks.settings import session_tool_search
        from physgate.orchestrator import binaries, git, role_python, run_config, tool_environment
        from physgate.orchestrator.decompose import binary_version
        from physgate.orchestrator.dispatch import probe_interpreter
        from physgate.orchestrator.invocation import claude_binary, session_python_bytecode

        params = json.loads(inputs.params.read_bytes())
        harness = run_config.harness_root()
        binary = claude_binary()

        def interpreter() -> Any:  # noqa: ANN401 - a record's dump
            named = params.get("role_python")
            if named is None:
                return None
            measured = role_python.measure(named, probe=probe_interpreter, harness=harness)
            return measured.model_dump(mode="json")

        def tools() -> Any:  # noqa: ANN401 - a record's dump
            named = params.get("tool_environment")
            if named is None:
                return None
            forbidden = tool_environment.forbidden_places(
                harness=harness,
                install=None,
                run_dir=Path(os.path.realpath(inputs.run_root)),
                target=inputs.target_from,
            )
            return tool_environment.measure_named(named, forbidden=forbidden).model_dump(
                mode="json"
            )

        def servers() -> Any:  # noqa: ANN401 - a record's dump
            if params.get("tool_environment") is None:
                return None
            return tool_environment.recorded_servers().model_dump(mode="json")

        measures: dict[str, Callable[[], Any]] = {
            "claude_version": lambda: binary_version(binary),
            "binary": lambda: binaries.measure(binary).model_dump(mode="json"),
            "git_binary": lambda: git.harness_git().model_dump(mode="json"),
            "role_python": interpreter,
            "tool_environment": tools,
            "tool_servers": servers,
            "endpoint": lambda: run_config.endpoint_of(os.environ.get("ANTHROPIC_BASE_URL")),
            "tool_search": session_tool_search,
            "python_bytecode": session_python_bytecode,
        }
        pins = {"harness": run_config.harness_state(harness).model_dump(mode="json")}
        for name in PINNED:
            if name not in measures:
                msg = f"the census holds {name} equal across a tier's runs, and nothing measures it"
                raise _refuse("pins_unreadable", msg, field=name)
            pins[name] = measures[name]()
        return pins

    def decompose(self, call: Decompose) -> int:
        """``physgate decompose`` with the trial's brief, seed, run id and places."""
        argv = [
            "decompose",
            str(call.brief),
            "--seed",
            str(call.seed),
            "--run-id",
            call.run_id,
            "--params",
            str(call.params),
            "--target",
            str(call.target),
            "--run-dir",
            str(call.run_dir),
            "--install",
            str(call.install),
            "--review-root",
            str(call.review_root),
        ]
        return self._main(argv, call.log)

    def drive(self, call: Drive) -> int:
        """``physgate run``, or ``physgate resume`` with the person's word on the limit if given."""
        argv = [
            "resume" if call.resume else "run",
            "--run-dir",
            str(call.run_dir),
            "--target",
            str(call.target),
            "--install",
            str(call.install),
            "--review-root",
            str(call.review_root),
        ]
        if call.resume and call.limit_reset:
            argv.append("--limit-reset")
        if call.resume and call.credential_replaced:
            argv.append("--credential-replaced")
        return self._main(argv, call.log)

    def _main(self, argv: list[str], log: Path) -> int:
        from physgate.cli import main  # the composition root, imported when a trial runs

        with _output_to(log):
            try:
                return main(argv, self.registrations)
            except SystemExit as exc:  # argparse's refusal of a command line
                return exc.code if isinstance(exc.code, int) else 2


# The ledger: appended, synced, never rewritten. -------------------------------------------


def _append(ledger: Path, line: Mapping[str, Any]) -> None:
    """Append ``line`` to the ledger and sync it before anything it names is done."""
    data = canonical_json(dict(line))  # one line, its newline included
    new = not ledger.exists()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(ledger, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)
    if new:
        _sync_directory(ledger.parent)


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_ledger(ledger: Path) -> list[dict[str, Any]]:
    """The ledger's whole lines; a last line cut off by a kill is dropped from the file.

    A line is written before the step it names, and the step is taken only once the write
    returned, so a cut line's step was never taken.

    Raises:
        RoundError: a whole line is not a ledger line.
    """
    data = ledger.read_bytes()
    if data and not data.endswith(b"\n"):
        whole = data[: data.rfind(b"\n") + 1]
        with ledger.open("r+b") as handle:
            handle.truncate(len(whole))
            handle.flush()
            os.fsync(handle.fileno())
        data = whole
    lines = []
    for number, raw in enumerate(data.splitlines(), 1):
        try:
            line = json.loads(raw)
        except ValueError:
            line = None
        if not isinstance(line, dict) or not isinstance(line.get("kind"), str):
            msg = f"line {number} of the round's ledger is not a ledger line"
            raise RoundError(msg, refused_because="ledger_unreadable")
        lines.append(line)
    return lines


def _write_whole(path: Path, data: bytes) -> None:
    """Put ``data`` at ``path`` whole: written apart, synced, then renamed over it."""
    part = path.with_name(f".{path.name}.part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(part, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(part, path)


# The version's tasks: this module's one reader of the store. --------------------------------


@dataclass(frozen=True)
class _Version:
    manifest: TierSet
    #: Each tier's tasks by their brief's digest.
    tasks: dict[str, dict[str, Task]]
    #: Every canary of the version's protected tasks and of every role's root in the store.
    canaries: frozenset[str]


def _version_tasks(store: Path, role: Role, version: str) -> _Version:
    """The version held to its manifest, its tasks by tier and brief, and the canaries to look for.

    Raises:
        RoundError: a task cannot be read, two share a brief, or a canary list cannot be read;
            the tier is said, never a task.
    """
    directory = version_dir(store, role, version)
    try:
        manifest = read_version(directory)
    except PerRoleError as exc:
        msg = f"the version {version[:8]} is not what its manifest says"
        raise RoundError(msg, refused_because="version_unknown") from exc
    tasks: dict[str, dict[str, Task]] = {}
    canaries: set[str] = set()
    briefs: set[str] = set()
    for tier in VERSION_TIERS:
        found: dict[str, Task] = {}
        here = directory / tier
        try:
            entries = sorted(p for p in here.iterdir() if p.is_dir() and not p.is_symlink())
            for entry in entries:
                task = parse_task((entry / "task.json").read_bytes())
                brief = hashlib.sha256(task.brief.encode()).hexdigest()
                if brief in briefs:
                    msg = f"two tasks of the version share a brief (one in the {tier} tier)"
                    raise RoundError(msg, refused_because="briefs_shared", tier=tier)
                briefs.add(brief)
                found[brief] = task
                if task.canary is not None:
                    canaries.add(task.canary)
        except (OSError, PerRoleError) as exc:
            if isinstance(exc, RoundError):
                raise
            # The error may name the task; only its tier is said.
            msg = f"a task of the {tier} tier cannot be read"
            raise RoundError(msg, refused_because="tier_unreadable", tier=tier) from None
        tasks[tier] = found
    try:
        canaries |= set(store_canaries(store))
    except (OSError, PerRoleError):
        msg = "the store's canary lists cannot all be read, so no run can be held to them"
        raise RoundError(msg, refused_because="canary_list_unreadable") from None
    return _Version(manifest=manifest, tasks=tasks, canaries=frozenset(canaries))


# The inputs, and the refusals before anything. ----------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """What a round is started with; given again, the same, to resume it."""

    store: Path
    role: Role
    version: str
    tiers: tuple[Tier, ...]
    trials: int
    seed_base: int
    params: Path
    run_root: Path
    target_from: Path
    install: Path
    prices: DatedSheet
    out: Path
    #: The first so many tasks of each named tier, in the round's order; ``None`` for all.
    tasks: int | None = None
    #: The order's seed, for the registered order of one cell: its (id digest, trial) pairs
    #: sorted and shuffled once by ``random.Random("<seed>:order:<suite>")``, trial ``n`` of a task
    #: seeded ``seed base + n``; ``None`` for the driver's own order.
    order_seed: int | None = None


def _refuse(reason: str, msg: str, **context: str) -> RoundError:
    return RoundError(msg, refused_because=reason, **context)


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if done.returncode != 0:
        msg = f"git {args[0] if args else ''} failed"
        raise _refuse("git", msg, error=done.stderr.strip()[-300:])
    return done.stdout


def _target_head(target: Path) -> str:
    """The pristine target's commit, or the round refused.

    Raises:
        RoundError: it is no repository, its worktree is not clean, or its top holds a run's
            configuration.
    """
    if (target / "run.json").exists():
        msg = "the target's top holds a run's configuration; a target is a design repository"
        raise _refuse("target_holds_a_run", msg)
    head = _git("-C", str(target), "rev-parse", "--verify", "HEAD^{commit}").strip()
    if _git("-C", str(target), "status", "--porcelain", "--untracked-files=all").strip():
        msg = "the target's worktree is not clean; every trial clones one commit, as it is"
        raise _refuse("target_not_clean", msg)
    return head


def _register_head(store: Path, role: Role) -> dict[str, Any]:
    """How many lines the role's register holds, and the digest of its last."""
    from physgate.evaluation.tiers.exposure import register_lines

    lines = register_lines(store, role)
    last = None if not lines else hashlib.sha256(canonical_json(lines[-1].model_dump(mode="json")))
    return {"lines": len(lines), "last_sha256": None if last is None else last.hexdigest()}


def _not_from_a_session() -> None:
    """Refuse a round started from inside a harness session, before anything is read or touched.

    Raises:
        RoundError: this process runs inside a session's environment.
    """
    from physgate.evaluation.tiers.exposure import ExposureError, _refuse_inside_a_session

    try:
        _refuse_inside_a_session()
    except ExposureError as exc:
        raise _refuse(
            "inside_a_session", f"a round is never started from a session: {exc}"
        ) from None


def _checked(
    inputs: Inputs, driver: Driver
) -> tuple[_Version, frozenset[str], str, dict[str, Any], list[_Planned], dict[str, Any]]:
    """Every refusal of the start that reads the store, the register or the machine, in order.

    Returns the version's tasks, the flagged held-out tasks, the check record's digest, the
    inputs as the ledger holds them, the round's order and the pins measured now.

    Raises:
        RoundError: a refusal, named by its reason.
    """
    found, flagged, check_sha256 = _refusals(inputs)
    target_head = _target_head(inputs.target_from)
    given = _inputs_record(inputs, target_head, check_sha256)
    order = _order(inputs, found, flagged)
    if not order:
        raise _refuse("nothing_to_run", "the named tiers hold no task the round runs")
    return found, flagged, check_sha256, given, order, _measured(driver, inputs)


def _refusals(inputs: Inputs) -> tuple[_Version, frozenset[str], str]:
    """Everything that refuses the round before a trial starts, read now.

    Returns the version's tasks, the held-out tasks the check flagged (by their brief's digest),
    and the check record's digest.

    Raises:
        RoundError: a refusal, named by its reason; or the register cannot be read whole.
    """
    from physgate.evaluation.tiers.exposure import exposed_versions, run_roots, versions
    from physgate.evaluation.tiers.measure import checked

    store, role = inputs.store, inputs.role
    _not_from_a_session()
    living = running_session(store, role)
    if living is not None:
        msg = f"{living}: no round starts while a session left in the work root still runs"
        raise _refuse("session_lives", msg)
    refusal = leftover_refusal(store)
    if refusal is not None:
        raise _refuse(refusal[0], refusal[1])
    try:
        known = versions(store, role)
        exposed = exposed_versions(store, role)
        roots = [Path(os.path.realpath(r)) for r in run_roots(store, role)]
    except PerRoleError as exc:
        reason = exc.context.get("refused_because", "register_unreadable")
        raise _refuse(reason, f"the register cannot be read whole: {exc}") from None
    if inputs.version not in known:
        raise _refuse("version_unknown", f"the role has no version {inputs.version[:8]}")
    if inputs.version in exposed:
        msg = f"the version {inputs.version[:8]} is marked exposed; nothing is measured on it"
        raise _refuse("version_exposed", msg)
    try:
        record = checked(store, role, known[inputs.version])
    except PerRoleError as exc:
        raise _refuse(exc.context.get("refused_because", "held_out_unchecked"), str(exc)) from None
    _require_run_root_spelt(inputs.run_root)
    run_root = Path(os.path.realpath(inputs.run_root))
    if run_root not in roots:
        msg = "the run root is not one of the role's registered run roots"
        raise _refuse("run_root_not_registered", msg, run_root=str(inputs.run_root))
    _require_reviews_may_run_beneath(run_root)
    out = Path(os.path.realpath(inputs.out))
    for name, place in (("run root", run_root), ("target", inputs.target_from), ("store", store)):
        there = Path(os.path.realpath(place))
        if out == there or there in out.parents:
            # In the run root the exposure scan walks it; in the target or the store it leaves
            # them unclean, and a resume is refused.
            msg = f"the round's output directory lies in its {name}; give it a place of its own"
            raise _refuse("out_misplaced", msg)
    found = _version_tasks(store, role, inputs.version)
    held = found.tasks["held_out"]
    by_digest: dict[str, list[str]] = {}
    for brief, task in held.items():
        by_digest.setdefault(id_digest(task.id), []).append(brief)
    if any(len(by_digest.get(digest, [])) != 1 for digest in record.flagged):
        msg = "the check record flags a task that is not exactly one held-out task of the version"
        raise _refuse("check_record_not_the_tier", msg)
    flagged = frozenset(by_digest[digest][0] for digest in record.flagged)
    _require_params(inputs, found.canaries)
    _target_head(inputs.target_from)
    check_sha256 = hashlib.sha256(check_path(store, role, inputs.version).read_bytes()).hexdigest()
    return found, flagged, check_sha256


def _require_run_root_spelt(run_root: Path) -> None:
    """Refuse a run root that is not its real path spelt as the disk spells each part.

    The core's rule for a run root (:func:`.tiers.exposure.add_run_root`): the hooks match a
    root by its spelling, and every trial's run directory is named beneath the root as given. A
    root reached through a linked parent, or typed in another case on a volume that ignores case,
    would spell its sessions' places otherwise than the run roots that withhold them.

    Raises:
        RoundError: the root is not so spelt, or a directory on its way cannot be listed.
    """
    from physgate.evaluation.tiers.exposure import _spelt_as_its_real_path

    try:
        spelt = _spelt_as_its_real_path(Path(run_root).absolute())
    except OSError:
        spelt = False
    if not spelt:
        msg = (
            "the run root is not its real path spelt as the disk spells it (another case, or a "
            "linked parent): every trial's run directory is named beneath it as it is on disk"
        )
        raise _refuse("run_root_not_spelt_as_on_disk", msg)


def _require_reviews_may_run_beneath(run_root: Path) -> None:
    """Refuse a run root beneath which no trial's review root may lie.

    Each trial reviews inside its own run directory (:data:`REVIEW`), as every measured run does,
    and the core refuses at the run a review root whose path holds a word that would tell a
    reviewer what it reads, or that lies inside a git checkout
    (:func:`physgate.reviewers.places.require_review_root`). Asked here of the place the round's
    first trial reviews in, the round's own name in it a digest: a root the core would refuse
    at every run is refused before anything is made.

    Raises:
        RoundError: the review root of a trial beneath this root would be refused.
    """
    try:
        require_review_root(_run_dir(run_root, "0" * 16, 0, 1) / REVIEW)
    except ReviewRootError as exc:
        if exc.context.get("found"):
            # The words are said, never the path.
            msg = "the run root's path holds a word that would tell a reviewer what it reads"
            raise _refuse("run_root_telltale", msg, found=exc.context["found"]) from None
        msg = "the run root lies inside a git checkout, so no trial's review may run beneath it"
        raise _refuse("run_root_in_a_checkout", msg) from None


def _run_dir(run_root: Path, round_id: str, index: int, attempt: int) -> Path:
    """A trial's run directory: ``<run root>/<round>/<iiii>-<n>``, the root as it really is."""
    return Path(os.path.realpath(run_root)) / round_id / f"{index:04d}-{attempt}"


def _require_params(inputs: Inputs, canaries: frozenset[str]) -> None:
    """Refuse parameters that are not a measured run's on this store.

    Raises:
        RoundError: not reportable, a protected place of the store not withheld, or a canary
            not looked for; places by the store's own words, canaries by count.
    """
    try:
        params = json.loads(inputs.params.read_bytes())
    except (OSError, ValueError):
        raise _refuse("params_unreadable", "the run parameters cannot be read") from None
    if not isinstance(params, dict) or params.get("reportable") is not True:
        msg = "the run parameters are not reportable; a round's runs are measured runs"
        raise _refuse("params_not_reportable", msg)
    held_out = params.get("held_out")
    looked = params.get("held_out_canaries")
    if not (
        isinstance(held_out, list)
        and all(isinstance(h, str) for h in held_out)
        and isinstance(looked, list)
        and all(isinstance(c, str) for c in looked)
    ):
        msg = "the run parameters name their held-out places and canaries as lists of strings"
        raise _refuse("params_unreadable", msg)
    store, role = inputs.store, inputs.role
    others = [r for r in get_args(Role) if r != role and os.path.lexists(role_root(store, r))]
    also = [(store, role), *((store, other) for other in others)]
    places = tuple(held_out)
    for refusal in (
        spelling_refusal(places, also=also),
        withheld_refusal(places, also=also),
        work_refusal(places),
        protected_tier_refusal(places, also=also),
    ):
        if refusal is not None:
            msg = "the run parameters do not withhold the store as every run on it must: "
            raise _refuse(refusal[0], msg + refusal[1])
    missing = canaries - set(looked)
    if missing:
        msg = "the run parameters do not look for every canary of the version and the store"
        raise _refuse("canaries_not_looked_for", msg, missing=str(len(missing)))
    refusal = _whole_root_refusal(params)
    if refusal is not None:
        raise _refuse(refusal[0], refusal[1])


def _whole_root_refusal(params: Mapping[str, Any]) -> tuple[str, str] | None:
    """Why a round of any tier may not run on these parameters' roots withheld whole, or None.

    A round's trials lie beside one another beneath the store's run roots, each holding every
    canary of the store, a plan written from its brief, and its answer. Every measured run, of
    whatever tier, withholds whole exactly the registered run roots of the stores it names, by
    the core's own rule (:func:`.tiers.exposure.run_roots_refusal`), which the core asks again at
    each decomposition and a counted run is held to where it is counted: asked here, a round the
    rule refuses makes nothing. The driver checks the field and never writes it, since the
    parameters are held to their digest. An empty list passes only for a store with no run root,
    and a round's store always has its own.
    """
    from physgate.evaluation.tiers.exposure import run_roots_refusal

    whole = params.get("withheld_whole", [])
    if not (isinstance(whole, list) and all(isinstance(root, str) for root in whole)):
        msg = "the run parameters name the roots they withhold whole as a list of strings"
        return "params_unreadable", msg
    if len(set(whole)) != len(whole):
        # The core's configuration refuses it at the first decomposition, after the round began.
        return "params_unreadable", "the run parameters withhold whole one root twice"
    # Only the two fields the rule reads: the rest of a run's configuration is measured by the
    # command at each decomposition, and is not known before it.
    fields: dict[str, Any] = {
        "held_out": tuple(params.get("held_out") or ()),
        "withheld_whole": tuple(whole),
    }
    return run_roots_refusal(RunConfig.model_construct(**fields), None)


# The round. ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Planned:
    index: int
    tier: Tier
    brief_sha256: str
    trial: int
    seed: int


def _order(inputs: Inputs, found: _Version, flagged: frozenset[str]) -> list[_Planned]:
    if inputs.order_seed is not None:
        return _registered_order(inputs, found, flagged)
    order: list[_Planned] = []
    for tier in VERSION_TIERS:
        if tier not in inputs.tiers:
            continue
        briefs = sorted(b for b in found.tasks[tier] if not (tier == "held_out" and b in flagged))
        if inputs.tasks is not None:
            briefs = briefs[: inputs.tasks]
        for brief in briefs:
            for trial in range(inputs.trials):
                index = len(order)
                order.append(_Planned(index, tier, brief, trial, inputs.seed_base + index))
    return order


def _registered_order(inputs: Inputs, found: _Version, flagged: frozenset[str]) -> list[_Planned]:
    """The registered order of one cell: every (task, trial) pair, shuffled once by a seed string.

    The cell's pairs (a held-out task the check flagged left out) are sorted by the task's id
    digest and the trial, then shuffled once by ``random.Random("<order seed>:order:<suite>")``,
    the suite being ``<role>_<tier>``; trial ``n`` of a task is seeded ``seed base + n``, whatever
    its place. One cell a round: its order, and the raw trial run right after each harness
    trial, are the cell's.

    Raises:
        RoundError: more than one tier named.
    """
    if len(inputs.tiers) != 1:
        msg = "a round in the registered order runs one cell: name one tier"
        raise _refuse("order_one_cell", msg)
    (tier,) = inputs.tiers
    tasks = {
        b: t for b, t in found.tasks[tier].items() if not (tier == "held_out" and b in flagged)
    }
    digests = sorted((id_digest(task.id), brief) for brief, task in tasks.items())
    if inputs.tasks is not None:
        digests = digests[: inputs.tasks]
    pairs = sorted(
        (digest, trial, brief) for digest, brief in digests for trial in range(inputs.trials)
    )
    random.Random(f"{inputs.order_seed}:order:{inputs.role}_{tier}").shuffle(pairs)
    return [
        _Planned(index, tier, brief, trial, inputs.seed_base + trial)
        for index, (_digest, trial, brief) in enumerate(pairs)
    ]


def _inputs_record(inputs: Inputs, target_head: str, check_sha256: str) -> dict[str, Any]:
    """The inputs as the ledger holds them: a resume is held to their digest."""
    return {
        "store": os.path.realpath(inputs.store),
        "role": inputs.role,
        "version": inputs.version,
        "tiers": list(inputs.tiers),
        "trials": inputs.trials,
        "tasks": inputs.tasks,
        "seed_base": inputs.seed_base,
        "params_sha256": hashlib.sha256(inputs.params.read_bytes()).hexdigest(),
        "run_root": os.path.realpath(inputs.run_root),
        "target_from": os.path.realpath(inputs.target_from),
        "target_head": target_head,
        "install": os.path.realpath(inputs.install),
        "prices": inputs.prices.sheet.date,
        "prices_sha256": inputs.prices.sha256,
        "check_sha256": check_sha256,
        # Only where it is given, so a round in the driver's own order is held as it always was.
        **({} if inputs.order_seed is None else {"order_seed": inputs.order_seed}),
    }


#: The ledger's lines that close a trial's attempt without assembling it: superseded (its one
#: more go, or a person's word), set aside with nothing in it, a refused credential, the limit,
#: and a draw whose records say its answer is not to be trusted (run once more).
CLOSING = ("superseded", "left", "credential", "limit", "excluded")


@dataclass
class _Round:
    inputs: Inputs
    driver: Driver
    scorer: Scorer
    sleep: Callable[[float], None]
    now: Callable[[], datetime]
    round_id: str
    place: Path
    ledger: Path
    lines: list[dict[str, Any]]
    order: list[_Planned]
    tasks: dict[str, Task]
    #: The person's word that the usage limit reset, for the one trial and attempt the round
    #: stood waiting at when this process started; ``None`` once used, or for none.
    reset_for: tuple[int, int] | None = None
    #: The trial a person's restart names, whose directory the round sets aside; ``None`` once
    #: used, or for none.
    set_aside_for: int | None = None
    #: The person's word that the refused credential was replaced, for the one trial and attempt
    #: whose run the round stood stopped at on it; ``None`` once used, or for none.
    replaced_for: tuple[int, int] | None = None
    #: Why the round stands waiting, for a person or for the usage limit, for what it prints and
    #: writes in the output directory; ``None`` while it does not.
    waiting: dict[str, Any] | None = None
    #: The one trial a call that names a place of the order assembled, as its sheet says it.
    trial: dict[str, Any] | None = None
    #: What this process has done to each run, so a step that moves nothing is not taken twice.
    acted: set[tuple[Any, ...]] = field(default_factory=set)

    def add(self, line: dict[str, Any]) -> None:
        _append(self.ledger, line)
        self.lines.append(line)

    def of(self, index: int, kind: str) -> list[dict[str, Any]]:
        return [x for x in self.lines if x["kind"] == kind and x.get("index") == index]

    def closing(self, index: int, attempt: int) -> dict[str, Any] | None:
        """The line that closed the trial's attempt without assembling it, if one did."""
        return next(
            (
                x
                for x in self.lines
                if x["kind"] in CLOSING and x.get("index") == index and x.get("attempt") == attempt
            ),
            None,
        )

    def run_dir(self, index: int, attempt: int) -> Path:
        return _run_dir(self.inputs.run_root, self.round_id, index, attempt)

    def run_id(self, index: int, attempt: int) -> str:
        return f"{self.round_id}-{index:04d}-{attempt}"

    def delay(self) -> float:
        """The first registered retry delay, from the parameters every trial is decomposed with."""
        bounds = json.loads((self.place / "params.json").read_bytes()).get("bounds", {})
        delays = bounds.get("infra_retry_delays_s") or []
        return float(delays[0]) if delays else 0.0

    def brief(self, planned: _Planned) -> Path:
        """The trial's brief file beneath the withheld root: the task's brief, byte for byte."""
        path = self.place / "briefs" / f"{planned.index:04d}.md"
        data = self.tasks[planned.brief_sha256].brief.encode()
        if path.exists():
            if path.read_bytes() != data:
                msg = "a trial's brief file is not its task's brief"
                raise _refuse("brief_changed", msg, index=str(planned.index))
            return path
        path.parent.mkdir(mode=0o700, exist_ok=True)
        _write_whole(path, data)
        return path


def run_round(
    inputs: Inputs,
    *,
    driver: Driver,
    scorer: Scorer,
    resume: bool = False,
    limit_reset: bool = False,
    set_aside: int | None = None,
    credential_replaced: bool = False,
    only: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> tuple[Status, dict[str, Any]]:
    """Run, or go on with, the round ``inputs`` name; how it left off and its counts and digests.

    ``limit_reset`` is a person's word that the account's usage limit reset, for the wait the
    round stands at, held to the core's rule for a run's (:func:`resume_refusal`); ``set_aside``
    names the trial the round stands stopped at for a person, whose directory is then set aside on
    the person's word. Either given to a round that stands at no such wait is refused, before
    anything is made. ``credential_replaced`` is a person's word that the refused credential the
    round stands stopped at was replaced with another secret: the trial's halted run is resumed
    with that word (``physgate resume --credential-replaced``), which records both fingerprints;
    given to a round that stands at no refused credential, it is refused before anything is
    made. ``only`` names one place of the round's order: the round takes that trial on until it
    is assembled (or waits) and stops there, ``trial_assembled``, its one-entry run set written,
    so a raw trial can run right after it; only the first place not yet assembled may be named,
    or one already assembled (which only says it again). ``now`` is the clock a limit's wait is
    read against.

    Raises:
        RoundError: the round is refused, or stopped at a step it names; nothing of a task.
    """
    if not resume and only not in (None, 0):
        # A fresh round has assembled nothing: its first place is the only one it may take on.
        msg = "only the first place of the order not yet assembled may be taken on"
        raise _refuse("only_out_of_order", msg, only=str(only), first="0")
    if not resume and (set_aside is not None or limit_reset or credential_replaced):
        # A fresh round stands at no wait: a person's word for one is refused before anything.
        word = (
            "set_aside"
            if set_aside is not None
            else "limit_reset"
            if limit_reset
            else "credential_replaced"
        )
        msg = "a fresh round stands at no wait a person's word is for"
        raise _refuse(f"{word}_not_waiting", msg)
    out = inputs.out
    withheld = withheld_root(inputs.store, inputs.role) / HARNESS_ROUNDS
    if resume:
        # What the round's own earlier process left is dealt with first, before any refusal can
        # end the start (the register's above all, which now finds a left review's exposure
        # itself): never from a session, and only once the round is found and its lock held.
        _not_from_a_session()
        round_id, place = _found(out, withheld)
        lock, dead = _locked(place)
        try:
            _what_its_earlier_process_left(place, round_id)
            found, flagged, check_sha256, given, order, pins = _checked(inputs, driver)
        except BaseException:
            _release(lock, claimed=False)
            raise
    else:
        found, flagged, check_sha256, given, order, pins = _checked(inputs, driver)
        _require_clean(pins)
        # Made before anything else, and only if it is not there: two rounds started into one
        # output directory at once are one round and a refusal, and the refused one made nothing.
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            out.mkdir(mode=0o700)
        except FileExistsError:
            msg = "the round's output directory exists; each round gets a directory of its own"
            raise _refuse("out_exists", msg, out=str(out)) from None
        round_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
        place = withheld / round_id
        withheld.mkdir(mode=0o700, exist_ok=True)
        place.mkdir(mode=0o700)
        lock, dead = _locked(place)
    claimed = [False]
    try:
        if not resume:
            # First, so a round killed at any later step is found again by its output directory.
            _write_whole(out / ROUND_RECORD, canonical_json({"format": 1, "round": round_id}))
        lines = _held_to(place, round_id, given, order, pins) if resume else []
        if not lines:
            _require_clean(pins)
        ctx = _Round(
            inputs=inputs,
            driver=driver,
            scorer=scorer,
            sleep=sleep,
            now=now,
            round_id=round_id,
            place=place,
            ledger=place / LEDGER,
            lines=lines,
            order=order,
            tasks={b: t for tier in found.tasks.values() for b, t in tier.items()},
        )
        words = _Words(limit_reset, set_aside, credential_replaced, only)
        status = _go(ctx, found, given, pins, dead, lock, claimed, words)
    except BaseException as exc:
        # A process that ends as it should leaves no pid behind; a kill leaves its own.
        _release(lock, claimed=claimed[0] and isinstance(exc, Exception))
        raise
    _release(lock, claimed=claimed[0])
    return status, _summary(ctx, done=status in ("done", "done_without_caps"))


@dataclass(frozen=True)
class _Words:
    """A person's words a restart is given: each for the one wait the round stands at."""

    limit_reset: bool = False
    set_aside: int | None = None
    credential_replaced: bool = False
    #: The one place of the order this call takes on, or ``None`` for every trial.
    only: int | None = None


def _go(
    ctx: _Round,
    found: _Version,
    given: dict[str, Any],
    pins: dict[str, Any],
    dead: int | None,
    lock: int,
    claimed: list[bool],
    words: _Words,
) -> Status:
    """The round, once its lock is held and its ledger read: every trial in order, then its sets."""
    inputs = ctx.inputs
    if not ctx.lines:
        # The parameters every trial is decomposed with, beneath the withheld root.
        shutil.copyfile(inputs.params, ctx.place / "params.json")
    copied = hashlib.sha256((ctx.place / "params.json").read_bytes()).hexdigest()
    if copied != given["params_sha256"]:
        msg = "the round's copy of its parameters is not the file it was started with"
        raise _refuse("params_changed", msg)
    protected_named = any(tier in PROTECTED_TIERS for tier in inputs.tiers)
    current: list[_Planned | None] = [None]
    try:
        # Read before this process acts: what the round stood waiting at when it was started; its
        # directory first held to be the round's own, since reading a run's record may cut it.
        standing = _standing(ctx)
        if standing is not None:
            at, last, _closing = standing
            _require_its_own(ctx, at.index, last, ctx.run_dir(at.index, last))
        set_aside, limit_reset = words.set_aside, words.limit_reset
        stopped = _stopped_for_a_person_at(ctx)
        if set_aside is not None and set_aside != stopped:
            msg = (
                "the trial the restart names is not the one the round stands stopped at for a "
                "person; nothing is set aside"
            )
            raise _refuse("set_aside_not_waiting", msg, index=str(set_aside))
        ctx.set_aside_for = set_aside
        if limit_reset:
            ctx.reset_for = _waiting_at_start(ctx)
            if ctx.reset_for is None:
                msg = "the round stands waiting for no usage limit; the word is for none"
                raise _refuse("limit_reset_not_waiting", msg)
        if words.credential_replaced:
            waiting_on = _credential_at_start(ctx)
            if waiting_on is None:
                msg = "the round stands stopped at no refused credential; the word is for none"
                raise _refuse("credential_replaced_not_waiting", msg)
            ctx.replaced_for = waiting_on
        if not ctx.lines:
            header = {
                "kind": "round",
                "format": LEDGER_FORMAT,
                "round": ctx.round_id,
                "inputs": given,
                "inputs_sha256": hashlib.sha256(canonical_json(given)).hexdigest(),
                "pins": pins,
                "protected_sha256": {
                    tier: getattr(found.manifest, tier).sha256 for tier in PROTECTED_TIERS
                },
                "order": [vars(p) for p in ctx.order],
                "register_before": _register_head(inputs.store, inputs.role),
                "started": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            ctx.add(header)
            _write_whole(inputs.out / ROUND_RECORD, canonical_json(_summary(ctx, done=False)))
        if dead is not None:
            ctx.add({"kind": "lock_taken_over", "pid": dead})
        _claim(lock)
        claimed[0] = True
        (ctx.place / "logs").mkdir(mode=0o700, exist_ok=True)
        for planned in _these(ctx, words.only):
            current[0] = planned
            status = _trial(ctx, planned)
            if status == "waiting_for_limit":
                _said_wait(ctx, planned)
            if status in ("waiting_for_limit", "waiting_for_a_person"):
                # Said where a wrapper reads it, as well as printed: which trial, and until when.
                _write_whole(inputs.out / ROUND_RECORD, canonical_json(_summary(ctx, done=False)))
                return status
            _one_entry(ctx, planned)
        current[0] = None
        if words.only is not None:
            # One trial of the order, named: assembled, its set written, and said where it lies
            # and whether its raw pair runs now; the round goes on later, unless it was the last.
            ctx.trial = _sheet(ctx, ctx.order[words.only])
            if len(_assembled(ctx)) < len(ctx.order):
                _write_whole(inputs.out / ROUND_RECORD, canonical_json(_summary(ctx, done=False)))
                return "trial_assembled"
        _outputs(ctx)
    except RoundError:
        raise
    except Exception as exc:
        stopped_at = current[0]
        tier = None if stopped_at is None else stopped_at.tier
        if tier in PROTECTED_TIERS or (tier is None and protected_named):
            # An error of a protected trial, or of the protected tiers' records, may name a task;
            # its tier and its kind alone are said.
            where = "trial" if stopped_at is not None else "round's records"
            msg = f"a {tier or 'protected'} {where} stopped on an error ({type(exc).__name__})"
            context: dict[str, str] = {} if tier is None else {"tier": tier}
            if stopped_at is not None:
                context["index"] = str(stopped_at.index)
            raise RoundError(msg, **context) from None
        raise
    return "done_without_caps" if _no_cap_in_the_cell(ctx) else "done"


def _these(ctx: _Round, only: int | None) -> list[_Planned]:
    """The trials this call takes on: every one in order, or the one place it names.

    Raises:
        RoundError: the place is not in the order, or an earlier place is not yet assembled.
    """
    if only is None:
        return ctx.order
    if not 0 <= only < len(ctx.order):
        raise _refuse(
            "only_not_in_the_order", "the round's order has no such place", only=str(only)
        )
    first = next((p.index for p in ctx.order if not ctx.of(p.index, "assembled")), None)
    if not ctx.of(only, "assembled") and only != first:
        msg = "only the first place of the order not yet assembled may be taken on"
        raise _refuse("only_out_of_order", msg, only=str(only), first=str(first))
    return [ctx.order[only]]


#: Beneath the round's directory (a protected tier) or its output directory (the visible tier):
#: each trial's one-entry run set and its sheet, written once the trial is assembled.
TRIALS = "trials"


def _sheet(ctx: _Round, planned: _Planned) -> dict[str, Any]:
    """What a raw trial's rule reads of an assembled harness trial: never an outcome or a score."""
    line = next(x for x in ctx.lines if x["kind"] == "assembled" and x["index"] == planned.index)
    excluded = line["record"].get("reason") if line["outcome"] == "excluded" else None
    where = ctx.inputs.out if planned.tier == VISIBLE else ctx.place
    return {
        "format": 1,
        "round": ctx.round_id,
        "index": planned.index,
        "tier": planned.tier,
        "suite": f"{ctx.inputs.role}_{planned.tier}",
        # The arm the trial is of: every trial of this driver's is the harness as measured; an
        # arm with a part taken away would name itself here, and never take a raw pair.
        "arm": "harness",
        "trial": planned.trial,
        "seed": planned.seed,
        "attempt": line["attempt"],
        "run_id": line["run_id"],
        "run_dir": line["run_dir"],
        "harness_total": line["harness_total"],
        "no_figure": line.get("no_figure"),
        "raw_pair": "now" if line["harness_total"] is not None else "at_cell_end",
        "rerun_of": line.get("rerun_of"),
        "excluded": excluded,
        "class": None if excluded is None else rerun_cause(excluded, "harness"),
        "runs": str(where / TRIALS / f"{planned.index:04d}.runs.json"),
    }


def _one_entry(ctx: _Round, planned: _Planned) -> None:
    """Write the assembled trial's one-entry run set and its sheet; the same bytes again after."""
    sheet = _sheet(ctx, planned)
    trials = Path(sheet["runs"]).parent
    trials.mkdir(mode=0o700, exist_ok=True)
    entry = {"run_dir": sheet["run_dir"], "trial": planned.trial}
    runs = RunSet.model_validate_json(json.dumps({"format": 1, "trials": [entry]}))
    _write_whole(Path(sheet["runs"]), runs.model_dump_json().encode())
    _write_whole(trials / f"{planned.index:04d}.trial.json", canonical_json(sheet))


# The lock and the pins. ---------------------------------------------------------------------


def _locked(place: Path) -> tuple[int, int | None]:
    """The round's lock, held exclusively, and the pid a driver that died holding it left.

    Taken before the ledger is read. The kernel's lock is the gate: a driver whose process is
    gone holds none, so its lock is free and the pid it left in the lock's file names it.

    Raises:
        RoundError: another driver holds the round now; nothing was written.
    """
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(place / LOCK, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        holder = _holder(fd)
        os.close(fd)
        named = "" if holder is None else f" (pid {holder})"
        msg = f"another driver holds this round{named}; one driver drives a round at a time"
        raise _refuse("round_held", msg) from None
    return fd, _holder(fd)


def _holder(fd: int) -> int | None:
    raw = os.pread(fd, 64, 0).strip()
    return int(raw) if raw.isdigit() else None


def _claim(fd: int) -> None:
    """Name this process in the lock's file, once the round's ledger says who held it before."""
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
    os.fsync(fd)


def _release(fd: int, *, claimed: bool) -> None:
    """Let the lock go; a driver that ends as it should takes its pid out of the lock's file."""
    try:
        if claimed:
            os.ftruncate(fd, 0)
            os.fsync(fd)
    finally:
        os.close(fd)


def _measured(driver: Driver, inputs: Inputs) -> dict[str, Any]:
    """The harness checkout and every pinned field, as the driver measures them.

    Raises:
        RoundError: they cannot be measured.
    """
    try:
        pins = driver.pins(inputs)
    except RoundError:
        raise
    except (OrchestratorError, PerRoleError, ToolEnvironmentError, OSError, ValueError) as exc:
        msg = f"the harness, its client and its tools cannot be measured ({type(exc).__name__})"
        raise _refuse("pins_unreadable", msg) from None
    measured: dict[str, Any] = json.loads(json.dumps(pins, sort_keys=True))
    return measured


def _require_clean(pins: dict[str, Any]) -> None:
    """Refuse a round on a checkout that is not a clean commit: its runs are measured runs.

    Raises:
        RoundError: no commit, or anything not committed.
    """
    harness = pins.get("harness") or {}
    if harness.get("commit") is None or harness.get("clean") is not True:
        msg = "a measured round starts only from a clean checkout; commit the changes first"
        raise _refuse("harness_not_clean", msg)


def _pins_differ(recorded: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """What differs between two measurements, each field by its name (``harness.commit``)."""
    changed: list[str] = []
    for key in sorted(set(recorded) | set(now)):
        was, is_ = recorded.get(key), now.get(key)
        if was == is_:
            continue
        if isinstance(was, dict) and isinstance(is_, dict):
            changed += [
                f"{key}.{k}" for k in sorted(set(was) | set(is_)) if was.get(k) != is_.get(k)
            ]
        else:
            changed.append(key)
    return changed


def _found(out: Path, withheld: Path) -> tuple[str, Path]:
    """The round ``out`` names, and its directory beneath the withheld root.

    Raises:
        RoundError: ``out`` holds no round, or its directory is gone.
    """
    try:
        summary = json.loads((out / ROUND_RECORD).read_bytes())
        round_id = summary["round"]
    except (OSError, ValueError, KeyError, TypeError):
        msg = "the output directory holds no round to resume"
        raise _refuse("no_round", msg, out=str(out)) from None
    if not (isinstance(round_id, str) and round_id.isalnum()):
        raise _refuse("no_round", "the output directory names no round", out=str(out))
    place = withheld / round_id
    if not place.is_dir():
        raise _refuse("round_gone", "the round's directory is not beneath the withheld root")
    return round_id, place


def _held_to(
    place: Path,
    round_id: str,
    given: dict[str, Any],
    order: list[_Planned],
    pins: dict[str, Any],
) -> list[dict[str, Any]]:
    """The round's ledger, held to the inputs, the order and the pins it was started with.

    Raises:
        RoundError: the ledger is not the round's, or the inputs, the order or the pins differ.
    """
    ledger = place / LEDGER
    # A round killed before its first line took no step: it begins again from its first line.
    lines = _read_ledger(ledger) if ledger.is_file() else []
    if not lines:
        return lines
    if lines[0].get("kind") != "round" or lines[0].get("round") != round_id:
        raise _refuse("ledger_unreadable", "the round's ledger does not begin with its round")
    header = lines[0]
    if header.get("inputs_sha256") != hashlib.sha256(canonical_json(given)).hexdigest():
        changed = sorted(k for k in given if header.get("inputs", {}).get(k) != given[k])
        msg = "the round is resumed with other inputs than it was started with"
        raise _refuse("inputs_differ", msg, fields=",".join(changed))
    if header.get("order") != [vars(p) for p in order]:
        raise _refuse("order_differs", "the round's order is not the one its ledger holds")
    changed = _pins_differ(header.get("pins") or {}, pins)
    if changed:
        msg = (
            "the round is resumed on other code or another client than it began with; a round "
            "continued on them would be two rounds under one name"
        )
        raise _refuse("harness_differs", msg, fields=",".join(changed))
    return lines


# What a trial's directory holds. ------------------------------------------------------------


#: What a trial's directory holds before its decomposition is given it: the target's clone and
#: the run's review root, both this process's.
_PREPARED = frozenset({TARGET, REVIEW})
#: What a decomposition writes before its call: the parameters' record, and the review root's.
_BEFORE_THE_CALL = frozenset({PARAMS_RECORD, REVIEW_ROOT_RECORD})


def _never_dispatched(run_dir: Path) -> bool:
    """Whether the log in ``run_dir`` is of a run the core will never dispatch, as the core says.

    A decomposition opens its run's record (the log made, empty) once its call and the plan's
    review have ended, then writes the configuration, the run's branch and commits and its opening
    a line at a time, and last the round journal's terminal line. One killed in that span, or whose
    start raised, left a log no command will ever drive: ``run`` and ``resume`` refuse it, and the
    decomposition refuses a directory that holds a log. So it is asked of the core's own reading,
    as every command that drives a run reads it first:

    - no configuration recorded beside the log: the core's reader of it refuses
      (:func:`load_run_config`), and only a decomposition's opening writes one;
    - the core's record refusing to open it (:class:`RunRecord`): the opening cut before its
      review, or the round journal not ended, ended void, or not the log's rounds;
    - a record that opens with no line: the run's first line is its start, which only a
      decomposition writes.

    Nothing else is read here, so nothing of the machine refuses it: a credential, the OS layer,
    the endpoint, the binary and the harness are each held to when a run is driven, after this
    opening, and a run they refuse is a run the core resumes once they are put right. Any other
    refusal of the opening (a changed record, another run's log) is left for the core to say when
    the run is driven. Opening the record is what a command that drives the run does first: a
    torn last line is cut as the core cuts it.
    """
    config_path = run_dir / "run.json"
    if not os.path.lexists(config_path):
        return True
    try:
        config = load_run_config(config_path)
        record = RunRecord(config, run_dir)
    except RunStateError:
        return True
    except (OrchestratorError, OSError, ValueError):
        return False  # the core says why, and refuses it, when the run is driven
    try:
        return not record.log.events
    finally:
        record.close()


def _state(run_dir: Path) -> Literal["unmade", "free", "spent", "run"]:
    """What a trial's directory holds, by an allow-list that fails closed.

    ``unmade``: nothing but what this process prepares, so no call was given it. ``free``: that,
    and the records a decomposition writes before its call, so no model call was made and no
    session started. ``run``: a run's log the core would dispatch. ``spent``: anything else, so a
    call may have been made and its spend lies in the directory: a run begun and never finished
    among them (:func:`_never_dispatched`).
    """
    if not os.path.lexists(run_dir):
        return "unmade"
    if (run_dir / "events.jsonl").exists():
        return "spent" if _never_dispatched(run_dir) else "run"
    entries = set(os.listdir(run_dir))
    review = run_dir / REVIEW
    nothing_reviewed = not os.path.lexists(review) or (
        review.is_dir() and not review.is_symlink() and not any(review.iterdir())
    )
    if not nothing_reviewed:
        return "spent"
    if entries <= _PREPARED:
        return "unmade"
    if PARAMS_RECORD in entries and entries <= _PREPARED | _BEFORE_THE_CALL:
        return "free"
    return "spent"


def _events(run_dir: Path) -> tuple[bytes, list[Event] | None]:
    """The run's log, and its events when it can be read whole; ``None`` when it cannot."""
    data = (run_dir / "events.jsonl").read_bytes()
    if not data or not data.endswith(b"\n"):
        return data, None
    try:
        return data, parse_events(data, log=str(run_dir / "events.jsonl"))
    except PerRoleError:
        return data, None
    except Exception:  # noqa: BLE001 - a log the core could not have written is the core's to say
        return data, None


def _what_it_spent(run_dir: Path) -> tuple[str, int | Literal["unread"]]:
    """A decomposition with no run's cause and spend, read from its round journal.

    The cause is the void the journal ended on, or ``killed`` where it ended on none. The spend
    is every call's and review's on the journal's end lines, or ``unread`` where a round has its
    start line and no end line (or there is no journal), so a call's spend is on no record. Read
    by the journal's own reader (:func:`journal_spend`), beside its writer.
    """
    void, spent = journal_spend(run_dir)
    return (KILLED if void is None else void), ("unread" if spent is None else spent)


def _held(run_dir: Path) -> list[str]:
    """What a directory set aside or superseded held, by its entries' names."""
    return sorted(os.listdir(run_dir))


def _a_person_fixes(cause: str) -> bool:
    """Whether a decomposition's cause is one a person fixes before the round is started again."""
    return cause != KILLED and cause not in INFRASTRUCTURE_CAUSES


def _deal_with(place: Path, index: int, attempt: int, run_dir: Path) -> bool:
    """Do what the core's commands do first with a directory a killed decomposition left.

    The credential files of its sessions no process runs as are removed; then the plan's review
    session a killed decomposition left running is stopped, its credential files removed, and
    its streams redacted and scanned for the held-out canaries (an exposure written to its own
    file first). What was done is written in the trial's log beneath the withheld root. Done
    again on a directory already dealt with, it finds nothing more to do. Returns whether the
    directory's plan review showed held-out material, now or before.
    """
    review = review_root_path(run_dir / REVIEW)
    remove_left_credentials(run_dir, review)
    held = (os.environ.get(name, "") for name in SECRET_VARIABLE.values())
    left = stop_left_review(run_dir, secrets=tuple(secret for secret in held if secret))
    if left.said is not None:
        log = _log_at(place, index, attempt, "left")
        log.parent.mkdir(mode=0o700, exist_ok=True)
        with log.open("a") as handle:
            handle.write(left.said + "\n")
    return left.exposed


def _left_exposed(index: int, attempt: int, **context: str) -> RoundError:
    msg = (
        "a plan review a killed decomposition left in the trial's directory showed "
        "held-out material: the tier counts as exposed, and a person looks before the round "
        "goes on"
    )
    return _refuse("left_review_exposed", msg, index=str(index), attempt=str(attempt), **context)


def _left_behind(ctx: _Round, planned: _Planned, attempt: int, run_dir: Path) -> None:
    """Deal with a directory before it is left behind (:func:`_deal_with`).

    Raises:
        RoundError: its plan review showed held-out material.
    """
    if _deal_with(ctx.place, planned.index, attempt, run_dir):
        raise _left_exposed(planned.index, attempt)


def _what_its_earlier_process_left(place: Path, round_id: str) -> None:
    """Deal with every directory the round's earlier process placed, before the start can refuse.

    Asked first of a restart, once the round is found and its lock held, so no other driver acts
    on it: whatever ends the start after this (the register, the pins, the inputs), no left
    review of the round still runs and no credential of its sessions stays on disk because of it.
    A directory is the round's own when its own ledger placed it: the (trial, attempt) of each
    ``placed`` line, at ``<run root>/<round>/<iiii>-<n>`` beneath the run root the ledger's first
    line records (never the run root this start was given), each a directory, never a link. Only
    those are touched; another round's, and anything else beneath the run root, are not.

    Raises:
        RoundError: the ledger cannot be read, so which directories are the round's cannot be
            told (nothing is touched); or, once every one is dealt with, a plan review left in
            one showed held-out material (the first named, and how many did).
    """
    ledger = place / LEDGER
    lines = _read_ledger(ledger) if ledger.is_file() else []
    if not lines:
        return
    header = lines[0]
    given = header.get("inputs")
    root = given.get("run_root") if isinstance(given, dict) else None
    ours = header.get("kind") == "round" and header.get("round") == round_id
    if not ours or not isinstance(root, str):
        raise _refuse("ledger_unreadable", "the round's ledger does not begin with its round")
    placed = sorted(
        {
            (line["index"], line["attempt"])
            for line in lines
            if line["kind"] == "placed"
            and type(line.get("index")) is int
            and type(line.get("attempt")) is int
        }
    )
    exposed: list[tuple[int, int]] = []
    for index, attempt in placed:
        run_dir = Path(root) / round_id / f"{index:04d}-{attempt}"
        if not _no_link_on_the_way(run_dir) or not os.path.isdir(run_dir):
            continue
        if _deal_with(place, index, attempt, run_dir):
            exposed.append((index, attempt))
    if exposed:
        raise _left_exposed(*exposed[0], directories=str(len(exposed)))


def _prepare(ctx: _Round, run_dir: Path) -> None:
    """Make the trial's directory afresh: the target's clone and the run's review root.

    Whatever a killed earlier preparation left there is removed first, and only that: the
    directory is ``unmade``, so it holds nothing but what this process prepares.
    """
    if os.path.lexists(run_dir):
        if _state(run_dir) != "unmade":
            msg = "the trial's directory holds more than a preparation; nothing is removed"
            raise _refuse("run_dir_not_unmade", msg, run_dir=str(run_dir))
        shutil.rmtree(run_dir)
    run_dir.parent.mkdir(mode=0o700, exist_ok=True)
    run_dir.mkdir(mode=0o700)
    target = run_dir / TARGET
    _git("clone", "--quiet", "--no-hardlinks", "--", str(ctx.inputs.target_from), str(target))
    _git("-C", str(target), "remote", "remove", "origin")
    head = _git("-C", str(target), "rev-parse", "--verify", "HEAD^{commit}").strip()
    if head != ctx.lines[0]["inputs"]["target_head"]:
        msg = "the target's clone is not at the commit the round started from"
        raise _refuse("target_moved", msg)
    (run_dir / REVIEW).mkdir(mode=0o700)


def _log(ctx: _Round, index: int, attempt: int, step: str) -> Path:
    return _log_at(ctx.place, index, attempt, step)


def _log_at(place: Path, index: int, attempt: int, step: str) -> Path:
    return place / "logs" / f"{index:04d}-{attempt}.{step}.log"


# Where the round stands when it is started. -------------------------------------------------


def _standing(ctx: _Round) -> tuple[_Planned, int, dict[str, Any] | None] | None:
    """The first trial not assembled, its last attempt and the line that closed it, if placed."""
    planned = next((p for p in ctx.order if not ctx.of(p.index, "assembled")), None)
    if planned is None:
        return None
    placed = ctx.of(planned.index, "placed")
    if not placed:
        return None
    last = int(placed[-1]["attempt"])
    return planned, last, ctx.closing(planned.index, last)


def _waiting_at_start(ctx: _Round) -> tuple[int, int] | None:
    """The trial and attempt the round stood waiting for the usage limit at, read before acting.

    The round stops at the first trial that waits, so only the first trial not yet assembled
    can: its decomposition ended on the limit with no fresh one placed yet, or its run halted on
    the limit. The person's word is for that wait alone.
    """
    standing = _standing(ctx)
    if standing is None:
        return None
    planned, last, closing = standing
    i = planned.index
    if closing is not None:
        return (i, last) if closing["kind"] == "limit" else None
    run_dir = ctx.run_dir(i, last)
    if _state(run_dir) != "run":
        return None
    _data, events = _events(run_dir)
    halt = None if events is None else machine_end(events)
    return (i, last) if halt is not None and halt.reason == USAGE_LIMIT else None


def _stopped_for_a_person_at(ctx: _Round) -> int | None:
    """The trial the round stands stopped at for a person's word on its directory, if any.

    A decomposition that spent its call and left no run, once the trial's one more go is spent;
    or a directory with nothing but its parameters, once the trial had its one free set-aside.
    """
    standing = _standing(ctx)
    if standing is None:
        return None
    planned, last, closing = standing
    if closing is not None:
        return None
    i = planned.index
    state = _state(ctx.run_dir(i, last))
    if state == "run" and _halted_on_a_credential(ctx.run_dir(i, last)):
        # A run halted on a refused credential: a person resumes it on the credential put right,
        # or sets its directory aside and the trial is decomposed afresh, spending nothing.
        return i
    if state == "spent" and _once_more_taken(ctx, i):
        return i
    if state == "free" and any(x["attempt"] != last for x in ctx.of(i, "left")):
        return i
    return None


def _halted_on_a_credential(run_dir: Path) -> bool:
    """Whether the run in ``run_dir`` stands halted on a refused credential, by its own log."""
    _data, events = _events(run_dir)
    halt = None if events is None else machine_end(events)
    return halt is not None and halt.reason == CREDENTIAL_REFUSED


def _credential_at_start(ctx: _Round) -> tuple[int, int] | None:
    """The trial and attempt the round stood stopped at on a refused credential, read before acting.

    Its run halted on one, or its decomposition met one (the ``credential`` line closing it, no
    fresh one placed yet). The person's word is for that stop alone; a fresh decomposition
    records the credential it is made on, so there the word is taken and nothing needs it.
    """
    standing = _standing(ctx)
    if standing is None:
        return None
    planned, last, closing = standing
    i = planned.index
    if closing is not None:
        return (i, last) if closing["kind"] == "credential" else None
    run_dir = ctx.run_dir(i, last)
    if _state(run_dir) == "run" and _halted_on_a_credential(run_dir):
        return (i, last)
    return None


def _replaced(ctx: _Round, i: int, attempt: int) -> bool:
    """Whether the person's word on the credential is for this run's resume; used once, if it is."""
    if ctx.replaced_for != (i, attempt):
        return False
    ctx.replaced_for = None
    return True


# One trial. ---------------------------------------------------------------------------------


def _machine_halts(events: Sequence[Event]) -> int:
    """The run's machine halts that count as its ends: neither the limit's nor a credential's."""
    return sum(
        1
        for e in events
        if isinstance(e, Halted)
        and e.reason in INFRASTRUCTURE_HALTS
        and e.reason not in (CREDENTIAL_REFUSED, USAGE_LIMIT)
    )


def _once_more_taken(ctx: _Round, i: int) -> bool:
    """Whether the trial's one more go of the machine's rule is spent.

    One per trial, across its draws: a fresh decomposition superseded a directory, or a draw run
    again after an exclusion had spent it (its own superseded line, or its run's one resume).
    """
    return bool(ctx.of(i, "superseded")) or any(
        x.get("once_more_spent") for x in ctx.of(i, "excluded")
    )


def _touched(ctx: _Round, i: int, attempt: int) -> bool:
    """Whether this process decomposed, drove or resumed the run: what it ended on is news."""
    keys = ("decomposed", "driven", "resume", "credential", "limit")
    return any((key, i, attempt) in ctx.acted for key in keys)


def _the_word(ctx: _Round, i: int, attempt: int) -> bool:
    """Whether the person's word on the limit is for this run's next step; used once, if it is."""
    if ctx.reset_for != (i, attempt):
        return False
    ctx.reset_for = None
    return True


def _limit_holds(ctx: _Round, planned: _Planned, run_dir: Path, *, word: bool) -> bool:
    """Whether the core would refuse the resume of a run halted on the limit now; said if so.

    The core's own reading (:func:`limit_wait`): a reset the client's limit message gave is waited
    for whatever the word says; one it did not is waited for until the core's stated wait has
    passed, or until the word.
    """
    now = ctx.now()
    waiting = limit_wait(run_dir, now, limit_reset=word)
    if waiting is None:
        return False
    ctx.waiting = {
        "index": planned.index,
        "why": USAGE_LIMIT,
        "resume_after": waiting["resume_after"],
        "word_helps": limit_wait(run_dir, now, limit_reset=True) is None,
    }
    return True


def _said_wait(ctx: _Round, planned: _Planned) -> None:
    """Make sure the round's wait for the limit says a trial and an instant still to come.

    A wait whose instant is already past, or that names none (the drive exited waiting where
    the core, read now, would already resume), says :data:`LIMIT_WAIT_FLOOR` from now instead,
    and that it is the floor; one to come is said as read.
    """
    now = ctx.now()
    waiting = ctx.waiting or {
        "index": planned.index,
        "why": USAGE_LIMIT,
        "resume_after": None,
        "word_helps": False,
    }
    after = waiting.get("resume_after")
    if after is None or stamped(after) <= now:
        waiting = {**waiting, "resume_after": utc_stamp(now + LIMIT_WAIT_FLOOR), "floor": True}
    ctx.waiting = waiting


def _past_the_limit(
    ctx: _Round, planned: _Planned, attempt: int, line: Mapping[str, Any]
) -> str | None:
    """How the round goes on past a decomposition that ended on the limit, or ``None`` to wait.

    Held to the core's rule for a run's resume (:func:`resume_refusal`), with the limit the core
    recorded for the decomposition (:func:`_limit_recorded`): ``waited`` once its reset has passed,
    where one was read, or else the stated wait after it stopped; ``operator`` before then, on the
    person's word, where no reset was read: the word is used once and named on the line of the
    directory it lets the round make. A line that names no halt goes on only on the word.
    """
    i = planned.index
    halted_at = line.get("halted_at")
    limit = _limit_recorded(ctx.run_dir(i, attempt))
    now = ctx.now()
    helps = True
    if halted_at is not None:
        if resume_refusal(halted_at, limit, now, limit_reset=False) is None:
            return "waited"
        helps = resume_refusal(halted_at, limit, now, limit_reset=True) is None
    if helps and _the_word(ctx, i, attempt):
        return "operator"
    ctx.waiting = {
        "index": i,
        "why": USAGE_LIMIT,
        "resume_after": None if halted_at is None else resume_after(halted_at, limit),
        "word_helps": helps,
    }
    return None


def _limit_recorded(run_dir: Path) -> UsageLimit | None:
    """The limit the core recorded a decomposition in ``run_dir`` stopped by, if it recorded one.

    The failed decomposition's halt, where its run's record was opened; otherwise the end line of
    the round its void rounds ended on the limit with (:func:`rounds_on_the_limit`).
    """
    if (run_dir / "events.jsonl").exists():
        _data, events = _events(run_dir)
        halt = None if events is None else machine_end(events)
        return None if halt is None else halt.usage_limit
    on_limit = rounds_on_the_limit(run_dir)
    return None if on_limit is None else on_limit[1]


def _wait_for_a_person(
    ctx: _Round, planned: _Planned, attempt: int, why: str, **said: Any
) -> Status:  # noqa: ANN401
    """Stop the round for a person, saying which trial, which directory and why."""
    ctx.waiting = {
        "index": planned.index,
        "run_dir": str(ctx.run_dir(planned.index, attempt)),
        "why": why,
        **said,
    }
    return "waiting_for_a_person"


def _trial(ctx: _Round, planned: _Planned) -> Status | None:
    """Take one trial on until it is assembled, or the round waits; ``None`` once assembled.

    Raises:
        RoundError: a step was taken and moved nothing, or the run is not the trial's.
    """
    i = planned.index
    while True:
        if ctx.of(i, "assembled"):
            return None
        placed = ctx.of(i, "placed")
        last = int(placed[-1]["attempt"]) if placed else None
        closing = None if last is None else ctx.closing(i, last)
        if last is not None and closing is None:
            status = _step(ctx, planned, last)
            if status is not None:
                return status
            continue
        past: dict[str, Any] = {}
        if last is not None and closing is not None:
            kind = closing["kind"]
            if kind == "credential" and _touched(ctx, i, last):
                # Its decomposition met a refused credential in this process: a person replaces it.
                return _wait_for_a_person(ctx, planned, last, CREDENTIAL_REFUSED)
            if kind == "limit":
                how = _past_the_limit(ctx, planned, last, closing)
                if how is None:
                    return "waiting_for_limit"
                past = {"limit_reset": how}
            if kind == "superseded" and closing.get("by", "rule") == "rule":
                ctx.sleep(float(closing["delay_s"]))
            if kind == "excluded":
                past = {"after_exclusion": last}
        attempt = 1 if last is None else last + 1
        ctx.add(
            {
                "kind": "placed",
                "index": i,
                "attempt": attempt,
                "run_id": ctx.run_id(i, attempt),
                "run_dir": str(ctx.run_dir(i, attempt)),
                "seed": planned.seed,
                **past,
            }
        )


def _no_link_on_the_way(path: Path) -> bool:
    """Whether no part of ``path``, from the top down to itself, is a link.

    A part not there yet is no link: this process makes it.
    """
    return all(not os.path.islink(part) for part in (*reversed(path.parents), path))


def _require_its_own(ctx: _Round, i: int, attempt: int, run_dir: Path) -> None:
    """Refuse a trial directory reached through a link, before anything reads or touches it.

    Its path is the run root the round recorded, the round's directory and the trial's, each
    part held to be no link: a link at any of them (or a run root whose real path moved since)
    would have the driver stop a review, remove a credential, write an exposure, decompose or
    drive in a directory that is not its own.

    Raises:
        RoundError: a part of the path is a link.
    """
    recorded = Path(ctx.lines[0]["inputs"]["run_root"]) / ctx.round_id / run_dir.name
    if recorded != run_dir or not _no_link_on_the_way(recorded):
        msg = "a part of the trial's directory's path is a link; nothing in it is touched"
        raise _refuse("run_dir_linked", msg, index=str(i), attempt=str(attempt))


def _step(ctx: _Round, planned: _Planned, attempt: int) -> Status | None:
    """One step of the trial's current run, as its own records say; ``None`` to look again."""
    i = planned.index
    run_dir = ctx.run_dir(i, attempt)
    _require_its_own(ctx, i, attempt, run_dir)
    state = _state(run_dir)
    if state == "unmade":
        return _decompose(ctx, planned, attempt, run_dir)
    if state == "free":
        return _set_aside(ctx, planned, attempt, run_dir)
    if state == "spent":
        on_limit = rounds_on_the_limit(run_dir)
        if on_limit is not None:
            # Rounds that ended void on the limit, its call's or its review's: no attempt, as a
            # run's record halted on a decomposition the limit stopped is none; then afresh.
            _left_behind(ctx, planned, attempt, run_dir)
            ended, limit = on_limit
            _void, spent = journal_spend(run_dir)
            ctx.add(
                {
                    "kind": "limit",
                    "index": i,
                    "attempt": attempt,
                    "run_id": ctx.run_id(i, attempt),
                    "halted_at": ended,
                    "resume_after": resume_after(ended, limit),
                    "tokens": "unread" if spent is None else spent,
                }
            )
            return None
        return _superseded_without_a_run(ctx, planned, attempt, run_dir)
    _the_trial_s(ctx, planned, attempt)
    _data, events = _events(run_dir)
    if events is None or next_step(events) not in ENDED_STEPS:
        _once(ctx, ("drive", i, attempt), "a drive of the run left it where it was")
        fresh = ("decomposed", i, attempt) in ctx.acted and ("driven", i, attempt) not in ctx.acted
        ctx.acted.add(("driven", i, attempt))
        return _drive(ctx, planned, attempt, "drive", resume=not fresh)
    halt = machine_end(events)
    once_more_taken = _once_more_taken(ctx, i)
    spent = TokenAccount.from_events(events).total().total()
    if halt is not None and halt.reason == "decomposition_failed":
        cause = decomposition_cause(halt)
        if cause in (CREDENTIAL_REFUSED, USAGE_LIMIT):
            # No attempt: a person replaces the credential, or the limit resets; then afresh.
            kind = "credential" if cause == CREDENTIAL_REFUSED else "limit"
            line = {"kind": kind, "index": i, "attempt": attempt, "run_id": ctx.run_id(i, attempt)}
            if kind == "limit":
                # The reset the core recorded on the halt where it read one, else its stated wait
                # after the halt: the round holds a restart to it as the core holds a run's resume.
                line |= {
                    "halted_at": halt.ts,
                    "resume_after": resume_after(halt.ts, halt.usage_limit),
                }
            ctx.add({**line, "tokens": spent})
            return None
        if not once_more_taken:
            _left_behind(ctx, planned, attempt, run_dir)
            ctx.add(
                {
                    "kind": "superseded",
                    "index": i,
                    "attempt": attempt,
                    "run_id": ctx.run_id(i, attempt),
                    "cause": cause,
                    "tokens": spent,
                    "delay_s": ctx.delay(),
                    "by": "rule",
                    "from_run": True,
                    "held": _held(run_dir),
                }
            )
            return None
    elif halt is not None and halt.reason == CREDENTIAL_REFUSED:
        # No attempt either: the run waits for a person, and is resumed once started again, on
        # the credential put right, or on another secret where the person says it was replaced.
        if ctx.set_aside_for == i:
            return _set_aside_on_a_credential(ctx, planned, attempt, run_dir, spent)
        if _touched(ctx, i, attempt):
            return _wait_for_a_person(ctx, planned, attempt, CREDENTIAL_REFUSED)
        ctx.acted.add(("credential", i, attempt))
        return _drive(
            ctx, planned, attempt, "resume", resume=True, replaced=_replaced(ctx, i, attempt)
        )
    elif halt is not None and halt.reason == USAGE_LIMIT:
        # Never an end: the run is resumed past the limit, however often it met it, once the
        # core would resume it; until then the round waits, saying until when.
        if _limit_holds(ctx, planned, run_dir, word=ctx.reset_for == (i, attempt)):
            return "waiting_for_limit"
        _once(ctx, ("limit", i, attempt), "the run's resume past the usage limit left it there")
        return _drive(ctx, planned, attempt, "resume", resume=True)
    elif halt is not None and _machine_halts(events) == 1 and not once_more_taken:
        _once(ctx, ("resume", i, attempt), "the run's one resume left it where it was")
        ctx.sleep(ctx.delay())
        return _drive(ctx, planned, attempt, "resume", resume=True)
    _assemble(ctx, planned, attempt, events)
    return None


def _set_aside_on_a_credential(
    ctx: _Round, planned: _Planned, attempt: int, run_dir: Path, spent: int
) -> Status | None:
    """Set aside, on a person's word, a run halted on a refused credential: no attempt spent.

    The run stays where it is, for the exposure scan, named on a ``credential`` line as the
    person's act with what it spent; the trial is decomposed afresh, as after a decomposition
    that met a refused credential.
    """
    i = planned.index
    _left_behind(ctx, planned, attempt, run_dir)
    ctx.set_aside_for = None
    ctx.add(
        {
            "kind": "credential",
            "index": i,
            "attempt": attempt,
            "run_id": ctx.run_id(i, attempt),
            "tokens": spent,
            "by": "operator",
            "from_run": True,
            "held": _held(run_dir),
        }
    )
    return None


def _decompose(ctx: _Round, planned: _Planned, attempt: int, run_dir: Path) -> Status | None:
    """Prepare the trial's directory and decompose its brief into it."""
    i = planned.index
    _once(ctx, ("decompose", i, attempt), "a decomposition left nothing in its directory")
    _prepare(ctx, run_dir)
    code = ctx.driver.decompose(
        Decompose(
            brief=ctx.brief(planned),
            seed=planned.seed,
            run_id=ctx.run_id(i, attempt),
            params=ctx.place / "params.json",
            target=run_dir / TARGET,
            run_dir=run_dir,
            install=ctx.inputs.install,
            review_root=run_dir / REVIEW,
            log=_log(ctx, i, attempt, "decompose"),
        )
    )
    ctx.acted.add(("decomposed", i, attempt))
    if code == REFUSED and _state(run_dir) in ("unmade", "free"):
        # Refused before its call: a person reads why, beneath the withheld root. A refusal after
        # the call (a void) is the trial's run, taken on from what the directory holds.
        _refused_by(code, "decompose", i, attempt)
    return None


def _set_aside(ctx: _Round, planned: _Planned, attempt: int, run_dir: Path) -> Status | None:
    """Set aside a directory whose records show no call and no session: once per trial, free."""
    i = planned.index
    _left_behind(ctx, planned, attempt, run_dir)
    earlier = [x for x in ctx.of(i, "left") if x["attempt"] != attempt]
    if earlier and ctx.set_aside_for != i:
        return _wait_for_a_person(ctx, planned, attempt, "set_aside_twice")
    by = "operator" if earlier else "rule"
    if by == "operator":
        ctx.set_aside_for = None
    why = "its decomposition recorded its parameters, and made no call and started no session"
    ctx.add(
        {
            "kind": "left",
            "index": i,
            "attempt": attempt,
            "run_id": ctx.run_id(i, attempt),
            "why": why,
            "held": _held(run_dir),
            "by": by,
        }
    )
    if ("decomposed", i, attempt) in ctx.acted:
        # This process's own decomposition left it so: the round stops for a person to look,
        # and a later start makes the trial's run again in a fresh directory.
        msg = f"the trial's decomposition {why}; its output lies beneath the withheld root"
        raise _refuse("decomposition_left_no_run", msg, index=str(i), attempt=str(attempt))
    return None


def _superseded_without_a_run(
    ctx: _Round, planned: _Planned, attempt: int, run_dir: Path
) -> Status | None:
    """Supersede once a decomposition that spent its call and left no run; then stop for a person.

    Killed after its call or during its plan's review, or ended void: no run record says how it
    ended, so it cannot be resumed and has nothing to assemble. Its one fresh decomposition is
    the trial's one more go; once that is spent, a person's word on a restart that names the
    trial sets the directory aside.
    """
    i = planned.index
    _left_behind(ctx, planned, attempt, run_dir)
    cause, tokens = _what_it_spent(run_dir)
    if cause == CREDENTIAL_REFUSED:
        # Its call met a refused credential and its rounds ended void on it (a review mode that
        # holds the plan): no attempt, as a run's record halted on a decomposition the credential
        # stopped is none. Named with its spend; a person replaces it, then the trial afresh.
        line = {"kind": "credential", "index": i, "attempt": attempt}
        ctx.add({**line, "run_id": ctx.run_id(i, attempt), "tokens": tokens})
        return None
    if _once_more_taken(ctx, i) and ctx.set_aside_for != i:
        return _wait_for_a_person(
            ctx,
            planned,
            attempt,
            "spent_decomposition",
            cause=cause,
            tokens=tokens,
            fix_first=_a_person_fixes(cause),
        )
    by = "operator" if _once_more_taken(ctx, i) else "rule"
    if by == "operator":
        ctx.set_aside_for = None
    ctx.add(
        {
            "kind": "superseded",
            "index": i,
            "attempt": attempt,
            "run_id": ctx.run_id(i, attempt),
            "cause": cause,
            "tokens": tokens,
            "delay_s": ctx.delay(),
            "by": by,
            "from_run": False,
            "held": _held(run_dir),
        }
    )
    return None


def _drive(
    ctx: _Round,
    planned: _Planned,
    attempt: int,
    command: str,
    *,
    resume: bool,
    replaced: bool = False,
) -> Status | None:
    """Drive or resume the trial's run, the person's word on the limit given if it is for it."""
    i = planned.index
    run_dir = ctx.run_dir(i, attempt)
    code = ctx.driver.drive(
        Drive(
            resume=resume,
            run_dir=run_dir,
            target=run_dir / TARGET,
            install=ctx.inputs.install,
            review_root=run_dir / REVIEW,
            limit_reset=resume and _the_word(ctx, i, attempt),
            log=_log(ctx, i, attempt, "drive"),
            credential_replaced=resume and replaced,
        )
    )
    status = _waits(code, command, i, attempt)
    if status == "waiting_for_limit":
        # The run halted on the limit, or its resume was refused before the reset: until when.
        _limit_holds(ctx, planned, run_dir, word=False)
    return status


def _the_trial_s(ctx: _Round, planned: _Planned, attempt: int) -> None:
    """Refuse a run in the trial's directory that is not the trial's, before it is driven.

    Raises:
        RoundError: another run id, brief or target commit.
    """
    i = planned.index
    config = load_run_config(ctx.run_dir(i, attempt) / "run.json")
    if (
        config.run_id != ctx.run_id(i, attempt)
        or config.brief_sha256 != planned.brief_sha256
        or config.target_head != ctx.lines[0]["inputs"]["target_head"]
    ):
        msg = "the run in the trial's directory is not the trial's"
        raise _refuse("run_not_the_trial_s", msg, index=str(i), attempt=str(attempt))


#: The status the orchestrator's commands exit with when they refuse what they were asked.
REFUSED = 2


def _refused_by(code: int, command: str, index: int, attempt: int) -> None:
    """Stop the round on a command's refusal: a person reads why, beneath the withheld root.

    Raises:
        RoundError: the command refused (exit 2).
    """
    if code == REFUSED:
        msg = f"the trial's {command} was refused; its output lies beneath the withheld root"
        raise _refuse(f"{command}_refused", msg, index=str(index), attempt=str(attempt))


def _waits(code: int, command: str, index: int, attempt: int) -> Status | None:
    """Whether a drive's exit says the run waits for the usage limit; a refusal stops the round."""
    if code == EXIT_WAITING_FOR_LIMIT:
        return "waiting_for_limit"
    _refused_by(code, command, index, attempt)
    return None


def _once(ctx: _Round, key: tuple[Any, ...], words: str) -> None:
    """Refuse a step this process already took on the same record: it would move nothing again.

    Raises:
        RoundError: the step was taken; its command's output lies beneath the withheld root.
    """
    if key in ctx.acted:
        msg = f"{words}; its command's output lies beneath the withheld root"
        raise _refuse("run_did_not_move", msg, index=str(key[1]), attempt=str(key[2]))
    ctx.acted.add(key)


@dataclass(frozen=True)
class Assembled:
    """A harness trial's record, assembled from its ended run, and what it was made from."""

    record: TrialRecord | ExcludedTrial
    #: How the answer's extraction ended; ``None`` where the run's plan named no directory.
    answer: str | None
    unscored: bool
    manifest_id: str


def assemble_trial(
    run_dir: Path,
    task: Task,
    events: Sequence[Event],
    *,
    role: Role,
    tier: str,
    trial: int,
    prices: DatedSheet,
    scorer: Scorer,
    place: Path,
    name: str,
    keep_score: bool = True,
) -> Assembled:
    """Extract, score, price and assemble a trial's ended run: the one step that writes its record.

    The answer is taken from the run branch into ``place/answers/<name>/``, from the module
    directories the run's own plan names, and scored; its score is kept beside it in
    ``place/scores/<name>.json`` unless ``keep_score`` is false. The round runs it once per
    trial; the record audit runs it again, into a place of its own, to derive the record anew.
    """
    config = load_run_config(run_dir / "run.json")
    extraction = None
    planned_dirs = planned_module_dirs(events, role)
    if planned_dirs:
        answer = place / "answers" / name / task.answer.path
        (place / "answers").mkdir(mode=0o700, exist_ok=True)
        extraction = extract(
            run_dir / TARGET, config.run_id, task.answer.path, answer, module_dirs=planned_dirs
        )
    found = extraction is not None and extraction.status == "found"
    score: Mapping[str, Any] | None = None
    if found:
        score = scorer(task, place / "answers" / name / task.answer.path)
        if keep_score:
            (place / "scores").mkdir(mode=0o700, exist_ok=True)
            _write_whole(place / "scores" / f"{name}.json", canonical_json(dict(score)))
    unscored = False
    if not found:
        try:
            unscored = harness_ended_by_infrastructure(run_dir, task, answer_found=False)
        except TrialExcludedError:
            unscored = False  # assembled as excluded below, with its reason
    cost = price_run(run_dir, prices, review_roots=(run_dir / REVIEW,))
    manifest_id = manifest_id_of(run_dir, read_run_events(run_dir))
    record = harness_trial(
        suite=f"{role}_{tier}",
        task=task,
        trial=trial,
        run_dir=run_dir,
        manifest_id=manifest_id,
        cost=cost,
        score=score,
        unscored=unscored,
    )
    return Assembled(
        record, None if extraction is None else extraction.status, unscored, manifest_id
    )


def run_events(run_dir: Path) -> list[Event] | None:
    """The run's events when its log can be read whole, as the round reads them; else ``None``."""
    return _events(run_dir)[1]


def _assemble(ctx: _Round, planned: _Planned, attempt: int, events: list[Event]) -> None:
    """Extract, score, price and assemble the trial's ended run, then record it in the ledger.

    Raises:
        RoundError: the run is not the trial's: another run id, brief or target commit.
    """
    i = planned.index
    run_dir = ctx.run_dir(i, attempt)
    task = ctx.tasks[planned.brief_sha256]
    _the_trial_s(ctx, planned, attempt)
    config = load_run_config(run_dir / "run.json")
    done = assemble_trial(
        run_dir,
        task,
        events,
        role=ctx.inputs.role,
        tier=planned.tier,
        trial=planned.trial,
        prices=ctx.inputs.prices,
        scorer=ctx.scorer,
        place=ctx.place,
        name=f"{i:04d}-{attempt}",
    )
    record = done.record
    try:
        total: int | None = harness_total(run_dir)
        no_total = None
        no_figure = None
    except ComparisonError as exc:
        total, no_total = None, str(exc)
        no_figure = {"because": _no_figure_because(run_dir, done.unscored), "detail": no_total}
    earlier = ctx.of(i, "excluded")
    if (
        isinstance(record, ExcludedTrial)
        and rerun_cause(record.reason, "harness") == "untrusted"
        and not earlier
    ):
        # Not to be trusted, by the reason's field alone, before anyone reads a score: the trial
        # is run once more into a fresh directory with the same seed; this draw is kept where it
        # lies for the exposure scan, named here with its spend, in no run set and no cap.
        ctx.add(
            {
                "kind": "excluded",
                "index": i,
                "attempt": attempt,
                "run_id": config.run_id,
                "run_dir": str(run_dir),
                "field": reason_field(record.reason),
                "reason": record.reason,
                "tokens": TokenAccount.from_events(events).total().total(),
                "harness_total": total,
                "once_more_spent": bool(ctx.of(i, "superseded")) or _machine_halts(events) > 0,
                "held": _held(run_dir),
                "by": "rule",
            }
        )
        return
    rerun = (
        {}
        if not earlier
        else {
            "rerun_of": {
                key: earlier[-1][key] for key in ("attempt", "run_id", "run_dir", "field", "reason")
            }
        }
    )
    ctx.add(
        {
            "kind": "assembled",
            "index": i,
            "attempt": attempt,
            "run_id": config.run_id,
            "run_dir": str(run_dir),
            "manifest_id": done.manifest_id,
            "answer": done.answer,
            "unscored": done.unscored,
            "outcome": "excluded" if isinstance(record, ExcludedTrial) else record.outcome,
            "record": record.model_dump(mode="json"),
            "harness_total": total,
            "no_total": no_total,
            "no_figure": no_figure,
            **rerun,
        }
    )


#: Why a harness trial gives the raw arm no figure, read from its own records, never from the
#: refusal's words: its log cannot be read; the machine ended it after its one more go; a
#: session was read without a result to check it against (or never ended); it stands where a
#: resume continues it, or has not ended; it ended at its decomposition with no role session.
NoFigure = Literal["log_unreadable", "unscored", "leftover_unread", "stuck", "no_role_session"]


def _no_figure_because(run_dir: Path, unscored: bool) -> NoFigure:
    """Why the trial's run gives no figure, the first of :data:`NoFigure` its records show."""
    data, events = _events(run_dir)
    if events is None or not data:
        return "log_unreadable"
    try:
        state = replay(events)
    except OrchestratorError:
        return "log_unreadable"
    if unscored:
        return "unscored"
    if (
        open_sessions(events, run_dir)
        or any(isinstance(e, TokensUsed) and e.partial for e in events)
        or any(isinstance(e, LeftoverRead) and not e.complete for e in events)
    ):
        return "leftover_unread"
    step = state.next_step().kind
    if step not in ENDED_STEPS or (step == "halted" and state.halt_resumable()):
        return "stuck"
    return "no_role_session"


def _no_cap_in_the_cell(ctx: _Round) -> list[str]:
    """The tiers with a trial that gives no figure where no trial of the tier gives one.

    For such a trial the cap rule has nothing to take (the largest figure among the task's other
    trials, else the middle figure of the cell): the round ends ``done_without_caps``. Where a
    trial of the tier gives a figure, the rule gives every no-figure trial of it a cap, and the
    round ends ``done``, the no-figure trials stated.
    """
    assembled = _assembled(ctx)
    tiers: list[str] = []
    for tier in VERSION_TIERS:
        totals = [x["harness_total"] for p, x in assembled if p.tier == tier]
        if None in totals and all(total is None for total in totals):
            tiers.append(tier)
    return tiers


# What the round writes. ---------------------------------------------------------------------


def _assembled(ctx: _Round) -> list[tuple[_Planned, dict[str, Any]]]:
    by_index = {x["index"]: x for x in ctx.lines if x["kind"] == "assembled"}
    return [(p, by_index[p.index]) for p in ctx.order if p.index in by_index]


def _record_line(line: dict[str, Any]) -> bytes:
    raw = line["record"]
    model = ExcludedTrial if "reason" in raw and "outcome" not in raw else TrialRecord
    return model.model_validate_json(json.dumps(raw)).model_dump_json().encode() + b"\n"


def _outputs(ctx: _Round) -> None:
    """Every run set, every tier's records and the round's records, written from the ledger."""
    done = _assembled(ctx)
    combined: list[dict[str, Any]] = []
    for tier in VERSION_TIERS:
        these = [(p, x) for p, x in done if p.tier == tier]
        if not these:
            continue
        entries = [{"run_dir": x["run_dir"], "trial": p.trial} for p, x in these]
        combined += entries
        runs = RunSet.model_validate_json(json.dumps({"format": 1, "trials": entries}))
        where = ctx.inputs.out if tier == VISIBLE else ctx.place
        _write_whole(where / f"{tier}.runs.json", runs.model_dump_json().encode())
        _write_whole(where / f"{tier}.trials.jsonl", b"".join(_record_line(x) for _, x in these))
    every = RunSet.model_validate_json(json.dumps({"format": 1, "trials": combined}))
    _write_whole(ctx.place / COMBINED, every.model_dump_json().encode())
    if not any(x["kind"] == "ended" for x in ctx.lines):
        after = _register_head(ctx.inputs.store, ctx.inputs.role)
        ctx.add({"kind": "ended", "register_after": after})
    _write_whole(ctx.place / ROUND_RECORD, canonical_json(_audit(ctx)))
    _write_whole(ctx.inputs.out / ROUND_RECORD, canonical_json(_summary(ctx, done=True)))


def _pins(ctx: _Round) -> dict[str, Any]:
    """The pins every assembled run shares; a pin they do not share is named as differing."""
    seen: dict[str, set[str]] = {}
    values: dict[str, Any] = {}
    for _, line in _assembled(ctx):
        config = load_run_config(Path(line["run_dir"]) / "run.json")
        tools = config.tool_environment
        pins = {
            "models": config.models.model_dump(mode="json"),
            "claude_version": config.claude_version,
            "binary": None if config.binary is None else config.binary.model_dump(mode="json"),
            "harness_commit": config.harness.commit,
            "tool_environment_sha256": (
                None
                if tools is None
                else hashlib.sha256(canonical_json(tools.model_dump(mode="json"))).hexdigest()
            ),
            "account": None if config.account is None else config.account.name,
        }
        for key, value in pins.items():
            seen.setdefault(key, set()).add(json.dumps(value, sort_keys=True))
            values[key] = value
    return {k: (values[k] if len(seen[k]) == 1 else "differs") for k in values}


#: What the round's record names of each decomposition it superseded, and of each it set aside.
_SUPERSEDED = ("index", "attempt", "run_id", "cause", "tokens", "by", "from_run", "held")
_LEFT = ("index", "attempt", "run_id", "why", "held", "by")
_EXCLUDED = (
    "index",
    "attempt",
    "run_id",
    "run_dir",
    "field",
    "reason",
    "tokens",
    "harness_total",
    "once_more_spent",
    "held",
    "by",
)


def _named(line: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    # A line an earlier format wrote lacks the newer keys: a superseded run of the machine's
    # rule, with its run record.
    defaults = {"by": "rule", "from_run": True, "held": None, "run_id": None}
    return {k: line.get(k, defaults.get(k)) for k in keys}


def _no_cap(ctx: _Round, tiers: Sequence[str]) -> dict[str, int]:
    """How many assembled trials of each of ``tiers`` give the baseline no cap."""
    assembled = _assembled(ctx)
    return {
        tier: sum(1 for p, x in assembled if p.tier == tier and x["harness_total"] is None)
        for tier in tiers
    }


def _audit(ctx: _Round) -> dict[str, Any]:
    """The round's record, beneath the withheld root: every trial, run and digest."""
    header = ctx.lines[0]
    ended = next((x for x in ctx.lines if x["kind"] == "ended"), None)
    trials = []
    for planned, line in _assembled(ctx):
        gone = [_named(x, _SUPERSEDED) for x in ctx.of(planned.index, "superseded")]
        trials.append(
            {
                "index": planned.index,
                "tier": planned.tier,
                "trial": planned.trial,
                "seed": planned.seed,
                "brief_sha256": planned.brief_sha256,
                "run_id": line["run_id"],
                "run_dir": line["run_dir"],
                "manifest_id": line["manifest_id"],
                "answer": line["answer"],
                "outcome": line["outcome"],
                "excluded": line["record"].get("reason"),
                "harness_total": line["harness_total"],
                "no_total": line["no_total"],
                "no_figure": line.get("no_figure"),
                "rerun_of": line.get("rerun_of"),
                # Each second draw of the trial's plan, with its cause and spend.
                "superseded_count": len(gone),
                "superseded": gone,
                "left": [_named(x, _LEFT) for x in ctx.of(planned.index, "left")],
                # Each refused credential a person's word replaced in the run: both fingerprints.
                "credential_replaced": _replacements(Path(line["run_dir"])),
            }
        )

    def every(kind: str, keys: Sequence[str]) -> list[dict[str, Any]]:
        return [_named(x, keys) for x in ctx.lines if x["kind"] == kind]

    return {
        "format": 1,
        "round": ctx.round_id,
        "inputs": header["inputs"],
        "inputs_sha256": header["inputs_sha256"],
        "pins_at_start": header.get("pins"),
        "protected_sha256": header["protected_sha256"],
        "pins": _pins(ctx),
        "trials": trials,
        "no_cap": _no_cap(ctx, header["inputs"]["tiers"]),
        # The same count, by the name the cap rule reads it under; and the tiers where no trial
        # gives a figure, so the rule can give none of them a cap.
        "no_figure": _no_cap(ctx, header["inputs"]["tiers"]),
        "no_cap_in_the_cell": _no_cap_in_the_cell(ctx),
        "superseded": every("superseded", _SUPERSEDED),
        "left": every("left", _LEFT),
        "excluded_runs": every("excluded", _EXCLUDED),
        "credential_refused": every("credential", ("index", "attempt", "run_id", "tokens", "by")),
        "usage_limit": every("limit", ("index", "attempt", "run_id", "tokens")),
        "lock_taken_over": every("lock_taken_over", ("pid",)),
        "register_before": header["register_before"],
        "register_after": None if ended is None else ended["register_after"],
    }


def _replacements(run_dir: Path) -> list[dict[str, Any]]:
    """Each refused credential a person's word replaced in the run, as its log records them."""
    events = _events(run_dir)[1] or []
    return [
        e.credential_replaced.model_dump(mode="json")
        for e in events
        if isinstance(e, Resumed) and e.credential_replaced is not None
    ]


def _summary(ctx: _Round, *, done: bool) -> dict[str, Any]:
    """The round's counts and digests, for the output directory and the terminal.

    The visible tier's outcomes and ends are counted; of a protected tier, only how many trials
    it has and how many are assembled: its outcomes are read only through its vector, which
    counts the look.
    """
    header = ctx.lines[0]
    assembled = _assembled(ctx)
    visible = {p.index for p in ctx.order if p.tier == VISIBLE}
    tiers: dict[str, Any] = {}
    for tier in header["inputs"]["tiers"]:
        planned = [p for p in ctx.order if p.tier == tier]
        mine = [x for p, x in assembled if p.tier == tier]
        counts: dict[str, Any] = {"trials": len(planned), "assembled": len(mine)}
        if tier == VISIBLE:
            for outcome in ("pass", "fail", "flaky", "unscored", "excluded"):
                counts[outcome] = sum(1 for x in mine if x["outcome"] == outcome)
        tiers[tier] = counts

    def seen(kind: str) -> int:
        return sum(1 for x in ctx.lines if x["kind"] == kind and x.get("index") in visible)

    summary = {
        "format": 1,
        "round": ctx.round_id,
        "version": header["inputs"]["version"],
        "inputs_sha256": header["inputs_sha256"],
        "check_sha256": header["inputs"]["check_sha256"],
        "params_sha256": header["inputs"]["params_sha256"],
        "done": done,
        "tiers": tiers,
        "superseded": seen("superseded"),
        "left": seen("left"),
        "excluded_runs": seen("excluded"),
        "credential_refused": seen("credential"),
        "usage_limit": seen("limit"),
        "no_cap": _no_cap(ctx, (VISIBLE,)),
        "no_figure": _no_cap(ctx, (VISIBLE,)),
        "register_before": header["register_before"],
        "register_after": next(
            (x["register_after"] for x in ctx.lines if x["kind"] == "ended"), None
        ),
    }
    if ctx.waiting is not None and not done:
        summary["waiting"] = ctx.waiting
    if ctx.trial is not None:
        # The one trial a call named: where its set lies, and for a visible trial whether its raw
        # pair runs now. Of a protected trial that is never said outside the withheld root (it
        # tells whether the trial gives a figure): its sheet beneath the root says it.
        shown = ("index", "runs", "raw_pair") if ctx.trial["tier"] == VISIBLE else ("index", "runs")
        summary["trial"] = {k: ctx.trial[k] for k in shown}
    return summary
