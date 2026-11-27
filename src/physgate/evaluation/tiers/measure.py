"""The counting rule, and the vector writer: the harness side of measuring a protected tier.

**The counting rule** (:func:`census`) holds a tier's trial records to the run set they came
from before any of them is counted:

- the version is one of the role's, and the register, read now, does not mark it exposed;
- each run is a harness run that was measured (reportable, from a clean checkout, never an
  ablation run), listed once, and was given exactly one task of the tier, found by its brief;
- every field of :data:`physgate.evaluation.observe.compare.DRIFT` but the two that differ by
  task (:data:`PER_TASK`) is the same in every run, the held-out roots as ``compare`` holds
  them (the protected tiers' digests, not the store's withheld and work roots', and whether
  those two roots were named); of those two, a task's
  runs share one target commit, while tasks may start from different ones;
- every run was made from one harness commit (``harness_commit_differs`` names both);
- the records are the runs, one each, by task and trial, all of the harness arm, none
  excluded; every task of the tier that is not left out has runs (``tier_not_covered``: a
  figure of a tier is of all of it, never of a part chosen by which runs were made); and every
  task was run the same number of times;
- of the held-out tier, the version has a check record (:mod:`physgate.evaluation.tiers.checks`):
  one with none is refused (``held_out_unchecked``), since a held-out tier nobody checked is not
  scored; each task it flags is exactly one task of the tier, and is left out, its runs and
  records with it, of every count; what was left out is returned with the counts, and the
  withheld vector carries it, by digest. The visible and validation tiers are counted whole.

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

from physgate.evaluation.gaps.vector import (
    VECTOR_FORMAT,
    VECTORS,
    GapsError,
    GapVector,
    TaskOutcome,
    vector_key,
)
from physgate.evaluation.observe.compare import DRIFT, compared_held_out
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.checks import CheckError, CheckRecord, LeftOut, left_out, read_check
from physgate.evaluation.tiers.manifest import TierSet, practice_refusal
from physgate.evaluation.tiers.store import WITHHELD, version_dir
from physgate.evaluation.tiers.task import Role, canonical_json, id_digest, parse_task
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
    #: Of the held-out tier: the tasks its version's check flagged, left out of every count
    #: above, and the record that flagged them. ``None`` for the other tiers, counted whole.
    left_out: LeftOut | None = None


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
    """The fields every run of a run set shares, as they are compared; the vector's digest's."""
    dumped = config.model_dump(mode="json")
    held: dict[str, Any] = {}
    for field in HELD_EQUAL:
        value: Any = dumped
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        held[field] = value
    digests, named = compared_held_out(config)
    held["held_out_sha256"] = {"digests": list(digests), "named": [list(n) for n in named]}
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
        if isinstance(shape, dict) and shape.get("ablation") is not None:
            # An ablation trial's record says so itself: it is never counted as the measured
            # arm's, whatever run set it is given beside.
            msg = f"record {number} is an ablation trial's; no count of a measured arm holds one"
            raise _refuse("ablation_record", msg)
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
    shakedown: bool = False,
) -> Census:
    """The tier's runs and records under the counting rule, or the reason they are refused.

    ``arm`` is the arm every record must be of; its callers refuse the raw arm first. A practice
    version is refused (``practice_version``) unless ``shakedown`` says the runs are a
    shakedown's (:func:`.manifest.practice_refusal`).

    Raises:
        GapsError: the rule refuses them; it names a run by its place in the run set only.
        ExposureError: the register cannot be read whole.
    """
    from physgate.evaluation.baseline.runner import RunSet
    from physgate.evaluation.observe.manifest import manifest_id_of, read_run_events
    from physgate.evaluation.tiers.exposure import exposed_versions, run_roots, versions
    from physgate.evaluation.tiers.store import role_root

    known = versions(store, role)
    # Where the earlier runs on the store lie, every role's: a counted run withheld each whole.
    registered = {
        str(root)
        for each in get_args(Role)
        if os.path.lexists(role_root(store, each))
        for root in run_roots(store, each)
    }
    if version not in known:
        raise _refuse("version_unknown", f"the role has no version {version[:8]}")
    practice = practice_refusal(known[version], shakedown=shakedown)
    if practice is not None:
        raise _refuse(*practice)
    if version in exposed_versions(store, role):
        msg = (
            f"the version {version[:8]} is marked exposed as the register reads now; nothing "
            "measured on it is counted"
        )
        raise _refuse("version_exposed", msg)
    check = checked(store, role, known[version]) if tier == "held_out" else None
    run_bytes, record_bytes = _read(runs, "run_set"), _read(trials, "trials")
    try:
        run_set = RunSet.model_validate_json(run_bytes)
    except ValidationError:
        raise _refuse("run_set_unreadable", "the run set is not one") from None
    records = _records(record_bytes)
    digest, by_brief = _tier_tasks(store, role, version, tier)
    left = (
        None if check is None else _left_out_of(check, tuple(by_brief.values()), f"the {tier} tier")
    )
    leaving = frozenset() if left is None else left[1]
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
            manifest_id = manifest_id_of(run_dir, read_run_events(run_dir))
        except (OrchestratorError, PerRoleError, OSError):
            raise _refuse("run_unreadable", f"{where} cannot be read whole") from None
        if config.ablation or not (config.reportable and config.harness.clean):
            msg = f"{where} was not measured: an ablation run, not reportable, or not clean"
            raise _refuse("run_not_measured", msg)
        if not registered <= set(config.withheld_whole):
            msg = (
                f"{where} did not withhold whole every run root of the store, where the earlier "
                "runs on it lie: a run counted for a version withheld each of them"
            )
            raise _refuse("run_roots_not_withheld", msg)
        task = by_brief.get(config.brief_sha256)
        if task is None:
            raise _refuse("run_not_in_tier", f"{where} was given no task of the {tier} tier")
        if task in leaving:
            # A task the check flagged is left out of every count: its run is not counted.
            continue
        manifests.append(manifest_id)
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
    if len(commits) > 1:
        # One commit for every counted trial: a change of the harness between trials, however
        # small, is a condition the two sides of a count did not share.
        named = " and ".join(sorted(commits))
        msg = f"the runs were made from different harness commits ({named}); a count holds one"
        raise _refuse("harness_commit_differs", msg)
    numbered: dict[str, set[int]] = {}
    for task, trial in pairs:
        numbered.setdefault(task, set()).add(trial)
    if any(trials != set(range(len(trials))) for trials in numbered.values()):
        msg = "a task's trials are not numbered from 0, one after another"
        raise _refuse("trials_not_numbered", msg)
    if not pairs:
        msg = f"the run set holds no run of a task of the {tier} tier that is counted"
        raise _refuse("nothing_counted", msg)
    unrun = set(by_brief.values()) - leaving - set(numbered)
    if unrun:
        # A tier's figure is of every task of it but those its check left out, never of a part
        # chosen by which runs were made.
        msg = (
            f"{len(unrun)} task(s) of the {tier} tier that are not left out have no run in the "
            "run set: a tier's figure covers every task of it but those its check left out"
        )
        raise _refuse("tier_not_covered", msg)
    # A left-out task's records are left out with its runs, never counted as another's.
    records = [r for r in records if not (r.arm == arm and r.task in leaving)]
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
        left_out=None if left is None else left[0],
    )


def checked(store: Path, role: Role, manifest: TierSet) -> CheckRecord:
    """The version's check record, or the reason no held-out figure of it is counted.

    Raises:
        GapsError: the version has no record (``held_out_unchecked``: a held-out tier nobody
            checked is not scored), or its record refuses as read (its own reason).
    """
    try:
        record = read_check(store, role, manifest.version, manifest=manifest)
    except CheckError as exc:
        reason = str(exc.context.get("refused_because", "check_record_unreadable"))
        raise _refuse(reason, str(exc)) from None
    if record is None:
        raise _refuse("held_out_unchecked", unchecked(manifest.version))
    return record


def unchecked(version: str) -> str:
    """The words every refusal of a version with no check record says."""
    return (
        f"the version {version[:8]} has no record of its blind check: a held-out tier nobody "
        "checked is not scored, so nothing of it is counted until its check is recorded"
    )


def _left_out_of(
    record: CheckRecord, ids: tuple[str, ...], what: str
) -> tuple[LeftOut, frozenset[str]]:
    """What ``record`` leaves out of a tier whose tasks have ``ids``, and those tasks' ids.

    Each flagged digest is the digest of exactly one of the tier's tasks, or the record is not
    this tier's check (``check_record_not_the_tier``); nothing is named.

    Raises:
        GapsError: a flagged digest is no task's, or several tasks'.
    """
    by_digest: Counter[str] = Counter(id_digest(task) for task in ids)
    if any(by_digest[digest] != 1 for digest in record.flagged):
        msg = (
            f"the check record flags a task that is not exactly one task of {what}: it is not "
            "this tier's check"
        )
        raise _refuse("check_record_not_the_tier", msg)
    flagged = set(record.flagged)
    return left_out(record), frozenset(task for task in ids if id_digest(task) in flagged)


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
        format=VECTOR_FORMAT,
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
        left_out=found.left_out,
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
