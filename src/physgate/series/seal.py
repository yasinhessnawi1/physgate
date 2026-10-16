"""What a session's end records about its series: each sealed record, and what was set aside.

These shapes ride on the session's end line in the run's event log, so they import nothing
heavier than pydantic: the event log is read by every command, and the record format itself
loads the unit registry.

A sealed record is named by its id and held by its digest and length, the way a trajectory
is; with it go the script that produced it, by its path in the worktree, the digest of the
script's bytes, and the git blob id those bytes have in the run's repository, so the change
check can confirm that the script the record names is the one the attempt committed.

What the collector did not seal is listed too, never dropped in silence: a file refused
(not a record, or a record whose provenance does not hold) with its reason, and a file
discarded (a writer's temporary file, or what an earlier session left in the outbox).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: The marker every record carries. A later shape is a new marker and a new model.
FORMAT = "series.v1"
#: The most bytes one record's file may hold.
MAX_FILE_BYTES = 4 * 1024 * 1024
#: An id, a group, a trace's name and an input's name: lower-case, safe as a file name.
NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
#: The most entries one session's end may list, sealed or set aside.
MAX_ENTRIES = 512

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BlobId = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SealedRecord(_Frozen):
    """One record the session left, as the collector sealed it."""

    record_id: Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
    sha256: Sha256
    length: Annotated[int, Field(ge=0)]
    #: The producing script's path relative to the worktree, its digest, its git blob id.
    script: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    script_sha256: Sha256
    script_blob: BlobId


class SetAside(_Frozen):
    """A file the collector did not seal, by a printable form of its name, and why."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class SessionSeries(_Frozen):
    """Everything one session left in its outbox: sealed, refused or discarded."""

    records: Annotated[tuple[SealedRecord, ...], Field(max_length=MAX_ENTRIES)] = ()
    refused: Annotated[tuple[SetAside, ...], Field(max_length=MAX_ENTRIES)] = ()
    discarded: Annotated[tuple[SetAside, ...], Field(max_length=MAX_ENTRIES)] = ()


class SeriesCheck(_Frozen):
    """One graph quantity held to the record it names: what it declares, what the record gives.

    Recorded for every quantity that names a record, passes included, on the change check's
    line of the run's event log. ``outcome`` is ``agrees`` within the frozen tolerance,
    ``differs`` beyond it, or ``unreadable`` when the value cannot be read off the record (no
    such record in the attempt, a trace missing, a unit of another kind); the last two refuse
    the attempt.
    """

    node_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    quantity: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    record_id: Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
    extract: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    trace: Annotated[str, StringConstraints(pattern=NAME_PATTERN)] | None = None
    #: The session that sealed the record read, when one did.
    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")] | None = None
    declared_value: float | int
    declared_unit: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    read_value: float | None = None
    read_unit: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    outcome: Literal["agrees", "differs", "unreadable"]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None


class AttemptRecord(_Frozen):
    """One record an attempt sealed, and the session whose end sealed it."""

    session_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
    record: SealedRecord


class AttemptSeries(_Frozen):
    """What a review is told about an attempt's simulation records.

    The records the attempt's sessions sealed (a later session's superseding an earlier one's
    of the same id), the run directory they lie under, and the result of holding each graph
    quantity that names one to it. It travels on the attempt as the gate and the reviewer
    receive it, and so reaches the review packet of both review arms by one route.
    """

    run_dir: Annotated[str, StringConstraints(min_length=1)]
    subtask_id: Annotated[str, StringConstraints(min_length=1)]
    attempt: Annotated[int, Field(ge=1)]
    records: tuple[AttemptRecord, ...] = ()
    checks: tuple[SeriesCheck, ...] = ()
