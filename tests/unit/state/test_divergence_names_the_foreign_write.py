"""An injected cross-role write is named from the change list of one step.

The store refuses a cross-role write at the point of writing, so a write that
reaches the graph anyway did not come through the guard. This is the check that
sees it, and it sees it off the durable record, which is the only way it can see
a write the store never made.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from helpers import node

from physgate.state.divergence import Divergence, divergence
from physgate.state.exceptions import MalformedNodeIdError
from physgate.state.protocol import NodeChange
from physgate.state.store import Store


def append_to_the_journal_behind_the_stores_back(
    root: Path,
    payload: dict[str, Any],
    *,
    node_id: str | None = None,
    op: str | None = None,
    version: int | None = None,
) -> int:
    """Write a node the way something bypassing the store would.

    A journal line and a node file, with no guard between. This is what an agent
    editing a file in its worktree and committing it looks like by the time the
    orchestrator reads the graph.
    """
    journal = root / "journal.jsonl"
    existing = [json.loads(line) for line in journal.read_bytes().splitlines() if line]
    rev = (max((e["rev"] for e in existing), default=0)) + 1
    # The identifier is a parameter and does not default to the payload's. It
    # used to be taken from the payload, which made a record whose name and
    # content disagree unreachable from here -- so the guard against that case
    # could not be tested, and was not there.
    named = payload["id"] if node_id is None else node_id
    # Coherent by default: a record the writing code could have produced, given
    # what is already in the journal. A test that wants an incoherent one says
    # so, which is the whole reason these are parameters.
    seen = [e["version"] for e in existing if e["node_id"] == named]
    entry = {
        "rev": rev,
        "op": ("write" if seen else "create") if op is None else op,
        "node_id": named,
        "version": (max(seen) + 1 if seen else 1) if version is None else version,
        "payload": payload,
    }
    with journal.open("ab") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    (root / "nodes" / f"{named}.json").write_text(
        json.dumps(
            {"rev": rev, "version": 1, "payload": payload}, sort_keys=True, separators=(",", ":")
        )
    )
    return rev


def test_a_step_that_touched_only_its_own_nodes_diverges_not_at_all(store: Store) -> None:
    store.write_node(node("control.loop_a", owner_role="control"), "control")
    cursor = store.head_revision()
    store.write_node(node("control.loop_a", owner_role="control", updated="t1"), "control")
    store.write_node(node("control.loop_b", owner_role="control"), "control")

    assert divergence(store, store.diff(cursor), "control") == []


def test_one_injected_cross_role_write_is_named_within_the_step(tmp_path: Path) -> None:
    """The acceptance the architecture asks for: caught within one step."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("electrical.motor", owner_role="electrical"), "electrical")
    store.write_node(node("control.loop", owner_role="control"), "control")
    store.close()

    reopened = Store(root)
    cursor = reopened.head_revision()

    # The step is dispatched to control. Control writes its own node, and
    # something also writes a node electrical owns, without passing the guard.
    reopened.write_node(node("control.loop", owner_role="control", updated="t1"), "control")
    reopened.close()
    rev = append_to_the_journal_behind_the_stores_back(
        root, node("electrical.motor", owner_role="electrical", updated="tampered")
    )

    after = Store(root)
    changes = after.diff(cursor)
    assert len(changes) == 2, "both the legal change and the injected one are in the record"

    found = divergence(after, changes, "control")

    assert len(found) == 1
    assert found[0] == Divergence(
        node_id="electrical.motor",
        revision=rev,
        owner_role="electrical",
        acting_role="control",
    )
    after.close()


