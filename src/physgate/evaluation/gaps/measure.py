"""``physgate gaps``: both gaps, their counts and intervals, and the trend that records them.

**The gaps.** The reward-hacking gap is the visible pass rate minus the held-out one; the
optimiser-overfit gap is the validation pass rate minus the held-out one, a noise floor until
the optimiser runs (neither tier has been seen by anything). Each is computed for one role and
arm, over the design's tasks times trials: the visible tier from its trial records and run set,
held to the counting rule (:func:`physgate.evaluation.tiers.measure.census`); the protected
tiers only through their vectors, each verified against the measurement line its writing added
to the register, written under the same configuration as the visible runs, and of the
design's counts. The version is read for exposure again here. A rate is never shown without
its count; each gap has a task-cluster bootstrap interval, and none where a tier holds one task,
which is said in words. Unscored and flaky trials are fails, tallied beside the rate. The harness
commits and the accounts the runs ran on are given with the result. The raw arm has no run sets
yet, and is refused in words.

**The trend.** A role has one trend. One writer (:func:`append_gap_line`, ``--append``) adds
one line per run set, stamped with its ISO week, its version, the visible runs' manifest ids, the
vectors' keys and the version's measurement count (every measurement line of the version: each
is a look); it writes no register line of its own, since each vector's writing was the look.
Each line holds its place (``n``) and the digest of the line before it (``prev``), and a head
beneath the role's withheld root, where no session writes, records how many lines the trend
holds and the digest of the last; the writer holds the trend's lock (beside the head) while it
checks the file and appends. One reader (:func:`read_gap_trend`) is given the store and the role
by its caller, never by a line, and holds the trend to its chain and its head. What it returns
holds no register line, no path, no name and no reason. :func:`gap_weeks` shows a week with no
line as missing.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import statistics
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from physgate.evaluation.gaps.stats import gap_between, wilson
from physgate.evaluation.gaps.vector import (
    VECTOR_FORMAT,
    GapsError,
    GapVector,
    Sha1,
    Sha256,
    read_vector,
)

Week = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-W[0-9]{2}$")]
Count = Annotated[int, Field(ge=0)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
RoleName = Literal["control", "firmware"]
#: The second gap's label in every line, until the optimiser exists.
FLOOR = "a noise floor until the optimiser runs: neither tier has been seen by anything"
ONE_TASK = "one task: no interval"
#: The trend's head and lock beneath the role's withheld root: ``trend.head``, ``trend.lock``.
TREND = "trend"
_ZERO = "0" * 64


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class GapsDesign(_Frozen):
    """What a gaps measurement was registered as: one role and arm on one version."""

    format: Literal[1]
    seed: int
    draws: Annotated[int, Field(ge=100)]
    store: Annotated[str, StringConstraints(pattern=r"^/.+")]
    role: Literal["control", "firmware"]
    version: Sha256
    arm: Literal["harness", "raw"]
    trials: Annotated[int, Field(ge=1)]
    visible: tuple[Name, ...] = Field(min_length=1)
    held_out_tasks: Annotated[int, Field(ge=1)]
    validation_tasks: Annotated[int, Field(ge=1)] | None = None


class TierCount(_Frozen):
    """One tier's passing trials over tasks times trials, and its fails apart from plain ones."""

    passed: Count
    n: Annotated[int, Field(ge=1)]
    tasks: Annotated[int, Field(ge=1)]
    unscored: Count
    flaky: Count
    #: ``passed/n · rate % [Wilson 95 %]``: never a bare percentage.
    rate: Name


class Gap(_Frozen):
    """A gap in points of rate, its task-cluster bootstrap interval or none, said in words."""

    gap: float
    interval: tuple[float, float] | None
    words: Name
    label: Name | None = None


class GapNumbers(_Frozen):
    """Each tier's count and both gaps: what a trend line shows as numbers."""

    visible: TierCount
    validation: TierCount | None
    held_out: TierCount
    reward_hacking: Gap
    optimiser_overfit: Gap | None


