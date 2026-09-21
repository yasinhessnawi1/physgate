"""The task ledger records one line per dispatched subtask and never rewrites one.

The architecture asks for two things this file proves: the ledger's length equals
the number of dispatched subtasks, and a skipped subtask is visible as a missing
id rather than as an absence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from physgate.state.task_ledger import TaskLedger, TaskLine


def line(task_id: str, **over: Any) -> TaskLine:
    """A complete, legal task line."""
    fields: dict[str, Any] = {
        "id": task_id,
        "spec_path": "specs/control_loop.md",
        "assigned_role": "control",
        "attempt_count": 1,
        "gate_result": "pass",
        "review_result": "pass",
        "merge_commit": "a" * 40,
    }
    fields.update(over)
    return TaskLine(**fields)


@pytest.fixture
def ledger(tmp_path: Path) -> TaskLedger:
    return TaskLedger(tmp_path / "ledger.jsonl")


# --- the shape --------------------------------------------------------------


def test_a_complete_line_validates() -> None:
    assert line("t-001").attempt_count == 1


@pytest.mark.parametrize("missing", ["id", "spec_path", "assigned_role", "attempt_count"])
def test_a_line_missing_a_mandatory_field_is_refused(missing: str) -> None:
    fields: dict[str, Any] = {
        "id": "t-001",
        "spec_path": "specs/control_loop.md",
        "assigned_role": "control",
        "attempt_count": 1,
    }
    del fields[missing]
    with pytest.raises(ValidationError):
        TaskLine.model_validate(fields)


def test_a_line_may_omit_the_results_that_have_not_happened_yet() -> None:
    """A task is written to the ledger when it is dispatched, before it is judged."""
    pending = TaskLine(
        id="t-002",
        spec_path="specs/firmware.md",
        assigned_role="firmware",
        attempt_count=0,
    )
    assert pending.gate_result is None
    assert pending.merge_commit is None


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        line("t-001", surprise=1)


def test_an_unknown_outcome_is_refused() -> None:
    with pytest.raises(ValidationError):
        line("t-001", gate_result="probably")


def test_a_negative_attempt_count_is_refused() -> None:
    with pytest.raises(ValidationError):
        line("t-001", attempt_count=-1)


def test_a_line_is_frozen() -> None:
    written = line("t-001")
    with pytest.raises(ValidationError):
        written.attempt_count = 2


# --- the file ---------------------------------------------------------------


def test_length_equals_the_number_of_appended_lines(ledger: TaskLedger) -> None:
    for i in range(7):
        ledger.append(line(f"t-{i:03d}"))
    assert len(ledger) == 7
    assert len(ledger.read_all()) == 7


def test_read_all_returns_them_in_the_order_they_were_appended(
    ledger: TaskLedger,
) -> None:
    ids = ["t-003", "t-001", "t-002"]
    for task_id in ids:
        ledger.append(line(task_id))
    assert [entry.id for entry in ledger.read_all()] == ids


def test_a_skipped_subtask_is_a_missing_id_not_an_absence(ledger: TaskLedger) -> None:
    for task_id in ("t-001", "t-002", "t-004"):
        ledger.append(line(task_id))
    assert ledger.find("t-003") is None
    assert [entry.id for entry in ledger.read_all()] == ["t-001", "t-002", "t-004"]
    assert ledger.find("t-004") is not None


def test_find_returns_the_line(ledger: TaskLedger) -> None:
    ledger.append(line("t-001", assigned_role="mechanical"))
    found = ledger.find("t-001")
    assert found is not None
    assert found.assigned_role == "mechanical"


def test_tail_returns_the_last_lines_oldest_first(ledger: TaskLedger) -> None:
    for i in range(5):
        ledger.append(line(f"t-{i:03d}"))
    assert [entry.id for entry in ledger.tail(2)] == ["t-003", "t-004"]
    assert ledger.tail(0) == []
    assert len(ledger.tail(99)) == 5


def test_the_ledger_offers_no_way_to_change_or_remove_a_line() -> None:
    """Append-only is structural here, not a promise in a docstring."""
    surface = {name for name in dir(TaskLedger) if not name.startswith("_")}
    assert not surface & {"update", "delete", "remove", "insert", "pop", "clear", "write"}
    assert "append" in surface


# --- reading it back from disk ----------------------------------------------


def test_a_second_ledger_on_the_same_file_reads_every_line(tmp_path: Path) -> None:
    first = TaskLedger(tmp_path / "ledger.jsonl")
    for i in range(4):
        first.append(line(f"t-{i:03d}"))
    first.close()

    second = TaskLedger(tmp_path / "ledger.jsonl")
    assert [entry.id for entry in second.read_all()] == ["t-000", "t-001", "t-002", "t-003"]
    assert second.find("t-002") is not None
    second.close()


def test_an_appended_line_is_on_disk_before_append_returns(tmp_path: Path) -> None:
    """Durability is the point of an append-only ledger, so it is asserted.

    The writer is deliberately not closed. Closing flushes, which would let a
    buffered write pass this test while a killed process lost the line.
    """
    path = tmp_path / "ledger.jsonl"
    writing = TaskLedger(path)
    writing.append(line("t-000"))

    on_disk = path.read_bytes()
    assert on_disk.count(b"\n") == 1, "the line has not reached the file"
    assert b'"t-000"' in on_disk

    reader = TaskLedger(path)
    assert [entry.id for entry in reader.read_all()] == ["t-000"]
    reader.close()
    writing.close()


def test_a_torn_final_line_is_dropped_and_reported(tmp_path: Path) -> None:
    """The deterministic half of the crash story.

    A process killed between writing a line and flushing it leaves a partial
    line. Waiting for a signal to land inside that window is not a test, so the
    window is reproduced directly.
    """
    path = tmp_path / "ledger.jsonl"
    first = TaskLedger(path)
    for i in range(3):
        first.append(line(f"t-{i:03d}"))
    first.close()

    intact = path.read_bytes()
    partial = first.read_all()[-1].model_dump_json().encode()[:40]
    assert not partial.endswith(b"\n"), "the fixture must write an incomplete line"
    path.write_bytes(intact + partial)

    reopened = TaskLedger(path)
    assert len(reopened) == 3
    assert reopened.torn_tail_bytes == len(partial)
    assert [entry.id for entry in reopened.read_all()] == ["t-000", "t-001", "t-002"]
    assert path.read_bytes() == intact, "the torn bytes are truncated away"
    reopened.close()


def test_an_intact_ledger_reports_no_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    written = TaskLedger(path)
    written.append(line("t-000"))
    written.close()
    assert TaskLedger(path).torn_tail_bytes == 0


def test_appending_after_a_torn_tail_was_dropped_continues_cleanly(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    first = TaskLedger(path)
    first.append(line("t-000"))
    first.close()
    path.write_bytes(path.read_bytes() + b'{"id": "t-001", "spec_pa')

    reopened = TaskLedger(path)
    assert len(reopened) == 1
    reopened.append(line("t-001"))
    reopened.close()

    assert [entry.id for entry in TaskLedger(path).read_all()] == ["t-000", "t-001"]
