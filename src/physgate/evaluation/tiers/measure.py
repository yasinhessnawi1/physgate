"""The counting rule, and the vector writer: the harness side of measuring a protected tier.

**The counting rule** (:func:`census`) holds a tier's trial records to the run set they came
from before any of them is counted:

- the version is one of the role's, and the register, read now, does not mark it exposed;
- each run is a harness run that was measured (reportable, from a clean checkout, never an
  ablation run), listed once, and was given exactly one task of the tier, found by its brief;
- every field of :data:`physgate.evaluation.observe.compare.DRIFT` but the two that differ by
  task (:data:`PER_TASK`) is the same in every run; of those two, a task's runs share one
  target commit, while tasks may start from different ones;
- the records are the runs, one each, by task and trial, all of the harness arm, none
  excluded; and every task was run the same number of times.

It reads only the tier it is given. **The vector writer** (:func:`write_vector`) is the
harness's own step for a protected tier: given the tier's records and run set, both beneath the
role's withheld root, it counts one measurement of the version in the register and then writes
the anonymous vector (:mod:`physgate.evaluation.gaps.vector`) beside them, its tasks in an order
drawn afresh from the operating system's generator, whose seed is recorded nowhere. What holds a
session off is the place, as for the register's other writers; the writer also refuses inside a
harness session's environment, as defence in depth. It refuses, writing nothing, for an exposed
version and for a run set the rule refuses. The raw arm has no run sets yet, and is refused in
words. Nothing it says names a task.

It opens the tier's tasks to find each run's task by its brief: one of the named openers of the
protected tiers.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from physgate.evaluation.gaps.vector import VECTORS, GapsError, GapVector, TaskOutcome, vector_key
from physgate.evaluation.observe.compare import DRIFT
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.store import WITHHELD, version_dir
from physgate.evaluation.tiers.task import Role, canonical_json, parse_task
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.run_config import RunConfig, load_run_config

#: The fields of ``DRIFT`` that differ by task: they map each run to its task.
PER_TASK: tuple[str, ...] = ("brief_sha256", "target_head")
#: The fields of ``DRIFT`` every run of a role and arm shares.
HELD_EQUAL: tuple[str, ...] = tuple(f for f in DRIFT if f not in PER_TASK)
#: The most bytes a run set or a records file is read to.
MOST_INPUT_BYTES = 64 * 1024 * 1024

RAW_ARM = (
    "the raw arm has no run sets yet: its rounds record none, so its gaps are not measured "
    "until they do"
)


def _refuse(reason: str, msg: str) -> GapsError:
    return GapsError(msg, refused_because=reason)


@dataclass(frozen=True)
class Census:
    """What a tier's runs and records came to under the counting rule."""

    tier_sha256: str
    #: Each task's outcomes, by its id: kept on the harness side, never written.
    outcomes: dict[str, TaskOutcome]
    trials: int
    drift_sha256: str
    harness_commits: tuple[str, ...]
    accounts: tuple[str, ...]
    manifest_ids: tuple[str, ...]
    run_set_sha256: str
    trials_sha256: str


def _read(path: Path, what: str) -> bytes:
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MOST_INPUT_BYTES + 1)
    except OSError as exc:
        raise _refuse(f"{what}_unreadable", f"the {what} cannot be read: {exc.strerror}") from None
    if len(raw) > MOST_INPUT_BYTES:
        raise _refuse(f"{what}_unreadable", f"the {what} is larger than any is")
    return raw


def _held(config: RunConfig) -> dict[str, Any]:
    dumped = config.model_dump(mode="json")
    held: dict[str, Any] = {}
    for field in HELD_EQUAL:
        value: Any = dumped
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        held[field] = value
    return held


def _tier_tasks(store: Path, role: Role, version: str, tier: str) -> tuple[str, dict[str, str]]:
    """The tier's digest, and each of its tasks' ids by its brief's digest; nothing named."""
    from physgate.evaluation.tiers.heldout import tier_digest

    directory = version_dir(store, role, version) / tier
    found: dict[str, str] = {}
    try:
        entries = sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink())
        for entry in entries:
            task = parse_task((entry / "task.json").read_bytes())
            brief = hashlib.sha256(task.brief.encode()).hexdigest()
            if brief in found:
                msg = f"two tasks of the {tier} tier share a brief, so a run's task cannot be told"
                raise _refuse("tier_unreadable", msg)
            found[brief] = task.id
        digest = tier_digest(directory)
    except (OSError, PerRoleError) as exc:
        if isinstance(exc, GapsError):
            raise
        # The error may name a task; only the tier is said.
        raise _refuse("tier_unreadable", f"a task of the {tier} tier cannot be read") from None
    return digest, found


