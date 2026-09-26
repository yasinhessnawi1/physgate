"""The journal's newest records, read without opening a store and without writing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import node

from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import JOURNAL_NAME, Store, journal_records_after


def _graph(tmp_path: Path, writes: int) -> Path:
    root = tmp_path / "graph"
    store = Store(root)
    for i in range(writes):
        payload = node(updated=f"2026-09-26T10:00:{i:02d}Z")
        assert store.write_node(payload, "electrical").accepted
    store.close()
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_records_after_a_revision_are_returned_in_order(tmp_path: Path) -> None:
    root = _graph(tmp_path, 4)
    assert [line.rev for line in journal_records_after(root, 0)] == [1, 2, 3, 4]
    assert [line.rev for line in journal_records_after(root, 2)] == [3, 4]
    assert journal_records_after(root, 4) == []
    assert journal_records_after(tmp_path / "absent", 0) == []


def test_reading_writes_nothing_and_trusts_no_node_file(tmp_path: Path) -> None:
    root = _graph(tmp_path, 2)
    node_file = next((root / "nodes").iterdir())
    node_file.write_text('{"tampered": true}')
    (root / "nodes" / "stranger.json").write_text("{}")
    before = _snapshot(root)
    records = journal_records_after(root, 0)
    assert _snapshot(root) == before
    assert records[-1].payload["updated"] == "2026-09-26T10:00:01Z"


def test_an_unterminated_final_line_is_a_write_in_progress(tmp_path: Path) -> None:
    root = _graph(tmp_path, 2)
    with (root / JOURNAL_NAME).open("ab") as handle:
        handle.write(b'{"rev": 3, "op": "write"')
    assert [line.rev for line in journal_records_after(root, 0)] == [1, 2]


def _append(root: Path, record: dict[str, object] | bytes) -> None:
    raw = record if isinstance(record, bytes) else json.dumps(record).encode()
    with (root / JOURNAL_NAME).open("ab") as handle:
        handle.write(raw + b"\n")


@pytest.mark.parametrize(
    "record",
    [
        b"not json",
        {
            "rev": 5,
            "op": "write",
            "node_id": "electrical.motor_left",
            "version": 3,
            "payload": node(),
        },
        {
            "rev": 3,
            "op": "create",
            "node_id": "electrical.motor_left",
            "version": 1,
            "payload": node(),
        },
        {
            "rev": 3,
            "op": "write",
            "node_id": "electrical.motor_left",
            "version": 9,
            "payload": node(),
        },
        {
            "rev": 3,
            "op": "write",
            "node_id": "electrical.motor_left",
            "version": 3,
            "payload": node(quantities={"i": {"value": 2.4}}),
        },
        {"rev": 3, "op": "write", "node_id": "electrical.other", "version": 3, "payload": node()},
    ],
    ids=[
        "not json",
        "a gap in revisions",
        "a second create",
        "a version that does not follow",
        "a bare number in the payload",
        "a payload naming another node",
    ],
)
def test_a_line_this_package_could_not_have_written_is_reported_not_skipped(
    tmp_path: Path, record: dict[str, object] | bytes
) -> None:
    root = _graph(tmp_path, 2)
    size = (root / JOURNAL_NAME).stat().st_size
    _append(root, record)
    with pytest.raises(CorruptRecordError) as caught:
        journal_records_after(root, 2)
    assert caught.value.context["offset"] == str(size)


def test_it_sees_what_an_open_handle_just_appended(tmp_path: Path) -> None:
    root = tmp_path / "graph"
    store = Store(root)
    assert store.write_node(node(), "electrical").accepted
    assert [line.rev for line in journal_records_after(root, 0)] == [1]
    assert store.write_node(node(updated="2026-09-26T11:00:00Z"), "electrical").accepted
    assert [line.op for line in journal_records_after(root, 1)] == ["write"]
    store.close()
