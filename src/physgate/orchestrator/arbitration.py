"""Which position on a disputed quantity stands: a fixed precedence, decided by code (ARCH-040).

A domain role that disagrees with a value of a cross node records a dispute; sizing alone writes
those values (ARCH-051). Nobody negotiates. :func:`arbitrate` reads the conflict and the standing
it is read in, and the first row of the precedence table that applies decides it:

1. ``gate``: the physics gate refused the attempt where it blocks. The gate's rejection stands;
   the dispute is recorded and is not counted.
2. ``sizing``: the first counted dispute of the quantity, with an attempt of the subtask left.
   Sizing's value stands, and the attempt is rejected before any review.
3. ``queue``: what survives both, a repeat of a quantity counted before or a dispute on the
   subtask's last attempt, goes to a person as one item.

The table is data, and :func:`require_table` holds its shape: each level named once, and the
queue last, applying always, so no conflict is left without exactly one outcome. A row added later
goes where it ranks and reads a fact of the standing that lines recorded before it lack, so those
lines are ruled as they were. Nothing here reads a session's words: a conflict names a quantity,
and the standing is three facts the run's record gives. The replay builds the standing again from
the lines before each ruling and holds the ruling to this table (``RunState``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.budget import after_rejection
from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.exceptions import ArbitrationError
from physgate.orchestrator.protocols import GateResult, QuantityRef

#: The levels a ruling is recorded at, by name, in the table's order: the name is what a line
#: holds, so a row inserted later does not renumber the lines written before it.
Level = Literal["gate", "sizing", "queue"]
#: What each level does to the attempt: the gate's rejection stands; the attempt is rejected
#: with sizing's value; or the subtask goes to a person.
Effect = Literal["gate_stands", "reject_attempt", "queue_item"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DisputeConflict(_Frozen):
    """A domain's dispute of one quantity of a cross node: what is in conflict, by name alone."""

    kind: Literal["dispute"] = "dispute"
    node_id: NonEmptyStr
    quantity: NonEmptyStr


#: Every conflict the table rules. A failed contract clause joins it with its place in the run.
Conflict = DisputeConflict


class Standing(_Frozen):
    """The facts of the run's record a conflict is ruled in."""

    #: The attempt's gate refused it where the gate blocks (``on``, a failing verdict).
    gate_refused: bool
    #: Earlier attempts of the subtask whose dispute of the same quantity was ruled at a level
    #: that counts: every level but the gate's.
    counted_before: Annotated[int, Field(ge=0)]
    #: Whether the subtask has an attempt after this one.
    attempt_left: bool


class Held(_Frozen):
    """Sizing's position: the disputed quantity as the graph holds it, and where it came from."""

    position: QuantityRef
    source: NonEmptyStr
    written_by: NonEmptyStr
    #: The canonical journal's revision of the node the value was read from.
    revision: Annotated[int, Field(ge=1)]


class Arbitration(_Frozen):
    """The outcome: the level that decided, and what it does."""

    level: NonEmptyStr
    effect: Effect


def _gate_refused(_: Conflict, standing: Standing) -> bool:
    return standing.gate_refused


def _sizing_stands(conflict: Conflict, standing: Standing) -> bool:
    return conflict.kind == "dispute" and standing.counted_before == 0 and standing.attempt_left


def always(_: Conflict, __: Standing) -> bool:
    """The queue's rule: what reaches the last row goes to a person."""
    return True


@dataclass(frozen=True)
class Rank:
    """One row of the precedence table: its level, what it does, and when it applies."""

    level: str
    effect: Effect
    applies: Callable[[Conflict, Standing], bool]


#: The precedence, highest first (ARCH-040): physics, then sizing, then a person.
TABLE: tuple[Rank, ...] = (
    Rank(level="gate", effect="gate_stands", applies=_gate_refused),
    Rank(level="sizing", effect="reject_attempt", applies=_sizing_stands),
    Rank(level="queue", effect="queue_item", applies=always),
)
#: The one level the count leaves out: a dispute the gate decided was never weighed.
NOT_COUNTED = "gate"


def require_table(table: Sequence[Rank]) -> None:
    """Refuse a table that could leave a conflict with no outcome, or rank a level twice.

    Raises:
        ArbitrationError: the table is empty, names a level twice, or does not end in the queue
            applying always, or holds that row anywhere else.
    """
    names = [rank.level for rank in table]
    if not table or len(set(names)) != len(names):
        msg = "a precedence table names each level once, and at least the queue"
        raise ArbitrationError(msg, levels=",".join(names))
    last = table[-1]
    if (last.level, last.effect, last.applies) != ("queue", "queue_item", always):
        msg = "a precedence table ends in the queue, which applies always"
        raise ArbitrationError(msg, levels=",".join(names))
    if any(rank.applies is always for rank in table[:-1]):
        msg = "only the last row of a precedence table applies always"
        raise ArbitrationError(msg, levels=",".join(names))


require_table(TABLE)


def arbitrate(conflict: Conflict, standing: Standing, table: Sequence[Rank] = TABLE) -> Arbitration:
    """The outcome of ``conflict`` in ``standing``: the first row of ``table`` that applies.

    Pure, and spends no token: the same conflict in the same standing is ruled the same way.

    Raises:
        ArbitrationError: ``table`` is not one :func:`require_table` accepts.
    """
    require_table(table)
    rank = next(rank for rank in table if rank.applies(conflict, standing))
    return Arbitration(level=rank.level, effect=rank.effect)


def dispute_standing(
    conflict: DisputeConflict,
    *,
    gate: GateResult | None,
    earlier: Iterable[tuple[Conflict, str]],
    attempt: int,
    fix: bool,
) -> Standing:
    """The standing of a dispute in ``attempt``, from the record's lines about the subtask.

    ``gate`` is the attempt's gate result, ``None`` where the gate was skipped; ``earlier`` the
    conflicts and levels ruled in the subtask's earlier attempts; ``fix`` whether this attempt is
    the one fix a person ordered, which is always the last.
    """
    refused = gate is not None and gate.mode == "on" and gate.verdict == "fail"
    counted = sum(1 for seen, level in earlier if seen == conflict and level != NOT_COUNTED)
    left = not fix and after_rejection(attempt) is not None
    return Standing(gate_refused=refused, counted_before=counted, attempt_left=left)