def _records(raw: bytes) -> list[Any]:
    from physgate.evaluation.per_role.report import TrialRecord

    found = []
    for number, line in enumerate(raw.decode(errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            shape = json.loads(line)
        except ValueError:
            shape = None
        if isinstance(shape, dict) and "reason" in shape and "outcome" not in shape:
            msg = (
                f"record {number} is an excluded trial; a run set is counted only when every "
                "trial it holds was scored"
            )
            raise _refuse("trial_excluded", msg)
        try:
            found.append(TrialRecord.model_validate_json(line))
        except ValidationError:
            msg = f"record {number} is not a trial record"
            raise _refuse("trials_unreadable", msg) from None
    return found


def census(
    store: Path,
    role: Role,
    version: str,
    tier: str,
    runs: Path,
    trials: Path,
    *,
    arm: str = "harness",
) -> Census:
    """The tier's runs and records under the counting rule, or the reason they are refused.

    ``arm`` is the arm every record must be of; its callers refuse the raw arm first.

    Raises:
        GapsError: the rule refuses them; it names a run by its place in the run set only.
        ExposureError: the register cannot be read whole.
    """
    from physgate.evaluation.baseline.runner import RunSet
    from physgate.evaluation.observe.manifest import manifest_id_of, read_run_events
    from physgate.evaluation.tiers.exposure import exposed_versions, versions

    if version not in versions(store, role):
        raise _refuse("version_unknown", f"the role has no version {version[:8]}")
    if version in exposed_versions(store, role):
        msg = (
            f"the version {version[:8]} is marked exposed as the register reads now; nothing "
            "measured on it is counted"
        )
        raise _refuse("version_exposed", msg)
    run_bytes, record_bytes = _read(runs, "run_set"), _read(trials, "trials")
    try:
        run_set = RunSet.model_validate_json(run_bytes)
    except ValidationError:
        raise _refuse("run_set_unreadable", "the run set is not one") from None
    records = _records(record_bytes)
    digest, by_brief = _tier_tasks(store, role, version, tier)
    seen: set[tuple[str, int]] = set()
    reference: dict[str, Any] | None = None
    heads: dict[str, str] = {}
    pairs: Counter[tuple[str, int]] = Counter()
    commits: set[str] = set()
    accounts: set[str] = set()
    manifests: list[str] = []
    for index, entry in enumerate(run_set.trials):
        where = f"run {index} of the run set"
        key = (os.path.realpath(entry.run_dir), entry.trial)
        if key in seen:
            raise _refuse("run_listed_twice", f"{where} is listed twice")
        seen.add(key)
        run_dir = Path(entry.run_dir)
        try:
            config = load_run_config(run_dir / "run.json")
            manifests.append(manifest_id_of(run_dir, read_run_events(run_dir)))
        except (OrchestratorError, PerRoleError, OSError):
            raise _refuse("run_unreadable", f"{where} cannot be read whole") from None
        if config.ablation or not (config.reportable and config.harness.clean):
            msg = f"{where} was not measured: an ablation run, not reportable, or not clean"
            raise _refuse("run_not_measured", msg)
        task = by_brief.get(config.brief_sha256)
        if task is None:
            raise _refuse("run_not_in_tier", f"{where} was given no task of the {tier} tier")
        held = _held(config)
        if reference is None:
            reference = held
        differ = [f for f in HELD_EQUAL if held[f] != reference[f]]
        if differ:
            msg = f"{where} differs from the first run in {', '.join(differ)}"
            raise _refuse("drift", msg)
        if heads.setdefault(task, config.target_head) != config.target_head:
            msg = f"{where} starts its task from another target commit than its task's runs"
            raise _refuse("target_head", msg)
        pairs[(task, entry.trial)] += 1
        if config.harness.commit is not None:
            commits.add(config.harness.commit)
        if config.account is not None:
            accounts.add(config.account.name)
    if any(count > 1 for count in pairs.values()):
        msg = "a task's trial is numbered twice in the run set: each trial of a task is run once"
        raise _refuse("trial_repeated", msg)
    numbered: dict[str, set[int]] = {}
    for task, trial in pairs:
        numbered.setdefault(task, set()).add(trial)
    if any(trials != set(range(len(trials))) for trials in numbered.values()):
        msg = "a task's trials are not numbered from 0, one after another"
        raise _refuse("trials_not_numbered", msg)
    recorded: Counter[tuple[str, int]] = Counter()
    for item in records:
        if item.arm != arm:
            # Counted apart, so that it can never stand in for a run's own record.
            recorded[("", -1)] += 1
            continue
        recorded[(item.task, item.trial)] += 1
    if recorded != pairs:
        msg = "the records are not the run set's runs, one each, by task and trial"
        raise _refuse("records_not_runs", msg)
    outcomes: dict[str, dict[str, int]] = {}
    for item in records:
        tally = outcomes.setdefault(
            item.task, {"passes": 0, "trials": 0, "unscored": 0, "flaky": 0}
        )
        tally["trials"] += 1
        tally["passes"] += item.outcome == "pass"
        tally["unscored"] += item.outcome == "unscored"
        tally["flaky"] += item.outcome == "flaky"
    counts = {t["trials"] for t in outcomes.values()}
    if len(counts) != 1:
        msg = "the tasks were run different numbers of times; a rate needs tasks times trials"
        raise _refuse("unequal_trials", msg)
    assert reference is not None  # a run set holds at least one run
    return Census(
        tier_sha256=digest,
        outcomes={task: TaskOutcome(**tally) for task, tally in outcomes.items()},
        trials=counts.pop(),
        drift_sha256=hashlib.sha256(canonical_json(reference)).hexdigest(),
        harness_commits=tuple(sorted(commits)),
        accounts=tuple(sorted(accounts)),
        manifest_ids=tuple(sorted(manifests)),
        run_set_sha256=hashlib.sha256(run_bytes).hexdigest(),
        trials_sha256=hashlib.sha256(record_bytes).hexdigest(),
    )


def _beneath(path: Path, root: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))


def write_vector(
    withheld: Path,
    *,
    version: str,
    tier: str,
    runs: Path,
    trials: Path,
    arm: str = "harness",
) -> str:
    """Count one measurement of ``version`` and write ``tier``'s vector; its key.

    Raises:
        GapsError: the arm, the tier, the inputs' place or the counting rule refuses it.
        ExposureError: asked for inside a session, or the register cannot be read or written.
    """
    from physgate.evaluation.tiers.exposure import (
        _refuse_inside_a_session,
        record_measurement,
        register_lines,
    )

    _refuse_inside_a_session()
    if arm != "harness":
        raise _refuse("raw_arm_has_no_run_sets", RAW_ARM)
    withheld = Path(os.path.realpath(withheld))
    store, role = withheld.parent.parent, withheld.parent.name
    if withheld.name != WITHHELD or role not in get_args(Role):
        raise _refuse("not_a_withheld_root", "the vector is written beneath a role's withheld root")
    # The register first: where it cannot be read, nothing else is.
    register_lines(store, role)  # type: ignore[arg-type]
    if tier not in get_args(GapVector.model_fields["tier"].annotation):
        raise _refuse("not_a_protected_tier", "a vector is of the validation or held-out tier")
    for path, what in ((runs, "run_set"), (trials, "trials")):
        if not _beneath(path, withheld):
            msg = f"the {what.replace('_', ' ')} is kept beneath the role's withheld root"
            raise _refuse(f"{what}_not_withheld", msg)
    found = census(store, role, version, tier, runs, trials, arm=arm)  # type: ignore[arg-type]
    tasks = list(found.outcomes.values())
    secrets.SystemRandom().shuffle(tasks)
    vector = GapVector(
        format=1,
        role=role,  # type: ignore[arg-type]
        arm="harness",
        tier=tier,  # type: ignore[arg-type]
        version=version,
        tier_sha256=found.tier_sha256,
        run_set_sha256=found.run_set_sha256,
        trials_sha256=found.trials_sha256,
        drift_sha256=found.drift_sha256,
        harness_commits=found.harness_commits,
        accounts=found.accounts,
        tasks=tuple(tasks),
    )
    raw = canonical_json(vector.model_dump(mode="json"))
    key = vector_key(raw)
    # The look is counted before the vector exists: a vector is never there uncounted.
    record_measurement(store, role, version, measured="gaps", key=key)  # type: ignore[arg-type]
    place = withheld / VECTORS
    try:
        place.mkdir(mode=0o700, exist_ok=True)
        partial = place / f".{key}.{os.getpid()}.partial"
        with partial.open("xb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        partial.replace(place / f"{key}.json")
    except OSError as exc:
        msg = f"the vector cannot be written: {exc.strerror}"
        raise _refuse("vector_unwritten", msg) from None
    return key
