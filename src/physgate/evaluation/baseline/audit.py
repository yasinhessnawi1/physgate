"""The record audit: every record of a cell re-derived from its runs' and sessions' own files.

A cell is a set of harness trials and the raw trials the baseline round ran on them. Each record
a round wrote is derived again here from the files its trial left, by the same functions that
wrote it, and the two are compared. A difference is a record defect: it is named by its kind
(:data:`KINDS`) and by the trial's place in its run set, and the audit fails.

**The raw arm** (:func:`audit_raw`) is re-derived as the round derived it. Every session the
round kept of an entry is read again in order, each one's end read by the round's own rule
(:func:`.runner.machine_end`, :func:`.runner.next_step`); the session the rule records is scored
again by the scorer given (the one the round ran), and its record assembled by the round's own
assembly (:func:`.runner.trial_line`). Each tier's counts are summed again by the round's own
sum (:func:`.runner.tally`) and held to its ``baseline.json``. Every input but the scorer's run is
a file the session or the round left: the record the raw arm wrote (``raw.json``), the stream,
the copied answer, and the harness run's token account for the cap.

**The harness arm** (:func:`audit_harness`) is re-derived from each run's own directory by the
harness round's own step (:func:`.harness_round.assemble_trial`): the answer its run branch
holds in the module directories its plan names, scored again, the run's cost priced again from
its log, whether the machine ended it read again, and the record assembled again.

**What it cannot re-derive.** The raw arm's own record of a session (its end, exit, tokens,
wall clock, whether a canary showed, what the end check found) is the source, not a result: it
is read, never re-derived. So is a harness run's event log. A score is re-derived with the
scorer of this environment: one whose libraries differ from the round's may differ. The round's
id and date, its ledger's times (when it waited, and for how long), and the check, made after
each session, that the pair was equal (the session's place is moved by then) are not re-derived.

**What it says.** Of a visible tier, each difference by kind and the trial's place in its run
set; of a protected tier, how many of each kind, and nothing else: no task, no path, no score,
no place. The whole detail, places of protected trials included, is written beneath the role's
withheld root, and its digest is said.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from physgate.evaluation.baseline.record import (
    BASELINE_RECORD,
    EXTERNAL_TIERS,
    VERSION_TIERS,
    BaselineRecord,
    ExternalSetRecord,
    SourceTier,
)
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    PLACE,
    TRIALS,
    WORK,
    BaselineError,
    Ledger,
    Planned,
    RunSet,
    Scorer,
    _check_of,
    _coverage,
    _tasks,
    machine_end,
    next_step,
    plan,
    read_lines,
    read_record,
    tallied,
    trial_line,
)
from physgate.evaluation.observe.cost import DatedSheet
from physgate.evaluation.per_role.assemble import ExcludedTrial
from physgate.evaluation.per_role.report import TrialRecord
from physgate.evaluation.tiers.store import version_dir, withheld_root
from physgate.evaluation.tiers.task import PROTECTED_TIERS, Role, Task, canonical_json
from physgate.orchestrator.run_config import load_run_config

#: Every kind of difference the audit names, each the field or the step that differs:
#: - ``missing``: the files give a record the round did not write; ``extra``: the round wrote a
#:   record the files do not give;
#: - ``excluded``: one is an excluded trial and the other is not;
#: - ``outcome``, ``reason`` (an exclusion's), ``cost``, ``wall_clock``, ``control`` (the control
#:   flags), ``gate``, ``review``: that field of the record;
#: - ``count``: a tier's count in the round's ``baseline.json``;
#: - ``sessions``: sessions kept after the one the round's rule records;
#: - ``unrederivable``: a file the record is derived from cannot be read, or the scorer or the
#:   assembly refused it (its kind only is kept).
KINDS = (
    "missing",
    "extra",
    "excluded",
    "outcome",
    "reason",
    "cost",
    "wall_clock",
    "control",
    "gate",
    "review",
    "count",
    "sessions",
    "unrederivable",
)
#: The kind of a difference in each field of a record.
FIELD_KINDS = {
    "outcome": "outcome",
    "reason": "reason",
    "cost": "cost",
    "wall_clock_s": "wall_clock",
    "control": "control",
    "gate": "gate",
    "review": "review",
}

Arm = Literal["raw", "harness"]


class AuditError(BaselineError):
    """The audit cannot be made, for a reason it names: no task, no path of a protected trial."""


@dataclass(frozen=True)
class Difference:
    """One record defect: the arm, the tier, its kind and the trial's place in its run set."""

    arm: Arm
    tier: SourceTier
    kind: str
    #: The trial's place in its run set; ``None`` for a tier's count.
    index: int | None
    #: The count that differs, for ``count``; ``None`` otherwise.
    field: str | None = None

    def detail(self) -> dict[str, Any]:
        """The whole difference, as written beneath the withheld root."""
        return {
            "arm": self.arm,
            "tier": self.tier,
            "kind": self.kind,
            "index": self.index,
            "field": self.field,
        }


