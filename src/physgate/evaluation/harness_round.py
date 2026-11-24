"""The harness-arm round: every task and trial of a tier version, one harness trial each.

**What it is given.** A tier-set store, a role and a version, the tiers to run, how many trials
of each task, a seed base, the run parameters, a registered run root, a pristine target
repository to clone, the hooks' installation and the price sheet's date. Nothing names a task:
the tasks are read from the version (:func:`_version_tasks`, this module's one reader of the
store), and every place a protected task's brief, answer, score or record is written lies
beneath the role's withheld root, which every run on the store withholds.

**Everything is refused before the first trial** (:func:`_refusals`), and again each time the
round is started: inside a harness session's environment; while a session left in the work
root still runs; a store a split or a session's work has not left clean; a version the role does
not have, that the register marks exposed, or that has no record of its blind check; a run root
that is not one of the role's registered run roots; parameters that are not reportable, that do
not withhold every protected place of the store or do not look for every canary of the version
and the store; a target that is not a clean repository, or whose top holds a run's
configuration. The core refuses what it refuses besides, at each decomposition, before its call.

**The order is fixed, and written once** in the round's ledger before the first trial: the
named tiers in the version's order (visible, validation, held out), within each the tasks by
their brief's digest (a held-out task the check flagged is left out), within each task its
trials from 0. Trial ``i`` has the seed ``seed base + i``.

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

**How a trial ends** (each read from the run's own lines, never from what this process holds):

- a run that has not ended is resumed (``physgate resume``), however often it was killed;
- a run that ended on the machine (:func:`.per_role.assemble.machine_end`) is given its trial's
  one more go: a run halted on the machine with one such halt in its log is resumed once, after
  its first registered retry delay; a run whose one decomposition call ended on the machine is
  superseded by one fresh decomposition into a new run directory, after the same delay. The
  superseded run stays where it is, for the exposure scan, named in the ledger and the round's
  record with its cause and its spend, and is neither in a run set nor in any cap. A trial that
  ends on the machine after its one more go is ``unscored``;
- a run halted on the account's usage limit, whose resume the core refuses before the reset,
  stops the round as waiting for the limit (exit 75), with nothing written and the resume not
  spent; a decomposition that ended on the usage limit stops the round so too, before its fresh
  decomposition, until the round is started again with the person's word that the limit reset;
- a directory whose decomposition recorded its parameters but left no run (killed inside the
  decomposition, or refused after that record) is set aside, named in the ledger, and the
  trial's run is made again in a fresh directory: no run started, so none is restarted, and it
  is not the trial's one more go;
- any other end is the run's own, and is assembled as it is.

**What it writes:** the run set and the trial records of each tier, ``<tier>.runs.json`` and
``<tier>.trials.jsonl``, the visible tier's in the round's output directory and the protected
tiers' beneath the withheld root; one combined run set of every tier beneath the withheld root,
for ``physgate baseline run``; the round's record beneath the withheld root (the version, the
check record's and the parameters' digests, the protected tiers' digests, every trial's seed,
run, total and outcome, the superseded and set-aside runs, the pins the runs share, the
register's head before and after); and in the output directory a copy of it with counts and
digests only, and no outcome of a protected tier. It writes no line of the register.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from physgate.evaluation.baseline.record import VERSION_TIERS
from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.observe.cost import DatedSheet, price_run
from physgate.evaluation.observe.manifest import manifest_id_of, read_run_events
from physgate.evaluation.per_role.arms.compare import (
    ENDED_STEPS,
    ComparisonError,
    harness_total,
    next_step,
)
from physgate.evaluation.per_role.arms.harness import extract
from physgate.evaluation.per_role.assemble import (
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
from physgate.orchestrator.events import Event, Halted, SubtaskPlanned, parse_events
from physgate.orchestrator.params_record import RECORD_NAME as PARAMS_RECORD
from physgate.orchestrator.run_config import load_run_config
from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT

#: Beneath the role's withheld root: every round's own directory.
HARNESS_ROUNDS = "harness"
LEDGER = "ledger.jsonl"
ROUND_RECORD = "round.json"
COMBINED = "all.runs.json"
#: Inside a trial's run directory: the target's clone and the run's review root.
TARGET = "target"
REVIEW = "review"
LEDGER_FORMAT = 1
#: The tier whose run set and records lie in the output directory; the others' are withheld.
VISIBLE = "visible"

Tier = Literal["visible", "validation", "held_out"]
#: How a round left off: every trial assembled, or waiting for the account's usage limit.
Status = Literal["done", "waiting_for_limit"]
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


class Driver(Protocol):
    """Decomposes and drives one harness run: the command's exit status, nothing else."""

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


