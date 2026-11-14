"""A hold on a producer is let go by how the producer stands, read from the record's state alone.

Merged: ``merged``. Rejected, removed, or escalated with its item decided and nothing acted on:
``ended_unmerged``. Waiting for sizing's closing pass after a person chose its value in a dispute:
``waits_for_closing_pass``, since that pass comes after the reader, which would otherwise wait for
it. Escalated with its item undecided, or held for an operator's confirmation, or running again
after a decision: still held.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from physgate.contracts.pairs import ContractPair, Side
from physgate.orchestrator.producer_wait import (
    Waits,
    gated,
    released_how,
    root_item,
    waiting_item,
)

ITEM = "run-1-drive-1"


@dataclass
class _Sub:
    status: str
    queue_item: str | None = ITEM
    next_resolve: int | None = None


@dataclass
class _State:
    """The two parts of the run's state the rule reads: each subtask, and which items are open."""

    subtasks: dict[str, _Sub]
    open_items: set[str] = field(default_factory=set)

    def undecided(self, item_id: str) -> bool:
        return item_id in self.open_items


@pytest.mark.parametrize(
    ("status", "undecided", "how"),
    [
        ("done", False, "merged"),
        ("rejected", False, "ended_unmerged"),
        ("removed", False, "ended_unmerged"),
        ("escalated", False, "ended_unmerged"),
        ("waiting", False, "waits_for_closing_pass"),
        ("escalated", True, None),
        ("active", False, None),
    ],
)
def test_how_a_hold_is_let_go(status: str, undecided: bool, how: str | None) -> None:  # noqa: FBT001
    state = _State({"drive": _Sub(status)}, {ITEM} if undecided else set())
    assert released_how(state, "drive") == how  # type: ignore[arg-type]


def test_only_an_escalated_producer_with_its_item_undecided_waits_on_a_person() -> None:
    for status in ("planned", "active", "waiting", "done", "rejected", "removed"):
        state = _State({"drive": _Sub(status)}, {ITEM})
        assert waiting_item(state, "drive") is None, status  # type: ignore[arg-type]
    assert waiting_item(_State({"drive": _Sub("escalated")}, {ITEM}), "drive") == ITEM  # type: ignore[arg-type]
    assert waiting_item(_State({"drive": _Sub("escalated")}), "drive") is None  # type: ignore[arg-type]
    assert waiting_item(_State({"drive": _Sub("escalated", None)}, {ITEM}), "drive") is None  # type: ignore[arg-type]


# --- every dispatch of a reader is held, and an attempt under way is let finish -------------------


def _side(subtask_id: str) -> Side:
    return Side(module=subtask_id, subtask_id=subtask_id, role=subtask_id)


def _pair(producer: str, consumer: str) -> ContractPair:
    return ContractPair(
        producer=_side(producer), consumer=_side(consumer), interfaces=(f"iface.{producer}",)
    )


@dataclass
class _Run:
    """What the hold reads of a run that acts on decisions by its recorded pairs."""

    subtasks: dict[str, _Sub]
    contract_pairs: tuple[ContractPair, ...]
    open_items: set[str] = field(default_factory=lambda: {ITEM})
    acts: bool = True
    producer_waits: Waits = field(default_factory=Waits)

    def undecided(self, item_id: str) -> bool:
        return item_id in self.open_items


#: Not dispatched yet; its next attempt due after an earlier one; an attempt under way; merged.
STANDINGS = [
    ("planned", 1, "hold"),
    ("active", 2, "hold"),
    ("active", None, None),
    ("done", None, None),
]


@pytest.mark.parametrize(("status", "next_resolve", "gate"), STANDINGS)
def test_a_reader_is_held_at_every_dispatch_and_never_inside_an_attempt(
    status: str, next_resolve: int | None, gate: str | None
) -> None:
    state = _Run(
        {"drive": _Sub("escalated"), "budget": _Sub(status, None, next_resolve)},
        (_pair("drive", "budget"),),
    )
    assert gated(state, "budget") == gate  # type: ignore[arg-type]


@pytest.mark.parametrize(("status", "next_resolve", "gate"), STANDINGS)
def test_a_reader_of_a_reader_waits_on_the_root_while_the_middle_ones_next_dispatch_is_due(
    status: str, next_resolve: int | None, gate: str | None
) -> None:
    state = _Run(
        {
            "drive": _Sub("escalated"),
            "fw": _Sub(status, None, next_resolve),
            "budget": _Sub("active", None, 2),
        },
        (_pair("drive", "fw"), _pair("fw", "budget")),
    )
    assert gated(state, "budget") == gate  # type: ignore[arg-type]
    if gate == "hold":
        assert root_item(state, "fw") == ITEM  # type: ignore[arg-type]
