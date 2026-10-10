"""The task ledger can be read without opening its writer, and reading it changes nothing.

Opening ``TaskLedger`` makes the directory, touches the file and truncates a torn tail: right
for the one writer, wrong for a reader, which might cut a line the writer is still completing.
``read_ledger`` reads through the same parser and writes nothing. Each test checks the bytes on
disk afterwards, and the audit-hook recorder sees no write-capable open, because a reader that
merely opened the file for appending would leave the bytes unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ui_rig import RECORDER

from physgate.state.exceptions import CorruptRecordError
from physgate.state.task_ledger import TaskLedger, TaskLine, read_ledger


def _line(task_id: str) -> TaskLine:
    return TaskLine(id=task_id, spec_path="specs/a.md", assigned_role="control", attempt_count=1)


def _ledger(path: Path, *ids: str) -> None:
    writer = TaskLedger(path)
    for task_id in ids:
        writer.append(_line(task_id))
    writer.close()


def test_the_reader_returns_what_the_writer_wrote(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _ledger(path, "t-1", "t-2")
    with RECORDER.recording() as writes:
        lines = read_ledger(path)
    assert [line.id for line in lines] == ["t-1", "t-2"]
    assert writes == []


def test_a_torn_tail_is_left_on_disk_and_not_returned(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _ledger(path, "t-1")
    with path.open("ab") as handle:
        handle.write(b'{"id": "t-2", "spec_pa')
    before = path.read_bytes()
    with RECORDER.recording() as writes:
        lines = read_ledger(path)
    assert [line.id for line in lines] == ["t-1"]
    assert path.read_bytes() == before, "a reader must never cut a line a writer is completing"
    assert writes == []


def test_a_corrupt_complete_line_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    _ledger(path, "t-1")
    with path.open("ab") as handle:
        handle.write(b'{"not": "a task line"}\n')
    before = path.read_bytes()
    with pytest.raises(CorruptRecordError) as caught:
        read_ledger(path)
    assert caught.value.context["offset"] == str(len(before) - len(b'{"not": "a task line"}\n'))
    assert path.read_bytes() == before


def test_a_missing_ledger_is_empty_and_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "never" / "ledger.jsonl"
    with RECORDER.recording() as writes:
        assert read_ledger(path) == []
    assert not path.parent.exists()
    assert writes == []


def test_the_writer_still_truncates_a_torn_tail_at_open(tmp_path: Path) -> None:
    """The parser is shared; only the writer acts on a torn tail, and it still does."""
    path = tmp_path / "ledger.jsonl"
    _ledger(path, "t-1")
    clean = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(b'{"id": "t-2"')
    writer = TaskLedger(path)
    assert writer.torn_tail_bytes == len(b'{"id": "t-2"')
    writer.close()
    assert path.read_bytes() == clean
