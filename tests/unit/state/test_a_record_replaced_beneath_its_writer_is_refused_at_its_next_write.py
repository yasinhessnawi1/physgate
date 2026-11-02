"""A record replaced beneath the writer that holds it is refused at the writer's next write.

The run's append-only records each have one writer. A writer that keeps a handle open would
otherwise go on writing to a file no path names once anything replaced the path, and every line
from then on would be lost without a word. Each writer here is shown the file it holds replaced by
a copy of itself, the same bytes at the same size on a new inode, and must refuse to write rather
than write where no one will read.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from helpers import node

from physgate.orchestrator.events import EventLog, RunStarted, StageEntered, SubtaskPlanned
from physgate.orchestrator.queue import ApprovalQueue
from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger, TaskLine


def _replace_with_a_copy(path: Path) -> None:
    """Put the same bytes at ``path`` on a new inode, as a put-back by replacing does."""
    copy = path.with_name(path.name + ".copy")
    shutil.copy2(path, copy)
    os.replace(copy, path)


def _started(path: Path) -> EventLog:
    log = EventLog(path, run_id="r", gate_mode="on")
    log.emit(RunStarted, config_sha256="d" * 64)
    log.emit(SubtaskPlanned, subtask_id="s1", spec_path="p", assigned_role="r", module_dir="m")
    return log


def _refused(write: object) -> BaseException | None:
    try:
        write()  # type: ignore[operator]
    except Exception as exc:  # noqa: BLE001 - the class is held by the caller
        return exc
    return None


def test_the_event_log_writes_nothing_once_its_file_was_replaced(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = _started(path)
    try:
        _replace_with_a_copy(path)
        held = path.read_bytes()
        raised = _refused(lambda: log.emit(StageEntered, subtask_id="s1", attempt=1, stage="gate"))
        assert raised is not None and type(raised).__name__ == "RecordMovedError", raised
        assert path.read_bytes() == held
    finally:
        log.close()


def test_the_event_log_writes_nothing_once_another_writer_appended(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = _started(path)
    try:
        other = EventLog(path, run_id="r", gate_mode="on")
        other.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
        other.close()
        held = path.read_bytes()
        raised = _refused(lambda: log.emit(StageEntered, subtask_id="s1", attempt=1, stage="gate"))
        assert raised is not None and type(raised).__name__ == "RecordMovedError", raised
        assert path.read_bytes() == held
    finally:
        log.close()


def test_the_task_ledger_writes_nothing_once_its_file_was_replaced(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = TaskLedger(path)
    try:
        ledger.append(
            TaskLine(id="s1", spec_path="s.md", assigned_role="electrical", attempt_count=1)
        )
        _replace_with_a_copy(path)
        held = path.read_bytes()
        line = TaskLine(id="s2", spec_path="s.md", assigned_role="electrical", attempt_count=1)
        raised = _refused(lambda: ledger.append(line))
        assert raised is not None and type(raised).__name__ == "RecordMovedError", raised
        assert path.read_bytes() == held
    finally:
        ledger.close()


def test_the_approval_queue_reads_nothing_of_a_file_replaced_beneath_it(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path / "queue.jsonl")
    _replace_with_a_copy(tmp_path / "queue.jsonl")
    raised = _refused(queue.refresh)
    assert raised is not None and type(raised).__name__ == "RecordMovedError", raised


def test_the_store_refuses_once_its_journal_was_replaced_at_the_same_size(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    try:
        assert store.write_node(node(), "electrical").accepted
        journal = tmp_path / "store" / "journal.jsonl"
        _replace_with_a_copy(journal)
        held = journal.read_bytes()
        raised = _refused(lambda: store.write_node(node("electrical.motor_right"), "electrical"))
        assert raised is not None and type(raised).__name__ == "StoreStaleError", raised
        assert journal.read_bytes() == held
    finally:
        store.close()


@pytest.mark.parametrize("name", ["events.jsonl", "ledger.jsonl"])
def test_a_writer_whose_file_is_untouched_writes_on(tmp_path: Path, name: str) -> None:
    """The guard's other side: nothing moved, nothing refused."""
    path = tmp_path / name
    if name == "events.jsonl":
        log = _started(path)
        log.emit(StageEntered, subtask_id="s1", attempt=1, stage="resolve")
        log.close()
        assert path.read_bytes().count(b"\n") == 3
    else:
        ledger = TaskLedger(path)
        ledger.append(
            TaskLine(id="s1", spec_path="s.md", assigned_role="electrical", attempt_count=1)
        )
        ledger.append(
            TaskLine(id="s2", spec_path="s.md", assigned_role="electrical", attempt_count=1)
        )
        ledger.close()
        assert path.read_bytes().count(b"\n") == 2
