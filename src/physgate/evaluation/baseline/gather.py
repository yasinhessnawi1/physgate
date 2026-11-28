"""The gatherer: a cell's harness records and each pair's one raw record, as the report reads them.

A cell's raw trials are run one baseline round at a time (each raw trial right after its harness
trial, the trials that give no figure together at the cell's end, a once-more as a round of its
own), so the cell's records lie in many rounds. The gatherer (:func:`gather`) brings them into one
file of trial records, the per-role report's input, and refuses a cell that cannot be counted:

- **The cell is a harness round's own.** It is given the harness round's run set of one tier,
  and every entry must be a draw that round kept, of the harness as measured (never an ablation
  arm's), and the set must be exactly the one the round's ledger gives for the tier, in its
  order, the round ended (:func:`.pairs.round_cell`). Its harness records are the ones the round
  assembled.
- **A cell is its first harness round's.** Another harness round that holds places of the
  harness as measured of the same tier of the same version, and is no shakedown, is a second run
  of the cell: the cell is counted from the round that started first, by the start each round's
  ledger records, and a later round is refused naming the earlier one
  (``cell_has_an_earlier_round``), so no person counts the round they prefer. Where the order
  cannot be told (the same start, or a ledger that records no start or no version), each is
  refused. The first round is gathered as it is: a later round changes nothing of it.
- **Each pair has one counted raw record.** Each harness trial's raw rounds are found by the pair
  register beneath the withheld root (:mod:`.pairs`), by the harness trial, never by a round's
  name or a set's file name. A record is counted where its round recorded it and no once-more
  round runs its entry in its place. A pair with none (``pair_without_record``) or with two
  (``pair_counted_twice``) refuses the cell, named by its place in the cell's run set; so does a
  record held to a draw its harness round did not keep, a round whose own ledger cannot be read
  as its own, and a raw round not ended. A development round writes no line in the register, so
  none of its records is ever found.
- **Nothing excluded is counted.** An excluded record of either arm refuses the cell
  (``trial_excluded``): the cell then has no verdict, as the criteria say.
- **One commit.** Every harness run and every raw record names the harness commit it ran from;
  two commits refuse the cell (``harness_commit_differs``, naming both), and a record that names
  none refuses it too. A practice round is held the same.

What it prints is counts and digests: never an outcome, a task or a score. A protected tier's
gathered records are written beneath the role's withheld root, or not at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from physgate.evaluation.baseline.pairs import (
    HarnessRound,
    HarnessRounds,
    PairError,
    baseline_lines,
    claims,
    round_cell,
    standing,
)
from physgate.evaluation.baseline.record import BASELINE_RECORD, BaselineRecord
from physgate.evaluation.baseline.runner import (
    BASELINE_DIR,
    HARNESS,
    LEDGER,
    WORK,
    BaselineError,
    Ledger,
    RunSet,
    TierName,
    _earlier_line,
    _require_unexposed,
    _tasks,
    read_record,
)
from physgate.evaluation.per_role.assemble import ExcludedTrial
from physgate.evaluation.per_role.report import TrialRecord
from physgate.evaluation.tiers.manifest import practice_refusal, read_version
from physgate.evaluation.tiers.store import version_dir, withheld_root
from physgate.evaluation.tiers.task import PROTECTED_TIERS, Role
from physgate.orchestrator.run_config import load_run_config


class GatherError(BaselineError):
    """The cell cannot be gathered, for a reason it names: a place, never a task."""


@dataclass(frozen=True)
class Gathered:
    """A cell gathered: its harness records, then its raw records, each in the cell's order."""

    tier: str
    harness_round: str
    harness_commit: str
    raw_rounds: tuple[str, ...]
    harness: tuple[TrialRecord, ...]
    raw: tuple[TrialRecord, ...]

    def lines(self) -> bytes:
        """The records as the report reads them: one trial record a line."""
        return b"".join(r.model_dump_json().encode() + b"\n" for r in (*self.harness, *self.raw))

    def printed(self, records_sha256: str) -> dict[str, Any]:
        """What the command prints: counts and digests only."""
        return {
            "format": 1,
            "status": "gathered",
            "tier": self.tier,
            "pairs": len(self.harness),
            "harness_round": self.harness_round,
            "raw_rounds": len(self.raw_rounds),
            "harness_commit": self.harness_commit,
            "records_sha256": records_sha256,
        }


def _refuse(reason: str, msg: str, **context: str) -> GatherError:
    return GatherError(msg, refused_because=reason, **context)


