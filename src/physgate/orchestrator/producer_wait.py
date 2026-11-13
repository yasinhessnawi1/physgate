"""A subtask waits for a subtask it reads from while that one waits, unmerged, on a person.

"Reads from" is the strongest relation the record holds: the run's contract pairs, recorded
from the plan before any module runs, each naming a producing and a consuming subtask and the
interfaces between them. A subtask's first dispatch is held while a pair's producer is escalated
with its item undecided. The run goes on with every subtask that does not read from it, and
waits on the queue when nothing else can run. The hold is let go once the producer merged, ended
without a merge, or waits for sizing's closing pass, which comes after the subtask; the release
line says which, so a reader tells "waited, then ran without it" from "ran before it". Two
subtasks that read from each other are never held, and a line says so.

Only in a run that acts on decisions and records its pairs: a run that records only never takes
a decision, so a producer in the queue has ended there, and a run without pairs has no recorded
relation. A run recorded before these lines existed has none of them, and replays as it did; a
run started under the rule says so on its first line, and its replay refuses a dispatch the record
owed one of them before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from physgate.orchestrator.events import DispatchHeld, DispatchReleased, ReleasedHow

if TYPE_CHECKING:
    from physgate.contracts.pairs import ContractPair
    from physgate.orchestrator.events import Envelope
    from physgate.orchestrator.replay import RunState

#: What a subtask's first dispatch is turned into: a line to write first, or passed over.
Gated = Literal["hold", "release", "held"]


@dataclass
class Waits:
    """The holds on the record: each open one by (subtask, producer), and each mutual release.

    ``strict`` once the run's first line says it started under the rule: a dispatch the record
    owes a hold or release line before is then refused, where a run without the mark replays it
    as it did before the rule existed.
    """

    open: dict[tuple[str, str], DispatchHeld] = field(default_factory=dict)
    mutual: set[tuple[str, str, str]] = field(default_factory=set)
    strict: bool = False


@dataclass(frozen=True)
class _Owed:
    kind: Literal["hold", "release"]
    producer: str
    item_id: str
    interfaces: tuple[str, ...] = ()
    outcome: ReleasedHow | None = None


def _applies(state: RunState) -> bool:
    return state.acts and state.contract_pairs is not None


def _reads_from(state: RunState, subtask_id: str) -> list[ContractPair]:
    """The pairs whose consumer is ``subtask_id``, in the recorded order."""
    return [p for p in state.contract_pairs or () if p.consumer.subtask_id == subtask_id]


def _mutual(state: RunState, subtask_id: str, producer: str) -> bool:
    return any(
        p.producer.subtask_id == subtask_id and p.consumer.subtask_id == producer
        for p in state.contract_pairs or ()
    )


def waiting_item(state: RunState, producer: str) -> str | None:
    """The item ``producer`` waits on a person for, unmerged: escalated, and its item undecided."""
    sub = state.subtasks.get(producer)
    if sub is None or sub.status != "escalated" or sub.queue_item is None:
        return None
    return sub.queue_item if state.undecided(sub.queue_item) else None


def released_how(state: RunState, producer: str) -> ReleasedHow | None:
    """How a hold on ``producer`` is let go now; ``None`` while it waits on a person or runs."""
    sub = state.subtasks[producer]
    if sub.status == "done":
        return "merged"
    if sub.status in ("rejected", "removed"):
        return "ended_unmerged"
    if sub.status == "waiting":
        return "waits_for_closing_pass"
    if sub.status == "escalated" and waiting_item(state, producer) is None:
        return "ended_unmerged"  # a decision taken on its item that acted on nothing
    return None


def _owed(state: RunState, subtask_id: str) -> _Owed | Literal["held"] | None:
    """The line the record owes before ``subtask_id``'s first dispatch, ``held``, or nothing.

    Every open hold is let go first, in the order written; while one stays open the subtask is
    passed over. A further hold is looked for only once none is open.
    """
    holds = [h for (d, _), h in state.producer_waits.open.items() if d == subtask_id]
    for hold in holds:
        how = released_how(state, hold.producer)
        if how is not None:
            return _Owed("release", hold.producer, hold.item_id, outcome=how)
    if holds:
        return "held"
    for pair in _reads_from(state, subtask_id):
        producer = pair.producer.subtask_id
        item = waiting_item(state, producer)
        if item is None:
            continue
        if _mutual(state, subtask_id, producer):
            if (subtask_id, producer, item) in state.producer_waits.mutual:
                continue
            return _Owed("release", producer, item, outcome="mutual_readers")
        return _Owed("hold", producer, item, interfaces=pair.interfaces)
    return None


def gated(state: RunState, subtask_id: str) -> Gated | None:
    """What becomes of ``subtask_id``'s first dispatch; ``None`` when it goes ahead as planned."""
    if not _applies(state) or state.subtasks[subtask_id].status != "planned":
        return None
    owed = _owed(state, subtask_id)
    if owed is None:
        return None
    return owed if isinstance(owed, str) else owed.kind


