"""What sizing's closing pass owes the domain modules: one follow-up for each node it reached.

The propagation check (ARCH-082) asks of every changed node whether each node it constrains
was rewritten after it, or says in its own ``no_change_justified`` why it need not be. Sizing's
closing pass runs after every domain module, and no domain session ran after it, so a value it
changes leaves each domain node that value constrains unwritten. The harness therefore owes the
module that wrote such a node one follow-up session of its own role.

What is owed is computed from the canonical journal and the change history alone, and on the
safe side: a value counts as changed when its quantities differ as written, so a respelled unit
may cost a session the check would not have asked for, and never the other way round. The check
stays the authority over what passes. Owed, for every module the closing pass reached:

- every node the closing pass created or wrote with other quantities, and every edge it carried
  before or after, a dropped edge included;
- into a node that exists, is not an interface node, was last written before the closing pass,
  and was last written by one of the candidate modules (the domain modules that merged).

A write that keeps every quantity (a justification added, say) owes nothing; nor does an edge
into a node written again since, by a domain attempt that returned to the gate after the pass.
"""

from __future__ import annotations

import importlib
from collections.abc import Collection, Sequence
from typing import Any, Literal

import pytest

from physgate.orchestrator.protocols import ChangeSet
from physgate.state.store import JournalLine

BUS = "sizing.bus"
DRIVER = "electrical.driver"
LOOP = "control.loop"


def quantity(value: float, unit: str, by: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "datasheet", "written_by": by}


def node(
    node_id: str,
    owner: str,
    *,
    domain: str | None = None,
    kind: str = "component",
    constrains: Sequence[str] = (),
    amps: float = 2.0,
    **fields: Any,  # noqa: ANN401 - a node's own fields
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": domain or ("cross" if owner == "sizing" else owner),
        "owner_role": owner,
        "quantities": {"peak_current": quantity(amps, "A", owner)},
        "constrains": list(constrains),
        "geometry_hash": "g0",
        "updated": "2026-11-01T00:00:00Z",
        **fields,
    }


class Journal:
    """A canonical journal and the change history the loop's log would give for it."""

    def __init__(self) -> None:
        self.lines: list[JournalLine] = []
        self.sets: list[ChangeSet] = []

    def merge(self, subtask_id: str, *payloads: dict[str, Any], attempt: int = 1) -> None:
        revisions = []
        for payload in payloads:
            seen = [ln for ln in self.lines if ln.node_id == payload["id"]]
            rev = len(self.lines) + 1
            op: Literal["create", "write"] = "write" if seen else "create"
            self.lines.append(
                JournalLine(
                    rev=rev, op=op, node_id=payload["id"], version=len(seen) + 1, payload=payload
                )
            )
            revisions.append(rev)
        self.sets.append(
            ChangeSet(subtask_id=subtask_id, attempt=attempt, revisions=tuple(revisions))
        )


def owed(
    journal: Journal, closing: str = "zc", candidates: Collection[str] = ("s1", "s2")
) -> dict[str, list[tuple[str, str]]]:
    """What the closing pass owes, by module, as (source, target) pairs; a failure if unbuilt."""
    try:
        computed = importlib.import_module("physgate.orchestrator.follow_up").owed
    except (ImportError, AttributeError):
        pytest.fail("no computation of what sizing's closing pass owes the domain modules")
    found = computed(journal.lines, journal.sets, closing, frozenset(candidates))
    return {s: [(e.source, e.target) for e in edges] for s, edges in found.items()}


def slice_journal(closing: dict[str, Any] | None = None) -> Journal:
    """Sizing's opening pass writes the bus; s1 writes the driver it constrains; then the pass."""
    journal = Journal()
    journal.merge("z0", node(BUS, "sizing", constrains=[DRIVER]))
    journal.merge("s1", node(DRIVER, "electrical", constrains=[BUS]))
    journal.merge("zc", closing or node(BUS, "sizing", constrains=[DRIVER], amps=3.0))
    return journal


def test_a_changed_value_owes_the_module_that_wrote_each_node_it_constrains() -> None:
    assert owed(slice_journal()) == {"s1": [(BUS, DRIVER)]}


def test_a_write_that_keeps_every_quantity_owes_nothing() -> None:
    # The closing pass keeps the values and says why under the domain's node id: no change.
    kept = node(BUS, "sizing", constrains=[DRIVER], no_change_justified={DRIVER: "still holds"})
    assert owed(slice_journal(kept)) == {}


def test_a_respelled_value_counts_as_changed_on_the_safe_side() -> None:
    respelled = node(BUS, "sizing", constrains=[DRIVER])
    respelled["quantities"] = {"peak_current": quantity(2000.0, "mA", "sizing")}
    assert owed(slice_journal(respelled)) == {"s1": [(BUS, DRIVER)]}