class _TrendRecord(_Frozen):
    """A line of the trend file, as its one writer writes it: its place and the line before it."""

    format: Literal[1]
    n: Count
    prev: Sha256
    week: Week
    role: Literal["control", "firmware"]
    arm: Literal["harness"]
    version: Sha256
    manifest_ids: tuple[Sha256, ...] = Field(min_length=1)
    keys: dict[Literal["held_out", "validation"], Sha256]
    measurements: Annotated[int, Field(ge=1)]
    floor: Name
    numbers: GapNumbers


class GapLine(_Frozen):
    """A trend line as its reader gives it: numbers only where every vector it names is counted."""

    week: Week
    role: Literal["control", "firmware"]
    arm: Literal["harness"]
    version: Sha256
    manifest_ids: tuple[Sha256, ...]
    measurements: int
    floor: Name
    #: ``None`` when a vector the line names has no measurement line in the register.
    numbers: GapNumbers | None
    #: Why the numbers are withheld, in words; ``None`` when they are given.
    unverified: Name | None = None
    #: In words, when the line's version is marked exposed as the register reads now, or when
    #: that cannot be told; ``None`` otherwise. The line stands: what is known is said beside it.
    exposed_since: Name | None = None


class GapWeek(_Frozen):
    """An ISO week of the trend: its lines, or none, and then it is missing."""

    week: Week
    lines: tuple[GapLine, ...]
    missing: bool


class Measured(_Frozen):
    """What ``physgate gaps`` found: the line it would append, and what it says beside it."""

    numbers: GapNumbers
    store: str
    role: Literal["control", "firmware"]
    version: Sha256
    manifest_ids: tuple[Sha256, ...]
    keys: dict[Literal["held_out", "validation"], Sha256]
    measurements: int
    notes: tuple[Name, ...]
    harness_commits: tuple[Sha1, ...]
    accounts: tuple[Name, ...]


def _refuse(reason: str, msg: str) -> GapsError:
    return GapsError(msg, refused_because=reason)


def _pct(fraction: float) -> str:
    return f"{100.0 * fraction:.1f}"


def _count(per_task: Sequence[tuple[int, int, int, int]]) -> TierCount:
    passed = sum(t[0] for t in per_task)
    n = sum(t[1] for t in per_task)
    low, high = wilson(passed, n)
    return TierCount(
        passed=passed,
        n=n,
        tasks=len(per_task),
        unscored=sum(t[2] for t in per_task),
        flaky=sum(t[3] for t in per_task),
        rate=f"{passed}/{n} · {_pct(passed / n)} % [{_pct(low)}, {_pct(high)}]",
    )


def _gap(
    a: Sequence[tuple[int, int, int, int]],
    b: Sequence[tuple[int, int, int, int]],
    design: GapsDesign,
    label: str,
    floor: str | None = None,
) -> Gap:
    # Sorted, so the interval is the counts', not the order a vector was shuffled into.
    first = sorted(p / n for p, n, _, _ in a)
    second = sorted(p / n for p, n, _, _ in b)
    if len(first) == 1 or len(second) == 1:
        value = statistics.fmean(first) - statistics.fmean(second)
        return Gap(gap=value, interval=None, words=ONE_TASK, label=floor)
    value, (low, high) = gap_between(
        first,
        second,
        seed=design.seed,
        label=f"{label}:{design.role}:{design.arm}",
        draws=design.draws,
    )
    words = f"task-cluster bootstrap 95 %, {design.draws} draws, seed {design.seed}"
    return Gap(gap=value, interval=(low, high), words=words, label=floor)


def _note(tier: str, count: TierCount) -> str:
    said = tier.replace("_", " ")
    if count.tasks == 1:
        return f"{said}: 1 task, so this rate is that task's outcome"
    return f"{said}: {count.tasks} tasks, {count.n // count.tasks} trials each"


