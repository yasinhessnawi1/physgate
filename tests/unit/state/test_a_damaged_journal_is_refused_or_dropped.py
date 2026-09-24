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
from typing import IO, Any

import pytest
from helpers import node
from pydantic import ValidationError

from physgate.state.divergence import divergence
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import JournalLine, Store

#: A payload that is a whole node, so a case about a revision is refused for the
#: revision rather than for the payload that was standing in as a placeholder.
NODE_AB = node("a.b")


def append_raw(root: Path, line: dict[str, Any]) -> None:
    """Write a journal line the way something bypassing the store would."""
    with (root / "journal.jsonl").open("ab") as handle:
        handle.write(json.dumps(line).encode() + b"\n")


def legal_line(
    rev: int,
    node_id: str = "electrical.motor",
    version: int = 1,
    *,
    op: str = "write",
    payload_id: str | None = None,
) -> dict[str, Any]:
    """A journal line, with every field the record relates independently settable.

    ``payload_id`` defaults to ``node_id`` because that is the coherent case, and
    is a parameter because the incoherent one has to be reachable from here. A
    helper that can only build coherent records cannot test the rule that records
    must be coherent, which is how that rule came to be missing.
    """
    payload = node(node_id if payload_id is None else payload_id)
    return {"rev": rev, "op": op, "node_id": node_id, "version": version, "payload": payload}


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
            {"rev": 0, "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        (
            "a negative revision",
            {"rev": -1, "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        (
            "a boolean revision",
            {"rev": True, "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        (
            "a boolean version",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": True, "payload": NODE_AB},
        ),
        ("a missing revision", {"op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB}),
        ("a missing payload", {"rev": 1, "op": "write", "node_id": "a.b", "version": 1}),
        (
            "a version of zero",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": 0, "payload": NODE_AB},
        ),
        (
            "an unknown operation",
            {"rev": 1, "op": "delete", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        (
            "a payload that is not an object",
            {"rev": 1, "op": "write", "node_id": "a.b", "version": 1, "payload": []},
        ),
        (
            "an unknown field",
            {
                "rev": 1,
                "op": "write",
                "node_id": "a.b",
                "version": 1,
                "payload": NODE_AB,
                "extra": 1,
            },
        ),
        (
            "an illegal identifier",
            {"rev": 1, "op": "write", "node_id": "../../x", "version": 1, "payload": NODE_AB},
        ),
        (
            "a revision written as text",
            {"rev": "1", "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
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
            {"rev": 0, "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        (
            "a boolean revision",
            {"rev": True, "op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB},
        ),
        ("a missing revision", {"op": "write", "node_id": "a.b", "version": 1, "payload": NODE_AB}),
        (
            "an illegal identifier",
            {"rev": 1, "op": "write", "node_id": "../../x", "version": 1, "payload": NODE_AB},
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
    append_raw(one_node, legal_line(2, version=1, op="create"))
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
    append_raw(one_node, legal_line(2, version=1, op="create"))

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
    append_raw(one_node, legal_line(2, version=1, op="create"))
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


# --- the record's shape is the model's own contract ---------------------------
#
# The consecutiveness rule subsumes several of these when a line is read back
# through recovery -- a revision of zero is refused for not following zero before
# it is refused for not being positive. The model is exported and can be built
# directly, so its own constraints are tested directly, or a mutation of one is
# answered by the other and neither is ever really tested.


@pytest.mark.parametrize(
    ("label", "field", "value"),
    [
        ("a revision of zero", "rev", 0),
        ("a negative revision", "rev", -1),
        ("a revision that is a boolean", "rev", True),
        ("a version of zero", "version", 0),
        ("a version that is a boolean", "version", True),
    ],
)
def test_the_record_refuses_it_on_its_own(label: str, field: str, value: object) -> None:
    fields: dict[str, Any] = {
        "rev": 1,
        "op": "write",
        "node_id": "electrical.motor",
        "version": 1,
        "payload": node("electrical.motor"),
    }
    fields[field] = value
    with pytest.raises(ValidationError):
        JournalLine.model_validate(fields)


def test_a_well_formed_record_validates() -> None:
    line = JournalLine.model_validate(
        {
            "rev": 1,
            "op": "create",
            "node_id": "electrical.motor",
            "version": 1,
            "payload": node("electrical.motor"),
        }
    )
    assert line.rev == 1
    assert line.op == "create"


def test_a_record_is_frozen() -> None:
    line = JournalLine.model_validate(
        {
            "rev": 1,
            "op": "create",
            "node_id": "electrical.motor",
            "version": 1,
            "payload": node("electrical.motor"),
        }
    )
    with pytest.raises(ValidationError):
        line.rev = 2


# --- the offsets survive a truncation ----------------------------------------


def test_the_change_list_still_seeks_correctly_after_a_torn_tail_was_dropped(
    one_node: Path,
) -> None:
    """Recovery truncates through a second handle, which leaves the writing one stale.

    The change list seeks to a recorded byte offset, so a stale one sends it into
    the middle of a line. Asking for everything since revision one is what reads
    that offset; asking for everything since the beginning reads from zero and
    would not notice.
    """
    with (one_node / "journal.jsonl").open("ab") as handle:
        handle.write(b'{"rev":2,"op":"wri')

    store = Store(one_node)
    assert store.write_node(node("electrical.motor"), "electrical").revision == 2

    journal = (one_node / "journal.jsonl").read_bytes()
    second_line_starts_at = journal.index(b"\n") + 1
    assert store._offsets[2] == second_line_starts_at, "the recorded offset is stale"  # noqa: SLF001

    assert [(c.revision, c.node_id) for c in store.diff(1)] == [(2, "electrical.motor")]
    store.close()


# --- a refused open leaves nothing behind -------------------------------------


def test_a_refused_open_closes_the_handle_it_opened(one_node: Path) -> None:
    """Bound before recovery so the error is the real one; closed so it does not leak."""
    append_raw(one_node, legal_line(9))

    opened: list[IO[bytes]] = []
    real_open = Path.open

    def note(self: Path, *args: Any, **kwargs: Any) -> Any:
        handle = real_open(self, *args, **kwargs)
        mode = str(args[0] if args else kwargs.get("mode", ""))
        if self.name == "journal.jsonl" and "a" in mode:
            opened.append(handle)
        return handle

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "open", note)
        with pytest.raises(CorruptRecordError):
            Store(one_node)

    assert opened, "the appending handle was never opened"
    assert all(handle.closed for handle in opened), "a refused open leaked a handle"


# --- a record must be one the writing code could have produced ----------------
#
# Every check below follows from that one sentence. The record's own fields have
# to agree with each other; the record has to agree with the records before it.
# The first round of this model closed each scalar field and left the payload
# opaque and the fields unrelated, which left four ways through.


def version_chain(root: Path, node_id: str) -> list[int]:
    """Every version recorded for a node, in journal order, read off the disk."""
    chain = []
    for raw in (root / "journal.jsonl").read_bytes().splitlines():
        if not raw:
            continue
        entry = json.loads(raw)
        if entry["node_id"] == node_id:
            chain.append(entry["version"])
    return chain


def assert_chain_is_intact(root: Path, node_id: str) -> None:
    """Versions 1..k, no gaps, no duplicates — part four of the definition.

    Asserted here as well as after the process-kill run, because a killed writer
    cannot produce a broken chain: it only ever stops. The cases that can produce
    one are injections, and until now nothing asserted it over those.
    """
    chain = version_chain(root, node_id)
    assert chain == list(range(1, len(chain) + 1)), chain


def test_a_record_whose_payload_names_a_different_node_is_refused(one_node: Path) -> None:
    """The file's name and its contents would otherwise disagree.

    Through the writing path they cannot: the record's identifier is taken from
    the payload. A record where they differ is a record this package did not
    write, and nothing downstream reads it expecting to have to check.
    """
    append_raw(one_node, legal_line(2, payload_id="electrical.elsewhere"))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "names the node it carries" in caught.value.context["reason"]


def test_a_payload_that_is_not_a_node_is_refused(one_node: Path) -> None:
    """The divergence check died on one of these with a bare key error."""
    line = legal_line(2, "electrical.motor", version=1, op="create")
    line["payload"] = {"anything": "goes"}
    append_raw(one_node, line)

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "payload" in caught.value.context["reason"]


def test_a_create_for_a_node_already_created_is_refused(one_node: Path) -> None:
    append_raw(one_node, legal_line(2, "control.loop", version=1, op="create"))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "already created" in caught.value.context["reason"]


def test_a_create_at_a_version_other_than_one_is_refused(one_node: Path) -> None:
    append_raw(one_node, legal_line(2, "electrical.motor", version=4, op="create"))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "version 1" in caught.value.context["reason"]


def test_a_write_for_a_node_that_was_never_created_is_refused(one_node: Path) -> None:
    """Otherwise a node is conjured from nothing at whatever version it claims."""
    append_raw(one_node, legal_line(2, "electrical.never", version=7))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "never created" in caught.value.context["reason"]


def test_a_version_that_skips_is_refused(one_node: Path) -> None:
    append_raw(one_node, legal_line(2, "control.loop", version=4))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "does not follow" in caught.value.context["reason"]


def test_the_store_does_not_manufacture_a_duplicate_after_an_injection(
    tmp_path: Path,
) -> None:
    """The worst of the four, because the store did the damage itself.

    A node at version five, one injected record claiming to create it at version
    one, and then the store's **own next legitimate write** continuing from the
    rewound counter. The chain on disk was ``[1, 2, 3, 4, 5, 1, 2]`` — the
    duplicate produced by the writing path, from a counter an injection had
    moved.
    """
    root = tmp_path / "graph"
    store = Store(root)
    for i in range(5):
        assert store.write_node(
            node("mechanical.a0", owner_role="mechanical", updated=f"t{i}"), "mechanical"
        ).accepted
    store.close()
    assert version_chain(root, "mechanical.a0") == [1, 2, 3, 4, 5]

    append_raw(root, legal_line(6, "mechanical.a0", version=1, op="create"))

    with pytest.raises(CorruptRecordError):
        Store(root)

    recovered = Store(root, on_corrupt="truncate")
    assert recovered.write_node(
        node("mechanical.a0", owner_role="mechanical", updated="after"), "mechanical"
    ).accepted
    recovered.close()

    assert_chain_is_intact(root, "mechanical.a0")
    assert version_chain(root, "mechanical.a0") == [1, 2, 3, 4, 5, 6]


def test_a_legitimate_foreign_write_still_passes_every_coherence_rule(
    one_node: Path,
) -> None:
    """The rules refuse records this package could not have written, and no others.

    A foreign write that a role could genuinely have made is coherent: it creates
    a node nobody has created, at version one, with a payload that is that node.
    It stays in the record and the divergence check names it.
    """
    append_raw(one_node, legal_line(2, "electrical.motor", version=1, op="create"))

    store = Store(one_node)
    assert store.head_revision() == 2
    assert [d.node_id for d in divergence(store, store.diff(0), "control")] == ["electrical.motor"]
    assert_chain_is_intact(one_node, "electrical.motor")
    store.close()


# --- the payload is a whole node, and this is the test that says only that ----
#
# Every other test of this rule reaches it through a payload whose identifier
# also disagrees with the record's, so the coherence half answers for both and a
# stub in place of the node validation leaves the suite green. These payloads
# carry the right identifier and are still not nodes, so only the node validation
# can refuse them.


def wrongly_shaped(label: str) -> dict[str, Any]:
    """A payload named correctly and shaped incorrectly."""
    payload = node("electrical.motor")
    if label == "missing kind":
        del payload["kind"]
    elif label == "an extra field":
        payload["surprise"] = 1
    elif label == "an unknown domain":
        payload["domain"] = "banana"
    elif label == "a bare-number quantity":
        payload["quantities"] = {"stall_current": 2.4}
    else:  # pragma: no cover - a label with no case is a broken test
        raise AssertionError(label)
    return payload


BADLY_SHAPED = ["missing kind", "an extra field", "an unknown domain", "a bare-number quantity"]


@pytest.mark.parametrize("label", BADLY_SHAPED)
def test_a_correctly_named_payload_that_is_not_a_node_is_refused_on_replay(
    label: str, one_node: Path
) -> None:
    line = legal_line(2, "electrical.motor", version=1, op="create")
    line["payload"] = wrongly_shaped(label)
    assert line["payload"]["id"] == line["node_id"], "the name must be right, or this tests nothing"
    append_raw(one_node, line)

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "payload" in caught.value.context["reason"], label


@pytest.mark.parametrize("label", BADLY_SHAPED)
def test_a_correctly_named_payload_that_is_not_a_node_is_refused_on_write(
    label: str, store: Store
) -> None:
    """The same four, through the door they would normally arrive by."""
    payload = wrongly_shaped(label)
    try:
        result = store.write_node(payload, "electrical")
    except Exception:  # noqa: BLE001 - either refusal is a refusal
        pass
    else:
        assert not result.accepted, label
    assert store.head_revision() == 0, label


# --- rollback is held to the version rule, and to one more -------------------


def test_a_rollback_that_skips_a_version_is_refused(one_node: Path) -> None:
    """The version rule was tested for writes only."""
    append_raw(one_node, legal_line(2, "control.loop", version=4, op="rollback"))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "does not follow" in caught.value.context["reason"]


def test_a_rollback_for_a_node_that_was_never_created_is_refused(one_node: Path) -> None:
    append_raw(one_node, legal_line(2, "electrical.never", version=1, op="rollback"))

    with pytest.raises(CorruptRecordError) as caught:
        Store(one_node)
    assert "never created" in caught.value.context["reason"]


def test_a_rollback_to_a_payload_this_node_never_held_is_refused(tmp_path: Path) -> None:
    """The constraint the writing path imposes and the replay path did not check.

    ``rollback`` only ever appends a payload it has just read out of an earlier
    revision of that same node. A record carrying an invented payload is
    therefore one this package could not have written, however well-formed.
    """
    root = tmp_path / "graph"
    store = Store(root)
    for i in range(2):
        store.write_node(node("control.loop", owner_role="control", updated=f"t{i}"), "control")
    store.close()

    invented = node("control.loop", owner_role="control")
    invented["geometry_hash"] = "sha256:" + "n" * 64
    line = legal_line(3, "control.loop", version=3, op="rollback")
    line["payload"] = invented
    append_raw(root, line)

    with pytest.raises(CorruptRecordError) as caught:
        Store(root)
    assert "never any of its revisions" in caught.value.context["reason"]


def test_a_rollback_to_a_payload_the_node_did_hold_is_accepted(tmp_path: Path) -> None:
    """The rule refuses invented payloads and no others."""
    root = tmp_path / "graph"
    store = Store(root)
    store.write_node(node("control.loop", owner_role="control", updated="first"), "control")
    first = dict(store.read_node("control.loop"))
    store.write_node(node("control.loop", owner_role="control", updated="second"), "control")
    store.close()

    line = legal_line(3, "control.loop", version=3, op="rollback")
    line["payload"] = first
    append_raw(root, line)

    reopened = Store(root)
    assert reopened.head_revision() == 3
    assert reopened.read_node("control.loop")["updated"] == "first"
    reopened.close()


def test_a_rollback_written_by_the_store_replays_clean(tmp_path: Path) -> None:
    """Whatever the rule refuses, it must not refuse this package's own output."""
    root = tmp_path / "graph"
    store = Store(root)
    for i in range(3):
        store.write_node(node("control.loop", owner_role="control", updated=f"t{i}"), "control")
    store.rollback("control.loop", store.history("control.loop")[0])
    store.write_node(node("control.loop", owner_role="control", updated="after"), "control")
    store.close()

    reopened = Store(root)
    assert reopened.head_revision() == 5
    assert reopened.history("control.loop") == [1, 2, 3, 4, 5]
    reopened.close()
