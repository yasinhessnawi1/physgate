"""Regression tests for the defects an independent review found.

Each one failed before the fix and passes after it. They are together in one file
because what they have in common is how they were found: by walking the paths
nobody had written a test for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import node

from physgate.state.divergence import divergence
from physgate.state.exceptions import CorruptRecordError, MalformedNodeIdError, MissingUnitError
from physgate.state.protocol import NodeChange
from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger, TaskLine


def journal_line(node_id: str, payload: dict[str, Any], rev: int = 1) -> bytes:
    return (
        json.dumps(
            {"rev": rev, "op": "create", "node_id": node_id, "version": 1, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


# --- the identifier rule holds on every path, not only on the write path -----


@pytest.mark.parametrize("bad", ["../../secrets", "/etc/hosts", "a/b", "..", "NoDots"])
def test_a_read_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.read_node(bad)


@pytest.mark.parametrize("bad", ["../../secrets", "/etc/hosts", "a/b"])
def test_a_traversal_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.traverse_constrains(bad)


@pytest.mark.parametrize("bad", ["../../secrets", "/etc/hosts"])
def test_a_history_lookup_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    with pytest.raises(MalformedNodeIdError):
        store.history(bad)


def test_a_read_of_a_planted_file_outside_the_graph_is_refused(tmp_path: Path) -> None:
    """The escape is only interesting if the target exists; plant one."""
    root = tmp_path / "graph"
    store = Store(root)
    outside = tmp_path / "planted.json"
    outside.write_text(json.dumps({"payload": {"id": "planted"}}))

    with pytest.raises(MalformedNodeIdError):
        store.read_node("../planted")

    store.close()


def test_recovery_refuses_a_journal_naming_a_path_outside_the_graph(
    tmp_path: Path,
) -> None:
    """The defect as it was reported: the write happened on open, from the record."""
    root = tmp_path / "graph"
    Store(root).close()
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    victim = victim_dir / "config.json"
    victim.write_text('{"do not":"clobber me"}')

    escaping = node("electrical.motor_left")
    escaping["id"] = "../../victim/config"
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(journal_line("../../victim/config", escaping))

    with pytest.raises(CorruptRecordError) as caught:
        Store(root)

    assert "illegal node id" in caught.value.context["reason"]
    assert victim.read_text() == '{"do not":"clobber me"}', "the file outside was written"


def test_the_way_through_is_explicit_and_reports_what_it_dropped(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    first = Store(root)
    first.write_node(node("electrical.a"), "electrical")
    first.close()

    escaping = node("electrical.motor_left")
    escaping["id"] = "../../victim/config"
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(journal_line("../../victim/config", escaping, rev=2))

    with pytest.raises(CorruptRecordError):
        Store(root)

    opened = Store(root, on_corrupt="truncate")
    assert opened.torn_tail_bytes > 0
    assert opened.head_revision() == 1
    assert [c.node_id for c in opened.diff(0)] == ["electrical.a"]
    opened.close()


def test_a_complete_but_unparseable_journal_line_is_not_treated_as_a_tail(
    tmp_path: Path,
) -> None:
    """Silently truncating would discard every valid record after it too."""
    root = tmp_path / "graph"
    first = Store(root)
    first.write_node(node("electrical.a"), "electrical")
    first.close()
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(b"{ this is complete and is not json }\n")

    with pytest.raises(CorruptRecordError) as caught:
        Store(root)
    assert "not valid JSON" in caught.value.context["reason"]


def test_divergence_does_not_silently_skip_an_illegal_identifier(tmp_path: Path) -> None:
    """A foreign write with an escaping id must not pass unreported."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("control.loop", owner_role="control"), "control")
    changes = store.diff(0)
    store.close()

    tampered = [type(changes[0])(changes[0].revision, "../../elsewhere", 1, "write")]
    reopened = Store(root)
    with pytest.raises(MalformedNodeIdError):
        divergence(reopened, tampered, "control")
    reopened.close()


# --- validation runs on both paths, and both are detected --------------------


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


# --- divergence judges by the owner at the change, not the owner now ---------