def _vector(
    path: Path, tier: str, design: GapsDesign, counted: dict[str, str], drift: str
) -> tuple[GapVector, str]:
    vector, key = read_vector(path)
    if counted.get(key) != design.version:
        msg = (
            f"the {tier.replace('_', ' ')} vector has no measurement of the version in the register"
        )
        raise _refuse("vector_unmeasured", msg)
    wanted = design.held_out_tasks if tier == "held_out" else design.validation_tasks
    if (
        vector.tier != tier
        or vector.role != design.role
        or vector.version != design.version
        or len(vector.tasks) != wanted
        or any(t.trials != design.trials for t in vector.tasks)
    ):
        msg = f"the {tier.replace('_', ' ')} vector is not of the design's tier, version or counts"
        raise _refuse("not_the_design", msg)
    if vector.format != VECTOR_FORMAT:
        msg = (
            f"the {tier.replace('_', ' ')} vector was written under the earlier rule, whose "
            "configuration digest held the digest of the role's whole withheld root, so it cannot "
            "be held to the visible runs' as they are compared now; write it again from its runs"
        )
        raise _refuse("vector_earlier_rule", msg)
    if vector.drift_sha256 != drift:
        msg = "the protected tiers' runs were not run under the visible runs' configuration"
        raise _refuse("drift", msg)
    return vector, key


def measure(
    design: GapsDesign,
    *,
    runs: Path,
    trials: Path,
    held_out: Path,
    validation: Path | None,
) -> Measured:
    """Both gaps of ``design``'s role and arm, or the reason they are not measured.

    Raises:
        GapsError: the design, the visible runs, a vector or the register refuses them.
        ExposureError: the register cannot be read whole.
    """
    from physgate.evaluation.tiers.exposure import measurements
    from physgate.evaluation.tiers.measure import RAW_ARM, census

    if design.arm != "harness":
        raise _refuse("raw_arm_has_no_run_sets", RAW_ARM)
    if (validation is None) != (design.validation_tasks is None):
        msg = "the design and the command differ on whether the validation tier is measured"
        raise _refuse("not_the_design", msg)
    store = Path(design.store)
    seen = census(store, design.role, design.version, "visible", runs, trials)
    if sorted(seen.outcomes) != sorted(design.visible) or seen.trials != design.trials:
        msg = "the visible runs are not the design's tasks times its trials"
        raise _refuse("not_the_design", msg)
    looks = measurements(store, design.role)
    # A vector is verified by a gaps measurement alone; every measurement line is a look.
    counted = {line.key: line.version for line in looks if line.measured == "gaps"}
    vectors = {"held_out": _vector(held_out, "held_out", design, counted, seen.drift_sha256)}
    if validation is not None:
        vectors["validation"] = _vector(
            validation, "validation", design, counted, seen.drift_sha256
        )
    if len({key for _, key in vectors.values()}) != len(vectors):
        raise _refuse("not_the_design", "one vector is given for two tiers")
    visible = [(t.passes, t.trials, t.unscored, t.flaky) for t in seen.outcomes.values()]
    tiers = {
        tier: [(t.passes, t.trials, t.unscored, t.flaky) for t in vector.tasks]
        for tier, (vector, _) in vectors.items()
    }
    numbers = GapNumbers(
        visible=_count(visible),
        validation=_count(tiers["validation"]) if "validation" in tiers else None,
        held_out=_count(tiers["held_out"]),
        reward_hacking=_gap(visible, tiers["held_out"], design, "gap"),
        optimiser_overfit=(
            _gap(tiers["validation"], tiers["held_out"], design, "overfit", FLOOR)
            if "validation" in tiers
            else None
        ),
    )
    shown = [("visible", numbers.visible), ("held_out", numbers.held_out)]
    if numbers.validation is not None:
        shown.insert(1, ("validation", numbers.validation))
    commits = {*seen.harness_commits}
    accounts = {*seen.accounts}
    for vector, _ in vectors.values():
        commits |= set(vector.harness_commits)
        accounts |= set(vector.accounts)
    return Measured(
        numbers=numbers,
        store=str(store),
        role=design.role,
        version=design.version,
        manifest_ids=seen.manifest_ids,
        keys={tier: key for tier, (_, key) in vectors.items()},  # type: ignore[misc]
        measurements=sum(1 for line in looks if line.version == design.version),
        notes=tuple(_note(tier, count) for tier, count in shown),
        harness_commits=tuple(sorted(commits)),
        accounts=tuple(sorted(accounts)),
    )