def gather(
    store: Path, role: Role, version: str, runs: RunSet, *, shakedown: bool = False
) -> Gathered:
    """The cell ``runs`` names, its harness records and each pair's one raw record; or refused.

    Raises:
        GatherError: the cell cannot be counted, for the reason it names (module text).
        BaselineError: the version refuses as read, or is marked exposed.
    """
    manifest = read_version(version_dir(store, role, version))
    practice = practice_refusal(manifest, shakedown=shakedown)
    if practice is not None:
        raise _refuse(practice[0], practice[1])
    _require_unexposed(store, role, version)
    tasks = _tasks(version_dir(store, role, version))
    rounds = HarnessRounds(store, role)
    places = []
    for at, entry in enumerate(runs.trials):
        config = load_run_config(Path(entry.run_dir) / "run.json")
        if config.ablation:
            msg = "a run of the cell is an ablation run; no cell of the harness holds one"
            raise _refuse("ablation_record", msg, place=str(at))
        if config.brief_sha256 not in tasks:
            raise _refuse("run_not_in_source", "a run of the cell was given no task of the version")
        try:
            place = rounds.place_of(entry.run_dir)
        except PairError as exc:
            raise _refuse(str(exc.context.get("refused_because")), str(exc)) from None
        if place is None:
            msg = "a run of the cell was placed by no harness round; a cell is a round's own"
            raise _refuse("no_harness_round", msg, place=str(at))
        places.append(place)
    if not places or len({(p.held.round_id, p.tier) for p in places}) != 1:
        msg = "a cell is one harness round's set of one tier, and this set is not"
        raise _refuse("cell_not_the_round_s", msg)
    first = places[0]
    try:
        cell = round_cell(first)
    except PairError as exc:
        raise _refuse(str(exc.context.pop("refused_because")), str(exc), **exc.context) from None
    given = [(os.path.realpath(e.run_dir), e.trial) for e in runs.trials]
    if given != [(os.path.realpath(r), t) for r, t, _ in cell.trials]:
        msg = "the set given is not the harness round's own set of the tier, in its order"
        raise _refuse("cell_not_the_round_s", msg)
    tier = first.tier
    earlier = _earlier_rounds(rounds, first.held, version, tier)
    if earlier:
        named = ",".join(earlier)
        msg = (
            f"the harness round {first.held.round_id} is not the cell's first: the round(s) "
            f"{named} hold the same tier of the version and started before it, or when cannot be "
            "told; a cell is counted from its first harness round only"
        )
        raise _refuse("cell_has_an_earlier_round", msg, earlier_round=named)
    commits: dict[str | None, str] = {}
    harness: list[TrialRecord] = []
    raw: list[TrialRecord] = []
    raw_rounds: list[str] = []
    for at, line in enumerate(first.held.tier_set(tier)):
        where = {"place": str(at)}
        record = line["record"]
        if line.get("outcome") == "excluded" or ("reason" in record and "outcome" not in record):
            msg = "a harness record of the cell is excluded; a cell with one has no verdict"
            raise _refuse("trial_excluded", msg, arm="harness", **where)
        kept = TrialRecord.model_validate_json(json.dumps(record))
        if kept.ablation is not None:
            raise _refuse("ablation_record", "a harness record of the cell is an ablation trial's")
        harness.append(kept)
        config = load_run_config(Path(line["run_dir"]) / "run.json")
        commits.setdefault(config.harness.commit, f"the harness run at place {at}")
        found, raw_round, commit = _raw_record(
            store, role, f"harness:{first.held.round_id}:{int(line['index'])}", line, tier, where
        )
        commits.setdefault(commit, f"the raw record at place {at}")
        raw.append(found)
        raw_rounds.append(raw_round)
    if None in commits:
        msg = f"{commits[None]} names no harness commit; every counted trial names its one commit"
        raise _refuse("harness_commit_unknown", msg)
    if len(commits) > 1:
        named = " and ".join(sorted(str(c) for c in commits))
        msg = f"the cell's trials ran from different harness commits ({named}); a cell has one"
        raise _refuse("harness_commit_differs", msg, commits=named)
    return Gathered(
        tier=tier,
        harness_round=first.held.round_id,
        harness_commit=str(next(iter(commits))),
        raw_rounds=tuple(sorted(set(raw_rounds))),
        harness=tuple(harness),
        raw=tuple(raw),
    )


#: How a harness round's ledger records its start: to the second, in UTC.
_STARTED = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def _started(held: HarnessRound) -> str | None:
    started = held.lines[0].get("started")
    return started if isinstance(started, str) and _STARTED.fullmatch(started) else None


def _of_the_cell(held: HarnessRound, version: str, tier: str) -> bool:
    """Whether ``held`` holds places of ``tier`` of ``version``, of the harness as measured.

    A ledger that does not say its version is taken to be of it: what cannot be told is refused.
    """
    inputs = held.lines[0].get("inputs")
    if isinstance(inputs, dict):
        if inputs.get("shakedown") is True:
            return False
        if isinstance(inputs.get("version"), str) and inputs["version"] != version:
            return False
    return any(p.get("arm") is None and p.get("tier") == tier for p in held.order)


