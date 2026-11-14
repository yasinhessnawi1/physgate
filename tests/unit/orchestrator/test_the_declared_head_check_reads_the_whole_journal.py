"""The declared head check reads the whole journal, at every place the journal is accounted for.

ARCH-122. The check is a function of the journal's lines and the landed parts writes alone: the
head of each node is its latest line, a landed write must still be its line, and every declared
quantity at the head is one the node's latest landed write holds. It runs when a session ends
too, so a line before the head changed while a session ran halts the run there, before the gate,
and not only at the next merge. A journal that cannot be read for the check halts it as well.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, Rig, plan
from test_a_declared_quantity_no_landed_parts_write_wrote_halts_the_run import (
    FORGED,
    HONEST,
    Journal,
    declared,
    events,
    incidents,
    merged,
    node,
    q,
)

from physgate.orchestrator.events import StageEntered
from physgate.state.exceptions import DesignStateError
from physgate.state.store import JournalLine, payload_digest


def unlanded(lines: list[Any], landed: list[tuple[str, str, int]]) -> str | None:
    """The check's answer, or a failing assertion while it is not built."""
    module = importlib.import_module("physgate.orchestrator.parts_write")
    found = getattr(module, "unlanded_declared", None)
    if found is None:
        pytest.fail("parts_write.unlanded_declared is not built yet")
    answer: str | None = found(lines, landed)
    return answer


def line(rev: int, payload: dict[str, Any]) -> Any:  # noqa: ANN401
    return SimpleNamespace(rev=rev, op="write", node_id=payload["id"], payload=payload)


PARTS = node("control.motor", {"mass": declared(0.4, "kg")})
LANDED = [("control.motor", payload_digest(PARTS), 2)]
OTHER = node("electrical.motor", {"stall_current": q(2.4, "A")})


def test_a_journal_that_holds_what_landed_holds() -> None:
    assert unlanded([line(1, OTHER), line(2, PARTS)], LANDED) is None


def test_a_later_line_that_keeps_the_declared_quantity_and_adds_its_own_holds() -> None:
    later = node("control.motor", {"mass": declared(0.4, "kg"), "stall_current": q(1.0, "A")})
    assert unlanded([line(1, OTHER), line(2, PARTS), line(3, later)], LANDED) is None


@pytest.mark.parametrize(
    "later",
    [
        node("control.motor", {"stall_current": q(1.0, "A")}),
        node("control.motor", {"mass": declared(0.9, "kg")}),
        node("control.motor", {"mass": q(0.4, "kg")}),
    ],
    ids=["dropped", "value-changed", "record-dropped"],
)
def test_a_later_line_that_changes_or_drops_the_declared_quantity_is_named(
    later: dict[str, Any],
) -> None:
    said = unlanded([line(1, OTHER), line(2, PARTS), line(3, later)], LANDED)
    assert said is not None and "mass" in said and "control.motor" in said


def test_a_declared_quantity_on_a_node_no_landed_write_wrote_is_named() -> None:
    forged = node("electrical.motor", {"mass": declared(0.4, "kg")})
    said = unlanded([line(1, forged), line(2, PARTS)], LANDED)
    assert said is not None and "electrical.motor" in said


def test_a_landed_revision_the_journal_does_not_hold_is_named() -> None:
    said = unlanded([line(1, OTHER)], LANDED)
    assert said is not None and "revision 2" in said


def test_a_landed_revision_holding_another_node_is_named() -> None:
    moved = SimpleNamespace(rev=2, op="write", node_id="control.other", payload=PARTS)
    said = unlanded([line(1, OTHER), moved], LANDED)
    assert said is not None and "revision 2" in said


def test_the_lines_are_read_in_revision_order_whatever_order_they_come_in() -> None:
    later = node("control.motor", {"stall_current": q(1.0, "A")})
    said = unlanded([line(3, later), line(2, PARTS), line(1, OTHER)], LANDED)
    assert said is not None and "mass" in said


@dataclass
class Tampering(FakeDispatcher):
    """While the second subtask's session runs, the first one's merged line is changed."""

    journal: Journal | None = None

    def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's types
        report = super().run(request, on_spawn)
        if request.subtask_id == "s2" and self.journal is not None:
            first = self.journal.lines[0]
            self.journal.lines[0] = JournalLine(
                rev=first.rev, op=first.op, node_id=first.node_id, version=first.version,
                payload=FORGED,
            )  # fmt: skip
        return report


def test_a_line_changed_while_a_session_ran_halts_when_the_session_ends_before_the_gate(
    tmp_path: Path,
) -> None:
    journal = Journal(writes=[HONEST])
    rig = Rig(tmp_path, diff=journal, dispatcher=Tampering(journal=journal))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = incidents(tmp_path)
    assert (incident.cause, incident.subtask_id) == ("foreign_journal_line", "s2")
    assert [m.subtask_id for m in merged(tmp_path)] == ["s1"]
    stages = [e.stage for e in events(tmp_path) if isinstance(e, StageEntered)]
    s2 = [e.stage for e in events(tmp_path) if isinstance(e, StageEntered) and e.subtask_id == "s2"]
    assert "gate" not in s2 and stages


@dataclass
class Unreadable(Journal):
    """A journal whose whole read fails once a line is in it, as a corrupted early line does."""

    def records_after(self, revision: int) -> list[Any]:
        if revision == 0 and self.lines:
            msg = "the journal holds a record this package could not have written"
            raise DesignStateError(msg)
        return super().records_after(revision)


def test_a_journal_the_check_cannot_read_halts_the_run(tmp_path: Path) -> None:
    rig = Rig(tmp_path, diff=Unreadable(writes=[HONEST]))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    (incident,) = incidents(tmp_path)
    assert incident.cause == "foreign_journal_line"
    assert "could not have written" in incident.detail
    assert merged(tmp_path) == []
