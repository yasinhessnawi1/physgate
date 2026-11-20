"""A builder is not dispatched until the module whose design it implements has merged.

"Implements" is the run's recorded design pairs (:mod:`physgate.orchestrator.design_pairs`), read
from the plan before any module runs. Every dispatch of a builder, its first or a later attempt's,
is held while a designer it pairs with has not merged: while the designer is with a person (the
line names the undecided item, so the hold pairs with something a person can act on), after it
ended without a merge (the builder then has nothing to build, so it stays held, and is neither run
nor failed), while the designer is itself a builder held so for good (a chain of pairs: the line
names the chain, and the builder is held for good as well), or while it has not merged for any
other reason. The line says which, and a new line
is written whenever that changes; the hold is let go once the designer merged, and the release
line says so. An attempt under way is let finish: only the next dispatch is held.

Where a builder is also a reader of the designer's interfaces, the reader's wait
(:mod:`physgate.orchestrator.producer_wait`) is asked first: a builder is dispatched only once
neither holds it. A run that acts on decisions waits on the queue while a held builder's designer
is with a person and nothing else can run; a builder held after its designer ended without a merge,
or in a run that records only, where no decision is ever taken, holds no wait: the run goes on to
its integration call, which names the builder among the subtasks that did not merge.

Only in a run whose opening records design pairs; a run recorded before them, or with none, has
none of these lines and replays as it did. A run with pairs is held to them strictly: replay
refuses a builder's dispatch the record owed a hold or release line before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from physgate.orchestrator import producer_wait
from physgate.orchestrator.events import (
    BuilderHeld,
    BuilderHeldWhy,
    BuilderReleased,
    DispatchHeld,
    DispatchReleased,
)
from physgate.orchestrator.producer_wait import Gated, dispatch_due, waiting_item

if TYPE_CHECKING:
    from physgate.orchestrator.design_pairs import DesignPair
    from physgate.orchestrator.events import Envelope
    from physgate.orchestrator.replay import RunState


@dataclass
class DesignWaits:
    """The builders' holds on the record, each open one by (builder, designer): its last line."""

    open: dict[tuple[str, str], BuilderHeld] = field(default_factory=dict)


#: Why a builder of a designer is held now: the reason, the item it waits on, the chain it names.
Standing = tuple[BuilderHeldWhy, str | None, tuple[str, ...] | None]


@dataclass(frozen=True)
class _Owed:
    kind: Literal["hold", "release"]
    pair: DesignPair
    standing: Standing | None = None


def _applies(state: RunState) -> bool:
    return state.design_pairs is not None


def _designers(state: RunState, builder: str) -> list[DesignPair]:
    """The pairs whose builder is ``builder``, in the recorded order."""
    return [p for p in state.design_pairs or () if p.builder == builder]


def standing(state: RunState, designer: str) -> Standing | None:
    """Why a builder of ``designer`` is held now; ``None`` once ``designer`` merged.

    A designer that is itself a builder held for good never merges: its builder is held for good
    too, on a line naming the chain from ``designer`` to the subtask that can no longer merge.
    """
    sub = state.subtasks[designer]
    if sub.status == "done":
        return None
    if sub.status in ("rejected", "removed"):
        return ("ended_unmerged", None, None)
    if sub.status == "escalated":
        item = waiting_item(state, designer)
        # A decision taken on its item that acted on nothing ends it there.
        return ("escalated", item, None) if item is not None else ("ended_unmerged", None, None)
    beyond = _held_for_good_by(state, designer)
    if beyond is not None:
        return ("designer_held", None, (designer, *beyond))
    return ("not_merged", None, None)


def _owed(state: RunState, builder: str) -> _Owed | Literal["held"] | None:
    """The line the record owes before ``builder``'s next dispatch, ``held``, or nothing.

    Pair by pair in the recorded order: a release once its designer merged, a hold where none is
    open or why it holds has changed. Once none is owed, the builder is passed over while any
    hold of it is open.
    """
    for pair in _designers(state, builder):
        now = standing(state, pair.designer)
        held = state.design_waits.open.get((builder, pair.designer))
        if now is None:
            if held is not None:
                return _Owed("release", pair)
            continue
        if held is None or (held.why, held.item_id, held.chain) != now:
            return _Owed("hold", pair, standing=now)
    if any(b == builder for b, _ in state.design_waits.open):
        return "held"
    return None


def design_gated(state: RunState, subtask_id: str) -> Gated | None:
    """What a builder's wait makes of ``subtask_id``'s next dispatch; ``None`` if it goes ahead."""
    if not _applies(state) or not dispatch_due(state, subtask_id):
        return None
    owed = _owed(state, subtask_id)
    if owed is None:
        return None
    return owed if isinstance(owed, str) else owed.kind


def gated(state: RunState, subtask_id: str) -> Gated | None:
    """What becomes of ``subtask_id``'s next dispatch under both waits; ``None`` if it goes ahead.

    The reader's wait first: a builder's wait is asked only once that one lets it go.
    """
    return producer_wait.gated(state, subtask_id) or design_gated(state, subtask_id)


def held_subtask(state: RunState) -> str | None:
    """The first subtask the queue holds back: a reader's, else a builder's, whose designer waits.

    A builder's only in a run that acts on decisions, and only while its designer is with a person:
    a hold after the designer ended without a merge waits on nothing a person can decide.
    """
    reader = producer_wait.held_subtask(state)
    if reader is not None or not _applies(state) or not state.acts:
        return reader
    for subtask_id in state.order:
        if not dispatch_due(state, subtask_id):
            continue
        if any(
            b == subtask_id and held.why == "escalated"
            for (b, _), held in state.design_waits.open.items()
        ):
            return subtask_id
    return None


