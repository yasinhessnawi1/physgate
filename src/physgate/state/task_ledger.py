"""The task ledger: one append-only line per dispatched subtask.

This is not the graph's journal. The graph keeps its own append-only file, which
is the authority its node files are derived from; this one records what the
orchestrator dispatched. They are different files with different shapes and
different readers, and the only thing they share is that neither ever rewrites a
line. See ``README.md`` in this directory.

Append-only is structural rather than promised: this class offers no update and
no delete, and the only write it has appends a line and flushes it to disk
before returning. A skipped subtask is visible as a missing id, which is why
``find`` returns ``None`` rather than raising — an absent id is an answer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from physgate.state.exceptions import CorruptRecordError

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

#: A gate or review result is one of these, or absent because it has not run.
Outcome = Literal["pass", "fail", "skipped"]

#: What to do about a complete line that is not a valid record.
OnCorrupt = Literal["raise", "truncate"]


def _first_validation_problem(exc: ValidationError) -> str:
    """The first thing wrong with a record, as a sentence rather than a report."""
    problems = exc.errors()
    if not problems:
        return "the line is not a valid record"
    first = problems[0]
    where = ".".join(str(part) for part in first["loc"]) or "the record"
    return f"{where}: {first['msg']}"


class TaskLine(BaseModel):
    """One dispatched subtask, as the architecture's task ledger records it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: NonEmptyStr
    spec_path: NonEmptyStr
    assigned_role: NonEmptyStr
    attempt_count: Annotated[int, Field(ge=0)]
    gate_result: Outcome | None = None
    review_result: Outcome | None = None
    merge_commit: str | None = None


class TaskLedger:
    """An append-only JSONL ledger of dispatched subtasks.

    Opening reads the file once and reports a torn final line rather than
    silently counting it. There is no update and no delete.

    **Reads answer from memory, and that is deliberate.** Unlike the graph store,
    which re-reads its files and refuses to answer when they have moved, this
    class holds every parsed line for the life of the handle and answers from
    that list. The ledger has one writer by architecture — the orchestrator —
    so a process-lifetime view is the right shape, and a second reader opens its
    own handle and gets its own view as of its own open. What it is not is a
    durable-record read in the sense the graph store means: a handle held open
    while something else appends will not see those lines. The graph store gets
    a staleness detector because concurrent writers there corrupt the record;
    here there is one writer and nothing to corrupt.
    """

    def __init__(self, path: Path, *, on_corrupt: OnCorrupt = "raise") -> None:
        """Open the ledger at ``path``, creating it if it does not exist.

        Args:
            path: the ledger file.
            on_corrupt: what to do about a complete line that is not a valid
                record. ``"raise"`` refuses to open and names the offset;
                ``"truncate"`` drops that line and everything after it. The
                default refuses, because a complete line that does not validate
                was written by something that is not this class.
        """
        self.path = Path(path)
        self._on_corrupt = on_corrupt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._torn_tail_bytes = 0
        self._corrupt_tail_bytes = 0
        self._lines: list[TaskLine] = []
        self._by_id: dict[str, int] = {}
        # Bound before recovery for the same reason the store's is: recovery can
        # refuse to open, and a caller closing in a finally block should see that
        # error rather than an attribute that was never assigned.
        self._handle = self.path.open("ab")
        try:
            self.recover()
        except Exception:
            self._handle.close()
            raise
        self._handle.seek(0, os.SEEK_END)

    def recover(self) -> None:
        """Read the file, dropping and reporting an incomplete final line.

        A process killed between writing a line and flushing it leaves a partial
        line. It is truncated away rather than parsed, because a half-written
        subtask record is not a subtask record.

        A **complete** line that does not validate is a different thing and is
        not treated as a tail: something wrote a record this class could not
        have written, and dropping it silently would discard every valid line
        after it too.

        Raises:
            CorruptRecordError: a complete line is not a valid record and the
                handle was opened with the default policy.
        """
        self._lines = []
        self._by_id = {}
        good_end = 0
        corrupt: tuple[int, str] | None = None
        with self.path.open("rb") as handle:
            for raw in handle:
                if not raw.endswith(b"\n"):
                    break
                try:
                    line = TaskLine.model_validate_json(raw)
                except ValidationError as exc:
                    corrupt = (good_end, _first_validation_problem(exc))
                    break
                self._by_id[line.id] = len(self._lines)
                self._lines.append(line)
                good_end += len(raw)
        size = self.path.stat().st_size
        if corrupt is not None and self._on_corrupt == "raise":
            offset, reason = corrupt
            msg = "the ledger holds a record this class could not have written"
            raise CorruptRecordError(msg, ledger=str(self.path), offset=str(offset), reason=reason)
        dropped = size - good_end
        if corrupt is not None:
            self._corrupt_tail_bytes = dropped
            self._torn_tail_bytes = 0
        else:
            self._torn_tail_bytes = dropped
            self._corrupt_tail_bytes = 0
        if dropped:
            with self.path.open("r+b") as handle:
                handle.truncate(good_end)

    @property
    def torn_tail_bytes(self) -> int:
        """Bytes dropped because the final line had no terminator. Zero if none."""
        return self._torn_tail_bytes

    @property
    def corrupt_tail_bytes(self) -> int:
        """Bytes dropped from a corrupt record onwards. Zero if none."""
        return self._corrupt_tail_bytes

    def append(self, line: TaskLine) -> None:
        """Append ``line`` and flush it to disk before returning."""
        payload = line.model_dump_json(exclude_none=False).encode() + b"\n"
        self._handle.write(payload)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._by_id[line.id] = len(self._lines)
        self._lines.append(line)

    def read_all(self) -> list[TaskLine]:
        """Every line this handle has seen, in the order it was appended.

        As of this handle's open, plus whatever it has appended since. See the
        class docstring: this is a process-lifetime view by design, not a
        durable-record read.
        """
        return list(self._lines)

    def tail(self, count: int = 1) -> list[TaskLine]:
        """The last ``count`` lines, oldest first."""
        if count <= 0:
            return []
        return list(self._lines[-count:])

    def find(self, task_id: str) -> TaskLine | None:
        """The most recent line with ``task_id``, or ``None`` if there is none.

        ``None`` rather than a raise: a skipped subtask is meant to be visible as
        a missing id, so an absent id is an answer and not an error.
        """
        index = self._by_id.get(task_id)
        return None if index is None else self._lines[index]

    def __len__(self) -> int:
        """How many lines the ledger holds."""
        return len(self._lines)

    def close(self) -> None:
        """Release the file handle. Idempotent."""
        if not self._handle.closed:
            self._handle.close()