Line = TrialRecord | ExcludedTrial


def _key(line: Line) -> tuple[str, str, str, int]:
    return (line.suite, line.task, line.arm, line.trial)


def compare(
    arm: Arm,
    tier: SourceTier,
    derived: Mapping[int, Line],
    written: Sequence[Line],
) -> list[Difference]:
    """The differences between the records the files give and those a round wrote, of one tier.

    Records are matched by suite, task, arm and trial number; a derived record's place is its
    entry's. A written record that matches none is ``extra``, and is said with no place.

    Raises:
        AuditError: two records of one side share their suite, task, arm and trial.
    """
    by_key: dict[tuple[str, str, str, int], tuple[int, Line]] = {}
    for index, line in derived.items():
        if _key(line) in by_key:
            msg = "two entries give records of one task and trial; they cannot be told apart"
            raise AuditError(msg, refused_because="entries_not_apart")
        by_key[_key(line)] = (index, line)
    seen: set[tuple[str, str, str, int]] = set()
    found: list[Difference] = []
    for line in written:
        key = _key(line)
        if key in seen:
            msg = "the round wrote two records of one task and trial"
            raise AuditError(msg, refused_because="records_not_apart")
        seen.add(key)
        if key not in by_key:
            found.append(Difference(arm, tier, "extra", None))
            continue
        index, given = by_key[key]
        found += [Difference(arm, tier, kind, index) for kind in _kinds(given, line)]
    found += [
        Difference(arm, tier, "missing", index)
        for key, (index, _) in by_key.items()
        if key not in seen
    ]
    return found


def _kinds(derived: Line, written: Line) -> list[str]:
    """The kinds in which two records of one trial differ, in :data:`KINDS`' order."""
    if type(derived) is not type(written):
        return ["excluded"]
    one, two = derived.model_dump(mode="json"), written.model_dump(mode="json")
    kinds = {
        FIELD_KINDS.get(name, "other")
        for name in one.keys() | two.keys()
        if one.get(name) != two.get(name)
    }
    return [kind for kind in (*KINDS, "other") if kind in kinds]


def _sessions(trial: Planned, out: Path, protected_root: Path) -> list[int]:
    """The numbers of the sessions the round kept of ``trial``'s entry, in order."""
    place = protected_root if trial.tier in PROTECTED_TIERS else out / WORK
    pattern = re.compile(rf"{trial.index:04d}-([0-9]+)")
    if not place.is_dir():
        return []
    return sorted(
        int(found.group(1)) for entry in place.iterdir() if (found := pattern.fullmatch(entry.name))
    )


def _rederive_raw(
    trial: Planned,
    sessions: list[int],
    *,
    role: Role,
    out: Path,
    protected_root: Path,
    prices: DatedSheet,
    score: Scorer,
) -> tuple[tuple[Mapping[str, Any], Line] | None, list[str]]:
    """The record the round's rule gives of ``trial`` from its kept sessions, and any oddity."""
    spent = False
    result: tuple[Mapping[str, Any], Line] | None = None
    odd: list[str] = []
    for session in sessions:
        name = f"{trial.index:04d}-{session}"
        directory = (protected_root if trial.tier in PROTECTED_TIERS else out / WORK) / name
        harness, stream = directory / "harness", directory / PLACE / "session" / "stdout.jsonl"
        if result is not None:
            odd.append("sessions")  # a session after the one recorded
            break
        record = read_record(harness)
        end, _ = machine_end(record, stream, trial.task)
        step = next_step(end, spent)
        if step == "once_more":
            spent = True
            continue
        if step != "record":
            continue  # a wait: no trial, never scored
        scored = None
        if record.get("answer") == "found":
            scored = score(trial.task, harness / "answer" / trial.task.answer.path)
        line = trial_line(trial, role, record, stream, prices, scored, unscored=end == "machine")
        result = (record, line)
    return result, odd


