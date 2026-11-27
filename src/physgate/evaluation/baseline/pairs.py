"""Which harness trial a raw entry pairs, its cell, and which baseline round holds its record.

**The harness trial an entry pairs** is found from the entry itself: the harness round that
placed its run. Every harness round keeps its ledger beneath the role's withheld root
(``withheld/harness/<round>/ledger.jsonl``), and every draw of a trial is named there on a
``placed`` line by its run directory; the draw the round kept is the one its ``assembled`` line
names. So a run made by a harness round is that round's place (:class:`HarnessPlace`), whatever
file a person lists it in; a run no harness round placed (one made by hand, for a development or
an external round) is its own pair, by its directory and trial number.

**The cell** of a trial whose harness run gives no figure is its harness round's own set of the
trial's tier (:func:`round_cell`): the round's assembled trials of the harness as measured, in
the round's order, exactly the entries the round writes as ``<tier>.runs.json``, and held to the
combined set the round wrote beneath the withheld root once it ended. An ablation arm's trial and
a draw the round excluded and superseded are never in it, and a trial the round kept as excluded
is in it with no figure. It exists only once the round has ended: before then the cell is not
whole, and a raw trial capped from it would be capped from part of it.

**The pair register** (:func:`claims`, :func:`claim`): beneath the role's withheld root, where a
protected round's records lie, ``withheld/baseline/pairs/<digest of the pair>.jsonl`` names every
baseline round that took the pair on, with the directory its ledger lies in. A round writes its
line before its first session, under the work root's hold, and the next round of the same pair
reads every earlier one's ledger to say where the pair stands there (:func:`standing`): a record,
a stop, a session started and not settled, or nothing yet. A round that ended before the register
existed wrote no line, and is not seen by it. A development round is never counted: it writes no
line, and no line holds it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.store import BASELINE_DIR, withheld_root
from physgate.evaluation.tiers.task import Role, canonical_json

#: Beneath the role's withheld root: every harness round's own directory (the round driver's).
HARNESS_ROUNDS = "harness"
#: In a harness round's directory: its ledger, and the combined run set it writes at its end.
HARNESS_LEDGER = "ledger.jsonl"
COMBINED = "all.runs.json"
#: The tiers a harness round's combined set holds, in the order it writes them.
SET_TIERS = ("visible", "validation", "held_out")
#: Beneath the withheld root's baseline directory: one file of lines per pair.
PAIRS = "pairs"
#: The ledger line a once-more round writes on the earlier round's ledger: the entry it supersedes.
SUPERSEDED_BY = "superseded_by"


class PairError(PerRoleError):
    """The pair or its cell cannot be told, or a round of it refuses: no task is named."""


# -- the harness round's ledger ----------------------------------------------------------------


def _whole_lines(path: Path) -> list[dict[str, Any]]:
    """The whole lines of a ledger, a last line a kill cut off left out; read, never mended.

    Raises:
        OSError: it cannot be read.
        PairError: a whole line is not a ledger line (``ledger_unread``).
    """
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[: data.rfind(b"\n") + 1]
    lines = []
    for raw in data.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            line = None
        if not isinstance(line, dict) or not isinstance(line.get("kind"), str):
            msg = "a line of a round's ledger is not a ledger line"
            raise PairError(msg, refused_because="ledger_unread", ledger=path.parent.name)
        lines.append(line)
    return lines


@dataclass(frozen=True)
class HarnessRound:
    """A harness round as its ledger beneath the withheld root holds it."""

    round_id: str
    place: Path
    lines: tuple[dict[str, Any], ...]

    @property
    def order(self) -> list[dict[str, Any]]:
        """The round's order: each place's index, tier, task digest, trial, seed and arm."""
        return list(self.lines[0].get("order") or [])

    def of(self, kind: str) -> list[dict[str, Any]]:
        """The ledger's lines of ``kind``, in order."""
        return [x for x in self.lines if x["kind"] == kind]

    @property
    def ended(self) -> bool:
        """Whether the round wrote its sets and its end: every place it keeps is assembled."""
        return any(x["kind"] == "ended" for x in self.lines)

    def dropped(self) -> frozenset[int]:
        """The ablation arm's places a person's word dropped."""
        return frozenset(int(i) for x in self.of("arm_dropped") for i in x.get("places", ()))

    def left(self, tier: str) -> list[int]:
        """The places of the harness as measured, of ``tier``, the round has not yet assembled."""
        done = {int(x["index"]) for x in self.of("assembled")}
        return [
            int(p["index"])
            for p in self.order
            if p.get("arm") is None
            and p.get("tier") == tier
            and int(p["index"]) not in done
            and int(p["index"]) not in self.dropped()
        ]

    def tier_set(self, tier: str) -> list[dict[str, Any]]:
        """The round's assembled trials of the harness as measured, of ``tier``, in its order.

        Each is the place's ``assembled`` line with the place's trial number: the entries the
        round writes as its tier's run set, in the same order.
        """
        by_index = {int(x["index"]): x for x in self.of("assembled")}
        found = []
        for place in self.order:
            index = int(place["index"])
            if place.get("arm") is None and place.get("tier") == tier and index in by_index:
                found.append({**by_index[index], "trial": int(place["trial"])})
        return found


