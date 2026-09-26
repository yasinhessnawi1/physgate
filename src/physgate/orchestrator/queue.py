"""The approval queue: what a person decides, with what they need to decide it.

One append-only file per run. An item carries the five things ARCH-130 names:
the decision required, the artefact diff, the finding that triggered it, the
most relevant quantities (at most three), and a link to every trajectory
involved. A person's decision is a second line that names the item; nothing is
ever edited, so the file says what was asked, what was decided, and when.

The item's wording is a template filled by code. The queue is where a model
would be most tempting, since it is prose for a person, and there is none.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from physgate.orchestrator.budget import REPAIR_BUDGET
from physgate.orchestrator.common import NonEmptyStr, Timestamp, utc_now, utc_stamp
from physgate.orchestrator.events import read_jsonl
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.protocols import QuantityRef
from physgate.orchestrator.repair import Finding

#: The queue's three sources (ARCH-130).
QueueSource = Literal["gate_escalation", "repair_budget_exhausted", "arbitration"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_id: NonEmptyStr
    ts: Timestamp


class QueueItem(_Record):
    """One decision a person has to take."""

    kind: Literal["item"] = "item"
    run_id: NonEmptyStr
    subtask_id: NonEmptyStr
    source: QueueSource
    decision_required: NonEmptyStr
    artefact_diff: str
    triggering_finding: NonEmptyStr
    quantities: Annotated[tuple[QuantityRef, ...], Field(max_length=3)]
    trajectories: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class QueueResolution(_Record):
    """A person's decision on one item."""

    kind: Literal["resolution"] = "resolution"
    decision: NonEmptyStr
    resolved_by: NonEmptyStr


_RECORD: TypeAdapter[QueueItem | QueueResolution] = TypeAdapter(
    Annotated[QueueItem | QueueResolution, Field(discriminator="kind")]
)


def escalation_item(
    *,
    item_id: str,
    run_id: str,
    subtask_id: str,
    findings: tuple[Finding, ...],
    artefact_diff: str,
    trajectories: tuple[str, ...],
    ts: str,
) -> QueueItem:
    """The item for a subtask whose every attempt was rejected.

    The triggering finding is the last one. The quantities are the last
    finding's that has any, because the most recent evidence is the most
    relevant.

    Raises:
        QueueError: fewer findings or trajectories than attempts were given.
    """
    if len(findings) != REPAIR_BUDGET or len(trajectories) != REPAIR_BUDGET:
        msg = "an exhausted budget is escalated with every attempt's finding and trajectory"
        raise QueueError(msg, findings=str(len(findings)), trajectories=str(len(trajectories)))
    with_quantities = [f for f in findings if f.quantities]
    return QueueItem(
        item_id=item_id,
        ts=ts,
        run_id=run_id,
        subtask_id=subtask_id,
        source="repair_budget_exhausted",
        decision_required=(
            f"Subtask {subtask_id} was rejected on all {REPAIR_BUDGET} attempts. Decide whether "
            "to accept the last attempt as it stands, rewrite the subtask's specification, or "
            "split the subtask."
        ),
        artefact_diff=artefact_diff,
        triggering_finding=findings[-1].text,
        quantities=with_quantities[-1].quantities if with_quantities else (),
        trajectories=trajectories,
    )


class ApprovalQueue:
    """The one writer of a run's approval queue."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Open or create the queue at ``path``.

        Raises:
            QueueError: a complete line is not a record, or does not follow from the
                lines before it (an item listed twice, a decision on no open item).
        """
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._items: dict[str, QueueItem] = {}
        self._resolved: dict[str, QueueResolution] = {}
        records, good_end, corrupt = read_jsonl(self.path, self._admit_line)
        if corrupt is not None:
            offset, reason = corrupt
            msg = "the approval queue holds a line this package could not have written"
            raise QueueError(msg, queue=str(self.path), offset=str(offset), reason=reason)
        if self.path.stat().st_size != good_end:
            with self.path.open("r+b") as handle:
                handle.truncate(good_end)

    def _admit_line(self, raw: bytes) -> QueueItem | QueueResolution:
        record = _RECORD.validate_json(raw)
        self._check(record)
        self._record(record)
        return record

    def _check(self, record: QueueItem | QueueResolution) -> None:
        """Raise ``ValueError`` unless ``record`` may be the next line."""
        if isinstance(record, QueueItem):
            if record.item_id in self._items:
                msg = f"item {record.item_id!r} listed twice"
                raise ValueError(msg)
        elif record.item_id not in self._items or record.item_id in self._resolved:
            msg = f"a decision on {record.item_id!r}, which is not an open item"
            raise ValueError(msg)

    def _record(self, record: QueueItem | QueueResolution) -> None:
        if isinstance(record, QueueItem):
            self._items[record.item_id] = record
        else:
            self._resolved[record.item_id] = record

    def _append(self, record: QueueItem | QueueResolution) -> None:
        try:
            self._check(record)
        except ValueError as exc:
            raise QueueError(str(exc), queue=str(self.path)) from None
        with self.path.open("ab") as handle:
            handle.write(record.model_dump_json().encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._record(record)

    def add(self, item: QueueItem) -> None:
        """List ``item``, synced before returning."""
        self._append(item)

    def resolve(self, item_id: str, *, decision: str, resolved_by: str) -> QueueResolution:
        """Record a person's decision on an open item."""
        record = QueueResolution(
            item_id=item_id,
            ts=utc_stamp(self._clock()),
            decision=decision,
            resolved_by=resolved_by,
        )
        self._append(record)
        return record

    def open_items(self) -> list[QueueItem]:
        """Items no decision has been recorded for, oldest first."""
        return [i for k, i in self._items.items() if k not in self._resolved]

    def items(self) -> list[QueueItem]:
        """Every item, oldest first."""
        return list(self._items.values())