def iso_week(day: date) -> str:
    """``day``'s ISO week, as ``YYYY-Www``."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _monday(week: str) -> date:
    return date.fromisocalendar(int(week[:4]), int(week[6:]), 1)


def _broken(msg: str) -> GapsError:
    return _refuse("trend_broken", msg)


def _trend_bytes(path: Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise _refuse("trend_unreadable", f"the trend cannot be read: {exc.strerror}") from None


def _head_of(dir_fd: int | None) -> tuple[int, str] | None:
    """The trend's head beneath the withheld root: (lines, last digest); ``None`` if absent."""
    from physgate.evaluation.tiers.exposure import HEAD_SUFFIX, MOST_RECORD_BYTES, _Head, _read_at

    if dir_fd is None:
        return None
    raw = _read_at(dir_fd, TREND + HEAD_SUFFIX, MOST_RECORD_BYTES)
    if raw is None:
        return None
    try:
        head = _Head.model_validate_json(raw)
    except ValidationError:
        raise _broken("the trend's head is not a head") from None
    return head.lines, head.last


def _held_to_head(data: bytes, head: tuple[int, str] | None, role: str) -> list[_TrendRecord]:
    """Every line of the trend, held to its chain and to its head, each its role's, none twice.

    Raises:
        GapsError: a line is cut, is not its writer's, is out of its chain, is another role's or
            counts a run set again; the trend holds fewer or more lines than its head records,
            its last line is not the one the head records, or it has lines and no head.
    """
    recorded, last = head if head is not None else (0, _ZERO)
    lines = data.splitlines(keepends=True)
    if lines and not lines[-1].endswith(b"\n"):
        msg = (
            f"the trend's last line (line {len(lines)}) is cut: a write stopped part way through "
            f"it, before its head moved. The head records {recorded} line(s); a person removes "
            f"the bytes after the end of line {recorded}, and the trend reads again"
        )
        raise _refuse("trend_unreadable", msg)
    if lines and head is None:
        msg = (
            "the trend holds lines and the role's withheld root holds no head for it: it is not "
            "this store's and role's trend, or its head was removed"
        )
        raise _broken(msg)
    found: list[_TrendRecord] = []
    prev = _ZERO
    for number, raw in enumerate(lines, 1):
        record = _parse(raw.decode(errors="replace"), number)
        if record.n != number - 1 or record.prev != prev:
            msg = (
                f"line {number} of the trend is not where its chain puts it: a line up to it was "
                "changed, dropped or added by hand"
            )
            raise _broken(msg)
        if record.role != role:
            raise _broken(f"line {number} of the trend is another role's")
        _admit(record, found, number)
        found.append(record)
        prev = hashlib.sha256(raw).hexdigest()
    if len(found) < recorded:
        msg = (
            f"the trend holds {len(found)} line(s) and its head records {recorded}: lines have "
            "been removed. A person who can write the role's withheld root puts back the lines "
            "removed, or, if they are lost, removes the trend and its head (trend.head) together, "
            "and the trend starts again from its next line"
        )
        raise _broken(msg)
    if len(found) > recorded:
        msg = (
            f"the trend holds {len(found) - recorded} line(s) past its head: a write stopped "
            "between a line and its head, so those lines were never recorded as written. A person "
            f"removes the lines after line {recorded} and appends their run set again"
        )
        raise _broken(msg)
    if (hashlib.sha256(lines[-1]).hexdigest() if lines else _ZERO) != last:
        msg = f"line {recorded} of the trend is not the one its head records: it was changed"
        raise _broken(msg)
    return found