def test_a_legitimate_handover_is_not_reported_as_divergent(store: Store) -> None:
    """The false positive the as-of-now reading produced.

    A role creates its own node and, in the same step, hands ownership on. Read
    as of now, both of its own changes look like writes to someone else's node.
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
    """Reading as-of-the-change must not become a way to hide a later foreign write."""
    store.write_node(node("control.loop", owner_role="control"), "control")
    cursor = store.head_revision()
    store.write_node(node("control.loop", owner_role="control", updated="t1"), "control")

    found = divergence(store, store.diff(cursor), "electrical")
    assert [d.owner_role for d in found] == ["control"]


# --- the ledger ---------------------------------------------------------------


def test_a_corrupt_ledger_line_does_not_make_the_ledger_unopenable_for_ever(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    first = TaskLedger(path)
    first.append(TaskLine(id="t-000", spec_path="s", assigned_role="control", attempt_count=1))
    first.close()
    with path.open("ab") as handle:
        handle.write(b'{"id":"t-001","attempt_count":"not a number"}\n')

    with pytest.raises(CorruptRecordError) as caught:
        TaskLedger(path)
    assert caught.value.context["offset"]

    through = TaskLedger(path, on_corrupt="truncate")
    assert [entry.id for entry in through.read_all()] == ["t-000"]
    assert through.torn_tail_bytes > 0
    through.close()

    assert len(TaskLedger(path)) == 1, "the way through left a record that opens"


def test_find_returns_the_most_recent_line_for_an_id(tmp_path: Path) -> None:
    """The documented behaviour, which first-wins would also have satisfied."""
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    ledger.append(TaskLine(id="t-000", spec_path="s", assigned_role="control", attempt_count=1))
    ledger.append(TaskLine(id="t-000", spec_path="s", assigned_role="control", attempt_count=2))
    found = ledger.find("t-000")
    assert found is not None
    assert found.attempt_count == 2, "find returned the first line, not the most recent"
    ledger.close()


# --- each enforcement point is tested where it sits ---------------------------
#
# The identifier rule is enforced at more than one place on purpose: at each
# public entry point, at the single function that builds a node path, and again
# as a containment check on the path that function produces. Weakening any one
# of them alone leaves the others doing the work, so a mutation of one is green
# unless that one has a test of its own. These are those tests.


@pytest.mark.parametrize("bad", ["NoDots", "Electrical.Motor", "has space.x", ""])
def test_the_path_builder_refuses_an_illegal_identifier(bad: str, store: Store) -> None:
    """The chokepoint's pattern rule, with the containment check out of the way.

    These identifiers are illegal but do not escape the graph directory, so the
    containment check would let every one of them through. That is the point of
    choosing them: the pattern rule is the only thing standing here, which is
    what makes this a test of the pattern rule.
    """
    with pytest.raises(MalformedNodeIdError, match="dotted identifier|not a string"):
        store._node_path(bad)  # noqa: SLF001 - the chokepoint is the subject


def test_the_path_builder_refuses_a_path_that_escapes_the_graph_directory(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The containment check, with the pattern rule out of the way.

    It exists to catch a future loosening of the pattern, so it is tested with
    the pattern neutralised — otherwise the pattern would answer for it and the
    check would be decoration.
    """
    monkeypatch.setattr("physgate.state.store.validate_node_id", lambda node_id: str(node_id))
    with pytest.raises(MalformedNodeIdError, match="outside the graph directory"):
        store._node_path("../escape")  # noqa: SLF001 - the chokepoint is the subject


def test_divergence_validates_the_identifier_itself(store: Store) -> None:
    """Divergence's own check, with a store that does not validate for it.

    The real store's reads validate, so removing this check changes nothing
    while the call order happens to put a validating read first. A stub without
    that behaviour is what makes this check its own.
    """

    class StoreThatValidatesNothing:
        def history(self, node_id: str) -> list[int]:
            return []

        def payload_at(self, revision: int) -> dict[str, Any]:
            return {"owner_role": "electrical"}

    stub = StoreThatValidatesNothing()
    with pytest.raises(MalformedNodeIdError):
        divergence(stub, [NodeChange(1, "../../elsewhere", 1, "write")], "control")  # type: ignore[arg-type]