def _earlier_rounds(
    rounds: HarnessRounds, held: HarnessRound, version: str, tier: str
) -> list[str]:
    """The other harness rounds of the cell that started before ``held``, or when is not known."""
    mine = _started(held)
    found = []
    for other in rounds.every():
        if other.round_id == held.round_id or not _of_the_cell(other, version, tier):
            continue
        theirs = _started(other)
        if mine is None or theirs is None or theirs <= mine:
            found.append(other.round_id)
    return found


def _raw_record(
    store: Path,
    role: Role,
    key: str,
    kept: dict[str, Any],
    tier: str,
    where: dict[str, str],
) -> tuple[TrialRecord, str, str | None]:
    """The pair's one counted raw record, its round, and the harness commit its session names.

    Raises:
        GatherError: the pair has none, has two, or the one it has cannot be counted.
    """
    try:
        found = claims(store, role, key)
    except PairError as exc:
        raise _refuse("pairs_unread", str(exc), **where) from None
    states = [(line, standing(line)) for line in found]
    unread = [line for line, state in states if state == "unread"]
    if unread:
        msg = f"the round {unread[0]['round']} took the pair on and its ledger cannot be read"
        raise _refuse("pair_unread", msg, earlier_round=str(unread[0]["round"]), **where)
    counted = [line for line, state in states if state == "recorded"]
    if not counted:
        stood = ",".join(sorted({state for _, state in states})) or "none"
        msg = f"the pair has no counted raw record (its rounds stand: {stood})"
        raise _refuse("pair_without_record", msg, standing=stood, **where)
    if len(counted) > 1:
        named = " and ".join(str(line["round"]) for line in counted)
        msg = f"the pair has a counted raw record in more than one round ({named})"
        raise _refuse("pair_counted_twice", msg, rounds=named, **where)
    line = counted[0]
    out, entry, round_id = Path(str(line["out"])), int(line["entry"]), str(line["round"])
    lines = baseline_lines(out)
    assert lines is not None  # its standing was read from it
    runs = RunSet.model_validate_json(json.dumps(lines[0]["runs"]))
    if os.path.realpath(runs.trials[entry].run_dir) != os.path.realpath(kept["run_dir"]):
        msg = (
            f"the pair's raw record in the round {round_id} is held to a draw its harness round "
            "did not keep, and no once-more ran it under the one it kept"
        )
        raise _refuse("pair_on_a_superseded_draw", msg, earlier_round=round_id, **where)
    try:
        BaselineRecord.model_validate_json((out / BASELINE_RECORD).read_bytes())
    except (OSError, ValueError):
        msg = f"the raw round {round_id} has not ended; a cell is gathered from ended rounds"
        raise _refuse("raw_round_not_ended", msg, earlier_round=round_id, **where) from None
    ledger = Ledger(out / LEDGER, lines)
    record = _earlier_line(store, role, out, ledger, runs, entry, cast("TierName", tier))
    if isinstance(record, ExcludedTrial):
        msg = "a raw record of the cell is excluded; a cell with one has no verdict"
        raise _refuse("trial_excluded", msg, arm="raw", **where)
    session = next(int(x["session"]) for x in ledger.recorded() if int(x["index"]) == entry)
    name = f"{entry:04d}-{session}"
    directory = (
        withheld_root(store, role) / BASELINE_DIR / round_id / name
        if tier in PROTECTED_TIERS
        else out / WORK / name
    )
    pins = read_record(directory / HARNESS).get("pins") or {}
    checkout = pins.get("harness") if isinstance(pins, dict) else None
    commit = checkout.get("commit") if isinstance(checkout, dict) else None
    return record, round_id, commit if isinstance(commit, str) else None


def write_gathered(store: Path, role: Role, gathered: Gathered, out: Path) -> str:
    """Write the gathered records to ``out``, a new file; their digest.

    A protected tier's records go beneath the role's withheld root, where every output on such a
    cell lies, or nowhere.

    Raises:
        GatherError: ``out_not_withheld`` for a protected tier's records anywhere else;
            ``out_exists`` where the file is there already.
    """
    if gathered.tier in PROTECTED_TIERS:
        real = Path(os.path.realpath(out.parent)) / out.name
        if not real.is_relative_to(os.path.realpath(withheld_root(store, role))):
            msg = "a protected cell's gathered records are written beneath the withheld root only"
            raise _refuse("out_not_withheld", msg)
    data = gathered.lines()
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise _refuse("out_exists", "the gathered records' file is there already") from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(data).hexdigest()