def _parse(raw: str, number: int) -> _TrendRecord:
    try:
        return _TrendRecord.model_validate_json(raw)
    except ValidationError:
        msg = f"line {number} of the trend is not a line its writer could have written"
        raise _refuse("trend_unreadable", msg) from None


def _admit(record: _TrendRecord, seen: Sequence[_TrendRecord], number: int) -> None:
    for earlier in seen:
        if set(earlier.manifest_ids) & set(record.manifest_ids) or set(earlier.keys.values()) & set(
            record.keys.values()
        ):
            msg = f"line {number} of the trend counts a run set or a vector again"
            raise _refuse("run_set_repeated", msg)


def _withheld_fd(store: Path, role: str) -> int | None:
    from physgate.evaluation.tiers.exposure import _dir_fd
    from physgate.evaluation.tiers.store import withheld_root

    return _dir_fd(withheld_root(store, role))  # type: ignore[arg-type]


def _read_trend(path: Path, store: Path, role: str) -> list[_TrendRecord]:
    """The trend's lines held to its head, under its lock shared where a writer ever made one."""
    from physgate.evaluation.tiers.exposure import LOCK_SUFFIX

    fd = _withheld_fd(store, role)
    try:
        lock: int | None = None
        if fd is not None:
            try:
                # Never made here: a reader leaves the withheld root as it found it.
                lock = os.open(TREND + LOCK_SUFFIX, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                lock = None
            except OSError as exc:
                raise _broken(f"the trend's lock cannot be taken: {exc.strerror}") from None
        try:
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_SH)
            return _held_to_head(_trend_bytes(path), _head_of(fd), role)
        finally:
            if lock is not None:
                os.close(lock)
    finally:
        if fd is not None:
            os.close(fd)