def held_subtask(state: RunState) -> str | None:
    """The first planned subtask a hold on the record keeps back, in plan order."""
    if not _applies(state):
        return None
    for subtask_id in state.order:
        if state.subtasks[subtask_id].status != "planned":
            continue
        if any(d == subtask_id for d, _ in state.producer_waits.open):
            return subtask_id
    return None


def owed_line(
    state: RunState, subtask_id: str, envelope: Envelope
) -> DispatchHeld | DispatchReleased:
    """The hold or release line the record owes for ``subtask_id``, with ``envelope``.

    Raises:
        ValueError: the record owes none.
    """
    owed = _owed(state, subtask_id) if _applies(state) else None
    if not isinstance(owed, _Owed):
        msg = f"no hold or release is owed for {subtask_id!r}"
        raise ValueError(msg)
    if owed.kind == "hold":
        return DispatchHeld(
            **envelope,
            subtask_id=subtask_id,
            producer=owed.producer,
            item_id=owed.item_id,
            interfaces=owed.interfaces,
        )
    assert owed.outcome is not None  # noqa: S101 - every release is built with one
    return DispatchReleased(
        **envelope,
        subtask_id=subtask_id,
        producer=owed.producer,
        item_id=owed.item_id,
        outcome=owed.outcome,
    )


def take(state: RunState, event: DispatchHeld | DispatchReleased) -> str | None:
    """Take a hold or release line; why it cannot come next, or ``None`` once it is taken."""
    subtask_id = event.subtask_id
    if subtask_id not in state.subtasks or not _applies(state):
        return "a hold or release in a run that does not act on decisions by its recorded pairs"
    kind = "hold" if isinstance(event, DispatchHeld) else "release"
    step = state.next_step()
    owed = _owed(state, subtask_id) if state.subtasks[subtask_id].status == "planned" else None
    if (step.kind, step.subtask_id) != (kind, subtask_id) or not isinstance(owed, _Owed):
        return f"no {type(event).__name__} is owed for {subtask_id!r} now"
    if isinstance(event, DispatchHeld):
        if (event.producer, event.item_id, event.interfaces) != (
            owed.producer,
            owed.item_id,
            owed.interfaces,
        ):
            return "a hold names another producer, item or interfaces than the record owes"
        state.producer_waits.open[(subtask_id, event.producer)] = event
        return None
    if (event.producer, event.item_id, event.outcome) != (
        owed.producer,
        owed.item_id,
        owed.outcome,
    ):
        return "a release names another producer, item or outcome than the record owes"
    if event.outcome == "mutual_readers":
        state.producer_waits.mutual.add((subtask_id, event.producer, event.item_id))
    else:
        del state.producer_waits.open[(subtask_id, event.producer)]
    return None


def held_dispatch(state: RunState, subtask_id: str) -> str | None:
    """Why ``subtask_id`` cannot be dispatched now, or ``None``.

    A hold on the record still keeps it back; or, in a run started under the rule, the record owes
    a hold or release line before it, which a dispatch in its place left out.
    """
    for d, producer in state.producer_waits.open:
        if d == subtask_id:
            return f"{subtask_id!r} is held while {producer!r}, which it reads from, waits"
    owed = _owed(state, subtask_id) if state.producer_waits.strict and _applies(state) else None
    if isinstance(owed, _Owed):
        return (
            f"{subtask_id!r} is dispatched while {owed.producer!r}, which it reads from, waits on"
            f" a person, with no {owed.kind} line on the record of a run started under the hold"
        )
    return None