def _refusals(inputs: Inputs) -> tuple[_Version, frozenset[str], str]:
    """Everything that refuses the round before a trial starts, read now.

    Returns the version's tasks, the held-out tasks the check flagged (by their brief's digest),
    and the check record's digest.

    Raises:
        RoundError: a refusal, named by its reason; or the register cannot be read whole.
    """
    from physgate.evaluation.tiers.exposure import (
        ExposureError,
        _refuse_inside_a_session,
        exposed_versions,
        run_roots,
        versions,
    )
    from physgate.evaluation.tiers.measure import checked

    store, role = inputs.store, inputs.role
    try:
        _refuse_inside_a_session()
    except ExposureError as exc:
        raise _refuse(
            "inside_a_session", f"a round is never started from a session: {exc}"
        ) from None
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
    run_root = Path(os.path.realpath(inputs.run_root))
    if run_root not in roots:
        msg = "the run root is not one of the role's registered run roots"
        raise _refuse("run_root_not_registered", msg, run_root=str(inputs.run_root))
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


# The round. ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Planned:
    index: int
    tier: Tier
    brief_sha256: str
    trial: int
    seed: int


def _order(inputs: Inputs, found: _Version, flagged: frozenset[str]) -> list[_Planned]:
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
    }


@dataclass
class _Round:
    inputs: Inputs
    driver: Driver
    scorer: Scorer
    sleep: Callable[[float], None]
    limit_reset: bool
    round_id: str
    place: Path
    ledger: Path
    lines: list[dict[str, Any]]
    order: list[_Planned]
    tasks: dict[str, Task]
    #: What this process has done to each run, so a step that moves nothing is not taken twice.
    acted: set[tuple[Any, ...]] = field(default_factory=set)

    def add(self, line: dict[str, Any]) -> None:
        _append(self.ledger, line)
        self.lines.append(line)

    def of(self, index: int, kind: str) -> list[dict[str, Any]]:
        return [x for x in self.lines if x["kind"] == kind and x.get("index") == index]

    def run_dir(self, index: int, attempt: int) -> Path:
        return (
            Path(os.path.realpath(self.inputs.run_root)) / self.round_id / f"{index:04d}-{attempt}"
        )

    def run_id(self, index: int, attempt: int) -> str:
        return f"{self.round_id}-{index:04d}-{attempt}"

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
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Status, dict[str, Any]]:
    """Run, or go on with, the round ``inputs`` name; how it left off and its counts and digests.

    Raises:
        RoundError: the round is refused, or stopped at a step it names; nothing of a task.
    """
    found, flagged, check_sha256 = _refusals(inputs)
    target_head = _target_head(inputs.target_from)
    given = _inputs_record(inputs, target_head, check_sha256)
    order = _order(inputs, found, flagged)
    if not order:
        raise _refuse("nothing_to_run", "the named tiers hold no task the round runs")
    out = inputs.out
    withheld = withheld_root(inputs.store, inputs.role) / HARNESS_ROUNDS
    if resume:
        round_id, lines, place = _reopened(out, withheld, given, order)
    else:
        if os.path.lexists(out):
            msg = "the round's output directory exists; each round gets a directory of its own"
            raise _refuse("out_exists", msg, out=str(out))
        round_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
        place = withheld / round_id
        withheld.mkdir(mode=0o700, exist_ok=True)
        place.mkdir(mode=0o700)
        out.mkdir(mode=0o700, parents=True)
        # First, so a round killed at any later step is found again by its output directory.
        _write_whole(out / ROUND_RECORD, canonical_json({"format": 1, "round": round_id}))
        lines = []
    if not lines:
        # The parameters every trial is decomposed with, beneath the withheld root.
        shutil.copyfile(inputs.params, place / "params.json")
    copied = hashlib.sha256((place / "params.json").read_bytes()).hexdigest()
    if copied != given["params_sha256"]:
        msg = "the round's copy of its parameters is not the file it was started with"
        raise _refuse("params_changed", msg)
    ctx = _Round(
        inputs=inputs,
        driver=driver,
        scorer=scorer,
        sleep=sleep,
        limit_reset=limit_reset,
        round_id=round_id,
        place=place,
        ledger=place / LEDGER,
        lines=lines,
        order=order,
        tasks={b: t for tier in found.tasks.values() for b, t in tier.items()},
    )
    if not lines:
        header = {
            "kind": "round",
            "format": LEDGER_FORMAT,
            "round": round_id,
            "inputs": given,
            "inputs_sha256": hashlib.sha256(canonical_json(given)).hexdigest(),
            "protected_sha256": {
                tier: getattr(found.manifest, tier).sha256 for tier in PROTECTED_TIERS
            },
            "order": [vars(p) for p in order],
            "register_before": _register_head(inputs.store, inputs.role),
            "started": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        ctx.add(header)
        _write_whole(out / ROUND_RECORD, canonical_json(_summary(ctx, done=False)))
    (ctx.place / "logs").mkdir(mode=0o700, exist_ok=True)
    for planned in order:
        protected = planned.tier in PROTECTED_TIERS
        try:
            status = _trial(ctx, planned)
        except RoundError:
            raise
        except Exception as exc:
            if not protected:
                raise
            # An error of a protected trial may name its task; its tier and kind alone are said.
            msg = f"a {planned.tier} trial stopped on an error ({type(exc).__name__})"
            raise RoundError(msg, tier=planned.tier, index=str(planned.index)) from None
        if status == "waiting_for_limit":
            return status, _summary(ctx, done=False)
    _outputs(ctx)
    return "done", _summary(ctx, done=True)


def _reopened(
    out: Path, withheld: Path, given: dict[str, Any], order: list[_Planned]
) -> tuple[str, list[dict[str, Any]], Path]:
    """The round ``out`` names, held to the inputs it was started with.

    Raises:
        RoundError: ``out`` holds no round, its ledger is gone, or the inputs differ.
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
    ledger = place / LEDGER
    # A round killed before its first line took no step: it begins again from its first line.
    lines = _read_ledger(ledger) if ledger.is_file() else []
    if not lines:
        return round_id, lines, place
    if lines[0].get("kind") != "round" or lines[0].get("round") != round_id:
        raise _refuse("ledger_unreadable", "the round's ledger does not begin with its round")
    header = lines[0]
    if header.get("inputs_sha256") != hashlib.sha256(canonical_json(given)).hexdigest():
        changed = sorted(k for k in given if header.get("inputs", {}).get(k) != given[k])
        msg = "the round is resumed with other inputs than it was started with"
        raise _refuse("inputs_differ", msg, fields=",".join(changed))
    if header.get("order") != [vars(p) for p in order]:
        raise _refuse("order_differs", "the round's order is not the one its ledger holds")
    return round_id, lines, place


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


def _state(run_dir: Path) -> Literal["unmade", "left", "run"]:
    """What a trial's directory holds: nothing of a run yet, a decomposition with no run, a run.

    A decomposition records its parameters before its call: a directory without that record
    and without a log was given to no call.
    """
    if (run_dir / "events.jsonl").exists():
        return "run"
    if any(
        os.path.lexists(run_dir / name) for name in (PARAMS_RECORD, "run.json", "decomposition")
    ):
        return "left"
    return "unmade"


def _prepare(ctx: _Round, run_dir: Path) -> None:
    """Make the trial's directory afresh: the target's clone and the run's review root.

    Whatever a killed earlier preparation left there is removed first: no call was given it.
    """
    if os.path.lexists(run_dir):
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
    return ctx.place / "logs" / f"{index:04d}-{attempt}.{step}.log"


def _delay(run_dir: Path) -> float:
    delays = load_run_config(run_dir / "run.json").bounds.infra_retry_delays_s
    return float(delays[0]) if delays else 0.0


def _machine_halts(events: Sequence[Event]) -> int:
    return sum(1 for e in events if isinstance(e, Halted) and e.reason in INFRASTRUCTURE_HALTS)


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
        set_aside = {x["attempt"] for x in ctx.of(i, "left")}
        superseded = ctx.of(i, "superseded")
        last = placed[-1]["attempt"] if placed else None
        if last is None or last in set_aside or any(s["attempt"] == last for s in superseded):
            if last is not None and any(s["attempt"] == last for s in superseded):
                gone = next(s for s in superseded if s["attempt"] == last)
                if gone["cause"] == "usage_limit" and not ctx.limit_reset:
                    return "waiting_for_limit"
                ctx.sleep(float(gone["delay_s"]))
            attempt = 1 if last is None else last + 1
            ctx.add(
                {
                    "kind": "placed",
                    "index": i,
                    "attempt": attempt,
                    "run_id": ctx.run_id(i, attempt),
                    "run_dir": str(ctx.run_dir(i, attempt)),
                    "seed": planned.seed,
                }
            )
            continue
        status = _step(ctx, planned, last, once_more_taken=bool(superseded))
        if status is not None:
            return status


def _step(ctx: _Round, planned: _Planned, attempt: int, *, once_more_taken: bool) -> Status | None:
    """One step of the trial's current run, as its own lines say; ``None`` to look again."""
    i = planned.index
    run_dir = ctx.run_dir(i, attempt)
    target, review = run_dir / TARGET, run_dir / REVIEW
    state = _state(run_dir) if os.path.lexists(run_dir) else "unmade"
    if state == "unmade":
        _once(ctx, ("decompose", i, attempt), "a decomposition left nothing in its directory")
        _prepare(ctx, run_dir)
        code = ctx.driver.decompose(
            Decompose(
                brief=ctx.brief(planned),
                seed=planned.seed,
                run_id=ctx.run_id(i, attempt),
                params=ctx.place / "params.json",
                target=target,
                run_dir=run_dir,
                install=ctx.inputs.install,
                review_root=review,
                log=_log(ctx, i, attempt, "decompose"),
            )
        )
        ctx.acted.add(("decomposed", i, attempt))
        _refused_by(code, "decompose", i, attempt)
        return None
    if state == "left":
        why = "its decomposition recorded its parameters and left no run"
        ctx.add({"kind": "left", "index": i, "attempt": attempt, "why": why})
        if ("decomposed", i, attempt) in ctx.acted:
            # This process's own decomposition left it so: the round stops for a person to look,
            # and a later start makes the trial's run again in a fresh directory.
            msg = f"the trial's decomposition {why}; its output lies beneath the withheld root"
            raise _refuse("decomposition_left_no_run", msg, index=str(i), attempt=str(attempt))
        return None
    _data, events = _events(run_dir)
    if events is None or next_step(events) not in ENDED_STEPS:
        _once(ctx, ("drive", i, attempt), "a drive of the run left it where it was")
        fresh = ("decomposed", i, attempt) in ctx.acted and ("driven", i, attempt) not in ctx.acted
        ctx.acted.add(("driven", i, attempt))
        code = ctx.driver.drive(
            Drive(
                resume=not fresh,
                run_dir=run_dir,
                target=target,
                install=ctx.inputs.install,
                review_root=review,
                limit_reset=ctx.limit_reset,
                log=_log(ctx, i, attempt, "drive"),
            )
        )
        return _waits(code, "drive", i, attempt)
    halt = machine_end(events)
    if halt is not None and halt.reason == "decomposition_failed" and not once_more_taken:
        ctx.add(
            {
                "kind": "superseded",
                "index": i,
                "attempt": attempt,
                "run_id": ctx.run_id(i, attempt),
                "cause": decomposition_cause(halt),
                "tokens": TokenAccount.from_events(events).total().total(),
                "delay_s": _delay(run_dir),
            }
        )
        return None
    if (
        halt is not None
        and halt.reason != "decomposition_failed"
        and _machine_halts(events) == 1
        and not once_more_taken
    ):
        _once(ctx, ("resume", i, attempt), "the run's one resume left it where it was")
        if halt.reason != "usage_limit":
            ctx.sleep(_delay(run_dir))
        code = ctx.driver.drive(
            Drive(
                resume=True,
                run_dir=run_dir,
                target=target,
                install=ctx.inputs.install,
                review_root=review,
                limit_reset=ctx.limit_reset,
                log=_log(ctx, i, attempt, "drive"),
            )
        )
        return _waits(code, "resume", i, attempt)
    _assemble(ctx, planned, attempt, events)
    return None


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


def _assemble(ctx: _Round, planned: _Planned, attempt: int, events: list[Event]) -> None:
    """Extract, score, price and assemble the trial's ended run, then record it in the ledger.

    Raises:
        RoundError: the run is not the trial's: another run id, brief or target commit.
    """
    i = planned.index
    run_dir = ctx.run_dir(i, attempt)
    task = ctx.tasks[planned.brief_sha256]
    config = load_run_config(run_dir / "run.json")
    if (
        config.run_id != ctx.run_id(i, attempt)
        or config.brief_sha256 != planned.brief_sha256
        or config.target_head != ctx.lines[0]["inputs"]["target_head"]
    ):
        msg = "the run in the trial's directory is not the trial's"
        raise _refuse("run_not_the_trial_s", msg, index=str(i), attempt=str(attempt))
    name = f"{i:04d}-{attempt}"
    extraction = None
    if any(isinstance(e, SubtaskPlanned) for e in events):
        answer = ctx.place / "answers" / name / task.answer.path
        (ctx.place / "answers").mkdir(mode=0o700, exist_ok=True)
        extraction = extract(run_dir / TARGET, config.run_id, task.answer.path, answer)
    found = extraction is not None and extraction.status == "found"
    score: Mapping[str, Any] | None = None
    if found:
        score = ctx.scorer(task, ctx.place / "answers" / name / task.answer.path)
        (ctx.place / "scores").mkdir(mode=0o700, exist_ok=True)
        _write_whole(ctx.place / "scores" / f"{name}.json", canonical_json(dict(score)))
    unscored = False
    if not found:
        try:
            unscored = harness_ended_by_infrastructure(run_dir, task, answer_found=False)
        except TrialExcludedError:
            unscored = False  # assembled as excluded below, with its reason
    cost = price_run(run_dir, ctx.inputs.prices, review_roots=(run_dir / REVIEW,))
    manifest_id = manifest_id_of(run_dir, read_run_events(run_dir))
    record = harness_trial(
        suite=f"{ctx.inputs.role}_{planned.tier}",
        task=task,
        trial=planned.trial,
        run_dir=run_dir,
        manifest_id=manifest_id,
        cost=cost,
        score=score,
        unscored=unscored,
    )
    try:
        total: int | None = harness_total(run_dir)
        no_total = None
    except ComparisonError as exc:
        total, no_total = None, str(exc)
    ctx.add(
        {
            "kind": "assembled",
            "index": i,
            "attempt": attempt,
            "run_id": config.run_id,
            "run_dir": str(run_dir),
            "manifest_id": manifest_id,
            "answer": None if extraction is None else extraction.status,
            "unscored": unscored,
            "outcome": "excluded" if isinstance(record, ExcludedTrial) else record.outcome,
            "record": record.model_dump(mode="json"),
            "harness_total": total,
            "no_total": no_total,
        }
    )


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


def _audit(ctx: _Round) -> dict[str, Any]:
    """The round's record, beneath the withheld root: every trial, run and digest."""
    header = ctx.lines[0]
    ended = next((x for x in ctx.lines if x["kind"] == "ended"), None)
    trials = []
    for planned, line in _assembled(ctx):
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
            }
        )
    return {
        "format": 1,
        "round": ctx.round_id,
        "inputs": header["inputs"],
        "inputs_sha256": header["inputs_sha256"],
        "protected_sha256": header["protected_sha256"],
        "pins": _pins(ctx),
        "trials": trials,
        "superseded": [
            {k: x[k] for k in ("index", "attempt", "run_id", "cause", "tokens")}
            for x in ctx.lines
            if x["kind"] == "superseded"
        ],
        "left": [
            {k: x[k] for k in ("index", "attempt", "why")} for x in ctx.lines if x["kind"] == "left"
        ],
        "register_before": header["register_before"],
        "register_after": None if ended is None else ended["register_after"],
    }