def append_gap_line(path: Path, found: Measured, *, today: date | None = None) -> None:
    """Append ``found`` to its role's trend at ``path``, chained, and move the trend's head.

    Under the trend's lock, beneath the role's withheld root: the whole file is held to its
    chain and its head first, so nothing is appended to a trend that was cut or edited.

    Raises:
        GapsError: the trend refuses as read (:func:`read_gap_trend`), or the run set or a
            vector is in it already.
        ExposureError: asked for inside a session; the role's withheld root is missing or a link.
    """
    from physgate.evaluation.tiers.exposure import (
        LOCK_SUFFIX,
        _refuse_inside_a_session,
        _write_head,
    )

    _refuse_inside_a_session()
    fd = _withheld_fd(Path(found.store), found.role)
    if fd is None:
        raise _broken("the role's withheld root is not there, so the trend has no head")
    try:
        try:
            lock = os.open(
                TREND + LOCK_SUFFIX, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
        except OSError as exc:
            raise _broken(f"the trend's lock cannot be taken: {exc.strerror}") from None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = _trend_bytes(path)
            seen = _held_to_head(data, _head_of(fd), found.role)
            last = data.splitlines(keepends=True)[-1] if seen else b""
            record = _TrendRecord(
                format=1,
                n=len(seen),
                prev=hashlib.sha256(last).hexdigest() if seen else _ZERO,
                week=iso_week(today or datetime.now(UTC).date()),
                role=found.role,
                arm="harness",
                version=found.version,
                manifest_ids=found.manifest_ids,
                keys=found.keys,
                measurements=found.measurements,
                floor=FLOOR,
                numbers=found.numbers,
            )
            _admit(record, seen, len(seen) + 1)
            line = record.model_dump_json().encode() + b"\n"
            with Path(path).open("ab") as out:
                out.write(line)
                out.flush()
                os.fsync(out.fileno())
            _write_head(fd, TREND, len(seen) + 1, hashlib.sha256(line).hexdigest())
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def read_gap_trend(path: Path, *, store: Path, role: RoleName) -> tuple[GapLine, ...]:
    """Every line of ``role``'s gap trend in ``store``, held to its head; the one reader.

    The store and the role are the caller's: no line names the register it is checked against.

    **What "verified" covers, exactly.** A line's numbers are given when (1) the trend is the one
    its writer wrote: every line sits in the chain from the first to the head beneath the role's
    withheld root, where no session writes, so a line edited, dropped or added by hand refuses
    the whole trend; and (2) every vector the line names is a gaps measurement of the line's
    version in the role's register. It does not mean the numbers were computed again from the
    vectors and the visible runs: the writer computed them as it appended, and the reader opens
    neither. Whoever can write the withheld root can write the head again; the place is the hold
    against that, as for the register.

    A missing file with no head is an empty trend. A line whose vectors are not all counted, or
    whose register cannot be read, is given without its numbers, and says why. A line whose
    version is marked exposed as the register reads now says so beside its numbers.

    Raises:
        GapsError: a line is cut (in words that say the repair), is not its writer's, is out of
            its chain or past its head (in words that say the repair), is another role's,
            repeats a run set or a vector, or names vectors measured on another version than
            its own; or the trend has lines and the role's withheld root no head for them.
        ExposureError: the role's withheld root is a link.
    """
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers.exposure import exposed_versions, measurements

    records = _read_trend(path, store, role)
    if not records:
        return ()
    counted: dict[str, str] | None
    try:
        counted = {
            line.key: line.version for line in measurements(store, role) if line.measured == "gaps"
        }
    except PerRoleError:
        counted = None
    exposed: frozenset[str] | None
    try:
        exposed = exposed_versions(store, role)
    except PerRoleError:
        exposed = None
    lines: list[GapLine] = []
    for number, record in enumerate(records, 1):
        unverified: str | None = None
        if counted is None:
            unverified = "the register its vectors are counted in cannot be read"
        else:
            for key in record.keys.values():
                version = counted.get(key)
                if version is not None and version != record.version:
                    msg = f"line {number} of the trend names a vector measured on another version"
                    raise _refuse("mixed_versions", msg)
                if version is None:
                    unverified = "a vector the line names has no gaps measurement in the register"
        since: str | None = None
        if exposed is None:
            since = (
                f"whether the tier version {record.version[:8]} has been seen since cannot be "
                "told: its register cannot be read whole"
            )
        elif record.version in exposed:
            since = (
                f"the tier version {record.version[:8]} is marked exposed as the register reads "
                "now: it has been seen since this line was measured"
            )
        lines.append(
            GapLine(
                week=record.week,
                role=record.role,
                arm=record.arm,
                version=record.version,
                manifest_ids=record.manifest_ids,
                measurements=record.measurements,
                floor=record.floor,
                numbers=None if unverified else record.numbers,
                unverified=unverified,
                exposed_since=since,
            )
        )
    return tuple(lines)


def gap_weeks(lines: Sequence[GapLine], *, through: date | None = None) -> tuple[GapWeek, ...]:
    """Every ISO week from the trend's first line to its last (or ``through``), missing ones too."""
    if not lines:
        return ()
    first = min(_monday(line.week) for line in lines)
    last = max(_monday(line.week) for line in lines)
    if through is not None:
        last = max(last, _monday(iso_week(through)))
    weeks = []
    day = first
    while day <= last:
        week = iso_week(day)
        here = tuple(line for line in lines if line.week == week)
        weeks.append(GapWeek(week=week, lines=here, missing=not here))
        day += timedelta(days=7)
    return tuple(weeks)
