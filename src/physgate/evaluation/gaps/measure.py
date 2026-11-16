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

**The trend.** One writer (:func:`append_gap_line`, ``--append``) adds one line per run set,
stamped with its ISO week, its version, the visible runs' manifest ids, the vectors' keys and
the version's measurement count; it writes no register line of its own, since each vector's
writing was the look. One reader (:func:`read_gap_trend`) checks every line: it refuses a cut
line, a run set already in the file, and a line whose vectors were measured on another version;
it verifies each line's keys against the register and gives a line's numbers only when every
key is there. What it returns holds no register line, no path, no name and no reason.
:func:`gap_weeks` shows a week with no line as missing.
"""

from __future__ import annotations

import os
import statistics
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from physgate.evaluation.gaps.stats import gap_between, wilson
from physgate.evaluation.gaps.vector import GapsError, GapVector, Sha1, Sha256, read_vector

Week = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-W[0-9]{2}$")]
Count = Annotated[int, Field(ge=0)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
#: The second gap's label in every line, until the optimiser exists.
FLOOR = "a noise floor until the optimiser runs: neither tier has been seen by anything"
ONE_TASK = "one task: no interval"


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
    """A line of the trend file, as its one writer writes it."""

    format: Literal[1]
    week: Week
    store: Annotated[str, StringConstraints(pattern=r"^/.+")]
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
    first = [p / n for p, n, _, _ in a]
    second = [p / n for p, n, _, _ in b]
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
    counted = {line.key: line.version for line in measurements(store, design.role)}
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
        measurements=sum(1 for v in counted.values() if v == design.version),
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


def _parse(raw: str, number: int) -> _TrendRecord:
    if not raw.endswith("\n"):
        msg = f"line {number} of the trend is cut: it has no end"
        raise _refuse("trend_unreadable", msg)
    try:
        return _TrendRecord.model_validate_json(raw)
    except ValidationError:
        msg = f"line {number} of the trend is not a line its writer could have written"
        raise _refuse("trend_unreadable", msg) from None


def _records(path: Path) -> list[_TrendRecord]:
    """Every line of the trend, each its writer's, no run set twice."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _refuse("trend_unreadable", f"the trend cannot be read: {exc.strerror}") from None
    found: list[_TrendRecord] = []
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        record = _parse(raw, number)
        _admit(record, found, number)
        found.append(record)
    return found


def _admit(record: _TrendRecord, seen: Sequence[_TrendRecord], number: int) -> None:
    for earlier in seen:
        if set(earlier.manifest_ids) & set(record.manifest_ids) or set(earlier.keys.values()) & set(
            record.keys.values()
        ):
            msg = f"line {number} of the trend counts a run set or a vector again"
            raise _refuse("run_set_repeated", msg)


def append_gap_line(path: Path, found: Measured, *, today: date | None = None) -> None:
    """Append ``found`` to the trend at ``path``, after checking the whole file and it.

    Raises:
        GapsError: the file holds a line its writer could not have written, or the run set
            or a vector is in it already.
    """
    record = _TrendRecord(
        format=1,
        week=iso_week(today or datetime.now(UTC).date()),
        store=found.store,
        role=found.role,
        arm="harness",
        version=found.version,
        manifest_ids=found.manifest_ids,
        keys=found.keys,
        measurements=found.measurements,
        floor=FLOOR,
        numbers=found.numbers,
    )
    seen = _records(path)
    _admit(record, seen, len(seen) + 1)
    with Path(path).open("ab") as out:
        out.write(record.model_dump_json().encode() + b"\n")
        out.flush()
        os.fsync(out.fileno())


def read_gap_trend(path: Path) -> tuple[GapLine, ...]:
    """Every line of the gap trend, each verified against its role's register; the one reader.

    A missing file is an empty trend. A line whose vectors are not all counted in the register,
    or whose register cannot be read, is given without its numbers, and says why.

    Raises:
        GapsError: a line is cut or is not its writer's, repeats a run set or a vector, or
            names vectors measured on another version than its own.
    """
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers.exposure import measurements

    registers: dict[tuple[str, str], dict[str, str] | None] = {}
    lines: list[GapLine] = []
    for number, record in enumerate(_records(path), 1):
        where = (record.store, record.role)
        if where not in registers:
            try:
                counted = measurements(Path(record.store), record.role)
                registers[where] = {line.key: line.version for line in counted}
            except PerRoleError:
                registers[where] = None
        counted_keys = registers[where]
        unverified: str | None = None
        if counted_keys is None:
            unverified = "the register its vectors are counted in cannot be read"
        else:
            for key in record.keys.values():
                version = counted_keys.get(key)
                if version is not None and version != record.version:
                    msg = f"line {number} of the trend names a vector measured on another version"
                    raise _refuse("mixed_versions", msg)
                if version is None:
                    unverified = "a vector the line names has no measurement in the register"
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