def test_the_guard_never_saw_the_injected_write(tmp_path: Path) -> None:
    """Which is the point: the second line catches what the first never met."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("electrical.motor", owner_role="electrical"), "electrical")
    store.close()

    refused = Store(root)
    result = refused.write_node(
        node("electrical.motor", owner_role="electrical", updated="t1"), "control"
    )
    assert result.accepted is False, "the store's own guard refuses this"
    assert refused.diff(0) == refused.diff(0)[: len(refused.diff(0))]
    assert len(refused.diff(0)) == 1, "and nothing about it reached the record"
    refused.close()

    append_to_the_journal_behind_the_stores_back(
        root, node("electrical.motor", owner_role="electrical", updated="t1")
    )
    after = Store(root)
    assert len(after.diff(0)) == 2, "bypassing the store does reach the record"
    assert len(divergence(after, after.diff(0), "control")) == 2
    after.close()


def test_every_offending_change_is_named_not_just_the_first(store: Store) -> None:
    store.write_node(node("electrical.a", owner_role="electrical"), "electrical")
    store.write_node(node("mechanical.b", owner_role="mechanical"), "mechanical")
    store.write_node(node("control.c", owner_role="control"), "control")

    found = divergence(store, store.diff(0), "control")

    assert [d.node_id for d in found] == ["electrical.a", "mechanical.b"]
    assert [d.owner_role for d in found] == ["electrical", "mechanical"]


def test_a_node_changed_twice_in_one_step_is_named_once_per_change(store: Store) -> None:
    store.write_node(node("electrical.a", owner_role="electrical"), "electrical")
    store.write_node(node("electrical.a", owner_role="electrical", updated="t1"), "electrical")

    found = divergence(store, store.diff(0), "control")

    assert [d.revision for d in found] == [1, 2]


def test_the_description_names_the_node_the_owner_and_the_acting_role() -> None:
    line = str(
        Divergence(
            node_id="electrical.motor",
            revision=7,
            owner_role="electrical",
            acting_role="control",
        )
    )
    assert "electrical.motor" in line
    assert "'electrical'" in line
    assert "'control'" in line
    assert "7" in line


def test_an_empty_change_list_diverges_not_at_all(store: Store) -> None:
    store.write_node(node("control.loop", owner_role="control"), "control")
    assert divergence(store, store.diff(store.head_revision()), "control") == []


# --- whose ownership, and as of when -----------------------------------------


def test_a_legitimate_handover_is_not_reported_as_divergent(store: Store) -> None:
    """Read as of now, a role's own writes look foreign the moment it hands over.

    A role creates its own node and passes ownership on in the same step. Both of
    its changes were legitimate when it made them, and the check must say so.
    """
    store.write_node(node("electrical.motor", owner_role="electrical"), "electrical")
    handed_on = node("electrical.motor", owner_role="electrical")
    handed_on["owner_role"] = "control"
    store.write_node(handed_on, "electrical")

    assert store.read_node("electrical.motor")["owner_role"] == "control"
    assert divergence(store, store.diff(0), "electrical") == []


def test_a_write_after_the_handover_by_the_old_owner_is_still_reported(
    store: Store,
) -> None:
    """Reading as of the change must not become a way to hide a later write."""
    store.write_node(node("control.loop", owner_role="control"), "control")
    cursor = store.head_revision()
    store.write_node(node("control.loop", owner_role="control", updated="t1"), "control")

    found = divergence(store, store.diff(cursor), "electrical")
    assert [d.owner_role for d in found] == ["control"]


def test_divergence_does_not_silently_skip_an_illegal_identifier(store: Store) -> None:
    """A foreign write must not pass unreported by being malformed as well."""
    store.write_node(node("control.loop", owner_role="control"), "control")
    tampered = [NodeChange(1, "../../elsewhere", 1, "write")]

    with pytest.raises(MalformedNodeIdError):
        divergence(store, tampered, "control")


def test_divergence_validates_the_identifier_itself(store: Store) -> None:
    """Its own check, with a store that will not answer for it.

    The real store's reads validate, so removing this check changes nothing
    while the call order happens to put a validating read first. A stub without
    that behaviour is what makes the check its own.
    """

    class StoreThatValidatesNothing:
        def history(self, node_id: str) -> list[int]:
            return []

        def payload_at(self, revision: int) -> dict[str, Any]:
            return {"owner_role": "electrical"}

    with pytest.raises(MalformedNodeIdError):
        divergence(
            StoreThatValidatesNothing(),  # type: ignore[arg-type]
            [NodeChange(1, "../../elsewhere", 1, "write")],
            "control",
        )
