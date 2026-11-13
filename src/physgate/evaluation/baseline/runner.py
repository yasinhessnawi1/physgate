"""The baseline round: the raw arm on every trial a set of harness runs made on a tier version.

**What it is given.** A tier-set store, a role and a version id, and the harness run set: one
entry per harness trial, its run directory and its trial number. Nothing names a task. Each
harness run recorded the digest of the brief it was given, and the round finds the run's task
as the one task of the version, in any of its three tiers, with that brief. So the run set,
which a person writes and keeps anywhere, holds no held-out or validation id.

**Everything is refused before any session starts** (:func:`plan`): a store a split or a
session's work has not left clean; a version that is not what its manifest says, or two of
whose tasks share a brief; an entry whose run no task of the version was given, that is
listed twice, or whose run's token account cannot give a cap (:func:`.arms.compare.harness_total`);
and, unless the round is a development one, a harness run that is not reportable or not from
a clean checkout.

**Each trial** runs the raw arm once (:func:`.arms.raw.run_raw`) under a setup derived from
the harness run's own record (:func:`setup_from_run`), capped at that run's total, every class
of token counted. Its answer is scored harness-side by the scorer the caller gives; a session
the machine ended before an answer existed is run once more, whole, after the harness run's
own first infrastructure delay, and if the machine ends it again it is ``unscored``. The pair
is then held equal (:func:`.arms.compare.differences`): any difference but the two a
development round names (``reportable``, ``harness``) refuses the round, with the fields
named and nothing of the task. The trial is assembled by the trial layer
(:func:`.assemble.raw_trial`), excluded where its records say so.

**Where a protected task's trial lies.** A validation or held-out task's session works outside
the store, as an authoring session's does, with a record in the role's root saying so; once
the trial is scored and compared, its whole directory (the session's record, stream, answer
and score) is moved beneath the role's withheld root, ``withheld/baseline/<round id>/``, which
every run that names the store withholds, and the record is removed. A round stopped between
leaves the record, and nothing starts on the store until a person has looked. Their trial
records go there too; the visible tier's lie in the round's own directory.

**What it writes,** beside the visible trials: ``evaluation/tiers.json`` and ``baseline.json``
(:mod:`.record`), each a new file, counts and digests only.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from physgate.evaluation.baseline.record import (
    BASELINE_RECORD,
    TIERS_RECORD,
    BaselineRecord,
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
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.manifest import TierSet, read_version
from physgate.evaluation.tiers.store import (
    WORKING,
    leftover_refusal,
    make_role_root,
    role_root,
    version_dir,
    withheld_root,
)
from physgate.evaluation.tiers.task import PROTECTED_TIERS, Role, Task, canonical_json, parse_task
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.oslayer.probe import Absent, Present

#: Where a round's protected trials lie, beneath the role's withheld root.
BASELINE_DIR = "baseline"
#: The differences a development round is held to without refusing: the harness run's own
#: state. Every other one refuses any round.
DEVELOPMENT_DIFFERENCES = frozenset({"reportable", "harness"})
TRIALS = "trials.jsonl"
SCORE = "score.json"

TierName = Literal["visible", "validation", "held_out"]
#: The version's three tiers, in the order the split writes them.
VERSION_TIERS: tuple[TierName, ...] = ("visible", "validation", "held_out")


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
) -> RawSetup:
    """The raw arm's setup, every pin taken from the harness run's own record.

    What the record names, the raw session is given: the binary's version, the role's model,
    effort, output-token limit, reasoning display, bounds, endpoint, held-out roots and
    canaries and network. What this machine supplies (the binary, the credential, the
    installation, the OS layer and the interpreter as measured now) is compared with the
    record afterwards, never assumed equal.

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
        base_url=None if config.endpoint == "default" else config.endpoint,
        install_bin=install_bin,
        role_python=role_python,
        held_out=tuple(config.held_out),
        held_out_canaries=tuple(config.held_out_canaries),
        network=config.network,
        os_layer=os_layer,
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