def held_for_good(state: RunState, subtask_id: str) -> bool:
    """Whether ``subtask_id`` is a builder no decision of this run can let go any more.

    Held, with nothing owed, by a hold whose designer ended without a merge, by one whose
    designer is with a person in a run that records only, or by one whose designer is itself
    held so for good. Integration is called with such a builder unmerged, as with a subtask that
    ended.
    """
    return _held_for_good_by(state, subtask_id) is not None


def _held_for_good_by(state: RunState, subtask_id: str) -> tuple[str, ...] | None:
    """The chain that holds ``subtask_id`` for good, from its designer on; ``None`` if none does.

    The earliest such hold of its on the record, so the chain a line names does not move while the
    holds it rests on stand, whatever later holds join them. A designer is dispatched
    before its builder, so the chain is followed back through the plan and ends.
    """
    if not _applies(state) or design_gated(state, subtask_id) != "held":
        return None
    for_good = [
        held
        for pair in _designers(state, subtask_id)
        if (held := state.design_waits.open.get((subtask_id, pair.designer))) is not None
        and (
            held.why in ("ended_unmerged", "designer_held")
            or (held.why == "escalated" and not state.acts)
        )
    ]
    if not for_good:
        return None
    first = min(for_good, key=lambda held: held.seq)
    return first.chain if first.chain is not None else (first.designer,)


def wait_line(
    state: RunState, subtask_id: str, envelope: Envelope
) -> DispatchHeld | DispatchReleased | BuilderHeld | BuilderReleased:
    """The hold or release line the record owes for ``subtask_id``, of either wait.

    Raises:
        ValueError: the record owes none.
    """
    if producer_wait.gated(state, subtask_id) in ("hold", "release"):
        return producer_wait.owed_line(state, subtask_id, envelope)
    owed = _owed(state, subtask_id) if design_gated(state, subtask_id) else None
    if not isinstance(owed, _Owed):
        msg = f"no hold or release is owed for {subtask_id!r}"
        raise ValueError(msg)
    if owed.kind == "release":
        return BuilderReleased(
            **envelope,
            subtask_id=subtask_id,
            designer=owed.pair.designer,
            nodes=owed.pair.nodes,
        )
    assert owed.standing is not None  # noqa: S101 - every hold is built with why
    why, item_id, chain = owed.standing
    return BuilderHeld(
        **envelope,
        subtask_id=subtask_id,
        designer=owed.pair.designer,
        nodes=owed.pair.nodes,
        why=why,
        item_id=item_id,
        chain=chain,
    )


def take(state: RunState, event: BuilderHeld | BuilderReleased) -> str | None:
    """Take a builder's hold or release line; why it cannot come next, or ``None`` once taken."""
    subtask_id = event.subtask_id
    if subtask_id not in state.subtasks or not _applies(state):
        return "a builder's hold or release in a run that records no design pairs"
    kind = "hold" if isinstance(event, BuilderHeld) else "release"
    step = state.next_step()
    owed = _owed(state, subtask_id) if design_gated(state, subtask_id) else None
    if (step.kind, step.subtask_id) != (kind, subtask_id) or not isinstance(owed, _Owed):
        return f"no {type(event).__name__} is owed for {subtask_id!r} now"
    if producer_wait.gated(state, subtask_id) is not None:
        return f"a builder's {kind} for {subtask_id!r} while a reader's wait still holds it"
    if (event.designer, event.nodes) != (owed.pair.designer, owed.pair.nodes) or (
        isinstance(event, BuilderHeld) and (event.why, event.item_id, event.chain) != owed.standing
    ):
        return (
            f"a builder's {kind} names another designer, nodes, reason or chain than the record "
            "owes"
        )
    if owed.kind != kind:
        return f"no {type(event).__name__} is owed for {subtask_id!r} now"
    if isinstance(event, BuilderHeld):
        state.design_waits.open[(subtask_id, event.designer)] = event
    else:
        del state.design_waits.open[(subtask_id, event.designer)]
    return None


def held_dispatch(state: RunState, subtask_id: str) -> str | None:
    """Why ``subtask_id`` cannot be dispatched now as a builder, or ``None``.

    A hold on the record still keeps it back; or the record owes a hold or release line before
    it, which a dispatch in its place left out.
    """
    if not _applies(state):
        return None
    for (b, designer), held in state.design_waits.open.items():
        if b == subtask_id:
            return (
                f"{subtask_id!r} is held while {designer!r}, whose design it implements, has not "
                f"merged ({held.why})"
            )
    owed = _owed(state, subtask_id)
    if isinstance(owed, _Owed):
        return (
            f"{subtask_id!r} is dispatched while {owed.pair.designer!r}, whose design it "
            f"implements, has not merged, with no {owed.kind} line on the record"
        )
    return None


def open_holds(state: RunState) -> list[BuilderHeld]:
    """Every builder's hold open on the record, in plan order of the builder."""
    rank = {subtask_id: index for index, subtask_id in enumerate(state.order)}
    return sorted(state.design_waits.open.values(), key=lambda h: rank.get(h.subtask_id, 0))


def held_builders(state: RunState) -> dict[str, list[dict[str, object]]]:
    """The open builders' holds as a run's status prints them: ``{"held": [...]}``, or nothing."""
    holds = [
        held.model_dump(include={"subtask_id", "designer", "nodes", "why", "item_id", "chain"})
        for held in open_holds(state)
    ]
    return {"held": holds} if holds else {}