@dataclass
class HarnessRounds:
    """Every harness round of the role, read once, and each draw's place by its run directory."""

    store: Path
    role: Role
    _rounds: dict[str, HarnessRound] | None = None
    _draws: dict[str, tuple[str, int, int]] = field(default_factory=dict)

    def _read(self) -> dict[str, HarnessRound]:
        if self._rounds is not None:
            return self._rounds
        rounds: dict[str, HarnessRound] = {}
        root = withheld_root(self.store, self.role) / HARNESS_ROUNDS
        with contextlib.suppress(FileNotFoundError):
            for name in sorted(os.listdir(root)):
                place = root / name
                ledger = place / HARNESS_LEDGER
                if place.is_symlink() or not ledger.is_file() or ledger.is_symlink():
                    continue
                try:
                    lines = _whole_lines(ledger)
                except OSError:
                    msg = "a harness round's ledger beneath the withheld root cannot be read"
                    raise PairError(
                        msg, refused_because="ledger_unread", harness_round=name
                    ) from None
                if not lines or lines[0].get("kind") != "round" or lines[0].get("round") != name:
                    continue
                rounds[name] = HarnessRound(name, place, tuple(lines))
                for line in lines:
                    if line["kind"] == "placed" and isinstance(line.get("run_dir"), str):
                        real = os.path.realpath(line["run_dir"])
                        there = self._draws.get(real)
                        if there is not None and there[0] != name:
                            # A run directory is made by one round: two that name it cannot
                            # both be its round, and which one is cannot be told.
                            msg = "two harness rounds' ledgers place the same run"
                            raise PairError(msg, refused_because="run_in_two_rounds")
                        self._draws[real] = (name, int(line["index"]), int(line["attempt"]))
        self._rounds = rounds
        return rounds

    def round(self, round_id: str) -> HarnessRound:
        """The harness round ``round_id``."""
        return self._read()[round_id]

    def place_of(self, run_dir: str) -> HarnessPlace | None:
        """The harness round's place that placed the run at ``run_dir``; ``None`` for none."""
        rounds = self._read()
        found = self._draws.get(os.path.realpath(run_dir))
        if found is None:
            return None
        round_id, index, attempt = found
        held = rounds[round_id]
        place = next((p for p in held.order if int(p["index"]) == index), None)
        if place is None:
            msg = "a harness round's ledger places a draw at a place its order does not have"
            raise PairError(msg, refused_because="ledger_unread", harness_round=round_id)
        kept = next((x for x in held.of("assembled") if int(x["index"]) == index), None)
        final = kept is not None and os.path.realpath(kept["run_dir"]) == os.path.realpath(run_dir)
        return HarnessPlace(
            held=held,
            index=index,
            attempt=attempt,
            tier=str(place["tier"]),
            trial=int(place["trial"]),
            arm=place.get("arm"),
            final=final,
        )


