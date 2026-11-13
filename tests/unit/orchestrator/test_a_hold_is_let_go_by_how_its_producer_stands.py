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

from physgate.orchestrator.producer_wait import released_how, waiting_item

ITEM = "run-1-drive-1"


@dataclass
class _Sub:
    status: str
    queue_item: str | None = ITEM


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
