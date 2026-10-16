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

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