@dataclass(frozen=True)
class HarnessPlace:
    """The place of a harness round a run is a draw of."""

    held: HarnessRound
    index: int
    attempt: int
    tier: str
    trial: int
    #: The ablation arm the place is of, by name; ``None`` for the harness as measured.
    arm: str | None
    #: Whether the run is the draw the round kept for the place (its ``assembled`` line's).
    final: bool

    @property
    def key(self) -> str:
        """The pair: the harness round and the place, whichever draw of it the run is."""
        return f"harness:{self.held.round_id}:{self.index}"


def run_key(run_dir: str, trial: int) -> str:
    """The pair of a run no harness round placed: its directory, as it really is, and its trial."""
    return f"run:{os.path.realpath(run_dir)}:{trial}"


@dataclass(frozen=True)
class RoundCell:
    """A harness round's own cell of one tier, as the cap rule and the audit read it."""

    round_id: str
    tier: str
    #: Each trial of the cell in the round's order: its run directory, its trial number, and
    #: whether the round kept it as excluded (it then gives no figure).
    trials: tuple[tuple[str, int, bool], ...]

    def entries(self) -> list[dict[str, Any]]:
        """The cell's run set's entries, as the round writes its tier's set."""
        return [{"run_dir": run_dir, "trial": trial} for run_dir, trial, _ in self.trials]

    def runs_sha256(self) -> str:
        """The digest of the tier's run set as the round writes it, ``<tier>.runs.json``."""
        from physgate.evaluation.baseline.runner import RunSet

        runs = RunSet.model_validate_json(json.dumps({"format": 1, "trials": self.entries()}))
        return hashlib.sha256(runs.model_dump_json().encode()).hexdigest()

    def origin(self) -> dict[str, str]:
        """Where the cell came from, as a raw trial's cap record holds it."""
        return {"round": self.round_id, "tier": self.tier, "runs_sha256": self.runs_sha256()}


def round_cell(found: HarnessPlace) -> RoundCell:
    """The harness round's own cell of the place's tier, once the round has ended.

    Raises:
        PairError: the round has places left (``cell_not_ended``, naming them), or the combined
            set it wrote is not the one its ledger gives (``cell_not_the_round_s``).
    """
    held = found.held
    if not held.ended:
        left = [i for tier in SET_TIERS for i in held.left(tier)]
        msg = (
            "the trial's harness trial gives no figure, and its cap is taken from its cell, "
            "which is whole only once the harness round has assembled its last place: the "
            f"round has {len(left)} place(s) left; this raw trial runs at the cell's end"
        )
        raise PairError(
            msg,
            refused_because="cell_not_ended",
            harness_round=held.round_id,
            places_left=",".join(str(i) for i in left),
        )
    combined: list[dict[str, Any]] = []
    for tier in SET_TIERS:
        combined += [{"run_dir": x["run_dir"], "trial": x["trial"]} for x in held.tier_set(tier)]
    try:
        written = json.loads((held.place / COMBINED).read_bytes())
    except (OSError, ValueError):
        written = None
    if not isinstance(written, dict) or written.get("trials") != combined:
        msg = "the harness round's combined run set is not the one its own ledger gives"
        raise PairError(msg, refused_because="cell_not_the_round_s", harness_round=held.round_id)
    trials = tuple(
        (str(x["run_dir"]), int(x["trial"]), _excluded(x)) for x in held.tier_set(found.tier)
    )
    return RoundCell(held.round_id, found.tier, trials)


def _excluded(line: Mapping[str, Any]) -> bool:
    return line.get("outcome") == "excluded"