def audit_raw(
    *,
    store: Path,
    role: Role,
    runs: RunSet,
    out: Path,
    prices: DatedSheet,
    score: Scorer,
    version: str | None = None,
    external: Path | None = None,
    base_url: str | None = None,
    development: bool = False,
) -> list[Difference]:
    """Every record of the baseline round in ``out``, re-derived and compared.

    Given the round's own inputs; the plan is read again (:func:`.runner.plan`), so each
    entry's task, tier and cap are found as the round found them.

    Raises:
        BaselineError: the round's plan, ledger or a record is refused as read.
    """
    ledger = Ledger.read(out)
    source, planned = plan(
        store, role, version, runs, base_url=base_url, development=development, external=external
    )
    round_id = str(ledger.lines[0]["round"])
    protected_root = withheld_root(store, role) / BASELINE_DIR / round_id
    counted = EXTERNAL_TIERS if isinstance(source, ExternalSetRecord) else VERSION_TIERS
    derived: dict[SourceTier, dict[int, Line]] = {tier: {} for tier in counted}
    found: list[Difference] = []
    summed: list[tuple[Planned, Mapping[str, Any], Line]] = []
    for trial in planned:
        sessions = _sessions(trial, out, protected_root)
        try:
            result, odd = _rederive_raw(
                trial,
                sessions,
                role=role,
                out=out,
                protected_root=protected_root,
                prices=prices,
                score=score,
            )
        except Exception:  # noqa: BLE001 - its kind alone is kept; the record is not derived
            found.append(Difference("raw", trial.tier, "unrederivable", trial.index))
            continue
        found += [Difference("raw", trial.tier, kind, trial.index) for kind in odd]
        if result is not None:
            derived[trial.tier][trial.index] = result[1]
            summed.append((trial, result[0], result[1]))
    written = {
        tier: [
            line
            for line in read_lines((protected_root if tier in PROTECTED_TIERS else out) / TRIALS)
            if line.suite == f"{role}_{tier}"
        ]
        for tier in counted
    }
    for tier in counted:
        found += compare("raw", tier, derived[tier], written[tier])
    found += _counts(store, role, source, planned, counted, out, tallied(summed, counted))
    return found


def _counts(
    store: Path,
    role: Role,
    source: Any,  # noqa: ANN401 - a version's manifest or an external set's record
    planned: list[Planned],
    counted: tuple[SourceTier, ...],
    out: Path,
    tallies: Mapping[SourceTier, Any],
) -> list[Difference]:
    """Each tier's counts summed again, held to the round's ``baseline.json``."""
    path = out / BASELINE_RECORD
    try:
        written = BaselineRecord.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return [Difference("raw", tier, "count", None, "record") for tier in counted]
    check = None if isinstance(source, ExternalSetRecord) else _check_of(store, role, source)
    flagged = 0 if check is None else len(check.flagged)
    found = []
    for tier in counted:
        again = tallies[tier].counts(**_coverage(source, planned, tier, flagged))
        one, two = again.model_dump(mode="json"), written.counts[tier].model_dump(mode="json")
        found += [
            Difference("raw", tier, "count", None, name)
            for name in sorted(one.keys() | two.keys())
            if one.get(name) != two.get(name)
        ]
    return found


def rederive_harness_trial(
    run_dir: Path,
    task: Task,
    *,
    role: Role,
    tier: SourceTier,
    trial: int,
    prices: DatedSheet,
    score: Scorer,
    place: Path,
) -> Line:
    """A harness trial's record, derived again from its run's own directory by the round's own step.

    The step that wrote it (:func:`.harness_round.assemble_trial`) is run again on the run's log
    as the round reads it, its answer taken from the run branch into ``place`` and scored again,
    its score not kept.

    Raises:
        AuditError: the run's log cannot be read whole.
    """
    from physgate.evaluation.harness_round import assemble_trial, run_events

    events = run_events(run_dir)
    if events is None:
        msg = "the run's log cannot be read whole"
        raise AuditError(msg, refused_because="log_unread")
    return assemble_trial(
        run_dir,
        task,
        events,
        role=role,
        tier=tier,
        trial=trial,
        prices=prices,
        scorer=score,
        place=place,
        name="audit",
        keep_score=False,
    ).record