def _summary(ctx: _Round, *, done: bool) -> dict[str, Any]:
    """The round's counts and digests, for the output directory and the terminal.

    The visible tier's outcomes are counted; a protected tier's are not: they are read only
    through its vector, which counts the look.
    """
    header = ctx.lines[0]
    assembled = _assembled(ctx)
    tiers: dict[str, Any] = {}
    for tier in header["inputs"]["tiers"]:
        planned = [p for p in ctx.order if p.tier == tier]
        mine = [x for p, x in assembled if p.tier == tier]
        counts: dict[str, Any] = {"trials": len(planned), "assembled": len(mine)}
        if tier == VISIBLE:
            for outcome in ("pass", "fail", "flaky", "unscored", "excluded"):
                counts[outcome] = sum(1 for x in mine if x["outcome"] == outcome)
        tiers[tier] = counts
    return {
        "format": 1,
        "round": ctx.round_id,
        "version": header["inputs"]["version"],
        "inputs_sha256": header["inputs_sha256"],
        "check_sha256": header["inputs"]["check_sha256"],
        "params_sha256": header["inputs"]["params_sha256"],
        "done": done,
        "tiers": tiers,
        "superseded": sum(1 for x in ctx.lines if x["kind"] == "superseded"),
        "left": sum(1 for x in ctx.lines if x["kind"] == "left"),
        "register_before": header["register_before"],
        "register_after": next(
            (x["register_after"] for x in ctx.lines if x["kind"] == "ended"), None
        ),
    }