# -- the pair register ---------------------------------------------------------------------------


def _pairs_dir(store: Path, role: Role) -> Path:
    return withheld_root(store, role) / BASELINE_DIR / PAIRS


def _pair_file(store: Path, role: Role, key: str) -> Path:
    return _pairs_dir(store, role) / f"{hashlib.sha256(key.encode()).hexdigest()}.jsonl"


def claims(store: Path, role: Role, key: str) -> list[dict[str, Any]]:
    """Every baseline round's line for the pair ``key``, in the order they were written.

    Raises:
        PairError: the pair's file cannot be read whole (``pairs_unread``).
    """
    path = _pair_file(store, role, key)
    try:
        lines = _whole_lines(path)
    except FileNotFoundError:
        return []
    except (OSError, PairError):
        msg = "the pair register's file for an entry cannot be read whole"
        raise PairError(msg, refused_because="pairs_unread") from None
    return [x for x in lines if x.get("key") == key]


def claim(store: Path, role: Role, key: str, round_id: str, out: Path, entry: int) -> None:
    """Write the round's line for the pair ``key``, once: before its first session.

    Called under the work root's hold, so no two rounds write a pair's lines at once.
    """
    if any(c["round"] == round_id and c["entry"] == entry for c in claims(store, role, key)):
        return
    path = _pair_file(store, role, key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = {
        "kind": "pair",
        "key": key,
        "round": round_id,
        "out": os.path.realpath(out),
        "entry": entry,
    }
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, canonical_json(line))
        os.fsync(fd)
    finally:
        os.close(fd)


#: Where a pair stands in a round that took it on, read from that round's own ledger:
#: - ``superseded``: a once-more round runs the entry in its place (its ``superseded_by`` line);
#: - ``recorded``: the round recorded the entry's trial, its one record;
#: - ``stopped``: the round stopped on the entry for a cause; only a once-more runs it again;
#: - ``started``: a session of the entry started and was not settled (the round waits, or was
#:   killed): that round is resumed, never another started;
#: - ``claimed``: no session started yet, and the round can still reach it;
#: - ``free``: no session started, and the round stopped on another entry, so never reaches it;
#: - ``unread``: the round's directory or ledger cannot be read, or is not the round's.
Standing = Literal["superseded", "recorded", "stopped", "started", "claimed", "free", "unread"]


def baseline_lines(out: Path) -> list[dict[str, Any]] | None:
    """A baseline round's ledger lines, as written; ``None`` where they cannot be read whole."""
    try:
        lines = _whole_lines(Path(out) / "ledger.jsonl")
    except (OSError, PairError):
        return None
    if not lines or lines[0].get("kind") != "round":
        return None
    return lines


def standing(line: Mapping[str, Any]) -> Standing:
    """Where the pair stands in the round a register line names, read from its own ledger."""
    lines = baseline_lines(Path(str(line["out"])))
    if lines is None or lines[0].get("round") != line["round"]:
        return "unread"
    return standing_in(lines, int(line["entry"]))


def standing_in(lines: Sequence[Mapping[str, Any]], entry: int) -> Standing:
    """Where the entry stands in a baseline round's ledger ``lines``."""
    if any(x["kind"] == SUPERSEDED_BY and x.get("entry") == entry for x in lines):
        return "superseded"
    own = [x for x in lines if x.get("index") == entry]
    kinds = {x["kind"] for x in own}
    if "recorded" in kinds:
        return "recorded"
    if "stopped" in kinds:
        return "stopped"
    if "started" in kinds:
        return "started"
    if any(x["kind"] == "stopped" for x in lines):
        return "free"
    return "claimed"


def superseded_by(lines: Sequence[Mapping[str, Any]], entry: int) -> Mapping[str, Any] | None:
    """The line naming the round that runs the entry once more in its place, if one does."""
    return next((x for x in lines if x["kind"] == SUPERSEDED_BY and x.get("entry") == entry), None)
