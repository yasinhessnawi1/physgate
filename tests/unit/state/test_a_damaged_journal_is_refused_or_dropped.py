"""The journal is replayed at every open, so every line in it is untrusted input.

The store rebuilds itself from this file. For a while only the identifier on each
line was checked and the rest was read raw, which was enough for a line carrying
a revision of zero to rewind the head on the next open: the change list then
reported nothing, and a foreign write sitting on disk became invisible to the
check whose whole purpose is to name it.

Two rules come out of that. A line is a record with a shape, validated like any
other thing crossing a boundary. And revisions are **consecutive**, not merely
increasing — this package mints them one after another and never skips, so a gap
is a line it could not have written, which is what the corruption error means.

Every failure arrives as that error, carrying the byte offset, so the caller who
asks to be let through is let through whatever was wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers import node

from physgate.state.divergence import divergence
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import Store


def append_raw(root: Path, line: dict[str, Any]) -> None:
    """Write a journal line the way something bypassing the store would."""
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(json.dumps(line).encode() + b"\n")


def legal_line(rev: int, node_id: str = "electrical.motor", version: int = 1) -> dict[str, Any]:
    payload = node(node_id)
    return {"rev": rev, "op": "write", "node_id": node_id, "version": version, "payload": payload}


@pytest.fixture
def one_node(tmp_path: Path) -> Path:
    """A graph directory holding one legitimately written node at revision 1."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("control.loop", owner_role="control"), "control")
    store.close()
    return root


# --- the shape of a line -----------------------------------------------------