def plan(
    store: Path, role: Role, version: str, runs: RunSet, *, development: bool = False
) -> tuple[TierSet, list[Planned]]:
    """Every harness trial of ``runs``, read and found, or the round refused before it starts.

    Raises:
        BaselineError: the store, the version or an entry refuses the round; it names the
            entry by its place in the run set, never by its task.
    """
    refusal = leftover_refusal(store)
    if refusal is not None:
        raise BaselineError(refusal[1], refused_because=refusal[0])
    directory = version_dir(store, role, version)
    manifest = read_version(directory)
    tasks = _tasks(directory)
    planned: list[Planned] = []
    seen: set[tuple[str, int]] = set()
    for index, entry in enumerate(runs.trials):
        where = {"entry": str(index)}
        key = (os.path.realpath(entry.run_dir), entry.trial)
        if key in seen:
            msg = "a harness trial is listed twice in the run set"
            raise BaselineError(msg, **where)
        seen.add(key)
        run_dir = Path(entry.run_dir)
        config = load_run_config(run_dir / "run.json")
        found = tasks.get(config.brief_sha256)
        if found is None:
            msg = "the harness run was given no task of this version"
            raise BaselineError(msg, **where)
        tier, task = found
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
        planned.append(Planned(index, entry, config, task, tier, cap))
    return manifest, planned


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

    def counts(self) -> TierCounts:
        return TierCounts(**vars(self))


def _working(root: Path, name: str, work: Path) -> Path:
    """Record inside the role's root ``root`` that ``work`` is out of it, as an author's is.

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


def _secure(work: Path, place: Path) -> None:
    """Move a protected trial's whole directory beneath the withheld root."""
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
    version: str,
    runs: RunSet,
    out: Path,
    setup_for: SetupFor,
    score: Scorer,
    prices: DatedSheet,
    arm: Arm = run_raw,
    sleep: Callable[[float], None] = time.sleep,
    development: bool = False,
) -> BaselineRecord:
    """Run the raw arm on every trial of ``runs``, and write the round's records under ``out``.

    ``out`` is new: a round gets a directory of its own, and its records are never replaced.

    Raises:
        BaselineError: the round was refused before it started, or stopped by a pair that
            differs in more than the harness, or by trials that ran under different pins.
    """
    if out.exists():
        msg = "the round's directory exists; each round gets a directory of its own"
        raise BaselineError(msg, out=str(out))
    manifest, planned = plan(store, role, version, runs, development=development)
    out.mkdir(mode=0o700, parents=True)
    round_id = secrets.token_hex(8)
    protected_root = withheld_root(store, role) / BASELINE_DIR / round_id
    tallies = {tier: _Tally() for tier in VERSION_TIERS}
    pins: dict[str, Any] | None = None
    for trial in planned:
        protected = trial.tier in PROTECTED_TIERS
        record, line = _one_trial(
            trial,
            out=out,
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
    tiers = tiers_record(manifest)
    baseline = BaselineRecord(
        format=1,
        id=round_id,
        created=datetime.now(UTC).strftime("%Y-%m-%d"),
        tiers=tiers,
        pins=pins,
        pin_set_sha256=pin_set_sha256(pins),
        development=development,
        harness_runs=len({p.entry.run_dir for p in planned}),
        counts={tier: tallies[tier].counts() for tier in VERSION_TIERS},
    )
    write_new(out / TIERS_RECORD, record_bytes(tiers))
    write_new(out / BASELINE_RECORD, record_bytes(baseline))
    return baseline


def _one_trial(
    trial: Planned,
    *,
    out: Path,
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
    for attempt in (1, 2):
        name = f"{trial.index:04d}-{attempt}"
        work = out / "work" / name
        working = (
            _working(role_root(store, role), f"baseline-{name}", work)
            if protected_root is not None
            else None
        )
        record = arm(task, setup_for(trial.config, role), work, cap=trial.cap)
        stream = work / "session" / "stdout.jsonl"
        answer = work / "answer" / task.answer.path
        scored: Mapping[str, Any] | None = None
        if record.get("answer") == "found":
            scored = score(task, answer)
            write_new(work / SCORE, canonical_json(dict(scored)))
        machine = False
        if scored is None:
            try:
                machine = raw_ended_by_infrastructure(record, stream, task)
            except TrialExcludedError:
                machine = False  # assembled as excluded below, with its reason
        if machine and attempt == 1:
            _finish(work, working, protected_root, name)
            sleep(delays[0] if delays else 0.0)
            continue
        found = differences(run_dir, work, role=role, task=task)
        allowed = DEVELOPMENT_DIFFERENCES if development else frozenset()
        named = sorted({f.split(":", 1)[0] for f in found} - allowed)
        if named:
            _finish(work, working, protected_root, name)
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
        _finish(work, working, protected_root, name)
        return record, line
    msg = "a trial ran past its one re-run"  # unreachable: the second attempt always returns
    raise BaselineError(msg, entry=str(trial.index))


def _finish(work: Path, working: Path | None, protected_root: Path | None, name: str) -> None:
    """Move a protected trial's directory beneath the withheld root, then clear its record."""
    if protected_root is None or working is None:
        return
    _secure(work, protected_root / name)
    working.unlink()
