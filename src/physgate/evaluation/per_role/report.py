"""The per-role report: every trial of every arm, as one table that is the same every time.

The input is the experiment's design, frozen in its criteria before any arm runs (the
suites, their tasks, arms and trials, the bootstrap's seed and draws, and the published
numbers to show beside ours), and one record per task, arm and trial. The output is
Markdown, written by this module alone, so the same records always give the same bytes.

**The denominator is the design's, never the records'.** A suite's denominator for an arm
is its tasks times its trials. A record missing, repeated or not in the design refuses the
report: a trial that is absent is never a trial that did not count. Every outcome that is
not a pass is a fail for its arm in the headline:

- ``flaky``: a firmware answer whose three executions split;
- ``unscored``: a firmware answer the machine ended on its first attempt and on its retry.
  Counting it as anything but a fail would let an answer gain by not being scored;
- an emulator limit the answer hit: the answer's fail, the same limits for both arms.

Each is counted beside the headline, so the reader sees how many fails are of which kind.

**Every rate is printed with its count and denominator,** never as a bare percentage:

- the trials an arm passed, with a Wilson 95 % interval;
- a task-cluster bootstrap interval of the same rate, tasks resampled whole, because the
  trials of one task are not independent;
- the tasks with at least one passing trial, with a Wilson interval;
- the paired difference between two arms, per task, bootstrapped over tasks;
- the reward-hacking gap per role and arm: visible minus held-out, each tier's tasks
  resampled on its own.

Each bootstrap draws from its own generator, seeded by the design's seed and its own
label, so adding a suite changes no other interval.

**What the gate and the reviewers caught** is counted per arm from the run's events: the
gate's blocking failures, by artefact, and those the paired reviewer had passed; the
reviews, and those that failed. On these tasks the gate checks no control or firmware
performance, so its catches can only be units and magnitudes, and the firmware's timing
is unchecked by it. The report says both, every time.

**A published number is shown beside ours, never against it,** and only with a record of
its split, protocol and scorer and of how they differ from ours, next to our own raw arm
on the same split. Without either, the report refuses.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from physgate.evaluation.per_role.base import Identifier, _Frozen
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.task import Role, TaskId, Tier

Arm = Literal["harness", "observe", "raw"]
#: The arms in the order the report shows them.
ARMS: tuple[Arm, ...] = ("harness", "observe", "raw")
#: How a trial ended for the scorer. Only ``pass`` passes.
Outcome = Literal["pass", "fail", "flaky", "unscored"]
Count = Annotated[int, Field(ge=0)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=400)]

#: The two-sided 95 % normal quantile, ``NormalDist().inv_cdf(0.975)``.
Z95 = 1.959963984540054
#: Draws per bootstrap interval, as the analysis was registered.
DRAWS = 10_000

ARM_NAMES: dict[Arm, str] = {
    "harness": "harness (gate on)",
    "observe": "harness (gate observes)",
    "raw": "raw agent",
}
GATE_SCOPE = (
    "The gate checks no control or firmware performance: on these tasks its catches can "
    "only be units and magnitudes."
)
FIRMWARE_TIMING = "Firmware timing: unchecked by the gate."


class ReportError(PerRoleError):
    """The records or the design cannot give an honest table."""


class GateCatches(_Frozen):
    """What the gate did in one trial of an arm that has it (ARCH-083's counts)."""

    checks_run: Count
    #: Distinct artefacts with a blocking failure.
    artefacts_caught: Count
    #: Of those, the artefacts the paired reviewer had passed.
    caught_after_reviewer_passed: Count


class ReviewCatches(_Frozen):
    """What the paired reviewers said in one trial of an arm that has them."""

    reviews: Count
    failed: Count
    blocked: Count

    @model_validator(mode="after")
    def _within_reviews(self) -> ReviewCatches:
        if self.failed + self.blocked > self.reviews:
            msg = "more reviews failed or blocked than ran"
            raise ValueError(msg)
        return self


class Cost(_Frozen):
    """A trial's tokens and their price, from the run's cost record."""

    #: Every token: input, cache writes, cache reads and output.
    tokens: Count
    usd: Decimal = Field(ge=0)
    #: A list price billed, or on the subscription an estimate of what the list price is.
    basis: Literal["list_price", "list_price_estimate"]
    #: Some call's price could not be read whole, so the figure may be short.
    lower_bound: bool


class ControlFlags(_Frozen):
    """What a control trial's score flagged, beside its outcome."""

    #: The loop's gain never crossed one: its phase margin is infinite and passes.
    no_gain_crossover: bool
    #: A published benchmark's secondary view: the headline plus the gain margin and
    #: overshoot its record holds, with the gain margin read as a ratio, and in dB.
    #: ``None`` on a task with no secondary view.
    full_view_ratio: bool | None = None
    full_view_db: bool | None = None

    @model_validator(mode="after")
    def _both_views_or_none(self) -> ControlFlags:
        if (self.full_view_ratio is None) != (self.full_view_db is None):
            msg = "the secondary view is read both ways, or not at all"
            raise ValueError(msg)
        return self


class FirmwareRuns(_Frozen):
    """How a firmware trial's executions went, beside its outcome."""

    #: Every execution of the answer whose guest started: three for an answer scored on
    #: its first attempt, fewer where the machine ended an attempt before its guest did.
    executions: Count
    #: Executions whose sandbox runtime wrote to its error stream: an upper bound on the
    #: runtime failing in the middle of a run, which scores as the answer's fail.
    sandbox_failed: Count
    #: Executions ended by one of the emulator's own limits: the answer's fail.
    limit_hits: Count
    #: Attempts the machine ended before the guest started, each run again once.
    infrastructure_ends: Count

    @model_validator(mode="after")
    def _within_executions(self) -> FirmwareRuns:
        if max(self.sandbox_failed, self.limit_hits) > self.executions:
            msg = "more executions failed than ran"
            raise ValueError(msg)
        return self


class TrialRecord(_Frozen):
    """One trial of one arm on one task: how it ended, what it cost, what was caught."""

    suite: Identifier
    task: TaskId
    arm: Arm
    trial: Count
    outcome: Outcome
    cost: Cost
    wall_clock_s: Annotated[float, Field(ge=0)]
    #: The gate's and the reviewers' work: present exactly on the arms that have them.
    gate: GateCatches | None = None
    review: ReviewCatches | None = None
    control: ControlFlags | None = None
    firmware: FirmwareRuns | None = None

    @model_validator(mode="after")
    def _holds_its_arm_s_shape(self) -> TrialRecord:
        harnessed = self.arm != "raw"
        if (self.gate is not None, self.review is not None) != (harnessed, harnessed):
            msg = "a harness arm records its gate and reviewers, and the raw arm neither"
            raise ValueError(msg)
        if (self.control is None) == (self.firmware is None):
            msg = "a trial is a control trial or a firmware trial"
            raise ValueError(msg)
        if self.control is not None and self.outcome in ("flaky", "unscored"):
            msg = "a control answer is scored once, so it is never flaky or unscored"
            raise ValueError(msg)
        return self


class Suite(_Frozen):
    """One set of tasks run on the same arms the same number of times."""

    name: Identifier
    label: Text
    role: Role
    tier: Tier
    tasks: tuple[TaskId, ...] = Field(min_length=1)
    arms: tuple[Arm, ...] = Field(min_length=2)
    trials: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _is_comparable(self) -> Suite:
        if len(set(self.tasks)) != len(self.tasks) or len(set(self.arms)) != len(self.arms):
            msg = f"the suite {self.name!r} names a task or an arm twice"
            raise ValueError(msg)
        if "harness" not in self.arms or "raw" not in self.arms:
            msg = f"the suite {self.name!r} compares nothing without the harness and the raw arm"
            raise ValueError(msg)
        return self


class Comparability(_Frozen):
    """How a published number was produced, and every way that differs from ours."""

    split: Text
    protocol: Text
    scorer: Text
    differences: tuple[Text, ...] = Field(min_length=1)


class Published(_Frozen):
    """A number someone else published, to be shown beside our suite on the same split."""

    suite: Identifier
    system: Text
    figure: Text
    source: Text
    record: Comparability | None = None
    warning: Text | None = None


class Design(_Frozen):
    """What the experiment registered: its suites, its analysis, the numbers shown beside."""

    experiment: Text
    seed: int
    draws: Annotated[int, Field(ge=100)] = DRAWS
    suites: tuple[Suite, ...] = Field(min_length=1)
    published: tuple[Published, ...] = ()

    @model_validator(mode="after")
    def _counts_each_task_once(self) -> Design:
        names = [s.name for s in self.suites]
        tasks = [t for s in self.suites for t in s.tasks]
        if len(set(names)) != len(names) or len(set(tasks)) != len(tasks):
            msg = "a suite is named twice, or a task is in two suites and would count twice"
            raise ValueError(msg)
        return self


def parse_design(raw: bytes) -> Design:
    """The design in ``raw``, or refused with the reason.

    Raises:
        ReportError: it is not a design.
    """
    try:
        return Design.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"the design is not one: {exc.errors()[0]['msg']}"
        raise ReportError(msg) from exc


def parse_trials(lines: Iterable[str]) -> list[TrialRecord]:
    """One record per non-empty line, or refused with the line that is not one.

    Raises:
        ReportError: a line is not a trial record.
    """
    records = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(TrialRecord.model_validate_json(line))
        except ValidationError as exc:
            msg = f"line {number} is not a trial record: {exc.errors()[0]['msg']}"
            raise ReportError(msg) from exc
    return records


# ---------------------------------------------------------------------------- the checks


def complete(design: Design, records: Sequence[TrialRecord]) -> dict[str, list[TrialRecord]]:
    """The records by suite, refused unless each suite has every task × arm × trial once.

    Raises:
        ReportError: a record is not in the design, is repeated, is of the other role, or
            a task, arm or trial the design names has no record.
    """
    suites = {s.name: s for s in design.suites}
    seen: set[tuple[str, str, str, int]] = set()
    by_suite: dict[str, list[TrialRecord]] = {name: [] for name in suites}
    for record in records:
        suite = suites.get(record.suite)
        if suite is None:
            msg = f"a record names the suite {record.suite!r}, which the design does not have"
            raise ReportError(msg, suite=record.suite)
        if (
            record.task not in suite.tasks
            or record.arm not in suite.arms
            or record.trial >= suite.trials
        ):
            msg = (
                f"a record of {record.suite!r} is for {record.task!r}, arm {record.arm!r}, "
                f"trial {record.trial}, which the suite does not run"
            )
            raise ReportError(msg, suite=record.suite, task=record.task)
        if (record.control is None) != (suite.role == "firmware"):
            msg = f"a record of {record.suite!r} is not a {suite.role} trial"
            raise ReportError(msg, suite=record.suite, task=record.task)
        key = (record.suite, record.task, record.arm, record.trial)
        if key in seen:
            msg = f"{record.task!r}, arm {record.arm!r}, trial {record.trial} is recorded twice"
            raise ReportError(msg, suite=record.suite, task=record.task)
        seen.add(key)
        by_suite[record.suite].append(record)
    for suite in design.suites:
        wanted = len(suite.tasks) * len(suite.arms) * suite.trials
        if len(by_suite[suite.name]) != wanted:
            missing = wanted - len(by_suite[suite.name])
            msg = (
                f"the suite {suite.name!r} is missing {missing} of its {wanted} trials: its "
                "denominator is its tasks times its trials, so the report cannot be written"
            )
            raise ReportError(msg, suite=suite.name)
    return by_suite


def require_comparable(design: Design) -> None:
    """Refuse a published number without its record or without our raw arm on its split.

    Raises:
        ReportError: a published number has no comparability record, or names a suite the
            design does not run with the raw arm.
    """
    suites = {s.name: s for s in design.suites}
    for item in design.published:
        if item.record is None:
            msg = (
                f"{item.system}'s published {item.figure} has no record of its split, "
                "protocol and scorer, so it is not shown"
            )
            raise ReportError(msg, system=item.system)
        suite = suites.get(item.suite)
        if suite is None or "raw" not in suite.arms:
            msg = f"{item.system}'s published number names no suite with our raw arm beside it"
            raise ReportError(msg, system=item.system)


# ------------------------------------------------------------------------------- the stats


def wilson(passed: int, n: int) -> tuple[float, float]:
    """The Wilson score 95 % interval of ``passed`` in ``n``, as fractions.

    Raises:
        ValueError: ``n`` is not positive or ``passed`` is outside ``[0, n]``.
    """
    if n <= 0 or not 0 <= passed <= n:
        msg = f"no interval for {passed} of {n}"
        raise ValueError(msg)
    p = passed / n
    z2 = Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _generator(seed: int, label: str) -> random.Random:
    # A string seed is hashed with SHA-512, so it is the same in every process.
    return random.Random(f"{seed}:{label}")


def _interval(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    count = len(ordered)
    return ordered[math.floor(0.025 * count)], ordered[math.ceil(0.975 * count) - 1]


def cluster_bootstrap(
    groups: Sequence[Sequence[float]],
    statistic: Callable[[Sequence[Sequence[float]]], float],
    *,
    seed: int,
    label: str,
    draws: int,
) -> tuple[float, float]:
    """A 95 % percentile interval of ``statistic``, each group's tasks resampled whole.

    ``groups`` holds one list of per-task values per independent sample (one for a rate or
    a paired difference, two for a gap between tiers); each is resampled with replacement
    at its own size, from one generator seeded by ``seed`` and ``label``.
    """
    rng = _generator(seed, label)
    values = []
    for _ in range(draws):
        sample = [[group[rng.randrange(len(group))] for _ in group] for group in groups]
        values.append(statistic(sample))
    return _interval(values)


def _mean_of_first(sample: Sequence[Sequence[float]]) -> float:
    return statistics.fmean(sample[0])


def _gap(sample: Sequence[Sequence[float]]) -> float:
    return statistics.fmean(sample[0]) - statistics.fmean(sample[1])


# ----------------------------------------------------------------------------- formatting


def _pct(fraction: float) -> str:
    return f"{100.0 * fraction:.1f}"


def _rate(passed: int, n: int) -> str:
    low, high = wilson(passed, n)
    return f"{passed}/{n} · {_pct(passed / n)} % [{_pct(low)}, {_pct(high)}]"


def _points(value: float) -> str:
    return f"{100.0 * value:+.1f}"


def _span(low: float, high: float) -> str:
    return f"[{_points(low)}, {_points(high)}]"


def _usd(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def _hours(seconds: float) -> str:
    return f"{seconds / 3600.0:.2f} h"


def _minutes(seconds: float) -> str:
    return f"{seconds / 60.0:.1f} min"


def _table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


# ---------------------------------------------------------------------------- the sections


def _per_task(records: Sequence[TrialRecord], tasks: Sequence[str]) -> list[float]:
    """Each task's pass rate over its trials, in the design's task order."""
    passed: dict[str, int] = dict.fromkeys(tasks, 0)
    trials: dict[str, int] = dict.fromkeys(tasks, 0)
    for record in records:
        trials[record.task] += 1
        passed[record.task] += record.outcome == "pass"
    return [passed[t] / trials[t] for t in tasks]


def _of_arm(records: Sequence[TrialRecord], arm: Arm) -> list[TrialRecord]:
    return [r for r in records if r.arm == arm]


def _arms(suite: Suite) -> list[Arm]:
    return [arm for arm in ARMS if arm in suite.arms]


def _headline(design: Design, suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    head = [
        "Arm",
        "Trials passed · Wilson 95 %",
        "Task-cluster bootstrap 95 %",
        f"Tasks passed in any of {suite.trials} · Wilson 95 %",
        "Fail",
        "Flaky",
        "Unscored",
    ]
    rows = []
    for arm in _arms(suite):
        mine = _of_arm(records, arm)
        passed = sum(r.outcome == "pass" for r in mine)
        per_task = _per_task(mine, suite.tasks)
        low, high = cluster_bootstrap(
            [per_task],
            _mean_of_first,
            seed=design.seed,
            label=f"rate:{suite.name}:{arm}",
            draws=design.draws,
        )
        any_pass = sum(rate > 0 for rate in per_task)
        rows.append(
            [
                ARM_NAMES[arm],
                _rate(passed, len(mine)),
                f"[{_pct(low)}, {_pct(high)}]",
                _rate(any_pass, len(suite.tasks)),
                str(sum(r.outcome == "fail" for r in mine)),
                str(sum(r.outcome == "flaky" for r in mine)),
                str(sum(r.outcome == "unscored" for r in mine)),
            ]
        )
    return _table(head, rows)


def _contrasts(design: Design, suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    pairs = [("harness", "raw"), ("harness", "observe"), ("observe", "raw")]
    rows = []
    for one, other in pairs:
        if one not in suite.arms or other not in suite.arms:
            continue
        mine = _per_task(_of_arm(records, one), suite.tasks)
        theirs = _per_task(_of_arm(records, other), suite.tasks)
        paired = [a - b for a, b in zip(mine, theirs, strict=True)]
        low, high = cluster_bootstrap(
            [paired],
            _mean_of_first,
            seed=design.seed,
            label=f"paired:{suite.name}:{one}-{other}",
            draws=design.draws,
        )
        rows.append(
            [
                f"{ARM_NAMES[one]} − {ARM_NAMES[other]}",
                f"{_points(statistics.fmean(paired))} points",
                f"{_span(low, high)} points",
            ]
        )
    return _table(["Paired, per task", "Difference", "Task-cluster bootstrap 95 %"], rows)


def _catches(suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    head = [
        "Arm",
        "Gate checks run",
        "Gate: artefacts caught",
        "Caught after the reviewer passed",
        "Reviews",
        "Reviews failed",
        "Reviews blocked",
    ]
    rows = []
    for arm in _arms(suite):
        mine = _of_arm(records, arm)
        if arm == "raw":
            rows.append([ARM_NAMES[arm], "—", "—", "—", "—", "—", "—"])
            continue
        gates = [r.gate for r in mine if r.gate is not None]
        reviews = [r.review for r in mine if r.review is not None]
        rows.append(
            [
                ARM_NAMES[arm],
                str(sum(g.checks_run for g in gates)),
                str(sum(g.artefacts_caught for g in gates)),
                str(sum(g.caught_after_reviewer_passed for g in gates)),
                str(sum(v.reviews for v in reviews)),
                str(sum(v.failed for v in reviews)),
                str(sum(v.blocked for v in reviews)),
            ]
        )
    return _table(head, rows)


def _cost(suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    head = [
        "Arm",
        "Tokens",
        "USD",
        "USD per trial",
        "Wall-clock",
        "Median per trial",
    ]
    rows = []
    for arm in _arms(suite):
        mine = _of_arm(records, arm)
        bases = {r.cost.basis for r in mine}
        if len(bases) != 1:
            msg = (
                f"the cost of {arm!r} on {suite.name!r} mixes a billed list price with the "
                "subscription's estimate"
            )
            raise ReportError(msg, suite=suite.name, arm=arm)
        mark = "≥ " if any(r.cost.lower_bound for r in mine) else ""
        basis = "list price" if bases == {"list_price"} else "estimate at list price"
        usd = sum((r.cost.usd for r in mine), Decimal(0))
        seconds = [r.wall_clock_s for r in mine]
        rows.append(
            [
                ARM_NAMES[arm],
                str(sum(r.cost.tokens for r in mine)),
                f"{mark}{_usd(usd)} ({basis})",
                f"{mark}{_usd(usd / len(mine))}",
                _hours(sum(seconds)),
                _minutes(statistics.median(seconds)),
            ]
        )
    return _table(head, rows)


def _count_of(records: Sequence[TrialRecord], test: Callable[[TrialRecord], bool]) -> str:
    return f"{sum(test(r) for r in records)}/{len(records)}"


def _control_notes(suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    lines = []
    parts = []
    for arm in _arms(suite):
        mine = _of_arm(records, arm)
        flagged = _count_of(mine, lambda r: r.control is not None and r.control.no_gain_crossover)
        parts.append(f"{ARM_NAMES[arm]} {flagged}")
    lines.append(
        "- Trials whose loop never crossed unity gain, so that the phase margin is infinite "
        "and passes (python-control's convention): " + "; ".join(parts) + "."
    )
    views = [r.control for r in records if r.control is not None]
    if any(v.full_view_ratio is not None for v in views):
        if any(v.full_view_ratio is None for v in views):
            msg = f"the secondary view of {suite.name!r} is read for some trials and not others"
            raise ReportError(msg, suite=suite.name)
        lines.append(
            "- The secondary view, the headline plus the gain margin and overshoot the "
            "benchmark's record holds; the record gives the gain margin no unit, so it is "
            "read both ways:"
        )
        lines.append("")
        rows = []
        for arm in _arms(suite):
            mine = _of_arm(records, arm)
            ratio = sum(r.control is not None and r.control.full_view_ratio is True for r in mine)
            db = sum(r.control is not None and r.control.full_view_db is True for r in mine)
            rows.append([ARM_NAMES[arm], _rate(ratio, len(mine)), _rate(db, len(mine))])
        lines += _table(["Arm", "Gain margin as a ratio", "Gain margin in dB"], rows)
    return lines


def _firmware_notes(suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    sandbox, limits, ends = [], [], []
    for arm in _arms(suite):
        runs = [r.firmware for r in _of_arm(records, arm) if r.firmware is not None]
        executions = sum(f.executions for f in runs)
        sandbox.append(f"{ARM_NAMES[arm]} {sum(f.sandbox_failed for f in runs)}/{executions}")
        limits.append(f"{ARM_NAMES[arm]} {sum(f.limit_hits for f in runs)}/{executions}")
        ends.append(f"{ARM_NAMES[arm]} {sum(f.infrastructure_ends for f in runs)}")
    return [
        f"- {FIRMWARE_TIMING}",
        "- An unscored answer, one the machine ended before its guest started on the first "
        "attempt and on the retry, counts as a fail for its arm; so does a flaky one, whose "
        "three executions split.",
        "- Executions whose sandbox runtime wrote to its error stream, an upper bound on the "
        "runtime failing mid-run, which scores as the answer's fail: " + "; ".join(sandbox) + ".",
        "- Executions ended by one of the emulator's own limits, the answer's fail under the "
        "same limits for both arms: " + "; ".join(limits) + ".",
        "- Attempts the machine ended before the guest started, each run once more: "
        + "; ".join(ends)
        + ".",
    ]


def _suite(design: Design, suite: Suite, records: Sequence[TrialRecord]) -> list[str]:
    lines = [
        f"### {suite.label}",
        "",
        f"`{suite.name}`: tier {suite.tier}, {len(suite.tasks)} tasks × {suite.trials} "
        f"trials per arm.",
        "",
    ]
    lines += _headline(design, suite, records)
    lines += ["", *_contrasts(design, suite, records), ""]
    lines += [*_catches(suite, records), ""]
    lines += [*_cost(suite, records), ""]
    if suite.role == "control":
        lines += _control_notes(suite, records)
    else:
        lines += _firmware_notes(suite, records)
    return [*lines, ""]


def _gaps(design: Design, role: Role, by_suite: Mapping[str, list[TrialRecord]]) -> list[str]:
    own = [s for s in design.suites if s.role == role]
    visible = [s for s in own if s.tier == "visible"]
    held = [s for s in own if s.tier == "held_out"]
    if not visible or not held:
        return []
    if len(visible) != 1 or len(held) != 1:
        msg = f"the {role} role has more than one visible or held-out suite; its gap is unclear"
        raise ReportError(msg, role=role)
    seen, unseen = visible[0], held[0]
    rows = []
    for arm in ARMS:
        if arm not in seen.arms or arm not in unseen.arms:
            continue
        mine = _of_arm(by_suite[seen.name], arm)
        theirs = _of_arm(by_suite[unseen.name], arm)
        a = _per_task(mine, seen.tasks)
        b = _per_task(theirs, unseen.tasks)
        low, high = cluster_bootstrap(
            [a, b], _gap, seed=design.seed, label=f"gap:{role}:{arm}", draws=design.draws
        )
        rows.append(
            [
                ARM_NAMES[arm],
                _rate(sum(r.outcome == "pass" for r in mine), len(mine)),
                _rate(sum(r.outcome == "pass" for r in theirs), len(theirs)),
                f"{_points(statistics.fmean(a) - statistics.fmean(b))} points",
                f"{_span(low, high)} points",
            ]
        )
    return [
        "### Reward-hacking gap: visible minus held-out",
        "",
        *_table(["Arm", "Visible", "Held-out", "Gap", "Task-cluster bootstrap 95 %"], rows),
        "",
    ]


def _beside(design: Design, by_suite: Mapping[str, list[TrialRecord]]) -> list[str]:
    if not design.published:
        return []
    suites = {s.name: s for s in design.suites}
    lines = ["## Beside, not against: published numbers", ""]
    for item in design.published:
        record = item.record
        assert record is not None  # held by require_comparable
        suite = suites[item.suite]
        ours = []
        for arm in _arms(suite):
            mine = _of_arm(by_suite[suite.name], arm)
            passed = sum(r.outcome == "pass" for r in mine)
            ours.append(f"{ARM_NAMES[arm]} {_rate(passed, len(mine))}")
        lines += [
            f"### {item.system}: {item.figure}",
            "",
            f"- Source: {item.source}.",
            f"- Ours on the same split (`{suite.name}`): " + "; ".join(ours) + ".",
            f"- Split: {record.split}",
            f"- Protocol: {record.protocol}",
            f"- Scorer: {record.scorer}",
            "- How theirs differs from ours:",
            *[f"  - {d}" for d in record.differences],
        ]
        if item.warning is not None:
            lines.append(f"- Warning: {item.warning}")
        lines.append("")
    return lines


def render(design: Design, records: Sequence[TrialRecord]) -> str:
    """The report of ``records`` under ``design``, as Markdown.

    Raises:
        ReportError: the records are not every trial the design registered, once each; a
            published number lacks its record or our raw arm beside it; or one arm's cost
            mixes a billed price with an estimate.
    """
    by_suite = complete(design, records)
    require_comparable(design)
    lines = [
        f"# Per-role results: {design.experiment}",
        "",
        "Every rate is a count of trials with its denominator, the design's tasks times its "
        "trials; any outcome but a pass is a fail. Intervals are 95 %: Wilson for counts; "
        f"bootstrap over tasks, {design.draws} draws, seed {design.seed}, for rates, paired "
        "differences and gaps.",
        "",
    ]
    for role in ("control", "firmware"):
        suites = [s for s in design.suites if s.role == role]
        if not suites:
            continue
        lines += [f"## {role.capitalize()}", "", f"> {GATE_SCOPE}"]
        if role == "firmware":
            lines.append(f"> {FIRMWARE_TIMING}")
        lines.append("")
        for suite in suites:
            lines += _suite(design, suite, by_suite[suite.name])
        lines += _gaps(design, role, by_suite)
    lines += _beside(design, by_suite)
    return "\n".join(lines).rstrip("\n") + "\n"