@pytest.mark.parametrize(
    ("label", "line"),
    [
        (
            "a revision of zero",
            {"rev": 0, "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        (
            "a negative revision",
            {"rev": -1, "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        (
            "a boolean revision",
            {"rev": True, "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        (
            "a boolean version",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": True, "payload": {}},
        ),
        ("a missing revision", {"op": "write", "node_id": "a.b", "version": 1, "payload": {}}),
        ("a missing payload", {"rev": 1, "op": "write", "node_id": "a.b", "version": 1}),
        (
            "a version of zero",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": 0, "payload": {}},
        ),
        (
            "an unknown operation",
            {"rev": 1, "op": "delete", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        (
            "a payload that is not an object",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": 1, "payload": []},
        ),
        (
            "an unknown field",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": 1, "payload": {}, "extra": 1},
        ),
        (
            "an illegal identifier",
            {"rev": 1, "op": "write", "node_id": "../../x", "version": 1, "payload": {}},
        ),
        (
            "a revision written as text",
            {"rev": "1", "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
    ],
)
def test_a_line_that_is_not_a_record_is_refused(
    label: str, line: dict[str, Any], tmp_path: Path
) -> None:
    root = tmp_path / "graph"
    Store(root).close()
    append_raw(root, line)

    with pytest.raises(CorruptRecordError) as caught:
        Store(root)
    assert caught.value.context["offset"] == "0", label


@pytest.mark.parametrize(
    ("label", "line"),
    [
        (
            "a revision of zero",
            {"rev": 0, "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        (
            "a boolean revision",
            {"rev": True, "op": "write", "node_id": "a.b", "version": 1, "payload": {}},
        ),
        ("a missing revision", {"op": "write", "node_id": "a.b", "version": 1, "payload": {}}),
        (
            "an illegal identifier",
            {"rev": 1, "op": "write", "node_id": "../../x", "version": 1, "payload": {}},
        ),
    ],
)
def test_the_way_through_reaches_every_kind_of_damage(
    label: str, line: dict[str, Any], tmp_path: Path
) -> None:
    """A failure that escapes validation escapes the policy with it.

    The missing-revision case used to raise a bare key error from inside the
    loop, before the policy was ever consulted, so the caller who had asked to be
    let through was not let through.
    """
    root = tmp_path / "graph"
    Store(root).close()
    append_raw(root, line)

    opened = Store(root, on_corrupt="truncate")
    assert opened.corrupt_tail_bytes > 0, label
    assert opened.head_revision() == 0
    opened.close()


# --- revisions are consecutive ------------------------------------------------


def test_a_revision_that_rewinds_the_head_is_refused(one_node: Path) -> None:
    """The defect: the last line set the head, so a low revision wound it back."""
    append_raw(one_node, legal_line(2))
    append_raw(one_node, legal_line(0, version=2))

    with pytest.raises(CorruptRecordError):
        Store(one_node)


def test_a_gap_in_the_revisions_is_refused(one_node: Path) -> None:
    """Increasing is not enough; this package never skips one."""
    append_raw(one_node, legal_line(3))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "consecutive" in caught.value.context["reason"]


def test_a_repeated_revision_is_refused(one_node: Path) -> None:
    append_raw(one_node, legal_line(1))

    with pytest.raises(CorruptRecordError):
        Store(one_node)


def test_a_consecutive_foreign_write_is_kept_and_named(one_node: Path) -> None:
    """Refusing a bad line must not become a way to lose a legitimate record.

    A foreign write with a correct revision is a real change to the graph. It
    stays in the record, it appears in the change list, and the divergence check
    names it — which is the whole point of keeping it rather than dropping it.
    """
    append_raw(one_node, legal_line(2))

    store = Store(one_node)
    assert store.head_revision() == 2
    assert [c.node_id for c in store.diff(0)] == ["control.loop", "electrical.motor"]
    assert [d.node_id for d in divergence(store, store.diff(0), "control")] == ["electrical.motor"]
    store.close()


def test_the_foreign_write_is_still_named_after_a_rewind_is_dropped(
    one_node: Path,
) -> None:
    """The reported scenario, end to end.

    The rewinding line is dropped, the foreign write before it is kept, and the
    check names it. Dropping from the corrupt line onwards is what makes that
    true: dropping the whole tail would have taken the foreign write with it and
    hidden the thing being looked for.
    """
    append_raw(one_node, legal_line(2))
    append_raw(one_node, legal_line(0, version=2))

    store = Store(one_node, on_corrupt="truncate")
    assert store.head_revision() == 2
    assert [d.node_id for d in divergence(store, store.diff(0), "control")] == ["electrical.motor"]
    store.close()


# --- a torn tail and a corrupt record are different things --------------------


def test_a_torn_tail_is_counted_as_a_torn_tail(one_node: Path) -> None:
    with (one_node / "journal.jsonl").open("ab") as handle:
        handle.write(b'{"rev":2,"op":"write","node_id":"electri')

    store = Store(one_node)
    assert store.torn_tail_bytes == 40
    assert store.corrupt_tail_bytes == 0
    assert store.head_revision() == 1
    store.close()


def test_a_dropped_corrupt_record_is_counted_as_corruption(one_node: Path) -> None:
    append_raw(one_node, legal_line(9))

    store = Store(one_node, on_corrupt="truncate")
    assert store.corrupt_tail_bytes > 0
    assert store.torn_tail_bytes == 0, "a complete line is not a torn tail"
    store.close()


def test_a_complete_but_unparseable_line_is_not_treated_as_a_tail(one_node: Path) -> None:
    with (one_node / "journal.jsonl").open("ab") as handle:
        handle.write(b"{ this is complete and is not json }\n")

    with pytest.raises(CorruptRecordError):
        Store(one_node)


# --- the handle exists even when the open refuses -----------------------------


def test_a_caller_closing_in_a_finally_block_sees_the_real_error(one_node: Path) -> None:
    """Binding the handle after recovery hid the refusal behind an attribute error."""
    append_raw(one_node, legal_line(9))

    store = None
    with pytest.raises(CorruptRecordError):
        try:
            store = Store(one_node)
        finally:
            if store is not None:
                store.close()


def test_appends_after_a_dropped_tail_land_at_the_right_offset(one_node: Path) -> None:
    """Recovery truncates through another handle, so the writing one is re-seeked."""
    with (one_node / "journal.jsonl").open("ab") as handle:
        handle.write(b'{"rev":2,"op":"wri')

    store = Store(one_node)
    assert store.write_node(node("electrical.motor"), "electrical").revision == 2
    assert [c.revision for c in store.diff(0)] == [1, 2]
    store.close()

    reopened = Store(one_node)
    assert [c.revision for c in reopened.diff(0)] == [1, 2]
    assert reopened.read_node("electrical.motor")["id"] == "electrical.motor"
    reopened.close()