@dataclass(frozen=True)
class HarnessCell:
    """One tier of the harness arm's cell: its run set and the records written of it."""

    tier: SourceTier
    runs: RunSet
    trials: Path


def audit_harness(
    *,
    store: Path,
    role: Role,
    version: str,
    cells: Sequence[HarnessCell],
    prices: DatedSheet,
    score: Scorer,
    scratch: Path,
) -> list[Difference]:
    """Every harness trial record of ``cells``, re-derived from its run's directory and compared.

    Each run's answer is taken from its run branch into ``scratch`` (a directory beneath the
    role's withheld root, removed after) and scored again (:func:`rederive_harness_trial`).

    Raises:
        BaselineError: the version, a run's record or the records written are refused as read.
    """
    tasks = _tasks(version_dir(store, role, version))
    found: list[Difference] = []
    try:
        for cell in cells:
            derived: dict[int, Line] = {}
            for index, entry in enumerate(cell.runs.trials):
                here = scratch / secrets.token_hex(8)
                try:
                    derived[index] = _harness_entry(
                        Path(entry.run_dir),
                        entry.trial,
                        tasks,
                        cell=cell,
                        role=role,
                        prices=prices,
                        score=score,
                        here=here,
                    )
                except Exception:  # noqa: BLE001 - its kind alone is kept
                    found.append(Difference("harness", cell.tier, "unrederivable", index))
                finally:
                    shutil.rmtree(here, ignore_errors=True)
            found += compare("harness", cell.tier, derived, read_lines(cell.trials))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return found


def _harness_entry(
    run_dir: Path,
    trial: int,
    tasks: Mapping[str, tuple[SourceTier, Task]],
    *,
    cell: HarnessCell,
    role: Role,
    prices: DatedSheet,
    score: Scorer,
    here: Path,
) -> Line:
    """One harness trial's record, derived again into ``here``."""
    config = load_run_config(run_dir / "run.json")
    tier, task = tasks[config.brief_sha256]
    if tier != cell.tier:
        msg = "the run's task is of another tier than the cell's"
        raise AuditError(msg, refused_because="tier")
    here.mkdir(mode=0o700, parents=True)
    return rederive_harness_trial(
        run_dir,
        task,
        role=role,
        tier=cell.tier,
        trial=trial,
        prices=prices,
        score=score,
        place=here,
    )


def said(found: Sequence[Difference]) -> dict[str, Any]:
    """What the audit prints: a visible tier by kind and place; a protected one counted by kind."""
    out: dict[str, Any] = {}
    for arm in ("harness", "raw"):
        for tier in (*VERSION_TIERS, *EXTERNAL_TIERS):
            these = [d for d in found if d.arm == arm and d.tier == tier]
            if not these:
                continue
            if tier in PROTECTED_TIERS:
                out[f"{arm}.{tier}"] = dict(sorted(Counter(d.kind for d in these).items()))
            else:
                out[f"{arm}.{tier}"] = sorted(
                    ({"kind": d.kind, "index": d.index, "field": d.field} for d in these),
                    key=lambda d: (d["kind"], -1 if d["index"] is None else d["index"]),
                )
    return out


def detail_bytes(found: Sequence[Difference]) -> bytes:
    """The whole detail, places of protected trials included: written beneath the withheld root."""
    rows = sorted(
        (d.detail() for d in found),
        key=lambda d: (d["arm"], d["tier"], d["kind"], -1 if d["index"] is None else d["index"]),
    )
    return canonical_json({"format": 1, "differences": rows})


def write_detail(store: Path, role: Role, found: Sequence[Difference]) -> str:
    """Write the whole detail beneath the role's withheld root, once; its digest."""
    data = detail_bytes(found)
    digest = hashlib.sha256(data).hexdigest()
    place = withheld_root(store, role) / BASELINE_DIR / "audits"
    place.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = place / f"{digest}.json"
    if not path.exists():
        path.write_bytes(data)
    return digest


def printed(found: Sequence[Difference], digest: str) -> str:
    """The audit's one line: the differences as :func:`said`, how many, and the detail's digest."""
    return json.dumps(
        {"format": 1, "differences": said(found), "total": len(found), "detail_sha256": digest},
        sort_keys=True,
    )
