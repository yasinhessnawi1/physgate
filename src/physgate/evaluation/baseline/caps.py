"""The raw arm's cap for a harness trial, and for one that gives no figure: one rule, held here.

The raw arm's cap for a (task, trial) is the token total of its paired harness run
(:func:`.per_role.arms.compare.harness_total`). A harness trial can give no figure: the machine
ended it for good (unscored), it stopped where nothing continues it, or a session it left at a
kill was read without a result. Such a trial never blocks its pair. Its raw trial's cap is:

1. **the largest total among the same task's other harness trials of the cell** that give one;
2. if none of them gives one, **the median of the totals of every harness trial of the cell**
   that gives one. For an even count the median is the mean of the two middle totals, rounded
   down to a whole token (``(a + b) // 2`` of the two middle values, sorted ascending);
3. if no harness trial of the cell gives a figure, there is no cap (:class:`NoCapError`).

A cell is one tier's harness trials (a suite): the cap of a held-out trial is never taken from a
visible trial's total. A trial's task is named by the digest of the brief its run was given,
never by its id. Pass or fail never enters the rule: only totals do. A superseded run is in no
cell's run set, so it never enters it either.

Every raw trial is capped by this rule, and the rule it took and its inputs (each trial by its
place in the cell's run set, with its total) are recorded with the trial (:class:`RawCap`), so
the record audit derives the same cap again from them. Where the cell is a harness round's own
(:func:`.pairs.round_cell`), the record names the round, the tier and the digest of the round's
run set of it, so the cap can be held to the set the round wrote.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from physgate.evaluation.per_role.exceptions import PerRoleError

#: Which of the rule's three steps gave the cap: the pair's own total, the largest of the same
#: task's other trials, or the median of the cell.
CapRule = Literal["pair", "task_largest", "cell_median"]


class NoCapError(PerRoleError):
    """No harness trial of the cell gives a figure, so the rule gives no cap."""


@dataclass(frozen=True)
class CellTrial:
    """One harness trial of a cell, as the rule reads it."""

    #: Its place in the cell's run set.
    place: int
    #: The digest of the brief its run was given: its task, never named.
    task: str
    #: Its run's token total, or ``None`` where it gives no figure.
    total: int | None


@dataclass(frozen=True)
class RawCap:
    """The cap a raw trial runs under, the step of the rule that gave it, and that step's inputs."""

    rule: CapRule
    cap: int
    #: The trials the step read, each by its place in the cell's run set, with its total.
    inputs: tuple[tuple[int, int], ...]
    #: Where the cell came from, for a cap taken from a harness round's own cell: the round, the
    #: tier and the digest of the round's run set of it. ``None`` for a pair's own total, and for
    #: a cell that is no round's.
    cell: Mapping[str, str] | None = field(default=None, hash=False)

    def recorded(self) -> dict[str, object]:
        """The form the trial's records hold: no task, places and totals only.

        The cell's origin is held only where there is one, so a record written before it was
        held keeps its form.
        """
        recorded: dict[str, object] = {
            "rule": self.rule,
            "cap": self.cap,
            "inputs": [{"place": place, "total": total} for place, total in self.inputs],
        }
        if self.cell is not None:
            recorded["cell"] = dict(self.cell)
        return recorded


def median_total(totals: Sequence[int]) -> int:
    """The median of ``totals``; for an even count the two middle ones' mean, rounded down.

    Raises:
        ValueError: ``totals`` is empty.
    """
    if not totals:
        msg = "the median of no totals"
        raise ValueError(msg)
    ordered = sorted(totals)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def raw_cap(own: CellTrial, cell: Sequence[CellTrial]) -> RawCap:
    """The raw cap of the harness trial ``own``, a trial of ``cell``, by the rule above.

    Raises:
        NoCapError: ``own`` gives no figure and neither does any other trial of the cell
            (``no_cap_in_the_cell``).
        ValueError: ``own`` is not a trial of ``cell``.
    """
    if own not in cell:
        msg = "a trial's cap is taken from its own cell, and the trial is not in it"
        raise ValueError(msg)
    if own.total is not None:
        return RawCap("pair", own.total, ((own.place, own.total),))
    others = [
        (t.place, t.total)
        for t in cell
        if t.place != own.place and t.task == own.task and t.total is not None
    ]
    if others:
        return RawCap("task_largest", max(t for _, t in others), tuple(sorted(others)))
    given = [(t.place, t.total) for t in cell if t.total is not None]
    if not given:
        msg = (
            "no harness trial of the cell gives a token total, so the rule gives the raw trial of "
            "one that gives none no cap"
        )
        raise NoCapError(msg, refused_because="no_cap_in_the_cell")
    return RawCap("cell_median", median_total([total for _, total in given]), tuple(sorted(given)))
