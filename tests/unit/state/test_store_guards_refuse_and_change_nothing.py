"""A refused write mints no revision and leaves the node exactly as it was.

The three guards are the correctness the store comparison scored, and the thing
it scored beyond acceptance and refusal was that a refused write changed nothing.
Every refusal here is checked by reading the node back and comparing bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import node

from physgate.state.exceptions import (
    MalformedNodeIdError,
    MissingUnitError,
    StoreStaleError,
)
from physgate.state.protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
    canonical_json,
)
from physgate.state.store import RevisionNotFoundError, Store


def snapshot(store: Store, node_id: str) -> tuple[str, int, list[int]]:
    """Everything a refused write must leave untouched."""
    return (
        canonical_json(store.read_node(node_id)),
        store.head_revision(),
        store.history(node_id),
    )


# --- the owning role ---------------------------------------------------------


def test_a_role_cannot_create_a_node_it_does_not_own(store: Store) -> None:
    result = store.write_node(node(owner_role="electrical"), "control")
    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE
    assert result.revision is None
    assert store.head_revision() == 0


def test_a_role_cannot_update_a_node_it_does_not_own(store: Store) -> None:
    store.write_node(node(), "electrical")
    before = snapshot(store, "electrical.motor_left")

    result = store.write_node(node(updated="2026-09-22T00:00:00Z"), "control")

    assert result.accepted is False
    assert result.reason == REJECT_CROSS_ROLE
    assert result.revision is None
    assert snapshot(store, "electrical.motor_left") == before


def test_the_owning_role_can_update_its_own_node(store: Store) -> None:
    store.write_node(node(), "electrical")
    result = store.write_node(node(updated="2026-09-22T00:00:00Z"), "electrical")
    assert result.accepted is True
    assert result.revision == 2


# --- interface immutability --------------------------------------------------


def test_an_interface_node_cannot_be_written_after_it_is_created(store: Store) -> None:
    """Immutable from creation. The orchestrator writes each one exactly once."""
    interface = node("iface.control.07", kind="interface", owner_role="orchestrator")
    assert store.write_node(interface, "orchestrator").accepted is True
    before = snapshot(store, "iface.control.07")

    result = store.write_node(
        node(
            "iface.control.07",
            kind="interface",
            owner_role="orchestrator",
            updated="2026-09-22T00:00:00Z",
        ),
        "orchestrator",
    )

    assert result.accepted is False
    assert result.reason == REJECT_INTERFACE_IMMUTABLE
    assert snapshot(store, "iface.control.07") == before


def test_creating_an_interface_node_is_allowed(store: Store) -> None:
    interface = node("iface.control.07", kind="interface", owner_role="orchestrator")
    assert store.write_node(interface, "orchestrator").accepted is True


# --- quantities --------------------------------------------------------------


def test_a_quantity_with_no_unit_is_refused(store: Store) -> None:
    store.write_node(node(), "electrical")
    before = snapshot(store, "electrical.motor_left")

    bare = node(
        quantities={"stall_current": {"value": 2.4, "source": "datasheet", "written_by": "sizing"}}
    )
    result = store.write_node(bare, "electrical")

    assert result.accepted is False
    assert result.reason == REJECT_MISSING_UNIT
    assert snapshot(store, "electrical.motor_left") == before


def test_a_bare_number_is_refused_on_create(store: Store) -> None:
    result = store.write_node(node(quantities={"stall_current": 2.4}), "electrical")
    assert result.reason == REJECT_MISSING_UNIT
    assert store.head_revision() == 0


# --- the order the guards run in ---------------------------------------------


def test_a_write_carrying_two_faults_is_refused_for_the_first_of_them(store: Store) -> None:
    """Guard order is semantics.

    The rejection reasons are the vocabulary the frozen correctness score is
    counted in. A write that is both cross-role and unit-less must be refused as
    cross-role, or those counters stop being comparable with the ones the store
    comparison published.
    """
    store.write_node(node(), "electrical")
    both = node(quantities={"stall_current": {"value": 2.4, "source": "d", "written_by": "s"}})
    result = store.write_node(both, "control")
    assert result.reason == REJECT_CROSS_ROLE


def test_an_interface_write_that_is_also_unit_less_is_refused_as_interface(
    store: Store,
) -> None:
    interface = node("iface.control.07", kind="interface", owner_role="orchestrator")
    store.write_node(interface, "orchestrator")
    both = node(
        "iface.control.07",
        kind="interface",
        owner_role="orchestrator",
        quantities={"x": {"value": 1.0, "source": "d", "written_by": "s"}},
    )
    assert store.write_node(both, "orchestrator").reason == REJECT_INTERFACE_IMMUTABLE


# --- a malformed id raises rather than joining the rejection vocabulary -------


def test_a_malformed_node_id_raises_and_writes_nothing(store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.write_node(node("../../secrets"), "electrical")
    assert store.head_revision() == 0
    assert list(store.nodes_dir.iterdir()) == []


def test_the_identifier_is_checked_before_any_guard_runs(store: Store) -> None:
    """Order matters here too.

    A malformed id is not a policy decision, so it raises rather than becoming a
    rejection reason. That has to hold even when the write would also have been
    refused for a reason that *is* in the vocabulary, or the id check is not
    first and a bad id can be answered with a rejection instead.
    """
    with pytest.raises(MalformedNodeIdError):
        store.write_node(node("../../secrets", owner_role="electrical"), "control")
    with pytest.raises(MalformedNodeIdError):
        store.write_node(node("../../secrets", quantities={"x": 2.4}), "electrical")
    assert store.head_revision() == 0


def test_the_escape_attempt_wrote_no_file_outside_the_graph(tmp_path: Path) -> None:
    store = Store(tmp_path / "graph")
    outside = tmp_path / "secrets.json"
    with pytest.raises(MalformedNodeIdError):
        store.write_node(node("../secrets"), "electrical")
    assert not outside.exists()
    assert not (tmp_path / "graph" / ".." / "secrets.json").resolve().exists()
    store.close()


# --- rollback ----------------------------------------------------------------


def test_rollback_appends_a_new_head_and_deletes_nothing(store: Store) -> None:
    store.write_node(node(updated="a"), "electrical")
    store.write_node(node(updated="b"), "electrical")
    store.write_node(node(updated="c"), "electrical")
    assert store.history("electrical.motor_left") == [1, 2, 3]

    store.rollback("electrical.motor_left", 1)

    assert store.history("electrical.motor_left") == [1, 2, 3, 4]
    assert store.read_node("electrical.motor_left")["updated"] == "a"
    assert store.head_revision() == 4


def test_rollback_to_a_revision_of_another_node_raises(store: Store) -> None:
    store.write_node(node("electrical.motor_left"), "electrical")
    store.write_node(node("control.loop", owner_role="control"), "control")
    with pytest.raises(RevisionNotFoundError) as caught:
        store.rollback("control.loop", 1)
    assert caught.value.context["belongs_to"] == "electrical.motor_left"


def test_rollback_to_a_revision_that_does_not_exist_raises(store: Store) -> None:
    store.write_node(node(), "electrical")
    with pytest.raises(RevisionNotFoundError):
        store.rollback("electrical.motor_left", 99)


# --- the change list and the traversal ---------------------------------------


def test_the_change_list_names_every_accepted_mutation(store: Store) -> None:
    store.write_node(node("electrical.a"), "electrical")
    store.write_node(node("electrical.b"), "electrical")
    store.write_node(node("electrical.a", updated="later"), "electrical")

    changes = store.diff(0)

    assert [(c.revision, c.node_id, c.op) for c in changes] == [
        (1, "electrical.a", "create"),
        (2, "electrical.b", "create"),
        (3, "electrical.a", "write"),
    ]


def test_a_refused_write_appears_in_no_change_list(store: Store) -> None:
    store.write_node(node(), "electrical")
    cursor = store.head_revision()
    store.write_node(node(updated="x"), "control")
    assert store.diff(cursor) == []


def test_traversal_follows_the_constrains_edges_breadth_first(store: Store) -> None:
    store.write_node(
        node("electrical.a", constrains=["electrical.b", "electrical.c"]), "electrical"
    )
    store.write_node(node("electrical.b", constrains=["electrical.d"]), "electrical")
    store.write_node(node("electrical.c", constrains=[]), "electrical")
    store.write_node(node("electrical.d", constrains=[]), "electrical")

    assert store.traverse_constrains("electrical.a") == [
        "electrical.b",
        "electrical.c",
        "electrical.d",
    ]


def test_traversal_terminates_on_a_cycle(store: Store) -> None:
    store.write_node(node("electrical.a", constrains=["electrical.b"]), "electrical")
    store.write_node(node("electrical.b", constrains=["electrical.a"]), "electrical")
    assert store.traverse_constrains("electrical.a") == ["electrical.b"]


def test_traversal_skips_an_edge_to_a_node_that_does_not_exist(store: Store) -> None:
    store.write_node(node("electrical.a", constrains=["electrical.ghost"]), "electrical")
    assert store.traverse_constrains("electrical.a") == []


# --- the staleness guard -----------------------------------------------------


def test_a_handle_refuses_every_read_once_another_handle_has_written(
    tmp_path: Path,
) -> None:
    """The store cannot answer inconsistently, so it declines to answer at all."""
    root = tmp_path / "graph"
    first = Store(root)
    first.write_node(node(), "electrical")

    watcher = Store(root)
    first.write_node(node(updated="later"), "electrical")

    for call in (
        lambda: watcher.head_revision(),
        lambda: watcher.history("electrical.motor_left"),
        lambda: watcher.diff(0),
        lambda: watcher.read_node("electrical.motor_left"),
        lambda: watcher.traverse_constrains("electrical.motor_left"),
    ):
        with pytest.raises(StoreStaleError):
            call()

    first.close()
    watcher.close()


def test_a_stale_handle_refuses_to_write_rather_than_minting_a_taken_revision(
    tmp_path: Path,
) -> None:
    """The silent corruption this guard exists for.

    Without it both handles mint the same revision number, the journal carries
    two lines at that revision, and one of the two nodes never appears in a
    change list again — so the divergence check can never name it.
    """
    root = tmp_path / "graph"
    first = Store(root)
    second = Store(root)

    assert first.write_node(node("electrical.a"), "electrical").revision == 1
    with pytest.raises(StoreStaleError):
        second.write_node(node("electrical.b"), "electrical")

    first.close()
    second.close()

    fresh = Store(root)
    assert fresh.head_revision() == 1
    assert [c.node_id for c in fresh.diff(0)] == ["electrical.a"]
    journal = (root / "journal.jsonl").read_bytes().splitlines()
    assert len(journal) == 1, "exactly one line was minted"
    fresh.close()


def test_a_handle_that_does_all_the_writing_itself_never_refuses(store: Store) -> None:
    for i in range(20):
        assert store.write_node(node("electrical.a", updated=f"t{i}"), "electrical").accepted
    assert store.head_revision() == 20


def test_closing_a_stale_handle_still_works(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    first, second = Store(root), Store(root)
    first.write_node(node(), "electrical")
    second.close()
    first.close()


def test_the_staleness_error_says_what_moved(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    first, second = Store(root), Store(root)
    first.write_node(node(), "electrical")
    with pytest.raises(StoreStaleError) as caught:
        second.head_revision()
    context = caught.value.context
    assert int(context["size_now"]) > int(context["size_at_last_sync"])
    first.close()
    second.close()


# --- the journal's torn tail -------------------------------------------------


def test_a_torn_journal_tail_is_dropped_and_reported(tmp_path: Path) -> None:
    """The deterministic half of the crash story, for the graph's own journal.

    A journal line is a few hundred bytes against an eight-kilobyte buffer, so a
    signal cannot split one: the window this code exists for is too narrow to hit
    on purpose. It is reproduced directly instead.
    """
    root = tmp_path / "graph"
    first = Store(root)
    first.write_node(node("electrical.a"), "electrical")
    first.write_node(node("electrical.b"), "electrical")
    first.close()

    journal = root / "journal.jsonl"
    intact = journal.read_bytes()
    journal.write_bytes(intact + b'{"rev":3,"op":"write","node_id":"electri')

    reopened = Store(root)

    assert reopened.head_revision() == 2
    assert reopened.torn_tail_bytes == 40
    assert journal.read_bytes() == intact
    assert [c.revision for c in reopened.diff(0)] == [1, 2]
    reopened.close()


def test_a_write_after_a_torn_tail_was_dropped_continues_from_the_right_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "graph"
    first = Store(root)
    first.write_node(node("electrical.a"), "electrical")
    first.close()
    (root / "journal.jsonl").write_bytes(
        (root / "journal.jsonl").read_bytes() + b'{"rev":2,"op":"cre'
    )

    reopened = Store(root)
    assert reopened.write_node(node("electrical.b"), "electrical").revision == 2
    assert [c.revision for c in reopened.diff(0)] == [1, 2]
    reopened.close()


def test_an_intact_journal_reports_no_torn_tail(store: Store) -> None:
    store.write_node(node(), "electrical")
    assert store.torn_tail_bytes == 0


# --- the schema is enforced on the way in and on the way out ------------------
#
# Validation runs on both paths by decision. Neither path had a detector, which
# made the decision a sentence: with the write-path call gone, a node with an
# unknown kind was accepted, journalled and materialised, and only failed later
# on read-back -- a corrupt node in the durable record.


def test_a_structurally_invalid_node_is_refused_on_the_write_path(store: Store) -> None:
    """Quantity-valid, node-invalid: only the write-path validation catches it."""
    broken = node()
    broken["kind"] = "banana"
    with pytest.raises(Exception, match="kind"):
        store.write_node(broken, "electrical")
    assert store.head_revision() == 0


def test_a_node_missing_a_mandatory_field_is_refused_on_the_write_path(
    store: Store,
) -> None:
    broken = node()
    del broken["geometry_hash"]
    with pytest.raises(Exception, match="geometry_hash"):
        store.write_node(broken, "electrical")
    assert store.head_revision() == 0


def test_an_unknown_domain_is_refused(store: Store) -> None:
    """The architecture enumerates the domain as it enumerates the kind."""
    broken = node()
    broken["domain"] = "banana"
    with pytest.raises(Exception, match="domain"):
        store.write_node(broken, "electrical")


def test_a_node_file_corrupted_in_a_non_quantity_field_is_refused_on_read(
    tmp_path: Path,
) -> None:
    """The read path's own validation, with nothing else able to catch it."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("electrical.motor_left"), "electrical")

    path = root / "nodes" / "electrical.motor_left.json"
    on_disk = json.loads(path.read_text())
    on_disk["payload"]["kind"] = "banana"
    path.write_text(json.dumps(on_disk))

    with pytest.raises(Exception, match="kind"):
        store.read_node("electrical.motor_left")
    store.close()


def test_a_node_file_corrupted_in_a_quantity_is_refused_on_read(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("electrical.motor_left"), "electrical")

    path = root / "nodes" / "electrical.motor_left.json"
    on_disk = json.loads(path.read_text())
    on_disk["payload"]["quantities"]["stall_current"] = 2.4
    path.write_text(json.dumps(on_disk))

    with pytest.raises(MissingUnitError):
        store.read_node("electrical.motor_left")
    store.close()
