"""A subtask waits for a subtask it reads from while that one waits, unmerged, on a person.

"Reads from" is the strongest relation the record holds: the run's contract pairs, recorded
from the plan before any module runs, each naming a producing and a consuming subtask and the
interfaces between them. Every dispatch of a subtask, its first or a later attempt's, is held while
a pair's producer is escalated with its item undecided, or would itself be held at its own next
dispatch, at any depth: the hold names the undecided item at the chain's root, so every hold pairs
with something a person can act on. A later dispatch meets a waiting producer once a merged one is
reopened, runs again and goes to a person. An attempt under way is let finish: only the next
dispatch is held. The run goes on with every subtask that does not read from it, and waits on the
queue when nothing else can run. The hold is let go once the producer merged, ended without a
merge, or waits for sizing's closing pass, which comes after the subtask; the release line says
which, so a reader tells "waited, then ran without it" from "ran before it". Two subtasks that read
from each other are never held, and a line says so.

A run started under the ``wait_cycle`` mark ``release`` also lets a hold go when its producer can
never end before the held subtask runs: it waits, through builder and reader holds, for that
subtask, or is a builder held for good (:mod:`physgate.orchestrator.wait_cycle`).

A run started under ``release_2`` opens a hold only on a producer that is itself escalated with
its item undecided, never on one merely blocked behind such a producer. An open hold can outlive
that: a person's decision takes the producer out of ``escalated`` (a retry or a fix ordered, a
reopen after a merge) without ending it. The hold is then let go on the two outcomes of the
earlier rule, and only on them:

* ``producer_waits_for_reader``: the producer's next dispatch waits for the reader, directly or
  through a chain whose links are a builder's wait for a designer that has not merged and holds
  that are open (never one that is only owed), so neither could run and no person could lift
  either;
* ``producer_held_for_good``: the producer is a builder that can never run again.

Every chain of waits was walked: it ends in a subtask with a person (an item is open), in a subtask
that can run (the run is not waiting), in a cycle (the first outcome lets its hold go; a cycle
holds a reader hold, as builder links alone cannot cycle) or in a subtask that can never run (the
second). A producer that is running its retry, or is about to, keeps its readers: they wait for
its new values, and are let go only because it waits for them or can never run. No other release is
written for a hold on a producer, so a reader is never let go merely because its producer waits
for a person elsewhere. The cost: a reader of a producer blocked behind a person may run on the
plan's interface values, and a reader of a reader runs before the middle module has merged; a
module downstream is reopened only by a person's choice or by its own failing pair, and what it
read through another module's own nodes is covered by no test. A run recorded under ``release``
or with no mark replays as it always did, cycle releases included.

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

#: The two outcomes of the ``wait_cycle`` rule (:mod:`physgate.orchestrator.wait_cycle`).
CYCLE_OUTCOMES = ("producer_waits_for_reader", "producer_held_for_good")

#: What a subtask's dispatch is turned into: a line to write first, or passed over.
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
    #: ``True`` once the run's first line says it started under the ``wait_cycle`` rule: a hold
    #: on a producer that can never end before the reader runs is let go, on a line of its own.
    cycle: bool = False
    #: ``True`` once the first line says ``release_2``: a hold is only ever on a producer that is
    #: itself with a person (:func:`root_item`), and the run's end names what never ran.
    narrow: bool = False
    #: Each (reader, producer, attempts on record) that rule let go: one line per dispatch.
    let_go: set[tuple[str, str, int]] = field(default_factory=set)


@dataclass(frozen=True)
class _Owed:
    kind: Literal["hold", "release"]
    producer: str
    item_id: str
    interfaces: tuple[str, ...] = ()
    outcome: ReleasedHow | None = None


def let_go_key(state: RunState, reader: str, producer: str) -> tuple[str, str, int]:
    """The dispatch of ``reader`` the cycle rule let go of ``producer``: once per dispatch."""
    return (reader, producer, len(state.subtasks[reader].attempts))


def _applies(state: RunState) -> bool:
    return state.acts and state.contract_pairs is not None


def dispatch_due(state: RunState, subtask_id: str) -> bool:
    """Whether ``subtask_id``'s next line starts an attempt not yet on the record: a dispatch.

    Its first attempt, or a later one: the next after a rejection, a fix a person ordered, or a
    reopen. An attempt under way is not, nor one restarted after an infrastructure failure or a
    kill: it is let finish.
    """
    sub = state.subtasks[subtask_id]
    if sub.status not in ("planned", "active") or sub.next_resolve is None:
        return False
    return not sub.attempts or sub.attempts[-1].number != sub.next_resolve


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


def root_item(state: RunState, producer: str, seen: frozenset[str] = frozenset()) -> str | None:
    """The undecided item ``producer`` waits on, directly or through a chain; ``None`` if none.

    In a run started under ``release_2`` only directly: a producer merely blocked behind one that
    is with a person holds nobody, so every wait ends in a person or in a subtask that can run.

    Directly: it is escalated and its item undecided. Through a chain: its next dispatch is due
    and a subtask it reads from waits so, at any depth, so it would be held itself; the item is
    the one at the chain's root, which a person can act on. Two subtasks that read from each other
    are never held, so a link between them is not followed, and no subtask is visited twice.
    """
    item = waiting_item(state, producer)
    if item is not None or state.producer_waits.narrow:
        return item
    if not dispatch_due(state, producer) or producer in seen:
        return None
    for pair in _reads_from(state, producer):
        upstream = pair.producer.subtask_id
        if _mutual(state, producer, upstream):
            continue
        found = root_item(state, upstream, seen | {producer})
        if found is not None:
            return found
    return None


def released_how(state: RunState, producer: str) -> ReleasedHow | None:
    """How a hold on ``producer`` is let go now; ``None`` while it waits on a person or runs.

    A producer not yet dispatched, held itself, about to run or running again after a reopen,
    keeps its readers held: they are let go only by how it ends, link by link along a chain.
    """
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
    """The line the record owes before ``subtask_id``'s next dispatch, ``held``, or nothing.

    Every open hold is let go first, in the order written; while one stays open the subtask is
    passed over. A further hold is looked for only once none is open.
    """
    from physgate.orchestrator.wait_cycle import letting_go  # noqa: PLC0415 - it reads this module

    cycle = state.producer_waits.cycle
    holds = [h for (d, _), h in state.producer_waits.open.items() if d == subtask_id]
    for hold in holds:
        how = released_how(state, hold.producer)
        if how is None and cycle:
            how = letting_go(state, hold.producer, subtask_id)
        if how is not None:
            return _Owed("release", hold.producer, hold.item_id, outcome=how)
    if holds:
        return "held"
    for pair in _reads_from(state, subtask_id):
        producer = pair.producer.subtask_id
        item = root_item(state, producer, frozenset({subtask_id}))
        if item is None:
            continue
        if _mutual(state, subtask_id, producer):
            if (subtask_id, producer, item) in state.producer_waits.mutual:
                continue
            return _Owed("release", producer, item, outcome="mutual_readers")
        if cycle:
            if let_go_key(state, subtask_id, producer) in state.producer_waits.let_go:
                continue  # let go of this producer for this dispatch: never held on it again
            # Under ``release_2`` a producer with a person has no next dispatch to wait on, so no
            # release can be owed in place of a new hold: only the hold already open is let go.
            how = None if state.producer_waits.narrow else letting_go(state, producer, subtask_id)
            if how is not None:
                return _Owed("release", producer, item, outcome=how)
        return _Owed("hold", producer, item, interfaces=pair.interfaces)
    return None


def gated(state: RunState, subtask_id: str) -> Gated | None:
    """What becomes of ``subtask_id``'s next dispatch; ``None`` when it goes ahead as planned."""
    if not _applies(state) or not dispatch_due(state, subtask_id):
        return None
    owed = _owed(state, subtask_id)
    if owed is None:
        return None
    return owed if isinstance(owed, str) else owed.kind


def held_subtask(state: RunState) -> str | None:
    """The first subtask due a dispatch that a hold on the record keeps back, in plan order."""
    if not _applies(state):
        return None
    for subtask_id in state.order:
        if not dispatch_due(state, subtask_id):
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
    owed = _owed(state, subtask_id) if dispatch_due(state, subtask_id) else None
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
    elif event.outcome in CYCLE_OUTCOMES:
        state.producer_waits.let_go.add(let_go_key(state, subtask_id, event.producer))
        state.producer_waits.open.pop((subtask_id, event.producer), None)
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