def test_an_edge_the_closing_pass_dropped_is_still_owed() -> None:
    assert owed(slice_journal(node(BUS, "sizing", amps=3.0))) == {"s1": [(BUS, DRIVER)]}


def test_a_node_the_closing_pass_created_owes_each_node_it_constrains() -> None:
    journal = slice_journal(node(BUS, "sizing", constrains=[DRIVER]))
    journal.sets.pop()
    journal.lines.pop()
    journal.merge("zc", node("sizing.rail", "sizing", constrains=[DRIVER]))
    assert owed(journal) == {"s1": [("sizing.rail", DRIVER)]}


def test_an_interface_node_owes_nothing() -> None:
    journal = Journal()
    journal.merge("z0", node(BUS, "sizing", constrains=["iface.bus"]))
    journal.merge("s1", node("iface.bus", "electrical", kind="interface", domain="cross"))
    journal.merge("zc", node(BUS, "sizing", constrains=["iface.bus"], amps=3.0))
    assert owed(journal) == {}


def test_a_node_written_again_since_the_closing_pass_owes_nothing() -> None:
    # A domain attempt that returned to the gate after the pass merged it, as a resize does.
    journal = slice_journal()
    journal.merge("s1", node(DRIVER, "electrical", constrains=[BUS], amps=3.0), attempt=2)
    assert owed(journal) == {}


def test_a_node_no_candidate_wrote_owes_nothing() -> None:
    # Sizing's own nodes, a node no module of the run wrote, and one no node by that id.
    journal = Journal()
    journal.lines.append(
        JournalLine(rev=1, op="create", node_id=LOOP, version=1, payload=node(LOOP, "control"))
    )
    journal.merge("z0", node(BUS, "sizing", constrains=["sizing.rail", LOOP, "gone.node"]))
    journal.merge("z0", node("sizing.rail", "sizing"), attempt=2)
    journal.merge(
        "zc", node(BUS, "sizing", constrains=["sizing.rail", LOOP, "gone.node"], amps=3.0)
    )
    assert owed(journal, candidates=("s1", "z0")) == {"z0": [(BUS, "sizing.rail")]}
    assert owed(journal) == {}


def test_each_module_reached_is_owed_once_with_every_edge_in_order() -> None:
    journal = Journal()
    journal.merge("z0", node(BUS, "sizing", constrains=[DRIVER, LOOP]))
    journal.merge("z0", node("sizing.rail", "sizing", constrains=[DRIVER]), attempt=2)
    journal.merge("s1", node(DRIVER, "electrical"))
    journal.merge("s2", node(LOOP, "control"))
    journal.merge(
        "zc",
        node(BUS, "sizing", constrains=[DRIVER, LOOP], amps=4.0),
        node("sizing.rail", "sizing", constrains=[DRIVER], amps=5.0),
    )
    assert owed(journal) == {
        "s1": [(BUS, DRIVER), ("sizing.rail", DRIVER)],
        "s2": [(BUS, LOOP)],
    }


def test_without_a_closing_pass_merge_nothing_is_owed() -> None:
    journal = slice_journal()
    assert owed(journal, closing="zz") == {}


# --- a closing pass that merges twice: each change set judged as the propagation check does -----


def _two_closing_merges(between: str) -> Journal:
    """Sizing's closing pass merges, is reopened and merges again."""
    journal = Journal()
    journal.merge("z0", node(BUS, "sizing", constrains=[DRIVER], amps=2.0))
    journal.merge("s1", node(DRIVER, "electrical", amps=2.0))
    journal.merge("zc", node(BUS, "sizing", constrains=[DRIVER], amps=3.0))
    if between == "changed back":
        journal.merge("zc", node(BUS, "sizing", constrains=[DRIVER], amps=2.0), attempt=2)
    elif between == "target rewritten, changed again":
        journal.merge("s1", node(DRIVER, "electrical", amps=2.0), attempt=2)
        journal.merge("zc", node(BUS, "sizing", constrains=[DRIVER], amps=4.0), attempt=2)
    elif between == "target rewritten, kept":
        journal.merge("s1", node(DRIVER, "electrical", amps=2.0), attempt=2)
        journal.merge("zc", node(BUS, "sizing", constrains=[DRIVER], amps=3.0), attempt=2)
    return journal


@pytest.mark.parametrize("between", ["changed back", "target rewritten, changed again"])
def test_a_second_closing_merge_that_changes_the_source_owes_its_edges(between: str) -> None:
    assert owed(_two_closing_merges(between)) == {"s1": [(BUS, DRIVER)]}


def test_a_second_closing_merge_that_keeps_the_source_owes_nothing_rewritten_since() -> None:
    assert owed(_two_closing_merges("target rewritten, kept")) == {}
